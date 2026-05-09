# Reglas de Entrada — Estrategia 30 Segundos

**Tipo:** Checklist operacional  
**Aplicar antes de cada entrada**  

---

## Estructura de decisión (árbol de condiciones)

```
¿Estamos en segundo 30-41 de la vela M1?
        │
        NO → No hacer nada, esperar siguiente vela
        │
        SÍ
        │
        ▼
¿El precio está en una zona S/R válida?
        │
        NO → Descartar. No hay zona = no hay trade.
        │
        SÍ
        │
        ▼
¿La vela M1 actual muestra wick de rechazo (ratio wick/cuerpo ≥ 1.5)?
        │
        NO → Descartar. Puede ser ruptura, no rechazo.
        │
        SÍ (parcial 1.5–3.0 o total > 3.0)
        │
        ▼
¿El puntaje de confluencia de indicadores ≥ 6?
        │
        NO → Descartar. Señal débil.
        │
        SÍ
        │
        ▼
¿ATR en rango válido (ni demasiado bajo ni demasiado alto)?
        │
        NO → Descartar. Mercado dormido o con noticia.
        │
        SÍ
        │
        ▼
ENTRADA VÁLIDA → Expiry 60s
```

---

## Regla 1 — Ventana de tiempo (OBLIGATORIA)

**Condición:** `30 ≤ segundo_actual ≤ 41`

```python
from datetime import datetime, timezone, timedelta

BROKER_TZ = timezone(timedelta(hours=-3))  # UTC-3
now = datetime.now(tz=BROKER_TZ)
second = now.second

if not (30 <= second <= 41):
    return  # fuera de ventana
```

**Justificación:** Entrar antes del segundo 30 significa que la vela aún no ha desarrollado el wick. Entrar después del segundo 41 deja menos margen para que el broker procese la operación antes de que la ventana de entrada se cierre.

---

## Regla 2 — Zona de Precio (OBLIGATORIA)

La vela debe estar tocando una zona pre-identificada. No se improvisa la zona en el momento de la entrada.

### Zonas aceptadas (por orden de prioridad)

| Prioridad | Zona | Ejemplo |
|---|---|---|
| 1 | S/R horizontal con 3+ toques | 1.09350 tocado 4 veces |
| 2 | S/R horizontal con 2 toques | 1.09200 tocado 2 veces |
| 3 | Nivel redondo (00, 50) | 1.0900, 1.0950 |
| 4 | EMA(21) como soporte/resistencia dinámica | Precio ≈ EMA21 ±0.05% |
| 5 | Banda de Bollinger (superior o inferior) | Close ≤ BB_lower |

### Tolerancia de zona
```
tolerancia = ATR(7) * 0.5
si abs(precio_actual - nivel_zona) <= tolerancia:
    zona_activa = True
```

### Zonas prohibidas
- Zona sin historia (primer toque en toda la serie)
- Zona dentro de un rango de consolidación flat (sin impulso previo)
- Zona ya "consumida" (precio la atravesó y volvió — estructura rota)

---

## Regla 3 — Wick de Rechazo (OBLIGATORIA)

### Cálculo del wick
```python
open_p = candle['open']
high_p = candle['high']
low_p  = candle['low']
close_p = candle['close']

body_size = abs(close_p - open_p)
upper_wick = high_p - max(open_p, close_p)
lower_wick = min(open_p, close_p) - low_p
```

### Clasificación
| Ratio wick/cuerpo | Clasificación | ¿Acepta entrada? |
|---|---|---|
| < 1.5 | Sin rechazo | NO |
| 1.5 – 3.0 | Rechazo parcial | SÍ (puntaje bajo) |
| > 3.0 | Rechazo total | SÍ (puntaje alto) |

### Dirección del wick
- **Wick inferior largo** + zona de soporte → señal CALL
- **Wick superior largo** + zona de resistencia → señal PUT
- **Ambos wicks largos** (doji) → señal ambigua, requiere indicadores extra

### Tamaño mínimo del wick
```python
atr = calcular_atr(candles, period=7)
if wick_size < atr * 1.0:
    return  # wick demasiado pequeño — ruido
```

---

## Regla 4 — Confluencia de Indicadores (MÍNIMO 2 adicionales)

Después de confirmar zona + wick, se verifican los indicadores. Se necesita acumulación de **6 puntos mínimo**.

### Checklist de puntuación

**ZONA Y WICK (base)**
- [ ] Zona S/R 3+ toques → +3 pts
- [ ] Zona S/R 2 toques → +2 pts
- [ ] Zona nivel redondo → +2 pts
- [ ] Wick ratio > 3.0 → +2 pts
- [ ] Wick ratio 1.5–3.0 → +1 pt

**INDICADORES CONFIRMADORES**
- [ ] RSI(7) < 25 o > 75 → +2 pts
- [ ] RSI(7) < 30 o > 70 → +1 pt
- [ ] Precio en Bollinger Band (toca la banda) → +2 pts
- [ ] Stochastic(5,3) cruce en zona extrema (< 20 o > 80) → +2 pts
- [ ] Stochastic(5,3) en zona extrema sin cruce → +1 pt
- [ ] EMA(21) coincide con zona tocada → +1 pt
- [ ] MACD rápido (3,8) confirma dirección → +1 pt
- [ ] Tendencia M5 alineada (EMA8 > EMA21 en M5 para CALL) → +1 pt

**Total posible:** ~17 puntos  
**Umbral mínimo:** 6 puntos  
**Entrada de alta confianza:** 9+ puntos  

---

## Regla 5 — Filtro ATR (OBLIGATORIA)

```python
atr = calcular_atr(candles[-10:], period=7)

ATR_MIN = 0.00005  # evitar mercados planos
ATR_MAX = 0.00030  # evitar noticias o spikes

if atr < ATR_MIN or atr > ATR_MAX:
    return  # condiciones no aptas
```

**Nota por par de activos:** Los umbrales ATR varían por activo. Los valores anteriores aplican para EUR/USD. Para pares más volátiles (GBP/JPY, XAU/USD) ajustar 3x–5x.

---

## Regla 6 — Anti-noticias (RECOMENDADA)

No entrar en las ventanas:
- **2 minutos antes** de un evento de alto impacto
- **3 minutos después** del evento

Fuentes de calendario: Forex Factory, Investing.com, DailyFX.

---

## Regla 7 — Gestión de Gale / Martingala

Esta estrategia **no incorpora gale automático por defecto**. Las razones:

1. La ventana de 30s ocurre solo una vez por vela — no hay "segunda oportunidad" en la misma zona
2. Si se pierde la operación, la zona puede haber sido rota (cambio de contexto)

**Gale permitido únicamente si:**
- La zona sigue intacta (precio no la atravesó)
- El siguiente M1 también muestra wick de rechazo en la misma zona
- Se entra de nuevo en el segundo 30 de esa siguiente vela

---

## Resumen visual de entrada válida

```
Precio M1:
          ↑ wick superior largo
  ┌───────┐
  │ vela  │  ← cuerpo pequeño
  └───────┘
          ↓ zona S/R  ←────── aquí debe estar el wick inferior

Condición ideal:
  - Segundo 30-41 ✓
  - Zona S/R con 2+ toques ✓  
  - Wick inferior / cuerpo > 1.5 ✓
  - RSI(7) < 30 ✓
  - Precio en BB inferior ✓
  - Stochastic cruce alcista en < 20 ✓
  - Score ≥ 6 ✓
  → CALL, expiry 60s
```

---

## Errores comunes que invalidan la entrada

| Error | Consecuencia |
|---|---|
| Entrar antes del segundo 30 | Wick no está completo — podría cambiar |
| Ignorar la dirección del wick | Entrar en dirección equivocada |
| Zona sin historia | Sin evidencia de respeto previo |
| Score < 6 | Alta probabilidad de fallo |
| ATR muy bajo | Precio se mueve poco — no hay impulso de rechazo |
| Noticia en ventana | Spike imprevisible anula el setup |
| Zona ya rota previamente | La zona no funciona más |
