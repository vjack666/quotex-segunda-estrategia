# 05 — Flujo de Datos End-to-End

## 1) Arranque

`main.py`:

- carga CLI
- aplica overrides en runtime
- inicia loop del bot

## 2) Ciclo de scan

`consolidation_bot.scan_all()`:

- obtiene activos OTC abiertos
- filtra payout mínimo
- realiza fetch de velas 5m y 1m

## 3) Generación de señales

- STRAT-A: consolidación 5m + patrones/score
- STRAT-B: spring/upthrust 1m + confianza

## 4) Selección y filtros

- umbral dinámico de score
- filtros estructurales y de sobreextensión
- límites de concurrencia/gale
- para rebotes: validación rechazo M1 (dirección, cuerpo, mecha)
- para rebotes: ventana temporal intravela configurable (segundo 30-41 por defecto)
- para rebotes: clasificación rechazo parcial/total (opcionalmente solo total)

## 5) Ejecución

- envío de orden al broker (`buy`)
- tracking en memoria del trade abierto

## 6) Resolución

- actualización de resultado en journal (`WIN/LOSS/UNRESOLVED/PENDING`)
- actualización de stats de sesión

## 7) Persistencia

- candidatos y decisiones a SQLite diario
- logs operativos en `data/logs/bot`
- capturas forenses de rupturas en `data/vela_ops`

## 8) Aprendizaje

Post-sesión:

- export métricas CSV
- revisión de caja negra
- export de velas candidatas
- archivado de sesión en `aprendizaje/sesiones`
