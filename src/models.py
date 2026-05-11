"""
models.py — Estructuras de datos compartidas entre módulos.

Importar desde aquí para evitar imports circulares entre módulos.

CONTENIDO:
- Candle: Estructura de vela OHLCV
- ConsolidationZone: Zona de consolidación detectada
- SignalMode: Enum de modo de señal (rebound/breakout)
- CandidateEntry: Candidato a entrar en operación
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from zone_memory import HistoricalZone


@dataclass
class Candle:
    """Vela OHLCV con timestamp."""
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
        """Rango total de la vela."""
        return self.high - self.low


@dataclass
class ConsolidationZone:
    """Zona de consolidación detectada en el mercado."""
    asset:       str
    ceiling:     float   # resistencia (techo)
    floor:       float   # soporte (piso)
    bars_inside: int     # cantidad de velas dentro de la zona
    detected_at: float   # timestamp de detección
    range_pct:   float   # rango como % del precio

    @property
    def midpoint(self) -> float:
        """Punto medio de la zona."""
        return (self.ceiling + self.floor) / 2

    @property
    def age_minutes(self) -> float:
        """Antigüedad de la zona en minutos."""
        return (time.time() - self.detected_at) / 60


class SignalMode(Enum):
    """Modo de señal del candidato a entrar."""
    REBOUND = "rebound"      # rebote en extremo de zona
    BREAKOUT = "breakout"    # ruptura de zona con fuerza


@dataclass
class CandidateEntry:
    """
    Candidato a entrar en operación.
    
    Contiene toda la información necesaria para validar y ejecutar una entrada:
    - Activo, dirección, zona de consolidación
    - Score compuesto de múltiples componentes
    - Patrón de vela confirmado + fortaleza
    - Historia de zonas cercanas (zone memory)
    """
    asset: str
    payout: int
    zone: ConsolidationZone
    direction: str
    candles: List[Candle]
    
    # Scoring
    score: float = 0.0
    score_breakdown: dict = field(default_factory=dict)
    
    # Patrón de vela 1m
    reversal_pattern: str = "none"
    reversal_strength: float = 0.0
    reversal_confirms: bool = False
    
    # Modo de señal
    mode: SignalMode = SignalMode.REBOUND
    
    # Datos adicionales
    candles_h1: List[Candle] = field(default_factory=list)
    zone_memory: list = field(default_factory=list)  # List[HistoricalZone] pero sin ciclo

    def __str__(self) -> str:
        """Representación legible del candidato."""
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
