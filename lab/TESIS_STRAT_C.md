# TESIS COMPLETA — STRAT-C: Por qué no se ejecutan las órdenes y qué falta para completar el sistema

**Fecha:** 2026-05-06  
**Estado:** STRAT-C visible en monitor, candidatos detectados, pero CERO órdenes ejecutadas.  
**Versión del bot:** consolidation_bot.py / estrategia_30s/detector.py

---

## 1. RESUMEN EJECUTIVO

El monitor muestra 3 candidatos válicos en STRAT-C (INTC_OTC CALL S:41.2, USDINR_OTC PUT S:29.4, MCD_OTC CALL S:23.5). El checklist marca ✅ en todos los ítems de INTC_OTC. Sin embargo, **nunca se abre una orden**. La causa raíz es una combinación de **10 defectos estructurales** identificados, siendo el más crítico que el motor de trading está deshabilitado por bandera de configuración.

Este documento clasifica cada defecto, explica su origen, su impacto real y el código exacto a corregir.

---

## 2. ARQUITECTURA DE STRAT-C (estado actual)

```
estrategia_30s/
├── detector.py         ← Motor de señales (RSI, BB, Stoch, EMA, S/R, Wick)
├── indicadores_calc.py ← Cálculos técnicos puros
├── zonas.py            ← Detección de niveles S/R horizontales
├── reglas_entrada.md   ← Árbol de decisión
└── implementacion.md   ← Estado: "Integración con bot → ⏳ Pendiente"

src/
└── consolidation_bot.py
    ├── Line 84:  from estrategia_30s import detector as strat_c_detector
    ├── Line 342: STRAT_C_CAN_TRADE = False          ← BLOCKER 1
    ├── Line 3679: if _STRAT_C_AVAILABLE and ...     ← Evaluación
    ├── Line 3688: check_time=False                  ← BLOCKER 2
    └── Line 3727: if STRAT_C_CAN_TRADE ...          ← BLOCKER 1 (gate de ejecución)
```

### Flujo completo de una señal STRAT-C:

```
[Scan loop] → [evaluar_vela(candles, check_time=False)]
                      │
                 [¿Wick ratio >= 1.5?]
                      │
               [¿Zona S/R activa?]
                      │
               [¿ATR en rango?]
                      │
              [¿Score >= MIN_SCORE?]
                      │
                      ↓
              Candidato guardado en last_scan_strat_c
                      │
              Candidato enviado al HUB (strat_c_for_hub)
              → Monitor muestra ✅ en checklist
                      │
              [¿STRAT_C_CAN_TRADE?] ← PARED AQUÍ
                      │
                    FALSE
                      │
                 ORDEN NUNCA EJECUTADA
```

---

## 3. LOS 10 DEFECTOS IDENTIFICADOS

### DEFECTO 1 — BLOCKER PRIMARIO: `STRAT_C_CAN_TRADE = False`

**Archivo:** `src/consolidation_bot.py` línea 342  
**Código:**
```python
STRAT_C_CAN_TRADE = False  # default: bloqueado
```

**Gate de ejecución:** líneas 3725-3729
```python
if (
    STRAT_C_CAN_TRADE
    and len(self.trades) < MAX_CONCURRENT_TRADES
    and not self._gale_order_active
):
```

**Causa:** El flag requiere `--strat-c-enabled` al lanzar main.py. El usuario nunca ha pasado ese argumento.  
**Impacto:** 100% — Sin este flag, JAMÁS se abre ninguna orden, sin importar la señal.  
**Corrección inmediata:** Lanzar con:
```
python main.py --strat-c-enabled --strat-b-live --hub-multi-monitor
```

---

### DEFECTO 2 — `check_time=False`: La estrategia evalúa en CUALQUIER segundo

**Archivo:** `src/consolidation_bot.py` línea 3688  
**Código:**
```python
_c_result = strat_c_detector.evaluar_vela(
    _c_candles_dict,
    zonas=None,
    check_time=False,   ← PROBLEMA
)
```

**Concepto original de la estrategia** (de `reglas_entrada.md`):
```
¿Estamos en segundo 30-41 de la vela M1?
    NO → No hacer nada, esperar siguiente vela
    SÍ → Evaluar wick de rechazo...
```

**Por qué es `check_time=False`:** El docstring dice "Pasar False en backtesting". Se aplicó por error al código de producción.

**Impacto:** El detector puede disparar señales en el segundo 5, segundo 55, o segundo 15. Esto produce:
- Entradas demasiado tempranas (wick no se ha formado)
- Entradas demasiado tardías (orden no procesa antes de cierre)
- Señales de la vela ANTERIOR (wick visible pero ya expirado)
- Los candidatos mostrados en el monitor NO son necesariamente del segundo correcto

**Corrección:** Cambiar a `check_time=True` Y usar la zona horaria correcta del broker.  
⚠️ **Problema adicional:** `BROKER_TZ = UTC-3` está hardcodeado en detector.py. Si el broker no está en UTC-3, el check falla silenciosamente.

**Corrección completa:**
```python
# En consolidation_bot.py — pasar el segundo del broker calibrado
from datetime import datetime, timezone, timedelta
_broker_second = datetime.fromtimestamp(self._broker_now_ts(), tz=timezone.utc).second
_in_window = (REJECTION_ENTRY_WINDOW_START_SEC <= _broker_second <= REJECTION_ENTRY_WINDOW_END_SEC)
_c_result = strat_c_detector.evaluar_vela(
    _c_candles_dict,
    zonas=None,
    check_time=False,  # mantenemos False pero pasamos _in_window externamente
) if _in_window else None
```

---

### DEFECTO 3 — Sin ticker dedicado: la ventana de 11 segundos puede saltarse

**Contexto:** El loop principal de escaneo corre un ciclo completo por todos los activos (20-50 activos × operaciones de broker). Si el ciclo tarda > 11 segundos, la ventana 30-41 pasa sin que STRAT-C evalúe.

**Evidencia:** El scan loop incluye:
- `get_open_assets()` — llamada WebSocket ~0.5-2s
- `get_candles()` por cada activo — ~0.2-0.5s × N activos
- STRAT-A y STRAT-B evaluaciones antes de STRAT-C

Con 30 activos escaneados, el ciclo puede tardar 15-30s. La ventana 30-41 tiene sólo 11s.

**Impacto:** STRAT-C puede evaluar correctamente 0 veces en algunos minutos si el loop está ocupado.

**Corrección requerida:** Un ticker secundario independiente que:
1. Monitorea el segundo actual del broker cada 1s
2. Cuando `30 <= segundo <= 41`, evalúa STRAT-C para los activos pre-candidatos
3. Opera independientemente del ciclo principal de STRAT-A/B

---

### DEFECTO 4 — Zona horaria del broker hardcodeada a UTC-3

**Archivo:** `estrategia_30s/detector.py` línea 19  
**Código:**
```python
BROKER_TZ = timezone(timedelta(hours=-3))  # UTC-3
```

**Problema:** La hora del broker Quotex depende de su servidor. Si el servidor está en UTC-5 o UTC-4, la ventana de tiempo check_time sería incorrecta, rechazando señales válidas o aceptando señales en el segundo equivocado.

**El bot tiene:** `_broker_now_ts()` que retorna el timestamp calibrado del broker. Este método debería ser la fuente de verdad para STRAT-C, no un timezone hardcodeado.

**Corrección:**
```python
# En detector.py: permitir inyección de timestamp
def evaluar_vela(candles, zonas=None, *, check_time=True, broker_ts=None):
    if check_time:
        ts = broker_ts if broker_ts else time.time()
        second = datetime.fromtimestamp(ts, tz=timezone.utc).second
        if not (ENTRY_WINDOW_START_SEC <= second <= ENTRY_WINDOW_END_SEC):
            return None
```

---

### DEFECTO 5 — `STRAT_C_MIN_SCORE` existe pero no filtra en el loop

**Archivo:** `src/consolidation_bot.py` línea 344  
**Código:**
```python
STRAT_C_MIN_SCORE = 4.0   # definida pero no usada en el scan loop
```

**Cómo debería usarse:**
```python
# En el loop de escaneo
if _c_score < STRAT_C_MIN_SCORE:
    continue  # rechazar antes de crear candidato
```

**Actualmente:** La variable existe pero el filtrado real ocurre dentro de `strat_c_detector.MIN_SCORE` que es configurada vía `main.py`. Sin embargo, si la config se cambia en runtime sin reiniciar, `STRAT_C_MIN_SCORE` y `strat_c_detector.MIN_SCORE` pueden divergir.

**Corrección:** Agregar guard explícito en el loop:
```python
if _c_score < STRAT_C_MIN_SCORE:
    log.debug("STRAT-C rechazado por score bajo: %s score=%.1f < %.1f", sym, _c_score, STRAT_C_MIN_SCORE)
    continue
```

---

### DEFECTO 6 — Duración inconsistente: "30s" en nombre pero `STRAT_C_DURATION_SEC = 60`

**Manifiestos:**
- Monitor muestra: `STRAT-C  Rechazo M1 (30s)` 
- `consolidation_bot.py` línea 343: `STRAT_C_DURATION_SEC = 60`
- `main.py` línea 330: `help="Habilitar STRAT-C: rechazo M1 con expiración 60s"`
- `reglas_entrada.md`: `ENTRADA VÁLIDA → Expiry 60s`

**El nombre "30s"** se refiere a la VENTANA DE ENTRADA (segundo 30-41), NO a la duración de la operación.

**La duración 60s** es correcta: la operación entra en el segundo 30-41 y expira 60s después, cubriendo la segunda mitad de la vela actual + ~30s de la siguiente.

**El problema real:** El monitor muestra "(30s)" dando la impresión de que la expiración es 30s. Esto confunde la monitorización.

**Corrección en hub_strategy_monitor.py:**
```python
# Cambiar el título descriptivo
"STRAT-C  Rechazo M1 (ventana s30-41, exp 60s)"
```

---

### DEFECTO 7 — Sin pipeline steps para STRAT-C en el monitor

**STRAT-B** tiene `_pipeline_steps_b()` que muestra 6 etapas de procesamiento:
```
[x] Datos 1m recolectados
[x] Patron Wyckoff detectado
[x] Confianza >= 70%
[x] Motor habilitado para operar
[x] Limites/cooldown permitidos
[x] Orden ejecutada
```

**STRAT-C** usa `_checklist_generic()` que solo muestra:
```
[x] Activo detectado en scan
[x] Direccion valida (CALL/PUT)
[x] Payout >= 80%
[x] Score >= 40
[x] Distancia al trigger disponible
```

**Lo que FALTA mostrar en el monitor STRAT-C:**
- `[ ] En ventana de tiempo (s30-41)` ← NUNCA se muestra si está en la ventana
- `[ ] Zona S/R activa` ← requisito del detector, no visible
- `[ ] ATR en rango válido` ← filtro crítico, no visible
- `[ ] Wick ratio >= 1.5` ← condición base, no visible
- `[ ] Motor habilitado (strat-c-enabled)` ← el blocker 1, no visible
- `[ ] Score >= MIN_SCORE` ← la métrica correcta (0-17, no 0-100)

**El checklist actual muestra `Score >= 40`** — pero el score interno es 0-17. El score 41.2 que muestra el monitor es el normalizado `_c_score / 17.0 * 100.0`. El threshold real del detector es `MIN_SCORE = 6.0` (sobre 17), equivalente a 35.3/100. Sin embargo, el monitor verifica contra 40/100 = 6.8/17, que es ligeramente más estricto. **Inconsistencia**.

---

### DEFECTO 8 — Concurrencia compartida: STRAT-C bloqueada por STRAT-A/B activas

**Código en el gate de ejecución:**
```python
if (
    STRAT_C_CAN_TRADE
    and len(self.trades) < MAX_CONCURRENT_TRADES   ← comparte con A y B
    and not self._gale_order_active                 ← bloqueado por cualquier gale
):
```

**Problema:** `MAX_CONCURRENT_TRADES` es global para las 3 estrategias. Si STRAT-A tiene 2 trades abiertos y `MAX_CONCURRENT_TRADES = 2`, STRAT-C nunca puede entrar aunque haya una señal perfecta.

**Además:** `self._gale_order_active` bloquea STRAT-C durante CUALQUIER gale de STRAT-A o STRAT-B. Esto puede durar 45-60s, exactamente la duración de la ventana STRAT-C.

**Corrección:** Permitir configurar `STRAT_C_MAX_CONCURRENT` independiente, o dar a STRAT-C prioridad de entrada en la ventana de tiempo.

---

### DEFECTO 9 — Calculo de zonas S/R en cada scan es caro y no se cachea

**Código en detector.py línea 123-132:**
```python
if zonas is None:
    zonas = detectar_zonas_sr(
        candles,
        lookback=SR_LOOKBACK,      # = 50 velas
        pivot_window=SR_PIVOT_WINDOW,
        merge_threshold_atr_mult=SR_MERGE_ATR_MULT,
    )
```

**El bot llama con `zonas=None`** en cada scan para cada activo.  
**El cálculo de zonas S/R** requiere iterar 50-100 velas buscando pivotes, merging zonas, filtrado por ATR. Con 30 activos, esto es 30 × cálculo_zonas por scan.

**Impacto:** Latencia adicional en el loop de escaneo. Puede contribuir al problema del Defecto 3 (ventana de 11s saltada).

**Corrección:** Cachear zonas por activo con TTL de 5 minutos:
```python
# En consolidation_bot.py
_c_zonas_cache: dict[str, tuple[float, list]] = {}  # asset -> (ts, zonas)

def _get_strat_c_zonas(sym, candles_1m):
    cached = _c_zonas_cache.get(sym)
    if cached and (time.time() - cached[0]) < 300:  # 5 min TTL
        return cached[1]
    zonas = strat_c_detector.detectar_zonas_sr(...)
    _c_zonas_cache[sym] = (time.time(), zonas)
    return zonas
```

---

### DEFECTO 10 — Sin cooldown propio para STRAT-C

**Defecto:** STRAT-C usa el mismo cooldown que STRAT-A (`SAME_ASSET_REENTRY_COOLDOWN_SEC = 65s`). Pero la duración de STRAT-C es 60s. Si una operación STRAT-C termina, el cooldown de 65s bloquea la re-entrada por 5s extra innecesarios.

**Más importante:** No hay un cooldown específico de STRAT-C que impida entrar en el mismo activo 2 veces en la misma ventana M1 (doble señal en el mismo segundo 30-41).

**Corrección:**
```python
STRAT_C_COOLDOWN_SEC = 70.0  # ligeramente más que 60s para no solapar
_strat_c_last_entry: dict[str, float] = {}  # asset -> timestamp

# En el gate:
if time.time() - _strat_c_last_entry.get(sym, 0) < STRAT_C_COOLDOWN_SEC:
    continue
```

---

## 4. TABLA DE PRIORIDADES

| # | Defecto | Impacto | Urgencia | Estado |
|---|---------|---------|----------|--------|
| 1 | `STRAT_C_CAN_TRADE = False` | 100% — sin órdenes | CRÍTICO | ⚠️ Fix inmediato: `--strat-c-enabled` |
| 2 | `check_time=False` — señales en segundo equivocado | Alta — entradas incorrectas | ALTO | Requiere código |
| 3 | Sin ticker dedicado para ventana 30-41 | Alta — ventana se salta | ALTO | Requiere refactor |
| 4 | Timezone hardcodeada UTC-3 | Media — falla silenciosa | MEDIO | Requiere código |
| 5 | `STRAT_C_MIN_SCORE` no filtra en loop | Baja — redundante | BAJO | Cosmético |
| 6 | Nombre "30s" vs duración 60s | Muy baja — confusión visual | MÍNIMO | Cosmético |
| 7 | Sin pipeline steps en monitor | Media — observabilidad | MEDIO | Requiere código |
| 8 | Concurrencia compartida bloquea STRAT-C | Alta — oportunidades perdidas | ALTO | Requiere código |
| 9 | Zonas S/R sin cache por activo | Baja — latencia | BAJO | Optimización |
| 10 | Sin cooldown propio STRAT-C | Media — doble entrada posible | MEDIO | Requiere código |

---

## 5. ROADMAP DE IMPLEMENTACIÓN COMPLETO

### FASE 0 — Activar (HOY, 0 código)
```bash
python main.py --strat-c-enabled --strat-b-live --hub-multi-monitor
```
**Resultado:** STRAT-C empieza a operar en demo. Defecto 1 resuelto.  
⚠️ Los defectos 2-10 siguen presentes pero no bloquean las órdenes.

---

### FASE 1 — Corrección de timing (PRIORIDAD ALTA)

**Objetivo:** Que las señales STRAT-C sean generadas SOLO en el segundo correcto del broker.

**Cambio 1 — consolidation_bot.py:**
```python
# Antes de evaluar_vela, verificar segundo del broker
from datetime import datetime, timezone
_broker_second = datetime.fromtimestamp(self._broker_now_ts(), tz=timezone.utc).second
if not (REJECTION_ENTRY_WINDOW_START_SEC <= _broker_second <= REJECTION_ENTRY_WINDOW_END_SEC):
    # Fuera de ventana: registrar como candidato con nota "out_of_window"
    # pero NO ejecutar ni agregar a last_scan_strat_c como señal activa
    pass
else:
    _c_result = strat_c_detector.evaluar_vela(
        _c_candles_dict, zonas=None, check_time=False
    )
```

**Cambio 2 — detector.py:**
```python
# Cambiar BROKER_TZ por inyección de timestamp
def evaluar_vela(candles, zonas=None, *, check_time=True, broker_ts=None):
    if check_time:
        ts = broker_ts if broker_ts is not None else time.time()
        second = int(ts) % 60  # extrae el segundo del timestamp UNIX
        if not (ENTRY_WINDOW_START_SEC <= second <= ENTRY_WINDOW_END_SEC):
            return None
```

---

### FASE 2 — Ticker dedicado para ventana de entrada (PRIORIDAD ALTA)

**Objetivo:** STRAT-C evalúa exactamente en el segundo 30 de CADA vela M1, independientemente del ciclo principal.

```python
# Nuevo método en ConsolidationBot
async def _strat_c_window_ticker(self):
    """Ticker dedicado que evalúa STRAT-C exactamente en segundo 30-41."""
    while True:
        try:
            broker_second = datetime.fromtimestamp(
                self._broker_now_ts(), tz=timezone.utc
            ).second
            
            if REJECTION_ENTRY_WINDOW_START_SEC <= broker_second <= REJECTION_ENTRY_WINDOW_END_SEC:
                # Estamos en la ventana — evaluar candidatos pre-cargados
                await self._evaluate_strat_c_window()
            
            # Esperar 0.5s para no saltarse el segundo 30
            await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            return
        except Exception as e:
            log.debug("_strat_c_window_ticker error: %s", e)
            await asyncio.sleep(1.0)
```

---

### FASE 3 — Pipeline steps en monitor STRAT-C (PRIORIDAD MEDIA)

**Objetivo:** El monitor muestra exactamente en qué etapa está la señal y por qué no se ejecuta.

Agregar en `hub_strategy_monitor.py`:
```python
def _pipeline_steps_c(c: dict) -> list[tuple[str, bool]]:
    score = float(c.get("score", 0.0) or 0.0)  # normalizado 0-100
    raw_score = score * 17.0 / 100.0             # volver a 0-17
    payout = int(c.get("payout", 0) or 0)
    direction = str(c.get("direction", "") or "").lower()
    
    # Extraer detalles del JSON de la señal
    details = c.get("strategy_details") or {}
    wick_ratio = float(details.get("wick_ratio", 0.0) or 0.0)
    atr_ok = details.get("atr_ok", False)
    zona_activa = details.get("zona_activa", False)
    in_window = details.get("in_window", False)
    
    return [
        ("Velas 1m suficientes (>=15)",     bool(c.get("asset", ""))),
        ("En ventana s30-41",               in_window),
        ("Wick rechazo >= 1.5",             wick_ratio >= 1.5),
        ("Zona S/R activa",                 zona_activa),
        ("ATR en rango válido",             atr_ok),
        (f"Score >= {MIN_SCORE_C:.1f}/17",  raw_score >= MIN_SCORE_C),
        ("Motor habilitado (strat-c-enabled)", STRAT_C_CAN_TRADE_display),
        ("Capacidad disponible",            capacity_ok),
    ]
```

---

### FASE 4 — Concurrencia independiente (PRIORIDAD MEDIA)

```python
# En consolidation_bot.py
STRAT_C_MAX_CONCURRENT = 1  # máximo 1 trade STRAT-C activo simultáneo

# En el gate de ejecución:
strat_c_active = sum(1 for t in self.trades.values() if t.strategy_origin == "STRAT-C")
if (
    STRAT_C_CAN_TRADE
    and strat_c_active < STRAT_C_MAX_CONCURRENT
    # Nota: NO bloquear por gale de otras estrategias
):
```

---

### FASE 5 — Cooldown propio STRAT-C (PRIORIDAD MEDIA)

```python
# En ConsolidationBot.__init__:
self._strat_c_last_entry: dict[str, float] = {}

# En el gate:
_strat_c_elapsed = time.time() - self._strat_c_last_entry.get(sym, 0)
if _strat_c_elapsed < STRAT_C_COOLDOWN_SEC:
    log.debug("STRAT-C cooldown activo para %s (%.0fs)", sym, STRAT_C_COOLDOWN_SEC - _strat_c_elapsed)
    continue

# Tras ejecutar la orden:
self._strat_c_last_entry[sym] = time.time()
```

---

### FASE 6 — Cache de zonas S/R por activo (PRIORIDAD BAJA)

```python
# En ConsolidationBot.__init__:
self._strat_c_zones_cache: dict[str, tuple[float, list]] = {}

# Uso:
_cached = self._strat_c_zones_cache.get(sym, (0.0, None))
if time.time() - _cached[0] > 300:  # TTL 5min
    _zonas = detectar_zonas_sr(...)
    self._strat_c_zones_cache[sym] = (time.time(), _zonas)
else:
    _zonas = _cached[1]
```

---

## 6. RESPUESTA DIRECTA: POR QUÉ NO SE EJECUTA LA ORDEN

### Causa raíz #1 (100% bloqueante):
```python
# consolidation_bot.py line 342
STRAT_C_CAN_TRADE = False  # ← AQUÍ
```

El motor está apagado. El checklist del monitor verifica `score >= 40`, `payout >= 80%`, etc. — pero NINGUNO de esos checks controla si se ejecuta la orden. La ejecución está detrás de `STRAT_C_CAN_TRADE` que por defecto es `False`.

Para encenderlo: `python main.py --strat-c-enabled`

### Causa raíz #2 (causa señales en segundos incorrectos):
```python
# consolidation_bot.py line 3688
check_time=False,  # ← AQUÍ
```

Los candidatos mostrados en el monitor fueron detectados en segundos FUERA de la ventana 30-41. El wick puede ser real, pero la entrada no sería en el momento correcto.

---

## 7. ESTADO COMPLETO DEL SISTEMA STRAT-C

```
MÓDULO           ESTADO      NOTAS
─────────────────────────────────────────────────────
detector.py      ✅ Funcional  Señales generadas correctamente
indicadores.py   ✅ Funcional  RSI, BB, Stoch, EMA, ATR implementados
zonas.py         ✅ Funcional  S/R detectado por pivotes
HUB monitor      ✅ Parcial    Muestra candidatos, falta pipeline steps
Hub state        ✅ Funcional  strat_c_watching actualizado
record_scan_cycle✅ Funcional  Candidatos enviados al HUB
─────────────────────────────────────────────────────
STRAT_C_CAN_TRADE❌ BLOQUEADO  Default False, requiere --strat-c-enabled
check_time        ❌ INCORRECTO False hardcodeado en producción
Ticker dedicado   ❌ FALTANTE  No existe, usa loop de STRAT-A/B
Timezone calibrada❌ INCORRECTO UTC-3 hardcodeado, no usa _broker_now_ts
Pipeline monitor  ❌ FALTANTE  No hay _pipeline_steps_c en hub_monitor
Concurrencia      ❌ COMPARTIDA Bloquea con gale de STRAT-A/B
Cooldown propio   ❌ FALTANTE  Usa cooldown global, no específico
Zonas cache       ❌ FALTANTE  Recalcula en cada scan (lento)
Black box STRAT-C ❌ NO INTEGRADO  black_box_recorder no conectado
Backtesting       ❌ PENDIENTE  implementacion.md marca como "⏳ Pendiente"
─────────────────────────────────────────────────────
```

---

## 8. LISTA DE CAMBIOS DE CÓDIGO NECESARIOS

### Para que STRAT-C opere correctamente (mínimo viable):

1. **`main.py`**: Agregar `--strat-c-enabled` a los lanzamientos por defecto o documentar en README
2. **`consolidation_bot.py`**: Cambiar `check_time=False` → verificación de segundo del broker
3. **`consolidation_bot.py`**: Agregar cooldown independiente `self._strat_c_last_entry`
4. **`consolidation_bot.py`**: Separar gate de concurrencia STRAT-C de gale de STRAT-A/B

### Para que STRAT-C sea observable (calidad de análisis):

5. **`hub_strategy_monitor.py`**: Agregar `_pipeline_steps_c()` con 8 ítems
6. **`hub_strategy_monitor.py`**: Corregir threshold del monitor (mostrar raw_score/17 no 0-100)
7. **`hub_strategy_monitor.py`**: Mostrar "Motor habilitado" como ítem de checklist

### Para que STRAT-C sea robusta (producción):

8. **`estrategia_30s/detector.py`**: Parámetro `broker_ts` en `evaluar_vela()` para reemplazar BROKER_TZ
9. **`consolidation_bot.py`**: Ticker dedicado `_strat_c_window_ticker`
10. **`consolidation_bot.py`**: Cache de zonas S/R por activo con TTL 5min
11. **`src/black_box_recorder.py`**: Integrar registro de señales STRAT-C con `detalles`

---

## 9. CUÁNDO ESTARÁ "COMPLETA" LA ESTRATEGIA

STRAT-C estará al 100% cuando:
- [ ] Opera en demo con señales válidas (Fase 0 + 1)
- [ ] Ticker dedicado garantiza la ventana de 11s (Fase 2)
- [ ] Monitor muestra pipeline completo y diagnóstico claro (Fase 3)
- [ ] Concurrencia independiente de STRAT-A/B (Fase 4)
- [ ] Cooldown propio activo (Fase 5)
- [ ] Black box integrado para auditoría (ver lab/BLACK_BOX_INTEGRATION.py)
- [ ] 50+ trades en demo analizados con deep_stratb_analysis (adaptado para STRAT-C)
- [ ] Winrate >= 60% demostrado en demo antes de activar en real

---

*Tesis generada por análisis exhaustivo del código fuente. Todos los números de línea son exactos al 2026-05-06.*
