import logging
import threading
import time
from datetime import datetime

import requests
from cachetools import TTLCache

from config import COINGECKO_API_KEY, COINGECKO_BASE, COINS

logger = logging.getLogger(__name__)

_price_cache = TTLCache(maxsize=200, ttl=120)
_ohlc_cache = TTLCache(maxsize=200, ttl=600)
_snapshot_cache = TTLCache(maxsize=1, ttl=300)
_last_snapshot_update: datetime | None = None


def _headers() -> dict:
    headers = {"User-Agent": "PriceBot/11.0", "Accept": "application/json"}
    if COINGECKO_API_KEY:
        headers["x-cg-demo-api-key"] = COINGECKO_API_KEY
    return headers


def resolve_coin_id(query: str) -> str | None:
    normalized = query.strip().lower()
    return COINS.get(normalized, normalized if normalized else None)


def update_price_snapshot() -> None:
    global _last_snapshot_update
    try:
        ids = ",".join(sorted(set(COINS.values())))
        response = requests.get(
            f"{COINGECKO_BASE}/simple/price",
            params={
                "ids": ids,
                "vs_currencies": "usd",
                "include_24hr_change": "true",
                "include_24hr_vol": "true",
                "include_market_cap": "true",
            },
            timeout=15,
            headers=_headers(),
        )
        response.raise_for_status()
        _snapshot_cache["snapshot"] = response.json()
        _last_snapshot_update = datetime.utcnow()
        logger.info("Coin snapshot updated for %s coins", len(response.json()))
    except Exception as exc:
        logger.warning("Failed to update price snapshot: %s", exc)


def _price_updater_loop() -> None:
    while True:
        update_price_snapshot()
        time.sleep(600)


def start_price_updater() -> None:
    update_price_snapshot()
    threading.Thread(target=_price_updater_loop, daemon=True).start()


def get_market_snapshot(coin_id: str) -> dict | None:
    snapshot = _snapshot_cache.get("snapshot", {})
    return snapshot.get(coin_id)


def get_ohlc(coin_id: str, days: int = 30) -> list[list[float]]:
    cache_key = f"{coin_id}:{days}"
    if cache_key in _ohlc_cache:
        return _ohlc_cache[cache_key]

    response = requests.get(
        f"{COINGECKO_BASE}/coins/{coin_id}/ohlc",
        params={"vs_currency": "usd", "days": days},
        timeout=15,
        headers=_headers(),
    )
    response.raise_for_status()
    ohlc = response.json()
    _ohlc_cache[cache_key] = ohlc
    return ohlc


def get_last_snapshot_at() -> str | None:
    if _last_snapshot_update:
        return _last_snapshot_update.isoformat() + "Z"
    return None


def get_trending(limit: int = 10) -> dict:
    snapshot = _snapshot_cache.get("snapshot", {})
    if not snapshot:
        return {"gainers": [], "losers": []}

    id_to_alias = {}
    for alias, coin_id in COINS.items():
        if len(alias) <= 5:
            id_to_alias.setdefault(coin_id, alias.upper())

    rows = []
    for coin_id, data in snapshot.items():
        change = float(data.get("usd_24h_change", 0))
        rows.append({
            "coin_id": coin_id,
            "ticker": id_to_alias.get(coin_id, coin_id.split("-")[0].upper()),
            "price_usd": round(float(data["usd"]), 2),
            "change_24h_percent": round(change, 2),
            "volume_24h": round(float(data.get("usd_24h_vol", 0)), 2),
        })

    sorted_rows = sorted(rows, key=lambda r: r["change_24h_percent"], reverse=True)
    gainers = sorted_rows[:limit]
    losers = list(reversed(sorted_rows[-limit:]))
    return {"gainers": gainers, "losers": losers}


def get_coin_data(query: str) -> dict | None:
    coin_id = resolve_coin_id(query)
    if not coin_id:
        return None

    snapshot = get_market_snapshot(coin_id)
    if not snapshot:
        return None

    try:
        ohlc = get_ohlc(coin_id)
    except Exception as exc:
        logger.warning("OHLC fetch failed for %s: %s", coin_id, exc)
        ohlc = []

    closes = [row[3] for row in ohlc] if ohlc else []
    ticker = query.strip().lower()
    for alias, cid in COINS.items():
        if cid == coin_id and len(alias) <= 5:
            ticker = alias.upper()
            break
    else:
        ticker = coin_id.split("-")[0].upper()

    return {
        "coin_id": coin_id,
        "ticker": ticker,
        "name": query.strip().title(),
        "price_usd": round(float(snapshot["usd"]), 2),
        "change_24h_percent": round(float(snapshot.get("usd_24h_change", 0)), 2),
        "volume_24h": round(float(snapshot.get("usd_24h_vol", 0)), 2),
        "market_cap_usd": round(float(snapshot.get("usd_market_cap", 0)), 2),
        "ohlc": ohlc,
        "closes": closes,
        "data_source": "coingecko",
        "snapshot_at": (_last_snapshot_update or datetime.utcnow()).isoformat() + "Z",
    }
