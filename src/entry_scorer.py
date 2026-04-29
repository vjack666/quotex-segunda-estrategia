from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from statistics import mean
from typing import List, Tuple

from models import Candle, ConsolidationZone  # shared types — avoids circular import


# ─────────────────────────────────────────────────────────────────────────────
#  MODO DE SEÑAL
# ─────────────────────────────────────────────────────────────────────────────

class SignalMode(Enum):
    REBOUND = "rebound"    # rebote en extremo de zona
    BREAKOUT = "breakout"  # ruptura de zona con fuerza


# ─────────────────────────────────────────────────────────────────────────────
#  UMBRALES Y PESOS
# ─────────────────────────────────────────────────────────────────────────────

SCORE_THRESHOLD = 65
MAX_ENTRIES_CYCLE = 1

# Pesos para cada modo (suman 100)
WEIGHTS_REBOUND: dict[str, int] = {
    "compression": 20,
    "bounce":      35,
    "trend":       25,
    "payout":      20,
}

WEIGHTS_BREAKOUT: dict[str, int] = {
    "compression": 15,
    "momentum":    35,
    "trend":       30,
    "payout":      20,
}

RANGE_EXCELLENT = 0.0010
RANGE_GOOD      = 0.0015
RANGE_OK        = 0.0020
RANGE_MAX       = 0.0030

BOUNCE_CANDLES = 3
WICK_RATIO_MIN = 0.4

TREND_EMA_FAST = 10
TREND_EMA_SLOW = 20

PAYOUT_MIN = 80
PAYOUT_MAX = 95

# Contexto histórico: niveles swing en H1 (cubre ~3 días con 80 velas)
HIST_LEVEL_TOUCH_PCT   = 0.0015  # 0.15% — proximidad para considerar "en el nivel"
HIST_LEVEL_SWING_N     = 3       # velas a cada lado para confirmar pivote swing
HIST_LEVEL_PUT_BONUS   = 18.0    # bonus PUT cuando precio choca con alto histórico (resistencia)
HIST_LEVEL_CALL_BONUS  = 12.0    # bonus CALL cuando precio choca con bajo histórico (soporte)
HIST_LEVEL_PENALTY     = 12.0    # penalización si operamos contra el nivel histórico

# Ajuste por antigüedad de zona (minutos → puntos: negativos penalizan, positivos bonifican)


# ─────────────────────────────────────────────────────────────────────────────
#  ESTRUCTURA DE CANDIDATO
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class CandidateEntry:
    asset: str
    payout: int
    zone: ConsolidationZone
    direction: str
    candles: List[Candle]
    score: float = 0.0
    score_breakdown: dict = field(default_factory=dict)
    reversal_pattern: str = "none"
    reversal_strength: float = 0.0
    reversal_confirms: bool = False
    mode: SignalMode = SignalMode.REBOUND
    # Velas H1 históricas (hasta ~3 días) para detección de altos/bajos antiguos.
    candles_h1: List[Candle] = field(default_factory=list)

    def __str__(self) -> str:
        bd = self.score_breakdown
        mode_label = self.mode.value
        return (
            f"{self.asset:20s} {self.direction.upper():4s} [{mode_label}] "
            f"SCORE={self.score:.1f}/100 "
            f"[compression={bd.get('compression', 0):.1f} "
            f"bounce/momentum={bd.get('bounce', bd.get('momentum', 0)):.1f} "
            f"trend={bd.get('trend', 0):.1f} "
            f"payout={bd.get('payout', 0):.1f}]"
        )


# ─────────────────────────────────────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _ema(values: List[float], period: int) -> List[float]:
    if len(values) < period:
        return []
    k = 2 / (period + 1)
    result = [mean(values[:period])]
    for v in values[period:]:
        result.append(v * k + result[-1] * (1 - k))
    return result


def _clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))


def _normalize(val: float, lo: float, hi: float) -> float:
    if hi <= lo:
        return 0.0
    return _clamp((val - lo) / (hi - lo), 0.0, 1.0)


# ─────────────────────────────────────────────────────────────────────────────
#  COMPONENTES COMPARTIDOS
# ─────────────────────────────────────────────────────────────────────────────

def _score_compression(zone: ConsolidationZone, weight: int) -> float:
    r = zone.range_pct

    if r <= RANGE_EXCELLENT:
        ratio = 1.0
    elif r <= RANGE_GOOD:
        ratio = 0.85 + 0.15 * (RANGE_GOOD - r) / (RANGE_GOOD - RANGE_EXCELLENT)
    elif r <= RANGE_OK:
        ratio = 0.60 + 0.25 * (RANGE_OK - r) / (RANGE_OK - RANGE_GOOD)
    elif r <= RANGE_MAX:
        ratio = 0.0 + 0.60 * (RANGE_MAX - r) / (RANGE_MAX - RANGE_OK)
    else:
        ratio = 0.0

    bars_bonus = _normalize(zone.bars_inside, 15, 30) * 0.15
    ratio = _clamp(ratio + bars_bonus, 0.0, 1.0)

    return round(ratio * weight, 2)


def _score_payout(payout: int, weight: int) -> float:
    ratio = _normalize(payout, PAYOUT_MIN, PAYOUT_MAX)
    return round(ratio * weight, 2)


def _score_trend(candles: List[Candle], direction: str, weight: int) -> float:
    needed = TREND_EMA_SLOW + 5
    if len(candles) < needed:
        return weight * 0.5

    closes = [c.close for c in candles[-40:]]
    ema_fast = _ema(closes, TREND_EMA_FAST)
    ema_slow = _ema(closes, TREND_EMA_SLOW)

    if not ema_fast or not ema_slow:
        return weight * 0.5

    ef_last = ema_fast[-1]
    es_last = ema_slow[-1]

    if len(ema_fast) >= 5:
        slope = (ema_fast[-1] - ema_fast[-5]) / (ema_fast[-5] or 1)
    else:
        slope = 0.0

    if direction == "put":
        aligned = ef_last < es_last
        slope_support = slope < 0
    else:
        aligned = ef_last > es_last
        slope_support = slope > 0

    if aligned and slope_support:
        ratio = 0.85 + 0.15 * _normalize(abs(slope) * 100, 0, 0.5)
    elif aligned and not slope_support:
        ratio = 0.55
    elif not aligned and slope_support:
        ratio = 0.35
    else:
        ratio = 0.10

    price = closes[-1]
    if direction == "put" and price < ef_last:
        ratio = _clamp(ratio + 0.10, 0.0, 1.0)
    elif direction == "call" and price > ef_last:
        ratio = _clamp(ratio + 0.10, 0.0, 1.0)

    return round(ratio * weight, 2)


# ─────────────────────────────────────────────────────────────────────────────
#  COMPONENTES ESPECÍFICOS POR MODO
# ─────────────────────────────────────────────────────────────────────────────

def _score_bounce(candles: List[Candle], zone: ConsolidationZone, direction: str, weight: int) -> float:
    """Componente REBOUND: mide calidad de mecha en el extremo y momentum de velas recientes."""
    if len(candles) < BOUNCE_CANDLES + 1:
        return 0.0

    last = candles[-1]
    total_range = last.high - last.low
    if total_range == 0:
        wick_score = 0.0
    elif direction == "put":
        upper_wick = last.high - max(last.open, last.close)
        wick_score = _normalize(upper_wick / total_range, WICK_RATIO_MIN, 0.8)
    else:
        lower_wick = min(last.open, last.close) - last.low
        wick_score = _normalize(lower_wick / total_range, WICK_RATIO_MIN, 0.8)

    recent = candles[-(BOUNCE_CANDLES + 1):]
    if direction == "put":
        bearish = sum(1 for c in recent if c.close < c.open)
        momentum_score = bearish / len(recent)
    else:
        bullish = sum(1 for c in recent if c.close > c.open)
        momentum_score = bullish / len(recent)

    combined = 0.6 * wick_score + 0.4 * momentum_score
    return round(combined * weight, 2)


def _score_momentum(candles: List[Candle], weight: int) -> float:
    """
    Componente BREAKOUT: mide fuerza de la vela de ruptura vs historial.
    Interpolado linealmente: cuerpo = 1.0× avg → 0 pts; cuerpo = 2.5× avg → 100 pts.
    """
    if len(candles) < 2:
        return 0.0

    breakout_candle = candles[-1]
    lookback = candles[-(11):-1] if len(candles) >= 11 else candles[:-1]
    if not lookback:
        return round(weight * 0.5, 2)

    avg = mean(c.body for c in lookback) or 0.0
    if avg == 0:
        return round(weight * 0.5, 2)

    ratio = breakout_candle.body / avg  # 1.0x a 2.5x
    normalized = _normalize(ratio, 1.0, 2.5)
    return round(normalized * weight, 2)


def _age_adjustment(zone: ConsolidationZone) -> float:
    """Ajuste por antigüedad de zona. Negativo penaliza, positivo bonifica."""
    age = zone.age_minutes
    if age < 10.0:
        return -12.0
    if age < 30.0:
        return -5.0
    if age <= 90.0:
        return 0.0
    return 5.0


def detect_swing_levels(
    candles_h1: List[Candle],
    n: int = HIST_LEVEL_SWING_N,
) -> tuple:
    """
    Detecta pivotes swing high/low en velas H1 (context histórico de 2-3 días).

    Un swing high: la vela i tiene el HIGH más alto de las N velas anteriores y N siguientes.
    Un swing low:  la vela i tiene el LOW más bajo  de las N velas anteriores y N siguientes.

    Retorna (List[float] swing_highs, List[float] swing_lows).
    """
    highs: List[float] = []
    lows: List[float] = []
    if len(candles_h1) < 2 * n + 1:
        return highs, lows
    for i in range(n, len(candles_h1) - n):
        c = candles_h1[i]
        left  = candles_h1[i - n: i]
        right = candles_h1[i + 1: i + n + 1]
        if all(c.high >= lc.high for lc in left) and all(c.high >= rc.high for rc in right):
            highs.append(c.high)
        if all(c.low <= lc.low for lc in left) and all(c.low <= rc.low for rc in right):
            lows.append(c.low)
    return highs, lows


def _score_historical_level(entry: "CandidateEntry") -> float:
    """
    Ajuste de score por proximidad a altos/bajos históricos detectados en H1.

    Lógica:
    - Precio cerca de un SWING HIGH (resistencia histórica):
        → PUT alineado:  +HIST_LEVEL_PUT_BONUS  (mercado rechaza el nivel, ideal para venta)
        → CALL contra:   -HIST_LEVEL_PENALTY     (llamada contra resistencia, penalizar)
    - Precio cerca de un SWING LOW (soporte histórico):
        → CALL alineado: +HIST_LEVEL_CALL_BONUS  (soporte histórico, ideal para compra)
        → PUT contra:    -HIST_LEVEL_PENALTY      (venta contra soporte, penalizar)
    """
    if not entry.candles_h1:
        return 0.0

    # Precio actual: cierre de la última vela disponible
    if entry.candles:
        price = float(entry.candles[-1].close)
    else:
        price = float(entry.candles_h1[-1].close)

    swing_highs, swing_lows = detect_swing_levels(entry.candles_h1)
    if not swing_highs and not swing_lows:
        return 0.0

    tol = price * HIST_LEVEL_TOUCH_PCT

    near_high = any(abs(price - h) <= tol for h in swing_highs)
    near_low  = any(abs(price - l) <= tol for l in swing_lows)

    if near_high:
        return HIST_LEVEL_PUT_BONUS if entry.direction == "put" else -HIST_LEVEL_PENALTY
    if near_low:
        return HIST_LEVEL_CALL_BONUS if entry.direction == "call" else -HIST_LEVEL_PENALTY
    return 0.0


# ─────────────────────────────────────────────────────────────────────────────
#  FUNCIÓN PRINCIPAL DE SCORING
# ─────────────────────────────────────────────────────────────────────────────

def score_candidate(
    entry: CandidateEntry,
    mode: SignalMode | None = None,
) -> float:
    """
    Calcula el score del candidato usando los pesos del modo activo.

    Si `mode` no se pasa explícitamente, se usa `entry.mode`.
    El score se almacena en `entry.score` y el desglose en `entry.score_breakdown`.
    """
    effective_mode = mode if mode is not None else entry.mode
    entry.mode = effective_mode  # asegurar consistencia

    if effective_mode == SignalMode.BREAKOUT:
        w = WEIGHTS_BREAKOUT
        s_comp     = _score_compression(entry.zone, w["compression"])
        s_momentum = _score_momentum(entry.candles, w["momentum"])
        s_trend    = _score_trend(entry.candles, entry.direction, w["trend"])
        s_payout   = _score_payout(entry.payout, w["payout"])
        age_adj    = _age_adjustment(entry.zone)
        hist_adj   = _score_historical_level(entry)

        total = s_comp + s_momentum + s_trend + s_payout + age_adj + hist_adj
        entry.score = round(total, 1)
        entry.score_breakdown = {
            "compression": s_comp,
            "momentum":    s_momentum,
            "trend":       s_trend,
            "payout":      s_payout,
            "age_adjustment": age_adj,
            # alias para compatibilidad con código que lee "bounce"
            "bounce":      s_momentum,
        }
        if hist_adj != 0.0:
            entry.score_breakdown["hist_level"] = round(hist_adj, 1)
    else:
        w = WEIGHTS_REBOUND
        s_comp    = _score_compression(entry.zone, w["compression"])
        s_bounce  = _score_bounce(entry.candles, entry.zone, entry.direction, w["bounce"])
        s_trend   = _score_trend(entry.candles, entry.direction, w["trend"])
        s_payout  = _score_payout(entry.payout, w["payout"])
        age_adj   = _age_adjustment(entry.zone)
        hist_adj  = _score_historical_level(entry)

        total = s_comp + s_bounce + s_trend + s_payout + age_adj + hist_adj
        entry.score = round(total, 1)
        entry.score_breakdown = {
            "compression": s_comp,
            "bounce":      s_bounce,
            "trend":       s_trend,
            "payout":      s_payout,
            "age_adjustment": age_adj,
        }
        if hist_adj != 0.0:
            entry.score_breakdown["hist_level"] = round(hist_adj, 1)

    return entry.score


def select_best(
    candidates: List[CandidateEntry],
    max_entries: int = MAX_ENTRIES_CYCLE,
    threshold: int = SCORE_THRESHOLD,
) -> Tuple[List[CandidateEntry], List[CandidateEntry]]:
    passed = [c for c in candidates if c.score >= threshold]
    failed = [c for c in candidates if c.score < threshold]

    passed.sort(key=lambda x: -x.score)
    failed.sort(key=lambda x: -x.score)

    selected = passed[:max_entries]
    rejected = passed[max_entries:] + failed

    return selected, rejected


def explain_score(entry: CandidateEntry, threshold: int = SCORE_THRESHOLD) -> str:
    bd = entry.score_breakdown
    mode_label = entry.mode.value.upper()
    age_adjustment = bd.get("age_adjustment", 0.0)
    age_txt = f" (ajuste antigüedad zona: {age_adjustment:+.1f})" if age_adjustment != 0 else ""

    hist_adj = bd.get("hist_level", 0.0)
    hist_txt = ""
    if hist_adj > 0:
        hist_txt = f" | 🟣 Alto histórico resistencia → {hist_adj:+.1f} pts"
    elif hist_adj < 0:
        hist_txt = f" | 🔴 Contra nivel histórico → {hist_adj:+.1f} pts"

    if entry.mode == SignalMode.BREAKOUT:
        w = WEIGHTS_BREAKOUT
        lines = [
            f"+- SCORE BREAKDOWN [{mode_label}]: {entry.asset} ({entry.direction.upper()}) -",
            f"| Score total   : {entry.score:5.1f} / 100  {'OK' if entry.score >= threshold else 'SKIP'}{age_txt}{hist_txt}",
            f"| Min threshold : {threshold}",
            f"| S1 Compresión : {bd.get('compression', 0):5.1f} / {w['compression']} (range={entry.zone.range_pct*100:.3f}% bars={entry.zone.bars_inside})",
            f"| S2 Momentum   : {bd.get('momentum', 0):5.1f} / {w['momentum']}",
            f"| S3 Tendencia  : {bd.get('trend', 0):5.1f} / {w['trend']}",
            f"| S4 Payout     : {bd.get('payout', 0):5.1f} / {w['payout']} (payout={entry.payout}%)",
            f"| Zona edad     : {entry.zone.age_minutes:.0f} min → ajuste {age_adjustment:+.1f} pts",
            f"| Alto histórico : ajuste {hist_adj:+.1f} pts  ({'PUT alineado con resistencia' if hist_adj > 0 else 'CALL contra resistencia' if hist_adj < 0 else 'sin nivel próximo'})",
            "+--------------------------------------------",
        ]
    else:
        w = WEIGHTS_REBOUND
        lines = [
            f"+- SCORE BREAKDOWN [{mode_label}]: {entry.asset} ({entry.direction.upper()}) -",
            f"| Score total   : {entry.score:5.1f} / 100  {'OK' if entry.score >= threshold else 'SKIP'}{age_txt}{hist_txt}",
            f"| Min threshold : {threshold}",
            f"| S1 Compresión : {bd.get('compression', 0):5.1f} / {w['compression']} (range={entry.zone.range_pct*100:.3f}% bars={entry.zone.bars_inside})",
            f"| S2 Rebote     : {bd.get('bounce', 0):5.1f} / {w['bounce']}",
            f"| S3 Tendencia  : {bd.get('trend', 0):5.1f} / {w['trend']}",
            f"| S4 Payout     : {bd.get('payout', 0):5.1f} / {w['payout']} (payout={entry.payout}%)",
            f"| Zona edad     : {entry.zone.age_minutes:.0f} min → ajuste {age_adjustment:+.1f} pts",
            f"| Alto histórico : ajuste {hist_adj:+.1f} pts  ({'PUT alineado con resistencia' if hist_adj > 0 else 'CALL contra resistencia' if hist_adj < 0 else 'sin nivel próximo'})",
            "+--------------------------------------------",
        ]
    return "\n".join(lines)
