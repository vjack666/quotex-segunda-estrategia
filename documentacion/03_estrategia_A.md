# 03 — Estrategia A: Consolidación (estado actual)

## Resumen

STRAT-A analiza velas de 5 minutos, detecta zonas de consolidación y evalúa entradas de:

- Rebote en techo/piso
- Ruptura fuerte (breakout)
- Escenario de sobreextensión con rebote técnico (cuando aplica)

Duración de orden operativa: 300 segundos.

## Pipeline STRAT-A

1. Fetch 5m por activo (`CANDLES_LOOKBACK = 55`)
2. Guard de historia mínima (`MIN_CANDLES_FOR_FULL_SCAN = 50`)
3. Detección de zona de consolidación
4. Clasificación de señal (rebote / breakout)
5. Confirmaciones 1m y cálculo de score
6. Selección por umbral dinámico
7. Filtros finales de ejecución y envío de orden

## Filtros relevantes añadidos

### Filtro F1 (force breakout)

Para candidatos con `force_execute=True`:

- Si no hay patrón de reversión (`reversal = none`) y score < umbral dinámico, se descarta.

Objetivo: evitar forzar rupturas de baja calidad.

### Filtro F2 (sobreextensión)

Si la distancia al trigger excede `MAX_BREAKOUT_OVEREXTENSION_PCT = 0.12%`, se descarta la entrada de breakout.

Objetivo: no perseguir precio ya extendido.

### Escenario extra: overextension -> soporte -> CALL

Cuando F2 bloquea una ruptura PUT por sobreextensión, el bot puede buscar soporte fuerte en 2m y generar un candidato CALL de rebote si hay condiciones de toques/proximidad.

### Complemento rechazo M1 (tesis hibrida)

Para entradas por rebote, se añadió una validación operativa adicional:

- Ventana temporal configurable para ejecutar rechazo intravela M1
	(por defecto, segundo 30-41).
- Clasificación de calidad de rechazo:
	- parcial: cumple mecha/cuerpo mínimo pero sin giro contundente.
	- total: cuerpo más dominante y rechazo más fuerte.
- Opción de bloquear rechazos parciales por configuración.

Objetivo: combinar timing preciso de rechazo con filtros estructurales ya
existentes, reduciendo entradas tardías o de baja calidad.

## Score y selección

El score considera compresión, rebote, tendencia y payout, más ajustes por patrón/reversión y contexto.

Para rebotes confirmados como rechazo total se aplica un bonus pequeño de score.

El umbral es dinámico en ventana de scans:

- base: 65
- bajo: 62
- alto: 68

## Ejecución

- `MAX_CONCURRENT_TRADES = 2`
- cooldown entre entradas: 30s
- bloqueo de reentrada por estructura configurable (`STRUCTURE_ENTRY_LOCK_TTL_MIN`)

## Registro

Cada candidato A se persiste en caja negra con:

- decisión (`ACCEPTED`, `REJECTED_SCORE`, `REJECTED_LIMIT`, `REJECTED_STRUCTURE`, ...)
- `strategy_json` con snapshot de parámetros y breakdown de score
- velas usadas para análisis
