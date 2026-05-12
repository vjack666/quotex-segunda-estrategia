# AUDITORÍA TÉCNICA: AISLAMIENTO DEL CUELLO BOTELLA
## Ejecución: Run 3 (5 min controlado) + Histórico

---

## 📊 MÉTRICAS DE EJECUCIÓN

### Run 3 (17:16-17:17 UTC)
- **Ciclos de escaneo:** 3
- **Candidatos creados:** 0
- **Nuevas entradas:** 0
- **DB delta:** CERO (seguía en 5 candidates, 4 shadow)
- **HTF cache:** 22 activos disponibles (estado OK)
- **Trades abiertos:** 0

### Histórico acumulado
- **Total runs:** 5+ desde 08:31
- **Total candidates lifetime:** 5
- **Total ganancias:** 0W/0L
- **Balance:** $56.04 (sin cambios en runs recientes)

---

## 🔴 HALLAZGO CRÍTICO: CANDLE FETCH RETURNS ZERO

### Evidencia en bot_stdout.txt:
```
[DEBUG-SCAN] 30. Got 0 1m candles for DOTUSD_OTC
[DEBUG-SCAN] 27. Got 0 candles for EURCHF_OTC
[DEBUG-SCAN] 27. Got 0 candles for LINUSD_OTC
```

**Interpretación:** El sistema está escaneando activos pero **el cliente Quotex está devolviendo arrays de velas vacíos**. Sin velas:
- ❌ No hay consolidation detection
- ❌ No hay signal detection (STRAT-A/B)
- ❌ No hay candidates creados
- ❌ No hay scoring
- ❌ No hay entradas posibles

### Ubicación del cuello:
**TIER 2 (Candle Fetch) → retornando [] cuando debería retornar 30-50 velas**

---

## 🔍 ANÁLISIS POR TIER

### Tier 1: Asset Discovery ✅
- **Estado:** OK
- **Métricas:** 22-32 activos/ciclo
- **Fuente:** HTF biblioteca funcional
- **Problema:** NINGUNO

### Tier 2: Candle Fetch ❌ **CUELLO**
- **5m candles:** fetch_5m_limited() retorna [] frecuentemente
- **1m candles:** fetch_1m_limited() retorna [] frecuentemente
- **Estado cliente:** Desconocido (posible reconexión/timeout)
- **Problema:** **CRÍTICO - Sin velas, sin signals**

### Tier 3: Signal Detection ❌ **CONSECUENCIA**
- **Estado:** No se ejecuta (sin velas = no hay consolidation)
- **STRAT-A candidates:** 0 en últimos ciclos
- **STRAT-B signals:** Insuficientes datos 1m
- **Problema:** Cascada de Tier 2

### Tier 4: Scoring ❌ **CONSECUENCIA**
- **Estado:** Sin candidatos = sin scoring
- **Problema:** Secuencial de Tier 3

### Tier 5: Pre-validation Gates ❌ **CONSECUENCIA**
- **Estado:** Sin candidatos = sin gates
- **Problema:** Secuencial de Tier 4

### Tier 6: Entry ❌ **CONSECUENCIA**
- **Trades:** 0 abiertos
- **Problema:** Cascada final

---

## 🧮 RATIO DE FILTRADO REAL

```
Activos escaneados:        32/ciclo
├─ Fetches 5m exitosos:     ~0 (PROBLEMA)
├─ Fetches 1m exitosos:     ~0 (PROBLEMA)
├─ Consolidation detected:  0
├─ Candidates creados:      0
├─ Candidates scored:       0
├─ Candidates pre-validate: 0
├─ Candidates entered:      0
└─ Win/Loss:                0W/0L
```

**Eficiencia pipeline:** 32 → 0 (0% conversion)
**Cuello dominante:** Tier 2 (Candle Fetch)

---

## 💡 ROOT CAUSE ANALYSIS

### Hipótesis Principal:
El cliente Quotex está devolviendo arrays vacíos debido a:

1. **Problema de reconexión:**
   - Cliente se desconectó silenciosamente
   - fetch_candles_with_retry() llama a client sin validar conexión

2. **Timeout en WebSocket:**
   - Respuesta de candles nunca llega
   - Timeout_sec expira sin resultado
   - Retorna [] en lugar de excepción

3. **Mismatch de símbolos:**
   - Los símbolos OTC que el HTF cache reporta
   - No son idénticos a los que el cliente puede consultar
   - "DOTUSD_OTC" vs formato alternativo

4. **Rate limiting o throttling:**
   - Broker bloqueó fetches por concurrencia
   - Semaphore CANDLE_FETCH_CONCURRENCY se quedó esperando

### Evidencia que falta:
- ❓ Estado de reconexión del cliente
- ❓ Errores del WebSocket
- ❓ Timeouts reportados en logs
- ❓ Validación pre-fetch de conexión

---

## 📋 RECOMENDACIÓN MÍNIMA Y REVERSIBLE

### Opción A: Diagnosticar conexión (REVERSIBLE, sin refactor)

**Cambio quirúrgico en `scan_all()`:**
```python
# ANTES del primer fetch 5m:
if not await self.client.check_connection():
    log.warning("[CANDLE-FETCH] Client desconectado, skippeando ciclo")
    return

# Validar que tenemos velas para ALGÚN activo antes de continuar
candles_ok = await self._validate_candle_fetch_health()
if not candles_ok:
    log.error("[CANDLE-FETCH] Todos los fetches devolvieron [], reconectando...")
    await self.reconnect_client(reason="candle_fetch_all_empty")
```

**Impacto:** 
- Detiene generación de 0-candidates cuando cliente está muerto
- Evita ciclos vacíos
- Mejora diagnostic

### Opción B: Aumentar concurrencia inteligente (MÁS SEGURO)

**Cambio reversible:**
```python
# Reducir CANDLE_FETCH_CONCURRENCY si está muy alto
CANDLE_FETCH_CONCURRENCY = 3  # (reduce si está en 10+)

# Agregar retry con backoff
for attempt in range(3):
    candles = await _fetch_5m_limited(sym)
    if candles:
        break
    if attempt < 2:
        await asyncio.sleep(0.5 * (attempt + 1))
```

**Impacto:** 
- Recupera fetches fallidos
- Sin cambiar lógica de trading
- Reversible: quitar retry loop

### Opción C: Cambiar source de candles (EXPERIMENTAL)

**Alternativa si Quotex WebSocket falla:**
- Usar client.get_candles() con polling en lugar de histórico
- Cachear localmente si el broker no devuelve
- Fallback a análisis con 1m si 5m falla

---

## ✅ PRÓXIMOS PASOS ORDENADOS

1. **INMEDIATO:** Activar validación de conexión
   - Agregar `client.check_connection()` pre-fetch
   - Logs de diagnóstico sin cambiar lógica

2. **CORTO PLAZO:** Implementar retry smartcontratos con backoff
   - 3 intentos con delays crecientes
   - Timeout re-evaluado

3. **MEDIO PLAZO:** Investigar estado WebSocket
   - Agregar telemetría de reconexiones
   - Medir latencia de fetch

4. **ANÁLISIS PROFUNDO:** Validar contra Quotex API
   - ¿Devuelve [] realmente o hay desconexión silenciosa?
   - ¿Hay rate limiting?

---

## 📌 CONCLUSIÓN

**El cuello NO es:** 
- ❌ Scoring demasiado estricto (score=23.6 < 25)
- ❌ HTF validation insuficiente
- ❌ Spike filters bloqueando

**El cuello ES:**
- 🔴 **Candle fetch devolviendo arrays vacíos**
- 🔴 **Sin velas = sin consolidation = sin candidates**
- 🔴 **Pipeline colapsado antes de Tier 3**

**Recomendación:** Implementar validación de conexión + retry (Opción A+B) sin refactor masivo.
