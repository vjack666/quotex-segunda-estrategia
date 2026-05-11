# MATRIZ DE CALIDAD DE ENTRADA
*Clasificación real de setups basada en el código existente*

---

## Principio de la Matriz

Cada operación debe clasificarse antes de ejecutarse. La clasificación no es
opcional ni subjetiva: se deriva de condiciones verificables que ya están
implementadas en los módulos existentes.

La clasificación determina si se opera, no si se analiza. El análisis ocurre
siempre. La ejecución solo ocurre en categorías A y B.

---

## CATEGORÍA A — Setup Perfecto
*Operar sin restricción. Prioridad máxima en cola de entrada.*

### Condiciones obligatorias (todas deben cumplirse):

**Estructura HTF:**
- Tendencia 15m alineada con dirección de entrada
- MA rápida > MA lenta en 15m para CALL, inverso para PUT
- Cache HTF vigente (< 870 segundos de antigüedad)
- Módulo: `htf_scanner.get_candles_15m()` + `_score_trend` en `entry_scorer.py`

**Zona de consolidación:**
- `range_pct` ≤ 0.10% (RANGE_EXCELLENT en entry_scorer.py)
- `bars_inside` ≥ 20 (zona bien establecida)
- Antigüedad de zona entre 30 y 120 minutos
- Módulo: `ConsolidationZone` + `_score_compression`

**Contexto histórico:**
- `zone_memory` sin muros en la dirección (sin resistencias/soportes bloqueantes)
- Zona histórica de soporte alineada debajo para CALL, resistencia arriba para PUT
- Módulo: `zone_memory.py` → `score_zone_memory()`

**Confirmación de vela 1m:**
- Patrón de reversión con strength ≥ 0.75 (bearish_engulfing, bullish_engulfing, shooting_star, hammer)
- `confirms_direction = True`
- Módulo: `candle_patterns.detect_reversal_pattern()`

**Feed limpio:**
- Sin anomalía de spike en últimas 20 velas 1m
- Sin anomalía de spike en últimas 12 velas 5m
- Módulo: `spike_filter.detect_spike_anomaly()`

**Payout:**
- ≥ 87%

**Score:**
- ≥ 78 puntos (umbral endurecido respecto al actual de 65)

**Nivel H1:**
- Precio en zona de swing low para CALL (bonus +12)
- Precio en zona de swing high para PUT (bonus +18)
- Módulo: `detect_swing_levels` + `_score_historical_level` en `entry_scorer.py`

### Riesgo: Bajo
### Acción: Ejecutar inmediatamente con monto Masaniello calculado.

---

## CATEGORÍA B — Setup Bueno
*Operar. Requiere mayor vigilancia post-entrada.*

### Condiciones: Cumple todo lo de Categoría A excepto uno de estos:

- Patrón 1m tiene strength entre 0.55 y 0.74 (morning_star_simple, bullish_hammer, bearish_inverted_hammer, evening_star_simple)
- `range_pct` entre 0.10% y 0.15% (zona algo más ancha pero aún comprimida)
- Zona con antigüedad entre 20 y 30 minutos (joven pero no reciente)
- Payout entre 84% y 86%
- Score entre 73 y 77

### Restricción adicional:
No operar si ya hay una operación B activa en la misma sesión que resultó en pérdida.
La segunda operación B consecutiva en sesión solo se permite si el winrate de la sesión
actual es ≥ 50%.

### Riesgo: Medio
### Acción: Ejecutar con monitoreo activo. Anotar como "B" en journal para análisis estadístico.

---

## CATEGORÍA C — Setup Dudoso
*No operar. Registrar el candidato en journal para análisis posterior.*

### Condiciones que lo clasifican como C (basta con una):

- HTF sin alinear (trend 15m contrario a la dirección de entrada)
- Sin patrón de vela 1m confirmado (pattern = "none")
- Zona con antigüedad < 20 minutos
- Spike detectado en cualquier timeframe en las últimas 30 minutos
- Payout < 84%
- Score entre 65 y 72
- Zone memory con muro bloqueante a menos de 0.15% en la dirección

### Riesgo: Alto
### Acción: No ejecutar. Registrar candidato con etiqueta "REJECTED_C" para estadística.

---

## CATEGORÍA D — Setup Prohibido
*Nunca operar. Si el sistema intenta ejecutarlo, hay un error de lógica.*

### Condiciones que lo definen (cualquiera es suficiente):

- Precio dentro de la zona de consolidación activa (no en extremo)
- Spike detectado en vela actual o anterior inmediata
- HTF sin datos (cache vacío o expirado)
- Payout < 80%
- Score < 65
- Zona sin confirmar (bars_inside < 10)
- Ya hay una operación activa (una sola entrada por ciclo, MAX_ENTRIES_CYCLE = 1)
- Zona con antigüedad < 10 minutos
- Se alcanzó el límite de operaciones de la sesión (> 5 ops en 2 horas)

### Riesgo: Crítico
### Acción: Bloquear en código. No mostrar en HUB como candidato válido.

---

## Tabla Resumen de Condiciones

| Condición | Cat A | Cat B | Cat C | Cat D |
|---|---|---|---|---|
| HTF 15m alineado | ✅ obligatorio | ✅ obligatorio | ❌ falla aquí | ❌ |
| Patrón 1m strength ≥ 0.75 | ✅ obligatorio | ⚠️ 0.55-0.74 | ❌ none | ❌ |
| range_pct ≤ 0.10% | ✅ | ⚠️ hasta 0.15% | ⚠️ | ❌ > 0.30% |
| Zona ≥ 30 min antigüedad | ✅ | ⚠️ 20-30 min | ❌ < 20 min | ❌ < 10 min |
| Sin spike | ✅ obligatorio | ✅ obligatorio | ❌ falla aquí | ❌ spike actual |
| Payout ≥ 87% | ✅ | ⚠️ 84-86% | ❌ < 84% | ❌ < 80% |
| Score ≥ 78 | ✅ | ⚠️ 73-77 | ❌ 65-72 | ❌ < 65 |
| Zone memory sin muro | ✅ obligatorio | ✅ obligatorio | ❌ falla aquí | ❌ |
| H1 swing level alineado | ✅ ideal | ⚠️ neutral ok | ❌ contra | ❌ |

---

## Flujo de Clasificación en Código

El flujo de clasificación debe seguir este orden estricto. Si algún filtro falla,
se asigna la categoría más baja correspondiente y se detiene el análisis:

```
1. ¿Hay operación activa? → D (salir)
2. ¿Ops en sesión > 5? → D (salir)
3. ¿Payout < 80%? → D (salir)
4. ¿Score < 65? → D (salir)
5. ¿Spike en vela actual? → D (salir)
6. ¿HTF cache vacío? → D (salir)
7. ¿HTF alineado? → si no → C (registrar y salir)
8. ¿Sin patrón 1m? → C (registrar y salir)
9. ¿Zona < 10 min? → D (salir)
10. ¿Zona < 20 min? → C (registrar y salir)
11. ¿Zone memory muro bloqueante? → C (registrar y salir)
12. ¿Payout < 84%? → C (registrar y salir)
13. ¿Score < 73? → C (registrar y salir)
14. ¿Patrón strength < 0.55? → C (registrar y salir)
15. ¿Patrón strength < 0.75 O payout < 87% O score < 78? → B (operar con aviso)
16. Todo cumplido → A (operar)
```

---

## Nota sobre el Sistema Actual

El sistema actual ejecuta el paso 4 (score ≥ 65) y omite los pasos 7, 8, 9, 10, 11
como bloqueantes hard. Los trata como penalizaciones de score, no como vetos.

El cambio más importante no es agregar lógica nueva. Es convertir condiciones que
hoy son penalizaciones de score en vetos binarios que detienen la ejecución.

Esto se implementa modificando el flujo de decisión en `consolidation_bot.py` antes
de llamar a `_enter()`, sin tocar los módulos de scoring existentes.
