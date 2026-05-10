"""
zone_memory.py
==============
Módulo de memoria de zonas históricas de consolidación.

Lee la tabla `expired_zones` del journal SQLite y clasifica las zonas pasadas
del mismo activo como soporte, resistencia o neutral, según cómo terminaron
(BROKEN_ABOVE, BROKEN_BELOW, TIME_LIMIT) y su posición relativa al precio actual.

La información se usa en entry_scorer.py para bonificar o penalizar entradas
según si hay acumulaciones previas que actúen como muro o como trampolín.

USO:
    from zone_memory import ZoneMemory, query_nearby_zones
    zones = query_nearby_zones(db_path, asset="EURJPY_otc", current_price=184.44)
    adj   = score_zone_memory(zones, direction="call", current_price=184.44)
"""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List

# ─────────────────────────────────────────────────────────────────────────────
#  PARÁMETROS
# ─────────────────────────────────────────────────────────────────────────────

# Radio (% del precio) dentro del cual una zona vieja es "relevante"
ZONE_MEMORY_RADIUS_PCT   = 0.004   # 0.4% — cubre aprox 4 velas de movimiento 5m

# Solo considerar zonas con menos de N horas de antigüedad
ZONE_MEMORY_MAX_AGE_H    = 48.0

# Mínimo de barras dentro para que la zona tenga peso (zonas de 1-2 velas = ruido)
ZONE_MEMORY_MIN_BARS     = 4

# Distancia "peligrosa": si hay nivel a menos de este % bloqueando la dirección → penalizar
ZONE_MEMORY_DANGER_PCT   = 0.0015  # 0.15%

# Ajustes al score
ZONE_MEMORY_BONUS_CLEAR_PATH  = 8.0   # zona rota en la dirección → camino libre
ZONE_MEMORY_BONUS_SUPPORT     = 5.0   # soporte/resistencia histórica alineada
ZONE_MEMORY_PENALTY_WALL      = -15.0 # muro histórico no roto a <0.15% bloqueando
ZONE_MEMORY_PENALTY_AGAINST   = -8.0  # zona en la dirección opuesta, sin romper

# Factores de decaimiento por antigüedad (la zona "se olvida" con el tiempo)
_DECAY_TABLE = [
    (4.0,  1.0),    # < 4h  → 100%
    (12.0, 0.75),   # < 12h → 75%
    (24.0, 0.50),   # < 24h → 50%
    (48.0, 0.25),   # < 48h → 25%
]


# ─────────────────────────────────────────────────────────────────────────────
#  DATACLASSES
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class HistoricalZone:
    """Zona de consolidación pasada relevante para el precio actual."""
    ceiling:       float
    floor:         float
    midpoint:      float
    bars_inside:   int           # proxy de fuerza de la acumulación
    expiry_reason: str           # BROKEN_ABOVE | BROKEN_BELOW | TIME_LIMIT
    age_hours:     float         # antigüedad en horas al momento de consulta
    role:          str           # "resistance" | "support" | "neutral"
    strength:      float         # 0.0–1.0 (bars_inside normalizado × decay)
    dist_pct:      float         # distancia % al precio actual (positivo = encima)

    def __repr__(self) -> str:
        return (
            f"HistoricalZone({self.role.upper()} "
            f"{self.floor:.5f}–{self.ceiling:.5f} "
            f"bars={self.bars_inside} age={self.age_hours:.1f}h "
            f"reason={self.expiry_reason} str={self.strength:.2f})"
        )


# ─────────────────────────────────────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _decay(age_hours: float) -> float:
    for threshold, factor in _DECAY_TABLE:
        if age_hours < threshold:
            return factor
    return 0.0


def _strength(bars_inside: int, age_hours: float) -> float:
    # Normalizar barras: 4 barras = mínimo útil, 20+ = máximo
    normalized = min(1.0, max(0.0, (bars_inside - 4) / 16.0))
    return round(normalized * _decay(age_hours), 3)


def _classify_role(expiry_reason: str, dist_pct: float) -> str:
    """
    Determina el rol de la zona respecto al precio actual.

    dist_pct > 0  → zona está ENCIMA del precio
    dist_pct < 0  → zona está DEBAJO del precio

    BROKEN_ABOVE (zona rota hacia arriba):
      - Si está debajo → fue soporte que se superó → ahora actúa como soporte (pull-back típico)
      - Si está encima → raro, tratar como neutral

    BROKEN_BELOW (zona rota hacia abajo):
      - Si está encima → fue soporte que cayó → ahora actúa como resistencia (flip típico)
      - Si está debajo → raro, tratar como neutral

    TIME_LIMIT (zona que murió sin romperse):
      - Actúa como muro: si está encima → resistencia; si está abajo → soporte
    """
    if expiry_reason == "BROKEN_ABOVE":
        return "support" if dist_pct < 0 else "neutral"
    if expiry_reason == "BROKEN_BELOW":
        return "resistance" if dist_pct > 0 else "neutral"
    # TIME_LIMIT — zona intacta, más fuerte como muro
    return "resistance" if dist_pct > 0 else "support"


# ─────────────────────────────────────────────────────────────────────────────
#  FUNCIÓN PRINCIPAL DE CONSULTA
# ─────────────────────────────────────────────────────────────────────────────

def query_nearby_zones(
    db_path: str | Path,
    asset: str,
    current_price: float,
    radius_pct: float = ZONE_MEMORY_RADIUS_PCT,
    max_age_hours: float = ZONE_MEMORY_MAX_AGE_H,
    min_bars: int = ZONE_MEMORY_MIN_BARS,
) -> List[HistoricalZone]:
    """
    Consulta las zonas históricas del activo que están dentro del radio del precio actual.

    Devuelve lista vacía si la DB no existe, no tiene datos o hay error de IO.
    Nunca lanza excepción — el llamador puede usarla sin try/except.
    """
    db_path = Path(db_path)
    if not db_path.exists():
        return []

    now = time.time()
    since_iso = _ts_to_iso(now - max_age_hours * 3600)
    radius    = current_price * radius_pct

    price_lo = current_price - radius
    price_hi = current_price + radius

    try:
        conn = sqlite3.connect(str(db_path), timeout=3.0)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT ceiling, floor, bars_inside, expiry_reason, expired_at
            FROM   expired_zones
            WHERE  asset          = ?
              AND  expired_at    >= ?
              AND  bars_inside   >= ?
              AND  ceiling       >= ?
              AND  floor         <= ?
            ORDER  BY id DESC
            LIMIT  20
            """,
            (asset, since_iso, min_bars, price_lo, price_hi),
        ).fetchall()
        conn.close()
    except Exception:
        return []

    result: List[HistoricalZone] = []
    seen: set[tuple] = set()   # dedup: evitar zonas casi idénticas

    for row in rows:
        ceiling = float(row["ceiling"])
        floor   = float(row["floor"])
        mid     = (ceiling + floor) / 2.0
        bars    = int(row["bars_inside"] or 0)
        reason  = str(row["expiry_reason"] or "TIME_LIMIT")

        # Antigüedad
        try:
            from datetime import datetime, timezone, timedelta
            _tz = timezone(timedelta(hours=-3))
            exp_dt  = datetime.fromisoformat(str(row["expired_at"]))
            age_sec = (datetime.now(tz=_tz) - exp_dt).total_seconds()
            age_h   = max(0.0, age_sec / 3600.0)
        except Exception:
            age_h = max_age_hours  # peor caso: la más vieja posible

        # Dedup: redondear midpoint a 3 decimales para colisión
        dedup_key = (round(mid, 3), reason)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        # Posición relativa al precio (+ = encima, - = abajo)
        dist_pct = (mid - current_price) / current_price

        role     = _classify_role(reason, dist_pct)
        strength = _strength(bars, age_h)

        result.append(HistoricalZone(
            ceiling       = ceiling,
            floor         = floor,
            midpoint      = mid,
            bars_inside   = bars,
            expiry_reason = reason,
            age_hours     = age_h,
            role          = role,
            strength      = strength,
            dist_pct      = dist_pct,
        ))

    # Ordenar por proximidad al precio actual
    result.sort(key=lambda z: abs(z.dist_pct))
    return result


# ─────────────────────────────────────────────────────────────────────────────
#  FUNCIÓN DE SCORING
# ─────────────────────────────────────────────────────────────────────────────

def score_zone_memory(
    zones: List[HistoricalZone],
    direction: str,
    current_price: float,
) -> float:
    """
    Calcula el ajuste al score (positivo o negativo) basado en zonas históricas.

    Reglas:
      CALL:
        +bonus  si hay soporte histórico debajo (precio tiene base)
        +bonus  si zona rota hacia arriba (BROKEN_ABOVE) encima → camino limpio
        -penalty si hay resistencia no rota (TIME_LIMIT) encima a < DANGER_PCT
        -penalty si hay resistencia (BROKEN_BELOW flip) encima a < DANGER_PCT

      PUT:
        +bonus  si hay resistencia histórica encima (precio tiene techo)
        +bonus  si zona rota hacia abajo (BROKEN_BELOW) abajo → camino limpio
        -penalty si hay soporte no roto (TIME_LIMIT) abajo a < DANGER_PCT
        -penalty si hay soporte (BROKEN_ABOVE flip) abajo a < DANGER_PCT

    Retorna el ajuste total (puede ser 0.0 si no hay zonas relevantes).
    """
    if not zones:
        return 0.0

    direction = direction.lower()
    total_adj = 0.0
    danger_threshold = ZONE_MEMORY_DANGER_PCT

    for z in zones:
        above = z.dist_pct > 0   # zona está encima del precio
        below = z.dist_pct < 0   # zona está debajo del precio
        close = abs(z.dist_pct) < danger_threshold
        w     = z.strength       # 0.0–1.0

        if direction == "call":
            # Soporte abajo → buena base, bonificar
            if below and z.role == "support":
                total_adj += ZONE_MEMORY_BONUS_SUPPORT * w

            # Zona rota hacia arriba (BROKEN_ABOVE) encima → camino libre
            if above and z.expiry_reason == "BROKEN_ABOVE":
                total_adj += ZONE_MEMORY_BONUS_CLEAR_PATH * w

            # Muro encima cerca → peligro para CALL
            if above and close and z.role == "resistance":
                total_adj += ZONE_MEMORY_PENALTY_WALL * w

            # Zona resistencia no tan cerca pero encima
            if above and not close and z.role == "resistance":
                total_adj += ZONE_MEMORY_PENALTY_AGAINST * w * 0.5

        else:  # PUT
            # Resistencia encima → buena presión bajista, bonificar
            if above and z.role == "resistance":
                total_adj += ZONE_MEMORY_BONUS_SUPPORT * w

            # Zona rota hacia abajo (BROKEN_BELOW) abajo → camino libre
            if below and z.expiry_reason == "BROKEN_BELOW":
                total_adj += ZONE_MEMORY_BONUS_CLEAR_PATH * w

            # Piso abajo cerca → peligro para PUT
            if below and close and z.role == "support":
                total_adj += ZONE_MEMORY_PENALTY_WALL * w

            # Zona soporte no tan cerca pero abajo
            if below and not close and z.role == "support":
                total_adj += ZONE_MEMORY_PENALTY_AGAINST * w * 0.5

    return round(total_adj, 2)


# ─────────────────────────────────────────────────────────────────────────────
#  HELPERS INTERNOS
# ─────────────────────────────────────────────────────────────────────────────

def _ts_to_iso(ts: float) -> str:
    """Convierte timestamp UNIX a string ISO-8601 comparable con la DB (UTC-3)."""
    from datetime import datetime, timezone, timedelta
    tz = timezone(timedelta(hours=-3))
    return datetime.fromtimestamp(ts, tz=tz).isoformat()
