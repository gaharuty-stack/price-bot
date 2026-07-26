import math


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
    return {
        "macd": round(macd_val, 4),
        "signal": round(signal_val, 4),
        "histogram": round(macd_val - signal_val, 4),
    }


def calculate_bollinger(closes: list[float], period: int = 20) -> dict:
    if len(closes) < period:
        return {"upper": 0.0, "middle": 0.0, "lower": 0.0}

    recent = closes[-period:]
    middle = sum(recent) / period
    variance = sum((x - middle) ** 2 for x in recent) / period
    std = math.sqrt(variance)
    return {
        "upper": round(middle + 2 * std, 2),
        "middle": round(middle, 2),
        "lower": round(middle - 2 * std, 2),
    }


def calculate_atr(ohlc: list[list[float]], period: int = 14) -> float:
    if len(ohlc) < period + 1:
        return 0.0

    true_ranges = []
    for i in range(1, len(ohlc)):
        high, low, close_prev = ohlc[i][1], ohlc[i][2], ohlc[i - 1][3]
        tr = max(high - low, abs(high - close_prev), abs(low - close_prev))
        true_ranges.append(tr)

    if len(true_ranges) < period:
        return 0.0

    return round(sum(true_ranges[-period:]) / period, 2)


def calculate_stochastic(ohlc: list[list[float]], period: int = 14) -> float:
    if len(ohlc) < period:
        return 50.0

    window = ohlc[-period:]
    highs = [row[1] for row in window]
    lows = [row[2] for row in window]
    close = window[-1][3]
    high, low = max(highs), min(lows)

    if high == low:
        return 50.0

    return round(((close - low) / (high - low)) * 100, 1)
