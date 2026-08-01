import logging
import threading
import time
from datetime import datetime

import requests
from cachetools import TTLCache

from config import COINGECKO_API_KEY, COINGECKO_BASE, COINS

logger = logging.getLogger(__name__)

_price_cache = TTLCache(maxsize=200, ttl=120)
_ohlc_cache = TTLCache(maxsize=200, ttl=900)
_snapshot_cache = TTLCache(maxsize=1, ttl=300)
_last_snapshot_update: datetime | None = None
_http = requests.Session()

# Hot coins warmed in background so first paid hits stay fast.
_HOT_COINS = (
    "bitcoin",
    "ethereum",
    "solana",
    "binancecoin",
    "ripple",
    "dogecoin",
    "cardano",
    "avalanche-2",
)

CG_TIMEOUT = 6


def _headers() -> dict:
    headers = {"User-Agent": "PriceBot/13.2", "Accept": "application/json"}
    if COINGECKO_API_KEY:
        headers["x-cg-demo-api-key"] = COINGECKO_API_KEY
    return headers


def resolve_coin_id(query: str) -> str | None:
    """Only known aliases — never treat random strings as coin ids."""
    normalized = query.strip().lower()
    if not normalized:
        return None
    return COINS.get(normalized)


def update_price_snapshot() -> None:
    global _last_snapshot_update
    try:
        ids = sorted(set(COINS.values()))
        merged: dict = dict(_snapshot_cache.get("snapshot") or {})
        got_any = False
        for i in range(0, len(ids), 25):
            chunk = ids[i : i + 25]
            try:
                response = _http.get(
                    f"{COINGECKO_BASE}/simple/price",
                    params={
                        "ids": ",".join(chunk),
                        "vs_currencies": "usd",
                        "include_24hr_change": "true",
                        "include_24hr_vol": "true",
                        "include_market_cap": "true",
                    },
                    timeout=CG_TIMEOUT,
                    headers=_headers(),
                )
                if response.status_code == 429:
                    logger.warning("CoinGecko rate limited on snapshot chunk %s", i)
                    time.sleep(1.5)
                    continue
                response.raise_for_status()
                merged.update(response.json())
                got_any = True
            except Exception as chunk_exc:
                logger.warning("Snapshot chunk failed (%s): %s", i, chunk_exc)
            if i + 25 < len(ids):
                time.sleep(0.35)

        if not got_any and not merged:
            logger.warning("Empty CoinGecko snapshot")
            return

        _snapshot_cache["snapshot"] = merged
        _last_snapshot_update = datetime.utcnow()
        logger.info("Coin snapshot updated for %s coins", len(merged))
    except Exception as exc:
        logger.warning("Failed to update price snapshot: %s", exc)


def _fetch_single_price(coin_id: str) -> dict | None:
    """Fallback when bulk snapshot is cold / rate-limited."""
    cache_key = f"single:{coin_id}"
    if cache_key in _price_cache:
        return _price_cache[cache_key]
    try:
        response = _http.get(
            f"{COINGECKO_BASE}/simple/price",
            params={
                "ids": coin_id,
                "vs_currencies": "usd",
                "include_24hr_change": "true",
                "include_24hr_vol": "true",
                "include_market_cap": "true",
            },
            timeout=CG_TIMEOUT,
            headers=_headers(),
        )
        if response.status_code == 429:
            logger.warning("CoinGecko 429 for single price %s", coin_id)
            return None
        response.raise_for_status()
        row = response.json().get(coin_id)
        if row:
            _price_cache[cache_key] = row
            snap = dict(_snapshot_cache.get("snapshot") or {})
            snap[coin_id] = row
            _snapshot_cache["snapshot"] = snap
        return row
    except Exception as exc:
        logger.warning("Single price failed for %s: %s", coin_id, exc)
        return None


def _price_updater_loop() -> None:
    while True:
        update_price_snapshot()
        _warm_hot_ohlc()
        time.sleep(600)


def _warm_hot_ohlc() -> None:
    for coin_id in _HOT_COINS:
        try:
            get_ohlc(coin_id)
            time.sleep(0.25)
        except Exception as exc:
            logger.debug("OHLC warm failed for %s: %s", coin_id, exc)


def start_price_updater() -> None:
    """Non-blocking: do not stall gunicorn boot / Railway healthchecks."""

    def _boot() -> None:
        update_price_snapshot()
        _warm_hot_ohlc()
        _price_updater_loop()

    threading.Thread(target=_boot, daemon=True, name="price-updater").start()


def get_market_snapshot(coin_id: str) -> dict | None:
    snapshot = _snapshot_cache.get("snapshot", {})
    row = snapshot.get(coin_id)
    if row:
        return row
    if not snapshot:
        update_price_snapshot()
        snapshot = _snapshot_cache.get("snapshot", {})
        row = snapshot.get(coin_id)
        if row:
            return row
    return _fetch_single_price(coin_id)


def get_ohlc(coin_id: str, days: int = 30) -> list[list[float]]:
    cache_key = f"{coin_id}:{days}"
    if cache_key in _ohlc_cache:
        return _ohlc_cache[cache_key]

    response = _http.get(
        f"{COINGECKO_BASE}/coins/{coin_id}/ohlc",
        params={"vs_currency": "usd", "days": days},
        timeout=CG_TIMEOUT,
        headers=_headers(),
    )
    if response.status_code == 429:
        raise RuntimeError(f"CoinGecko 429 for OHLC {coin_id}")
    response.raise_for_status()
    ohlc = response.json()
    if not isinstance(ohlc, list):
        raise ValueError(f"Unexpected OHLC payload for {coin_id}")
    _ohlc_cache[cache_key] = ohlc
    return ohlc


def get_last_snapshot_at() -> str | None:
    if _last_snapshot_update:
        return _last_snapshot_update.isoformat() + "Z"
    return None


def get_trending(limit: int = 10) -> dict:
    snapshot = _snapshot_cache.get("snapshot", {})
    if not snapshot:
        update_price_snapshot()
        snapshot = _snapshot_cache.get("snapshot", {})
    if not snapshot:
        return {"gainers": [], "losers": []}

    id_to_alias = {}
    for alias, coin_id in COINS.items():
        if len(alias) <= 5:
            id_to_alias.setdefault(coin_id, alias.upper())

    rows = []
    for coin_id, data in snapshot.items():
        change = float(data.get("usd_24h_change", 0) or 0)
        rows.append(
            {
                "coin_id": coin_id,
                "ticker": id_to_alias.get(coin_id, coin_id.split("-")[0].upper()),
                "price_usd": _smart_price(data["usd"]),
                "change_24h_percent": round(change, 2),
                "volume_24h": round(float(data.get("usd_24h_vol", 0) or 0), 2),
            }
        )

    sorted_rows = sorted(rows, key=lambda r: r["change_24h_percent"], reverse=True)
    gainers = sorted_rows[:limit]
    losers = list(reversed(sorted_rows[-limit:]))
    return {"gainers": gainers, "losers": losers}


def _smart_price(value: float) -> float:
    """Keep meaningful digits for both BTC and micro-cap coins like SHIB."""
    v = float(value)
    if v >= 1000:
        return round(v, 2)
    if v >= 1:
        return round(v, 4)
    if v >= 0.01:
        return round(v, 6)
    return round(v, 8)


def get_coin_data(query: str) -> dict | None:
    coin_id = resolve_coin_id(query)
    if not coin_id:
        return None

    snapshot = get_market_snapshot(coin_id)
    if not snapshot or "usd" not in snapshot:
        return None

    try:
        ohlc = get_ohlc(coin_id)
    except Exception as exc:
        logger.warning("OHLC fetch failed for %s: %s", coin_id, exc)
        ohlc = []

    closes = [row[3] for row in ohlc] if ohlc else []
    ticker = query.strip().upper()
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
        "price_usd": _smart_price(snapshot["usd"]),
        "change_24h_percent": round(float(snapshot.get("usd_24h_change", 0) or 0), 2),
        "volume_24h": round(float(snapshot.get("usd_24h_vol", 0) or 0), 2),
        "market_cap_usd": round(float(snapshot.get("usd_market_cap", 0) or 0), 2),
        "ohlc": ohlc,
        "closes": closes,
        "data_source": "coingecko",
        "snapshot_at": (_last_snapshot_update or datetime.utcnow()).isoformat() + "Z",
    }
