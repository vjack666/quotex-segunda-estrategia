# Estudio de Caja Negra - SOLUSD_otc (2026-04-28 21:29:08 UTC-3)

## Registro localizado
- `id`: 1628
- `scanned_at`: 2026-04-28T21:29:08-03:00
- `asset`: SOLUSD_otc
- `direction`: call
- `payout`: 92
- `amount`: 1.39
- `stage`: breakout
- `score`: 24.5
- `decision`: ACCEPTED
- `outcome`: UNRESOLVED
- `order_id`: 7cbc012f-97b2-4afb-b8d6-45446e486ed0
- `reject_reason`: (vacío)
- `profit`: 0.0
- `closed_at`: 2026-04-28T21:29:53.524937-03:00

## Línea reportada por operación
- `19:29:08 [INFO] [STRAT-A] 🟢 ENTRADA[breakout] CALL SOLUSD_otc $1.39 120s | SCORE=24.5/100 | CALL en SOLUSD_otc payout=92%`

## Snapshot de configuración guardado en la operación (strategy_json)
```json
{
  "tf_sec": 300,
  "candles_lookback": 55,
  "min_consolidation_bars": 12,
  "max_range_pct": 0.003,
  "touch_tolerance_pct": 0.00035,
  "max_consolidation_min": 0,
  "min_payout": 80,
  "duration_sec": 120,
  "amount_initial": 1.0,
  "amount_martin": 3.0,
  "max_concurrent_trades": 1,
  "cooldown_between_entries": 30,
  "score_threshold_base": 65,
  "score_threshold_session": 65,
  "volume_multiplier": 1.2,
  "volume_lookback": 10,
  "zone_age_rebound_min": 20,
  "zone_age_breakout_min": 8,
  "strict_pattern_check": true,
  "entry_sync_to_candle": true,
  "entry_max_lag_sec": 1.5,
  "entry_reject_last_sec": 2.0,
  "align_scan_to_candle": false,
  "scan_lead_sec": 35.0,
  "broker_tz": "UTC-3",
  "compensation_pending": false,
  "last_closed_outcome": "",
  "last_closed_amount": 0.0,
  "max_loss_session": 0.2,
  "dynamic_atr_range": true,
  "atr_period": 14,
  "atr_range_factor": 1.35,
  "min_dynamic_range_pct": 0.0015,
  "max_dynamic_range_pct": 0.015,
  "h1_confirm_enabled": true,
  "cycle_max_operations": 5,
  "cycle_target_wins": 2,
  "cycle_target_profit_pct": 0.1,
  "cycle_id": 1,
  "cycle_ops": 0,
  "cycle_wins": 0,
  "cycle_losses": 0,
  "cycle_profit": 0.0,
  "strat_b_can_trade": false,
  "strat_b_duration_sec": 120,
  "strat_b_min_confidence": 0.7,
  "greylist_assets": [
    "USDDZD_otc"
  ]
}
```

## Nota rápida para revisión posterior
- La operación quedó como `ACCEPTED` con `order_id` real, pero `outcome` figura `UNRESOLVED`.
- Conviene revisar por qué no consolidó a `WIN/LOSS` pese a tener `closed_at` registrado.
