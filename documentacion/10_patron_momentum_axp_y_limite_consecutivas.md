# Patron momentum AXP y limite de consecutivas (2026-04-29)

## Referencia de caja negra
En la franja de las 13:00 (UTC-3) se observaron entradas consecutivas en el mismo activo:

- 13:11:21 - AXP_otc - breakout CALL - ACCEPTED (id 1682)
- 13:13:43 - AXP_otc - breakout CALL - ACCEPTED (id 1683)
- 13:14:52 - AXP_otc - breakout CALL - ACCEPTED (id 1684)

Nota: en el pedido se mencionan 13:03:22, 13:11:31 y 13:13:53. En la DB los timestamps mas cercanos y confirmados para AXP son los tres listados arriba.

## Patron que se mantiene
Se mantiene el patron de breakout/momentum en activos muy volatiles porque fue correcto en contexto:

- Detectar ruptura con fuerza (BROKEN_ABOVE o BROKEN_BELOW)
- Permitir entrada por momentum cuando la ruptura es valida

## Guardrail agregado
Para evitar sobreexposicion en un mismo activo:

- Maximo 2 entradas consecutivas por activo
- La tercera entrada seguida del mismo activo se bloquea
- Se registra en caja negra como:
  - decision = REJECTED_LIMIT
  - outcome = LIMIT_SKIPPED
  - reject_reason = "maximo 2 entradas consecutivas en <asset>"

## Excepcion aplicada
La etapa martin queda exenta de este limite para no romper la recuperacion del ciclo.
