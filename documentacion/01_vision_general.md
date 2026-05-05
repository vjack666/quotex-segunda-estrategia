# 01 — Visión General del Sistema

## Qué es

Bot de trading OTC para Quotex con dos estrategias en paralelo:

- STRAT-A: consolidación en 5m
- STRAT-B: spring/upthrust en 1m

El sistema está orientado a entrenamiento iterativo: recolectar datos, analizar caja negra, ajustar pocos parámetros y repetir.

## Objetivo operativo

1. Detectar setups de alta probabilidad en múltiples activos OTC
2. Registrar cada decisión (aceptada y rechazada) para aprendizaje
3. Ajustar filtros para reducir rigidez excesiva sin perder control

## Modos de ejecución

- Análisis/monitoreo: `python main.py --hub-readonly`
- Un ciclo: `python main.py --once`
- Loop continuo: `python main.py`
- Cuenta real: `python main.py --real`

## Estrategias

### STRAT-A (principal)

- Detecta consolidación en velas 5m
- Opera rebotes y rupturas
- Usa scoring matemático + filtros estructurales

### STRAT-B (complementaria)

- Detecta spring/upthrust en 1m
- Puede operar en live con `--strat-b-live`
- Si no está en live, igual puede quedar auditada en logs/near-miss según umbral

## Tesis operativa hibrida (nuevo complemento)

El sistema adopta una tesis combinada para rechazos:

1. Contexto estructural del bot (zonas + filtros + score).
2. Confirmación visual de rechazo M1 (mecha + cuerpo + patrón).
3. Timing intravela (ventana de segundos configurable, orientada al segundo 30).

Esto evita operar solo por intuición visual y, a la vez, mejora la precisión
temporal de entrada cuando el setup ya está validado por el motor.

## Gestión de riesgo/capital (estado entrenamiento)

- Duración de órdenes: 300s
- Max trades simultáneos: 2
- Ciclo objetivo configurable por CLI (`--cycle-ops`, `--cycle-wins`, `--cycle-profit-pct`)
- Stop-loss de sesión: desactivado por flag interno para recopilar datos (`ENABLE_SESSION_STOP_LOSS=False`)

## Datos y caja negra

- Journal diario: `data/db/trade_journal-YYYY-MM-DD.db`
- Logs del bot: `data/logs/bot/`
- Capturas forenses de rupturas: `data/vela_ops/`
- Scripts de análisis: `lab/`
- Flujo de aprendizaje y reportes: `aprendizaje/`
