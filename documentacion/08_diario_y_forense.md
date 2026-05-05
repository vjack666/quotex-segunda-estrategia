# 08 — Diario y Forense

## Diario SQLite (caja negra)

Ruta actual:

- `data/db/trade_journal-YYYY-MM-DD.db`

Tabla principal: `candidates`

Cada fila guarda:

- activo, dirección, score, payout
- decisión (`ACCEPTED`, `REJECTED_SCORE`, `REJECTED_LIMIT`, `REJECTED_STRUCTURE`, ...)
- `reject_reason`
- outcome (`WIN`, `LOSS`, `PENDING`, `UNRESOLVED`, etc.)
- `strategy_origin` y snapshot `strategy_json`
- velas en `candles_json`

## Estrategias en el mismo journal

- STRAT-A y STRAT-B comparten la misma tabla
- separación por `strategy_json.strategy_origin`

## Capturas forenses

Ruta:

- `data/vela_ops/*.json`

Se generan para eventos de ruptura (BROKEN_*), con contexto de zona y velas para análisis posterior.

## Logs operativos

Ruta:

- `data/logs/bot/*.log`

## Scripts de análisis disponibles

- `lab/full_session_review.py`
- `lab/black_box_stratb.py`
- `lab/dump_candidate_candles.py`
- `aprendizaje/scripts/exportar_metricas_aprendizaje.py`

## Recomendación de ciclo de mejora

1. correr sesión
2. extraer métricas
3. revisar hallazgos por estrategia
4. ajustar pocos parámetros
5. repetir
