from indicators import (
    calculate_atr,
    calculate_bollinger,
    calculate_macd,
    calculate_rsi,
    calculate_stochastic,
)


def _px(v: float) -> float:
    if v >= 1000:
        return round(v, 2)
    if v >= 1:
        return round(v, 4)
    if v >= 0.01:
        return round(v, 6)
    return round(v, 8)


def _momentum(closes: list[float], lookback: int = 5) -> float:
    if len(closes) < lookback + 1 or closes[-lookback - 1] == 0:
        return 0.0
    return ((closes[-1] - closes[-lookback - 1]) / closes[-lookback - 1]) * 100


def generate_signal(
    price: float,
    change_24h: float,
    volume: float,
    closes: list[float],
    ohlc: list[list[float]],
) -> dict:
    rsi = calculate_rsi(closes)
    macd = calculate_macd(closes)
    bollinger = calculate_bollinger(closes)
    stochastic = calculate_stochastic(ohlc)
    atr = calculate_atr(ohlc)
    mom5 = _momentum(closes, 5)

    buy_score, sell_score = 0, 0
    votes = []

    if rsi < 30:
        buy_score += 25
        votes.append("rsi_oversold")
    elif rsi > 70:
        sell_score += 25
        votes.append("rsi_overbought")

    if macd["macd"] > macd["signal"] and macd["histogram"] > 0:
        buy_score += 20
        votes.append("macd_bull")
    elif macd["macd"] < macd["signal"] and macd["histogram"] < 0:
        sell_score += 20
        votes.append("macd_bear")

    if bollinger["lower"] > 0 and price <= bollinger["lower"]:
        buy_score += 15
        votes.append("bb_lower")
    elif bollinger["upper"] > 0 and price >= bollinger["upper"]:
        sell_score += 15
        votes.append("bb_upper")

    if stochastic < 20:
        buy_score += 15
        votes.append("stoch_oversold")
    elif stochastic > 80:
        sell_score += 15
        votes.append("stoch_overbought")

    if change_24h > 1:
        buy_score += min(20, int(change_24h * 4))
    elif change_24h < -1:
        sell_score += min(20, int(abs(change_24h) * 4))

    if mom5 > 2:
        buy_score += 8
        votes.append("mom5_up")
    elif mom5 < -2:
        sell_score += 8
        votes.append("mom5_down")

    if volume > 100_000_000:
        if change_24h >= 0:
            buy_score += 5
        else:
            sell_score += 5

    atr_safe = atr if atr and atr > 0 else price * 0.02

    if buy_score > sell_score:
        signal = "BUY"
        confidence = min(88, 45 + buy_score * 0.55)
        target = price + 1.5 * atr_safe
        stop = price - 1.0 * atr_safe
    elif sell_score > buy_score:
        signal = "SELL"
        confidence = min(88, 45 + sell_score * 0.55)
        target = price - 1.5 * atr_safe
        stop = price + 1.0 * atr_safe
    else:
        signal = "HOLD"
        confidence = 50.0
        target = price
        stop = price

    # Confluence = how many independent TA votes agree with the side.
    side_votes = [v for v in votes if (
        (signal == "BUY" and ("bull" in v or "oversold" in v or "lower" in v or "up" in v))
        or (signal == "SELL" and ("bear" in v or "overbought" in v or "upper" in v or "down" in v))
    )]
    confluence = len(side_votes)
    tradeable_now = signal in ("BUY", "SELL") and confluence >= 2 and confidence >= 58

    return {
        "signal": signal,
        "confidence": round(confidence, 1),
        "target_price": _px(target),
        "stop_loss": _px(stop),
        "rsi": rsi,
        "macd": macd,
        "bollinger": bollinger,
        "stochastic": stochastic,
        "atr": atr,
        "momentum_5d": round(mom5, 2),
        "confluence": confluence,
        "tradeable_now": tradeable_now,
        "setup_votes": side_votes,
        "methodology": "rule_based_ta_v3_confluence",
        "disclaimer": "Not financial advice. Signals are heuristic summaries of TA indicators.",
    }
