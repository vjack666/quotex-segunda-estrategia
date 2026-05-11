# QUOTEX Trading System

Bot asyncio 24/7 para operar activos OTC en Quotex con estrategias independientes,
martingala por contexto aislado, GaleWatcher en hilo dedicado y caja negra SQLite por día.

---

## Estrategias activas

| ID | Nombre | Duración | Estado |
|----|--------|----------|--------|
| STRAT-A | Consolidación (techo/piso en 5 min) | 300 s | **Opera** |
| STRAT-B | Spring / Upthrust (sweep de liquidez) | 300 s | Implementada, deshabilitada por configuración runtime de `main.py` |

### STRAT-A — Consolidación
- Escanea activos OTC y aplica filtros operativos del runtime.
- Detecta consolidación en M5: mínimo 15 velas dentro del rango, ancho máximo 0.3 %.
- Entra en techo (PUT) o piso (CALL) cuando el precio llega a la zona.
- Usa pre-validación OLD (`_pre_validate_entry`) con vetos binarios antes de `_enter()`.
- Bloqueo de re-entrada en la misma estructura: 180 min (configurable).

### STRAT-B — Spring / Upthrust
- Detecta barridos de liquidez en zonas de estructura.
- Tiene path de ejecución implementado en `consolidation_bot.py`.
- En estado actual, `main.py` fuerza `STRAT_B_CAN_TRADE = False` en `_apply_runtime_config()`.

---

## Martingala y gestión de capital

- `MartingaleCalculator` (src/martingale_calculator.py): calcula la inversión siguiente
  en base al saldo actual, objetivo de incremento y máximo de entradas consecutivas (4).
- **Contexto aislado por estrategia+activo**: cada par (estrategia, activo) tiene su
  propia instancia de calculadora para que una pérdida en EURUSD no contamine la secuencia
  de GBPUSD. El martin anticipado usa siempre el calculador del contexto correcto.
- Monto mínimo: `$1.01` (broker exige estrictamente > $1.00).
- GaleWatcher (`mg/mg_watcher.py`): hilo independiente que monitorea la operación abierta,
  consulta precio cada 1 s y dispara el gale exactamente 3 s antes del cierre si va perdiendo.

---

## Arquitectura

```
main.py                      ← Entrada CLI, configuración de runtime, lanzador de monitores
src/
  consolidation_bot.py       ← Motor central (STRAT-A, B), place_order, GaleWatcher bridge
  entry_scorer.py            ← Scoring de candidatos STRAT-A
  candle_patterns.py         ← Patrones de vela (rechazo, doji, envolvente…)
  strategy_spring_sweep.py   ← Detección STRAT-B
  martingale_calculator.py   ← Calculadora de martingala con contexto aislado
  trade_journal.py           ← Registro de operaciones (SQLite trade_journal)
  black_box_recorder.py      ← Caja negra completa (SQLite black_box_strat)
  hub_strategy_monitor.py    ← Monitores externos (consolas separadas)
  smc_analysis.py            ← Análisis SMC auxiliar
mg/
  mg_watcher.py              ← GaleWatcher (hilo dedicado)
hub/
  hub_dashboard.py           ← Panel HUB (render live/static)
  hub_models.py              ← HubState, modelos de datos del panel
data/
  db/                        ← trade_journal-YYYY-MM-DD.db, black_box_strat-YYYY-MM-DD.db
  logs/bot/                  ← consolidation_bot-YYYY-MM-DD.log
  hub_runtime_state.json     ← Snapshot en vivo para los monitores A/B/C
Documentos/                  ← Documentación técnica detallada y roadmap
aprendizaje/                 ← Scripts de entrenamiento y archivo de sesión
src/lab/                     ← Análisis offline y scripts de diagnóstico
```

### Detalles críticos de implementación

- **GaleWatcher bridge**: `_run_on_main_loop_bounded` delega corrutinas del hilo GaleWatcher
  al event loop principal vía `asyncio.run_coroutine_threadsafe`. Si el bridge supera el timeout
  (`GALE_BRIDGE_PRICE_TIMEOUT_SEC = 2.2 s`), cancela el `concurrent.futures.Future` para evitar
  acumulación de tareas huérfanas que congelen el loop.
- **Reset de flags pyquotex**: si `buy()` expira en 30 s, se resetean
  `ssl_Mutual_exclusion` y `ssl_Mutual_exclusion_write` para desbloquear el spin-lock interno
  de la librería y permitir el siguiente `buy()` sin reconectar.
- **Caja negra SQLite**: tablas `scans`, `scan_candidates`, `strategy_metrics`, `phase_log`.
  Rotación diaria automática. Retención de archivos: 31 días.

---

## Setup rápido (Windows PowerShell)

```powershell
cd "C:\Users\v_jac\Desktop\QUOTEX - segunda estrategia"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install --upgrade pip
pip install -r requirements.txt
```

## Variables requeridas en `.env`

```
QUOTEX_EMAIL=tu@email.com
QUOTEX_PASSWORD=tupassword
```

---

## Ejecución

| Comando | Descripción |
|---------|-------------|
| `python main.py` | Loop continuo (DEMO) |
| `python main.py --once` | Un solo ciclo y salir |
| `python main.py --real` | Loop en cuenta REAL ⚠️ |
| `python main.py --hub-readonly` | Solo monitoreo, sin órdenes |
| `python main.py --no-hub-multi-monitor` | Sin consolas de monitor A/B/C |

## Parámetros CLI principales

```
Gestión de capital
  --amount-initial 1.01          Monto mínimo de orden (broker: > $1.00)
  --amount-martin 2.0            Incremento objetivo por ciclo
  --max-loss-session 0.20        Stop-loss de sesión (fracción del saldo)
  --cycle-ops 5                  Máximo de operaciones por ciclo
  --cycle-wins 2                 Objetivo de aciertos por ciclo
  --cycle-profit-pct 0.10        Take-profit por ciclo (fracción)

Filtros operativos
  --min-payout 85                Payout mínimo que aplica `main.py` sobre runtime
  --scan-lead-sec 35.0           Anticipación del scan antes del open de vela
  --same-asset-cooldown-sec 65   Cooldown entre entradas al mismo activo

STRAT-A
  --adaptive-threshold-base 50   Umbral base aplicado por CLI en runtime
  --adaptive-threshold-low 48    Umbral bajo dinámico
  --adaptive-threshold-high 54   Umbral alto dinámico
  --structure-entry-lock-ttl-min 180
```

## Estado de Validación (actual)

- OLD es autoridad única de ejecución.
- NEW está integrado como observador shadow (sin autoridad live).
- Existe instrumentación de shadow runtime y pack de observación en `src/lab/`.
- La validación estadística formal NEW vs OLD todavía no es concluyente.
- Antes de cualquier promoción de NEW, revisar `Documentos/files/ESTADO_REAL_SISTEMA.md`.

---

## Análisis y flujo de aprendizaje

```powershell
# Parser de métricas runtime shadow
.venv\Scripts\python.exe src\lab\shadow_log_parser.py --log bot_stdout.txt --json-out data\exports\shadow_runtime_summary.json --csv-out data\exports\shadow_runtime_summary.csv

# Reconciliación de integridad shadow
.venv\Scripts\python.exe src\lab\shadow_reconcile.py --db data\db\trade_journal-YYYY-MM-DD.db --json-out data\exports\shadow_reconcile_report.json

# Auditoría de overhead runtime
.venv\Scripts\python.exe src\lab\shadow_overhead_audit.py --parser-json data\exports\shadow_runtime_summary.json --db data\db\trade_journal-YYYY-MM-DD.db --json-out data\exports\shadow_overhead_report.json
```
