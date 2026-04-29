# Estudio de caso - JNJ_otc breakout CALL (2026-04-29 11:22:26 UTC-3)

## Operación guardada
- id: 1666
- scanned_at: 2026-04-29T11:22:26-03:00
- asset: JNJ_otc
- direction: call
- stage: breakout
- payout: 89
- amount: 1.62
- score: 68.0
- decision: ACCEPTED
- order_id: 38c254a4-773f-49e8-9d7b-beb3e3230489
- closed_at: 2026-04-29T11:23:26-03:00

## Evidencia de ejecución en log
- 09:22:26 candidato aceptado con score 68.0 y umbral 65.
- 09:22:26 entrada enviada: ENTRADA[breakout] CALL JNJ_otc $1.62 30s.
- 09:22:39 orden aceptada por broker con id 38c254a4-773f-49e8-9d7b-beb3e3230489.

## Velas descargadas para análisis
- CSV: data/exports/20260429_112621_JNJ_otc_multiframe_2dias.csv
- Timeframes: 1m, 5m, 15m, 4h
- Universo usado para soporte operativo: ventana 1m de 50 min antes a 20 min después de la entrada.

## Soportes detectados (clustering de lows 1m)
Top niveles por toques:
- 188.80 (6 toques, ancho 0.006, último toque 11:08)
- 188.81 (5 toques, ancho 0.008, último toque 11:21)
- 188.75 (4 toques, ancho 0.007, último toque 11:22)

Soporte estructural 5m más repetido en tramo previo:
- 188.73 y 188.75 (2 toques cada uno)

## Conclusión: mejor zona de soporte para mejorar entrada CALL
- Soporte operativo principal: 188.80
- Zona recomendada de gatillo para CALL: [188.83, 188.86]
- Precio de entrada observado en el caso: 188.78

## Ajuste recomendado para afinar punto de entrada
- Mantener validación de breakout, pero para CALL exigir retesteo cercano al soporte operativo (188.80) y disparar cuando vuelva a cerrar por encima de 188.83.
- Evitar compra si el precio queda demasiado extendido por encima de 188.86 en el minuto de entrada.
- Esto reduce entradas tardías y mejora relación soporte-riesgo en escenarios similares.
