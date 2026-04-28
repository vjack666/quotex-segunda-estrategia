# 06 — Parámetros de Configuración

Todos los parámetros están definidos como constantes en `src/consolidation_bot.py` (salvo los de scoring que están en `src/entry_scorer.py`). Algunos pueden sobreescribirse en tiempo de ejecución desde `main.py` vía argumentos CLI.

---

## Detección de Zona de Consolidación

| Constante | Valor actual | CLI override | Descripción |
|---|---|---|---|
| `TF_5M` | `300` | — | Período de vela principal (5 minutos en segundos) |
| `CANDLES_LOOKBACK` | `55` | — | Velas a pedir al broker por activo |
| `MIN_CONSOLIDATION_BARS` | `12` | — | Mínimo de velas con cierre dentro del rango |
| `MAX_RANGE_PCT` | `0.003` | — | Amplitud máxima del rango: 0.3% del precio |
| `TOUCH_TOLERANCE_PCT` | `0.00035` | — | Tolerancia para "tocar" techo/piso: 0.035% |
| `MAX_CONSOLIDATION_MIN` | `0` | — | Minutos máximos que una zona es válida (0 = sin límite) |

---

## ATR Dinámico

| Constante | Valor actual | Descripción |
|---|---|---|
| `USE_DYNAMIC_ATR_RANGE` | `True` | Activa ajuste de MAX_RANGE_PCT según volatilidad |
| `ATR_PERIOD` | `14` | Velas para calcular el ATR |
| `ATR_RANGE_FACTOR` | `1.35` | Multiplicador sobre ATR para obtener el rango |
| `MIN_DYNAMIC_RANGE_PCT` | `0.0015` | Rango mínimo dinámico permitido (0.15%) |
| `MAX_DYNAMIC_RANGE_PCT` | `0.0150` | Rango máximo dinámico permitido (1.5%) |

**Fórmula:**
```
atr_pct = ATR(14) / close_actual
dynamic_range = clamp(atr_pct × 1.35, 0.0015, 0.0150)
```

---

## Filtros de Calidad

| Constante | Valor actual | CLI override | Descripción |
|---|---|---|---|
| `MIN_PAYOUT` | `80` | `--min-payout` | Payout mínimo en % para operar un activo |
| `VOLUME_MULTIPLIER` | `1.2` | — | Cuerpo de ruptura debe ser ≥ 1.2× el cuerpo promedio |
| `VOLUME_LOOKBACK` | `10` | — | Velas para calcular cuerpo promedio (proxy de volumen) |
| `REBOUND_MIN_STRENGTH` | `0.50` | — | Fuerza mínima del patrón de reversión para rebote |
| `H1_CONFIRM_ENABLED` | `True` | — | Activa filtro de tendencia macro H1 |
| `H1_EMA_FAST` | `20` | — | EMA rápida para tendencia H1 |
| `H1_EMA_SLOW` | `50` | — | EMA lenta para tendencia H1 |

---

## Scoring (en `entry_scorer.py`)

| Constante | Valor actual | Descripción |
|---|---|---|
| `SCORE_THRESHOLD` | `62` | Puntuación mínima para operar (0-100) |
| `MAX_ENTRIES_CYCLE` | `1` | Máximo de entradas por ciclo de escaneo |
| `W_COMPRESSION` | `25` | Peso de la dimensión "compresión" del rango |
| `W_BOUNCE` | `30` | Peso de la dimensión "rebote" en extremos |
| `W_TREND` | `25` | Peso de la dimensión "tendencia" EMA 5m |
| `W_PAYOUT` | `20` | Peso de la dimensión "payout" del activo |

---

## Gestión de Capital

| Constante | Valor actual | CLI override | Descripción |
|---|---|---|---|
| `AMOUNT_INITIAL` | `1.00` | `--amount-initial` | Monto base por entrada inicial (USD) |
| `AMOUNT_MARTIN` | `3.00` | `--amount-martin` | Monto de martingala fijo |
| `MIN_ORDER_AMOUNT` | `1.00` | — | Monto mínimo absoluto |
| `TARGET_MIN_PROFIT` | `1.00` | — | Ganancia mínima objetivo en entrada inicial (USD neto) |
| `MARTIN_TARGET_PROFIT` | `2.00` | — | Ganancia objetivo adicional en compensación (USD neto) |
| `MAX_LOSS_SESSION` | `0.20` | `--max-loss-session` | Drawdown máximo de sesión (fracción) → detiene el bot |

**Nota sobre monto dinámico:** el monto real que se envía se calcula para que la ganancia neta resulte en un balance entero. Por ejemplo, con balance $67.99 y payout 85%, se calcula el monto exacto para terminar en $69.00 exacto.

---

## Gestión de Ciclo (Masaniello Simplificado)

| Constante | Valor actual | CLI override | Descripción |
|---|---|---|---|
| `CYCLE_MAX_OPERATIONS` | `6` | `--cycle-ops` | Máximo de operaciones antes de reiniciar ciclo |
| `CYCLE_TARGET_WINS` | `2` | `--cycle-wins` | Wins mínimos objetivo por ciclo |
| `CYCLE_TARGET_PROFIT_PCT` | `0.10` | `--cycle-profit-pct` | Reiniciar ciclo al lograr +10% sobre balance base |

**Reglas de reinicio de ciclo** (primera que se cumple):
1. Balance actual ≥ balance_inicio_ciclo × 1.10 (take-profit +10%)
2. Wins acumulados ≥ 2
3. Operaciones completadas ≥ 6
4. Imposible alcanzar 2 wins en las operaciones restantes → reinicio anticipado

---

## Timing de Entrada

| Constante | Valor actual | Descripción |
|---|---|---|
| `DURATION_SEC` | `120` | Duración fija de cada opción binaria (2 minutos = 120s) |
| `VALID_DURATIONS_SEC` | `[120]` | Única duración aceptada por el broker |
| `ENTRY_SYNC_TO_CANDLE` | `True` | Activa validación de timing respecto a vela |
| `ENTRY_REJECT_LAST_SEC` | `60.0` | Rechaza entrada si quedan ≤ 60s para cierre de vela |
| `ENTRY_MAX_LAG_SEC` | `1.5` | No usado activamente (legado) |
| `ENTRY_CANDLE_BUFFER_SEC` | `0.0` | No usado en modo duración fija |
| `ALIGN_SCAN_TO_CANDLE` | `False` | Activa sincronización del scan al reloj de vela 5m |
| `SCAN_LEAD_SEC` | `35.0` | `--scan-lead-sec` | Anticipación del scan al open de vela (solo si ALIGN=True) |

---

## Red y Concurrencia

| Constante | Valor actual | Descripción |
|---|---|---|
| `CANDLE_FETCH_CONCURRENCY` | `8` | Máximo de fetches simultáneos al broker |
| `CANDLE_FETCH_TIMEOUT_SEC` | `10.0` | Timeout por request de velas 5m |
| `CANDLE_FETCH_1M_TIMEOUT_SEC` | `8.0` | Timeout por request de velas 1m |
| `H1_FETCH_TIMEOUT_SEC` | `12.0` | Timeout por request de velas H1 |
| `FETCH_RETRIES` | `2` | Reintentos por fetch fallido |
| `FETCH_RETRY_BACKOFF_SEC` | `0.35` | Espera entre reintentos (se multiplica por intento) |
| `ORDER_SEND_RETRIES` | `1` | Reintentos de orden (solo en timeout confirmación) |
| `CONNECT_RETRIES` | `3` | Intentos de conexión inicial |
| `CF_403_BACKOFF_SEC` | `8.0` | Espera adicional ante bloqueo Cloudflare 403 |
| `HEALTHCHECK_RECONNECT_RETRIES` | `2` | Intentos de reconexión en loop 24/7 |

---

## Operación del Loop

| Constante | Valor actual | Descripción |
|---|---|---|
| `SCAN_INTERVAL_SEC` | `60` | Segundos entre ciclos de escaneo |
| `MAX_CONCURRENT_TRADES` | `1` | Máximo de operaciones abiertas simultáneas |
| `COOLDOWN_BETWEEN_ENTRIES` | `30` | Segundos de espera entre órdenes exitosas |

---

## STRAT-B

| Constante | Valor actual | CLI override | Descripción |
|---|---|---|---|
| `STRAT_B_CAN_TRADE` | `False` | `--strat-b-live` | Permite que STRAT-B abra operaciones reales |
| `STRAT_B_DURATION_SEC` | `120` | `--strat-b-duration` | Duración de opciones STRAT-B |
| `STRAT_B_MIN_CONFIDENCE` | `0.70` | `--strat-b-min-confidence` | Confianza mínima para entrar en STRAT-B |
| `STRAT_B_LOG_TOP_N` | `3` | — | Máximo de señales B a mostrar en log |
| `STRAT_B_PREVIEW_MIN_CONF` | `0.45` | — | Umbral para mostrar "near-miss" en log |

---

## Captura Forense

| Constante | Valor actual | Descripción |
|---|---|---|
| `BROKEN_CAPTURE_DIR` | `data/vela_ops/` | Carpeta donde se guardan los JSON de capturas |
| `BROKEN_FOLLOWUP_DELAY_SEC` | `900` (15 min) | Espera antes de capturar velas post-evento |
| `BROKEN_FOLLOWUP_1M_COUNT` | `40` | Cantidad de velas 1m del follow-up |

---

## Zona Horaria

| Constante | Valor | Descripción |
|---|---|---|
| `BROKER_TZ` | `UTC-3` | Zona horaria del broker/gráficas |
| `BROKER_TZ_LABEL` | `"UTC-3"` | Etiqueta en logs |
