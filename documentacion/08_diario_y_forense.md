# 08 — Diario de Operaciones y Capturas Forenses

---

## Parte A: Diario de Operaciones (SQLite)

### Ubicación

```
trade_journal.db   ← en la raíz del proyecto
```

### Acceso

```python
from trade_journal import get_journal

journal = get_journal()  # singleton — una sola instancia por proceso
```

### Estructura de la Base de Datos

#### Tabla `candidates`

Cada señal evaluada por el bot queda registrada, independientemente de si se ejecutó o no.

| Columna | Tipo | Descripción |
|---|---|---|
| `id` | INTEGER PK | ID auto-incremental |
| `created_at` | TEXT | Timestamp ISO de evaluación |
| `asset` | TEXT | Símbolo del activo (`EURUSD_otc`) |
| `direction` | TEXT | `call` o `put` |
| `payout` | INTEGER | Payout del activo en % |
| `score` | REAL | Puntuación 0-100 |
| `score_compression` | REAL | Componente de compresión |
| `score_bounce` | REAL | Componente de rebote |
| `score_trend` | REAL | Componente de tendencia |
| `score_payout` | REAL | Componente de payout |
| `zone_ceiling` | REAL | Techo de la zona detectada |
| `zone_floor` | REAL | Piso de la zona detectada |
| `zone_range_pct` | REAL | Amplitud del rango (fracción) |
| `zone_bars_inside` | INTEGER | Barras dentro del rango |
| `zone_age_min` | REAL | Antigüedad de la zona en minutos |
| `candles_json` | TEXT | Últimas 20 velas en JSON |
| `decision` | TEXT | `ACCEPTED`, `REJECTED_SCORE`, `REJECTED_LIMIT`, `REJECTED_TIMING` |
| `reject_reason` | TEXT | Motivo de rechazo (si aplica) |
| `outcome` | TEXT | `PENDING`, `WIN`, `LOSS`, `EXPIRED`, `UNRESOLVED`, `DRY_RUN`, `BROKER_REJECTED`, `TIMING_SKIPPED` |
| `profit` | REAL | Ganancia neta en USD |
| `order_id` | TEXT | ID de orden del broker (string) |
| `amount` | REAL | Monto invertido en USD |
| `stage` | TEXT | `initial`, `breakout`, `martin` |
| `strategy_json` | TEXT | Snapshot JSON de los parámetros activos |
| `closed_at` | TEXT | Timestamp de cierre |

#### Tabla `expired_zones`

Registra cada vez que una zona de consolidación termina (por ruptura, tiempo, etc.).

| Columna | Tipo | Descripción |
|---|---|---|
| `id` | INTEGER PK | ID auto-incremental |
| `expired_at` | TEXT | Timestamp de expiración |
| `asset` | TEXT | Símbolo del activo |
| `expiry_reason` | TEXT | `BROKEN_ABOVE`, `BROKEN_BELOW`, `TIME_LIMIT`, otro |
| `ceiling` | REAL | Techo de la zona |
| `floor` | REAL | Piso de la zona |
| `range_pct` | REAL | Amplitud del rango |
| `bars_inside` | INTEGER | Barras que estuvieron dentro |
| `age_min` | REAL | Tiempo que la zona estuvo activa |
| `last_close` | REAL | Precio de cierre de la vela que cerró la zona |
| `break_body` | REAL | Tamaño del cuerpo de la vela de ruptura |
| `payout` | INTEGER | Payout del activo |

#### Tabla `entry_timing`

Telemetría de cada intento de entrada con datos de sincronización.

| Columna | Tipo | Descripción |
|---|---|---|
| `id` | INTEGER PK | — |
| `candidate_id` | INTEGER FK | Referencia a `candidates.id` |
| `logged_at` | TEXT | Timestamp |
| `time_since_open_sec` | REAL | Segundos transcurridos desde apertura de vela |
| `secs_to_close_sec` | REAL | Segundos restantes para cierre de vela |
| `duration_sec` | INTEGER | Duración usada para la orden |
| `timing_decision` | TEXT | `ACCEPT_IN_CANDLE`, `REJECT_LAST_MINUTE`, `SYNC_DISABLED` |

---

### Operaciones del Journal

#### Registrar candidato

```python
cid = journal.log_candidate(
    entry,              # CandidateEntry
    decision="ACCEPTED",
    amount=1.25,
    stage="initial",
    outcome="PENDING",
    strategy=bot._strategy_snapshot(),
)
# Retorna: int (ID de la fila en candidates)
```

#### Registrar zona expirada

```python
expired_zone_id = journal.log_expired_zone(
    asset=sym,
    expiry_reason="BROKEN_ABOVE",
    ceiling=zone.ceiling,
    floor=zone.floor,
    ...
)
# Retorna: int (ID para incluir en el nombre del archivo forense)
```

#### Actualizar resultado

```python
journal.update_outcome_by_id(row_id=trade.journal_id, outcome="WIN", profit=0.85)
# o
journal.update_outcome(order_id="abc-123", outcome="LOSS", profit=-1.00)
```

#### Reporte de rendimiento

```bash
python -m trade_journal        # reporte completo
python -m trade_journal 7      # últimos 7 días
```

---

## Parte B: Capturas Forenses (vela_ops/)

### Propósito

Cuando el precio **rompe** una zona de consolidación con fuerza (`BROKEN_ABOVE` o `BROKEN_BELOW`), el sistema guarda un snapshot forense completo del evento para análisis offline posterior.

Esto permite responder: **¿Qué pasó después de la ruptura?** — validar si la entrada fue acertada y calibrar los parámetros.

### Ubicación

```
data/vela_ops/
  YYYYMMDD_HHMMSS_ASSET_REASON_ID.json
```

Ejemplo de nombre:
```
20260421_143022_EURUSD_otc_BROKEN_ABOVE_47.json
```

### Estructura del JSON

```json
{
  "event_type": "BROKEN_ZONE",
  "saved_at": "2026-04-21T14:30:22-03:00",
  "asset": "EURUSD_otc",
  "reason": "BROKEN_ABOVE",
  "expired_zone_id": 47,
  "payout": 87,

  "zone": {
    "ceiling": 1.08425,
    "floor": 1.08380,
    "range_pct": 0.000415,
    "bars_inside": 16,
    "age_min": 12.3
  },

  "trigger_candle_5m": {
    "ts": 1745253000,
    "open": 1.08410,
    "high": 1.08465,
    "low": 1.08405,
    "close": 1.08460,
    "body": 0.00050
  },

  "analysis_1m": {
    "target_window": { "pre": 40, "post": 40 },
    "pre_40":  [ ... 40 velas 1m anteriores al evento ... ],
    "post_40_initial": [ ... velas 1m disponibles en el momento ... ]
  },

  "candles_1m_used": [ ... últimas 60 velas 1m ... ],
  "candles_5m_zone_context": [ ... últimas 24 velas 5m ... ],

  "followup": {
    "delay_sec": 900,
    "requested_candles_1m": 40,
    "status": "pending" | "saved" | "error",
    "saved_at": null | "ISO timestamp",
    "candles_1m": [ ... 40 velas 1m capturadas 15 min después ... ],
    "error": null | "mensaje de error"
  }
}
```

### Follow-up Asíncrono (15 minutos después)

Al guardar el snapshot inicial, se programa una tarea asyncio:

```python
def _schedule_followup_capture(asset, capture_file):
    task = asyncio.create_task(
        _capture_followup_after_delay(asset, capture_file)
    )
```

La tarea:
1. Espera `BROKEN_FOLLOWUP_DELAY_SEC = 900` segundos (15 minutos)
2. Descarga `BROKEN_FOLLOWUP_1M_COUNT = 40` velas de 1m
3. Actualiza el JSON con las velas post-evento y cambia `status` a `"saved"`

Esto proporciona el patrón **40/40** (40 velas pre-evento + 40 velas post-evento) para análisis estadístico offline.

---

### Análisis Offline del Patrón 40/40

Con los archivos en `data/vela_ops/` se puede ejecutar análisis estadístico:

**¿Qué preguntas responde?**
- Después de una ruptura por arriba (BROKEN_ABOVE), ¿cuántas veces el precio siguió subiendo en los próximos 40 minutos?
- ¿Cuál es el retroceso promedio post-ruptura?
- ¿El cuerpo de la vela de ruptura predice la magnitud del movimiento posterior?

**Estructura de datos disponible por evento:**
- 40 velas 1m previas a la ruptura
- Vela 5m que causó la ruptura (con cuerpo, rango, posición relativa)
- Zona de consolidación original (techo, piso, amplitud, antigüedad)
- 40 velas 1m posteriores a la ruptura

---

### Snapshot de Parámetros Activos

Cada candidato registrado en el journal incluye en `strategy_json` un snapshot de todos los parámetros operativos al momento de la señal:

```json
{
  "tf_sec": 300,
  "min_consolidation_bars": 12,
  "max_range_pct": 0.003,
  "duration_sec": 120,
  "score_threshold": 62,
  "volume_multiplier": 1.2,
  "cycle_id": 3,
  "cycle_wins": 1,
  ...
}
```

Esto permite reproducir exactamente las condiciones en las que se tomó cada decisión, incluso si los parámetros cambiaron después.
