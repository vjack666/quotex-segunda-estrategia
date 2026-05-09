# Indicadores para Estrategia de 30 Segundos — Rechazo M1

**Categoría:** Investigación de indicadores técnicos  
**Aplicación:** Detección de rechazo en zona durante el segundo 30 de vela M1  

---

## Principio fundamental

Para una estrategia de expiración ultra-corta (60s), los indicadores **no deben ser lagging ni lentos**. El precio ya ha tomado una decisión a nivel de zona — el trabajo del indicador es **confirmar el contexto** y **filtrar falsos rechazos**.

Se priorizan indicadores que:
1. Respondan rápidamente a cambios recientes (EMA corta, RSI rápido)
2. Identifiquen zonas de sobre-extensión (Bollinger, RSI extremo)
3. Detecten momentum de reversión (Stochastic, MACD rápido)
4. Midan la calidad del wick (cálculo interno de vela)

---

## 1. RSI Rápido — RSI(7) o RSI(14)

### ¿Qué es?
El Relative Strength Index (RSI) mide la velocidad y magnitud de los movimientos de precio recientes. Oscila entre 0 y 100.

### Configuración recomendada para 30s
- **Período:** 7 (más sensible que el estándar de 14)
- **Timeframe de cálculo:** M1 (velas de 1 minuto)
- **Lookback mínimo:** 14 velas

### Cómo usarlo en esta estrategia
| Señal | Condición RSI(7) | Dirección |
|---|---|---|
| Zona de sobreventa | RSI < 30 | CALL (compra) |
| Zona de sobrecompra | RSI > 70 | PUT (venta) |
| Confirmación fuerte | RSI < 20 o RSI > 80 | +peso extra |

### Por qué funciona en rechazos M1
Cuando el precio llega a una zona de soporte y el RSI está en zona de sobreventa, ambas condiciones **se refuerzan mutuamente**: la zona de precio actúa como resistencia a continuar cayendo, y el RSI indica agotamiento del movimiento bajista. El rechazo que vemos en la vela M1 es la materialización técnica de ese agotamiento.

### Limitaciones
- En tendencias fuertes, el RSI puede mantenerse en zona extrema durante muchas velas sin reversión
- Usar **siempre en conjunción** con la zona de precio — el RSI aislado genera muchas señales falsas en scalping

### Cálculo Python (referencia)
```python
def rsi(closes: list, period: int = 7) -> float:
    if len(closes) < period + 1:
        return 50.0
    deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    gains = [d for d in deltas[-period:] if d > 0]
    losses = [-d for d in deltas[-period:] if d < 0]
    avg_gain = sum(gains) / period if gains else 0.0
    avg_loss = sum(losses) / period if losses else 0.001
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))
```

---

## 2. EMA Doble — EMA(8) / EMA(21)

### ¿Qué es?
Las Exponential Moving Averages dan más peso a los precios recientes. La combinación 8/21 en M1 actúa como detector de micro-tendencia.

### Configuración recomendada para 30s
- **EMA rápida:** 8 períodos (M1)
- **EMA lenta:** 21 períodos (M1)
- **Uso complementario:** EMA(50) M1 como zona dinámica relevante

### Cómo usarlo en esta estrategia
| Señal | Condición | Dirección |
|---|---|---|
| Micro-tendencia alcista | EMA(8) > EMA(21) | Favorece CALL |
| Micro-tendencia bajista | EMA(8) < EMA(21) | Favorece PUT |
| Precio en EMA como zona | Close ≈ EMA(21) ±0.1% | Rechazo potencial |
| Cruce reciente (≤3 velas) | EMA(8) cruza EMA(21) | Confirmación de reversión |

### Uso estratégico
La EMA(21) actúa como zona dinámica de soporte/resistencia. Cuando el precio:
1. Llega a la EMA(21) desde arriba → posible soporte
2. Llega a la EMA(21) desde abajo → posible resistencia

Si el wick de rechazo toca exactamente la EMA(21), la probabilidad de reversión aumenta.

### Alineación de tendencia (filtro macro)
Antes de entrar, verificar:
- EMA(8) M5 > EMA(21) M5 → solo CALL en rechazo de soporte
- EMA(8) M5 < EMA(21) M5 → solo PUT en rechazo de resistencia

---

## 3. Bandas de Bollinger — BB(20, 2.0)

### ¿Qué es?
Las Bollinger Bands crean un canal dinámico alrededor del precio usando la desviación estándar. La banda superior/inferior indica sobre-extensión estadística.

### Configuración recomendada para 30s
- **Período:** 20 (M1)
- **Desviación estándar:** 2.0
- **Componentes:** Banda superior, media (SMA20), banda inferior

### Cómo usarlo en esta estrategia
| Señal | Condición | Dirección |
|---|---|---|
| Precio toca banda inferior | Close ≤ BB_lower | CALL potencial |
| Precio toca banda superior | Close ≥ BB_upper | PUT potencial |
| Wick atraviesa la banda | Wick toca BB pero cierre dentro | Rechazo de banda confirmado |
| Banda estrecha (squeeze) | (BB_upper - BB_lower) < umbral | Evitar — volatilidad baja |

### BB + Rechazo de wick (señal doble)
La señal más fuerte de esta estrategia combina:
- El **wick de la vela** toca o atraviesa la banda de Bollinger
- El **cuerpo de la vela** cierra dentro de las bandas

Esto indica que el mercado rechazó explícitamente el precio fuera del rango estadístico normal.

### Squeeze detection (filtro de volatilidad)
```
bandwidth = (BB_upper - BB_lower) / BB_middle
if bandwidth < 0.002:  # squeeze — evitar entrada
    skip = True
```

---

## 4. Oscilador Estocástico — Stochastic(5, 3, 3)

### ¿Qué es?
El Stochastic compara el precio de cierre con el rango de precios durante un período. Es muy sensible en configuración rápida y útil para detectar momentos exactos de giro.

### Configuración recomendada para 30s
- **K:** 5 períodos (ultra-rápido)
- **D:** 3 períodos (suavizado de K)
- **Slowing:** 3

### Cómo usarlo en esta estrategia
| Señal | Condición | Dirección |
|---|---|---|
| Sobreventa extrema | %K < 20 y %D < 20 | CALL potencial |
| Sobrecompra extrema | %K > 80 y %D > 80 | PUT potencial |
| Cruce alcista | %K cruza %D hacia arriba desde zona < 20 | CALL fuerte |
| Cruce bajista | %K cruza %D hacia abajo desde zona > 80 | PUT fuerte |

### Diferencia con RSI
- El RSI mide **velocidad** del movimiento
- El Stochastic mide **posición relativa** del precio en su rango reciente
- Juntos dan una imagen más completa del agotamiento del movimiento

### Timing en 30s
El cruce del Stochastic en zona extrema es especialmente valioso porque tiende a ocurrir **dentro de la misma vela** en la que se detecta el wick de rechazo, haciéndolo un confirmador en tiempo real.

---

## 5. MACD Rápido — MACD(3, 8, 5)

### ¿Qué es?
El Moving Average Convergence Divergence mide la diferencia entre dos EMAs. La versión rápida (3, 8, 5) reacciona en segundos al cambio de momentum.

### Configuración para 30s
- **EMA rápida:** 3
- **EMA lenta:** 8
- **Señal (suavizado):** 5
- **Alternativa clásica:** MACD(12, 26, 9) para confirmación en M5

### Cómo usarlo en esta estrategia
| Señal | Condición | Interpretación |
|---|---|---|
| Histograma positivo creciente | MACD > Signal y subiendo | Momentum alcista |
| Histograma negativo decreciente | MACD < Signal y bajando | Momentum bajista |
| Cruce MACD/Signal | MACD cruza Signal | Inicio de impulso |
| Divergencia | Precio hace nuevo mínimo, MACD no | Posible reversión |

### Uso combinado
El MACD rápido confirma que el impulso de rechazo detectado visualmente en el wick **ya ha iniciado** — no estamos entrando antes del movimiento sino cuando el movimiento ya comenzó.

---

## 6. ATR — Average True Range (7)

### ¿Qué es?
El ATR mide la volatilidad promedio del mercado en los últimos N períodos. No indica dirección, solo magnitud del movimiento esperado.

### Configuración para 30s
- **Período:** 7 (M1)

### Cómo usarlo como filtro
```
ATR_threshold_min = 0.00005  # pips mínimos de volatilidad para entrar
ATR_threshold_max = 0.00030  # evitar noticias o volatilidad extrema

if ATR < ATR_threshold_min:
    skip = True  # mercado dormido, sin rechazo real
if ATR > ATR_threshold_max:
    skip = True  # demasiado ruido, rechazo no confiable
```

### Uso como objetivo de tamaño de wick
El wick de rechazo debe ser **al menos 1.0x ATR(7)** para ser considerado significativo. Un wick menor es solo ruido estadístico.

```
wick_size = high - max(open, close)  # para wick superior
wick_size = min(open, close) - low   # para wick inferior
if wick_size < atr * 1.0:
    reject = True
```

---

## 7. Soporte y Resistencia Horizontal

### ¿Por qué es el indicador más importante?
Todos los indicadores anteriores son **confirmadores**. El **punto de partida** siempre debe ser una zona de soporte o resistencia horizontal clara.

### Cómo identificar zonas válidas
1. **Recency:** La zona fue tocada en las últimas 20–50 velas
2. **Número de toques:** Al menos 2 rebotes anteriores documentados
3. **Precisión:** El precio llegó exactamente (±0.5 ATR) al nivel
4. **Contexto:** La zona está en dirección contraria a la tendencia reciente

### Tipos de zonas por prioridad
| Prioridad | Tipo de zona |
|---|---|
| ★★★ Alta | Zona con 3+ toques anteriores |
| ★★★ Alta | Nivel round (e.g., 1.0900, 1.0950) |
| ★★ Media | Zona con 2 toques anteriores |
| ★★ Media | Máximo/mínimo de sesión anterior |
| ★ Baja | Zona con 1 toque |
| ★ Baja | EMA(50) como soporte dinámico |

---

## 8. Patrones de Vela (Price Action)

### Patrones de rechazo válidos para entrar
| Patrón | Tipo | Señal |
|---|---|---|
| **Hammer** | Cuerpo pequeño arriba, wick largo abajo | CALL |
| **Shooting Star** | Cuerpo pequeño abajo, wick largo arriba | PUT |
| **Pin Bar** | Wick > 2x cuerpo, cierre en 75% superior/inferior | CALL/PUT |
| **Engulfing alcista** | Vela actual cubre completamente a la anterior bajista | CALL |
| **Engulfing bajista** | Vela actual cubre completamente a la anterior alcista | PUT |
| **Doji con wick** | Cuerpo casi nulo + wick significativo en zona | Confirma rechazo |

### Clasificación de calidad de rechazo
```
ratio_wick_a_cuerpo = wick_size / body_size

if ratio > 3.0:     # rechazo TOTAL — señal fuerte
if ratio 1.5–3.0:  # rechazo PARCIAL — señal media
if ratio < 1.5:     # no es rechazo — ignorar
```

---

## Resumen: Sistema de puntuación por confluencia

Para entrar se requieren **mínimo 2 confirmaciones** adicionales a la zona + wick.

| Condición | Puntos |
|---|---|
| Zona S/R con 3+ toques | +3 |
| Zona S/R con 2 toques | +2 |
| RSI(7) en extremo (< 25 o > 75) | +2 |
| RSI(7) en zona media (< 30 o > 70) | +1 |
| Precio en Bollinger Band | +2 |
| Stochastic cruce en extremo | +2 |
| EMA(21) como zona dinámica | +1 |
| MACD rápido confirma dirección | +1 |
| ATR dentro de rango válido | +1 (filtro) |
| Wick ratio > 3.0 (rechazo total) | +2 |
| Wick ratio 1.5–3.0 (rechazo parcial) | +1 |
| Alineación tendencia M5 | +1 |

**Umbral de entrada:** ≥ 6 puntos (incluyendo zona + wick mínimo)  
**Entrada de alta confianza:** ≥ 9 puntos  

---

## Fuentes de referencia

- Investopedia — Moving Averages, RSI, Bollinger Bands, Stochastic
- TradingView — Documentación de indicadores técnicos
- StockCharts School — Stochastic Oscillator Fast/Slow
- Conocimiento propio del bot STRAT-B: `src/consolidation_bot.py`, `src/entry_scorer.py`
