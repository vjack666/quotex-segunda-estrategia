# 06 — Parámetros de Configuración (vigentes)

Fuente de verdad: `src/consolidation_bot.py` y overrides de `main.py`.

## Núcleo operativo

| Parámetro | Valor actual |
|---|---|
| `TF_5M` | `300` |
| `CANDLES_LOOKBACK` | `55` |
| `MIN_CONSOLIDATION_BARS` | `12` |
| `MIN_CANDLES_FOR_FULL_SCAN` | `50` |
| `MIN_PAYOUT` | `80` |
| `DURATION_SEC` | `300` |
| `MAX_CONCURRENT_TRADES` | `2` |

## Filtros clave

| Parámetro | Valor |
|---|---|
| `MAX_BREAKOUT_OVEREXTENSION_PCT` | `0.0012` (0.12%) |
| `FORCE_EXECUTE_STRONG_BREAKOUT` | `True` |
| `STRUCTURE_ENTRY_LOCK_TTL_MIN` | `180` |
| `SAME_ASSET_REENTRY_COOLDOWN_SEC` | `65` |

## Rechazo M1 (complemento hibrido)

| Parámetro | Valor por defecto |
|---|---|
| `REJECTION_ENTRY_WINDOW_ENABLED` | `True` |
| `REJECTION_ENTRY_WINDOW_START_SEC` | `30` |
| `REJECTION_ENTRY_WINDOW_END_SEC` | `41` |
| `REJECTION_TOTAL_MIN_BODY_RATIO` | `0.55` |
| `REJECTION_ALLOW_PARTIAL` | `True` |

Interpretación:

- La validación de rechazo en rebotes se habilita preferentemente en la ventana
	intravela configurada (orientada al segundo 30).
- El rechazo se clasifica en parcial/total según proporción de cuerpo.
- Se puede forzar modo estricto de solo rechazo total.

## Umbral dinámico de score

| Parámetro | Valor |
|---|---|
| `ADAPTIVE_THRESHOLD_BASE` | `65` |
| `ADAPTIVE_THRESHOLD_LOW` | `62` |
| `ADAPTIVE_THRESHOLD_HIGH` | `68` |
| `ADAPTIVE_THRESHOLD_WINDOW_SCANS` | `10` |

## STRAT-B

| Parámetro | Valor |
|---|---|
| `STRAT_B_DURATION_SEC` | `300` |
| `STRAT_B_MIN_CONFIDENCE` | `0.70` |
| `STRAT_B_MIN_CONFIDENCE_EARLY` | `0.62` |
| `STRAT_B_PREVIEW_MIN_CONF` | `0.45` |
| `STRAT_B_ALLOW_WYCKOFF_EARLY` | `True` |

Nota: en ejecución normal, `main.py` define `STRAT_B_CAN_TRADE` con `--strat-b-live`.

## Riesgo de sesión (entrenamiento)

| Parámetro | Valor |
|---|---|
| `MAX_LOSS_SESSION` | `0.20` |
| `ENABLE_SESSION_STOP_LOSS` | `False` |

Interpretación: el umbral existe, pero el corte automático por drawdown está desactivado para recolectar datos.

## Overrides CLI más usados

- `--min-payout`
- `--cycle-ops`
- `--cycle-wins`
- `--cycle-profit-pct`
- `--scan-lead-sec`
- `--scan-sleep-sec`
- `--strat-b-live`
- `--strat-b-min-confidence`
- `--same-asset-cooldown-sec`
- `--structure-entry-lock-ttl-min`
- `--rejection-entry-window-enabled` / `--no-rejection-entry-window-enabled`
- `--rejection-entry-window-start-sec`
- `--rejection-entry-window-end-sec`
- `--rejection-total-min-body`
- `--rejection-disallow-partial`
