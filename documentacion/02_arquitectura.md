# 02 — Arquitectura del Sistema

## Estructura de Archivos

```
QUOTEX - segunda estrategia/
│
├── main.py                        ← Punto de entrada CLI (argumentos, arranque)
├── .env                           ← Credenciales (EMAIL, PASSWORD) — NO versionar
├── requirements.txt               ← Dependencias pip
├── trade_journal.db               ← Base de datos SQLite (generada en runtime)
├── consolidation_bot.log          ← Log rotativo de sesión
│
├── src/                           ← Código fuente principal
│   ├── consolidation_bot.py       ← Motor principal del bot (~2100 líneas)
│   ├── models.py                  ← Estructuras de datos compartidas (Candle, ConsolidationZone)
│   ├── entry_scorer.py            ← Sistema de scoring matemático de señales
│   ├── candle_patterns.py         ← Detección de patrones de reversión en velas 1m
│   ├── strategy_spring_sweep.py   ← STRAT-B: detector Wyckoff Spring Sweep
│   ├── trade_journal.py           ← Persistencia SQLite de trades y candidatos
│   ├── config.py                  ← Configuración auxiliar
│   ├── bot.py                     ← Stub/utilidades
│   ├── smc_analysis.py            ← Análisis SMC (Smart Money Concepts)
│   ├── smc_dashboard.py           ← Dashboard SMC
│   ├── smc_decision_engine.py     ← Motor de decisión SMC
│   └── lab/                       ← Scripts de diagnóstico y pruebas rápidas
│       ├── check_asset_status.py
│       ├── inspect_candle_shape.py
│       ├── list_open_otc_assets.py
│       ├── place_demo_sell_fast.py
│       ├── quick_trade_test.py
│       ├── show_balance.py
│       └── verified_market_sell.py
│
├── data/
│   ├── candles_EURUSD_otc_60.csv  ← Dataset histórico para análisis offline
│   └── vela_ops/                  ← Capturas forenses JSON de eventos BROKEN_*
│
├── lab/                           ← Laboratorio de investigación offline
│   └── usddzd_otc_strategy2/
│       ├── concepto_estrategia_v2.txt
│       ├── evaluar_usddzd_v2.py
│       └── reglas_v2.json
│
└── sessions/
    ├── config.json                ← Configuración de sesión pyquotex
    └── session.json               ← Estado de autenticación guardado
```

---

## Diagrama de Dependencias entre Módulos

```
main.py
  └─→ consolidation_bot.py  (motor)
        ├─→ models.py              (Candle, ConsolidationZone)
        ├─→ entry_scorer.py        (CandidateEntry, score_candidate, select_best)
        │     └─→ models.py
        ├─→ candle_patterns.py     (detect_reversal_pattern, CandleSignal)
        │     └─→ models.py
        ├─→ strategy_spring_sweep.py  (detect_spring_sweep)
        ├─→ trade_journal.py       (get_journal, Journal)
        └─→ pyquotex.stable_api    (Quotex — WebSocket broker API)
```

---

## Módulos: Responsabilidades

### `main.py`
- Parsea argumentos de CLI con `argparse`
- Aplica overrides de configuración en tiempo de ejecución sobre las constantes de `consolidation_bot.py`
- Invoca `cb.main(dry_run, real_account, loop_forever)`

### `consolidation_bot.py`
- Clase `ConsolidationBot`: estado completo del bot en memoria
  - `self.zones`: dict de zonas de consolidación activas por activo
  - `self.trades`: dict de trades abiertos por activo
  - `self.stats`: contadores de sesión (scans, entradas, wins, losses...)
- Funciones de análisis técnico (puras): `detect_consolidation`, `broke_above`, `broke_below`, `price_at_ceiling`, `price_at_floor`, `is_high_volume_break`, `compute_atr`, `infer_h1_trend`
- Funciones de red: `fetch_candles_with_retry`, `get_open_assets`, `place_order`
- Función `main()`: loop principal 24/7

### `models.py`
- `Candle`: `ts, open, high, low, close` + propiedades calculadas `body`, `range`
- `ConsolidationZone`: `asset, ceiling, floor, bars_inside, detected_at, range_pct` + propiedad `age_minutes`

### `entry_scorer.py`
- `CandidateEntry`: representa una señal candidata con score y desglose
- `score_candidate(c)`: calcula puntuación 0-100 sobre 4 dimensiones
- `select_best(candidates)`: filtra los que superan `SCORE_THRESHOLD = 62` y devuelve el mejor
- `explain_score(c)`: genera texto legible del desglose de puntuación

### `candle_patterns.py`
- `detect_reversal_pattern(candles_1m, direction)` → `CandleSignal`
- Patrones soportados con su fuerza:
  - Bearish: `bearish_engulfing (0.85)`, `shooting_star (0.75)`, `evening_star_simple (0.65)`, `bearish_inverted_hammer (0.55)`
  - Bullish: `bullish_engulfing (0.85)`, `hammer (0.75)`, `morning_star_simple (0.65)`, `bullish_hammer (0.55)`

### `strategy_spring_sweep.py`
- `detect_spring_sweep(df)` → `(bool, dict)` — detector de patrones Wyckoff en DataFrame OHLC
- Completamente stateless — solo análisis, sin efectos secundarios

### `trade_journal.py`
- Singleton `get_journal()` → `Journal` (instancia única por proceso)
- Persiste en SQLite: `trade_journal.db`
- Registra cada señal evaluada, su resultado y el contexto de estrategia

---

## Tecnologías Clave

| Tecnología | Versión | Rol |
|---|---|---|
| Python | 3.13+ | Runtime |
| pyquotex | 1.0.3 | API WebSocket al broker Quotex |
| asyncio | stdlib | Concurrencia para fetches paralelos y loop principal |
| SQLite | stdlib | Persistencia del diario de trades |
| pandas | ≥1.5 | Análisis OHLC en STRAT-B |
| asyncio.Semaphore | stdlib | Control de concurrencia en fetch de velas (máx 8 simultáneos) |
