# Logs de Sesiones — Estrategia 30 Segundos

Carpeta para registrar resultados de:
- Backtesting manual (CSV)
- Backtesting automatizado (JSON/CSV)
- Sesiones demo en vivo

## Formato de log manual (backtest_manual.csv)

```csv
fecha,hora_entrada,activo,zona,wick_ratio,rsi,stoch,bb,score,direction,resultado
2026-05-10,14:30:32,EURUSD_OTC,1.09350,2.8,24.5,18.3,si,9,CALL,WIN
2026-05-10,14:32:31,EURUSD_OTC,1.09200,1.7,68.2,45.1,no,6,CALL,LOSS
```

## Archivos esperados
- `backtest_manual.csv` — señales revisadas manualmente en gráfico
- `backtest_auto_YYYY-MM-DD.json` — resultados del backtester.py
- `demo_sesion_YYYY-MM-DD.json` — operaciones en cuenta demo
