"""
strategy_spring_sweep.py

Estrategia alternativa "Spring Sweep Strategy (SSS)" para detectar
patron Wyckoff Spring / Liquidity Sweep en velas de 1 minuto.

API principal:
    detect_spring_sweep(df)         -> tuple[bool, dict]   (alcista)
    detect_upthrust(df)             -> tuple[bool, dict]   (bajista)
    detect_spring_or_upthrust(df)   -> tuple[bool, dict]   (combinado)

Entradas:
    - DataFrame con columnas OHLCV normalizadas.
      Se aceptan alias: open/high/low/close/volume o o/h/l/c/v.

Salida:
    - bool: True si hay senal valida
    - dict: metrica de confianza, precio sugerido, diagnostico y
            campo "signal_type": "spring" | "upthrust" | None
            campo "direction":   "call"   | "put"      | None

Nota:
    Este modulo es puro reconocimiento de patron. No envia ordenes,
    no toca websocket ni gestion de balance.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class SpringSweepConfig:
    """Parametros matematicos del detector Spring (alcista)."""

    support_lookback: int = 18
    min_rows: int = 20
    break_buffer_pct: float = 0.00005
    reclaim_tolerance_pct: float = 0.00030
    min_lower_wick_ratio: float = 0.45
    confirm_break_buffer_pct: float = 0.00005
    min_confirm_body_ratio: float = 0.40


# Alias para legibilidad en el código que instancia la config directamente.
SpringConfig = SpringSweepConfig


@dataclass(frozen=True)
class UpthrustConfig:
    """Parametros matematicos del detector Upthrust (bajista, espejo de Spring)."""

    resistance_lookback: int = 18
    min_rows: int = 20
    break_buffer_pct: float = 0.00005
    reclaim_tolerance_pct: float = 0.00030
    min_upper_wick_ratio: float = 0.45
    confirm_break_buffer_pct: float = 0.00005
    min_confirm_body_ratio: float = 0.40


@dataclass(frozen=True)
class WyckoffEarlyConfig:
    """Detector temprano M1+M2 (barrido + reacción) sin exigir confirmación M3."""

    lookback: int = 18
    min_rows: int = 20
    break_buffer_pct: float = 0.00005
    reclaim_tolerance_pct: float = 0.00030
    min_wick_ratio: float = 0.40


def _normalize_ohlc(df: pd.DataFrame) -> pd.DataFrame:
    """Normaliza alias de columnas a open/high/low/close/volume."""
    alias = {
        "o": "open",
        "h": "high",
        "l": "low",
        "c": "close",
        "v": "volume",
    }
    cols = {c.lower(): c for c in df.columns}
    renamed = {}
    for key, original in cols.items():
        if key in alias:
            renamed[original] = alias[key]
    if renamed:
        df = df.rename(columns=renamed)

    required = ["open", "high", "low", "close"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Faltan columnas OHLC requeridas: {missing}")

    out = df.copy()
    cast_cols = [c for c in ["open", "high", "low", "close", "volume"] if c in out.columns]
    for col in cast_cols:
        out[col] = pd.to_numeric(out[col], errors="coerce")

    out = out.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)
    return out


def _safe_ratio(num: float, den: float, default: float = 0.0) -> float:
    if den == 0:
        return default
    return num / den


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _confidence_from_metrics(
    breach_depth_pct: float,
    close_vs_support_pct: float,
    lower_wick_ratio: float,
    confirm_break_pct: float,
    confirm_body_ratio: float,
) -> float:
    """
    Combina metricas en [0, 1] con pesos simples.

    Intuicion:
    - Barrido: debe romper soporte pero no demasiado profundo.
    - Rechazo: cierre recuperando soporte + mecha inferior notoria.
    - Impulso: confirmacion rompe maximo del sweep con cuerpo alcista.
    """
    # Mejor si la ruptura es moderada (ej: 0.02% a 0.12%).
    depth_ideal_low = 0.0002
    depth_ideal_high = 0.0012
    if breach_depth_pct < depth_ideal_low:
        depth_score = _clamp(breach_depth_pct / depth_ideal_low, 0.0, 1.0)
    elif breach_depth_pct <= depth_ideal_high:
        depth_score = 1.0
    else:
        depth_score = _clamp(1.0 - (breach_depth_pct - depth_ideal_high) / 0.0020, 0.0, 1.0)

    reclaim_score = _clamp(1.0 - max(0.0, close_vs_support_pct) / 0.0015, 0.0, 1.0)
    wick_score = _clamp((lower_wick_ratio - 0.30) / 0.50, 0.0, 1.0)
    break_score = _clamp(confirm_break_pct / 0.0012, 0.0, 1.0)
    body_score = _clamp((confirm_body_ratio - 0.20) / 0.60, 0.0, 1.0)

    score = (
        depth_score * 0.20
        + reclaim_score * 0.25
        + wick_score * 0.20
        + break_score * 0.20
        + body_score * 0.15
    )
    return round(_clamp(score, 0.0, 1.0), 4)


def detect_spring_sweep(
    df: pd.DataFrame,
    config: SpringSweepConfig | None = None,
) -> tuple[bool, dict[str, Any]]:
    """
    Detecta Wyckoff Spring en las dos ultimas velas:
    - Vela -2: sweep (rompe soporte y recupera)
    - Vela -1: confirmacion alcista (rompe maximo del sweep)
    """
    cfg = config or SpringSweepConfig()
    data = _normalize_ohlc(df)

    if len(data) < cfg.min_rows:
        return False, {
            "pattern": "spring_sweep",
            "reason": f"Datos insuficientes: {len(data)} < {cfg.min_rows}",
            "confidence": 0.0,
            "suggested_entry": None,
        }

    sweep_idx = len(data) - 2
    confirm_idx = len(data) - 1

    support_start = max(0, sweep_idx - cfg.support_lookback)
    support_end = sweep_idx  # excluye sweep/confirmacion para evitar leak
    support_slice = data.iloc[support_start:support_end]

    if support_slice.empty:
        return False, {
            "pattern": "spring_sweep",
            "reason": "No hay ventana suficiente para soporte previo.",
            "confidence": 0.0,
            "suggested_entry": None,
        }

    support = float(support_slice["low"].min())

    sweep = data.iloc[sweep_idx]
    confirm = data.iloc[confirm_idx]

    sweep_range = float(sweep["high"] - sweep["low"])
    sweep_lower_wick = float(min(sweep["open"], sweep["close"]) - sweep["low"])
    lower_wick_ratio = _safe_ratio(sweep_lower_wick, sweep_range, default=0.0)

    confirm_range = float(confirm["high"] - confirm["low"])
    confirm_body = float(confirm["close"] - confirm["open"])
    confirm_body_ratio = _safe_ratio(confirm_body, confirm_range, default=0.0)

    broke_support = float(sweep["low"]) < support * (1.0 - cfg.break_buffer_pct)
    reclaimed_support = float(sweep["close"]) >= support * (1.0 - cfg.reclaim_tolerance_pct)
    strong_rejection = lower_wick_ratio >= cfg.min_lower_wick_ratio

    confirm_breaks_sweep_high = float(confirm["high"]) > float(sweep["high"]) * (
        1.0 + cfg.confirm_break_buffer_pct
    )
    confirm_bullish = float(confirm["close"]) > float(confirm["open"])
    confirm_closes_above_sweep = float(confirm["close"]) > float(sweep["high"])
    confirm_has_body = confirm_body_ratio >= cfg.min_confirm_body_ratio

    is_valid = all(
        [
            broke_support,
            reclaimed_support,
            strong_rejection,
            confirm_breaks_sweep_high,
            confirm_bullish,
            confirm_closes_above_sweep,
            confirm_has_body,
        ]
    )

    breach_depth_pct = _safe_ratio(support - float(sweep["low"]), support, default=0.0)
    close_vs_support_pct = _safe_ratio(abs(float(sweep["close"]) - support), support, default=0.0)
    confirm_break_pct = _safe_ratio(float(confirm["high"]) - float(sweep["high"]), float(sweep["high"]), default=0.0)

    confidence = _confidence_from_metrics(
        breach_depth_pct=breach_depth_pct,
        close_vs_support_pct=close_vs_support_pct,
        lower_wick_ratio=lower_wick_ratio,
        confirm_break_pct=confirm_break_pct,
        confirm_body_ratio=confirm_body_ratio,
    )

    # Entrada sugerida conservadora: ruptura/continuacion sobre maximo de confirmacion.
    suggested_entry = float(confirm["high"])

    details = {
        "pattern": "spring_sweep",
        "signal_type": "spring",
        "direction": "call",
        "is_valid": bool(is_valid),
        "confidence": confidence,
        "confidence_pct": round(confidence * 100.0, 2),
        "suggested_entry": suggested_entry,
        "support_level": support,
        "sweep_index": sweep_idx,
        "confirm_index": confirm_idx,
        "metrics": {
            "broke_support": bool(broke_support),
            "reclaimed_support": bool(reclaimed_support),
            "lower_wick_ratio": round(lower_wick_ratio, 4),
            "confirm_breaks_sweep_high": bool(confirm_breaks_sweep_high),
            "confirm_body_ratio": round(confirm_body_ratio, 4),
            "breach_depth_pct": round(breach_depth_pct, 6),
            "confirm_break_pct": round(confirm_break_pct, 6),
        },
    }

    if not is_valid:
        failing = []
        if not broke_support:
            failing.append("no rompió soporte")
        if not reclaimed_support:
            failing.append("no recuperó soporte al cierre")
        if not strong_rejection:
            failing.append("mecha inferior insuficiente")
        if not confirm_breaks_sweep_high:
            failing.append("confirmación no rompe máximo del sweep")
        if not confirm_bullish:
            failing.append("confirmación no es alcista")
        if not confirm_closes_above_sweep:
            failing.append("confirmación no cierra sobre el máximo del sweep")
        if not confirm_has_body:
            failing.append("cuerpo de confirmación débil")
        details["reason"] = "; ".join(failing)

    return bool(is_valid), details


class SpringSweepStrategy:
    """Wrapper OO opcional para integraciones que prefieren clase."""

    def __init__(self, config: SpringSweepConfig | None = None) -> None:
        self.config = config or SpringSweepConfig()

    def evaluate(self, candles_df: pd.DataFrame) -> tuple[bool, dict[str, Any]]:
        return detect_spring_sweep(candles_df, config=self.config)


# ─────────────────────────────────────────────────────────────────────────────
#  UPTHRUST — Patrón bajista espejo del Spring Sweep
# ─────────────────────────────────────────────────────────────────────────────

def _confidence_upthrust(
    breach_depth_pct: float,
    close_vs_resistance_pct: float,
    upper_wick_ratio: float,
    confirm_break_pct: float,
    confirm_body_ratio: float,
) -> float:
    """Confianza del Upthrust — espejo exacto de _confidence_from_metrics."""
    depth_ideal_low = 0.0002
    depth_ideal_high = 0.0012
    if breach_depth_pct < depth_ideal_low:
        depth_score = _clamp(breach_depth_pct / depth_ideal_low, 0.0, 1.0)
    elif breach_depth_pct <= depth_ideal_high:
        depth_score = 1.0
    else:
        depth_score = _clamp(1.0 - (breach_depth_pct - depth_ideal_high) / 0.0020, 0.0, 1.0)

    reclaim_score = _clamp(1.0 - max(0.0, close_vs_resistance_pct) / 0.0015, 0.0, 1.0)
    wick_score = _clamp((upper_wick_ratio - 0.30) / 0.50, 0.0, 1.0)
    break_score = _clamp(confirm_break_pct / 0.0012, 0.0, 1.0)
    body_score = _clamp((confirm_body_ratio - 0.20) / 0.60, 0.0, 1.0)

    score = (
        depth_score * 0.20
        + reclaim_score * 0.25
        + wick_score * 0.20
        + break_score * 0.20
        + body_score * 0.15
    )
    return round(_clamp(score, 0.0, 1.0), 4)


def detect_upthrust(
    df: pd.DataFrame,
    config: UpthrustConfig | None = None,
) -> tuple[bool, dict[str, Any]]:
    """
    Detecta Wyckoff Upthrust en las dos ultimas velas:
    - Vela -2: upthrust (rompe resistencia y regresa)
    - Vela -1: confirmacion bajista (rompe minimo del upthrust)

    Es el espejo exacto de detect_spring_sweep aplicado a maximos.
    Señal: PUT (distribución, probable caída).
    """
    cfg = config or UpthrustConfig()
    data = _normalize_ohlc(df)

    if len(data) < cfg.min_rows:
        return False, {
            "pattern": "upthrust",
            "signal_type": None,
            "direction": None,
            "reason": f"Datos insuficientes: {len(data)} < {cfg.min_rows}",
            "confidence": 0.0,
            "suggested_entry": None,
        }

    ut_idx = len(data) - 2
    confirm_idx = len(data) - 1

    resistance_start = max(0, ut_idx - cfg.resistance_lookback)
    resistance_slice = data.iloc[resistance_start:ut_idx]

    if resistance_slice.empty:
        return False, {
            "pattern": "upthrust",
            "signal_type": None,
            "direction": None,
            "reason": "No hay ventana suficiente para resistencia previa.",
            "confidence": 0.0,
            "suggested_entry": None,
        }

    resistance = float(resistance_slice["high"].max())

    ut = data.iloc[ut_idx]
    confirm = data.iloc[confirm_idx]

    ut_range = float(ut["high"] - ut["low"])
    ut_upper_wick = float(ut["high"] - max(ut["open"], ut["close"]))
    upper_wick_ratio = _safe_ratio(ut_upper_wick, ut_range, default=0.0)

    confirm_range = float(confirm["high"] - confirm["low"])
    confirm_body = float(confirm["open"] - confirm["close"])  # bajista: open > close
    confirm_body_ratio = _safe_ratio(confirm_body, confirm_range, default=0.0)

    broke_resistance = float(ut["high"]) > resistance * (1.0 + cfg.break_buffer_pct)
    reclaimed_resistance = float(ut["close"]) <= resistance * (1.0 + cfg.reclaim_tolerance_pct)
    strong_rejection = upper_wick_ratio >= cfg.min_upper_wick_ratio

    confirm_breaks_ut_low = float(confirm["low"]) < float(ut["low"]) * (
        1.0 - cfg.confirm_break_buffer_pct
    )
    confirm_bearish = float(confirm["close"]) < float(confirm["open"])
    confirm_closes_below_ut = float(confirm["close"]) < float(ut["low"])
    confirm_has_body = confirm_body_ratio >= cfg.min_confirm_body_ratio

    is_valid = all(
        [
            broke_resistance,
            reclaimed_resistance,
            strong_rejection,
            confirm_breaks_ut_low,
            confirm_bearish,
            confirm_closes_below_ut,
            confirm_has_body,
        ]
    )

    breach_depth_pct = _safe_ratio(float(ut["high"]) - resistance, resistance, default=0.0)
    close_vs_resistance_pct = _safe_ratio(
        abs(float(ut["close"]) - resistance), resistance, default=0.0
    )
    confirm_break_pct = _safe_ratio(
        float(ut["low"]) - float(confirm["low"]), float(ut["low"]), default=0.0
    )

    confidence = _confidence_upthrust(
        breach_depth_pct=breach_depth_pct,
        close_vs_resistance_pct=close_vs_resistance_pct,
        upper_wick_ratio=upper_wick_ratio,
        confirm_break_pct=confirm_break_pct,
        confirm_body_ratio=confirm_body_ratio,
    )

    suggested_entry = float(confirm["low"])

    details: dict[str, Any] = {
        "pattern": "upthrust",
        "signal_type": "upthrust",
        "direction": "put",
        "is_valid": bool(is_valid),
        "confidence": confidence,
        "confidence_pct": round(confidence * 100.0, 2),
        "suggested_entry": suggested_entry,
        "resistance_level": resistance,
        "upthrust_index": ut_idx,
        "confirm_index": confirm_idx,
        "metrics": {
            "broke_resistance": bool(broke_resistance),
            "reclaimed_resistance": bool(reclaimed_resistance),
            "upper_wick_ratio": round(upper_wick_ratio, 4),
            "confirm_breaks_ut_low": bool(confirm_breaks_ut_low),
            "confirm_body_ratio": round(confirm_body_ratio, 4),
            "breach_depth_pct": round(breach_depth_pct, 6),
            "confirm_break_pct": round(confirm_break_pct, 6),
        },
    }

    if not is_valid:
        failing = []
        if not broke_resistance:
            failing.append("no rompió resistencia")
        if not reclaimed_resistance:
            failing.append("no regresó a resistencia al cierre")
        if not strong_rejection:
            failing.append("mecha superior insuficiente")
        if not confirm_breaks_ut_low:
            failing.append("confirmación no rompe mínimo del upthrust")
        if not confirm_bearish:
            failing.append("confirmación no es bajista")
        if not confirm_closes_below_ut:
            failing.append("confirmación no cierra bajo el mínimo del upthrust")
        if not confirm_has_body:
            failing.append("cuerpo de confirmación débil")
        details["reason"] = "; ".join(failing)

    return bool(is_valid), details


def detect_wyckoff_early(
    df: pd.DataFrame,
    config: WyckoffEarlyConfig | None = None,
) -> tuple[bool, dict[str, Any]]:
    """
    Captura Wyckoff temprano (primeros 2 movimientos):
    - M1: barrido de nivel (soporte o resistencia)
    - M2: reacción inmediata/reclaim en la misma vela de barrido

    No exige M3 de confirmación, por eso se considera señal "early".
    """
    cfg = config or WyckoffEarlyConfig()
    data = _normalize_ohlc(df)

    if len(data) < cfg.min_rows:
        return False, {
            "pattern": "wyckoff_early",
            "signal_type": None,
            "direction": None,
            "reason": f"Datos insuficientes: {len(data)} < {cfg.min_rows}",
            "confidence": 0.0,
            "suggested_entry": None,
        }

    sweep_idx = len(data) - 1
    sweep = data.iloc[sweep_idx]

    start = max(0, sweep_idx - cfg.lookback)
    prev_slice = data.iloc[start:sweep_idx]
    if prev_slice.empty:
        return False, {
            "pattern": "wyckoff_early",
            "signal_type": None,
            "direction": None,
            "reason": "No hay ventana previa para niveles.",
            "confidence": 0.0,
            "suggested_entry": None,
        }

    support = float(prev_slice["low"].min())
    resistance = float(prev_slice["high"].max())

    rng = float(sweep["high"] - sweep["low"])
    lower_wick = float(min(sweep["open"], sweep["close"]) - sweep["low"])
    upper_wick = float(sweep["high"] - max(sweep["open"], sweep["close"]))
    lower_wick_ratio = _safe_ratio(lower_wick, rng, default=0.0)
    upper_wick_ratio = _safe_ratio(upper_wick, rng, default=0.0)

    # Early bullish (spring M1+M2)
    broke_support = float(sweep["low"]) < support * (1.0 - cfg.break_buffer_pct)
    reclaimed_support = float(sweep["close"]) >= support * (1.0 - cfg.reclaim_tolerance_pct)
    spring_early_valid = broke_support and reclaimed_support and lower_wick_ratio >= cfg.min_wick_ratio

    spring_depth_pct = _safe_ratio(support - float(sweep["low"]), support, default=0.0)
    spring_reclaim_pct = _safe_ratio(abs(float(sweep["close"]) - support), support, default=0.0)
    spring_conf = _confidence_from_metrics(
        breach_depth_pct=max(0.0, spring_depth_pct),
        close_vs_support_pct=spring_reclaim_pct,
        lower_wick_ratio=lower_wick_ratio,
        confirm_break_pct=0.0,
        confirm_body_ratio=0.25,
    )

    # Early bearish (upthrust M1+M2)
    broke_resistance = float(sweep["high"]) > resistance * (1.0 + cfg.break_buffer_pct)
    reclaimed_resistance = float(sweep["close"]) <= resistance * (1.0 + cfg.reclaim_tolerance_pct)
    upthrust_early_valid = (
        broke_resistance and reclaimed_resistance and upper_wick_ratio >= cfg.min_wick_ratio
    )

    upthrust_depth_pct = _safe_ratio(float(sweep["high"]) - resistance, resistance, default=0.0)
    upthrust_reclaim_pct = _safe_ratio(abs(float(sweep["close"]) - resistance), resistance, default=0.0)
    upthrust_conf = _confidence_upthrust(
        breach_depth_pct=max(0.0, upthrust_depth_pct),
        close_vs_resistance_pct=upthrust_reclaim_pct,
        upper_wick_ratio=upper_wick_ratio,
        confirm_break_pct=0.0,
        confirm_body_ratio=0.25,
    )

    # Escalado leve para reflejar que aún falta M3
    spring_conf = round(_clamp(spring_conf * 0.88, 0.0, 1.0), 4)
    upthrust_conf = round(_clamp(upthrust_conf * 0.88, 0.0, 1.0), 4)

    if spring_early_valid and spring_conf >= upthrust_conf:
        return True, {
            "pattern": "wyckoff_early",
            "signal_type": "wyckoff_early_spring",
            "direction": "call",
            "is_valid": True,
            "confidence": spring_conf,
            "confidence_pct": round(spring_conf * 100.0, 2),
            "suggested_entry": float(sweep["close"]),
            "support_level": support,
            "movement": "M1+M2",
            "reason": "Barrido de soporte y reclaim temprano (sin M3)",
        }

    if upthrust_early_valid:
        return True, {
            "pattern": "wyckoff_early",
            "signal_type": "wyckoff_early_upthrust",
            "direction": "put",
            "is_valid": True,
            "confidence": upthrust_conf,
            "confidence_pct": round(upthrust_conf * 100.0, 2),
            "suggested_entry": float(sweep["close"]),
            "resistance_level": resistance,
            "movement": "M1+M2",
            "reason": "Barrido de resistencia y reclaim temprano (sin M3)",
        }

    # near-miss: devolver el lado con mayor confianza para logging
    if upthrust_conf > spring_conf:
        return False, {
            "pattern": "wyckoff_early",
            "signal_type": "wyckoff_early_upthrust",
            "direction": "put",
            "is_valid": False,
            "confidence": upthrust_conf,
            "confidence_pct": round(upthrust_conf * 100.0, 2),
            "reason": "Sin reclaim/mecha suficiente en upthrust temprano",
        }

    return False, {
        "pattern": "wyckoff_early",
        "signal_type": "wyckoff_early_spring",
        "direction": "call",
        "is_valid": False,
        "confidence": spring_conf,
        "confidence_pct": round(spring_conf * 100.0, 2),
        "reason": "Sin reclaim/mecha suficiente en spring temprano",
    }


# ─────────────────────────────────────────────────────────────────────────────
#  COMBINADO — corre ambos detectores y retorna el de mayor confianza
# ─────────────────────────────────────────────────────────────────────────────

def detect_spring_or_upthrust(
    df: pd.DataFrame,
    spring_config: SpringSweepConfig | None = None,
    upthrust_config: UpthrustConfig | None = None,
    early_config: WyckoffEarlyConfig | None = None,
    allow_early: bool = True,
) -> tuple[bool, dict[str, Any]]:
    """
    Ejecuta detect_spring_sweep y detect_upthrust sobre el mismo DataFrame.
    Retorna el resultado con mayor confidence. Si empatan, prefiere Spring.

    El dict resultado incluye siempre:
      "signal_type": "spring" | "upthrust" | None
      "direction":   "call"   | "put"      | None
    """
    spring_valid, spring_info = detect_spring_sweep(df, config=spring_config)
    upthrust_valid, upthrust_info = detect_upthrust(df, config=upthrust_config)
    early_valid, early_info = detect_wyckoff_early(df, config=early_config) if allow_early else (False, {
        "confidence": 0.0,
        "signal_type": None,
        "direction": None,
    })

    spring_conf = float(spring_info.get("confidence", 0.0))
    upthrust_conf = float(upthrust_info.get("confidence", 0.0))
    early_conf = float(early_info.get("confidence", 0.0))

    # Enriquecer el dict de spring con los campos estandar
    spring_info.setdefault("signal_type", "spring" if spring_valid else None)
    spring_info.setdefault("direction", "call")

    if upthrust_valid and upthrust_conf > spring_conf:
        return True, upthrust_info

    if spring_valid:
        return True, spring_info

    if early_valid:
        return True, early_info

    # Ninguno es válido — retornar el de mayor confianza para near-miss logging
    if upthrust_conf > spring_conf:
        if upthrust_conf >= early_conf:
            return False, upthrust_info
        return False, early_info

    if early_conf > spring_conf:
        return False, early_info

    return False, spring_info
