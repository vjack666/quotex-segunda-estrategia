# Implementación — Estrategia 30 Segundos

**Fase:** Laboratorio / Diseño  
**Objetivo:** Hoja de ruta para convertir las reglas de entrada en código Python ejecutable  

---

## Estado de implementación

| Componente | Estado | Notas |
|---|---|---|
| Definición de reglas | ✅ Completo | Ver `reglas_entrada.md` |
| Investigación de indicadores | ✅ Completo | Ver `indicadores.md` |
| Cálculo de indicadores (Python) | ⏳ Pendiente | Esqueleto abajo |
| Detector de señales | ⏳ Pendiente | |
| Backtesting manual (100 señales) | ⏳ Pendiente | Requiere datos históricos M1 |
| Backtesting automatizado | ⏳ Pendiente | Requiere detector funcional |
| Integración con bot principal | ⏳ Pendiente | Como STRAT-C |
| Pruebas en demo | ⏳ Pendiente | |
| Producción | ⏳ Pendiente | |

---

## Arquitectura de módulos

```
estrategia_30s/
├── detector.py          ← Motor principal: evalúa si hay señal en una vela
├── indicadores_calc.py  ← Funciones puras de cálculo (RSI, EMA, BB, etc.)
├── zonas.py             ← Identificador de zonas S/R horizontales
├── backtester.py        ← Corre la estrategia sobre datos históricos CSV
└── logs/                ← Resultados de backtest y sesiones demo
```

---

## Esqueleto de código: `indicadores_calc.py`

```python
"""
Cálculos de indicadores técnicos para la estrategia de 30 segundos.
Todas las funciones reciben listas de floats y retornan un float.
"""
from typing import List


def rsi(closes: List[float], period: int = 7) -> float:
    """RSI clásico con suavizado Wilder."""
    if len(closes) < period + 1:
        return 50.0
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [d for d in deltas[-period:] if d > 0]
    losses = [-d for d in deltas[-period:] if d < 0]
    avg_gain = sum(gains) / period if gains else 0.0
    avg_loss = sum(losses) / period if losses else 1e-10
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def ema(prices: List[float], period: int) -> float:
    """EMA del último valor. Retorna el EMA actual."""
    if len(prices) < period:
        return prices[-1] if prices else 0.0
    k = 2.0 / (period + 1)
    result = sum(prices[:period]) / period
    for price in prices[period:]:
        result = price * k + result * (1 - k)
    return result


def bollinger_bands(closes: List[float], period: int = 20, std_dev: float = 2.0):
    """Retorna (upper, middle, lower)."""
    if len(closes) < period:
        return None, None, None
    window = closes[-period:]
    middle = sum(window) / period
    variance = sum((p - middle) ** 2 for p in window) / period
    std = variance ** 0.5
    upper = middle + std_dev * std
    lower = middle - std_dev * std
    return upper, middle, lower


def stochastic_k(highs: List[float], lows: List[float],
                 closes: List[float], k_period: int = 5) -> float:
    """Calcula %K del oscilador estocástico."""
    if len(closes) < k_period:
        return 50.0
    highest_high = max(highs[-k_period:])
    lowest_low = min(lows[-k_period:])
    if highest_high == lowest_low:
        return 50.0
    return 100.0 * (closes[-1] - lowest_low) / (highest_high - lowest_low)


def atr(highs: List[float], lows: List[float],
        closes: List[float], period: int = 7) -> float:
    """Average True Range."""
    if len(closes) < 2:
        return 0.0
    true_ranges = []
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        true_ranges.append(tr)
    window = true_ranges[-period:]
    return sum(window) / len(window)
```

---

## Esqueleto de código: `detector.py`

```python
"""
Detector de señales para la estrategia de 30 segundos.
Evalúa si en el segundo 30-41 de una vela M1 hay condiciones para entrar.
"""
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple
from indicadores_calc import rsi, ema, bollinger_bands, stochastic_k, atr

BROKER_TZ = timezone(timedelta(hours=-3))

# Parámetros ajustables
ENTRY_WINDOW_START = 30
ENTRY_WINDOW_END = 41
MIN_WICK_TO_BODY_RATIO = 1.5
MIN_SCORE = 6
ATR_MIN = 0.00005
ATR_MAX = 0.00030


def evaluar_vela(candles: list, zonas: list) -> Optional[Tuple[str, float, dict]]:
    """
    Evalúa si la vela actual tiene señal de entrada.

    Args:
        candles: Lista de dicts con keys open, high, low, close (M1, ordenadas ascendente)
        zonas: Lista de floats — niveles S/R pre-identificados

    Returns:
        Tuple (direccion, score, detalle) o None si no hay señal
    """
    now = datetime.now(tz=BROKER_TZ)
    if not (ENTRY_WINDOW_START <= now.second <= ENTRY_WINDOW_END):
        return None

    current = candles[-1]
    closes = [c['close'] for c in candles]
    highs  = [c['high']  for c in candles]
    lows   = [c['low']   for c in candles]

    # ── Calcular wick
    body = abs(current['close'] - current['open'])
    upper_wick = current['high'] - max(current['open'], current['close'])
    lower_wick = min(current['open'], current['close']) - current['low']
    body = body if body > 1e-10 else 1e-10

    # Determinar dirección del rechazo
    if lower_wick > upper_wick and lower_wick / body >= MIN_WICK_TO_BODY_RATIO:
        direction = 'CALL'
        wick = lower_wick
    elif upper_wick > lower_wick and upper_wick / body >= MIN_WICK_TO_BODY_RATIO:
        direction = 'PUT'
        wick = upper_wick
    else:
        return None  # sin wick de rechazo

    wick_ratio = wick / body

    # ── Verificar zona cercana
    current_atr = atr(highs, lows, closes, period=7)
    zona_activa = any(abs(current['low'] - z) <= current_atr * 0.5 for z in zonas) \
               or any(abs(current['high'] - z) <= current_atr * 0.5 for z in zonas)
    if not zona_activa:
        return None

    # ── Filtro ATR
    if current_atr < ATR_MIN or current_atr > ATR_MAX:
        return None

    # ── Puntaje
    score = 0.0
    detalle = {}

    # Wick
    if wick_ratio > 3.0:
        score += 2; detalle['wick'] = 'total'
    else:
        score += 1; detalle['wick'] = 'parcial'

    # Zona (simplificado — se puede mejorar con conteo de toques)
    score += 2; detalle['zona'] = 'activa'

    # RSI
    rsi_val = rsi(closes, period=7)
    detalle['rsi'] = round(rsi_val, 1)
    if direction == 'CALL' and rsi_val < 25:
        score += 2
    elif direction == 'CALL' and rsi_val < 30:
        score += 1
    elif direction == 'PUT' and rsi_val > 75:
        score += 2
    elif direction == 'PUT' and rsi_val > 70:
        score += 1

    # Bollinger
    bb_upper, bb_mid, bb_lower = bollinger_bands(closes, period=20)
    if bb_lower is not None:
        if direction == 'CALL' and current['close'] <= bb_lower:
            score += 2; detalle['bollinger'] = 'en_banda'
        elif direction == 'PUT' and current['close'] >= bb_upper:
            score += 2; detalle['bollinger'] = 'en_banda'

    # Stochastic
    k_val = stochastic_k(highs, lows, closes, k_period=5)
    detalle['stoch_k'] = round(k_val, 1)
    if direction == 'CALL' and k_val < 20:
        score += 2
    elif direction == 'PUT' and k_val > 80:
        score += 2
    elif direction == 'CALL' and k_val < 30:
        score += 1
    elif direction == 'PUT' and k_val > 70:
        score += 1

    # EMA alineación
    ema8  = ema(closes, 8)
    ema21 = ema(closes, 21)
    detalle['ema8'] = round(ema8, 5)
    detalle['ema21'] = round(ema21, 5)
    if direction == 'CALL' and ema8 > ema21:
        score += 1
    elif direction == 'PUT' and ema8 < ema21:
        score += 1

    detalle['score'] = score

    if score < MIN_SCORE:
        return None

    return direction, score, detalle
```

---

## Esqueleto de código: `backtester.py`

```python
"""
Backtester simple para la estrategia 30s usando datos CSV históricos.
Simula que la entrada ocurre al segundo 30 de cada vela M1.
"""
import csv
from detector import evaluar_vela, MIN_SCORE
from zonas import detectar_zonas_sr


def cargar_candles_csv(filepath: str) -> list:
    candles = []
    with open(filepath, newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            candles.append({
                'time':  row['time'],
                'open':  float(row['open']),
                'high':  float(row['high']),
                'low':   float(row['low']),
                'close': float(row['close']),
            })
    return candles


def correr_backtest(candles: list, ventana_lookback: int = 50):
    """
    Simula entradas históricas.
    Para cada vela i, usa las velas anteriores como contexto.
    El resultado de la operación es el close de la vela i+1 vs open de la vela i+1.
    """
    resultados = []

    for i in range(ventana_lookback, len(candles) - 1):
        contexto = candles[max(0, i - ventana_lookback):i + 1]
        zonas = detectar_zonas_sr(contexto)

        # Simular segundo 30 — no hay timestamp real, asumimos entrada válida
        vela_actual = candles[i]
        vela_siguiente = candles[i + 1]

        # Re-usar detector sin el check de tiempo
        # (En backtest, asumimos que todas las velas son candidatas)
        resultado = evaluar_vela_sin_tiempo(contexto, zonas)
        if resultado is None:
            continue

        direction, score, detalle = resultado

        # Resultado de la operación
        if direction == 'CALL':
            ganó = vela_siguiente['close'] > vela_siguiente['open']
        else:
            ganó = vela_siguiente['close'] < vela_siguiente['open']

        resultados.append({
            'vela_i': i,
            'time': vela_actual['time'],
            'direction': direction,
            'score': score,
            'ganó': ganó,
            **detalle
        })

    wins = sum(1 for r in resultados if r['ganó'])
    total = len(resultados)
    winrate = wins / total * 100 if total > 0 else 0

    print(f"\n=== BACKTEST RESULTADO ===")
    print(f"Total señales: {total}")
    print(f"Wins: {wins} | Losses: {total - wins}")
    print(f"Win rate: {winrate:.1f}%")

    return resultados


def evaluar_vela_sin_tiempo(candles, zonas):
    """Versión del detector sin restricción de tiempo (para backtest)."""
    # Se copiaría el mismo código de evaluar_vela pero sin el check de segundos
    pass  # TODO: implementar
```

---

## Integración futura con el bot principal (STRAT-C)

Cuando la estrategia esté validada, se integrará como `STRAT-C` en `src/consolidation_bot.py`:

```python
# En consolidation_bot.py (futuro)

STRAT_C_ENABLED = False  # activar cuando esté validada
STRAT_C_EXPIRY = 60       # segundos
STRAT_C_MIN_SCORE = 6.0
STRAT_C_ENTRY_WINDOW_START = 30
STRAT_C_ENTRY_WINDOW_END = 41

async def _evaluate_strat_c(self, candles: list, asset: str):
    """Evalúa si hay condición de rechazo M1 en segundo 30."""
    from estrategia_30s.detector import evaluar_vela
    from estrategia_30s.zonas import detectar_zonas_sr
    
    zonas = detectar_zonas_sr(candles)
    resultado = evaluar_vela(candles, zonas)
    
    if resultado is None:
        return
    
    direction, score, detalle = resultado
    if score < STRAT_C_MIN_SCORE:
        return
    
    await self._place_trade(asset, direction, STRAT_C_EXPIRY, score, 'STRAT-C')
```

---

## Flujo de validación antes de producción

```
1. Backtesting manual
   └── Revisar 100 señales históricas en gráfico
   └── Anotar cada una en logs/backtest_manual.csv
   └── Win rate objetivo: > 60%

2. Backtesting automático
   └── Correr backtester.py sobre data/candles_EURUSD_otc_60.csv
   └── Segmentar por horario (sesión London, NY)
   └── Segmentar por volatilidad (ATR ranges)

3. Demo en vivo
   └── Mínimo 50 operaciones en demo
   └── Win rate mínimo para avanzar: 58%

4. Producción
   └── Capital máximo por operación: 2% del balance
   └── Stop de sesión: -5% del balance
   └── STRAT_C_ENABLED = True en bot principal
```

---

## Datos necesarios para backtesting

El archivo `data/candles_EURUSD_otc_60.csv` ya existe en el proyecto. Formato esperado:

```csv
time,open,high,low,close,volume
2026-04-01 00:00:00,1.08340,1.08370,1.08310,1.08355,1250
2026-04-01 00:01:00,1.08355,1.08390,1.08330,1.08380,980
...
```

Para obtener más datos históricos M1, usar el script existente o la API de pyquotex:
```python
# En bot: stable_api.get_candles(asset, 60, count=1000, endtime=time.time())
```
