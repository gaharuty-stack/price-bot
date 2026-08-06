def _rsi_label(rsi: float) -> str:
    if rsi < 30:
        return f"oversold (RSI {rsi})"
    if rsi > 70:
        return f"overbought (RSI {rsi})"
    return f"neutral (RSI {rsi})"


def _macd_label(macd: dict) -> str:
    if macd["histogram"] > 0 and macd["macd"] > macd["signal"]:
        return "MACD bullish"
    if macd["histogram"] < 0 and macd["macd"] < macd["signal"]:
        return "MACD bearish"
    return "MACD flat"


def _bollinger_label(price: float, bollinger: dict) -> str:
    if bollinger["lower"] > 0 and price <= bollinger["lower"]:
        return "price at lower Bollinger band"
    if bollinger["upper"] > 0 and price >= bollinger["upper"]:
        return "price at upper Bollinger band"
    return "price mid-range in Bollinger bands"


def _smart_price(value: float) -> float:
    v = float(value)
    if v >= 1000:
        return round(v, 2)
    if v >= 1:
        return round(v, 4)
    if v >= 0.01:
        return round(v, 6)
    return round(v, 8)


def _levels_from_ohlc(ohlc: list, price: float) -> dict:
    """Near-term support/resistance from recent daily OHLC highs/lows."""
    if not ohlc or len(ohlc) < 5:
        return {
            "support": _smart_price(price * 0.97),
            "resistance": _smart_price(price * 1.03),
            "window_days": 0,
        }
    window = ohlc[-14:] if len(ohlc) >= 14 else ohlc
    # CoinGecko OHLC row: [ts, open, high, low, close]
    highs = [float(row[2]) for row in window if len(row) >= 5]
    lows = [float(row[3]) for row in window if len(row) >= 5]
    if not highs or not lows:
        return {
            "support": _smart_price(price * 0.97),
            "resistance": _smart_price(price * 1.03),
            "window_days": len(window),
        }
    support = min(lows)
    resistance = max(highs)
    if support >= price:
        support = min(lows + [price * 0.98])
    if resistance <= price:
        resistance = max(highs + [price * 1.02])
    return {
        "support": _smart_price(support),
        "resistance": _smart_price(resistance),
        "window_days": len(window),
    }


def _regime_and_risk(price: float, atr: float, change_24h: float, confidence: float) -> tuple[str, str, int]:
    atr_pct = (atr / price * 100) if price > 0 and atr > 0 else abs(change_24h)
    if atr_pct < 1.5:
        regime = "calm"
    elif atr_pct < 4:
        regime = "normal"
    else:
        regime = "volatile"

    if regime == "volatile" or abs(change_24h) > 8 or confidence < 55:
        risk = "high"
    elif regime == "normal" or abs(change_24h) > 3:
        risk = "medium"
    else:
        risk = "low"

    edge = int(confidence)
    if regime == "calm" and confidence >= 60:
        edge = min(95, edge + 5)
    if regime == "volatile":
        edge = max(20, edge - 8)
    return regime, risk, edge


def build_agent_brief(data: dict) -> dict:
    indicators = data["indicators"]
    rsi = indicators["rsi"]
    macd = indicators["macd"]
    bollinger = indicators["bollinger"]
    atr = float(indicators.get("atr") or 0)
    change = data["change_24h_percent"]
    signal = data["signal"]
    price = data["price_usd"]
    levels = _levels_from_ohlc(data.get("ohlc") or [], price)
    regime, risk, edge_score = _regime_and_risk(price, atr, change, float(data["confidence"]))
    confluence = int(data.get("confluence") or 0)
    tradeable = bool(data.get("tradeable_now"))
    # Boost edge when several indicators agree.
    if tradeable and confluence >= 3:
        edge_score = min(95, edge_score + 6)
    elif confluence <= 1 and signal != "HOLD":
        edge_score = max(25, edge_score - 6)

    parts = [
        _rsi_label(rsi),
        _macd_label(macd),
        _bollinger_label(price, bollinger),
        f"24h change {change:+.2f}%",
        f"regime {regime}",
        f"confluence {confluence}",
    ]
    reason = "; ".join(parts)

    if signal == "BUY":
        action_hint = (
            f"{'TRADEABLE' if tradeable else 'Weak'} bullish bias "
            f"({data['confidence']}% conf, edge {edge_score}, confluence {confluence}). "
            f"Target ${_smart_price(data['target_price'])}, stop ${_smart_price(data['stop_loss'])}. "
            f"Invalidation: daily close below support {levels['support']}."
        )
    elif signal == "SELL":
        action_hint = (
            f"{'TRADEABLE' if tradeable else 'Weak'} bearish bias "
            f"({data['confidence']}% conf, edge {edge_score}, confluence {confluence}). "
            f"Target ${_smart_price(data['target_price'])}, stop ${_smart_price(data['stop_loss'])}. "
            f"Invalidation: daily close above resistance {levels['resistance']}."
        )
    else:
        action_hint = (
            f"No strong edge (score {edge_score}, risk {risk}). "
            f"Wait between support {levels['support']} and resistance {levels['resistance']}."
        )

    return {
        "coin": data.get("ticker") or data.get("coin_id", ""),
        "price_usd": price,
        "change_24h": f"{change:+.2f}%",
        "signal": signal,
        "confidence": data["confidence"],
        "edge_score": edge_score,
        "confluence": confluence,
        "tradeable_now": tradeable,
        "regime": regime,
        "risk": risk,
        "levels": levels,
        "reason": reason,
        "action_hint": action_hint,
        "target_price": _smart_price(data["target_price"]),
        "stop_loss": _smart_price(data["stop_loss"]),
        "invalidation": (
            f"close below {levels['support']}"
            if signal == "BUY"
            else (
                f"close above {levels['resistance']}"
                if signal == "SELL"
                else f"break of {levels['support']}–{levels['resistance']} range"
            )
        ),
    }


def enrich_compare_with_relative(briefs: list[dict], btc_change: float | None) -> dict:
    """Add vs-BTC relative strength — differentiator vs single-coin price APIs."""
    ranked = []
    for b in briefs:
        change = float(str(b.get("change_24h", "0")).replace("%", "").replace("+", "") or 0)
        vs_btc = None if btc_change is None else round(change - btc_change, 2)
        ranked.append({
            "coin": b.get("coin"),
            "change_24h": change,
            "vs_btc_24h": vs_btc,
            "signal": b.get("signal"),
            "edge_score": b.get("edge_score"),
            "tradeable_now": b.get("tradeable_now"),
            "risk": b.get("risk"),
        })
    by_edge = sorted(ranked, key=lambda r: (r.get("edge_score") or 0), reverse=True)
    by_rel = sorted(
        ranked,
        key=lambda r: (r["vs_btc_24h"] if r["vs_btc_24h"] is not None else r["change_24h"]),
        reverse=True,
    )
    tradeable = [r for r in ranked if r.get("tradeable_now")]
    return {
        "relative": ranked,
        "best_edge": by_edge[0]["coin"] if by_edge else None,
        "best_vs_btc": by_rel[0]["coin"] if by_rel else None,
        "tradeable_count": len(tradeable),
    }


def build_preview_brief(data: dict, query: str, service_url: str, price: str, scan_price: str) -> dict:
    """Free tease: spot + 24h only. Signal/TA stay behind x402."""
    brief = build_agent_brief(data)
    edge = int(brief.get("edge_score") or 0)
    if edge >= 70:
        edge_band = "strong"
    elif edge >= 55:
        edge_band = "moderate"
    else:
        edge_band = "weak"
    coin = brief["coin"]
    return {
        "status": "preview",
        "query": query,
        "data": {
            "coin": coin,
            "price_usd": brief["price_usd"],
            "change_24h": brief["change_24h"],
        },
        "teaser": {
            "signal_ready": True,
            "edge_band": edge_band,
            "risk": brief.get("risk"),
            "regime": brief.get("regime"),
            "setup_hint": "tradeable" if brief.get("tradeable_now") else "weak_or_hold",
            "unlock": f"GET {service_url}/signal/{coin} — BUY/SELL/HOLD + S/R + invalidation",
            "best_value": f"GET {service_url}/api/scan — top BUY/SELL setups across liquid coins ({scan_price} USDC)",
        },
        "locked": [
            "signal",
            "confidence",
            "edge_score",
            "confluence",
            "tradeable_now",
            "reason",
            "levels",
            "invalidation",
            "action_hint",
            "target_price",
            "stop_loss",
        ],
        "upgrade": {
            "endpoint": f"{service_url}/signal/{coin}",
            "price": f"{price} USDC",
            "scan": {
                "endpoint": f"{service_url}/api/scan",
                "price": f"{scan_price} USDC",
                "why": "One payment → ranked tradeable BUY/SELL setups across liquid majors",
            },
            "pay": "x402 USDC on Base",
            "includes": [
                "BUY/SELL/HOLD signal",
                "confluence + tradeable_now",
                "support/resistance levels",
                "ATR-based target/stop",
                "invalidation + action_hint",
            ],
        },
    }
