"""
Cálculos de indicadores técnicos para la estrategia de 30 segundos.
Todas las funciones reciben listas de floats y retornan un float.
"""
from typing import List, Optional, Tuple


def rsi(closes: List[float], period: int = 7) -> float:
    """RSI clásico. Retorna 50.0 si no hay suficientes datos."""
    if len(closes) < period + 1:
        return 50.0
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [d for d in deltas[-period:] if d > 0]
    losses = [-d for d in deltas[-period:] if d < 0]
    avg_gain = sum(gains) / period if gains else 0.0
    avg_loss = sum(losses) / period if losses else 1e-10
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def ema(prices: List[float], period: int) -> float:
    """EMA del último valor usando suavizado exponencial estándar."""
    if not prices:
        return 0.0
    if len(prices) < period:
        return prices[-1]
    k = 2.0 / (period + 1)
    result = sum(prices[:period]) / period
    for price in prices[period:]:
        result = price * k + result * (1.0 - k)
    return result


def bollinger_bands(
    closes: List[float], period: int = 20, std_dev: float = 2.0
) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """Retorna (upper, middle, lower). None si no hay datos suficientes."""
    if len(closes) < period:
        return None, None, None
    window = closes[-period:]
    middle = sum(window) / period
    variance = sum((p - middle) ** 2 for p in window) / period
    std = variance ** 0.5
    upper = middle + std_dev * std
    lower = middle - std_dev * std
    return upper, middle, lower


def stochastic_k(
    highs: List[float], lows: List[float], closes: List[float], k_period: int = 5
) -> float:
    """Calcula %K del oscilador estocástico. Retorna 50.0 si no hay datos."""
    if len(closes) < k_period:
        return 50.0
    highest_high = max(highs[-k_period:])
    lowest_low = min(lows[-k_period:])
    if highest_high == lowest_low:
        return 50.0
    return 100.0 * (closes[-1] - lowest_low) / (highest_high - lowest_low)


def stochastic_d(
    highs: List[float], lows: List[float], closes: List[float],
    k_period: int = 5, d_period: int = 3
) -> Tuple[float, float]:
    """Retorna (%K, %D). Calcula %D como SMA de los últimos d_period %K."""
    if len(closes) < k_period + d_period - 1:
        k = stochastic_k(highs, lows, closes, k_period)
        return k, k

    k_values = []
    for i in range(d_period):
        idx = len(closes) - d_period + i + 1
        k_val = stochastic_k(highs[:idx], lows[:idx], closes[:idx], k_period)
        k_values.append(k_val)

    current_k = k_values[-1]
    current_d = sum(k_values) / len(k_values)
    return current_k, current_d


def atr(
    highs: List[float], lows: List[float], closes: List[float], period: int = 7
) -> float:
    """Average True Range. Retorna 0.0 si no hay datos suficientes."""
    if len(closes) < 2:
        return 0.0
    true_ranges = []
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        true_ranges.append(tr)
    window = true_ranges[-period:]
    return sum(window) / len(window) if window else 0.0
