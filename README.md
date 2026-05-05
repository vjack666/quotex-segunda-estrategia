# QUOTEX Trading System

Sistema de entrenamiento y ejecución para estrategias OTC en Quotex.

## Estado actual

- STRAT-A (Consolidación) activa
- STRAT-B (Spring/Upthrust) integrada y registrando en caja negra
- Duración de orden: 300s (5m)
- Caja negra en SQLite por día: data/db/trade_journal-YYYY-MM-DD.db
- Stop-loss de sesión desactivado para entrenamiento (flag interno)

## Estructura relevante

- main.py: entrada principal (CLI + loop)
- src/consolidation_bot.py: motor central
- src/entry_scorer.py: scoring y selección de candidatos
- src/strategy_spring_sweep.py: detección STRAT-B
- src/trade_journal.py: persistencia de caja negra
- documentacion/: documentación técnica
- aprendizaje/: flujo de entrenamiento y mejora
- lab/: scripts de análisis offline

## Setup rápido (Windows PowerShell)

1. cd c:\Users\v_jac\Desktop\QUOTEX - segunda estrategia
2. python -m venv .venv
3. .\.venv\Scripts\Activate.ps1
4. pip install --upgrade pip
5. pip install -r requirements.txt

## Variables requeridas en .env

- QUOTEX_EMAIL
- QUOTEX_PASSWORD

## Ejecución

- Un ciclo: python main.py --once
- Loop continuo: python main.py
- Cuenta real: python main.py --real
- HUB solo monitoreo (sin órdenes): python main.py --hub-readonly

## Parámetros útiles (CLI)

- --min-payout 80
- --cycle-ops 5
- --cycle-wins 2
- --cycle-profit-pct 0.10
- --strat-b-live
- --strat-b-min-confidence 0.70
- --same-asset-cooldown-sec 65
- --structure-entry-lock-ttl-min 180

## Flujo de aprendizaje recomendado

1. Ejecutar sesión de entrenamiento
2. Exportar métricas: .venv\Scripts\python.exe aprendizaje\scripts\exportar_metricas_aprendizaje.py
3. Revisar caja negra: .venv\Scripts\python.exe lab\full_session_review.py
4. Revisar A/B: .venv\Scripts\python.exe lab\black_box_stratb.py
5. Exportar velas: .venv\Scripts\python.exe lab\dump_candidate_candles.py
6. Archivar sesión: powershell -ExecutionPolicy Bypass -File aprendizaje\scripts\cerrar_sesion_aprendizaje.ps1
