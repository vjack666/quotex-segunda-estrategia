"""
models.py — Estructuras de datos compartidas entre módulos.

Importar desde aquí para evitar imports circulares entre
consolidation_bot.py y entry_scorer.py.
"""
from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class Candle:
    ts:    int
    open:  float
    high:  float
    low:   float
    close: float

    @property
    def body(self) -> float:
        """Tamaño absoluto del cuerpo (proxy de volumen)."""
        return abs(self.close - self.open)

    @property
    def range(self) -> float:
        return self.high - self.low


@dataclass
class ConsolidationZone:
    asset:       str
    ceiling:     float   # resistencia (techo)
    floor:       float   # soporte (piso)
    bars_inside: int
    detected_at: float
    range_pct:   float

    @property
    def midpoint(self) -> float:
        return (self.ceiling + self.floor) / 2

    @property
    def age_minutes(self) -> float:
        return (time.time() - self.detected_at) / 60
