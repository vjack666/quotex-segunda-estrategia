# 02 — Arquitectura del Sistema

## Estructura principal

```text
QUOTEX - segunda estrategia/
├── main.py
├── README.md
├── requirements.txt
├── src/
│   ├── consolidation_bot.py
│   ├── entry_scorer.py
│   ├── candle_patterns.py
│   ├── strategy_spring_sweep.py
│   ├── trade_journal.py
│   ├── models.py
│   └── ...
├── data/
│   ├── db/
│   ├── logs/bot/
│   ├── blackbox/
│   ├── vela_ops/
│   └── candles_candidatos/
├── lab/
├── aprendizaje/
│   ├── scripts/
│   ├── sesiones/
│   ├── reportes/
│   └── datasets/
├── documentacion/
└── sessions/
```

## Dependencias entre módulos

- `main.py`:
  - parsea CLI
  - aplica overrides en runtime
  - ejecuta loop principal
- `src/consolidation_bot.py`:
  - escaneo de activos
  - generación de candidatos A/B
  - ejecución de órdenes
  - resolución de trades
- `src/entry_scorer.py`:
  - puntuación y selección de candidatos de STRAT-A
- `src/strategy_spring_sweep.py`:
  - detector de señales STRAT-B en 1m
- `src/trade_journal.py`:
  - persistencia de decisiones/resultados en SQLite

## Persistencia y forense

- Journal operativo diario: `data/db/trade_journal-YYYY-MM-DD.db`
- Logs operativos: `data/logs/bot/*.log`
- Capturas de eventos BROKEN_*: `data/vela_ops/*.json`

## Componentes de aprendizaje

- `lab/full_session_review.py`: resumen financiero y riesgos de sesión
- `lab/black_box_stratb.py`: comparación STRAT-A vs STRAT-B
- `lab/dump_candidate_candles.py`: export de velas por activo
- `aprendizaje/scripts/exportar_metricas_aprendizaje.py`: métricas CSV por sesión
- `aprendizaje/scripts/cerrar_sesion_aprendizaje.ps1`: archivado de sesión
