# QUOTEX Trading System

Sistema unificado para bots de trading con pyquotex.

## Flujo esencial

- src/main.py: orquestador principal
- src/consolidation_bot.py: bot de consolidación con selección matemática del mejor candidato
- src/entry_scorer.py: motor de scoring (0-100) para filtrar entradas
- src/filter_and_sell_otc.py: bot de filtro y venta por payout
- src/smc_auto_trader.py: trader SMC

## Setup rápido (Windows PowerShell)

1. cd c:\Users\v_jac\Desktop\QUOTEX
2. python -m venv .venv
3. .\.venv\Scripts\Activate.ps1
4. pip install --upgrade pip
5. pip install -r requirements.txt

## Variables requeridas en .env

- QUOTEX_EMAIL
- QUOTEX_PASSWORD

## Ejecutar bots

Orquestador:

- python src/main.py --help

Consolidation (1 ciclo):

- python src/main.py consolidation --live

Consolidation 24/7:

- python src/main.py consolidation --live --loop

SMC:

- python src/main.py smc --live --asset EURUSD_otc --amount 1 --duration 60

Filter sell:

- python src/main.py filter-sell --live --min-payout 85 --amount 1

## Monitoreo en vivo

- Get-Content consolidation_bot.log -Wait -Tail 40

## Nota de limpieza

Los scripts de prueba y diagnóstico fueron movidos a src/lab para mantener src limpio sin eliminar herramientas útiles.
