# PLAN MAESTRO — Sistema de Trading de Alta Calidad
*Basado en auditoría técnica completa del código fuente real*

---

## 1. Propósito de Este Documento

Este documento conecta todos los hallazgos de la auditoría técnica con el objetivo
operativo real del sistema: **no operar mucho, operar bien**.

La meta no es maximizar el número de señales. Es maximizar la calidad de cada
operación ejecutada, para que el Masaniello tenga el mayor margen matemático posible.

---

## 2. El Problema Central del Sistema Actual

Después de revisar el código real de todos los módulos, el problema no está en la
detección de señales. El sistema ya detecta correctamente zonas, rebotes, springs y
rupturas. El problema está en **cuándo decide operar**.

El sistema actual opera cuando encuentra una señal que supera el umbral de score.
Eso no es lo mismo que operar solo los mejores setups del día.

La diferencia entre un sistema con 52% de acierto y uno con 62% no suele estar en
el algoritmo de detección. Está en los setups que se rechazan.

---

## 3. El Edge Real del Sistema

Después de analizar todos los módulos, el edge estadístico más probable está en la
**confluencia de tres capas**:

### Capa 1 — Estructura de mercado (HTF)
Cuando la tendencia en 15 minutos está alineada con la dirección de entrada, el
precio tiene mayor probabilidad de continuar esa dirección durante los 5 minutos
que dura la operación. Esto no es teoría: es el principio de "operar a favor del
flujo mayor".

Módulo que lo implementa: `htf_scanner.py` + `_score_trend` en `entry_scorer.py`.

### Capa 2 — Zona de consolidación fuerte
Una zona con range_pct bajo (idealmente < 0.10%) y muchas velas dentro indica que
el precio estuvo comprimido y los participantes acumularon posiciones. Un rechazo
desde esa zona tiene más probabilidad de ser real que uno desde una zona débil.

Módulo que lo implementa: `consolidation_bot.py` + `_score_compression` en `entry_scorer.py`.

### Capa 3 — Rechazo confirmado en 1 minuto
El patrón de vela 1m (hammer, engulfing, shooting star) es el detonador final.
Sin confirmación de vela, el setup puede estar bien estructurado pero el timing
es incorrecto.

Módulo que lo implementa: `candle_patterns.py`.

Cuando las tres capas coinciden, el sistema tiene edge real. Cuando falta alguna,
la operación entra en zona dudosa.

---

## 4. Lo Que Destruye el Edge

Basado en el código real, estas son las condiciones que generan operaciones de baja
calidad:

**Zona joven (< 30 minutos):** El scoring penaliza zonas con menos de 10 minutos,
pero permite operar zonas entre 10 y 30 minutos con solo -5 puntos de ajuste. Eso
no es suficiente penalización. Una zona joven no ha sido probada por el mercado.

**Payout marginal (80-83%):** El sistema acepta payouts desde 80%. Operar con 80%
de payout cuando el winrate objetivo es 60% produce un margen matemático muy ajustado.
Con 60% de acierto y 80% de payout: EV = 0.6 × 0.80 - 0.4 × 1.0 = 0.08. Apenas
rentable. Un payout de 87%+ con el mismo winrate produce EV = 0.122, que es 52% mejor.

**Score entre 65 y 72:** El umbral de 65 puntos deja pasar setups mediocres. Un
candidato con score 67 que cumple el threshold no es necesariamente bueno. Es
simplemente suficiente. "Suficiente" no es el objetivo.

**Sin confirmación de vela:** El sistema puede entrar con pattern = "none" si el
score es alto. Esto es un error conceptual. El score mide la calidad del contexto,
no el timing. El timing lo da la vela 1m.

**HTF sin alinear:** Entrar en rebote alcista cuando la tendencia 15m es bajista
es operar contra el flujo mayor. El sistema no bloquea esta condición; solo penaliza
levemente el componente de trend en el score.

---

## 5. Los Módulos Que Realmente Aportan Precisión

En orden de impacto estimado:

1. **htf_scanner.py** — Contexto de flujo mayor. Sin esto, el sistema opera en ciegas.
2. **zone_memory.py** — Historia de la zona. Las zonas que ya resistieron el precio son más fuertes.
3. **spike_filter.py** — Higiene de datos. Un feed contaminado genera señales falsas.
4. **candle_patterns.py** — Timing de entrada. El mejor contexto con mala vela = pérdida.
5. **entry_scorer.py** — Integrador de señales. El score es válido cuando todos los componentes aportan.
6. **vip_library.py** — Capa de vigilancia. Los candidatos que llevan tiempo cumpliendo condiciones son más confiables.

---

## 6. Los Módulos Que Generan Ruido

1. **LEGACY-RJ ticker** — Consume recursos sin producir nada. Debe desactivarse condicionalmente.
2. **martingale_calculator.py** — Coexiste con Masaniello como sistema secundario sin responsabilidad clara.
3. **strategy_spring_sweep.py en modo forzado off** — El módulo existe y funciona, pero está apagado desde main. Si no se usa, no debería correr.

---

## 7. Principio Rector del Plan

> El sistema debe buscar activamente razones para NO operar.
> Solo cuando no encuentra ninguna razón válida para rechazar un setup,
> debe autorizar la entrada.

Este es el cambio conceptual más importante. El sistema actual busca razones para
operar (score ≥ 65). El sistema mejorado debe buscar razones para rechazar, y solo
operar lo que sobrevive el filtro agresivo.

---

## 8. Estructura del Plan de Trabajo

El plan se divide en 6 fases, cada una documentada en detalle en ROADMAP_TECNICO.md.

Resumen ejecutivo:

- **Fase 1:** Eliminar ruido técnico (seguridad, debug, legacy activo inútil)
- **Fase 2:** Endurecer filtros de entrada (score mínimo, payout mínimo, HTF obligatorio)
- **Fase 3:** Mejorar timing (VIP library como gating, ventana de entrada estricta)
- **Fase 4:** Mejorar calidad estadística (métricas reales, análisis por tipo de setup)
- **Fase 5:** Optimizar Masaniello (proteger ciclos con filtros de calidad)
- **Fase 6:** Validar rentabilidad real (backtesting con journal + black box)

---

## 9. Métricas de Éxito del Sistema

El sistema habrá mejorado cuando estas métricas mejoren simultáneamente:

| Métrica | Estado actual estimado | Objetivo |
|---|---|---|
| Winrate real | Desconocido (journal no analizado estadísticamente) | ≥ 60% |
| Operaciones por sesión 2h | Sin límite explícito | ≤ 5 |
| Score promedio de entradas | ~67-72 estimado | ≥ 75 |
| Payout promedio | ~83% estimado | ≥ 87% |
| Entradas sin HTF alineado | Sin restricción | 0 |
| Entradas sin patrón 1m | Permitidas | 0 |
| Entradas en zona < 30min | Solo -5 pts penalización | Bloqueadas |
| Ciclos Masaniello completados positivamente | Desconocido | ≥ 70% |

---

## 10. Nota sobre el Masaniello

El Masaniello es matemáticamente correcto en su implementación (`masaniello_engine.py`
replica fielmente la fórmula del Excel). El problema no está en el motor de riesgo.
El problema está en la calidad de las entradas que el motor recibe.

Un Masaniello 5/2 (5 ops, 2 wins objetivo) tiene margen matemático positivo solo si
el winrate subyacente supera ~42%. Con 60% de winrate tiene margen amplio. Con 52%
de winrate opera en zona de riesgo. La diferencia la hacen los filtros, no el motor.

Ver PLAN_MASANIELLO.md para análisis detallado.
