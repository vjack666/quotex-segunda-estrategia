# ROADMAP TÉCNICO
*Plan de trabajo dividido en fases con objetivos, módulos y métricas de validación*

---

## Principio de Este Roadmap

Las fases están ordenadas por impacto inmediato y riesgo. Las primeras fases
producen mejoras sin tocar la lógica de trading. Las fases posteriores mejoran
la calidad de señal. Las últimas fases optimizan la gestión de riesgo y validan
resultados reales.

No saltarse fases. Cada fase crea la base de la siguiente.

## Estado Operativo Consolidado (2026-05-11)

- Fase 1: completada.
- Fase 2: completada y en operación.
- Fase 2.5: implementada de forma parcial.
    - Existe `entry_decision_engine.py`.
    - NEW funciona como observador shadow, no como autoridad live.
    - Persistencia shadow existe, pero la validación estadística sigue no concluyente.
- Prioridad actual: validación estadística formal e integridad de dataset.
- Restricción vigente: no tocar lógica live, broker, timing ni arquitectura de ejecución.

---

## FASE 1 — Eliminar Ruido Técnico
**Objetivo:** Dejar el sistema limpio, seguro y observable antes de tocar cualquier lógica de trading.
**Estado:** Completada.

- [x] 1.1 Seguridad de Credenciales
- [x] 1.2 Corregir Black Box Recorder
- [x] 1.3 Eliminar Debug Prints del Loop Crítico
- [x] 1.4 Desactivar LEGACY Ticker Condicionalmente
- [x] Validación: `py_compile`
- [x] Validación: `main.py --hub-readonly --once`

### 1.1 Seguridad de Credenciales
**Tarea:** Mover email, password, token y cookies fuera de archivos JSON en disco.
**Implementación:**
- Cargar desde variables de entorno: `os.environ.get("QUOTEX_EMAIL")`, etc.
- Crear archivo `.env` en directorio raíz (ya está en `.gitignore`).
- Eliminar valores reales de `config.json` y `session.json`.
- Invalidar sesiones activas y generar nuevas.

**Módulos:** `consolidation_bot.py` (carga de config), `config.json`, `session.json`
**Riesgo:** Bajo. No toca lógica de trading.
**Tiempo estimado:** 1-2 horas.
**Validación:** El bot arranca correctamente usando solo variables de entorno.

### 1.2 Corregir Black Box Recorder
**Tarea:** Reparar implementación inconsistente de `record_phase` y `record_maintenance_event`.
**Implementación:**
- Separar correctamente los dos métodos (hoy hay código de uno en el otro).
- Asegurar que variables como `strategy`, `phase`, `message` están definidas localmente.
- Verificar que HTFScanner y VipLibraryManager pueden llamar a `record_maintenance_event` sin excepción.

**Módulos:** `black_box_recorder.py`, `htf_scanner.py`, `vip_library.py`
**Riesgo:** Bajo-Medio. Solo afecta observabilidad.
**Tiempo estimado:** 2-4 horas.
**Validación:** Ningún módulo atrapa excepción silenciosa al llamar a black box.

### 1.3 Eliminar Debug Prints del Loop Crítico
**Tarea:** Reemplazar prints de debug síncronos por logging con gate de nivel.
**Implementación:**
- Crear flag de entorno `DEBUG_SCAN=false` en producción.
- Reemplazar `print("[DEBUG-SCAN]...")` por `log.debug(...)`.
- Configurar nivel de logging a INFO en producción, DEBUG solo en desarrollo.

**Módulos:** `consolidation_bot.py` (decenas de prints en scan_all y loop principal)
**Riesgo:** Bajo. No toca lógica.
**Tiempo estimado:** 1-2 horas.
**Validación:** Loop principal corre sin I/O de consola en producción.

### 1.4 Desactivar LEGACY Ticker Condicionalmente
**Tarea:** No crear la task del ticker LEGACY cuando la estrategia está archivada.
**Implementación:**
- Leer flag de configuración antes de crear la task.
- Si `LEGACY_RJ_ENABLED = False`, no llamar a `create_task(_LEGACY_RJ_window_ticker)`.

**Módulos:** `consolidation_bot.py`
**Riesgo:** Bajo. La task ya no hace nada útil.
**Tiempo estimado:** 30 minutos.
**Validación:** Proceso arranca con una task menos en el loop.

**Métricas de validación de Fase 1:**
- Zero excepciones silenciosas en black box durante 1 hora mínima de operación continua.
- Zero prints de debug en stdout durante sesión de producción.
- Zero credenciales en archivos de texto plano.

**Nota operativa:**
- La validación mínima bloqueante para abrir Fase 2 se reduce a 1 hora continua.
- Una ventana más larga (por ejemplo 24h) sigue siendo recomendable como validación prolongada no bloqueante.

---

## FASE 2 — Endurecer Filtros de Entrada
**Objetivo:** Convertir las condiciones más importantes en vetos binarios.
Reducir el número de operaciones y mejorar su calidad promedio.
**Estado:** ✅ Completada (2026-05-11)

### 2.1 Implementar Bloque de Pre-validación
**Tarea:** Crear función `_pre_validate_entry(candidate, context)` en `consolidation_bot.py`
que evalúa todos los filtros críticos antes de llamar a `_enter()`.
**Estado:** ✅ Completado (2026-05-11) — 11 vetos implementados

**Implementación del bloque (en orden):**
```
1. ✅ Verificar que no hay operación activa (línea 6630)
2. ✅ Verificar límite de operaciones en sesión (línea 6636)
3. ✅ Verificar payout ≥ 84% (línea 6645)
4. ✅ Verificar score ≥ 73 (línea 6656)
5. ✅ Verificar spike en 1m (línea 6669)
6. ✅ Verificar spike en 5m (línea 6681)
7. ✅ Verificar HTF disponible y alineado (línea 6692)
8. ✅ Verificar patrón 1m con confirms_direction = True (línea 6724)
9. ✅ Verificar patrón strength ≥ 0.55 (línea 6731 — IMPLEMENTADO HOY)
10. ✅ Verificar antigüedad de zona ≥ 20 minutos (línea 6741)
11. ✅ Verificar zone memory sin muro bloqueante (línea 6750)
```

Cada paso que falla registra el rechazo en journal con etiqueta del filtro y retorna.

**Módulos:** `consolidation_bot.py`, `spike_filter.py`, `candle_patterns.py`, `zone_memory.py`, `htf_scanner.py`
**Estado:** ✅ Completado
**Validación:** ✅ `py_compile` exitoso en todos los archivos críticos

### 2.2 Subir Payout Mínimo
**Tarea:** Cambiar payout mínimo de 80% a 84% globalmente.
**Módulos:** `consolidation_bot.py` (configuración de filtro de activos), `entry_scorer.py` (PAYOUT_MIN)
**Riesgo:** Bajo. Reduce universo de activos elegibles.
**Tiempo estimado:** 5 minutos.

### 2.3 Subir Score Mínimo
**Tarea:** Cambiar threshold de `SCORE_THRESHOLD = 65` a `SCORE_THRESHOLD = 73`.
**Módulos:** `entry_scorer.py`
**Riesgo:** Bajo. Reduce operaciones.
**Tiempo estimado:** 5 minutos.

**Métricas de validación de Fase 2:**
- Número de operaciones por sesión de 2h: entre 1 y 5 (objetivo: 3-4).
- Score promedio de operaciones ejecutadas: ≥ 75.
- Porcentaje de candidatos rechazados por HTF: registrado en journal.
- Porcentaje de candidatos rechazados por falta de patrón: registrado en journal.

---

## FASE 2.5 — Aislamiento Quirúrgico + Matriz A/B/C/D
**Objetivo:** Extraer lógica de decisión SIN romper pipeline vivo. Implementar clasificación probabilística.
**Estado:** Parcial / Experimental (2026-05-11)
**Duración estimada:** 2 semanas

**PRINCIPIO CRÍTICO:** En trading live, pipeline estable > arquitectura bonita. NO tocar websocket, async loops, ejecución real. Solo aislar decisión.

### 2.5.1 Crear entry_decision_engine.py

**Responsabilidad:**
- Motor independiente de decisión (9 vetos + clasificación)
- Entrada: CandidateEntry + contexto
- Salida: EntryDecision (aprobado/rechazado + categoría A/B/C + trazabilidad)

**Módulos afectados:** Nuevo módulo `src/entry_decision_engine.py`
**Riesgo:** Bajo. Módulo nuevo, sin dependencias de runtime async.
**Tiempo estimado:** 8-10 horas (diseño + implementación + validación local)
**Estado real:** ✅ Implementado en código, usado por shadow observation.

**Validación:**
- Compilar sin errores
- Comparar decisiones OLD vs NEW en 100 candidatos (deben ser idénticas)
- Test: todas las funciones de veto funcionan aisladas
- Log: explain_decision() genera trazabilidad legible

### 2.5.2 Implementar Matriz A/B/C/D

**Criterios de Clasificación:**

| Categoría | Score | Pattern Strength | Payout | Zone Age | HTF | Lógica Ejecución |
|-----------|-------|------------------|--------|----------|-----|------------------|
| **A** (Premium) | ≥80 | ≥0.75 | ≥87% | ≥45min | Req | Ejecutar siempre |
| **B** (Solid) | ≥73 | ≥0.60 | ≥84% | ≥20min | Req | Ejecutar si ciclo ≤1 loss |
| **C** (Acceptable) | ≥70 | ≥0.55 | ≥82% | ≥15min | Opt | Ejecutar si ciclo 0 loss |
| **REJECT** | <70 | <0.55 | <82% | <15min | - | No ejecutar |

**Integración en consolidation_bot.py:**
- Reemplazar `_pre_validate_entry()` con llamada a `evaluate_entry()`
- Agregar método `_journal_entry_approved()` para registrar categoría
- Sin cambios en `_enter()`, `_monitor_trade_live()`, `_resolve_trade()`

**Módulos afectados:** `consolidation_bot.py` (~50 líneas de cambios), `trade_journal.py` (~20 líneas nuevas)
**Riesgo:** Bajo. Cambios quirúrgicos, sin tocar ejecución.
**Tiempo estimado:** 6-8 horas (integración + validación + rollback plan)

**Validación:**
- Test live 30min: Cambiar entre OLD y NEW, comparar decisiones
- Test live 2h: Operar con NEW, validar no hay regresión
- Rollback plan: Si falla, revertir a OLD en <5 minutos
**Estado real:** 🟡 Parcial. La clasificación existe en NEW, pero OLD sigue autoridad única.

### 2.5.3 Shadow Mode para STRAT-B

**Objetivo:** Recolectar datos de STRAT-B sin riesgo financiero.

**Implementación:**
- `strategy_spring_sweep.py`: Agregar `SHADOW_MODE=True`
- Detectar patterns, clasificar con `entry_decision_engine`
- Registrar "habrían sido ejecutados" pero NO ejecutar
- Journal: Registrar como tipo 'SHADOW'

**Análisis post-1 semana:**
- ¿Cuántas detecciones totales?
- ¿Cuántas habrían sido aprobadas?
- ¿Distribución de categorías (A/B/C)?
- ¿Winrate simulado si hubiéramos ejecutado?

**Decisión gate:**
- Si winrate simulado ≥58%: Activar en live
- Si <55%: Mantener shadow o investigar
- Si 55-58%: Recolectar datos 2 semanas más

**Módulos afectados:** `strategy_spring_sweep.py` (~30 líneas), `trade_journal.py` (+tabla shadow_signals)
**Riesgo:** Ninguno. No ejecuta trades.
**Tiempo estimado:** 4-6 horas

**Validación:**
- Shadow mode detecta patterns correctamente
- Journal registra todas las detecciones
- Queries muestran datos consistentes
**Estado real:** 🟡 Parcial. Path de STRAT-B existe pero `main.py` mantiene `STRAT_B_CAN_TRADE=False` por configuración operativa.

### 2.5.4 Extender trade_journal.py

**Nuevos campos en tabla trades:**
```
category (A/B/C/REJECT)
htf_aligned (bool)
pattern_name (str)
pattern_strength (float)
zone_age_min (float)
zone_memory_adj (float)
veto_count (int)
```

**Nueva tabla shadow_signals:**
```
timestamp, strategy, pattern, decision, would_execute,
category, asset, pattern_strength, score, payout, mode
```

**Módulos afectados:** `trade_journal.py` (~40 líneas)
**Riesgo:** Bajo. Agrega columnas, no remueve.
**Tiempo estimado:** 3-4 horas

**Validación:**
- Tablas creadas correctamente
- Datos se registran sin errores
- Queries retornan resultados esperados
**Estado real:** 🟡 Parcial. Existe `shadow_decision_audit`, pero la cobertura de filas todavía es insuficiente para validación formal.

**Métricas de validación de Fase 2.5:**
- Decisiones OLD vs NEW: 100% idénticas en 100 candidatos
- Cero regresiones en órdenes ejecutadas (100+ trades)
- STRAT-B shadow: 50-100 detecciones en 1 semana
- STRAT-B winrate simulado: Calculable y consistente
- Rollback: <5 minutos si es necesario

**Nota de control de fase:**
- Mientras no exista evidencia estadística suficiente de divergencia/WR/PF/expectancy,
  Fase 2.5 se mantiene en estado experimental y NO habilita promoción de autoridad NEW.

---

## FASE 3 — Mejorar Timing de Entrada
**Objetivo:** Usar la VIP Library como capa de maduración antes de ejecutar.

### 3.1 Activar VIP Library como Gate Formal
**Tarea:** En lugar de ejecutar cuando un candidato pasa el score, moverlo a la VIP
Library y ejecutar cuando lleva al menos 1-2 ciclos de escaneo cumpliendo condiciones.

**Lógica:**
- Candidato pasa pre-validación → entra a VIP Library con `missing_conditions`.
- Si `missing_conditions ≤ 1` y el candidato estuvo en VIP Library por al menos
  el ciclo anterior → autorizar ejecución.
- Candidatos que solo duran un ciclo en VIP Library son más riesgosos.

**Módulos:** `vip_library.py`, `consolidation_bot.py`
**Riesgo:** Medio. Puede hacer perder algunas entradas tempranas.
**Tiempo estimado:** 4-6 horas.
**Validación:** VIP Library muestra candidatos "maduros" vs candidatos "nuevos".

### 3.2 Ventana de Entrada Estricta
**Tarea:** Definir ventana de tiempo válida para entrada relativa al cierre de vela 5m.

No entrar en los primeros 30 segundos ni en los últimos 45 segundos de una vela de 5 minutos.
Los primeros 30s son ruido post-cierre. Los últimos 45s son timing de riesgo.

**Módulos:** `consolidation_bot.py` (lógica de timing de entrada)
**Riesgo:** Bajo. Solo afecta timing.
**Tiempo estimado:** 1-2 horas.

**Métricas de validación de Fase 3:**
- Porcentaje de operaciones ejecutadas desde VIP Library vs entrada directa.
- Comparar winrate de entradas directas vs entradas maduras en VIP Library.

---

## FASE 4 — Mejorar Calidad Estadística
**Objetivo:** Construir base de datos de decisiones para medir winrate real por condición.

### 4.1 Extender Journal con Etiquetas de Filtros
**Tarea:** Registrar en el journal no solo el resultado, sino qué filtros pasó y cuáles
rechazaron a otros candidatos en el mismo ciclo de escaneo.

**Datos adicionales a registrar:**
- `htf_aligned: bool`
- `pattern_name: str`
- `pattern_strength: float`
- `zone_age_min: float`
- `zone_memory_adj: float`
- `rejection_reason: str` (para candidatos rechazados)
- `session_op_number: int`
- `category: str` (A/B/C/D)

**Módulos:** `trade_journal.py`, `consolidation_bot.py`
**Riesgo:** Bajo. Solo agrega datos.
**Tiempo estimado:** 3-5 horas.

### 4.2 Script de Análisis de Journal
**Tarea:** Crear script de análisis que lea el journal SQLite y reporte:
- Winrate total
- Winrate por categoría (A/B)
- Winrate con HTF alineado vs sin alinear
- Winrate por tipo de patrón 1m
- Winrate por rango de score (65-72 vs 73-80 vs 80+)
- Winrate por horario (hora del día)
- Winrate por activo (top 5 mejores y peores)

**Módulos:** Script nuevo en `src/lab/`
**Riesgo:** Ninguno. Solo lectura.
**Tiempo estimado:** 4-6 horas.

**Métricas de validación de Fase 4:**
- Reporte semanal automático con los datos anteriores.
- Identificar condición única que más diferencia ganadores de perdedores.

---

## FASE 5 — Optimizar Masaniello
**Objetivo:** Proteger los ciclos Masaniello con entradas de mayor calidad.
Ver PLAN_MASANIELLO.md para análisis detallado.

### 5.1 Modo Conservador Post-Pérdida
**Tarea:** Después de una pérdida en el ciclo, elevar temporalmente los umbrales:
- Score mínimo: de 73 a 78
- Payout mínimo: de 84% a 87%
- HTF: mantener como requisito
- Patrón: exigir strength ≥ 0.75 (solo Categoría A)

Este modo conservador protege el ciclo cuando ya hay una pérdida acumulada.

**Módulos:** `consolidation_bot.py`, `masaniello_engine.py`
**Riesgo:** Medio. Puede reducir oportunidades en momentos clave.
**Tiempo estimado:** 2-4 horas.

### 5.2 Pausa Post-Gale
**Tarea:** Después de activar un gale, no buscar nuevas entradas durante el resto
del ciclo de escaneo actual. El gale ya es una segunda oportunidad; buscar una
tercera en el mismo ciclo aumenta el riesgo exponencialmente.

**Módulos:** `consolidation_bot.py`, `mg_watcher.py`
**Riesgo:** Medio. Reduce sobreexposición.
**Tiempo estimado:** 1-2 horas.

**Métricas de validación de Fase 5:**
- Porcentaje de ciclos Masaniello completados positivamente (wins ≥ 2).
- Distribución de secuencias W/L dentro de ciclos.
- Frecuencia de activación de gale.

---

## FASE 6 — Validar Rentabilidad Real
**Objetivo:** Confirmar con datos reales que las mejoras producen rentabilidad sostenible.

### 6.1 Período de Validación
Operar mínimo 100 operaciones con el sistema mejorado antes de ajustar parámetros.
100 operaciones es el mínimo estadístico para que el winrate sea significativo
(margen de error ~±10 puntos porcentuales con 95% de confianza).

### 6.2 Criterios de Éxito
El sistema se considera validado si después de 100 operaciones:
- Winrate real ≥ 58%
- Winrate en Categoría A ≥ 62%
- Winrate en Categoría B ≥ 55%
- Porcentaje de ciclos Masaniello positivos ≥ 65%
- Promedio de operaciones por sesión de 2h: entre 2 y 5

### 6.3 Criterios de Revisión
Si después de 100 operaciones:
- Winrate total < 54%: revisar filtros. El edge puede estar mal identificado.
- Winrate Categoría A < 58%: revisar definición de Categoría A. Algo en los criterios está fallando.
- Más del 40% de operaciones activan gale: las entradas primarias son de mala calidad.

**Módulos:** Script de análisis de Fase 4 + revisión de parámetros.
**Tiempo estimado:** 2-4 semanas de operación real para acumular 100 trades.

---

## Dependencias entre Fases

```
Fase 1 (obligatoria antes de cualquier otra)
    ↓
Fase 2 (implementar filtros)
    ↓
Fase 3 (mejorar timing — paralela con Fase 2 si se tiene capacidad)
    ↓
Fase 4 (recolectar datos — comienza al mismo tiempo que Fase 2)
    ↓
Fase 5 (ajustar Masaniello con datos reales de Fase 4)
    ↓
Fase 6 (validación — requiere Fases 1-5 completadas)
```

---

## Tiempo Total Estimado

- Fase 1: 1-2 días de trabajo
- Fase 2: 2-3 días de trabajo
- Fase 3: 2-3 días de trabajo
- Fase 4: 2-3 días de trabajo (más tiempo de recolección de datos)
- Fase 5: 2-3 días de trabajo
- Fase 6: 2-4 semanas de operación real

Total de desarrollo: 2-3 semanas de trabajo técnico + 4 semanas de validación.
