# PLAN MASANIELLO
*Cómo proteger la progresión del ciclo con entradas de mayor calidad*

---

## El Masaniello No Es el Problema

Después de revisar `masaniello_engine.py` completo, la implementación es matemáticamente
correcta. Replica fielmente la fórmula del Excel original con la tabla de valores
(`_excel_value_table`) y el cálculo de inversión por columna (`_excel_investment_amount`).

El motor es sólido. El problema no está en el motor.

El problema está en lo que el motor recibe: entradas de calidad variable que
producen secuencias W/L impredecibles que deterioran el ciclo antes de que
pueda completarse positivamente.

---

## Matemática del Masaniello 5/2

Con configuración 5 operaciones, 2 wins objetivo, multiplicador 1.5:

**Secuencias que completan el ciclo positivamente:**
- WW (2 ops): ciclo completo en mínimas operaciones — ideal.
- WLW, LWW (3 ops): positivos.
- WLLW, LWLW, LLWW (4 ops): positivos (si el cuarto win llega).
- Cualquier secuencia con 2+ wins antes de acumular demasiadas pérdidas.

**Secuencias que destruyen el ciclo:**
- LLL (si max_losses_cycle_cutoff ≤ 3): ciclo terminado negativamente.
- Secuencias que llegan a 5 operaciones sin 2 wins.

Con `cycle_target_ops=5` y `cycle_target_wins=2`, el corte de pérdidas ocurre en
`max_losses_cycle_cutoff = 1 + 5 - 2 = 4 pérdidas`. El ciclo puede sobrevivir hasta
3 pérdidas si llega 2 wins antes de la 4ª pérdida.

**Conclusión matemática:** El Masaniello 5/2 necesita que por cada 5 operaciones
al menos 2 sean wins. Eso equivale a un winrate mínimo de 40%. Con winrate de 60%,
la probabilidad de completar el ciclo positivamente es muy alta.

El problema ocurre cuando el winrate real cae por debajo de 50%, que es lo que
sucede cuando el sistema opera setups mediocres.

---

## Qué Tipo de Entradas Ayudan al Masaniello

### Entradas que maximizan la probabilidad de ciclos positivos:

**1. Wins rápidos (primeras 2-3 ops del ciclo):**
Una secuencia WW o WLW completa el ciclo antes de llegar a la zona de riesgo.
Las entradas de Categoría A (edge máximo) tienen mayor probabilidad de producir
wins tempranos en el ciclo.

**Implicación práctica:** Ser más selectivo al inicio del ciclo, no al final.
Si el ciclo empieza con pérdida (L), el margen se reduce. Si empieza con win (W),
el ciclo tiene mayor tolerancia a errores posteriores.

**2. Alta probabilidad de win individual:**
Cada operación de Categoría A (estimado ≥ 62% de win individual) contribuye más
que una operación de Categoría B (estimado ≥ 55% de win individual).

La diferencia puede parecer pequeña, pero en la secuencia del ciclo se acumula.
Ciclo con 5 operaciones Categoría A: probabilidad de ciclo positivo alta.
Ciclo con 5 operaciones mixtas A/B/C: probabilidad de ciclo positivo moderada.

**3. Payout alto:**
Con payout 87% vs 80%, cada win produce más retorno, lo que beneficia el cálculo
de `bankroll` en el motor (`f_new = f_prev + d_profit` donde `d_profit = c_used × (L3-1) × b`).
Un payout más alto aumenta el ritmo de crecimiento de la banca en ciclos positivos.

---

## Qué Tipo de Entradas Destruyen el Masaniello

### Entradas que generan rachas malas y deterioran el ciclo:

**1. Entradas sin HTF alineado:**
Operar contra el flujo mayor aumenta la probabilidad de pérdida en cada operación
individual. Una racha de 3 pérdidas consecutivas (LLL) en un ciclo 5/2 con corte
en 4 pérdidas deja el ciclo muy comprometido.

**2. Entradas en zonas jóvenes o débiles:**
Zonas con menos de 20 minutos o `range_pct` > 0.20% tienen mayor probabilidad
de producir falsas señales. Una falsa señal al inicio del ciclo (primera operación
= pérdida) pone inmediatamente al sistema en modo recuperación.

**3. Múltiples entradas mediocres consecutivas:**
Si el sistema opera 3-4 candidatos de Categoría C/B en un mismo ciclo (porque
el umbral es bajo y hay muchas señales), la probabilidad de que todos sean wins
disminuye proporcionalmente. La concentración en pocos setups de alta calidad
es mejor que la dispersión en muchos setups mediocres.

**4. Entradas en horarios de baja liquidez:**
En horarios donde los activos OTC tienen spreads amplios o movimientos erráticos,
la probabilidad de win cae independientemente de la calidad del setup. El patrón
puede estar bien pero el mercado no tiene convicción en esa dirección.

**5. Gale sobre entradas mediocres:**
Si el gale se activa frecuentemente, significa que las entradas primarias son de
baja calidad. El gale tiene una probabilidad implícita de win que no es significativamente
mayor que la entrada primaria (la tendencia del mercado no cambia por el hecho de
haber perdido). Usar el gale como herramienta habitual deteriora la banca más rápido
de lo que puede recuperarse.

---

## Modo Conservador Post-Pérdida

### Propuesta de implementación:

**Estado normal (inicio de ciclo o después de win):**
- Score mínimo: 73
- Payout mínimo: 84%
- Patrón: strength ≥ 0.55 (Categorías A y B)
- HTF: obligatorio

**Estado conservador (después de pérdida en el ciclo):**
- Score mínimo: 78
- Payout mínimo: 87%
- Patrón: strength ≥ 0.75 (solo Categoría A)
- HTF: obligatorio
- Zone memory: sin ningún muro (incluso lejano)

**Estado de emergencia (2 pérdidas en el ciclo):**
- No buscar nuevas entradas por el resto del ciclo de escaneo actual.
- Esperar al ciclo siguiente con estado conservador.
- Solo operar si se encuentra un setup Categoría A perfecto (todos los filtros cumplidos).

**Lógica de implementación:**
```python
losses_in_cycle = masaniello_engine.state.losses_in_cycle

if losses_in_cycle == 0:
    min_score = 73
    min_payout = 84
    min_pattern_strength = 0.55

elif losses_in_cycle == 1:
    min_score = 78
    min_payout = 87
    min_pattern_strength = 0.75

elif losses_in_cycle >= 2:
    # Solo Categoría A perfecta
    min_score = 82
    min_payout = 87
    min_pattern_strength = 0.75
    # Adicionalmente: exigir H1 swing level alineado
```

---

## Pausa Entre Operaciones

### Propuesta:

Después de cada operación (win o pérdida), no buscar nuevas entradas durante
los siguientes 2 ciclos de escaneo. Esto evita:

- Operar en estado de mercado cambiante post-resultado.
- Entradas impulsivas motivadas por recuperar pérdidas.
- Sobreexposición en sesiones activas.

**Excepción:** Si la operación fue un win y el ciclo aún no está completo, mantener
vigilancia pero con estado conservador durante 1 ciclo.

---

## Señales de Alarma del Masaniello

Si se observan estas señales, revisar la calidad de las entradas inmediatamente:

| Señal | Umbral | Acción |
|---|---|---|
| Winrate < 50% en últimas 20 ops | < 50% | Revisar filtros. Detener operación. |
| Gale activado > 30% de operaciones | > 30% | Las primarias son malas. Endurecer. |
| Ciclos positivos < 50% en última semana | < 50% | Revisar matriz de calidad. |
| 3 ciclos negativos consecutivos | 3 seguidos | Pausa de 24h. Análisis de journal. |
| Pérdida diaria > 40% del límite | > 40% del límite | Detener sesión. Analizar. |

---

## Meta Realista del Masaniello

Con el sistema mejorado según este roadmap:

- Winrate objetivo: 60-65%
- Ciclos positivos esperados: 70-80%
- Frecuencia de gale: < 20% de operaciones
- Promedio de ops por ciclo para completarlo: 2.5-3.5

Esto no es garantía. Es la expectativa matemática con los filtros propuestos,
asumiendo que las condiciones de edge identificadas son reales.

La única forma de confirmar es operar 100+ operaciones con los filtros implementados
y medir los resultados reales contra estas proyecciones.
