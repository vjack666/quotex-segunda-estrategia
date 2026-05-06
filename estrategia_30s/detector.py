"""
Detector de señales para la estrategia de 30 segundos.
Evalúa si en el segundo 30-41 de una vela M1 hay condiciones para entrar.

Uso standalone:
    from estrategia_30s.detector import evaluar_vela
    resultado = evaluar_vela(candles, zonas)
    if resultado:
        direction, score, detalle = resultado
"""
import time as _time
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Tuple, Dict, Any

from .indicadores_calc import ema, bollinger_bands, stochastic_d, atr
from .zonas import detectar_zonas_sr

# ── Parámetros por defecto (sobrescribibles desde main.py) ──────────────────
ENTRY_WINDOW_START_SEC: int   = 30
ENTRY_WINDOW_END_SEC: int     = 41
MIN_WICK_TO_BODY_RATIO: float = 1.5
MIN_SCORE: float              = 6.0
# Filtro ATR normalizado (wick medido en unidades de ATR del propio activo)
# Reemplaza ATR_MIN/ATR_MAX absolutos — funciona en Forex, crypto y acciones.
WICK_ATR_MIN: float           = 0.15   # wick < 15% de un ATR → ruido, no estructura
WICK_ATR_MAX: float           = 3.50   # wick > 3.5 ATR → spike/noticia, no tradeable
# Legado (ya no se usan para filtrar, solo conservados por compatibilidad si alguien los lee)
ATR_MIN: float                = 0.00004
ATR_MAX: float                = 0.00040
# BROKER_TZ ya no se usa — el segundo se extrae directamente del timestamp UNIX.
# int(ts) % 60 da el segundo dentro del minuto sin depender de zona horaria.
BROKER_TZ                     = timezone(timedelta(hours=-3))  # conservado por compatibilidad

# Parametros de indicadores (calibrables)
ATR_PERIOD: int = 7

BB_PERIOD: int = 20
BB_STD_DEV: float = 2.0

# Estocástico Rápido (5,3) — timing de entrada en la ventana 30s
STOCH_K_PERIOD: int = 5
STOCH_D_PERIOD: int = 3
STOCH_EXTREME_LOW: float = 20.0
STOCH_LOW: float = 30.0
STOCH_EXTREME_HIGH: float = 80.0
STOCH_HIGH: float = 70.0

# Estocástico Lento (14,3) — reemplaza RSI, confirma momentum/tendencia
STOCH_SLOW_K_PERIOD: int = 14
STOCH_SLOW_D_PERIOD: int = 3
STOCH_SLOW_EXTREME_LOW: float = 20.0
STOCH_SLOW_LOW: float = 30.0
STOCH_SLOW_EXTREME_HIGH: float = 80.0
STOCH_SLOW_HIGH: float = 70.0

EMA_FAST_PERIOD: int = 8
EMA_SLOW_PERIOD: int = 21

# Parametros del detector de soporte/resistencia
SR_LOOKBACK: int = 50
SR_PIVOT_WINDOW: int = 3
SR_MERGE_ATR_MULT: float = 0.5
ZONE_TOLERANCE_ATR_MULT: float = 0.8

# Tipo de retorno
SignalResult = Tuple[str, float, Dict[str, Any]]


def evaluar_vela(
    candles: List[dict],
    zonas: Optional[List[float]] = None,
    *,
    check_time: bool = True,
    broker_ts: Optional[float] = None,
) -> Optional[SignalResult]:
    """
    Evalúa si la vela actual genera señal de entrada.

    Args:
        candles:    Lista de dicts {open, high, low, close} ordenados ASC.
                    Mínimo recomendado: 25 velas para indicadores.
        zonas:      Niveles S/R pre-identificados. Si es None se calculan internamente.
        check_time: Si True verifica que el segundo actual esté en [30-41].
                    Pasar False en backtesting o cuando la verificación la hace el caller.
        broker_ts:  Timestamp UNIX calibrado del broker. Elimina dependencia de timezone.
                    Si es None y check_time=True, usa time.time() (hora local).

    Returns:
        (direccion, score, detalle) si hay señal, None si no.
        direccion: "CALL" | "PUT"
        score:     Puntuación de confluencia (0–17)
        detalle:   Dict con valores de cada indicador
    """
    if len(candles) < 10:
        return None

    # ── 1. Ventana de tiempo ──────────────────────────────────────────────────
    # Se usa int(ts) % 60 para extraer el segundo sin depender de timezone.
    # broker_ts (calibrado) tiene prioridad sobre time.time() (hora local).
    if check_time:
        _ts = broker_ts if broker_ts is not None else _time.time()
        second = int(_ts) % 60
        if not (ENTRY_WINDOW_START_SEC <= second <= ENTRY_WINDOW_END_SEC):
            return None

    current = candles[-1]
    closes = [c['close'] for c in candles]
    highs  = [c['high']  for c in candles]
    lows   = [c['low']   for c in candles]

    # ── 2. Calcular wicks ─────────────────────────────────────────────────────
    body = abs(current['close'] - current['open'])
    body = body if body > 1e-10 else 1e-10
    upper_wick = current['high'] - max(current['open'], current['close'])
    lower_wick = min(current['open'], current['close']) - current['low']

    lower_ratio = lower_wick / body
    upper_ratio = upper_wick / body
    call_wick_ok = lower_ratio >= MIN_WICK_TO_BODY_RATIO
    put_wick_ok = upper_ratio >= MIN_WICK_TO_BODY_RATIO
    if not call_wick_ok and not put_wick_ok:
        return None  # sin wick de rechazo significativo

    # ── 3. Filtro ATR normalizado ──────────────────────────────────────────────
    # Mide la mecha activa en unidades de ATR del propio activo (scale-free).
    # Un wick de 0.15–3.5 ATR es estructura real; fuera de ese rango es ruido o spike.
    current_atr = atr(highs, lows, closes, period=ATR_PERIOD)
    if current_atr <= 0:
        return None
    active_wick = max(
        lower_wick if call_wick_ok else 0.0,
        upper_wick if put_wick_ok else 0.0,
    )
    wick_atr_ratio = active_wick / current_atr
    if wick_atr_ratio < WICK_ATR_MIN or wick_atr_ratio > WICK_ATR_MAX:
        return None

    # ── 4. Zona S/R cercana ───────────────────────────────────────────────────
    if zonas is None:
        zonas = detectar_zonas_sr(
            candles,
            lookback=SR_LOOKBACK,
            pivot_window=SR_PIVOT_WINDOW,
            merge_threshold_atr_mult=SR_MERGE_ATR_MULT,
        )

    tolerance = current_atr * ZONE_TOLERANCE_ATR_MULT

    call_zone_active = call_wick_ok and any(abs(current['low'] - z) <= tolerance for z in zonas)
    put_zone_active = put_wick_ok and any(abs(current['high'] - z) <= tolerance for z in zonas)
    if not call_zone_active and not put_zone_active:
        return None

    # Indicadores base antes de resolver una vela ambigua de doble rechazo.
    bb_upper, _bb_mid, bb_lower = bollinger_bands(closes, period=BB_PERIOD, std_dev=BB_STD_DEV)
    # Estocástico Rápido (5,3): timing de entrada
    k_val, d_val = stochastic_d(highs, lows, closes, k_period=STOCH_K_PERIOD, d_period=STOCH_D_PERIOD)
    stoch_valid = k_val is not None and d_val is not None and (k_val > 0.0 or d_val > 0.0)
    # Estocástico Lento (14,3): confirmación de momentum (reemplaza RSI)
    sk_val, sd_val = stochastic_d(highs, lows, closes, k_period=STOCH_SLOW_K_PERIOD, d_period=STOCH_SLOW_D_PERIOD)
    stoch_slow_valid = sk_val is not None and sd_val is not None and (sk_val > 0.0 or sd_val > 0.0)
    ema8 = ema(closes, EMA_FAST_PERIOD)
    ema21 = ema(closes, EMA_SLOW_PERIOD)

    call_bias = 0.0
    put_bias = 0.0

    # Stoch Lento — confirmación de momentum (mismo rol que RSI)
    if stoch_slow_valid:
        if sk_val < STOCH_SLOW_EXTREME_LOW and sd_val < STOCH_SLOW_EXTREME_LOW:
            call_bias += 2.0
        elif sk_val < STOCH_SLOW_LOW:
            call_bias += 1.0
        if sk_val > STOCH_SLOW_EXTREME_HIGH and sd_val > STOCH_SLOW_EXTREME_HIGH:
            put_bias += 2.0
        elif sk_val > STOCH_SLOW_HIGH:
            put_bias += 1.0

    if bb_lower is not None and current['low'] <= bb_lower:
        call_bias += 2.0
    if bb_upper is not None and current['high'] >= bb_upper:
        put_bias += 2.0

    # Stoch Rápido — timing de entrada
    if stoch_valid:
        if k_val < STOCH_EXTREME_LOW and d_val < STOCH_EXTREME_LOW:
            call_bias += 2.0
        elif k_val < STOCH_LOW:
            call_bias += 1.0
        if k_val > STOCH_EXTREME_HIGH and d_val > STOCH_EXTREME_HIGH:
            put_bias += 2.0
        elif k_val > STOCH_HIGH:
            put_bias += 1.0

    if ema8 > ema21:
        call_bias += 1.0
    elif ema8 < ema21:
        put_bias += 1.0

    dual_wick = call_wick_ok and put_wick_ok
    if dual_wick:
        if call_zone_active and put_zone_active and call_bias != put_bias:
            direction = 'CALL' if call_bias > put_bias else 'PUT'
        elif call_zone_active and not put_zone_active:
            direction = 'CALL'
        elif put_zone_active and not call_zone_active:
            direction = 'PUT'
        elif abs(lower_ratio - upper_ratio) >= 1.0:
            direction = 'CALL' if lower_ratio > upper_ratio else 'PUT'
        else:
            return None
    elif call_zone_active:
        direction = 'CALL'
    elif put_zone_active:
        direction = 'PUT'
    else:
        return None

    wick = lower_wick if direction == 'CALL' else upper_wick
    wick_ratio = lower_ratio if direction == 'CALL' else upper_ratio
    zona_precio = current['low'] if direction == 'CALL' else current['high']

    # ── 5. Calcular score de confluencia ──────────────────────────────────────
    score: float = 0.0
    detalle: Dict[str, Any] = {
        'direction': direction,
        'wick_ratio': round(wick_ratio, 2),
        'wick_atr_ratio': round(wick_atr_ratio, 2),
        'atr': round(current_atr, 6),
        'dual_wick': dual_wick,
        'call_bias': round(call_bias, 2),
        'put_bias': round(put_bias, 2),
    }

    # Wick quality — combinación de wick/body Y wick/ATR (normalizado por volatilidad)
    # wick/body > 3.0: mecha muy prominente relativa al cuerpo
    # wick/ATR  > 0.8: la mecha es "grande" dentro de la volatilidad normal del activo
    strong_body_ratio = wick_ratio > 3.0
    strong_atr_ratio  = wick_atr_ratio > 0.8
    if strong_body_ratio and strong_atr_ratio:
        score += 2.0
        detalle['wick_quality'] = 'total'
    elif strong_body_ratio or strong_atr_ratio:
        score += 1.0
        detalle['wick_quality'] = 'parcial'
    else:
        score += 0.0
        detalle['wick_quality'] = 'debil'

    # Zona base (+2 mínimo — ya la verificamos antes)
    score += 2.0
    detalle['zona'] = round(zona_precio, 5)

    # Estocástico Lento (14,3) — confirmación de momentum (reemplaza RSI)
    detalle['stoch_slow_k'] = round(sk_val, 1) if stoch_slow_valid else None
    detalle['stoch_slow_d'] = round(sd_val, 1) if stoch_slow_valid else None
    if stoch_slow_valid:
        if direction == 'CALL':
            if sk_val < STOCH_SLOW_EXTREME_LOW and sd_val < STOCH_SLOW_EXTREME_LOW:
                score += 2.0
            elif sk_val < STOCH_SLOW_LOW:
                score += 1.0
        else:
            if sk_val > STOCH_SLOW_EXTREME_HIGH and sd_val > STOCH_SLOW_EXTREME_HIGH:
                score += 2.0
            elif sk_val > STOCH_SLOW_HIGH:
                score += 1.0

    # Bollinger Bands(20)
    detalle['bb_lower'] = round(bb_lower, 5) if bb_lower else None
    detalle['bb_upper'] = round(bb_upper, 5) if bb_upper else None
    if bb_lower is not None:
        if direction == 'CALL' and current['low'] <= bb_lower:
            score += 2.0
            detalle['bb_signal'] = 'en_banda_inferior'
        elif direction == 'PUT' and current['high'] >= bb_upper:
            score += 2.0
            detalle['bb_signal'] = 'en_banda_superior'

    # Stochastic(5, 3) — solo puntúa si el valor es válido
    detalle['stoch_k'] = round(k_val, 1) if stoch_valid else None
    detalle['stoch_d'] = round(d_val, 1) if stoch_valid else None
    if stoch_valid:
        if direction == 'CALL':
            if k_val < STOCH_EXTREME_LOW and d_val < STOCH_EXTREME_LOW:
                score += 2.0
            elif k_val < STOCH_LOW:
                score += 1.0
        else:
            if k_val > STOCH_EXTREME_HIGH and d_val > STOCH_EXTREME_HIGH:
                score += 2.0
            elif k_val > STOCH_HIGH:
                score += 1.0

    # EMA(8) vs EMA(21) — micro-tendencia
    detalle['ema8']  = round(ema8, 5)
    detalle['ema21'] = round(ema21, 5)
    if direction == 'CALL' and ema8 > ema21:
        score += 1.0
        detalle['ema_trend'] = 'alcista'
    elif direction == 'PUT' and ema8 < ema21:
        score += 1.0
        detalle['ema_trend'] = 'bajista'
    else:
        detalle['ema_trend'] = 'contra_tendencia'

    detalle['score'] = score

    if score < MIN_SCORE:
        return None

    return direction, score, detalle


def evaluar_asset(candles: List[dict]) -> Optional[SignalResult]:
    """
    Punto de entrada simplificado: calcula zonas internamente y evalúa.
    Equivalente a evaluar_vela(candles, zonas=None).
    """
    return evaluar_vela(candles, zonas=None)
