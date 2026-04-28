# 04 — Estrategia B: Spring Sweep (Wyckoff)

## Concepto General

STRAT-B es una estrategia complementaria basada en el concepto de **Wyckoff Spring** y **Liquidity Sweep**. Opera sobre velas de **1 minuto** y corre en paralelo a STRAT-A durante cada ciclo de escaneo.

**Estado actual:** Por defecto opera en **modo espejo** (solo análisis y log). Para activar órdenes reales se requiere el flag `--strat-b-live`.

---

## Teoría del Spring Sweep

El patrón Wyckoff Spring describe un movimiento en el que el precio:

1. Establece un soporte claro (mínimos repetidos en zona de soporte)
2. **Penetra brevemente por debajo** del soporte (barre la liquidez de los stops)
3. **Recupera con rapidez** el nivel del soporte dentro de la misma vela o la siguiente
4. El cuerpo de la vela de recuperación debe ser fuerte (> 40% del rango total)

Esta "trampa bajista" normalmente precede un movimiento alcista significativo.

---

## Parámetros de Detección

Definidos en `SpringSweepConfig`:

| Parámetro | Valor | Descripción |
|---|---|---|
| `support_lookback` | 24 velas | Ventana para calcular el soporte de referencia |
| `min_rows` | 30 velas | Mínimo de datos de 1m necesarios |
| `break_buffer_pct` | 0.005% | Tolerancia para considerar que rompió el soporte |
| `reclaim_tolerance_pct` | 0.03% | Tolerancia para considerar que recuperó el soporte |
| `min_lower_wick_ratio` | 0.45 | Mecha inferior debe ser ≥ 45% del rango total |
| `confirm_break_buffer_pct` | 0.005% | Buffer para vela de confirmación |
| `min_confirm_body_ratio` | 0.40 | Cuerpo de vela confirmación ≥ 40% del rango |

---

## Algoritmo Paso a Paso

**Función:** `detect_spring_sweep(df)` → `(bool, dict)`

```
1. Normalizar DataFrame: aceptar alias open/high/low/close o o/h/l/c
2. Verificar mínimo de 30 filas
3. Calcular soporte_referencia = mínimo de low en las últimas 24 velas
4. Identificar "vela de barrido" (spring candle):
   - low < soporte_referencia - buffer (penetró el soporte)
   - close > soporte_referencia - tolerancia (recuperó el soporte)
   - lower_wick / rango_total ≥ 0.45 (mecha inferior prominente)
5. Si se encontró vela de barrido → buscar vela de confirmación:
   - close > spring_close + buffer_confirmacion
   - body / rango ≥ 0.40 (cuerpo fuerte)
6. Calcular confianza:
   - Base: 0.60 si spring detectado, +0.25 si hay confirmación
   - Ajuste por wick_ratio y body_ratio de confirmación
7. Retornar (True, {confidence, reason, ...}) si umbral superado
```

---

## Integración en el Loop Principal

Durante `scan_all()`, por cada activo:

```python
# Se obtienen velas 1m en paralelo con las 5m
candles_1m = await _fetch_1m_limited(sym)  # últimas 36 velas de 1m

if len(candles_1m) >= 30:
    spring_df = pd.DataFrame({open, high, low, close})
    strat_b_signal, strat_b_info = detect_spring_sweep(spring_df)
```

### Resultado por caso:

| Caso | Acción |
|---|---|
| `strat_b_signal = True` + `STRAT_B_CAN_TRADE = False` | Solo log: `[STRAT-B] ✅ ASSET CALL conf=XX%` |
| `strat_b_signal = True` + `STRAT_B_CAN_TRADE = True` + conf ≥ 0.70 | Abre entrada CALL real |
| `strat_b_signal = False` + conf ≥ 0.45 (near-miss) | Log: `[STRAT-B] ~ ASSET conf=XX%` |
| `strat_b_signal = False` + conf < 0.45 | Silencio |

### Parámetros de Umbral

| Parámetro | Valor | Descripción |
|---|---|---|
| `STRAT_B_MIN_CONFIDENCE` | 0.70 | Confianza mínima para entrar (cuando live) |
| `STRAT_B_PREVIEW_MIN_CONF` | 0.45 | Umbral para mostrar "near-miss" en log |
| `STRAT_B_LOG_TOP_N` | 3 | Máximo de señales B a mostrar en resumen |

---

## Entrada STRAT-B (cuando `--strat-b-live`)

Cuando STRAT-B abre una operación, crea una zona ficticia como contexto:

```python
pseudo_zone = ConsolidationZone(
    asset=sym,
    ceiling=candles_1m[-1].high,
    floor=candles_1m[-1].low,
    bars_inside=0,
    ...
)
```

Y llama a `_enter()` con:
- `direction = "call"` (siempre CALL — el spring es señal alcista)
- `duration_sec = STRAT_B_DURATION_SEC = 120`
- `strategy_origin = "STRAT-B"`

**Nota:** STRAT-B no usa martingala de consolidación. Si hay un trade STRAT-B activo y transcurre `duration_sec + 90s`, simplemente se cierra y registra el resultado.

---

## Estadísticas Independientes

El sistema trackea wins y losses de cada estrategia por separado:

```python
stats["strat_a_wins"] / stats["strat_a_losses"]  # STRAT-A
stats["strat_b_wins"] / stats["strat_b_losses"]  # STRAT-B
```

Esto permite evaluar la performance de cada estrategia de forma independiente en el log de sesión.

---

## Resumen en Log de Ciclo

Al final de cada ciclo de escaneo se imprime:

```
[STRAT-B] Resumen ciclo: 18 evaluados | señales=2 | datos_1m_insuficientes=1
[STRAT-B] ✅ EURUSD_otc [87%] CALL | conf=73.5 | Spring Sweep ✓
[STRAT-B] ✅ GBPUSD_otc [82%] CALL | conf=68.2 | Spring Sweep ✓
```

---

## Diferencias Clave vs STRAT-A

| Aspecto | STRAT-A | STRAT-B |
|---|---|---|
| Marco temporal de análisis | 5 minutos | 1 minuto |
| Tipo de señal | Rebote o ruptura de zona | Spring / Liquidity Sweep |
| Dirección de entrada | CALL o PUT | Siempre CALL |
| Confirmación adicional | Patrón 1m + score | Vela de confirmación interna |
| Scoring externo | Sí (entry_scorer.py) | No — confianza propia |
| Live por defecto | Sí | No (requiere --strat-b-live) |
| Martingala de 2do min | Sí | No |
