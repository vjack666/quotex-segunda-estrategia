from __future__ import annotations

from dataclasses import dataclass
import time
from typing import List

from models import Candle

REVERSAL_MIN_STRENGTH = 0.55


@dataclass
class CandleSignal:
    pattern_name: str
    strength: float
    confirms_direction: bool


def _body(c: Candle) -> float:
    return abs(c.close - c.open)


def _upper_wick(c: Candle) -> float:
    return c.high - max(c.open, c.close)


def _lower_wick(c: Candle) -> float:
    return min(c.open, c.close) - c.low


def _total_range(c: Candle) -> float:
    return c.high - c.low


def _body_pct(c: Candle) -> float:
    r = _total_range(c)
    if r <= 0:
        return 0.0
    return _body(c) / r


def _is_bullish(c: Candle) -> bool:
    return c.close > c.open


def _is_bearish(c: Candle) -> bool:
    return c.close < c.open


def _body_high_zone(c: Candle) -> bool:
    r = _total_range(c)
    if r <= 0:
        return False
    body_bottom = min(c.open, c.close)
    return body_bottom >= c.low + (0.55 * r)


def _body_low_zone(c: Candle) -> bool:
    r = _total_range(c)
    if r <= 0:
        return False
    body_top = max(c.open, c.close)
    return body_top <= c.low + (0.45 * r)


def _is_strong_bull(c: Candle) -> bool:
    r = _total_range(c)
    return r > 0 and _is_bullish(c) and (_body(c) / r) >= 0.5


def _is_strong_bear(c: Candle) -> bool:
    r = _total_range(c)
    return r > 0 and _is_bearish(c) and (_body(c) / r) >= 0.5


def _engulfs(curr: Candle, prev: Candle) -> bool:
    prev_min = min(prev.open, prev.close)
    prev_max = max(prev.open, prev.close)
    curr_min = min(curr.open, curr.close)
    curr_max = max(curr.open, curr.close)
    return curr_min <= prev_min and curr_max >= prev_max


def detect_reversal_pattern(candles_1m: List[Candle], direction: str) -> CandleSignal:
    """
    Analiza SOLO la última vela completa (candles_1m[-2]).
    direction esperado: "put" o "call".
    """
    if len(candles_1m) < 3:
        return CandleSignal("none", 0.0, False)

    curr = candles_1m[-2]
    prev = candles_1m[-3]

    body = _body(curr)
    total_range = _total_range(curr)
    if total_range <= 0:
        return CandleSignal("none", 0.0, False)

    upper_wick = _upper_wick(curr)
    lower_wick = _lower_wick(curr)
    body_pct = body / total_range

    if direction == "put":
        # Bearish Engulfing (0.85)
        if _is_bearish(curr) and _is_bullish(prev) and _engulfs(curr, prev):
            return CandleSignal("bearish_engulfing", 0.85, True)

        # Shooting Star (0.75)
        if (
            _is_bullish(prev)
            and body > 0
            and _body_low_zone(curr)
            and upper_wick >= (2.0 * body)
            and lower_wick < (0.2 * total_range)
        ):
            return CandleSignal("shooting_star", 0.75, True)

        # Evening Star simplificado (0.65)
        if body_pct < 0.2 and _is_strong_bull(prev):
            return CandleSignal("evening_star_simple", 0.65, True)

        # Bearish inverted hammer (0.55)
        if body > 0 and _body_low_zone(curr) and upper_wick >= (3.0 * body):
            return CandleSignal("bearish_inverted_hammer", 0.55, True)

        # Patrones alcistas que contradicen PUT
        if _is_bullish(curr) and _is_bearish(prev) and _engulfs(curr, prev):
            return CandleSignal("bullish_engulfing", 0.85, False)
        if (
            _is_bearish(prev)
            and body > 0
            and _body_high_zone(curr)
            and lower_wick >= (2.0 * body)
            and upper_wick < (0.2 * total_range)
        ):
            return CandleSignal("hammer", 0.75, False)
        if body_pct < 0.2 and _is_strong_bear(prev):
            return CandleSignal("morning_star_simple", 0.65, False)
        if body > 0 and _body_high_zone(curr) and lower_wick >= (3.0 * body):
            return CandleSignal("bullish_hammer", 0.55, False)

        return CandleSignal("none", 0.0, False)

    if direction == "call":
        # Bullish Engulfing (0.85)
        if _is_bullish(curr) and _is_bearish(prev) and _engulfs(curr, prev):
            return CandleSignal("bullish_engulfing", 0.85, True)

        # Hammer (0.75)
        if (
            _is_bearish(prev)
            and body > 0
            and _body_high_zone(curr)
            and lower_wick >= (2.0 * body)
            and upper_wick < (0.2 * total_range)
        ):
            return CandleSignal("hammer", 0.75, True)

        # Morning Star simplificado (0.65)
        if body_pct < 0.2 and _is_strong_bear(prev):
            return CandleSignal("morning_star_simple", 0.65, True)

        # Bullish hammer (0.55)
        if body > 0 and _body_high_zone(curr) and lower_wick >= (3.0 * body):
            return CandleSignal("bullish_hammer", 0.55, True)

        # Patrones bajistas que contradicen CALL
        if _is_bearish(curr) and _is_bullish(prev) and _engulfs(curr, prev):
            return CandleSignal("bearish_engulfing", 0.85, False)
        if (
            _is_bullish(prev)
            and body > 0
            and _body_low_zone(curr)
            and upper_wick >= (2.0 * body)
            and lower_wick < (0.2 * total_range)
        ):
            return CandleSignal("shooting_star", 0.75, False)
        if body_pct < 0.2 and _is_strong_bull(prev):
            return CandleSignal("evening_star_simple", 0.65, False)
        if body > 0 and _body_low_zone(curr) and upper_wick >= (3.0 * body):
            return CandleSignal("bearish_inverted_hammer", 0.55, False)

        return CandleSignal("none", 0.0, False)

    return CandleSignal("none", 0.0, False)


def explain_no_pattern_reason(candles_1m: List[Candle], direction: str) -> str:
    """Devuelve una razón corta cuando detect_reversal_pattern termina en 'none'."""
    if len(candles_1m) < 3:
        return f"insuficientes velas 1m ({len(candles_1m)}/3)"

    curr = candles_1m[-2]
    prev = candles_1m[-3]
    total_range = _total_range(curr)
    if total_range <= 0:
        return "vela 1m cerrada sin rango (high==low)"

    if direction not in {"put", "call"}:
        return f"dirección inválida '{direction}'"

    body = _body(curr)
    upper_wick = _upper_wick(curr)
    lower_wick = _lower_wick(curr)
    body_pct = body / total_range if total_range > 0 else 0.0
    prev_side = "bull" if _is_bullish(prev) else ("bear" if _is_bearish(prev) else "doji")
    curr_side = "bull" if _is_bullish(curr) else ("bear" if _is_bearish(curr) else "doji")

    if direction == "put":
        expected = "bearish_engulfing|shooting_star|evening_star_simple|bearish_inverted_hammer"
    else:
        expected = "bullish_engulfing|hammer|morning_star_simple|bullish_hammer"

    return (
        f"sin match [{expected}] prev={prev_side} curr={curr_side} "
        f"body_pct={body_pct:.2f} up/body={(upper_wick / max(body, 1e-9)):.2f} "
        f"down/body={(lower_wick / max(body, 1e-9)):.2f}"
    )


async def fetch_candles_1m(client, asset: str, count: int = 10) -> List[Candle]:
    end_time = time.time()
    tf_sec = 60
    offset = count * tf_sec
    try:
        raw_list = await client.get_candles(asset, end_time, offset, tf_sec)
    except Exception:
        return []
    if not raw_list:
        return []

    candles: List[Candle] = []
    for raw in raw_list:
        if not isinstance(raw, dict):
            continue
        try:
            candle = Candle(
                ts=int(raw["time"]),
                open=float(raw["open"]),
                high=float(raw["high"]),
                low=float(raw["low"]),
                close=float(raw["close"]),
            )
        except (KeyError, TypeError, ValueError):
            continue
        if candle.high > 0:
            candles.append(candle)

    return sorted(candles, key=lambda c: c.ts)
