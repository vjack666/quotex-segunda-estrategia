"""
entry_decision_engine.py — Motor de decisión de entrada modular e independiente.

RESPONSABILIDAD:
- Recibe candidato + contexto
- Evalúa todos los vetos (9 filtros binarios)
- Clasifica en categoría (A/B/C/REJECT)
- Devuelve decisión estructurada con trazabilidad

INTEGRACIÓN:
- Reemplaza lógica dentro de consolidation_bot._pre_validate_entry()
- SIN tocar: ejecución, websocket, async, monitor_live, reconexión

BENEFICIOS:
- Testeable aisladamente
- Trazabilidad completa
- Preparado para: modo conservador, shadow mode, estadísticas
"""

from dataclasses import dataclass, field
from collections.abc import Callable
from typing import Any, List, Mapping, Sequence, Optional, TypedDict
from enum import Enum
import logging

from models import Candle, ConsolidationZone, CandidateEntry
from zone_memory import HistoricalZone, score_zone_memory
from spike_filter import detect_spike_anomaly
from candle_patterns import CandleSignal

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# ENUMS Y TIPOS
# ─────────────────────────────────────────────────────────────────────────────

class EntryCategory(Enum):
    """Categoría de setup probabilístico."""
    PREMIUM = "A"      # Setup premium (>80% confianza)
    SOLID = "B"        # Setup sólido (60-80% confianza)
    ACCEPTABLE = "C"   # Setup aceptable (55-60% confianza)
    REJECT = "REJECT"  # No cumple mínimos


class VetoType(Enum):
    """Tipos de veto en la validación."""
    NO_CANDLES = "no_candles"
    ACTIVE_OPERATION = "active_operation"
    CYCLE_LIMIT = "cycle_limit"
    PAYOUT_MIN = "payout"
    SCORE_MIN = "score"
    SPIKE_1M = "spike_1m"
    SPIKE_5M = "spike_5m"
    HTF_MISSING = "htf_alignment"
    HTF_MISALIGNED = "htf_alignment"
    PATTERN_MISSING = "candle_pattern"
    PATTERN_WEAK = "candle_pattern"
    ZONE_TOO_NEW = "zone_age"
    ZONE_MEMORY_WALL = "zone_memory"


@dataclass
class VetoResult:
    """Resultado de evaluación de un veto."""
    veto_type: VetoType
    passed: bool
    reason: str = ""
    value: Optional[float] = None  # Valor que falló (score, strength, etc)
    threshold: Optional[float] = None  # Umbral comparado


@dataclass
class EntryDecision:
    """Decisión final de entrada estructurada."""
    approved: bool  # ¿Se ejecuta la orden?
    category: EntryCategory  # A/B/C/REJECT
    reason: str  # Explicación en lenguaje natural
    
    # Trazabilidad
    vetos: List[VetoResult] = field(default_factory=list)
    scores: dict = field(default_factory=dict)  # Score breakdown
    profile: str = "strict"  # "strict" o "recovery" (futuro)
    
    # Datos para registro en journal
    htf_aligned: bool = False
    pattern_name: str = "none"
    pattern_strength: float = 0.0
    zone_age_min: float = 0.0
    zone_memory_adj: float = 0.0
    payout_value: int = 0
    score_value: float = 0.0


class EntryContext(TypedDict, total=False):
    """Contexto opcional para evaluación de entrada."""
    candles_5m: Sequence[Candle]
    candles_1m: Sequence[Candle]
    candles_15m: Sequence[Candle]
    payout: int
    losses_in_cycle: int


# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURACIÓN DE CATEGORÍAS
# ─────────────────────────────────────────────────────────────────────────────

CATEGORY_RULES = {
    EntryCategory.PREMIUM: {
        "description": "Setup premium (máxima calidad)",
        "score_min": 80,
        "pattern_strength_min": 0.75,
        "payout_min": 87,
        "zone_age_min": 45,
        "htf_required": True,
        "conditions": "score≥80 AND strength≥0.75 AND payout≥87 AND age≥45min AND HTF aligned"
    },
    EntryCategory.SOLID: {
        "description": "Setup sólido (calidad media-alta)",
        "score_min": 73,
        "pattern_strength_min": 0.60,
        "payout_min": 84,
        "zone_age_min": 20,
        "htf_required": True,
        "conditions": "score≥73 AND strength≥0.60 AND payout≥84 AND age≥20min AND HTF aligned"
    },
    EntryCategory.ACCEPTABLE: {
        "description": "Setup aceptable (calidad media)",
        "score_min": 70,
        "pattern_strength_min": 0.55,
        "payout_min": 82,
        "zone_age_min": 15,
        "htf_required": False,  # Opcional
        "conditions": "score≥70 AND strength≥0.55 AND payout≥82 AND age≥15min"
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# EVALUACIÓN DE VETOS (FILTROS BINARIOS)
# ─────────────────────────────────────────────────────────────────────────────

def _check_candles_available(candles_5m: Sequence[Candle]) -> VetoResult:
    """Veto 0: ¿Hay velas 5m disponibles?"""
    passed = len(candles_5m) > 0
    return VetoResult(
        veto_type=VetoType.NO_CANDLES,
        passed=passed,
        reason="" if passed else "sin velas 5m para validar entrada"
    )


def _check_no_active_trade(active_trades: int, gale_active: bool) -> VetoResult:
    """Veto 1: ¿No hay operación activa?"""
    passed = active_trades == 0 and not gale_active
    reason = ""
    if not passed:
        reason = "gale activo" if gale_active else f"trades abiertos={active_trades}"
    return VetoResult(
        veto_type=VetoType.ACTIVE_OPERATION,
        passed=passed,
        reason=reason,
        value=active_trades
    )


def _check_cycle_limit(cycle_ops: int, max_ops: int = 5) -> VetoResult:
    """Veto 2: ¿Límite de operaciones por ciclo no alcanzado?"""
    passed = cycle_ops < max_ops
    return VetoResult(
        veto_type=VetoType.CYCLE_LIMIT,
        passed=passed,
        reason="" if passed else f"ciclo={cycle_ops}/{max_ops}",
        value=cycle_ops,
        threshold=max_ops
    )


def _check_payout_minimum(payout: int, min_payout: int = 84) -> VetoResult:
    """Veto 3: ¿Payout ≥ mínimo?"""
    passed = payout >= min_payout
    return VetoResult(
        veto_type=VetoType.PAYOUT_MIN,
        passed=passed,
        reason="" if passed else f"payout={payout}% < {min_payout}%",
        value=payout,
        threshold=min_payout
    )


def _check_score_minimum(score: float, threshold: int = 73) -> VetoResult:
    """Veto 4: ¿Score ≥ mínimo?"""
    passed = score >= threshold
    return VetoResult(
        veto_type=VetoType.SCORE_MIN,
        passed=passed,
        reason="" if passed else f"score={score:.1f} < {threshold}",
        value=score,
        threshold=threshold
    )


def _check_spike_1m(candles_1m: Sequence[Candle]) -> VetoResult:
    """Veto 5: ¿Sin spike en 1m?"""
    if not candles_1m:
        return VetoResult(
            veto_type=VetoType.SPIKE_1M,
            passed=False,
            reason="velas 1m no disponibles para validar spike"
        )
    
    spike_result = detect_spike_anomaly(list(candles_1m))
    passed = not spike_result.is_anomalous
    
    reason = ""
    if not passed and spike_result.event:
        reason = (
            f"gap={spike_result.event.gap_pct*100:.2f}% "
            f"body_mult={spike_result.event.body_mult:.2f}"
        )
    
    return VetoResult(
        veto_type=VetoType.SPIKE_1M,
        passed=passed,
        reason=reason
    )


def _check_spike_5m(candles_5m: Sequence[Candle]) -> VetoResult:
    """Veto 6: ¿Sin spike en 5m?"""
    spike_result = detect_spike_anomaly(list(candles_5m))
    passed = not spike_result.is_anomalous
    
    reason = ""
    if not passed and spike_result.event:
        reason = (
            f"gap={spike_result.event.gap_pct*100:.2f}% "
            f"body_mult={spike_result.event.body_mult:.2f}"
        )
    
    return VetoResult(
        veto_type=VetoType.SPIKE_5M,
        passed=passed,
        reason=reason
    )


def _check_htf_available_and_aligned(
    candles_15m: Sequence[Candle],
    direction: str,
    helper_infer_h1_trend: Callable[[list[Candle]], str],
) -> tuple[VetoResult, Optional[str]]:
    """Veto 7a/7b: ¿HTF disponible y alineado?"""
    
    if len(candles_15m) < 10:
        return VetoResult(
            veto_type=VetoType.HTF_MISSING,
            passed=False,
            reason="HTF 15m no disponible o insuficiente"
        ), None
    
    htf_trend = helper_infer_h1_trend(list(candles_15m))
    direction_lower = str(direction).lower()
    
    # Alineación: direction y htf_trend deben estar alineados
    aligned = (
        (direction_lower == "call" and htf_trend == "bullish") or
        (direction_lower == "put" and htf_trend == "bearish")
    )
    
    passed = aligned and htf_trend != "flat"
    
    reason = ""
    if not passed:
        reason = f"HTF {htf_trend} contra {direction_lower.upper()}"
    
    return VetoResult(
        veto_type=VetoType.HTF_MISALIGNED,
        passed=passed,
        reason=reason
    ), htf_trend


def _check_pattern_confirmed(
    pattern_name: str,
    pattern_confirms: bool,
    pattern_strength: float
) -> VetoResult:
    """Veto 7c: ¿Patrón confirmado con strength ≥ 0.55?"""
    
    # Primero: ¿patrón existe y confirma?
    if pattern_name == "none" or not pattern_confirms:
        return VetoResult(
            veto_type=VetoType.PATTERN_MISSING,
            passed=False,
            reason=f"patrón no confirmado ({pattern_name}, confirms={pattern_confirms})"
        )
    
    # Segundo: ¿strength suficiente?
    passed = pattern_strength >= 0.55
    reason = ""
    if not passed:
        reason = f"fortaleza={pattern_strength:.2f} < 0.55"
    
    veto_type = VetoType.PATTERN_WEAK if not passed else VetoType.PATTERN_MISSING
    
    return VetoResult(
        veto_type=veto_type,
        passed=passed,
        reason=reason,
        value=pattern_strength,
        threshold=0.55
    )


def _check_zone_age_minimum(zone_age_min: float, threshold: float = 20.0) -> VetoResult:
    """Veto 8: ¿Zona antigüedad ≥ 20 minutos?"""
    passed = zone_age_min >= threshold
    return VetoResult(
        veto_type=VetoType.ZONE_TOO_NEW,
        passed=passed,
        reason="" if passed else f"zona={zone_age_min:.1f}min < {threshold:.1f}min",
        value=zone_age_min,
        threshold=threshold
    )


def _check_zone_memory_no_wall(zone_adj: float, wall_threshold: float = -10.0) -> VetoResult:
    """Veto 9: ¿Zone memory no bloquea (ajuste > -10)?"""
    passed = zone_adj > wall_threshold
    return VetoResult(
        veto_type=VetoType.ZONE_MEMORY_WALL,
        passed=passed,
        reason="" if passed else f"memoria bloquea (ajuste={zone_adj:.1f})",
        value=zone_adj,
        threshold=wall_threshold
    )


# ─────────────────────────────────────────────────────────────────────────────
# CLASIFICACIÓN EN CATEGORÍAS
# ─────────────────────────────────────────────────────────────────────────────

def classify_candidate(
    score: float,
    pattern_strength: float,
    payout: int,
    zone_age_min: float,
    htf_aligned: bool,
    payout_current: int = 84  # Payout real disponible en momento de decisión
) -> EntryCategory:
    """
    Clasifica candidato en categoría A/B/C basada en métricas.
    
    CATEGORÍA A: Setup premium (máxima confianza)
    - Score ≥ 80
    - Pattern strength ≥ 0.75
    - Payout ≥ 87
    - Zone age ≥ 45 min
    - HTF aligned
    
    CATEGORÍA B: Setup sólido (confianza media-alta)
    - Score ≥ 73
    - Pattern strength ≥ 0.60
    - Payout ≥ 84
    - Zone age ≥ 20 min
    - HTF aligned
    
    CATEGORÍA C: Setup aceptable (confianza media)
    - Score ≥ 70
    - Pattern strength ≥ 0.55
    - Payout ≥ 82
    - Zone age ≥ 15 min
    - HTF no requerido
    
    REJECT: No cumple categoría C
    """
    
    # Categoría A
    if (score >= 80 and
        pattern_strength >= 0.75 and
        payout_current >= 87 and
        zone_age_min >= 45 and
        htf_aligned):
        return EntryCategory.PREMIUM
    
    # Categoría B
    if (score >= 73 and
        pattern_strength >= 0.60 and
        payout_current >= 84 and
        zone_age_min >= 20 and
        htf_aligned):
        return EntryCategory.SOLID
    
    # Categoría C
    if (score >= 70 and
        pattern_strength >= 0.55 and
        payout_current >= 82 and
        zone_age_min >= 15):
        return EntryCategory.ACCEPTABLE
    
    # Reject
    return EntryCategory.REJECT


def apply_category_logic(
    category: EntryCategory,
    losses_in_cycle: int = 0,
    phase2_profile: str = "strict"
) -> bool:
    """
    Aplica lógica de ejecución según categoría y estado del ciclo.
    
    CATEGORÍA A: Ejecutar siempre (premium)
    CATEGORÍA B: Ejecutar si ciclo sano (≤1 pérdida)
    CATEGORÍA C: Ejecutar solo si ciclo perfecto (0 pérdidas)
    REJECT: No ejecutar
    """
    
    if category == EntryCategory.PREMIUM:
        return True
    elif category == EntryCategory.SOLID:
        return losses_in_cycle <= 1
    elif category == EntryCategory.ACCEPTABLE:
        return losses_in_cycle == 0
    else:
        return False


# ─────────────────────────────────────────────────────────────────────────────
# MOTOR PRINCIPAL DE DECISIÓN
# ─────────────────────────────────────────────────────────────────────────────

def evaluate_entry(
    candidate: CandidateEntry,
    context: Mapping[str, Any],
    active_trades: int = 0,
    gale_active: bool = False,
    cycle_ops: int = 0,
    max_cycle_ops: int = 5,
    min_payout: int = 84,
    score_threshold: int = 73,
    enforce_quality: bool = True,
    helper_infer_h1_trend: Optional[Callable[[list[Candle]], str]] = None,
    helper_score_zone_memory: Optional[Callable[[list[HistoricalZone], str, float], float]] = None,
) -> EntryDecision:
    """
    MOTOR PRINCIPAL: Evalúa candidato contra todos los vetos y devuelve decisión.
    
    ENTRADA:
    - candidate: CandidateEntry con score, patrón, zona, dirección
    - context: diccionario con velas, payout, candles_1m, candles_15m, etc
    - Estado del bot: active_trades, gale_active, cycle_ops
    - Configuración: min_payout, score_threshold, enforce_quality
    - Helpers: funciones para HTF y zone memory
    
    SALIDA:
    - EntryDecision con approved/rejected, categoría, vetos, trazabilidad
    
    LÓGICA:
    1. Evalúa todos los vetos binarios (9 filtros)
    2. Si alguno falla: REJECT
    3. Si todos pasan: Clasifica en A/B/C
    4. Si pide ejecutar según categoría + estado del ciclo: APPROVED
    5. Si no: REJECTED (pero con categoría conocida)
    """
    
    # Inicializar decisión
    decision = EntryDecision(
        approved=False,
        category=EntryCategory.REJECT,
        reason="",
        profile="strict" if not enforce_quality else "strict"
    )
    
    # Extraer datos del contexto
    candles_5m = list(context.get("candles_5m") or candidate.candles or [])
    candles_1m = list(context.get("candles_1m") or [])
    candles_15m = list(context.get("candles_15m") or [])
    payout_now = int(context.get("payout", candidate.payout) or min_payout)
    
    # ─────────────────────────────────────────────────────────────────────────
    # VETO 0: ¿Hay velas 5m?
    # ─────────────────────────────────────────────────────────────────────────
    veto_0 = _check_candles_available(candles_5m)
    decision.vetos.append(veto_0)
    if not veto_0.passed:
        decision.reason = veto_0.reason
        return decision
    
    # ─────────────────────────────────────────────────────────────────────────
    # VETO 1: ¿No hay operación activa?
    # ─────────────────────────────────────────────────────────────────────────
    veto_1 = _check_no_active_trade(active_trades, gale_active)
    decision.vetos.append(veto_1)
    if not veto_1.passed:
        decision.reason = veto_1.reason
        return decision
    
    # ─────────────────────────────────────────────────────────────────────────
    # VETO 2: ¿Límite de ciclo?
    # ─────────────────────────────────────────────────────────────────────────
    veto_2 = _check_cycle_limit(int(cycle_ops), max_cycle_ops)
    decision.vetos.append(veto_2)
    if not veto_2.passed:
        decision.reason = veto_2.reason
        return decision
    
    # ─────────────────────────────────────────────────────────────────────────
    # VETO 3: ¿Payout mínimo?
    # ─────────────────────────────────────────────────────────────────────────
    veto_3 = _check_payout_minimum(payout_now, min_payout)
    decision.vetos.append(veto_3)
    decision.payout_value = payout_now
    if not veto_3.passed:
        decision.reason = veto_3.reason
        return decision
    
    if enforce_quality:
        # ─────────────────────────────────────────────────────────────────────
        # VETO 4: ¿Score mínimo? (solo si enforce_quality)
        # ─────────────────────────────────────────────────────────────────────
        score = float(getattr(candidate, "score", 0.0) or 0.0)
        veto_4 = _check_score_minimum(score, score_threshold)
        decision.vetos.append(veto_4)
        decision.score_value = score
        if not veto_4.passed:
            decision.reason = veto_4.reason
            return decision
        
        # ─────────────────────────────────────────────────────────────────────
        # VETO 5: ¿Sin spike 1m?
        # ─────────────────────────────────────────────────────────────────────
        veto_5 = _check_spike_1m(candles_1m)
        decision.vetos.append(veto_5)
        if not veto_5.passed:
            decision.reason = veto_5.reason
            return decision
        
        # ─────────────────────────────────────────────────────────────────────
        # VETO 6: ¿Sin spike 5m?
        # ─────────────────────────────────────────────────────────────────────
        veto_6 = _check_spike_5m(candles_5m)
        decision.vetos.append(veto_6)
        if not veto_6.passed:
            decision.reason = veto_6.reason
            return decision
        
        # ─────────────────────────────────────────────────────────────────────
        # VETO 7a/7b: ¿HTF disponible y alineado?
        # ─────────────────────────────────────────────────────────────────────
        infer_h1_trend_fn: Callable[[list[Candle]], str]
        infer_h1_trend_fn = helper_infer_h1_trend or (lambda _candles: "flat")
        veto_7ab, htf_trend = _check_htf_available_and_aligned(
            candles_15m,
            candidate.direction,
            infer_h1_trend_fn,
        )
        decision.vetos.append(veto_7ab)
        decision.htf_aligned = veto_7ab.passed
        if not veto_7ab.passed:
            decision.reason = veto_7ab.reason
            return decision
        
        # ─────────────────────────────────────────────────────────────────────
        # VETO 7c: ¿Patrón confirmado con strength ≥ 0.55?
        # ─────────────────────────────────────────────────────────────────────
        pattern_name = str(getattr(candidate, "_reversal_pattern", "none") or "none")
        pattern_confirms = bool(getattr(candidate, "_reversal_confirms", False))
        pattern_strength = float(getattr(candidate, "_reversal_strength", 0.0) or 0.0)
        
        veto_7c = _check_pattern_confirmed(pattern_name, pattern_confirms, pattern_strength)
        decision.vetos.append(veto_7c)
        decision.pattern_name = pattern_name
        decision.pattern_strength = pattern_strength
        if not veto_7c.passed:
            decision.reason = veto_7c.reason
            return decision
        
        # ─────────────────────────────────────────────────────────────────────
        # VETO 8: ¿Zona antigüedad ≥ 20 min?
        # ─────────────────────────────────────────────────────────────────────
        zone_age_min = float(candidate.zone.age_minutes if hasattr(candidate, "zone") else 0.0)
        veto_8 = _check_zone_age_minimum(zone_age_min, 20.0)
        decision.vetos.append(veto_8)
        decision.zone_age_min = zone_age_min
        if not veto_8.passed:
            decision.reason = veto_8.reason
            return decision
        
        # ─────────────────────────────────────────────────────────────────────
        # VETO 9: ¿Zone memory no bloquea?
        # ─────────────────────────────────────────────────────────────────────
        zone_adj = 0.0
        if hasattr(candidate, "zone_memory") and candidate.zone_memory:
            try:
                current_price = float(candles_5m[-1].close if candles_5m else candidate.zone.midpoint)
                score_zone_memory_fn: Callable[[list[HistoricalZone], str, float], float]
                score_zone_memory_fn = helper_score_zone_memory or score_zone_memory
                zone_adj = score_zone_memory_fn(
                    candidate.zone_memory,
                    candidate.direction,
                    current_price
                )
            except Exception as e:
                log.warning(f"Error scoring zone memory: {e}")
                zone_adj = 0.0
        
        veto_9 = _check_zone_memory_no_wall(zone_adj, -10.0)
        decision.vetos.append(veto_9)
        decision.zone_memory_adj = zone_adj
        if not veto_9.passed:
            decision.reason = veto_9.reason
            return decision
    
    # ─────────────────────────────────────────────────────────────────────────
    # TODOS LOS VETOS PASARON: Clasificar
    # ─────────────────────────────────────────────────────────────────────────
    
    score = float(getattr(candidate, "score", 0.0) or 0.0)
    pattern_strength = float(getattr(candidate, "_reversal_strength", 0.0) or 0.0)
    
    category = classify_candidate(
        score=score,
        pattern_strength=pattern_strength,
        payout=min_payout,  # Payout configurado
        zone_age_min=zone_age_min,
        htf_aligned=decision.htf_aligned,
        payout_current=payout_now  # Payout real en el momento
    )
    
    decision.category = category
    
    # ─────────────────────────────────────────────────────────────────────────
    # APLICAR LÓGICA DE CATEGORÍA
    # ─────────────────────────────────────────────────────────────────────────
    
    losses_in_cycle = int(context.get("losses_in_cycle", 0))
    should_execute = apply_category_logic(
        category=category,
        losses_in_cycle=losses_in_cycle,
        phase2_profile=decision.profile
    )
    
    if should_execute:
        decision.approved = True
        decision.reason = (
            f"APROBADO - Categoría {category.value}: "
            f"score={score:.0f}, pattern={pattern_strength:.2f}, "
            f"payout={payout_now}%, age={zone_age_min:.0f}min"
        )
    else:
        decision.approved = False
        decision.reason = (
            f"RECHAZADO - Categoría {category.value} no permite ejecución "
            f"(ciclo con {losses_in_cycle} pérdidas)"
        )
    
    return decision


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS PARA INTEGRACIÓN
# ─────────────────────────────────────────────────────────────────────────────

def explain_decision(decision: EntryDecision) -> str:
    """
    Devuelve explicación en lenguaje natural de la decisión.
    """
    lines = [
        f"{'═' * 70}",
        f"DECISIÓN DE ENTRADA: {'APROBADA ✓' if decision.approved else 'RECHAZADA ✗'}",
        f"{'═' * 70}",
        f"Categoría: {decision.category.value}",
        f"Razón: {decision.reason}",
        f"",
    ]
    
    if decision.vetos:
        lines.append("Vetos evaluados:")
        for veto in decision.vetos:
            status = "✓ PASS" if veto.passed else "✗ FAIL"
            if veto.reason:
                lines.append(f"  {status:8s} {veto.veto_type.value:20s} | {veto.reason}")
            else:
                lines.append(f"  {status:8s} {veto.veto_type.value:20s}")
        lines.append("")
    
    if decision.scores:
        lines.append("Scores:")
        for key, val in decision.scores.items():
            lines.append(f"  {key:15s}: {val}")
        lines.append("")
    
    return "\n".join(lines)
