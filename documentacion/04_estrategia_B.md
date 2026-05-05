# 04 — Estrategia B: Spring / Upthrust (estado actual)

## Resumen

STRAT-B detecta eventos Wyckoff en 1m usando `detect_spring_or_upthrust`.

Puede generar:

- señal CALL (spring)
- señal PUT (upthrust)
- señales tempranas Wyckoff (`wyckoff_early_*`)

## Activación

En runtime, `main.py` controla STRAT-B con CLI:

- `--strat-b-live`: habilita apertura de órdenes por STRAT-B
- sin flag: STRAT-B puede analizar/señalizar, pero no abre orden live

## Confianza

- umbral normal: `STRAT_B_MIN_CONFIDENCE = 0.70`
- umbral early: `STRAT_B_MIN_CONFIDENCE_EARLY = 0.62`
- near-miss visible desde `STRAT_B_PREVIEW_MIN_CONF = 0.45`

## Integración con caja negra

STRAT-B registra decisiones en el mismo journal:

- `ACCEPTED` cuando entra orden
- `REJECTED_SCORE` en señal/near-miss de confianza insuficiente
- `REJECTED_LIMIT` si hay bloqueo por concurrencia o gale activo

Esto permite comparar A/B con scripts de análisis y métricas por sesión.

## Duración y ejecución

- duración STRAT-B: 300s
- comparte límites globales de ejecución (concurrencia, cooldown y estados de riesgo operativos)
