# 07 — Broker API (pyquotex)

## Integración actual

El bot usa `pyquotex.stable_api` para:

- conexión y autenticación
- listado de activos OTC abiertos
- descarga de velas
- envío de órdenes binarias
- consulta de balance y resultados

## Llamada de orden

Forma esperada de envío:

- `buy(amount, asset, direction, duration)`
- `duration` operativo del sistema: `300`

## Reglas prácticas

1. Validar conexión antes de ordenar
2. Reintentar conexión si el websocket se degrada
3. Evitar saturación de requests con concurrencia controlada
4. Registrar siempre resultado/timeout en caja negra

## Errores comunes

- `expiration`: duración no válida para contexto del broker
- timeout de confirmación websocket
- activo no disponible o payout cambiante

## Cierre limpio

En finalización del proceso, el bot intenta cerrar conexiones y persistir estado de sesión para facilitar reconexión y continuidad operativa.
