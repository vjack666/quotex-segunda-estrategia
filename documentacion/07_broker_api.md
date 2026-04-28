# 07 — Integración con el Broker (pyquotex)

## Librería: pyquotex

**Versión:** 1.0.3  
**Módulo utilizado:** `pyquotex.stable_api` → clase `Quotex`

pyquotex es una librería no oficial que implementa el protocolo WebSocket de la plataforma Quotex. Permite autenticarse, consultar activos y colocar órdenes de opciones binarias de forma programática.

---

## Autenticación y Sesión

### Credenciales

Se leen del archivo `.env` en la carpeta raíz:

```
QUOTEX_EMAIL=tu@email.com
QUOTEX_PASSWORD=tupassword
```

**Nunca deben estar en el código fuente ni en commits.**

### Persistencia de Sesión

pyquotex guarda el token de autenticación en `sessions/session.json`. En arranques posteriores usa este token sin re-autenticar, acelerando la conexión. Si el token expira, vuelve a hacer login automáticamente.

### Proceso de Conexión

```python
client = Quotex(email=EMAIL, password=PASSWORD)
ok, reason = await client.connect()
# ok = True si conexión exitosa
# reason = string con error si falla

await client.change_account("PRACTICE")  # o "REAL"
```

### Manejo de Cloudflare 403

Quotex usa protección Cloudflare que puede bloquear conexiones nuevas con un "challenge 403". El bot detecta este caso:

```python
if "403" in reason_txt or "cloudflare" in reason_txt.lower():
    await asyncio.sleep(CF_403_BACKOFF_SEC)  # 8 segundos
    # reintentar
```

---

## Operaciones WebSocket

### Verificar Conexión Activa

```python
is_connected = await client.check_connect()
# True si el WebSocket está vivo
```

Usado en `ensure_connection()` al inicio de cada ciclo del loop 24/7.

### Obtener Lista de Instrumentos

```python
instruments = await client.get_instruments()
# Lista de listas. Campos relevantes:
#   [1]  = symbol (str)    ej: "EURUSD_otc"
#   [14] = is_open (bool)  si el activo está disponible para operar
#   [18] = payout (int)    porcentaje de ganancia (ej: 85 = 85%)
```

### Obtener Velas Históricas

```python
raw_list = await client.get_candles(
    asset,        # str: "EURUSD_otc"
    end_time,     # float: timestamp Unix del final
    offset,       # int: rango en segundos (count × period)
    tf_sec,       # int: periodo en segundos (60, 300, 3600...)
)
# Retorna lista de dicts: {time, open, high, low, close}
```

El bot usa un wrapper con timeout y reintentos:

```python
await fetch_candles_with_retry(client, asset, tf_sec, count, timeout_sec, retries=2)
```

### Obtener Balance

```python
balance = await client.get_balance()
# float: balance actual en USD de la cuenta activa (PRACTICE o REAL)
```

---

## Colocación de Órdenes

### Función `client.buy()`

```python
status, info = await client.buy(
    amount=1.00,       # float: monto a invertir en USD
    asset="EURUSD_otc", # str: símbolo del activo
    direction="call",   # str: "call" o "put"
    duration=120,       # int: duración en SEGUNDOS
)
```

### Respuestas del Broker

| `status` | `info` | Interpretación |
|---|---|---|
| `True` | `dict` con `id`, `openPrice`, `id_number`... | Orden aceptada correctamente |
| `False` | `None` y tardó ≥ 20s | Probable timeout de confirmación WebSocket |
| `False` | `dict` con `info=expiration` | Duración no válida para ese activo |
| `False` | Otro | Error duro del broker (activo cerrado, saldo insuficiente...) |

### Duraciones Válidas

Quotex solo acepta durations en valores específicos: **60, 120, 180, 240, 300 segundos**.

El bot usa exclusivamente `duration=120` (2 minutos). Usar otros valores causa rechazo inmediato con `info=expiration`.

### Identificadores de Orden

Al recibir la respuesta, el bot extrae dos identificadores:

```python
# ID de string (formato UUID o similar)
order_id = info.get("id", "")

# ID numérico (más estable para check_win)
order_ref = int(info.get("id_number") or info.get("idNumber") or
                info.get("openOrderId") or info.get("ticket") or 0)
```

`order_ref` (entero) es preferido para consultar resultados porque `check_win()` lo acepta directamente.

---

## Consulta de Resultado

### Por ID Numérico (preferido)

```python
win_val = await client.check_win(order_ref)
# Retorna float (profit, ej: 0.85) si ganó
#         float negativo si perdió
#         bool True/False en algunas versiones
```

### Por ID String

```python
status, payload = await client.get_result(order_id)
# status = "win" | "loss" | None
# payload = dict con "profitAmount" u otros campos
```

---

## Reconexión Automática en Órdenes

Antes de cada `client.buy()`, el bot verifica y reconecta si es necesario:

```python
async def _ensure_connected() -> bool:
    try:
        if await client.check_connect():
            return True
    except Exception:
        pass
    ok, reason = await client.connect()
    if ok:
        await client.change_account(account_type)
        return True
    return False
```

Esto previene el fallo "orden enviada a socket cerrado" que resultaba en timeouts de 125+ segundos.

---

## Reconexión en Loop 24/7

`ensure_connection()` corre antes de cada ciclo de escaneo:

```python
for attempt in range(1, HEALTHCHECK_RECONNECT_RETRIES + 1):
    ok, reason = await client.connect()
    if ok:
        await client.change_account(account_type)
        return True
    if "403" in reason:
        await asyncio.sleep(CF_403_BACKOFF_SEC)
    else:
        await asyncio.sleep(2.0)
return False
```

Si no puede reconectarse: el ciclo de escaneo se salta (`continue`) y reintenta en 5 segundos.

---

## Cierre Limpio

```python
try:
    await client.close()
except Exception:
    pass
```

Se llama en el bloque `finally` del `main()`, garantizando que el WebSocket se cierra correctamente al hacer Ctrl+C o al activarse el stop-loss de sesión.

---

## Puntos de Atención

### No enviar órdenes con tipos incorrectos

pyquotex es sensible a tipos:
- `amount` debe ser `float`, no `int`
- `duration` debe ser `int` en la lista de válidos

### No asumir que `info` es siempre un dict

Cuando hay timeout de WebSocket, `info` puede llegar como `None`. El código siempre valida:
```python
if status and isinstance(info, dict):
```

### No usar `asyncio.wait_for` alrededor de `client.buy()`

Experiencia aprendida: envolver `client.buy()` con un timeout local (ej: 25s) causa cancelación de la corutina mientras el broker ya está procesando la orden. El resultado es que el trade se abre en Quotex pero el bot no lo registra. La solución es dejar que `client.buy()` espere sin límite de tiempo local.
