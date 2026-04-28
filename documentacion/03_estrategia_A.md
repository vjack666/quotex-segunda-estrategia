# 03 — Estrategia A: Consolidación con Reversión / Ruptura

## Concepto General

STRAT-A es la estrategia principal del sistema. Se basa en la teoría de que el precio tiende a:

1. **Rebotar** en los extremos de una zona de rango estrecho (soporte/resistencia horizontal)
2. **Continuar en dirección de la ruptura** cuando rompe esa zona con velas de cuerpo fuerte

Toda la detección usa velas de **5 minutos**. La entrada se realiza en el momento de la detección y la opción expira en **120 segundos (2 minutos)**.

---

## Fase 1: Detección de Zona de Consolidación

**Función:** `detect_consolidation(candles, max_range_pct)`

El algoritmo desliza una ventana de `MIN_CONSOLIDATION_BARS = 12` velas sobre las últimas 55 velas obtenidas del broker, buscando la ventana más reciente que cumpla:

### Criterios de Validez de la Zona

| Criterio | Valor | Descripción |
|---|---|---|
| Barras mínimas dentro del rango | 12 velas | Mínimo de velas con cierre dentro del rango |
| Rango máximo del precio | 0.3% base / dinámico ATR | `(ceiling - floor) / midpoint ≤ MAX_RANGE_PCT` |
| Sin límite de tiempo | ∞ | `MAX_CONSOLIDATION_MIN = 0` (deshabilitado) |

### Rango Dinámico con ATR (cuando `USE_DYNAMIC_ATR_RANGE = True`)

El rango máximo permitido se ajusta según la volatilidad actual del activo:

```
atr_pct = ATR(14 velas) / precio_actual
dynamic_max_range = clamp(atr_pct × 1.35, 0.0015, 0.0150)
```

Esto evita que activos muy volátiles generen falsas zonas con 0.3% de rango.

### Estructura de la Zona

```python
ConsolidationZone:
  ceiling    # máximo del rango (resistencia / techo)
  floor      # mínimo del rango (soporte / piso)
  bars_inside  # cantidad de velas dentro
  range_pct    # amplitud normalizada
  detected_at  # timestamp de detección
  age_minutes  # tiempo transcurrido desde detección
```

---

## Fase 2: Clasificación del Precio Actual

Con la zona detectada, se analiza la última vela de 5 minutos (la más reciente):

### 2a. Precio tocando TECHO — modo REBOTE

```python
def price_at_ceiling(price, ceiling):
    return abs(price - ceiling) / ceiling <= 0.00035  # tolerancia 0.035%
```

→ **Señal propuesta:** PUT (espera caída desde resistencia)

**Requiere confirmación en velas 1m:** patrón bajista con fuerza ≥ 0.50

### 2b. Precio tocando PISO — modo REBOTE

```python
def price_at_floor(price, floor):
    return abs(price - floor) / floor <= 0.00035
```

→ **Señal propuesta:** CALL (espera subida desde soporte)

**Requiere confirmación en velas 1m:** patrón alcista con fuerza ≥ 0.50

### 2c. Ruptura del TECHO con fuerza — modo BREAKOUT

```python
def broke_above(candle, ceiling):
    return candle.close > ceiling * (1 + 0.00035)

def is_high_volume_break(candle, candles_history):
    avg = avg_body(últimas 10 velas)
    return candle.body >= avg * 1.2  # cuerpo ≥ 1.2× el promedio
```

→ **Señal: CALL inmediato** (momentum alcista, no requiere confirmación de patrón)

### 2d. Ruptura del PISO con fuerza — modo BREAKOUT

→ **Señal: PUT inmediato** (momentum bajista, no requiere confirmación de patrón)

---

## Fase 3: Confirmación con Patrones de Velas 1m

Solo aplica a entradas por **REBOTE** (no a breakouts).

Se toman las últimas velas de 1 minuto del activo y se busca el patrón más reciente:

### Patrones Bajistas (para entrada PUT en techo)

| Patrón | Fuerza |
|---|---|
| `bearish_engulfing` | 0.85 |
| `shooting_star` | 0.75 |
| `evening_star_simple` | 0.65 |
| `bearish_inverted_hammer` | 0.55 |

### Patrones Alcistas (para entrada CALL en piso)

| Patrón | Fuerza |
|---|---|
| `bullish_engulfing` | 0.85 |
| `hammer` | 0.75 |
| `morning_star_simple` | 0.65 |
| `bullish_hammer` | 0.55 |

### Umbral de Aprobación

```python
REBOUND_MIN_STRENGTH = 0.50
```

Si el patrón encontrado no confirma la dirección OR su fuerza es < 0.50 → señal descartada con log `"esperando confirmación"`.

---

## Fase 4: Confirmación de Tendencia Macro H1

Cuando `H1_CONFIRM_ENABLED = True`, el bot fetcha las últimas 80 velas de 1 hora y calcula:

```
EMA20 vs EMA50:
  EMA20 > EMA50 Y precio ≥ EMA20  →  tendencia "bullish"
  EMA20 < EMA50 Y precio ≤ EMA20  →  tendencia "bearish"
  resto                            →  "neutral"
```

**Filtros:**
- No permite entrada PUT si tendencia H1 es `bullish`
- No permite entrada CALL si tendencia H1 es `bearish`
- Tendencia neutral: permite ambas direcciones

---

## Fase 5: Scoring Matemático

Cada señal candidata se convierte en `CandidateEntry` y pasa por `score_candidate()` que evalúa 4 dimensiones en escala 0-100:

### Dimensiones del Score

| Dimensión | Peso | Qué mide |
|---|---|---|
| **Compresión** (`W_COMPRESSION = 25`) | 25 pts | Calidad del rango — menor rango y más barras = mejor |
| **Rebote** (`W_BOUNCE = 30`) | 30 pts | Mechas en las últimas 3 velas hacia el extremo |
| **Tendencia** (`W_TREND = 25`) | 25 pts | Alineación del precio con EMA10/EMA20 en 5m |
| **Payout** (`W_PAYOUT = 20`) | 20 pts | Payout del activo interpolado entre 80% y 95% |

### Bonificaciones y Penalizaciones Post-Score

Aplicadas sobre el score base **después** de las 4 dimensiones:

| Condición | Ajuste |
|---|---|
| Patrón 1m confirma + fuerza ≥ 0.60 | +8 pts |
| Patrón 1m confirma + fuerza ≥ 0.50 | +5 pts |
| Patrón 1m NO confirma | -6 pts |
| Ruptura con fuerza (`breakout_strength_ok`) | +6 pts |

### Umbral de Aprobación

```python
SCORE_THRESHOLD = 62
```

Solo señales con score ≥ 62 pasan a ejecución. Si ninguna candidata lo supera, el ciclo no opera.

---

## Fase 6: Guardia contra Datos Contaminados

Antes de procesar la señal, se verifica que el precio actual sea coherente con la zona:

```python
if not (zone.floor * 0.75 <= price <= zone.ceiling * 1.25):
    # dato contaminado — descartar
```

Pyquotex usa estado global para candles y en fetches concurrentes el precio de un activo puede mezclarse con otro. Esta guardia rechaza precios que se desvíen más del 25% del rango de la zona.

---

## Fase 7: Timing de Entrada

**Función:** `_sync_to_next_candle_open()`

Valida si el momento es apropiado para enviar la orden:

- Calcula cuántos segundos han transcurrido desde el inicio de la vela de 5 minutos actual
- **Rechaza** si quedan ≤ 60 segundos para cerrar la vela (`ENTRY_REJECT_LAST_SEC = 60`)
- **Acepta** en cualquier otro momento de la vela
- Duración de la orden: **siempre 120 segundos fijos**

```
Vela de 5m = 300 segundos
├── 0s ─────────────────── 240s → ACEPTA (240s disponibles)
└── 240s ─────────────────── 300s → RECHAZA (últimos 60s)
```

---

## Fase 8: Ejecución de la Orden

Una vez aprobada, se llama a `place_order()` que:

1. Verifica conexión WebSocket con `check_connect()` — reconecta si es necesario
2. Cambia la cuenta al tipo correcto (PRACTICE / REAL)
3. Llama a `client.buy(amount, asset, direction, duration=120)`
4. Si el broker responde `status=True` + dict con `id`: orden aceptada
5. Si el broker responde `status=False, info=None` y tardó ≥ 20s: reintenta (1 reintento)
6. Si el broker responde con error duro (expiration, asset cerrado): no reintenta

---

## Fase 9: Seguimiento y Resultado

El trade queda en `self.trades[asset]` como `TradeState`:

```python
TradeState:
  asset, direction, amount, entry_price
  ceiling, floor          # límites de la zona original
  order_id, order_ref     # identificadores del broker
  opened_at               # timestamp de entrada
  martin_fired            # si ya se activó la martingala
  stage                   # "initial" | "breakout" | "martin"
  journal_id              # ID en la BD SQLite
  strategy_origin         # "STRAT-A" | "STRAT-B"
  duration_sec            # 120
```

Transcurridos `duration_sec + 90s`, `_check_martin()` detecta el cierre, llama a `_resolve_trade()` para obtener WIN/LOSS del broker y actualiza el journal.

---

## Lógica de Martingala (2do Minuto)

Si durante el 2do minuto de una operación activa el precio rompe la zona **en contra** con fuerza:

- Trade PUT activo + precio rompió techo con fuerza → nueva entrada PUT (monto compensación)
- Trade CALL activo + precio rompió piso con fuerza → nueva entrada CALL (monto compensación)

El monto de compensación se calcula para:
1. Recuperar la pérdida probable del trade inicial
2. Generar $2 netos adicionales
3. Dejar el balance en un número entero (sin centavos residuales)

---

## Diagrama Simplificado del Flujo STRAT-A

```
Velas 5m del activo
        ↓
detect_consolidation()
  ├── Sin zona → skip
  └── Zona detectada
          ↓
    ¿Precio contaminado? → skip
          ↓
    Clasificar precio:
    ├── En TECHO → propone PUT → detect_reversal_pattern() → ¿fuerza ≥ 0.50? → candidato
    ├── En PISO  → propone CALL → detect_reversal_pattern() → ¿fuerza ≥ 0.50? → candidato
    ├── BROKEN_ABOVE + fuerza → CALL inmediato → candidato (+ captura forense)
    └── BROKEN_BELOW + fuerza → PUT inmediato → candidato (+ captura forense)
          ↓
    infer_h1_trend() → ¿contradice? → filtered_sensor
          ↓
    score_candidate() → aplicar bonus/penalizaciones
          ↓
    ¿score ≥ 62? 
    ├── No → REJECTED_SCORE (journal)
    └── Sí → _sync_to_next_candle_open()
              ├── ¿últimos 60s? → REJECTED_TIMING
              └── Ok → place_order() → TradeState → journal PENDING
```
