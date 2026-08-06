import base64
import logging
import os
import time
import uuid
from datetime import datetime

from cachetools import TTLCache
from flask import Flask, jsonify, make_response, request

from agent_format import build_agent_brief, build_preview_brief, enrich_compare_with_relative
from config import (
    COINS,
    MAX_COMPARE_COINS,
    PAYMENT,
    PAYMENT_TIERS,
    PREVIEW_RATE_LIMIT_PER_MINUTE,
    PRICE_SCAN,
    PRICE_SIGNAL,
    RATE_LIMIT_PER_MINUTE,
    SCAN_COINS,
    SERVICE_URL,
    SIGNAL_INDEX_COINS,
    VERSION,
)
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
        # Paid handlers log themselves on 200.
        if response.status_code == 200 and (
            path in (
                "/api/data",
                "/api/compare",
                "/api/trending",
                "/api/signal",
                "/api/scan",
                "/trade-signal",
            )
            or path.startswith("/signal/")
            or path.startswith("/api/v1/signal/")
        ):
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
        "confluence": signal_data.get("confluence", 0),
        "tradeable_now": signal_data.get("tradeable_now", False),
        "momentum_5d": signal_data.get("momentum_5d"),
        "setup_votes": signal_data.get("setup_votes") or [],
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
        "paid_24h": stats.get("paid_24h", 0),
        "conversion_pct": stats.get("conversion_pct", 0),
        "pricing": PAYMENT_TIERS,
        "avg_response_ms": avg_ms,
        "last_price_update": get_last_snapshot_at(),
        "data_source": "coingecko",
        "hero_endpoint": "/api/scan",
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
            result, query, SERVICE_URL, PRICE_SIGNAL, PRICE_SCAN
        )

    _track_response(started)
    return jsonify(response_cache[cache_key])


def _load_brief(query: str, agent_format: bool = True):
    """Build cached coin brief. Returns (payload_or_none, error_response_or_none)."""
    if not query:
        return None, (jsonify({"error": "missing_parameter", "message": "Use ?q=btc or /signal/BTC"}), 400)
    if not resolve_coin_id(query):
        return None, (jsonify({"error": "unknown_coin", "message": f"Unsupported coin: {query}"}), 404)

    cache_key = f"data:{query.lower()}:{'agent' if agent_format else 'full'}"
    if cache_key not in response_cache:
        try:
            result = build_coin_response(query)
        except ValueError as exc:
            return None, (jsonify({"error": "unknown_coin", "message": str(exc)}), 404)
        except Exception as exc:
            logger.exception("Failed for %s", query)
            return None, (jsonify({"error": "upstream_unavailable", "message": str(exc)}), 503)

        data = build_agent_brief(result) if agent_format else {
            k: v for k, v in result.items() if k not in ("ohlc", "closes")
        }
        response_cache[cache_key] = {
            "status": "ok",
            "query": query,
            "data": data,
            "format": "agent" if agent_format else "full",
        }
    return response_cache[cache_key], None


def _paid_signal_response(query: str, *, flat: bool = False, endpoint: str = "signal"):
    """Shared paid handler for /api/data and search-friendly /signal/* aliases."""
    started = time.perf_counter()
    guard, err = _paid_guard(endpoint)
    if err:
        return err
    request_id, ip, paid = guard

    fmt = (request.args.get("format") or "agent").strip().lower()
    agent_format = fmt != "full"
    cached, load_err = _load_brief(query, agent_format)
    if load_err:
        return load_err

    payment = {**PAYMENT, "amount": PAYMENT_TIERS["signal"]}
    if flat and agent_format:
        # Flat brief matches how agents consume /signal/BTC style APIs.
        payload = {
            **cached["data"],
            "status": "ok",
            "payment": payment,
            "paid_request": paid,
        }
    else:
        payload = {**cached, "payment": payment, "paid_request": paid}

    log_request(query, ip, 200, request_id, paid)
    _track_response(started)
    resp = make_response(jsonify(signed_payload(payload)), 200)
    resp.headers["X-Request-ID"] = request_id
    return resp


@app.route("/api/data", methods=["GET"])
def get_data():
    query = request.args.get("q", "").strip()
    return _paid_signal_response(query, flat=False, endpoint="data")


@app.route("/api/signal", methods=["GET"])
@app.route("/trade-signal", methods=["GET"])
def get_signal_query():
    query = request.args.get("q", "").strip()
    return _paid_signal_response(query, flat=True, endpoint="signal")


@app.route("/signal/<coin>", methods=["GET"])
@app.route("/api/v1/signal/<coin>", methods=["GET"])
def get_signal_path(coin: str):
    return _paid_signal_response(coin.strip(), flat=True, endpoint="signal")


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
            "price_usdc": PAYMENT_TIERS["compare"],
            "note": f"{len(results)} coin briefs in one ${PAYMENT_TIERS['compare']} call",
        },
        "tradeable_count": rel.get("tradeable_count"),
    }

    payment = {**PAYMENT, "amount": PAYMENT_TIERS["compare"]}
    payload = {
        "status": "ok",
        "coins": results,
        "relative_strength": rel.get("relative"),
        "summary": summary,
        "errors": errors,
        "format": "agent" if agent_format else "full",
        "payment": payment,
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

    payment = {**PAYMENT, "amount": PAYMENT_TIERS["trending"]}
    payload = {
        "status": "ok",
        "gainers": data["gainers"],
        "losers": data["losers"],
        "summary": f"Top gainer: {data['gainers'][0]['ticker'] if data['gainers'] else 'n/a'}",
        "payment": payment,
        "paid_request": paid,
    }
    log_request("trending", ip, 200, request_id, paid)
    _track_response(started)
    return jsonify(signed_payload(payload))


def _scan_market(limit: int = 5) -> dict:
    """Rank liquid coins by tradeable setups — the product agents pay for."""
    cache_key = f"scan:{limit}"
    if cache_key in response_cache:
        return response_cache[cache_key]

    briefs = []
    for coin_id in SCAN_COINS:
        try:
            row = build_coin_response(coin_id)
            briefs.append(build_agent_brief(row))
        except Exception:
            logger.exception("scan skip %s", coin_id)

    buys = sorted(
        [b for b in briefs if b.get("signal") == "BUY"],
        key=lambda b: (b.get("tradeable_now"), b.get("confluence", 0), b.get("edge_score", 0)),
        reverse=True,
    )[:limit]
    sells = sorted(
        [b for b in briefs if b.get("signal") == "SELL"],
        key=lambda b: (b.get("tradeable_now"), b.get("confluence", 0), b.get("edge_score", 0)),
        reverse=True,
    )[:limit]
    tradeable = [b for b in briefs if b.get("tradeable_now")]
    result = {
        "scanned": len(briefs),
        "tradeable_count": len(tradeable),
        "top_buys": buys,
        "top_sells": sells,
        "best_setup": (buys + sells + briefs)[0] if (buys or sells or briefs) else None,
    }
    response_cache[cache_key] = result
    return result


@app.route("/api/pulse", methods=["GET"])
def market_pulse():
    """Free FOMO tease: how many setups exist — not which or BUY/SELL."""
    started = time.perf_counter()
    ip = _client_ip()
    if not check_rate_limit(f"pulse:{ip}", PREVIEW_RATE_LIMIT_PER_MINUTE):
        return jsonify({"error": "rate_limit_exceeded", "retry_after_seconds": 60}), 429

    scan = _scan_market(limit=5)
    payload = {
        "status": "pulse",
        "scanned": scan["scanned"],
        "tradeable_setups": scan["tradeable_count"],
        "has_buy_candidates": bool(scan["top_buys"]),
        "has_sell_candidates": bool(scan["top_sells"]),
        "locked": ["top_buys", "top_sells", "signals", "levels", "targets"],
        "upgrade": {
            "endpoint": f"{SERVICE_URL}/api/scan",
            "price": f"{PRICE_SCAN} USDC",
            "pay": "x402 USDC on Base",
            "why": "Unlock ranked BUY/SELL setups with confluence, S/R, ATR targets",
        },
    }
    _track_response(started)
    return jsonify(payload)


@app.route("/api/scan", methods=["GET"])
def scan_setups():
    """Hero paid product: market-wide tradeable BUY/SELL setups in one call."""
    started = time.perf_counter()
    guard, err = _paid_guard("scan")
    if err:
        return err
    request_id, ip, paid = guard

    limit = min(request.args.get("limit", 5, type=int), 10)
    scan = _scan_market(limit=limit)
    if scan["scanned"] < 3:
        log_request("scan", ip, 503, request_id, paid)
        return jsonify({"error": "upstream_unavailable", "message": "scan universe cold"}), 503

    payment = {**PAYMENT, "amount": PAYMENT_TIERS["scan"]}
    payload = {
        "status": "ok",
        "scanned": scan["scanned"],
        "tradeable_count": scan["tradeable_count"],
        "top_buys": scan["top_buys"],
        "top_sells": scan["top_sells"],
        "best_setup": scan["best_setup"],
        "summary": (
            f"{scan['tradeable_count']} tradeable setups / {scan['scanned']} scanned. "
            f"Best: {(scan['best_setup'] or {}).get('coin', 'n/a')} "
            f"{(scan['best_setup'] or {}).get('signal', '')}."
        ),
        "payment": payment,
        "paid_request": paid,
    }
    log_request("scan", ip, 200, request_id, paid)
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


def _agent_guidance_text() -> str:
    return (
        "Crypto Agent Brief API — actionable x402 setups for trading agents "
        f"(signal {PAYMENT_TIERS['signal']} USDC, scan/compare {PAYMENT_TIERS['scan']} USDC on Base).\n"
        "Workflow:\n"
        "1) Free pulse: GET /api/pulse — how many tradeable setups exist right now (directions locked).\n"
        "2) Free tease: GET /api/preview?q=btc — spot+24h + setup_hint; signal locked.\n"
        f"3) BEST VALUE (hero): GET /api/scan — ranked top BUY/SELL setups across liquid coins "
        f"with confluence + tradeable_now + ATR targets ({PAYMENT_TIERS['scan']} USDC).\n"
        f"4) Single coin: GET /signal/BTC (also /signal/ETH, /signal/SOL) — "
        f"{PAYMENT_TIERS['signal']} USDC flat pack.\n"
        f"5) Compare: GET /api/compare?coins=btc,eth,sol — vs-BTC strength ({PAYMENT_TIERS['compare']} USDC).\n"
        "6) Momentum: GET /api/trending?limit=5.\n"
        "Pay HTTP 402 with x402 USDC on Base (PAYMENT-SIGNATURE / X-PAYMENT), then retry.\n"
        "Prefer /api/scan when you need what to trade next — not a single-coin coin-flip."
    )


def _paid_guidance(kind: str) -> str:
    if kind == "signal":
        return (
            "Use case: get a live Bitcoin/ETH/SOL BUY/SELL/HOLD trading signal for an AI agent. "
            f"Pay {PAYMENT_TIERS['signal']} USDC via x402 on Base, then GET /signal/BTC "
            "(or /api/signal?q=btc). Returns flat JSON: signal, confidence, edge_score, confluence, "
            "tradeable_now, support/resistance, regime, risk, invalidation, ATR target/stop. "
            f"For market-wide setups prefer GET /api/scan ({PAYMENT_TIERS['scan']} USDC)."
        )
    if kind == "data":
        return (
            "Legacy alias of /signal/{coin}. Prefer GET /signal/BTC or hero GET /api/scan. "
            "Pay once with x402 USDC on Base, then GET /api/data?q=btc for wrapped agent pack."
        )
    if kind == "compare":
        return (
            "Use case: rank BTC vs ETH vs SOL in one call for an AI trading agent. "
            f"GET /api/compare?coins=btc,eth,sol for {PAYMENT_TIERS['compare']} USDC. "
            "Returns per-coin agent packs + vs-BTC relative strength + tradeable_count."
        )
    if kind == "scan":
        return (
            "Use case: find what to trade NEXT across liquid majors in one payment. "
            f"Hero endpoint GET /api/scan for {PAYMENT_TIERS['scan']} USDC — returns top BUY and "
            "top SELL setups with confluence, tradeable_now, S/R, ATR targets. "
            "Free FOMO tease first: GET /api/pulse."
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


def _agent_brief_schema():
    return {
        "type": "object",
        "properties": {
            "coin": {"type": "string"},
            "price_usd": {"type": "number"},
            "change_24h": {"type": "string"},
            "signal": {"type": "string", "enum": ["BUY", "SELL", "HOLD"]},
            "confidence": {"type": "number"},
            "edge_score": {"type": "integer"},
            "confluence": {"type": "integer"},
            "tradeable_now": {"type": "boolean"},
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


def _signal_op(coin: str | None = None, *, path_style: str = "param") -> dict:
    """OpenAPI operation optimized for AgentCash 'bitcoin trading signal' queries."""
    legacy_x402 = {"price": PAYMENT["amount"], "network": PAYMENT["network"]}
    label = coin or "BTC/ETH/SOL"
    if path_style == "fixed" and coin:
        summary = (
            f"Returns a trading signal for {coin} (BUY/SELL/HOLD) with support/resistance, "
            f"edge_score, invalidation, target and stop — {PAYMENT['amount']} USDC x402"
        )
        description = (
            f"Get a live {coin} crypto trading signal for AI agents. "
            f"Pay {PAYMENT['amount']} USDC on Base via x402, then call this endpoint. "
            "Returns flat JSON: signal, confidence, edge_score, regime, risk, levels, "
            "invalidation, target_price, stop_loss, action_hint. "
            "Cheaper than typical $0.01–$0.25 signal APIs."
        )
        params = []
        op_id = f"signal{coin}"
    elif path_style == "query":
        summary = (
            "Returns a BUY/SELL/HOLD trading signal for any supported crypto "
            f"(q=btc|eth|sol|…) with S/R + invalidation — {PAYMENT['amount']} USDC x402"
        )
        description = (
            "Pay-per-call Bitcoin/ETH/SOL trading signal for automated agents. "
            f"Price {PAYMENT['amount']} USDC on Base. Use ?q=btc (or eth, sol, xrp, doge, …). "
            "Flat agent pack — not a raw CoinGecko dump."
        )
        params = [
            {
                "name": "q",
                "in": "query",
                "required": True,
                "description": "Coin ticker: btc, eth, sol, bitcoin, ethereum, …",
                "schema": {"type": "string", "minLength": 1, "example": "btc"},
            }
        ]
        op_id = "signalQuery"
    else:
        summary = (
            f"Returns a trading signal for {{{'coin'}}} — BUY/SELL/HOLD with support/resistance "
            f"and invalidation ({PAYMENT['amount']} USDC x402)"
        )
        description = (
            "Path-style crypto trading signal endpoint for AI agents "
            f"(example: /signal/BTC). Pay {PAYMENT['amount']} USDC via x402 on Base. "
            f"Supports {label} and 40+ other tickers."
        )
        params = [
            {
                "name": "coin",
                "in": "path",
                "required": True,
                "description": "Ticker or id: BTC, ETH, SOL, btc, eth, sol, …",
                "schema": {"type": "string", "example": "BTC"},
            }
        ]
        op_id = "signalByCoin"

    return {
        "operationId": op_id,
        "summary": summary,
        "description": description,
        "tags": ["Trading", "Crypto", "Signals"],
        "security": [{"x402": []}],
        "parameters": params,
        "responses": {
            "200": {
                "description": "Flat BUY/SELL/HOLD agent pack",
                "content": {"application/json": {"schema": _agent_brief_schema()}},
            },
            **_paid_402(),
        },
        "x-payment-info": _payment_info(),
        "x-guidance": _paid_guidance("signal"),
        "x402": legacy_x402,
    }


def _openapi_paths():
    legacy_x402 = {"price": PAYMENT["amount"], "network": PAYMENT["network"]}
    agent_brief_schema = _agent_brief_schema()
    free_security = []
    paid_security = [{"x402": []}]

    paths = {
        "/health": {
            "get": {
                "operationId": "health",
                "summary": "Service health and paid_request counters (free)",
                "tags": ["Meta"],
                "security": free_security,
                "responses": {"200": {"description": "Health JSON"}},
            }
        },
        "/guidance": {
            "get": {
                "operationId": "guidance",
                "summary": "How AI agents should use free tease + paid signal endpoints (free)",
                "tags": ["Meta"],
                "security": free_security,
                "responses": {"200": {"description": "Plain-text agent workflow guidance"}},
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
        "/signal/{coin}": {"get": _signal_op(path_style="param")},
        "/api/v1/signal/{coin}": {
            "get": {
                **_signal_op(path_style="param"),
                "operationId": "signalByCoinV1",
            }
        },
        "/api/signal": {"get": {**_signal_op(path_style="query"), "operationId": "apiSignalQuery"}},
        "/trade-signal": {"get": {**_signal_op(path_style="query"), "operationId": "tradeSignal"}},
        "/api/data": {
            "get": {
                "operationId": "getCoinBrief",
                "summary": (
                    "Legacy wrapped BUY/SELL/HOLD agent pack (prefer GET /signal/BTC) — "
                    f"{PAYMENT['amount']} USDC x402"
                ),
                "description": (
                    "Wrapped response {status,data}. Prefer flat GET /signal/BTC for new agents. "
                    "Returns USD price, BUY/SELL/HOLD, confidence, edge_score, S/R levels, "
                    "regime, risk, invalidation, target and stop."
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
                        "description": "Wrapped coin brief",
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
                    f"BUY/SELL/HOLD + vs-BTC strength in one {PAYMENT_TIERS['compare']} USDC payment"
                ),
                "description": (
                    "Portfolio ranking for agents. Compare 2–5 cryptocurrencies "
                    "(example: coins=btc,eth,sol) in a single x402 payment. "
                    "Returns per-coin agent packs, best/worst 24h, vs-BTC strength, tradeable_count. "
                    f"For market-wide setups prefer GET /api/scan ({PAYMENT_TIERS['scan']} USDC)."
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
                    "200": {
                        "description": "Multi-coin comparison with best/worst summary",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "status": {"type": "string"},
                                        "coins": {"type": "array", "items": agent_brief_schema},
                                        "summary": {
                                            "type": "object",
                                            "properties": {
                                                "best_performer": {"type": "string"},
                                                "worst_performer": {"type": "string"},
                                                "best_edge": {"type": "string"},
                                                "best_vs_btc": {"type": "string"},
                                            },
                                        },
                                    },
                                }
                            }
                        },
                    },
                    **_paid_402(),
                },
                "x-payment-info": {
                    "price": {
                        "mode": "fixed",
                        "currency": "USD",
                        "amount": f"{float(PAYMENT_TIERS['compare']):.6f}",
                    },
                    "protocols": [{"x402": {}}],
                },
                "x-guidance": _paid_guidance("compare"),
                "x402": {"price": PAYMENT_TIERS["compare"], "network": PAYMENT["network"]},
            }
        },
        "/api/trending": {
            "get": {
                "operationId": "getTrending",
                "summary": (
                    "Top crypto gainers and losers last 24h — "
                    f"momentum list for AI trading agents ({PAYMENT_TIERS['trending']} USDC x402)"
                ),
                "description": (
                    "Lists top gainers and losers among supported coins by 24h percent change. "
                    "Use before picking a coin for /signal/BTC or unlock setups via /api/scan."
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
                    "200": {
                        "description": "Trending gainers and losers",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "status": {"type": "string"},
                                        "gainers": {"type": "array", "items": {"type": "object"}},
                                        "losers": {"type": "array", "items": {"type": "object"}},
                                        "summary": {"type": "string"},
                                    },
                                }
                            }
                        },
                    },
                    **_paid_402(),
                },
                "x-payment-info": {
                    "price": {
                        "mode": "fixed",
                        "currency": "USD",
                        "amount": f"{float(PAYMENT_TIERS['trending']):.6f}",
                    },
                    "protocols": [{"x402": {}}],
                },
                "x-guidance": _paid_guidance("trending"),
                "x402": {"price": PAYMENT_TIERS["trending"], "network": PAYMENT["network"]},
            }
        },
        "/api/pulse": {
            "get": {
                "operationId": "marketPulse",
                "summary": "Free FOMO tease — count of tradeable setups (directions locked)",
                "description": (
                    "Free market pulse for AI agents: how many tradeable setups exist now. "
                    f"Directions stay locked — unlock with GET /api/scan ({PAYMENT_TIERS['scan']} USDC)."
                ),
                "tags": ["Search", "Crypto"],
                "security": free_security,
                "responses": {"200": {"description": "Setup count tease with upgrade to /api/scan"}},
            }
        },
        "/api/scan": {
            "get": {
                "operationId": "scanSetups",
                "summary": (
                    "Market-wide BUY/SELL setup scanner for AI agents — "
                    f"top tradeable setups in one {PAYMENT_TIERS['scan']} USDC payment"
                ),
                "description": (
                    "Hero paid endpoint. Scans liquid majors (BTC, ETH, SOL, …) and returns "
                    "ranked top BUY and top SELL setups with confluence, tradeable_now, "
                    "support/resistance, ATR-based target/stop, and invalidation. "
                    f"Pay {PAYMENT_TIERS['scan']} USDC via x402 on Base. "
                    "Free FOMO first: GET /api/pulse."
                ),
                "tags": ["Trading", "Crypto", "Signals", "Scan"],
                "security": paid_security,
                "parameters": [
                    {
                        "name": "limit",
                        "in": "query",
                        "schema": {"type": "integer", "default": 5, "minimum": 1, "maximum": 10},
                        "description": "How many top buys and top sells to return",
                    }
                ],
                "responses": {
                    "200": {
                        "description": "Ranked tradeable BUY/SELL setups",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "status": {"type": "string"},
                                        "scanned": {"type": "integer"},
                                        "tradeable_count": {"type": "integer"},
                                        "top_buys": {"type": "array", "items": agent_brief_schema},
                                        "top_sells": {"type": "array", "items": agent_brief_schema},
                                        "best_setup": agent_brief_schema,
                                        "summary": {"type": "string"},
                                    },
                                }
                            }
                        },
                    },
                    **_paid_402(),
                },
                "x-payment-info": {
                    "price": {
                        "mode": "fixed",
                        "currency": "USD",
                        "amount": f"{float(PAYMENT_TIERS['scan']):.6f}",
                    },
                    "protocols": [{"x402": {}}],
                },
                "x-guidance": _paid_guidance("scan"),
                "x402": {"price": PAYMENT_TIERS["scan"], "network": PAYMENT["network"]},
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
                "summary": "Free crypto spot price + 24h tease (BUY/SELL signal locked)",
                "description": (
                    "Free tease: USD price, 24h change, and edge_band teaser. "
                    "BUY/SELL/HOLD + levels + invalidation stay locked — "
                    f"upgrade via GET /signal/BTC for {PAYMENT['amount']} USDC."
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
                "responses": {"200": {"description": "Price tease with upgrade hint to /signal/BTC"}},
            }
        },
    }

    # Concrete /signal/BTC style paths win AgentCash vector search vs generic /api/data.
    for coin in SIGNAL_INDEX_COINS:
        paths[f"/signal/{coin}"] = {
            "get": {**_signal_op(coin, path_style="fixed"), "operationId": f"signal{coin}"}
        }
        paths[f"/api/v1/signal/{coin}"] = {
            "get": {**_signal_op(coin, path_style="fixed"), "operationId": f"signal{coin}V1"}
        }

    return paths


# Minimal 16x16 ICO — AgentCash/x402scan treat missing/invalid favicon as a discovery warning.
_FAVICON_ICO = base64.b64decode(
    "AAABAAEAEBAAAAEAIABIBAAAFgAAACgAAAAQAAAAIAAAAAEAIAAAAAAAAAQAAAAAAAAAAAAAAAAAAAAAAAAixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/IsVe/yLFXv8ixV7/AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
)


@app.route("/favicon.ico", methods=["GET"])
def favicon_ico():
    return make_response(
        _FAVICON_ICO,
        200,
        {
            "Content-Type": "image/x-icon",
            "Cache-Control": "public, max-age=86400",
        },
    )


@app.route("/favicon.svg", methods=["GET"])
def favicon_svg():
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
        '<rect width="64" height="64" rx="12" fill="#0f172a"/>'
        '<text x="32" y="42" text-anchor="middle" font-size="28" fill="#22c55e"'
        ' font-family="Arial,sans-serif">$</text></svg>'
    )
    return make_response(svg, 200, {"Content-Type": "image/svg+xml; charset=utf-8"})


@app.route("/guidance", methods=["GET"])
def guidance():
    return make_response(_agent_guidance_text(), 200, {"Content-Type": "text/plain; charset=utf-8"})


@app.route("/openapi.json", methods=["GET"])
@app.route("/.well-known/x402", methods=["GET"])
@app.route("/.well-known/x402.json", methods=["GET"])
def openapi_spec():
    info = {
        "title": "Crypto Agent Brief API",
        "version": VERSION,
        "description": (
            "Actionable x402 crypto setup API for AI trading agents — not raw CoinGecko dumps. "
            f"Hero: GET /api/scan — ranked BUY/SELL setups with confluence + tradeable_now "
            f"({PAYMENT_TIERS['scan']} USDC). "
            f"Single coin: GET /signal/BTC ({PAYMENT_TIERS['signal']} USDC) with S/R, invalidation, "
            "ATR target/stop. "
            f"Compare: GET /api/compare?coins=btc,eth,sol ({PAYMENT_TIERS['compare']} USDC). "
            "Free: GET /api/pulse (setup count) and GET /api/preview?q=btc. Guidance: /guidance."
        ),
        "x-guidance": _agent_guidance_text(),
        "x402": PAYMENT,
        "contact": {
            "url": os.environ.get(
                "CONTACT_URL",
                "https://github.com/gaharuty-stack/price-bot",
            ).strip(),
        },
    }
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
            {"name": "Scan", "description": "Market-wide tradeable setup scanner"},
            {"name": "Search", "description": "Coin list, preview, pulse, trending"},
            {"name": "Meta", "description": "Health, OpenAPI, guidance, llms.txt"},
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
            f"x402 crypto setup scanner + signals (scan {PAYMENT_TIERS['scan']} / "
            f"signal {PAYMENT_TIERS['signal']} USDC). Prefer GET /api/scan. Free /api/pulse."
        ),
        "guidance": f"{SERVICE_URL}/guidance",
        "x402": PAYMENT,
        "endpoints": [
            {"path": "/api/pulse", "method": "GET", "price": "0", "example": f"{SERVICE_URL}/api/pulse"},
            {"path": "/api/preview", "method": "GET", "price": "0", "example": f"{SERVICE_URL}/api/preview?q=btc"},
            {"path": "/api/scan", "method": "GET", "price": PAYMENT_TIERS["scan"], "example": f"{SERVICE_URL}/api/scan"},
            {"path": "/signal/BTC", "method": "GET", "price": PAYMENT_TIERS["signal"], "example": f"{SERVICE_URL}/signal/BTC"},
            {"path": "/signal/ETH", "method": "GET", "price": PAYMENT_TIERS["signal"], "example": f"{SERVICE_URL}/signal/ETH"},
            {"path": "/signal/SOL", "method": "GET", "price": PAYMENT_TIERS["signal"], "example": f"{SERVICE_URL}/signal/SOL"},
            {"path": "/api/signal", "method": "GET", "price": PAYMENT_TIERS["signal"], "example": f"{SERVICE_URL}/api/signal?q=btc"},
            {"path": "/trade-signal", "method": "GET", "price": PAYMENT_TIERS["signal"], "example": f"{SERVICE_URL}/trade-signal?q=btc"},
            {"path": "/api/compare", "method": "GET", "price": PAYMENT_TIERS["compare"], "example": f"{SERVICE_URL}/api/compare?coins=btc,eth,sol"},
            {"path": "/api/trending", "method": "GET", "price": PAYMENT_TIERS["trending"], "example": f"{SERVICE_URL}/api/trending"},
            {"path": "/api/coins", "method": "GET", "price": "0"},
            {"path": "/guidance", "method": "GET", "price": "0"},
        ],
    })


@app.route("/llms.txt", methods=["GET"])
@app.route("/ai.txt", methods=["GET"])
def llms_txt():
    text = f"""# Crypto Agent Brief API v{VERSION}

> Actionable x402 crypto setups for AI trading agents.
> Hero call: GET /api/scan → ranked BUY/SELL setups ({PAYMENT_TIERS['scan']} USDC).

## Why pay here
- Market-wide **setup scanner** (not one coin dump)
- confluence + tradeable_now so agents skip weak flips
- ATR-based target/stop + support/resistance + invalidation
- Free /api/pulse proves setups exist without revealing direction

## Preferred endpoints
- HERO scan → GET /api/scan ({PAYMENT_TIERS['scan']} USDC)
- Bitcoin signal → GET /signal/BTC ({PAYMENT_TIERS['signal']} USDC)
- Ethereum / Solana → GET /signal/ETH | /signal/SOL
- Compare + vs-BTC → GET /api/compare?coins=btc,eth,sol ({PAYMENT_TIERS['compare']} USDC)
- Gainers/losers → GET /api/trending ({PAYMENT_TIERS['trending']} USDC)

## Free
- Pulse (setup count) → GET /api/pulse
- Price tease → GET /api/preview?q=btc
- Guidance → GET /guidance
- Docs → GET /llms.txt

## Agent pack fields
coin, price_usd, signal, confidence, edge_score, confluence, tradeable_now,
regime, risk, levels.support, levels.resistance, reason, action_hint,
invalidation, target_price, stop_loss

## Pricing (Base USDC / x402)
- Signal / trending: {PAYMENT_TIERS['signal']} USDC
- Scan / compare: {PAYMENT_TIERS['scan']} USDC
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
            "Allow: /api/pulse\n"
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
        "tagline": f"x402 setup scanner — /api/scan {PAYMENT_TIERS['scan']} USDC",
        "coins_supported": len(set(COINS.values())),
        "payment": PAYMENT,
        "pricing": PAYMENT_TIERS,
        "guidance": "/guidance",
        "endpoints": {
            "free": [
                "/health",
                "/api/coins",
                "/api/preview",
                "/api/pulse",
                "/guidance",
                "/llms.txt",
                "/.well-known/x402",
            ],
            "paid": [
                "/api/scan",
                "/signal/BTC",
                "/signal/ETH",
                "/signal/SOL",
                "/api/signal",
                "/trade-signal",
                "/api/data",
                "/api/compare",
                "/api/trending",
            ],
        },
        "examples": {
            "pulse": "/api/pulse",
            "scan": "/api/scan",
            "preview": "/api/preview?q=btc",
            "btc_signal": "/signal/BTC",
            "eth_signal": "/signal/ETH",
            "sol_signal": "/signal/SOL",
            "any_signal": "/api/signal?q=btc",
            "compare": "/api/compare?coins=btc,eth,sol",
            "trending": "/api/trending",
        },
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
