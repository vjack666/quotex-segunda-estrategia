# 05 — Flujo de Datos: De Inicio a Fin

Este documento describe el camino completo que recorre el sistema desde que se lanza hasta que se registra el resultado de un trade.

---

## Etapa 0: Arranque (`main.py`)

```
python main.py [--loop] [--real] [--amount-initial 2.0] ...
```

1. `_build_parser()` → define todos los argumentos disponibles con defaults
2. `_apply_runtime_config(args)` → sobrescribe constantes en `consolidation_bot` module:
   - `cb.AMOUNT_INITIAL`, `cb.AMOUNT_MARTIN`, `cb.MAX_LOSS_SESSION`
   - `cb.CYCLE_MAX_OPERATIONS`, `cb.CYCLE_TARGET_WINS`
   - `cb.STRAT_B_CAN_TRADE`, `cb.STRAT_B_DURATION_SEC`
3. `asyncio.run(_run(args))` → inicia el event loop de asyncio

---

## Etapa 1: Conexión al Broker

**Función:** `connect_with_retry(client)` → máximo 3 intentos

```
intento 1: client.connect()
  ├── OK → continuar
  ├── Error 403/Cloudflare → esperar 8s → reintentar
  └── Otro error → esperar 1.5s → reintentar

Éxito → client.change_account("PRACTICE" | "REAL")
Fallo (3 intentos) → sys.exit(1)
```

**Datos de sesión:** pyquotex guarda tokens en `sessions/session.json` para evitar re-autenticar en cada arranque.

---

## Etapa 2: Inicialización

```python
# Balance inicial de sesión
bal = await client.get_balance()          # WebSocket request
bot.set_session_start_balance(bal)        # Fija referencia para drawdown

# Reconciliación de pendientes
await bot.reconcile_pending_candidates()  # Resuelve trades PENDING del pasado
```

### Reconciliación de Pendientes

Si el bot se detuvo abruptamente con trades abiertos, al arrancar consulta en la BD todos los candidatos con `outcome='PENDING'` y `decision='ACCEPTED'`, e intenta resolver su resultado con el broker. Si no puede → marca como `UNRESOLVED`.

---

## Etapa 3: Loop Principal

En modo `--loop`, el bot corre indefinidamente:

```
while True:
    1. Verificar conexión WebSocket (ensure_connection)
    2. scan_all()            ← ciclo de análisis y trading
    3. log_stats()           ← métricas de sesión
    4. sleep_with_inline_countdown(60s)  ← espera con contador visible
```

El intervalo entre ciclos es de `SCAN_INTERVAL_SEC = 60 segundos`. No se alinea al reloj de vela por defecto (`ALIGN_SCAN_TO_CANDLE = False`).

---

## Etapa 4: `scan_all()` — El Ciclo Central

Esta es la función más importante. Su flujo completo:

### 4.1 — Refresh de Balance y Stop-Loss

```python
await self.refresh_balance_and_risk()
# Si drawdown ≥ 20% → session_stop_hit = True → loop se detiene
```

### 4.2 — Obtener Activos Disponibles

```python
assets = await get_open_assets(client, MIN_PAYOUT=80)
# Lista de (symbol, payout) filtrada:
#   - Solo activos _otc
#   - Solo activos is_open = True
#   - Solo payout ≥ 80%
#   - Ordenada de mayor a menor payout
```

Internamente llama a `client.get_instruments()` que devuelve la lista completa de la plataforma.

### 4.3 — Revisión de Martingalas Activas

```python
for sym in list(self.trades.keys()):
    await self._check_martin(sym)
```

Si hay trades abiertos del ciclo anterior, evalúa si corresponde activar la martingala.

### 4.4 — Descarga Paralela de Velas

Para cada activo, se lanzan **simultáneamente** dos tareas asyncio:

```python
# Semáforo limita a CANDLE_FETCH_CONCURRENCY = 8 descargas simultáneas
fetch_sem = asyncio.Semaphore(8)

candles_tasks   = {sym: task(fetch 5m con retry)} para cada activo
candles_1m_tasks = {sym: task(fetch 1m con retry)} para cada activo
```

Todos los tasks se crean al mismo tiempo pero el semáforo garantiza que no haya más de 8 requests simultáneos al broker, evitando timeouts masivos.

### 4.5 — Procesamiento por Activo

Para cada `(sym, payout)` en la lista:

```
A) Esperar resultado fetch 5m:    candles = await candles_tasks[sym]
B) Esperar resultado fetch 1m:    candles_1m = await candles_1m_tasks[sym]

C) STRAT-B: detect_spring_sweep(candles_1m como DataFrame)
   → Si señal + --strat-b-live + conf ≥ 0.70 → _enter() inmediato

D) STRAT-A:
   1. Verificar mínimo de barras (≥ 14)
   2. Calcular rango dinámico ATR
   3. detect_consolidation(candles, dynamic_max_range)
      → No hay zona → skip
      → Hay zona → gestionar en self.zones[sym]

   4. Guardia de contaminación: precio dentro de ±25% del rango
   5. Clasificar precio: ceiling/floor/broke_above/broke_below
   6. Si rebote → detect_reversal_pattern(candles_1m, direction)
      → Sin confirmación (fuerza < 0.50) → skip
   7. Si H1_CONFIRM_ENABLED → fetch H1 → infer_h1_trend()
      → Tendencia contradice → filtered_sensor → skip
   8. Crear CandidateEntry → score_candidate() → aplicar bonus/penalizaciones
   9. Agregar a lista de candidates

E) await asyncio.sleep(0.25)  ← throttle entre activos
```

### 4.6 — Selección del Mejor Candidato

```python
selected, rejected = select_best(candidates)
# select_best: filtra score ≥ SCORE_THRESHOLD=62
#              ordena por score descendente
#              devuelve máximo MAX_ENTRIES_CYCLE=1 por ciclo
```

- Los `rejected` se registran en el journal con `decision="REJECTED_SCORE"`
- Si `selected` está vacío → log "⛔ Ningún candidato supera umbral" → ciclo sin trade

### 4.7 — Ejecución de Entradas

```python
for winner in selected:
    # Si hay trade activo → guardar en watched_candidates
    # Si no → ejecutar
    await _enter(winner.asset, winner.direction, amount, ...)
    await sleep_with_inline_countdown(30s, "Cooldown")
```

---

## Etapa 5: `_enter()` — Envío de la Orden

```
1. _sync_to_next_candle_open()
   ├── ≤ 60s para cierre de vela → REJECTED_TIMING → return False
   └── OK → duration_sec = 120

2. log "ENTRADA[stage] CALL/PUT ASSET $amount 120s | razón"

3. place_order(client, asset, direction, amount, 120, dry_run)
   ├── _ensure_connected()   (reconecta si WebSocket caído)
   ├── client.buy(amount, asset, direction, duration=120)
   ├── status=True + info dict → extraer order_id, order_ref, open_price
   └── status=False → retry si timeout, else return False

4. TradeState guardado en self.trades[asset]
5. journal: UPDATE candidates SET order_id=? WHERE id=?

6. client.get_balance()  → log balance actualizado
```

---

## Etapa 6: Captura Forense (solo en BROKEN_*)

Cuando el precio rompe la zona con fuerza, además de entrar:

```
1. _record_broken_zone_snapshot(...)
   → Guarda JSON en data/vela_ops/YYYYMMDD_HHMMSS_ASSET_REASON_ID.json
   → Incluye: 40 velas 1m pre-evento + las disponibles post-evento + contexto 5m

2. _schedule_followup_capture(asset, capture_file)
   → Crea tarea asyncio que espera 15 minutos
   → Luego descarga 40 velas 1m post-evento y actualiza el JSON
```

Este mecanismo permite análisis forense offline para validar la calidad del patrón 40/40.

---

## Etapa 7: Monitoreo del Trade Abierto

En el siguiente ciclo de `scan_all()`, el activo con trade abierto se detecta en el paso de martingalas:

```python
_check_martin(sym):
  elapsed = now - trade.opened_at

  Si elapsed < 120s → aún en primer minuto → no hacer nada
  Si elapsed ≥ 120s AND precio rompió zona en contra con fuerza:
    → activar martingala (PUT dinámico o CALL dinámico)
  Si elapsed > duration_sec + 90s:
    → trade expirado → _resolve_trade(trade, sym)
```

---

## Etapa 8: Resolución del Trade

**Función:** `_resolve_trade(trade, sym)`

```
Consulta resultado al broker:
  Si tiene order_ref (numérico) → client.check_win(order_ref)
    → retorna float (profit) o bool
  Sino → client.get_result(order_id)
    → retorna ("win"|"loss", payload_dict)

Determina outcome: "WIN" | "LOSS" | "EXPIRED"

Actualiza journal:
  journal.update_outcome_by_id(row_id, outcome, profit)

Actualiza balance:
  await refresh_balance_and_risk()

Actualiza ciclo matemático:
  _update_cycle_after_result(outcome, profit)

Actualiza estado de compensación:
  WIN → compensation_pending = False
  LOSS → compensation_pending = True, last_closed_amount = trade.amount

Elimina de self.trades[sym]
```

---

## Etapa 9: Gestión del Ciclo Matemático

Tras cada resultado, `_update_cycle_after_result()` verifica 4 condiciones de reinicio:

1. **Balance creció ≥ 10%** desde el inicio del ciclo → reinicio "objetivo +10% cumplido"
2. **2 wins acumulados** en el ciclo → reinicio "objetivo 2W cumplido"
3. **6 operaciones completadas** → reinicio "límite de 6 operaciones"
4. **Matemáticamente imposible** alcanzar 2W en los restantes → reinicio anticipado

Cada reinicio incrementa `cycle_id` y resetea los contadores del ciclo.

---

## Etapa 10: Log de Estadísticas

Al final de cada ciclo de `scan_all()`:

```
📊 STATS | Scans:N  Entradas:N  Martingalas:N  Zonas expiradas:N  
         Sin señal:N  Sensor filtradas:N  Drawdown:X%  
         Ciclo#N W/L ops:N/6  [A]:NW/NL  [B]:NW/NL
```

---

## Diagrama de Secuencia Completo

```
main.py
  │
  ├─ connect_with_retry()
  │    └─ WebSocket Quotex ←→ authenticate
  │
  ├─ get_balance()
  │
  ├─ reconcile_pending_candidates()
  │
  └─ loop:
       │
       ├─ ensure_connection()
       │
       ├─ scan_all()
       │    │
       │    ├─ refresh_balance_and_risk()  ← get_balance()
       │    │
       │    ├─ get_open_assets()           ← get_instruments()
       │    │
       │    ├─ _check_martin(trades)       ← fetch_candles_5m()
       │    │
       │    ├─ [PARALELO] fetch 5m × N activos  ← Semáforo(8)
       │    ├─ [PARALELO] fetch 1m × N activos  ← Semáforo(8)
       │    │
       │    ├─ [por activo]:
       │    │    ├─ detect_spring_sweep()  → STRAT-B log/trade
       │    │    ├─ detect_consolidation() → ConsolidationZone
       │    │    ├─ classify precio        → direction
       │    │    ├─ detect_reversal_pattern() ← candles_1m
       │    │    ├─ [fetch H1] infer_h1_trend()
       │    │    └─ score_candidate()      → CandidateEntry
       │    │
       │    ├─ select_best() → winner
       │    │
       │    └─ _enter(winner)
       │         ├─ _sync_to_next_candle_open()
       │         ├─ place_order()           ← client.buy()
       │         └─ TradeState + Journal
       │
       ├─ log_stats()
       │
       └─ sleep 60s (countdown visible)
```
