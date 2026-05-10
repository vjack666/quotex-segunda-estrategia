"""Modelos del HUB para datos reales de STRAT-A y STRAT-B."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, List, Optional


VALID_DIRECTIONS = {"call", "put"}
VALID_ENTRY_MODES = {
    "rebound_floor",
    "rebound_ceiling",
    "breakout_above",
    "breakout_below",
    "spring",
    "upthrust",
    "wyckoff_early_spring",
    "wyckoff_early_upthrust",
    "none",
}


def _normalize_direction(direction: str) -> str:
    value = str(direction).strip().lower()
    if value not in VALID_DIRECTIONS:
        raise ValueError(f"direction invalida: {direction!r}")
    return value


def _utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


@dataclass
class CandidateData:
    """Candidato normalizado para renderizar en el HUB."""

    strategy: str
    asset: str
    direction: str
    score: float
    payout: int
    zone_ceiling: float
    zone_floor: float
    zone_age_min: float
    pattern: str
    pattern_strength: float
    entry_mode: str
    detected_at: datetime = field(default_factory=_utc_now)
    confidence: Optional[float] = None
    signal_type: Optional[str] = None
    raw_reason: Optional[str] = None
    raw_note: Optional[str] = None
    dist_pct: Optional[float] = None  # distancia % del precio al trigger (None si sin precio)

    def __post_init__(self) -> None:
        self.strategy = str(self.strategy).strip().upper()
        self.asset = str(self.asset).strip().upper()
        self.direction = _normalize_direction(self.direction)

        self.score = max(0.0, min(100.0, float(self.score)))
        self.payout = int(self.payout)
        self.zone_ceiling = float(self.zone_ceiling)
        self.zone_floor = float(self.zone_floor)
        self.zone_age_min = max(0.0, float(self.zone_age_min))
        self.pattern = str(self.pattern).strip() or "none"
        self.pattern_strength = max(0.0, min(1.0, float(self.pattern_strength)))
        self.entry_mode = str(self.entry_mode).strip().lower()

        if self.payout < 0:
            raise ValueError("payout no puede ser negativo")
        if self.zone_floor > self.zone_ceiling:
            raise ValueError("zone_floor no puede ser mayor a zone_ceiling")
        if self.entry_mode not in VALID_ENTRY_MODES:
            raise ValueError(f"entry_mode invalido: {self.entry_mode!r}")

        if self.confidence is not None:
            self.confidence = max(0.0, min(1.0, float(self.confidence)))

    @property
    def rank_value(self) -> float:
        """Valor único para ordenar candidatos en el HUB."""
        if self.strategy == "STRAT-B" and self.confidence is not None:
            return self.confidence * 100.0
        return self.score

    @classmethod
    def from_strat_a(cls, data: dict[str, Any]) -> "CandidateData":
        """Construye candidato STRAT-A desde payload real del bot."""
        return cls(
            strategy="STRAT-A",
            asset=str(data.get("asset") or data.get("symbol") or ""),
            direction=str(data.get("direction") or ""),
            score=float(data.get("score", 0.0)),
            payout=int(data.get("payout", 0)),
            zone_ceiling=float(data.get("zone_ceiling", data.get("top", 0.0))),
            zone_floor=float(data.get("zone_floor", data.get("bottom", 0.0))),
            zone_age_min=float(data.get("zone_age_min", data.get("age_min", 0.0))),
            pattern=str(data.get("pattern") or data.get("pattern_name") or "none"),
            pattern_strength=float(data.get("pattern_strength", 0.0)),
            entry_mode=str(data.get("entry_mode") or "rebound_floor"),
            detected_at=data.get("detected_at") or _utc_now(),
            raw_reason=str(data.get("reason") or "") or None,
        )

    @classmethod
    def from_strat_b(cls, data: dict[str, Any]) -> "CandidateData":
        """Construye candidato STRAT-B desde señal real del bot."""
        confidence = float(data.get("confidence", 0.0))
        return cls(
            strategy="STRAT-B",
            asset=str(data.get("asset") or data.get("symbol") or ""),
            direction=str(data.get("direction") or ""),
            score=confidence * 100.0,
            payout=int(data.get("payout", 0)),
            zone_ceiling=float(data.get("zone_ceiling", data.get("top", 0.0))),
            zone_floor=float(data.get("zone_floor", data.get("bottom", 0.0))),
            zone_age_min=float(data.get("zone_age_min", data.get("age_min", 0.0))),
            pattern=str(data.get("pattern") or data.get("signal_name") or "none"),
            pattern_strength=float(data.get("pattern_strength", confidence)),
            entry_mode=str(data.get("entry_mode") or data.get("signal_type") or "spring"),
            detected_at=data.get("detected_at") or _utc_now(),
            confidence=confidence,
            signal_type=str(data.get("signal_type") or "") or None,
            raw_reason=str(data.get("reason") or "") or None,
        )


@dataclass
class HubScanSnapshot:
    """Resultado de un ciclo completo de escaneo."""

    scan_number: int
    timestamp: datetime
    total_assets_scanned: int
    strat_a_candidates: List[CandidateData] = field(default_factory=list)
    strat_b_candidates: List[CandidateData] = field(default_factory=list)
    strat_a_entered: Optional[str] = None
    strat_b_entered: Optional[str] = None
    balance: Optional[float] = None
    cycle_id: int = 0
    cycle_ops: int = 0
    cycle_wins: int = 0
    cycle_losses: int = 0


@dataclass
class GaleState:
    """[DEPRECATED] Estado anterior del GaleWatcher. Use MasanielloState en su lugar."""
    active:          bool  = False
    asset:           str   = ""
    direction:       str   = ""
    entry_price:     float = 0.0
    current_price:   float = 0.0
    secs_remaining:  float = 0.0
    duration_sec:    int   = 300
    payout:          int   = 0
    amount_invested: float = 0.0
    gale_amount:     float = 0.0
    is_losing:       bool  = False
    delta_pct:       float = 0.0
    updated_at:      float = 0.0
    gale_fired:          bool  = False
    gale_order_id:       str   = ""
    gale_success:        bool  = False
    consecutive_count:   int   = 0
    cycle_target_amount: float = 0.0
    safety_status:       str   = "OK"
    context_key:         str   = ""


@dataclass
class MasanielloState:
    """Estado en tiempo real del motor Masaniello (gestión dinámica de riesgo)."""
    active:              bool  = False       # hay una operación activa
    cycle_num:           int   = 1           # número de ciclo actual
    trades_in_cycle:     int   = 0           # operaciones completadas en ciclo
    wins_in_cycle:       int   = 0           # aciertos en ciclo actual
    losses_in_cycle:     int   = 0           # fallos en ciclo actual
    sequence:            str   = ""          # secuencia W/L del ciclo en curso
    
    # Operación actual
    asset:               str   = ""
    direction:           str   = ""          # "call" | "put"
    entry_price:         float = 0.0
    current_price:       float = 0.0
    current_amount:      float = 0.0         # monto actual de operación
    next_amount:         float = 0.0         # monto calculado para siguiente
    
    # Tiempos
    secs_remaining:      float = 0.0
    duration_sec:        int   = 300
    payout:              int   = 0           # payout %
    delta_pct:           float = 0.0         # variación %
    updated_at:          float = 0.0
    
    # Histórico y estadísticas
    total_pnl:           float = 0.0         # P&L acumulado
    win_rate_pct:        float = 0.0         # porcentaje de aciertos
    daily_loss:          float = 0.0         # pérdida diaria acumulada
    max_daily_loss:      float = 500.0       # límite de pérdida diaria
    
    # Configuración Masaniello (L1-L5)
    cycle_target_ops:    int   = 5           # L1: objetivo ops/ciclo
    cycle_target_wins:   int   = 2           # L2: objetivo wins/ciclo
    reference_balance:   float = 100.0       # banca base fija para cálculo inicial
    multiplier:          float = 1.5         # L3: multiplicador
    commission_pct:      float = 2.0         # L5: comisión %
    
    # Estado
    safety_status:       str   = "OK"        # OK | RIESGO | LIMITE | ERROR




@dataclass
class CandleSnapshot:
    """Vela OHLC simplificada para renderizar en el chart ASCII del HUB."""
    open:  float
    high:  float
    low:   float
    close: float
    ts:    float = 0.0   # Unix timestamp (opcional, solo para referencia)


@dataclass
class VipWindowData:
    """Ventana VIP para candidatos casi listos para entrada."""
    asset: str
    direction: str
    score: float
    payout: int
    entry_mode: str
    zone_floor: float
    zone_ceiling: float
    zone_age_min: float
    missing_conditions: int
    total_conditions: int
    ready_to_execute: bool
    missing_labels: List[str] = field(default_factory=list)
    conditions_ok: List[str] = field(default_factory=list)
    candles_15m_count: int = 0
    candles_5m_count: int = 0
    candles_1m_count: int = 0
    ma15_fast: Optional[float] = None
    ma15_slow: Optional[float] = None
    ma5_fast: Optional[float] = None
    ma5_slow: Optional[float] = None
    ma1_fast: Optional[float] = None
    ma1_slow: Optional[float] = None
    htf_trend: str = ""
    h1_trend: str = ""
    pattern: str = "none"
    pattern_strength: float = 0.0
    spike_clear: bool = True
    zone_memory_ok: bool = True
    order_block_ok: bool = True
    notes: str = ""
    updated_at: float = 0.0


@dataclass
class HubState:
    """Estado global del HUB en ejecución."""

    last_scan: Optional[HubScanSnapshot] = None
    strat_a_watching: List[CandidateData] = field(default_factory=list)
    strat_b_watching: List[CandidateData] = field(default_factory=list)
    active_trade_asset: Optional[str] = None
    active_trade_direction: Optional[str] = None
    active_trade_time_remaining_sec: Optional[float] = None
    active_trade_entry_price: Optional[float] = None
    active_trade_current_price: Optional[float] = None
    active_trade_delta_pct: Optional[float] = None
    last_trade_outcome: Optional[str] = None   # "WIN" | "LOSS" | "UNRESOLVED"
    last_trade_asset: Optional[str] = None
    last_trade_profit: Optional[float] = None
    total_scans: int = 0
    last_update: datetime = field(default_factory=_utc_now)
    live_wins: int = 0
    live_losses: int = 0
    known_balance: float = 0.0  # último balance conocido
    masaniello: "MasanielloState" = field(default_factory=lambda: MasanielloState())  # estado del Masaniello
    gale: "GaleState" = field(default_factory=lambda: GaleState())  # [DEPRECATED] usar masaniello
    # Chart ASCII: velas del último activo analizado/operado
    chart_candles: List["CandleSnapshot"] = field(default_factory=list)
    chart_asset: str = ""
    chart_entry_price: Optional[float] = None  # precio de entrada marcado en el chart
    chart_direction: str = ""                   # "call" | "put"
    chart_zone_floor: Optional[float] = None    # nivel soporte de la zona
    chart_zone_ceiling: Optional[float] = None  # nivel resistencia de la zona
    chart_live_price: Optional[float] = None    # precio actual (candidato sin trade activo)
    # HTF cache status: telemetría del scanner 15m en segundo plano
    htf_asset: str = ""
    htf_payout: int = 0
    htf_candles: int = 0
    htf_library_size: int = 0
    htf_cache_age_sec: float = 0.0
    htf_cache_ttl_sec: float = 0.0
    htf_last_refresh_ts: float = 0.0
    vip_windows: List[VipWindowData] = field(default_factory=list)


__all__ = [
    "CandidateData",
    "CandleSnapshot",
    "GaleState",
    "MasanielloState",
    "HubScanSnapshot",
    "HubState",
    "VipWindowData",
    "VALID_DIRECTIONS",
    "VALID_ENTRY_MODES",
]
