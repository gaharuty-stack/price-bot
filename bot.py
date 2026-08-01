import logging
import os
import time
import uuid
from datetime import datetime

from cachetools import TTLCache
from flask import Flask, jsonify, make_response, request

from agent_format import build_agent_brief, build_preview_brief
from config import COINS, MAX_COMPARE_COINS, PAYMENT, PREVIEW_RATE_LIMIT_PER_MINUTE, RATE_LIMIT_PER_MINUTE, SERVICE_URL, VERSION
from db import check_rate_limit, get_stats, init_db, log_request
from integrity import sign_data
from market_data import get_coin_data, get_last_snapshot_at, get_trending, resolve_coin_id, start_price_updater
from signals import generate_signal

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
start_time = datetime.utcnow()
response_cache = TTLCache(maxsize=500, ttl=int(os.environ.get("CACHE_TTL_SECONDS", "60")))
_request_times: list[float] = []

init_db()
start_price_updater()


@app.after_request
def _log_traffic(response):
    """Count free + paid hits so /health matches Railway traffic."""
    try:
        path = request.path or ""
        if path.startswith("/admin"):
            return response
        ip = _client_ip()
        paid = payment_was_settled(request) and response.status_code == 200
        q = request.args.get("q") or request.args.get("coins") or path
        # Avoid double-count on paid handlers that already log.
        if path in ("/api/data", "/api/compare", "/api/trending") and response.status_code == 200:
            return response
        log_request(str(q)[:120], ip, response.status_code, paid=paid)
    except Exception:
        logger.exception("traffic log failed")
    return response


@app.errorhandler(Exception)
def _unhandled(exc):
    logger.exception("Unhandled error: %s", exc)
    return jsonify({"error": "internal_error", "message": "temporary failure, retry"}), 503


def payment_was_settled(req) -> bool:
    """True when client presented an x402 payment proof on the request.

    Settlement response headers are added by the gateway on the way *out*.
    Flask only sees inbound proof headers (PAYMENT-SIGNATURE / X-PAYMENT).
    """
    for header in (
        "PAYMENT-SIGNATURE",
        "Payment-Signature",
        "X-PAYMENT",
        "X-Payment",
        "PAYMENT-RESPONSE",
        "Payment-Response",
        "X-PAYMENT-RESPONSE",
        "X-Payment-Response",
        "X-Payment-Tx-Hash",
    ):
        if req.headers.get(header):
            return True
    return False


def _client_ip() -> str:
    return request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()


def _track_response(start: float) -> None:
    _request_times.append((time.perf_counter() - start) * 1000)
    if len(_request_times) > 200:
        del _request_times[:100]


def build_coin_response(query: str) -> dict:
    market = get_coin_data(query)
    if not market:
        raise ValueError(f"Unknown coin: {query}")

    signal_data = generate_signal(
        price=market["price_usd"],
        change_24h=market["change_24h_percent"],
        volume=market["volume_24h"],
        closes=market["closes"],
        ohlc=market["ohlc"],
    )

    return {
        "coin_id": market["coin_id"],
        "ticker": market["ticker"],
        "name": market["name"],
        "price_usd": market["price_usd"],
        "change_24h_percent": market["change_24h_percent"],
        "volume_24h": market["volume_24h"],
        "market_cap_usd": market["market_cap_usd"],
        "signal": signal_data["signal"],
        "confidence": signal_data["confidence"],
        "target_price": signal_data["target_price"],
        "stop_loss": signal_data["stop_loss"],
        "indicators": {
            "rsi": signal_data["rsi"],
            "macd": signal_data["macd"],
            "bollinger": signal_data["bollinger"],
            "stochastic": signal_data["stochastic"],
            "atr": signal_data["atr"],
        },
        "methodology": signal_data["methodology"],
        "disclaimer": signal_data["disclaimer"],
        "data_source": market["data_source"],
        "snapshot_at": market["snapshot_at"],
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


def signed_payload(payload: dict) -> dict:
    signed = payload.copy()
    signed["integrity"] = {
        "signature": sign_data(payload),
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }
    return signed


def _paid_guard(endpoint: str):
    request_id = str(uuid.uuid4())[:8]
    ip = _client_ip()
    paid = payment_was_settled(request)
    if not check_rate_limit(ip, RATE_LIMIT_PER_MINUTE):
        log_request(endpoint, ip, 429, request_id, paid)
        return None, (jsonify({"error": "rate_limit_exceeded", "retry_after_seconds": 60}), 429)
    return (request_id, ip, paid), None


@app.route("/health", methods=["GET"])
def health():
    stats = get_stats()
    avg_ms = round(sum(_request_times) / len(_request_times), 1) if _request_times else None
    return jsonify({
        "status": "ok",
        "version": VERSION,
        "uptime_seconds": int((datetime.utcnow() - start_time).total_seconds()),
        "coins_supported": len(set(COINS.values())),
        "total_requests": stats.get("total_requests", 0),
        "paid_requests": stats.get("paid_requests", 0),
        "avg_response_ms": avg_ms,
        "last_price_update": get_last_snapshot_at(),
        "data_source": "coingecko",
    })


@app.route("/api/coins", methods=["GET"])
def list_coins():
    unique = sorted(set(COINS.values()))
    aliases = {}
    for alias, coin_id in COINS.items():
        aliases.setdefault(coin_id, []).append(alias)
    return jsonify({
        "count": len(unique),
        "coins": [{"id": c, "aliases": sorted(set(aliases.get(c, [c])))} for c in unique],
    })


@app.route("/api/preview", methods=["GET"])
def preview_data():
    started = time.perf_counter()
    ip = _client_ip()
    if not check_rate_limit(f"preview:{ip}", PREVIEW_RATE_LIMIT_PER_MINUTE):
        return jsonify({"error": "rate_limit_exceeded", "retry_after_seconds": 60}), 429

    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({"error": "missing_parameter", "message": "Use ?q=btc"}), 400
    if not resolve_coin_id(query):
        return jsonify({"error": "unknown_coin", "message": f"Unsupported coin: {query}"}), 404

    cache_key = f"preview:{query.lower()}"
    if cache_key not in response_cache:
        try:
            result = build_coin_response(query)
        except ValueError as exc:
            return jsonify({"error": "unknown_coin", "message": str(exc)}), 404
        except Exception as exc:
            logger.exception("Preview failed for %s", query)
            return jsonify({"error": "upstream_unavailable", "message": str(exc)}), 503

        response_cache[cache_key] = build_preview_brief(
            result, query, SERVICE_URL, PAYMENT["amount"]
        )

    _track_response(started)
    return jsonify(response_cache[cache_key])


@app.route("/api/data", methods=["GET"])
def get_data():
    started = time.perf_counter()
    guard, err = _paid_guard("data")
    if err:
        return err
    request_id, ip, paid = guard

    query = request.args.get("q", "").strip()
    # Default to agent brief — paid callers expect LLM-ready, not a huge dump.
    fmt = (request.args.get("format") or "agent").strip().lower()
    agent_format = fmt != "full"

    if not query:
        return jsonify({"error": "missing_parameter", "message": "Use ?q=bitcoin"}), 400
    if not resolve_coin_id(query):
        return jsonify({"error": "unknown_coin", "message": f"Unsupported coin: {query}"}), 404

    cache_key = f"data:{query.lower()}:{'agent' if agent_format else 'full'}"
    if cache_key not in response_cache:
        try:
            result = build_coin_response(query)
        except ValueError as exc:
            return jsonify({"error": "unknown_coin", "message": str(exc)}), 404
        except Exception as exc:
            logger.exception("Failed for %s", query)
            return jsonify({"error": "upstream_unavailable", "message": str(exc)}), 503

        data = build_agent_brief(result) if agent_format else result
        response_cache[cache_key] = {"status": "ok", "query": query, "data": data, "format": "agent" if agent_format else "full"}

    payload = {**response_cache[cache_key], "payment": PAYMENT, "paid_request": paid}
    log_request(query, ip, 200, request_id, paid)
    _track_response(started)
    resp = make_response(jsonify(signed_payload(payload)), 200)
    resp.headers["X-Request-ID"] = request_id
    return resp


@app.route("/api/compare", methods=["GET"])
def compare_coins():
    started = time.perf_counter()
    guard, err = _paid_guard("compare")
    if err:
        return err
    request_id, ip, paid = guard

    raw = request.args.get("coins", "").strip()
    fmt = (request.args.get("format") or "agent").strip().lower()
    agent_format = fmt != "full"
    if not raw:
        return jsonify({"error": "missing_parameter", "message": "Use ?coins=btc,eth,sol"}), 400

    queries = [q.strip() for q in raw.split(",") if q.strip()][:MAX_COMPARE_COINS]
    if len(queries) < 2:
        return jsonify({"error": "invalid_parameter", "message": "Provide at least 2 coins"}), 400

    results, errors = [], []
    for q in queries:
        if not resolve_coin_id(q):
            errors.append(q)
            continue
        try:
            row = build_coin_response(q)
            results.append(build_agent_brief(row) if agent_format else row)
        except Exception:
            errors.append(q)

    if len(results) < 2:
        return jsonify({"error": "unknown_coin", "message": f"Could not load coins: {errors}"}), 404

    def _change(row: dict) -> float:
        if "change_24h_percent" in row:
            return row["change_24h_percent"]
        return float(str(row.get("change_24h", "0")).replace("%", "").replace("+", ""))

    best = max(results, key=_change)
    worst = min(results, key=_change)
    best_key = best.get("ticker") or best.get("coin_id") or best.get("coin")
    worst_key = worst.get("ticker") or worst.get("coin_id") or worst.get("coin")

    summary = {
        "best_performer": best_key,
        "worst_performer": worst_key,
        "count": len(results),
    }

    payload = {
        "status": "ok",
        "coins": results,
        "summary": summary,
        "errors": errors,
        "format": "agent" if agent_format else "full",
        "payment": PAYMENT,
        "paid_request": paid,
    }
    log_request(f"compare:{raw}", ip, 200, request_id, paid)
    _track_response(started)
    return jsonify(signed_payload(payload))


@app.route("/api/trending", methods=["GET"])
def trending():
    started = time.perf_counter()
    guard, err = _paid_guard("trending")
    if err:
        return err
    request_id, ip, paid = guard

    limit = min(request.args.get("limit", 5, type=int), 10)
    data = get_trending(limit)
    if not data.get("gainers") and not data.get("losers"):
        log_request("trending", ip, 503, request_id, paid)
        return jsonify({"error": "upstream_unavailable", "message": "market snapshot empty"}), 503

    payload = {
        "status": "ok",
        "gainers": data["gainers"],
        "losers": data["losers"],
        "summary": f"Top gainer: {data['gainers'][0]['ticker'] if data['gainers'] else 'n/a'}",
        "payment": PAYMENT,
        "paid_request": paid,
    }
    log_request("trending", ip, 200, request_id, paid)
    _track_response(started)
    return jsonify(signed_payload(payload))


@app.route("/admin/stats", methods=["GET"])
def admin_stats():
    token = request.headers.get("X-Admin-Token", "")
    expected = os.environ.get("ADMIN_TOKEN", "")
    if not expected or token != expected:
        return jsonify({"error": "unauthorized"}), 401
    return jsonify(get_stats())


def _payment_info():
    """AgentCash / IETF payment discovery block (decimal USD amount)."""
    # Only x402 — empty mpp fields trigger L2_MPP_MALFORMED in AgentCash audit.
    return {
        "price": {
            "mode": "fixed",
            "currency": "USD",
            "amount": f"{float(PAYMENT['amount']):.6f}",
        },
        "protocols": [{"x402": {}}],
    }


def _paid_402():
    return {"402": {"description": "Payment Required"}}


def _openapi_paths():
    legacy_x402 = {"price": PAYMENT["amount"], "network": PAYMENT["network"]}
    agent_brief_schema = {
        "type": "object",
        "properties": {
            "coin": {"type": "string"},
            "price_usd": {"type": "number"},
            "change_24h": {"type": "string"},
            "signal": {"type": "string", "enum": ["BUY", "SELL", "HOLD"]},
            "confidence": {"type": "number"},
            "reason": {"type": "string"},
            "action_hint": {"type": "string"},
        },
    }
    # security: [] => AgentCash authMode "unprotected"
    free_security = []
    return {
        "/api/data": {
            "get": {
                "operationId": "getCoinBrief",
                "summary": (
                    "Bitcoin/ETH/SOL crypto price + BUY/SELL/HOLD TA signal — "
                    "LLM-ready brief for AI trading agents (x402)"
                ),
                "description": (
                    "Returns current USD price, 24h change, RSI/MACD/Bollinger context, "
                    "BUY/SELL/HOLD signal, confidence, reason, and action_hint for one coin "
                    "(btc, eth, sol, and 40+ others). Optimized for LLM agents. "
                    "Default format=agent. Pay per call with USDC on Base via x402."
                ),
                "tags": ["Trading", "Crypto", "Signals"],
                "parameters": [
                    {
                        "name": "q",
                        "in": "query",
                        "required": True,
                        "description": "Coin ticker or id: btc, eth, sol, bitcoin, ethereum, …",
                        "schema": {"type": "string", "minLength": 1, "example": "btc"},
                    },
                    {
                        "name": "format",
                        "in": "query",
                        "description": "agent = short brief (default); full = verbose JSON",
                        "schema": {"type": "string", "enum": ["agent", "full"], "default": "agent"},
                    },
                ],
                "responses": {
                    "200": {
                        "description": "Coin brief with price and TA signal",
                        "content": {"application/json": {"schema": agent_brief_schema}},
                    },
                    **_paid_402(),
                },
                "x-payment-info": _payment_info(),
                "x402": legacy_x402,
            }
        },
        "/api/compare": {
            "get": {
                "operationId": "compareCoins",
                "summary": (
                    "Compare Bitcoin vs Ethereum vs Solana (2–5 coins) — "
                    "best/worst 24h performer for AI agents"
                ),
                "description": (
                    "Compare 2–5 cryptocurrencies in one paid call. Returns per-coin "
                    "price + TA signal briefs and a summary of best/worst 24h performers. "
                    "Example: coins=btc,eth,sol. Useful for portfolio ranking and agent decisions."
                ),
                "tags": ["Trading", "Crypto", "Compare"],
                "parameters": [
                    {
                        "name": "coins",
                        "in": "query",
                        "required": True,
                        "description": "Comma-separated tickers, e.g. btc,eth,sol",
                        "schema": {"type": "string", "minLength": 3, "example": "btc,eth,sol"},
                    },
                    {
                        "name": "format",
                        "in": "query",
                        "schema": {"type": "string", "enum": ["agent", "full"], "default": "agent"},
                    },
                ],
                "responses": {
                    "200": {"description": "Multi-coin comparison with best/worst summary"},
                    **_paid_402(),
                },
                "x-payment-info": _payment_info(),
                "x402": legacy_x402,
            }
        },
        "/api/trending": {
            "get": {
                "operationId": "getTrending",
                "summary": (
                    "Top crypto gainers and losers last 24h — "
                    "trending movers for AI trading agents"
                ),
                "description": (
                    "Lists top gainers and losers among supported coins by 24h percent change. "
                    "Use when an agent needs market movers, momentum scan, or what is pumping/dumping today."
                ),
                "tags": ["Search", "Crypto", "Trending"],
                "parameters": [
                    {
                        "name": "limit",
                        "in": "query",
                        "schema": {"type": "integer", "default": 5, "minimum": 1, "maximum": 10},
                    }
                ],
                "responses": {
                    "200": {"description": "Trending gainers and losers"},
                    **_paid_402(),
                },
                "x-payment-info": _payment_info(),
                "x402": legacy_x402,
            }
        },
        "/api/coins": {
            "get": {
                "operationId": "listCoins",
                "summary": "List supported crypto coins and tickers (free)",
                "tags": ["Search", "Crypto"],
                "security": free_security,
                "responses": {"200": {"description": "Supported coin ids"}},
            }
        },
        "/api/preview": {
            "get": {
                "operationId": "previewBrief",
                "summary": "Free Bitcoin/ETH crypto price + signal preview (no payment)",
                "description": (
                    "Free taste of the agent brief: price, 24h change, BUY/SELL/HOLD signal and reason. "
                    "No action_hint/targets. Upgrade to /api/data for full brief."
                ),
                "tags": ["Search", "Crypto"],
                "security": free_security,
                "parameters": [
                    {
                        "name": "q",
                        "in": "query",
                        "required": True,
                        "schema": {"type": "string", "minLength": 1, "example": "btc"},
                    },
                ],
                "responses": {"200": {"description": "Preview brief with upgrade hint"}},
            }
        },
    }


@app.route("/favicon.ico", methods=["GET"])
@app.route("/favicon.svg", methods=["GET"])
def favicon():
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
        '<rect width="64" height="64" rx="12" fill="#0f172a"/>'
        '<text x="32" y="42" text-anchor="middle" font-size="28" fill="#22c55e"'
        ' font-family="Arial,sans-serif">$</text></svg>'
    )
    return make_response(svg, 200, {"Content-Type": "image/svg+xml; charset=utf-8"})


@app.route("/openapi.json", methods=["GET"])
@app.route("/.well-known/x402", methods=["GET"])
def openapi_spec():
    info = {
        "title": "Crypto Agent Brief API",
        "version": VERSION,
        "description": (
            "Crypto price + technical analysis (TA) briefs for AI agents: "
            "Bitcoin, Ethereum, Solana and 40+ coins. BUY/SELL/HOLD signals with RSI/MACD. "
            f"Pay-per-call {PAYMENT['amount']} USDC on Base via x402. Free preview available."
        ),
        "x-guidance": (
            "Use this API when you need a crypto price, trading signal, or TA brief for an AI agent. "
            "Free preview: GET /api/preview?q=btc (Bitcoin) or ?q=eth / ?q=sol. "
            "Paid single-coin brief: GET /api/data?q=btc (default format=agent) — returns price, "
            "BUY/SELL/HOLD, reason, action_hint. "
            "Compare coins: GET /api/compare?coins=btc,eth,sol. "
            "Market movers: GET /api/trending for top gainers/losers 24h. "
            f"Each paid call costs {PAYMENT['amount']} USDC on Base (x402). Read /llms.txt first."
        ),
        "x402": PAYMENT,
        "contact": {
            "url": os.environ.get(
                "CONTACT_URL",
                "https://github.com/gaharuty-stack/price-bot",
            ).strip(),
        },
    }
    contact_email = os.environ.get("CONTACT_EMAIL", "").strip()
    if contact_email:
        info["contact"]["email"] = contact_email

    return jsonify({
        "openapi": "3.1.0",
        "info": info,
        "servers": [{"url": SERVICE_URL}],
        "paths": _openapi_paths(),
    })


@app.route("/.well-known/mcp.json", methods=["GET"])
def mcp_discovery():
    return jsonify({
        "name": "Crypto Agent Brief API",
        "version": VERSION,
        "description": "LLM-ready crypto price + TA briefs. Use ?format=agent for concise answers.",
        "x402": PAYMENT,
        "endpoints": [
            {"path": "/api/preview", "method": "GET", "price": "0", "example": f"{SERVICE_URL}/api/preview?q=btc"},
            {"path": "/api/data", "method": "GET", "price": PAYMENT["amount"], "example": f"{SERVICE_URL}/api/data?q=btc&format=agent"},
            {"path": "/api/compare", "method": "GET", "price": PAYMENT["amount"], "example": f"{SERVICE_URL}/api/compare?coins=btc,eth,sol&format=agent"},
            {"path": "/api/trending", "method": "GET", "price": PAYMENT["amount"], "example": f"{SERVICE_URL}/api/trending"},
            {"path": "/api/coins", "method": "GET", "price": "0"},
        ],
    })


@app.route("/llms.txt", methods=["GET"])
@app.route("/ai.txt", methods=["GET"])
def llms_txt():
    text = f"""# Crypto Agent Brief API v{VERSION}

> Crypto price + TA (technical analysis) briefs for AI agents.
> Bitcoin, Ethereum, Solana and 40+ coins. Pay per call via x402 USDC on Base.

## When to use
- Free Bitcoin/ETH preview → GET /api/preview?q=btc
- Need BUY/SELL/HOLD signal + price for one coin → GET /api/data?q=btc
- Compare BTC vs ETH vs SOL → GET /api/compare?coins=btc,eth,sol
- Top crypto gainers/losers today → GET /api/trending

## Keywords agents search for
crypto price, bitcoin price, ethereum signal, solana TA, trading signal,
BUY SELL HOLD, RSI MACD, LLM crypto brief, market movers, compare coins

## Pricing
- Free preview: /api/preview?q=btc — signal + reason (no action_hint)
- Paid: /api/data, /api/compare, /api/trending — {PAYMENT['amount']} USDC each
- Free: /api/coins, /health, /.well-known/x402, /llms.txt

## Base URL
{SERVICE_URL}

## Example
GET {SERVICE_URL}/api/data?q=btc
→ coin, price_usd, signal, reason, action_hint (format=agent by default)

## Discovery
- OpenAPI: {SERVICE_URL}/openapi.json
- x402: {SERVICE_URL}/.well-known/x402
"""
    return make_response(text, 200, {"Content-Type": "text/plain; charset=utf-8"})


@app.route("/robots.txt", methods=["GET"])
def robots_txt():
    return make_response(
        f"User-agent: *\nAllow: /\nAllow: /llms.txt\n\nSitemap: {SERVICE_URL}/openapi.json\n",
        200,
        {"Content-Type": "text/plain"},
    )


@app.route("/", methods=["GET"])
def root():
    return jsonify({
        "service": "Crypto Agent Brief API",
        "version": VERSION,
        "status": "ok",
        "tagline": "LLM-ready crypto briefs — not raw JSON dumps",
        "coins_supported": len(set(COINS.values())),
        "payment": PAYMENT,
        "endpoints": {
            "free": ["/health", "/api/coins", "/api/preview", "/llms.txt", "/.well-known/x402"],
            "paid": ["/api/data", "/api/compare", "/api/trending"],
        },
        "examples": {
            "preview": "/api/preview?q=btc",
            "agent_brief": "/api/data?q=btc&format=agent",
            "compare": "/api/compare?coins=btc,eth,sol&format=agent",
            "trending": "/api/trending",
        },
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
