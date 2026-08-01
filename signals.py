from indicators import (
    calculate_atr,
    calculate_bollinger,
    calculate_macd,
    calculate_rsi,
    calculate_stochastic,
)


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

    buy_score, sell_score = 0, 0

    if rsi < 30:
        buy_score += 25
    elif rsi > 70:
        sell_score += 25

    if macd["macd"] > macd["signal"] and macd["histogram"] > 0:
        buy_score += 20
    elif macd["macd"] < macd["signal"] and macd["histogram"] < 0:
        sell_score += 20

    if bollinger["lower"] > 0 and price <= bollinger["lower"]:
        buy_score += 15
    elif bollinger["upper"] > 0 and price >= bollinger["upper"]:
        sell_score += 15

    if stochastic < 20:
        buy_score += 15
    elif stochastic > 80:
        sell_score += 15

    if change_24h > 1:
        buy_score += min(20, int(change_24h * 4))
    elif change_24h < -1:
        sell_score += min(20, int(abs(change_24h) * 4))

    if volume > 100_000_000:
        if change_24h >= 0:
            buy_score += 5
        else:
            sell_score += 5

    if buy_score > sell_score:
        signal = "BUY"
        confidence = min(85, 45 + buy_score * 0.6)
        target = price * 1.02
        stop = price * 0.98
    elif sell_score > buy_score:
        signal = "SELL"
        confidence = min(85, 45 + sell_score * 0.6)
        target = price * 0.98
        stop = price * 1.02
    else:
        signal = "HOLD"
        confidence = 50.0
        target = price
        stop = price

    def _px(v: float) -> float:
        if v >= 1000:
            return round(v, 2)
        if v >= 1:
            return round(v, 4)
        if v >= 0.01:
            return round(v, 6)
        return round(v, 8)

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
        "methodology": "rule_based_ta_v2",
        "disclaimer": "Not financial advice. Signals are heuristic summaries of TA indicators.",
    }
