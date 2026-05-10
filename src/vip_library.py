"""
vip_library.py
==============
Biblioteca VIP de candidatos casi listos para entrar.

Objetivo:
- Identificar activos que ya pasaron la mayor parte del filtro.
- Mantenerlos en una "ventana" dedicada con contexto multitemporal.
- Sacarlos cuando dejan de cumplir condiciones o cuando caducan.

La idea no es duplicar el scoring de entry_scorer, sino crear una capa
operativa superior para seguimiento fino antes de la ejecución.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from statistics import mean
from typing import Any, Iterable, List, Optional, Sequence

from models import Candle
from spike_filter import detect_spike_anomaly
from hub.hub_models import VipWindowData


# ─────────────────────────────────────────────────────────────────────────────
#  CONFIGURACIÓN
# ─────────────────────────────────────────────────────────────────────────────

VIP_MIN_PAYOUT = 85
VIP_MAX_MISSING_CONDITIONS = 3
VIP_MIN_SCORE = 50.0
VIP_EMA_FAST = 10
VIP_EMA_SLOW = 20
VIP_STALE_TTL_SEC = 900.0  # 15 min


# ─────────────────────────────────────────────────────────────────────────────
#  HELPERS MATEMÁTICOS
# ─────────────────────────────────────────────────────────────────────────────

def _ema(values: Sequence[float], period: int) -> List[float]:
    if len(values) < period:
        return []
    alpha = 2.0 / (period + 1.0)
    series = list(values)
    result = [mean(series[:period])]
    for value in series[period:]:
        result.append(alpha * value + (1.0 - alpha) * result[-1])
    return result


def _ma_pair(candles: Sequence[Candle], fast: int = VIP_EMA_FAST, slow: int = VIP_EMA_SLOW) -> tuple[Optional[float], Optional[float]]:
    closes = [float(c.close) for c in candles if c and c.close > 0]
    if len(closes) < slow:
        return None, None
    ema_fast = _ema(closes, fast)
    ema_slow = _ema(closes, slow)
    if not ema_fast or not ema_slow:
        return None, None
    return round(float(ema_fast[-1]), 6), round(float(ema_slow[-1]), 6)


def _trend_from_ma(fast: Optional[float], slow: Optional[float], direction: str) -> bool:
    if fast is None or slow is None:
        return False
    direction = direction.lower()
    return (fast > slow) if direction == "call" else (fast < slow)


def _trend_label(fast: Optional[float], slow: Optional[float]) -> str:
    if fast is None or slow is None:
        return "N/D"
    if fast > slow:
        return "BULL"
    if fast < slow:
        return "BEAR"
    return "FLAT"


def _candles_tail(candles: Sequence[Candle], limit: int) -> List[Candle]:
    ordered = sorted([c for c in candles if c is not None], key=lambda c: c.ts)
    return ordered[-limit:]


@dataclass
class VipCandidateWindow:
    """Snapshot interno de un candidato VIP."""
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
    missing_labels: List[str]
    conditions_ok: List[str]
    candles_15m_count: int
    candles_5m_count: int
    candles_1m_count: int
    ma15_fast: Optional[float]
    ma15_slow: Optional[float]
    ma5_fast: Optional[float]
    ma5_slow: Optional[float]
    ma1_fast: Optional[float]
    ma1_slow: Optional[float]
    htf_trend: str
    h1_trend: str
    pattern: str
    pattern_strength: float
    spike_clear: bool
    zone_memory_ok: bool
    order_block_ok: bool
    notes: str
    updated_at: float

    def to_hub(self) -> VipWindowData:
        return VipWindowData(
            asset=self.asset,
            direction=self.direction,
            score=self.score,
            payout=self.payout,
            entry_mode=self.entry_mode,
            zone_floor=self.zone_floor,
            zone_ceiling=self.zone_ceiling,
            zone_age_min=self.zone_age_min,
            missing_conditions=self.missing_conditions,
            total_conditions=self.total_conditions,
            ready_to_execute=self.ready_to_execute,
            missing_labels=list(self.missing_labels),
            conditions_ok=list(self.conditions_ok),
            candles_15m_count=self.candles_15m_count,
            candles_5m_count=self.candles_5m_count,
            candles_1m_count=self.candles_1m_count,
            ma15_fast=self.ma15_fast,
            ma15_slow=self.ma15_slow,
            ma5_fast=self.ma5_fast,
            ma5_slow=self.ma5_slow,
            ma1_fast=self.ma1_fast,
            ma1_slow=self.ma1_slow,
            htf_trend=self.htf_trend,
            h1_trend=self.h1_trend,
            pattern=self.pattern,
            pattern_strength=self.pattern_strength,
            spike_clear=self.spike_clear,
            zone_memory_ok=self.zone_memory_ok,
            order_block_ok=self.order_block_ok,
            notes=self.notes,
            updated_at=self.updated_at,
        )


class VipLibraryManager:
    """Biblioteca de ventanas VIP, actualizada con cada candidato evaluado."""

    def __init__(
        self,
        *,
        min_payout: int = VIP_MIN_PAYOUT,
        max_missing_conditions: int = VIP_MAX_MISSING_CONDITIONS,
        min_score: float = VIP_MIN_SCORE,
        stale_ttl_sec: float = VIP_STALE_TTL_SEC,
    ) -> None:
        self.min_payout = int(min_payout)
        self.max_missing_conditions = int(max_missing_conditions)
        self.min_score = float(min_score)
        self.stale_ttl_sec = float(stale_ttl_sec)
        self._windows: dict[str, VipCandidateWindow] = {}

    def get_windows(self) -> List[VipWindowData]:
        windows = [w.to_hub() for w in self._windows.values()]
        windows.sort(key=lambda w: (w.missing_conditions, -w.score, -w.payout))
        return windows

    def purge_stale(self) -> None:
        now = time.time()
        stale = [asset for asset, win in self._windows.items() if (now - win.updated_at) >= self.stale_ttl_sec]
        for asset in stale:
            self._windows.pop(asset, None)
        if stale:
            self._record_maintenance_event(
                subtype="PURGE",
                asset="",
                payload={"count": len(stale), "assets": stale, "ttl_sec": self.stale_ttl_sec},
            )

    def refresh_from_candidate(
        self,
        candidate: Any,
        *,
        candles_1m: Sequence[Candle] = (),
        candles_5m: Sequence[Candle] = (),
        candles_15m: Sequence[Candle] = (),
        h1_candles: Sequence[Candle] = (),
    ) -> Optional[VipWindowData]:
        """
        Evalúa un candidato y, si está lo bastante cerca de la entrada,
        lo guarda/actualiza en la biblioteca VIP.
        """
        self.purge_stale()

        asset = str(getattr(candidate, "asset", "") or "").upper()
        direction = str(getattr(candidate, "direction", "") or "").lower()
        score = float(getattr(candidate, "score", 0.0) or 0.0)
        payout = int(getattr(candidate, "payout", 0) or 0)
        zone = getattr(candidate, "zone", None)
        zone_floor = float(getattr(zone, "floor", 0.0) or 0.0)
        zone_ceiling = float(getattr(zone, "ceiling", 0.0) or 0.0)
        zone_age_min = float(getattr(zone, "age_minutes", 0.0) or 0.0)
        entry_mode = str(getattr(candidate, "_entry_mode", "none") or "none")
        pattern = str(getattr(candidate, "_reversal_pattern", "none") or "none")
        pattern_strength = float(getattr(candidate, "_reversal_strength", 0.0) or 0.0)
        confirms = bool(getattr(candidate, "_reversal_confirms", False))
        stage = str(getattr(candidate, "_stage", "") or "")
        force_execute = bool(getattr(candidate, "_force_execute", False))
        h1_trend = self._trend_on_candles(h1_candles, direction)
        ma15_fast, ma15_slow = _ma_pair(candles_15m)
        ma5_fast, ma5_slow = _ma_pair(candles_5m)
        ma1_fast, ma1_slow = _ma_pair(candles_1m)
        htf_trend = _trend_label(ma15_fast, ma15_slow)
        ma1_trend = _trend_label(ma1_fast, ma1_slow)
        ma5_trend = _trend_label(ma5_fast, ma5_slow)
        spike_ok = not self._has_spike(candles_1m) and not self._has_spike(candles_5m)
        zone_memory_adj = float((getattr(candidate, "score_breakdown", {}) or {}).get("zone_memory", 0.0) or 0.0)
        zone_memory_ok = zone_memory_adj >= 0.0
        order_block_ok = self._order_block_ok(candidate)

        conditions: list[tuple[str, bool]] = [
            ("Payout > min", payout > self.min_payout),
            ("Score base", score >= self.min_score),
            ("Patrón confirma", confirms or stage.startswith("breakout") or force_execute),
            ("H1 alineado", h1_trend == direction),
            ("MA 15m alineada", _trend_from_ma(ma15_fast, ma15_slow, direction)),
            ("MA 5m alineada", _trend_from_ma(ma5_fast, ma5_slow, direction)),
            ("MA 1m alineada", _trend_from_ma(ma1_fast, ma1_slow, direction)),
            ("Sin spike", spike_ok),
            ("Zona mem OK", zone_memory_ok),
            ("Order block OK", order_block_ok),
        ]

        ok_labels = [name for name, ok in conditions if ok]
        missing_labels = [name for name, ok in conditions if not ok]
        missing_count = len(missing_labels)
        ready = missing_count <= self.max_missing_conditions

        if not ready:
            # Si el candidato ya no está cerca de entrada, sale de la biblioteca.
            self._windows.pop(asset, None)
            self._record_maintenance_event(
                subtype="EXIT",
                asset=asset,
                payload={
                    "reason": "missing_conditions",
                    "missing_conditions": missing_count,
                    "missing_labels": missing_labels,
                    "score": round(score, 1),
                    "payout": payout,
                },
            )
            return None

        notes = ", ".join(missing_labels[:3]) if missing_labels else "listo"
        window = VipCandidateWindow(
            asset=asset,
            direction=direction,
            score=round(score, 1),
            payout=payout,
            entry_mode=entry_mode,
            zone_floor=zone_floor,
            zone_ceiling=zone_ceiling,
            zone_age_min=zone_age_min,
            missing_conditions=missing_count,
            total_conditions=len(conditions),
            ready_to_execute=ready,
            missing_labels=missing_labels,
            conditions_ok=ok_labels,
            candles_15m_count=len(candles_15m),
            candles_5m_count=len(candles_5m),
            candles_1m_count=len(candles_1m),
            ma15_fast=ma15_fast,
            ma15_slow=ma15_slow,
            ma5_fast=ma5_fast,
            ma5_slow=ma5_slow,
            ma1_fast=ma1_fast,
            ma1_slow=ma1_slow,
            htf_trend=htf_trend,
            h1_trend=h1_trend,
            pattern=pattern,
            pattern_strength=pattern_strength,
            spike_clear=spike_ok,
            zone_memory_ok=zone_memory_ok,
            order_block_ok=order_block_ok,
            notes=notes,
            updated_at=time.time(),
        )
        previous = self._windows.get(asset)
        self._windows[asset] = window
        self._record_maintenance_event(
            subtype="ENTER" if previous is None else "REFRESH",
            asset=asset,
            payload={
                "direction": direction,
                "score": window.score,
                "payout": window.payout,
                "ready_to_execute": window.ready_to_execute,
                "missing_conditions": window.missing_conditions,
                "total_conditions": window.total_conditions,
                "entry_mode": window.entry_mode,
                "pattern": window.pattern,
                "htf_trend": window.htf_trend,
                "h1_trend": window.h1_trend,
                "spike_clear": window.spike_clear,
                "zone_memory_ok": window.zone_memory_ok,
                "order_block_ok": window.order_block_ok,
            },
        )
        return window.to_hub()

    @staticmethod
    def _trend_on_candles(candles: Sequence[Candle], direction: str) -> str:
        ma_fast, ma_slow = _ma_pair(candles)
        if ma_fast is None or ma_slow is None:
            return "N/D"
        if _trend_from_ma(ma_fast, ma_slow, direction):
            return "BULL" if direction == "call" else "BEAR"
        return "CONTRA"

    @staticmethod
    def _has_spike(candles: Sequence[Candle]) -> bool:
        if len(candles) < 3:
            return False
        result = detect_spike_anomaly(candles)
        return bool(result.is_anomalous)

    @staticmethod
    def _order_block_ok(candidate: Any) -> bool:
        blocks = getattr(candidate, "_order_blocks", None) or {}
        direction = str(getattr(candidate, "direction", "") or "").lower()
        if not isinstance(blocks, dict):
            return True
        if direction == "call":
            return bool(blocks.get("bull")) or not bool(blocks.get("bear"))
        if direction == "put":
            return bool(blocks.get("bear")) or not bool(blocks.get("bull"))
        return True

    @staticmethod
    def _record_maintenance_event(*, subtype: str, asset: str = "", payload: Optional[dict[str, Any]] = None) -> None:
        try:
            from black_box_recorder import get_black_box

            recorder = get_black_box()
            recorder.record_maintenance_event(
                "VIP_LIBRARY",
                subtype,
                asset=asset,
                severity="INFO",
                payload=payload or {},
            )
        except Exception:
            return