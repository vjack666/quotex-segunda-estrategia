"""
Identificador de zonas de Soporte/Resistencia horizontales.
Basado en pivotos locales dentro de una serie de velas M1.
"""
from typing import List


def detectar_zonas_sr(
    candles: List[dict],
    lookback: int = 50,
    pivot_window: int = 3,
    merge_threshold_atr_mult: float = 0.5,
) -> List[float]:
    """
    Detecta niveles horizontales de S/R como lista de precios.

    Estrategia:
    - Busca máximos/mínimos locales (pivots) en la ventana lookback.
    - Agrupa niveles que estén dentro de merge_threshold_atr_mult * ATR entre sí.
    - Retorna el nivel representativo (promedio) de cada grupo.

    Args:
        candles:   Lista de dicts con keys open/high/low/close (orden ascendente).
        lookback:  Cuántas velas hacia atrás considerar.
        pivot_window: Ventana lateral para confirmar un pivot (N velas a cada lado).
        merge_threshold_atr_mult: Multiplica ATR para definir distancia de fusión de niveles.

    Returns:
        Lista de floats — precios de zonas S/R ordenados ascendentemente.
    """
    if len(candles) < pivot_window * 2 + 1:
        return []

    window = candles[-lookback:] if len(candles) > lookback else candles
    highs  = [c['high']  for c in window]
    lows   = [c['low']   for c in window]
    closes = [c['close'] for c in window]

    # Calcular ATR de referencia para fusión
    from .indicadores_calc import atr as calc_atr
    atr_val = calc_atr(highs, lows, closes, period=7)
    merge_dist = atr_val * merge_threshold_atr_mult if atr_val > 0 else 0.0001

    n = len(window)
    raw_levels: List[float] = []

    for i in range(pivot_window, n - pivot_window):
        # Pivot high
        if all(highs[i] >= highs[i - j] for j in range(1, pivot_window + 1)) and \
           all(highs[i] >= highs[i + j] for j in range(1, pivot_window + 1)):
            raw_levels.append(highs[i])

        # Pivot low
        if all(lows[i] <= lows[i - j] for j in range(1, pivot_window + 1)) and \
           all(lows[i] <= lows[i + j] for j in range(1, pivot_window + 1)):
            raw_levels.append(lows[i])

    if not raw_levels:
        return []

    # Fusionar niveles cercanos
    raw_levels.sort()
    merged: List[float] = []
    group: List[float] = [raw_levels[0]]

    for level in raw_levels[1:]:
        if level - group[-1] <= merge_dist:
            group.append(level)
        else:
            merged.append(sum(group) / len(group))
            group = [level]
    merged.append(sum(group) / len(group))

    return merged
