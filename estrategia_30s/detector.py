"""
Detector de señales para la estrategia de 30 segundos.
Evalúa si en el segundo 30-41 de una vela M1 hay condiciones para entrar.

Uso standalone:
    from estrategia_30s.detector import evaluar_vela
    resultado = evaluar_vela(candles, zonas)
    if resultado:
        direction, score, detalle = resultado
"""
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Tuple, Dict, Any

from .indicadores_calc import rsi, ema, bollinger_bands, stochastic_d, atr
from .zonas import detectar_zonas_sr

# ── Parámetros por defecto (sobrescribibles desde main.py) ──────────────────
ENTRY_WINDOW_START_SEC: int   = 30
ENTRY_WINDOW_END_SEC: int     = 41
MIN_WICK_TO_BODY_RATIO: float = 1.5
MIN_SCORE: float              = 6.0
ATR_MIN: float                = 0.00004   # mercado muy plano → no entrar
ATR_MAX: float                = 0.00040   # spike/noticia → no entrar
BROKER_TZ                     = timezone(timedelta(hours=-3))  # UTC-3

# Parametros de indicadores (calibrables)
ATR_PERIOD: int = 7
RSI_PERIOD: int = 7
RSI_EXTREME_LOW: float = 25.0
RSI_LOW: float = 30.0
RSI_EXTREME_HIGH: float = 75.0
RSI_HIGH: float = 70.0

BB_PERIOD: int = 20
BB_STD_DEV: float = 2.0

STOCH_K_PERIOD: int = 5
STOCH_D_PERIOD: int = 3
STOCH_EXTREME_LOW: float = 20.0
STOCH_LOW: float = 30.0
STOCH_EXTREME_HIGH: float = 80.0
STOCH_HIGH: float = 70.0

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
) -> Optional[SignalResult]:
    """
    Evalúa si la vela actual genera señal de entrada.

    Args:
        candles:    Lista de dicts {open, high, low, close} ordenados ASC.
                    Mínimo recomendado: 25 velas para indicadores.
        zonas:      Niveles S/R pre-identificados. Si es None se calculan internamente.
        check_time: Si True verifica que el segundo actual esté en [30-41].
                    Pasar False en backtesting.

    Returns:
        (direccion, score, detalle) si hay señal, None si no.
        direccion: "CALL" | "PUT"
        score:     Puntuación de confluencia (0–17)
        detalle:   Dict con valores de cada indicador
    """
    if len(candles) < 10:
        return None

    # ── 1. Ventana de tiempo ──────────────────────────────────────────────────
    if check_time:
        second = datetime.now(tz=BROKER_TZ).second
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

    # Determinar dirección dominante del rechazo
    if lower_wick >= upper_wick and lower_wick / body >= MIN_WICK_TO_BODY_RATIO:
        direction = 'CALL'
        wick = lower_wick
    elif upper_wick > lower_wick and upper_wick / body >= MIN_WICK_TO_BODY_RATIO:
        direction = 'PUT'
        wick = upper_wick
    else:
        return None  # sin wick de rechazo significativo

    wick_ratio = wick / body

    # ── 3. Filtro ATR ─────────────────────────────────────────────────────────
    current_atr = atr(highs, lows, closes, period=ATR_PERIOD)
    if current_atr < ATR_MIN or current_atr > ATR_MAX:
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
    zona_precio = current['low'] if direction == 'CALL' else current['high']
    zona_activa = any(abs(zona_precio - z) <= tolerance for z in zonas)
    if not zona_activa:
        return None

    # ── 5. Calcular score de confluencia ──────────────────────────────────────
    score: float = 0.0
    detalle: Dict[str, Any] = {
        'direction': direction,
        'wick_ratio': round(wick_ratio, 2),
        'atr': round(current_atr, 6),
    }

    # Wick quality
    if wick_ratio > 3.0:
        score += 2.0
        detalle['wick_quality'] = 'total'
    else:
        score += 1.0
        detalle['wick_quality'] = 'parcial'

    # Zona base (+2 mínimo — ya la verificamos antes)
    score += 2.0
    detalle['zona'] = round(zona_precio, 5)

    # RSI(7)
    rsi_val = rsi(closes, period=RSI_PERIOD)
    detalle['rsi'] = round(rsi_val, 1)
    if direction == 'CALL':
        if rsi_val < RSI_EXTREME_LOW:
            score += 2.0
        elif rsi_val < RSI_LOW:
            score += 1.0
    else:
        if rsi_val > RSI_EXTREME_HIGH:
            score += 2.0
        elif rsi_val > RSI_HIGH:
            score += 1.0

    # Bollinger Bands(20)
    bb_upper, _bb_mid, bb_lower = bollinger_bands(closes, period=BB_PERIOD, std_dev=BB_STD_DEV)
    detalle['bb_lower'] = round(bb_lower, 5) if bb_lower else None
    detalle['bb_upper'] = round(bb_upper, 5) if bb_upper else None
    if bb_lower is not None:
        if direction == 'CALL' and current['close'] <= bb_lower:
            score += 2.0
            detalle['bb_signal'] = 'en_banda_inferior'
        elif direction == 'PUT' and current['close'] >= bb_upper:
            score += 2.0
            detalle['bb_signal'] = 'en_banda_superior'

    # Stochastic(5, 3)
    k_val, d_val = stochastic_d(highs, lows, closes, k_period=STOCH_K_PERIOD, d_period=STOCH_D_PERIOD)
    detalle['stoch_k'] = round(k_val, 1)
    detalle['stoch_d'] = round(d_val, 1)
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
    ema8  = ema(closes, EMA_FAST_PERIOD)
    ema21 = ema(closes, EMA_SLOW_PERIOD)
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
