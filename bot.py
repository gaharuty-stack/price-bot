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


def payment_was_settled(req) -> bool:
    for header in ("X-Payment-Response", "X-PAYMENT-RESPONSE", "Payment-Response", "X-Payment-Tx-Hash"):
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
    agent_format = request.args.get("format", "").lower() == "agent"

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
    agent_format = request.args.get("format", "").lower() == "agent"
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


def _openapi_paths():
    price = {"price": PAYMENT["amount"], "network": PAYMENT["network"]}
    paid = {"402": {"description": "Payment required via x402"}}
    return {
        "/api/data": {
            "get": {
                "summary": "Price + TA signal for one coin",
                "parameters": [
                    {"name": "q", "in": "query", "required": True, "schema": {"type": "string", "example": "btc"}},
                    {"name": "format", "in": "query", "schema": {"type": "string", "enum": ["agent", "full"]}},
                ],
                "responses": {"200": {"description": "Coin data"}, **paid},
                "x402": price,
            }
        },
        "/api/compare": {
            "get": {
                "summary": "Compare 2-5 coins in one request",
                "parameters": [
                    {"name": "coins", "in": "query", "required": True, "schema": {"type": "string", "example": "btc,eth,sol"}},
                    {"name": "format", "in": "query", "schema": {"type": "string", "enum": ["agent", "full"]}},
                ],
                "responses": {"200": {"description": "Comparison"}, **paid},
                "x402": price,
            }
        },
        "/api/trending": {
            "get": {
                "summary": "Top gainers and losers (24h)",
                "parameters": [{"name": "limit", "in": "query", "schema": {"type": "integer", "default": 5}}],
                "responses": {"200": {"description": "Trending"}, **paid},
                "x402": price,
            }
        },
        "/api/coins": {"get": {"summary": "List supported coins (free)", "operationId": "listCoins"}},
        "/api/preview": {
            "get": {
                "summary": "Free taste of agent brief (no action_hint / targets)",
                "parameters": [
                    {"name": "q", "in": "query", "required": True, "schema": {"type": "string", "example": "btc"}},
                ],
                "responses": {"200": {"description": "Preview brief with upgrade hint"}},
            }
        },
    }


@app.route("/openapi.json", methods=["GET"])
@app.route("/.well-known/x402", methods=["GET"])
def openapi_spec():
    return jsonify({
        "openapi": "3.0.0",
        "info": {
            "title": "Crypto Agent Brief API",
            "version": VERSION,
            "description": (
                "LLM-ready crypto briefs: price, TA, compare, trending. "
                f"{PAYMENT['amount']} {PAYMENT['currency']} on Base via x402."
            ),
            "x402": PAYMENT,
        },
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

> LLM-ready crypto price + TA briefs. Pay per call via x402 USDC on Base.

## When to use
- Try before you pay → GET /api/preview?q=btc (free)
- Need a concise trading brief for one coin → GET /api/data?q=btc&format=agent
- Compare multiple coins in one call → GET /api/compare?coins=btc,eth,sol&format=agent
- Find top movers → GET /api/trending

## Pricing
- Free preview: /api/preview?q=btc — signal + reason, no action_hint
- Paid: /api/data, /api/compare, /api/trending — {PAYMENT['amount']} USDC each
- Free: /api/coins, /health, /.well-known/x402

## Base URL
{SERVICE_URL}

## Example (agent format)
GET {SERVICE_URL}/api/data?q=btc&format=agent

Returns: coin, price, signal, reason, action_hint — optimized for LLM consumption.

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
