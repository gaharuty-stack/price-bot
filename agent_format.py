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


def build_agent_brief(data: dict) -> dict:
    indicators = data["indicators"]
    rsi = indicators["rsi"]
    macd = indicators["macd"]
    bollinger = indicators["bollinger"]
    change = data["change_24h_percent"]
    signal = data["signal"]
    price = data["price_usd"]

    parts = [
        _rsi_label(rsi),
        _macd_label(macd),
        _bollinger_label(price, bollinger),
        f"24h change {change:+.2f}%",
    ]
    reason = "; ".join(parts)

    if signal == "BUY":
        action_hint = f"Bullish bias ({data['confidence']}% confidence). Watch target ${data['target_price']}, stop ${data['stop_loss']}."
    elif signal == "SELL":
        action_hint = f"Bearish bias ({data['confidence']}% confidence). Watch target ${data['target_price']}, stop ${data['stop_loss']}."
    else:
        action_hint = "No strong edge. Wait for clearer RSI/MACD alignment before acting."

    return {
        "coin": data.get("ticker") or data.get("coin_id", ""),
        "price_usd": price,
        "change_24h": f"{change:+.2f}%",
        "signal": signal,
        "confidence": data["confidence"],
        "reason": reason,
        "action_hint": action_hint,
        "target_price": data["target_price"],
        "stop_loss": data["stop_loss"],
    }
