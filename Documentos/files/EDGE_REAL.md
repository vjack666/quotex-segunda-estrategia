# EDGE REAL DEL SISTEMA
*Análisis de qué aporta precisión, qué agrega ruido y qué vale endurecer*

---

## Qué es Edge en Este Contexto

Edge es una ventaja estadística medible. Para opciones binarias de 5 minutos con
payout de 85%, el sistema necesita un winrate mínimo de 54.1% para ser rentable
(0.541 × 0.85 - 0.459 × 1.0 = 0.0). Con winrate de 60%, el EV es +0.11 por unidad,
que es un margen sólido para trabajo con Masaniello.

El edge no viene de un solo módulo. Viene de la confluencia de señales. Esta es la
razón por la que el sistema tiene potencial real: ya implementa múltiples capas de
filtrado que, si se endurecen y se hacen obligatorias, pueden elevar el winrate
desde el umbral de rentabilidad hacia la zona de consistencia.

---

## Componentes con Edge Real Estimado

### 1. Alineación HTF (15 minutos)
**Módulo:** `htf_scanner.py` + `_score_trend` en `entry_scorer.py`

**Por qué tiene edge:**
En mercados de opciones binarias de corto plazo, la estructura de tiempo mayor actúa
como "viento de cola" o "viento en contra". Operar un rebote alcista cuando el 15m
está en tendencia bajista es nadar contra la corriente. El precio puede rebotar, pero
la probabilidad de que ese rebote sea suficientemente fuerte para cerrar en verde en
5 minutos es significativamente menor.

**Estimación de impacto:**
La diferencia de winrate entre operaciones con HTF alineado vs sin alinear se estima
en 8-15 puntos porcentuales basándose en la lógica del scoring (`_score_trend` puede
aportar hasta 25 puntos en modo REBOUND). Este es el filtro más importante del sistema.

**Estado actual:** Implementado como penalización de score. No es un veto.
**Recomendación:** Convertir en veto binario. Sin HTF alineado = no operar.

---

### 2. Calidad de la Zona de Consolidación
**Módulo:** `consolidation_bot.py` + `_score_compression` en `entry_scorer.py`

**Por qué tiene edge:**
Una zona con `range_pct` bajo (< 0.10%) y muchas velas dentro (`bars_inside` > 20)
representa acumulación real de posiciones institucionales. El precio no está comprimido
por accidente. Cuando ese precio finalmente se mueve, la probabilidad de que lo haga
con convicción es mayor que en una zona de consolidación débil.

El sistema actual ya implementa una escala de calidad de zona con cuatro niveles
(EXCELLENT, GOOD, OK, MAX). El problema es que acepta zonas en nivel OK y MAX con
suficiente score compensatorio.

**Estimación de impacto:**
Zonas en nivel EXCELLENT (`range_pct` ≤ 0.10%) deberían tener 10-15 puntos más
de winrate que zonas en nivel OK (`range_pct` 0.15-0.20%).

**Estado actual:** Implementado con escala. Se permiten zonas mediocres.
**Recomendación:** Endurecer el mínimo aceptable a GOOD como límite máximo.

---

### 3. Confirmación de Vela 1 Minuto
**Módulo:** `candle_patterns.py`

**Por qué tiene edge:**
El patrón de vela 1m no predice el futuro. Lo que hace es confirmar que el precio
ya comenzó a reaccionar desde el extremo de la zona. Sin confirmación, el sistema
está anticipando una reacción que todavía no ocurrió.

Los patrones de mayor confianza (strength ≥ 0.75) como bearish_engulfing, bullish_engulfing,
shooting_star y hammer son los que tienen mejor edge porque requieren condiciones más
estrictas (engulfing requiere que la vela actual supere el rango de la anterior en
ambas direcciones, shooting star requiere mecha superior ≥ 2× cuerpo con mecha
inferior mínima).

**Estimación de impacto:**
Entradas con patrón strength ≥ 0.75 vs entradas sin patrón (none) pueden diferir
en 12-18 puntos de winrate. Entrar con `pattern = "none"` es esencialmente apostar
a que el precio reaccionará, no confirmar que ya está reaccionando.

**Estado actual:** El sistema puede entrar sin patrón si el score es suficientemente alto.
**Recomendación:** Patrón confirmado con `confirms_direction = True` debe ser obligatorio.

---

### 4. Filtro de Spikes
**Módulo:** `spike_filter.py`

**Por qué tiene edge:**
Los spikes en feeds OTC son glitches del broker o eventos de liquidez extrema. Una
vela con gap excesivo o cuerpo 6× el promedio contamina el análisis de zona, el
cálculo de EMA y la detección de patrón. El filtro ya está bien implementado con
dos reglas (gap rule y body+gap rule) y una ventana de lookback configurable.

**Estimación de impacto:**
Difícil de cuantificar directamente, pero una señal generada sobre datos contaminados
tiene probabilidad cercana al azar independientemente de la calidad del setup. Es un
filtro de higiene que protege todos los demás componentes.

**Estado actual:** Bien implementado y activo.
**Recomendación:** Mantener y asegurar que se aplica en todos los timeframes antes de scoring.

---

### 5. Memoria de Zonas Históricas
**Módulo:** `zone_memory.py`

**Por qué tiene edge:**
Una zona de resistencia histórica que el precio ha respetado en el pasado actúa como
muro real en la dirección de la operación. Operar hacia ese muro a menos de 0.15% de
distancia es exponerse a que el precio rebote antes de llegar al objetivo implícito.

El sistema ya implementa lógica de penalización (ZONE_MEMORY_PENALTY_WALL = -15 puntos)
y bonificación (ZONE_MEMORY_BONUS_CLEAR_PATH = +8 puntos) correctamente basada en el
rol de cada zona histórica (support, resistance, neutral) y su antigüedad.

**Estimación de impacto:**
La penalización de -15 puntos por muro bloqueante es significativa, pero no es un veto.
Un setup con score 80 que tiene un muro bloqueante baja a 65 y aún puede ejecutarse.

**Estado actual:** Implementado correctamente. No es un veto.
**Recomendación:** Añadir veto específico cuando hay muro dentro del umbral DANGER_PCT,
independientemente del score final.

---

### 6. Spring/Upthrust Wyckoff
**Módulo:** `strategy_spring_sweep.py`

**Por qué tiene edge potencial:**
El patrón Spring/Upthrust de Wyckoff es uno de los setups con mayor respaldo teórico
en análisis técnico. Identifica barridos de liquidez (el precio rompe un soporte/resistencia
para cazar stops y luego revierte agresivamente). En mercados OTC de corto plazo, estos
barridos son frecuentes y el rechazo posterior es a menudo rápido y limpio.

La implementación actual es sólida: verifica barrido, recuperación de soporte/resistencia
dentro de la misma vela, mecha proporcional y vela de confirmación posterior.

**Estado actual:** Forzado a OFF en main.py. El módulo funciona correctamente pero no se usa.
**Recomendación:** Evaluar activación en modo vigilancia (no ejecución automática) para
recolectar datos reales de precisión.

---

## Componentes que Probablemente Solo Agregan Ruido

### Score entre 65 y 72 como umbral de entrada
El threshold actual de 65 puntos fue diseñado para ser permisivo y no perder señales.
Pero operar todo lo que supere 65 incluye setups donde el contexto está bien pero el
timing es malo, o el timing está bien pero el contexto es débil.

La solución no es elevar el threshold a 80. Es exigir que todos los componentes
individuales sean aceptables, no solo la suma total.

### Gale como estrategia de recuperación por defecto
El gale (`mg_watcher.py`) tiene su lugar, pero cuando se usa frecuentemente indica
que las entradas primarias tienen calidad insuficiente. Un sistema con winrate real
de 62%+ no debería necesitar gale frecuente. Si el gale se activa en más del 30%
de las operaciones, el problema está en la selección de entradas, no en el gale.

### LEGACY-RJ
No aporta nada actualmente. Consume CPU y agrega complejidad de lectura al código.

---

## Qué Vale Endurecer

En orden de impacto esperado:

1. **HTF como filtro binario** — Mayor impacto. Implementación: 1-2 horas.
2. **Patrón 1m como requisito** — Alto impacto. Implementación: 30 minutos.
3. **Zona de antigüedad mínima 30 min** — Impacto medio-alto. Implementación: 20 minutos.
4. **Payout mínimo 87%** — Impacto directo en matemática de rentabilidad. Implementación: 5 minutos.
5. **Score mínimo 73 para B, 78 para A** — Impacto en calidad de selección. Implementación: 5 minutos.
6. **Zone memory muro como veto** — Impacto en evitar trampas. Implementación: 30 minutos.

---

## Qué Vale Eliminar

1. Entradas sin patrón 1m confirmado.
2. Entradas en zonas < 20 minutos de antigüedad.
3. Entradas cuando HTF no está disponible (cache vacío = no operar, no fallback).
4. Entradas con payout < 84%.
5. Más de 5 operaciones en una sesión de 2 horas.

---

## Síntesis del Edge

El sistema tiene edge real cuando opera en la intersección de:

**Flujo mayor a favor (HTF) × Zona fuerte probada × Rechazo confirmado en 1m**

Cualquier operación que no cumpla las tres condiciones simultáneamente está
operando con edge parcial, que en el largo plazo es equivalente a operar sin edge.
