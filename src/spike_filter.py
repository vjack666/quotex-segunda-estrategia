"""
spike_filter.py
===============
Filtro anti-spike para velas OTC con saltos anómalos (gaps/glitches).

Objetivo:
- Detectar velas con gap excesivo respecto al cierre previo.
- Detectar cuerpos desproporcionados respecto al contexto reciente.
- Entregar un diagnóstico compacto para penalizar/rechazar candidatos.
"""
from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import List, Optional, Sequence

from models import Candle

# Umbrales por defecto (conservadores para OTC)
DEFAULT_LOOKBACK = 20
DEFAULT_MAX_GAP_PCT = 0.005        # 0.50%
DEFAULT_MAX_BODY_MULT = 6.0         # 6x cuerpo mediano reciente
DEFAULT_MIN_GAP_FOR_BODY_RULE = 0.002  # 0.20%


@dataclass
class SpikeEvent:
    """Diagnóstico de una vela anómala."""
    index: int
    ts: int
    gap_pct: float
    body: float
    body_median: float
    body_mult: float
    open_price: float
    prev_close: float


@dataclass
class SpikeCheckResult:
    """Resultado del chequeo anti-spike."""
    is_anomalous: bool
    event: Optional[SpikeEvent] = None


@dataclass
class SpikeFilterStats:
    """Estadísticas de saneamiento de una serie de velas."""
    input_count: int
    kept_count: int
    dropped_count: int



def detect_spike_anomaly(
    candles: Sequence[Candle],
    *,
    lookback: int = DEFAULT_LOOKBACK,
    max_gap_pct: float = DEFAULT_MAX_GAP_PCT,
    max_body_mult: float = DEFAULT_MAX_BODY_MULT,
    min_gap_for_body_rule: float = DEFAULT_MIN_GAP_FOR_BODY_RULE,
) -> SpikeCheckResult:
    """
    Detecta si hay vela anómala en las últimas N velas.

    Reglas:
    1) Gap rule:
       |open_i - close_{i-1}| / close_{i-1} >= max_gap_pct
    2) Body+gap rule:
       body_i >= max_body_mult * median(body_window)
       y gap_i >= min_gap_for_body_rule
    """
    if len(candles) < 3:
        return SpikeCheckResult(is_anomalous=False)

    start = max(1, len(candles) - max(3, int(lookback)))

    strongest: Optional[SpikeEvent] = None
    strongest_score = -1.0

    for i in range(start, len(candles)):
        curr = candles[i]
        prev = candles[i - 1]

        prev_close = float(prev.close)
        if prev_close <= 0:
            continue

        gap_pct = abs(float(curr.open) - prev_close) / prev_close

        window_bodies = [abs(c.close - c.open) for c in candles[max(0, i - 12):i] if abs(c.close - c.open) > 0]
        if not window_bodies:
            continue

        body_median = float(median(window_bodies))
        if body_median <= 0:
            continue

        body = abs(float(curr.close) - float(curr.open))
        body_mult = body / body_median

        gap_hit = gap_pct >= max_gap_pct
        body_hit = (body_mult >= max_body_mult) and (gap_pct >= min_gap_for_body_rule)
        if not (gap_hit or body_hit):
            continue

        score = max(gap_pct / max_gap_pct, body_mult / max_body_mult)
        evt = SpikeEvent(
            index=i,
            ts=int(curr.ts),
            gap_pct=float(gap_pct),
            body=float(body),
            body_median=float(body_median),
            body_mult=float(body_mult),
            open_price=float(curr.open),
            prev_close=float(prev_close),
        )
        if score > strongest_score:
            strongest = evt
            strongest_score = score

    if strongest is None:
        return SpikeCheckResult(is_anomalous=False)
    return SpikeCheckResult(is_anomalous=True, event=strongest)


def sanitize_spike_candles(
    candles: Sequence[Candle],
    *,
    lookback: int = DEFAULT_LOOKBACK,
    max_gap_pct: float = DEFAULT_MAX_GAP_PCT,
    max_body_mult: float = DEFAULT_MAX_BODY_MULT,
    min_gap_for_body_rule: float = DEFAULT_MIN_GAP_FOR_BODY_RULE,
) -> tuple[List[Candle], SpikeFilterStats]:
    """
    Elimina velas anómalas de una serie OHLC manteniendo el orden temporal.

    Estrategia:
    - Conserva la primera vela válida como ancla.
    - Para cada vela siguiente, evalúa anomalía junto con el contexto reciente
      de velas ya aceptadas.
    - Si es anómala, se descarta; si no, se conserva.
    """
    ordered = sorted(list(candles), key=lambda c: c.ts)
    if not ordered:
        return [], SpikeFilterStats(input_count=0, kept_count=0, dropped_count=0)

    kept: List[Candle] = [ordered[0]]
    dropped = 0

    for curr in ordered[1:]:
        # Contexto mínimo: últimas velas válidas + vela candidata.
        context = kept[-max(3, int(lookback)):] + [curr]
        chk = detect_spike_anomaly(
            context,
            lookback=lookback,
            max_gap_pct=max_gap_pct,
            max_body_mult=max_body_mult,
            min_gap_for_body_rule=min_gap_for_body_rule,
        )
        if chk.is_anomalous and chk.event is not None and chk.event.ts == int(curr.ts):
            dropped += 1
            continue
        kept.append(curr)

    stats = SpikeFilterStats(
        input_count=len(ordered),
        kept_count=len(kept),
        dropped_count=dropped,
    )
    return kept, stats


__all__ = [
    "SpikeEvent",
    "SpikeCheckResult",
    "SpikeFilterStats",
    "detect_spike_anomaly",
    "sanitize_spike_candles",
]
