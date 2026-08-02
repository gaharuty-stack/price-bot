import logging
import os
import time
import uuid
from datetime import datetime

from cachetools import TTLCache
from flask import Flask, jsonify, make_response, request

from agent_format import build_agent_brief, build_preview_brief, enrich_compare_with_relative
from config import COINS, MAX_COMPARE_COINS, PAYMENT, PREVIEW_RATE_LIMIT_PER_MINUTE, RATE_LIMIT_PER_MINUTE, SERVICE_URL, VERSION
from db import check_rate_limit, get_stats, init_db, log_request
from integrity import sign_data
from market_data import get_coin_data, get_last_snapshot_at, get_market_snapshot, get_trending, resolve_coin_id, start_price_updater
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
        "ohlc": market.get("ohlc") or [],
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

        data = build_agent_brief(result) if agent_format else {
            k: v for k, v in result.items() if k not in ("ohlc", "closes")
        }
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

    results, errors, raw_rows = [], [], []
    for q in queries:
        if not resolve_coin_id(q):
            errors.append(q)
            continue
        try:
            row = build_coin_response(q)
            raw_rows.append(row)
            results.append(build_agent_brief(row) if agent_format else {
                k: v for k, v in row.items() if k not in ("ohlc", "closes")
            })
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

    btc_change = None
    btc_row = get_market_snapshot("bitcoin")
    if btc_row:
        try:
            btc_change = float(btc_row.get("usd_24h_change", 0) or 0)
        except (TypeError, ValueError):
            btc_change = None
    briefs = [build_agent_brief(r) for r in raw_rows]
    rel = enrich_compare_with_relative(briefs, btc_change)

    summary = {
        "best_performer": best_key,
        "worst_performer": worst_key,
        "best_edge": rel.get("best_edge"),
        "best_vs_btc": rel.get("best_vs_btc"),
        "count": len(results),
        "bundle": {
            "coins": len(results),
            "price_usdc": PAYMENT["amount"],
            "note": f"{len(results)} coin briefs in one ${PAYMENT['amount']} call",
        },
    }

    payload = {
        "status": "ok",
        "coins": results,
        "relative_strength": rel.get("relative"),
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


def _paid_guidance(kind: str) -> str:
    if kind == "data":
        return (
            "Use case: get a live BUY/SELL/HOLD trading signal for Bitcoin, Ethereum, or Solana. "
            "Pay once with x402 USDC on Base, then GET /api/data?q=btc. "
            "Default format=agent returns signal, support/resistance levels, regime, risk, "
            "edge_score, invalidation, target and stop. "
            "Free tease (price only): GET /api/preview?q=btc."
        )
    if kind == "compare":
        return (
            "Use case: rank BTC vs ETH vs SOL in one call for an AI trading agent. "
            "Best value: compare 2–5 coins in one payment — GET /api/compare?coins=btc,eth,sol. "
            "Returns per-coin agent packs + vs-BTC relative strength + best/worst 24h."
        )
    return (
        "Use case: find which cryptocurrencies are pumping or dumping today. "
        "GET /api/trending?limit=5 after x402 payment for top gainers/losers among supported coins."
    )


def _paid_402():
    return {"402": {"description": "Payment Required — settle x402 USDC on Base, then retry with PAYMENT-SIGNATURE or X-PAYMENT"}}


def _openapi_components():
    return {
        "securitySchemes": {
            "x402": {
                "type": "apiKey",
                "in": "header",
                "name": "PAYMENT-SIGNATURE",
                "description": (
                    "x402 v2 payment proof (also accepts X-PAYMENT). "
                    "Pay an offer from the HTTP 402 response body/accepts, then retry."
                ),
            }
        }
    }


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
            "edge_score": {"type": "integer"},
            "regime": {"type": "string", "enum": ["calm", "normal", "volatile"]},
            "risk": {"type": "string", "enum": ["low", "medium", "high"]},
            "levels": {
                "type": "object",
                "properties": {
                    "support": {"type": "number"},
                    "resistance": {"type": "number"},
                    "window_days": {"type": "integer"},
                },
            },
            "reason": {"type": "string"},
            "action_hint": {"type": "string"},
            "invalidation": {"type": "string"},
            "target_price": {"type": "number"},
            "stop_loss": {"type": "number"},
        },
    }
    # security: [] => free; security: [{x402: []}] => AgentCash authMode "paid"
    free_security = []
    paid_security = [{"x402": []}]
    return {
        "/health": {
            "get": {
                "operationId": "health",
                "summary": "Service health and paid_request counters (free)",
                "tags": ["Meta"],
                "security": free_security,
                "responses": {"200": {"description": "Health JSON"}},
            }
        },
        "/llms.txt": {
            "get": {
                "operationId": "llmsTxt",
                "summary": "Plain-text agent docs (free)",
                "tags": ["Meta"],
                "security": free_security,
                "responses": {"200": {"description": "llms.txt"}},
            }
        },
        "/openapi.json": {
            "get": {
                "operationId": "openapi",
                "summary": "OpenAPI 3.1 spec with x-payment-info (free)",
                "tags": ["Meta"],
                "security": free_security,
                "responses": {"200": {"description": "OpenAPI document"}},
            }
        },
        "/api/data": {
            "get": {
                "operationId": "getCoinBrief",
                "summary": (
                    "Live crypto BUY/SELL/HOLD trading signal with support/resistance, "
                    "regime, risk and invalidation — LLM-ready agent pack (x402)"
                ),
                "description": (
                    "Pay-per-call crypto intelligence for AI trading agents. "
                    "Returns USD price, 24h change, BUY/SELL/HOLD signal, confidence, "
                    "edge_score, RSI/MACD/Bollinger-derived reason, support and resistance "
                    "levels, volatility regime, risk, invalidation line, target_price and "
                    "stop_loss for one coin (btc, eth, sol, bitcoin, ethereum, and 40+ others). "
                    "Use when you need an actionable directional signal, not a raw price dump. "
                    "Default format=agent. Settle HTTP 402 with USDC on Base via x402, then retry."
                ),
                "tags": ["Trading", "Crypto", "Signals"],
                "security": paid_security,
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
                "x-guidance": _paid_guidance("data"),
                "x402": legacy_x402,
            }
        },
        "/api/compare": {
            "get": {
                "operationId": "compareCoins",
                "summary": (
                    "Compare Bitcoin vs Ethereum vs Solana (2–5 coins) — "
                    "BUY/SELL/HOLD briefs + vs-BTC relative strength in one payment"
                ),
                "description": (
                    "Best-value paid call for portfolio ranking agents. Compare 2–5 "
                    "cryptocurrencies (example: coins=btc,eth,sol) in a single x402 payment. "
                    "Returns per-coin price + BUY/SELL/HOLD agent packs, best/worst 24h "
                    "performers, and vs-BTC relative strength so an agent can pick the "
                    "strongest coin without multiple requests."
                ),
                "tags": ["Trading", "Crypto", "Compare"],
                "security": paid_security,
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
                "x-guidance": _paid_guidance("compare"),
                "x402": legacy_x402,
            }
        },
        "/api/trending": {
            "get": {
                "operationId": "getTrending",
                "summary": (
                    "Top crypto gainers and losers last 24h — "
                    "momentum scan for AI trading agents (x402)"
                ),
                "description": (
                    "Lists top gainers and losers among supported coins by 24h percent change. "
                    "Use when an agent needs market movers, a momentum scan, or what is "
                    "pumping/dumping today before picking a coin for /api/data."
                ),
                "tags": ["Search", "Crypto", "Trending"],
                "security": paid_security,
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
                "x-guidance": _paid_guidance("trending"),
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
                "summary": "Free crypto spot price + 24h change tease (signal locked behind x402)",
                "description": (
                    "Free tease for AI agents: current USD price and 24h change only. "
                    "BUY/SELL/HOLD signal, levels, regime, risk and invalidation stay locked — "
                    "upgrade to GET /api/data (or best-value /api/compare) after x402 payment."
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
                "responses": {"200": {"description": "Price tease with upgrade hint to paid agent pack"}},
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
            "x402 pay-per-call crypto trading intelligence for AI agents. "
            "Get live Bitcoin/ETH/SOL BUY/SELL/HOLD signals with support/resistance, "
            "volatility regime, risk, edge_score and invalidation — not raw CoinGecko dumps. "
            f"Price: {PAYMENT['amount']} USDC on Base per call. "
            "Best value: compare up to 5 coins + vs-BTC strength in one payment. "
            "Free routes use security: []. Paid routes require x402 (PAYMENT-SIGNATURE / X-PAYMENT) "
            "after HTTP 402. Free tease: GET /api/preview?q=btc (price only). "
            "Docs: /llms.txt."
        ),
        "x-guidance": (
            "Workflow for AI agents: (1) Free tease GET /api/preview?q=btc for spot+24h. "
            "(2) Pay x402 then GET /api/data?q=btc for full BUY/SELL/HOLD agent pack "
            "(signal, S/R levels, regime, risk, edge_score, invalidation, target/stop). "
            f"(3) Best value: GET /api/compare?coins=btc,eth,sol for multiple briefs + vs-BTC "
            f"relative strength in one {PAYMENT['amount']} USDC payment. "
            "(4) Momentum: GET /api/trending. Read /llms.txt."
        ),
        "x402": PAYMENT,
        "contact": {
            "url": os.environ.get(
                "CONTACT_URL",
                "https://github.com/gaharuty-stack/price-bot",
            ).strip(),
        },
    }
    # Default contact email so AgentCash ownership stays visible even if Railway env drifts.
    contact_email = os.environ.get("CONTACT_EMAIL", "gaharuty@gmail.com").strip()
    if contact_email:
        info["contact"]["email"] = contact_email

    return jsonify({
        "openapi": "3.1.0",
        "info": info,
        "servers": [{"url": SERVICE_URL}],
        "tags": [
            {"name": "Trading", "description": "BUY/SELL/HOLD crypto signals for agents"},
            {"name": "Crypto", "description": "Bitcoin, Ethereum, Solana and 40+ coins"},
            {"name": "Signals", "description": "Technical analysis agent packs"},
            {"name": "Compare", "description": "Multi-coin ranking + vs-BTC strength"},
            {"name": "Search", "description": "Coin list, preview, trending movers"},
            {"name": "Meta", "description": "Health, OpenAPI, llms.txt"},
        ],
        "components": _openapi_components(),
        "paths": _openapi_paths(),
    })


@app.route("/.well-known/mcp.json", methods=["GET"])
def mcp_discovery():
    return jsonify({
        "name": "Crypto Agent Brief API",
        "version": VERSION,
        "description": (
            "x402 crypto BUY/SELL/HOLD agent packs for Bitcoin/ETH/SOL. "
            "Free /api/preview is price-only; pay for signal, S/R, regime, risk, invalidation."
        ),
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

> x402 crypto trading intelligence for AI agents — not raw CoinGecko dumps.
> One paid call: BUY/SELL/HOLD + support/resistance + regime + risk + invalidation.

## Why this vs others
- Most APIs sell price only or expensive essays
- We sell a compact **agent pack** agents can act on
- Compare up to 5 coins in **one** ${PAYMENT['amount']} payment (best value)
- Free preview is price-only (signal locked) so you know what you buy

## Endpoints
- Free price tease → GET /api/preview?q=btc
- Full agent pack → GET /api/data?q=btc
- Multi-coin + vs-BTC strength → GET /api/compare?coins=btc,eth,sol
- Gainers/losers → GET /api/trending

## Agent pack fields (paid)
coin, price_usd, signal, confidence, edge_score, regime, risk,
levels.support, levels.resistance, reason, action_hint, invalidation,
target_price, stop_loss

## Pricing
- Free: /api/preview (price+24h only), /api/coins, /llms.txt
- Paid: {PAYMENT['amount']} USDC on Base (x402) per /api/data|/api/compare|/api/trending
- Pay HTTP 402 with PAYMENT-SIGNATURE or X-PAYMENT, then retry

## Base URL
{SERVICE_URL}
"""
    return make_response(text, 200, {"Content-Type": "text/plain; charset=utf-8"})


@app.route("/robots.txt", methods=["GET"])
def robots_txt():
    return make_response(
        (
            "User-agent: *\n"
            "Allow: /\n"
            "Allow: /llms.txt\n"
            "Allow: /ai.txt\n"
            "Allow: /openapi.json\n"
            "Allow: /.well-known/\n"
            "Allow: /api/preview\n"
            "Allow: /api/coins\n"
            f"\nSitemap: {SERVICE_URL}/openapi.json\n"
        ),
        200,
        {"Content-Type": "text/plain"},
    )


@app.route("/", methods=["GET"])
def root():
    return jsonify({
        "service": "Crypto Agent Brief API",
        "version": VERSION,
        "status": "ok",
        "tagline": "x402 BUY/SELL/HOLD agent packs — signal locked behind payment",
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
