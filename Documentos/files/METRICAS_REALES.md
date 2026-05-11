# MÉTRICAS REALES A MEDIR
*Qué registrar, cómo calcularlo y qué significa cada número*

---

## Por Qué Medir

Sin métricas reales, las decisiones de ajuste del sistema son opiniones.
Con métricas reales, las decisiones son datos.

El objetivo de este documento es definir exactamente qué medir desde el primer
día de operación, para que después de 100 operaciones haya suficiente información
para tomar decisiones informadas sobre qué funciona y qué no.

## Estado de Implementación (2026-05-11)

- Existe instrumentación shadow runtime en `consolidation_bot.py`.
- Existe paquete SQL de integridad y comparación en `src/lab/shadow_runtime_queries.sql`.
- Existen scripts operativos:
  - `src/lab/shadow_log_parser.py`
  - `src/lab/shadow_reconcile.py`
  - `src/lab/shadow_overhead_audit.py`
- La validación estadística formal NEW vs OLD sigue pendiente por cobertura insuficiente de `shadow_decision_audit`.

---

## Métricas Primarias (Obligatorias desde Día 1)

### M1 — Winrate Total
**Definición:** Porcentaje de operaciones que terminaron en WIN sobre el total ejecutado.
**Fórmula:** `(ops_win / ops_total) × 100`
**Objetivo:** ≥ 60%
**Umbral de alarma:** < 54%
**Dónde registrar:** `trade_journal.py` — columna `outcome`
**Mínimo de ops para significancia estadística:** 50 (margen ±14%), 100 (margen ±10%)

### M2 — Winrate sin Gale
**Definición:** Winrate solo de operaciones primarias, excluyendo gales.
**Por qué importa:** El gale enmascara la calidad de las entradas primarias.
Si el winrate total es 60% pero sin gale es 48%, el sistema depende del gale para sobrevivir.
**Objetivo:** ≥ 58%
**Umbral de alarma:** < 50%
**Dónde registrar:** Etiquetar operaciones como `is_gale: bool` en journal.

### M3 — Winrate con HTF Alineado
**Definición:** Winrate solo de operaciones donde la tendencia 15m estaba alineada.
**Por qué importa:** Confirma si el HTF realmente aporta edge o es ruido.
**Objetivo:** ≥ 63%
**Umbral de alarma:** < 55% (significa que HTF no aporta edge real)
**Dónde registrar:** `htf_aligned: bool` en registro de operación.

### M4 — Winrate por Categoría de Setup
**Definición:** Winrate separado por Categoría A vs Categoría B.
**Por qué importa:** Valida si la diferenciación de categorías refleja diferencias reales de calidad.
**Objetivos:**
- Categoría A: ≥ 62%
- Categoría B: ≥ 55%
**Umbral de alarma:**
- Categoría A < 56%: revisar criterios de Categoría A.
- Diferencia A-B < 5 puntos: la categorización no está discriminando correctamente.
**Dónde registrar:** `category: str` (A/B) en registro de operación.

### M5 — Ciclos Masaniello Completados Positivamente
**Definición:** Porcentaje de ciclos donde se alcanzaron los wins objetivo antes del corte.
**Fórmula:** `(ciclos_positivos / ciclos_totales) × 100`
**Objetivo:** ≥ 65%
**Umbral de alarma:** < 50%
**Dónde registrar:** `masaniello_engine.py` → en `_complete_cycle()`, registrar en journal.

---

## Métricas Secundarias (Implementar en Fase 4)

### M6 — Winrate por Tipo de Patrón 1m
**Categorías:**
- bearish_engulfing / bullish_engulfing (strength 0.85)
- shooting_star / hammer (strength 0.75)
- evening_star_simple / morning_star_simple (strength 0.65)
- bearish_inverted_hammer / bullish_hammer (strength 0.55)

**Por qué importa:** Puede revelar qué patrones tienen edge real vs cuáles son ruido.
Si hammer tiene winrate 65% y morning_star_simple tiene 48%, se justifica elevar el
mínimo de strength o excluir patterns específicos.

### M7 — Winrate por Rango de Score
**Categorías:**
- Score 65-72 (actual threshold mínimo)
- Score 73-77 (nuevo threshold B)
- Score 78-84 (threshold A)
- Score 85+ (setup excepcional)

**Por qué importa:** Confirma si el score tiene poder predictivo real.
Si todos los rangos tienen winrate similar, el score está mal calibrado.
Si el winrate sube progresivamente con el score, la calibración es correcta.

### M8 — Winrate por Horario (Hora del Día)
**Categorías:** Bloques de 1 hora (09:00-10:00, 10:00-11:00, etc.)
**Por qué importa:** Los mercados OTC tienen distintos niveles de liquidez y volatilidad
según el horario. Puede revelar ventanas óptimas y ventanas a evitar.
**Objetivo:** Identificar las 3-4 horas del día con mejor winrate.

### M9 — Winrate por Activo (Top y Bottom)
**Registrar:** Para cada activo, winrate individual en últimas 30 operaciones.
**Por qué importa:** Algunos activos OTC tienen comportamiento más predecible que otros.
Identificar los 5 mejores activos (mayor winrate) y reducir exposición a los peores.

### M10 — Frecuencia de Activación de Gale
**Fórmula:** `(ops_gale / ops_primarias) × 100`
**Objetivo:** < 25%
**Umbral de alarma:** > 35% (las entradas primarias son de baja calidad)

### M11 — Tiempo Promedio entre Operaciones
**Fórmula:** promedio de minutos entre el cierre de una op y la apertura de la siguiente.
**Objetivo:** > 15 minutos (no operar en modo reactivo inmediato)
**Umbral de alarma:** < 5 minutos (el sistema está sobreoperando)

### M12 — Porcentaje de Candidatos Rechazados por Filtro
**Registrar:** Para cada filtro crítico, cuántos candidatos bloquea por semana.
**Por qué importa:** Si un filtro rechaza < 5% de candidatos, es irrelevante.
Si rechaza > 50%, puede estar calibrado demasiado agresivo.

| Filtro | Rechazo esperado | Rechazo de alarma |
|---|---|---|
| HTF_ALIGNMENT_GATE | 20-40% | < 5% o > 60% |
| PATTERN_1M_GATE | 15-30% | < 5% o > 50% |
| ZONE_AGE_GATE | 10-25% | < 3% |
| PAYOUT_GATE | 10-20% | < 5% |
| SPIKE_GATE | 5-15% | < 1% |
| ZONE_MEMORY_WALL_GATE | 5-15% | < 2% |

---

## Dashboard de Métricas Semanal

Al final de cada semana de operación, generar reporte con:

```
=== REPORTE SEMANAL ===
Período: [fecha inicio] - [fecha fin]

OPERACIONES
  Total ejecutadas:        XX
  Por sesión promedio:     X.X
  Tiempo entre ops (avg):  XX min

WINRATE
  Total:                   XX%  [OBJETIVO: ≥60%]
  Sin gale:                XX%  [OBJETIVO: ≥58%]
  Con HTF alineado:        XX%  [OBJETIVO: ≥63%]
  Categoría A:             XX%  [OBJETIVO: ≥62%]
  Categoría B:             XX%  [OBJETIVO: ≥55%]

MASANIELLO
  Ciclos completados:      XX
  Ciclos positivos:        XX  (XX%)  [OBJETIVO: ≥65%]
  Gale activado:           XX%  [OBJETIVO: <25%]

FILTROS (candidatos rechazados)
  HTF_ALIGNMENT_GATE:      XX%
  PATTERN_1M_GATE:         XX%
  ZONE_AGE_GATE:           XX%
  PAYOUT_GATE:             XX%
  SPIKE_GATE:              XX%
  ZONE_MEMORY_WALL_GATE:   XX%

TOP 3 ACTIVOS (winrate):
  1. [activo]: XX%  (XX ops)
  2. [activo]: XX%  (XX ops)
  3. [activo]: XX%  (XX ops)

PEORES 3 ACTIVOS (winrate):
  1. [activo]: XX%  (XX ops)
  2. [activo]: XX%  (XX ops)
  3. [activo]: XX%  (XX ops)

MEJOR PATRÓN 1M:      [pattern] (XX% winrate)
PEOR PATRÓN 1M:       [pattern] (XX% winrate)

MEJOR HORARIO:        XX:00-XX:00 (XX% winrate)
PEOR HORARIO:         XX:00-XX:00 (XX% winrate)

ALERTAS:
  [lista de métricas que superaron umbral de alarma]
```

---

## Cómo Implementar el Registro

### En trade_journal.py — Campos a agregar por operación:

```python
# Campos nuevos a agregar al schema del journal
ALTER TABLE operations ADD COLUMN htf_aligned INTEGER DEFAULT 0;
ALTER TABLE operations ADD COLUMN pattern_name TEXT DEFAULT 'none';
ALTER TABLE operations ADD COLUMN pattern_strength REAL DEFAULT 0.0;
ALTER TABLE operations ADD COLUMN zone_age_min REAL DEFAULT 0.0;
ALTER TABLE operations ADD COLUMN zone_memory_adj REAL DEFAULT 0.0;
ALTER TABLE operations ADD COLUMN rejection_reason TEXT DEFAULT '';
ALTER TABLE operations ADD COLUMN session_op_number INTEGER DEFAULT 0;
ALTER TABLE operations ADD COLUMN category TEXT DEFAULT 'B';
ALTER TABLE operations ADD COLUMN is_gale INTEGER DEFAULT 0;
ALTER TABLE operations ADD COLUMN score_at_entry REAL DEFAULT 0.0;
ALTER TABLE operations ADD COLUMN payout_at_entry INTEGER DEFAULT 0;
```

### En consolidation_bot.py — Al momento de entry:

Pasar todos los campos anteriores al `log_candidate()` del journal cuando se
ejecuta una operación real.

### Script de análisis semanal (planificado):

El script `src/lab/weekly_report.py` está definido como objetivo documental.
Mientras no exista ese script, la medición operativa se realiza con:

- `src/lab/shadow_runtime_queries.sql` (SQL consolidado)
- `src/lab/shadow_log_parser.py` (runtime log metrics)
- `src/lab/shadow_reconcile.py` (integridad/linkage)
- `src/lab/shadow_overhead_audit.py` (sobrecarga runtime)
