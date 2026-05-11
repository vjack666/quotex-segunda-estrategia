# FILTROS CRÍTICOS
*Qué debe convertirse en veto binario y cómo implementarlo*

---

## Diferencia entre Penalización y Veto

El sistema actual usa el score como único mecanismo de control. Cualquier condición
negativa reduce puntos, pero no impide la entrada si el score total sigue siendo ≥ 65.

El problema es que un setup puede tener un contexto muy bueno (zona excelente, payout
alto, zona histórica alineada) y obtener score 75 aunque el HTF esté completamente
en contra y no haya confirmación de vela. Ese setup parece bueno en el score pero
es malo en la práctica.

Los filtros críticos son condiciones que deben implementarse como **vetos binarios**
que detienen la ejecución antes de que el score sea relevante.

---

## FILTRO 1 — Alineación HTF Obligatoria

**Nombre:** HTF_ALIGNMENT_GATE
**Módulo fuente:** `htf_scanner.py` + `entry_scorer._score_trend()`
**Clasificación:** VETO — bloquea ejecución

**Condición de veto:**
La tendencia en 15m NO está alineada con la dirección de entrada.
- Para CALL: EMA rápida 15m debe ser > EMA lenta 15m
- Para PUT: EMA rápida 15m debe ser < EMA lenta 15m

**Condición adicional de veto:**
El cache HTF está vacío o tiene más de 870 segundos de antigüedad.
Si no hay datos HTF recientes, no hay información suficiente para operar.

**Cómo verificar en código:**
```python
# Pseudocódigo — implementar en bloque de pre-validación en consolidation_bot.py
candles_15m = htf.get_candles_15m(asset)
if not candles_15m or len(candles_15m) < 20:
    reject("HTF_EMPTY")
    
ema_fast = ema(closes_15m, period=10)[-1]
ema_slow = ema(closes_15m, period=20)[-1]

if direction == "call" and ema_fast <= ema_slow:
    reject("HTF_BEARISH_CONTRA_CALL")
if direction == "put" and ema_fast >= ema_slow:
    reject("HTF_BULLISH_CONTRA_PUT")
```

**Impacto esperado:** Reducción del 20-35% de operaciones. Mejora estimada de winrate: +8-15 puntos.

---

## FILTRO 2 — Patrón de Vela 1m Obligatorio

**Nombre:** PATTERN_1M_GATE
**Módulo fuente:** `candle_patterns.detect_reversal_pattern()`
**Clasificación:** VETO — bloquea ejecución

**Condición de veto:**
El patrón de vela 1m retorna `pattern = "none"` O `confirms_direction = False`.

No basta con que haya un patrón. El patrón debe confirmar la dirección de entrada.
Un bearish_engulfing cuando se intenta entrar en CALL no confirma: lo contradice.

**Strength mínima aceptable:**
- Categoría A: strength ≥ 0.75
- Categoría B: strength ≥ 0.55

Si strength < 0.55, veto independientemente de la categoría.

**Cómo verificar en código:**
```python
# Ya existe la función. Solo agregar como condición hard antes de _enter()
signal = detect_reversal_pattern(candles_1m, direction)
if not signal.confirms_direction or signal.pattern_name == "none":
    reject("NO_PATTERN_1M")
if signal.strength < 0.55:
    reject("PATTERN_STRENGTH_TOO_LOW")
```

**Impacto esperado:** Reducción del 15-25% de operaciones. Mejora estimada de winrate: +10-18 puntos.

---

## FILTRO 3 — Antigüedad Mínima de Zona

**Nombre:** ZONE_AGE_GATE
**Módulo fuente:** `ConsolidationZone.age_minutes` en `models.py`
**Clasificación:** VETO — bloquea ejecución

**Condición de veto:**
`zone.age_minutes < 20`

Una zona con menos de 20 minutos de vida no ha sido probada suficientemente por el
mercado. El precio podría estar en medio de la formación de la zona, no en un extremo
válido para rebote.

**Penalización adicional (no veto):**
Zonas entre 20 y 30 minutos: reducir score en -8 puntos adicionales sobre el ajuste
existente de -5 puntos que ya aplica `_age_adjustment()`.

**Cómo verificar en código:**
```python
if zone.age_minutes < 20:
    reject("ZONE_TOO_YOUNG")
```

**Impacto esperado:** Reducción del 10-20% de operaciones. Mejora estimada de winrate: +5-10 puntos.

---

## FILTRO 4 — Payout Mínimo

**Nombre:** PAYOUT_GATE
**Módulo fuente:** Configuración del bot en `consolidation_bot.py`
**Clasificación:** VETO — bloquea ejecución

**Condición de veto:**
`payout < 84%`

La matemática es clara. Con 60% de winrate:
- Payout 80%: EV = +0.08 por unidad. Margen muy ajustado.
- Payout 84%: EV = +0.104 por unidad. Aceptable.
- Payout 87%: EV = +0.122 por unidad. Bueno.
- Payout 90%: EV = +0.14 por unidad. Excelente.

Con winrate real de 55% (realista en inicio), payout 80% produce EV negativo.
El payout mínimo de 84% garantiza que incluso con winrate bajo de 54% el sistema
es matemáticamente neutro, no negativo.

**Umbrales operativos:**
- Payout ≥ 87%: Categoría A y B permitidas.
- Payout 84-86%: Solo Categoría A permitida.
- Payout < 84%: VETO.

**Cómo verificar en código:**
```python
if payout < 84:
    reject("PAYOUT_TOO_LOW")
```

**Impacto esperado:** Mejora directa en matemática de rentabilidad. Sin reducción significativa de oportunidades si se opera en horarios de alta liquidez.

---

## FILTRO 5 — Spike en Feed

**Nombre:** SPIKE_GATE
**Módulo fuente:** `spike_filter.detect_spike_anomaly()`
**Clasificación:** VETO — bloquea ejecución

**Condición de veto:**
Anomalía detectada en ventana de lookback de velas 1m o 5m.

El filtro ya existe y está bien implementado. El problema es la integración:
debe aplicarse antes del scoring, no después. Un spike contamina el cálculo de
EMA, el análisis de zona y el patrón de vela. Si el spike ya ocurrió, todo el
análisis posterior es potencialmente inválido.

**Ventana de aplicación:**
- Velas 1m: lookback de 20 velas (últimos 20 minutos)
- Velas 5m: lookback de 12 velas (última hora)

**Cómo verificar en código:**
```python
# Ya existe. Asegurar que se llama antes del scoring
result_1m = detect_spike_anomaly(candles_1m, lookback=20)
result_5m = detect_spike_anomaly(candles_5m, lookback=12)
if result_1m.is_anomalous or result_5m.is_anomalous:
    reject("SPIKE_DETECTED")
```

**Impacto esperado:** Protección de datos. Mejora indirecta en todos los componentes de scoring.

---

## FILTRO 6 — Muro de Zone Memory

**Nombre:** ZONE_MEMORY_WALL_GATE
**Módulo fuente:** `zone_memory.score_zone_memory()`
**Clasificación:** VETO — bloquea ejecución

**Condición de veto:**
Existe una zona histórica con `role = "resistance"` (para CALL) o `role = "support"` (para PUT)
a menos de `ZONE_MEMORY_DANGER_PCT` (0.15%) en la dirección de la operación.

Esta condición ya genera -15 puntos en el score actual, pero no es un veto.
Con score 82 y muro a 0.1%, el candidato pasa con score 67 y se ejecuta.
Un muro a 0.15% en la dirección significa que el precio tiene que atravesar ese nivel
antes de que la operación sea rentable. Eso es un obstáculo real, no una penalización.

**Cómo verificar en código:**
```python
for zone in nearby_zones:
    if direction == "call":
        above = zone.dist_pct > 0
        if above and zone.role == "resistance" and abs(zone.dist_pct) < ZONE_MEMORY_DANGER_PCT:
            reject("RESISTANCE_WALL_BLOCKING_CALL")
    if direction == "put":
        below = zone.dist_pct < 0
        if below and zone.role == "support" and abs(zone.dist_pct) < ZONE_MEMORY_DANGER_PCT:
            reject("SUPPORT_WALL_BLOCKING_PUT")
```

**Impacto esperado:** Reducción del 5-10% de operaciones. Mejora estimada de winrate: +3-7 puntos.

---

## FILTRO 7 — Límite de Operaciones por Sesión

**Nombre:** SESSION_LIMIT_GATE
**Módulo fuente:** Contador de sesión en `consolidation_bot.py`
**Clasificación:** VETO — bloquea ejecución

**Condición de veto:**
Se han ejecutado 5 o más operaciones en la sesión actual (ventana de 2 horas).

El objetivo no es operar mucho. Es operar los mejores setups del día. Si en
2 horas ya se ejecutaron 5 operaciones, el sistema ya cumplió su misión.
Operaciones adicionales tienen mayor probabilidad de ser setups mediocres tomados
por disponibilidad, no por calidad.

**Excepción:** Si las primeras 3 operaciones fueron todas wins, el límite puede
extenderse a 6, pero no más.

**Cómo verificar en código:**
```python
if session_ops_count >= 5:
    reject("SESSION_LIMIT_REACHED")
```

**Impacto esperado:** Reducción de sobreoperación en sesiones activas. Protección del Masaniello.

---

## Tabla de Filtros por Prioridad de Implementación

| Filtro | Impacto Winrate | Dificultad | Prioridad | Tiempo estimado |
|---|---|---|---|---|
| HTF_ALIGNMENT_GATE | +8-15 pts | Baja | P0 | 2 horas |
| PATTERN_1M_GATE | +10-18 pts | Baja | P0 | 30 min |
| ZONE_AGE_GATE | +5-10 pts | Baja | P1 | 20 min |
| PAYOUT_GATE | Matemático directo | Mínima | P0 | 5 min |
| SPIKE_GATE | Protección base | Baja | P0 | 30 min |
| ZONE_MEMORY_WALL_GATE | +3-7 pts | Media | P1 | 1 hora |
| SESSION_LIMIT_GATE | Protección Masaniello | Baja | P1 | 30 min |

---

## Nota de Implementación

Todos estos filtros deben implementarse en un bloque de pre-validación centralizado
en `consolidation_bot.py`, antes de que se llame a `_enter()`. El bloque debe:

1. Evaluar cada filtro en orden (más baratos computacionalmente primero).
2. Al fallar cualquier filtro, registrar el rechazo en el journal con etiqueta del filtro.
3. No continuar evaluando filtros una vez que uno falla (fail-fast).
4. Publicar el rechazo en el HUB para visibilidad operativa.

Este bloque no debe modificar los módulos de scoring existentes. Se inserta como
capa de decisión entre el scoring y la ejecución.
