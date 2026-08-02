import math


def _smart_price(value: float) -> float:
    """Preserve meaningful digits for BTC and micro-caps (SHIB/PEPE)."""
    v = float(value)
    if v >= 1000:
        return round(v, 2)
    if v >= 1:
        return round(v, 4)
    if v >= 0.01:
        return round(v, 6)
    return round(v, 8)


def ema(values: list[float], period: int) -> list[float]:
    if len(values) < period:
        return []

    multiplier = 2 / (period + 1)
    result = [sum(values[:period]) / period]
    for price in values[period:]:
        result.append(price * multiplier + result[-1] * (1 - multiplier))
    return result


def calculate_rsi(closes: list[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0

    gains, losses = 0.0, 0.0
    for i in range(1, period + 1):
        diff = closes[i] - closes[i - 1]
        if diff >= 0:
            gains += diff
        else:
            losses -= diff

    avg_gain = gains / period
    avg_loss = losses / period
    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 1)


def calculate_macd(closes: list[float]) -> dict:
    if len(closes) < 26:
        return {"macd": 0.0, "signal": 0.0, "histogram": 0.0}

    ema12 = ema(closes, 12)
    ema26 = ema(closes, 26)
    offset = len(ema12) - len(ema26)
    macd_line = [a - b for a, b in zip(ema12[offset:], ema26)]

    if not macd_line:
        return {"macd": 0.0, "signal": 0.0, "histogram": 0.0}

    signal_line = ema(macd_line, 9)
    if not signal_line:
        return {"macd": 0.0, "signal": 0.0, "histogram": 0.0}

    macd_val = macd_line[-1]
    signal_val = signal_line[-1]
    # More decimals for tiny-priced assets so histogram is not always 0.
    places = 8 if abs(macd_val) < 0.01 else 4
    return {
        "macd": round(macd_val, places),
        "signal": round(signal_val, places),
        "histogram": round(macd_val - signal_val, places),
    }


def calculate_bollinger(closes: list[float], period: int = 20) -> dict:
    if len(closes) < period:
        return {"upper": 0.0, "middle": 0.0, "lower": 0.0}

    recent = closes[-period:]
    middle = sum(recent) / period
    variance = sum((x - middle) ** 2 for x in recent) / period
    std = math.sqrt(variance)
    return {
        "upper": _smart_price(middle + 2 * std),
        "middle": _smart_price(middle),
        "lower": _smart_price(middle - 2 * std),
    }


def calculate_atr(ohlc: list[list[float]], period: int = 14) -> float:
    if len(ohlc) < period + 1:
        return 0.0

    # CoinGecko OHLC: [ts, open, high, low, close]
    true_ranges = []
    for i in range(1, len(ohlc)):
        if len(ohlc[i]) < 5 or len(ohlc[i - 1]) < 5:
            continue
        high, low, close_prev = ohlc[i][2], ohlc[i][3], ohlc[i - 1][4]
        tr = max(high - low, abs(high - close_prev), abs(low - close_prev))
        true_ranges.append(tr)

    if len(true_ranges) < period:
        return 0.0

    return _smart_price(sum(true_ranges[-period:]) / period)


def calculate_stochastic(ohlc: list[list[float]], period: int = 14) -> float:
    if len(ohlc) < period:
        return 50.0

    # CoinGecko OHLC: [ts, open, high, low, close]
    window = [row for row in ohlc[-period:] if len(row) >= 5]
    if len(window) < period:
        return 50.0

    highs = [row[2] for row in window]
    lows = [row[3] for row in window]
    close = window[-1][4]
    high, low = max(highs), min(lows)

    if high == low:
        return 50.0

    return round(((close - low) / (high - low)) * 100, 1)
