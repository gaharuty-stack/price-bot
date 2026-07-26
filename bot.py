import logging
import os
import signal
import sys
import uuid
from datetime import datetime

from cachetools import TTLCache
from flask import Flask, jsonify, make_response, request

from config import COINS, PAYMENT, RATE_LIMIT_PER_MINUTE, SERVICE_URL
from db import check_rate_limit, get_stats, init_db, log_request
from integrity import sign_data
from market_data import get_coin_data, resolve_coin_id, start_price_updater
from signals import generate_signal

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("bot.log")],
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
start_time = datetime.utcnow()
response_cache = TTLCache(maxsize=500, ttl=int(os.environ.get("CACHE_TTL_SECONDS", "60")))

init_db()
start_price_updater()


def shutdown_handler(signum, frame):
    logger.info("Shutting down...")
    sys.exit(0)


signal.signal(signal.SIGTERM, shutdown_handler)
signal.signal(signal.SIGINT, shutdown_handler)


def payment_was_settled(req) -> bool:
    """Tollbooth forwards paid requests; detect settlement headers."""
    for header in (
        "X-Payment-Response",
        "X-PAYMENT-RESPONSE",
        "Payment-Response",
        "X-Payment-Tx-Hash",
    ):
        if req.headers.get(header):
            return True
    return False


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


@app.route("/health", methods=["GET"])
def health():
    return jsonify(
        {
            "status": "ok",
            "version": "11.0.0",
            "uptime_seconds": int((datetime.utcnow() - start_time).total_seconds()),
            "coins_supported": len(set(COINS.values())),
        }
    )


@app.route("/api/coins", methods=["GET"])
def list_coins():
    unique = sorted(set(COINS.values()))
    aliases = {}
    for alias, coin_id in COINS.items():
        aliases.setdefault(coin_id, []).append(alias)

    return jsonify(
        {
            "count": len(unique),
            "coins": [
                {"id": coin_id, "aliases": sorted(set(aliases.get(coin_id, [coin_id])))}
                for coin_id in unique
            ],
        }
    )


@app.route("/api/data", methods=["GET", "OPTIONS", "HEAD"])
def get_data():
    if request.method in ("OPTIONS", "HEAD"):
        return make_response("", 200)

    request_id = str(uuid.uuid4())[:8]
    query = request.args.get("q", "").strip()
    client_ip = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()
    paid = payment_was_settled(request)

    if not query:
        log_request("", client_ip, 400, request_id, paid)
        return jsonify({"error": "missing_parameter", "message": "Use ?q=bitcoin"}), 400

    if not resolve_coin_id(query):
        log_request(query, client_ip, 404, request_id, paid)
        return jsonify({"error": "unknown_coin", "message": f"Unsupported coin: {query}"}), 404

    if not check_rate_limit(client_ip, RATE_LIMIT_PER_MINUTE):
        log_request(query, client_ip, 429, request_id, paid)
        return jsonify({"error": "rate_limit_exceeded", "retry_after_seconds": 60}), 429

    cache_key = query.lower()
    if cache_key in response_cache:
        payload = response_cache[cache_key]
    else:
        try:
            result = build_coin_response(query)
        except ValueError as exc:
            log_request(query, client_ip, 404, request_id, paid)
            return jsonify({"error": "unknown_coin", "message": str(exc)}), 404
        except Exception as exc:
            logger.exception("Failed to build response for %s", query)
            log_request(query, client_ip, 503, request_id, paid)
            return jsonify({"error": "upstream_unavailable", "message": str(exc)}), 503

        payload = {
            "status": "ok",
            "query": query,
            "data": result,
            "payment": PAYMENT,
            "paid_request": paid,
        }
        response_cache[cache_key] = payload

    log_request(query, client_ip, 200, request_id, paid)
    response = make_response(jsonify(signed_payload(payload)), 200)
    response.headers["X-Request-ID"] = request_id
    return response


@app.route("/admin/stats", methods=["GET"])
def admin_stats():
    token = request.headers.get("X-Admin-Token", "")
    expected = os.environ.get("ADMIN_TOKEN", "")
    if not expected or token != expected:
        return jsonify({"error": "unauthorized"}), 401
    return jsonify(get_stats())


@app.route("/openapi.json", methods=["GET"])
@app.route("/.well-known/x402", methods=["GET"])
def openapi_spec():
    spec = {
        "openapi": "3.0.0",
        "info": {
            "title": "Crypto Price & TA API",
            "version": "11.0.0",
            "description": (
                "Real-time crypto prices and technical indicators from CoinGecko. "
                f"Paid access: {PAYMENT['amount']} {PAYMENT['currency']} on {PAYMENT['network']} via x402."
            ),
            "x402": PAYMENT,
        },
        "servers": [{"url": SERVICE_URL}],
        "paths": {
            "/api/data": {
                "get": {
                    "summary": "Get price + TA signal for a coin",
                    "operationId": "getCoinSignal",
                    "parameters": [
                        {
                            "name": "q",
                            "in": "query",
                            "required": True,
                            "schema": {"type": "string", "example": "bitcoin"},
                            "description": "Coin name or ticker (btc, eth, sol, ...)",
                        }
                    ],
                    "responses": {
                        "200": {"description": "Price and indicators"},
                        "402": {"description": "Payment required (handled by tollbooth gateway)"},
                    },
                    "x402": {"price": PAYMENT["amount"], "network": PAYMENT["network"]},
                }
            },
            "/api/coins": {
                "get": {
                    "summary": "List supported coins",
                    "operationId": "listCoins",
                }
            },
        },
    }
    return jsonify(spec)


@app.route("/.well-known/mcp.json", methods=["GET"])
def mcp_discovery():
    return jsonify(
        {
            "name": "Crypto Price & TA API",
            "version": "11.0.0",
            "description": "Real CoinGecko prices with RSI, MACD, Bollinger, ATR, Stochastic.",
            "x402": PAYMENT,
            "endpoints": [
                {
                    "path": "/api/data",
                    "method": "GET",
                    "parameters": [{"name": "q", "type": "string", "required": True}],
                    "price": PAYMENT["amount"],
                    "example": f"{SERVICE_URL}/api/data?q=bitcoin",
                },
                {
                    "path": "/api/coins",
                    "method": "GET",
                    "price": "0",
                    "description": "Free coin list for discovery",
                },
            ],
        }
    )


@app.route("/ai.txt", methods=["GET"])
def ai_txt():
    try:
        with open("ai.txt", encoding="utf-8") as handle:
            return make_response(handle.read(), 200, {"Content-Type": "text/plain; charset=utf-8"})
    except FileNotFoundError:
        return make_response("service: Crypto Price & TA API\n", 200, {"Content-Type": "text/plain"})


@app.route("/robots.txt", methods=["GET"])
def robots_txt():
    try:
        with open("robots.txt", encoding="utf-8") as handle:
            return make_response(handle.read(), 200, {"Content-Type": "text/plain; charset=utf-8"})
    except FileNotFoundError:
        return make_response("User-agent: *\nAllow: /\n", 200, {"Content-Type": "text/plain"})


@app.route("/", methods=["GET"])
def root():
    return jsonify(
        {
            "service": "Crypto Price & TA API",
            "version": "11.0.0",
            "status": "ok",
            "coins_supported": len(set(COINS.values())),
            "indicators": ["RSI", "MACD", "Bollinger Bands", "ATR", "Stochastic"],
            "data_source": "coingecko",
            "payment": PAYMENT,
            "docs": {
                "openapi": "/openapi.json",
                "x402": "/.well-known/x402",
                "mcp": "/.well-known/mcp.json",
                "coins": "/api/coins",
            },
            "example": f"/api/data?q=bitcoin",
            "note": "Payment enforced by x402 tollbooth gateway in production.",
        }
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, threaded=True)
