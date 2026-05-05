# Estrategia 30 Segundos — Rechazo M1 en Zona

**Versión:** 1.0  
**Fecha:** Mayo 2026  
**Tipo:** Binary Options — Scalping de precisión  
**Broker objetivo:** Quotex  

---

## ¿Qué es esta estrategia?

Es una estrategia de entrada de alta precisión basada en la **detección de rechazo de precio en una zona clave dentro del primer minuto de una vela M1**, específicamente aprovechando la acción entre el **segundo 30 y 41** de la vela.

El objetivo no es predecir el movimiento de largo plazo, sino capturar el **impulso de rechazo inmediato** que se produce cuando el precio toca una zona relevante (soporte, resistencia, banda, EMA) y comienza a revertir visiblemente en la primera mitad de la vela.

---

## Premisa de la estrategia

> Si el precio llega a una zona relevante y al segundo 30 de la vela M1 ya muestra un **wick de rechazo significativo** (mecha > cuerpo, cierre parcial en dirección opuesta), con **confluencia de al menos 2 indicadores**, existe una probabilidad elevada de que esa vela cierre como vela de rechazo y la siguiente vela continúe el movimiento de reversión.

---

## Timing de entrada en Quotex

| Parámetro | Valor |
|---|---|
| Ventana de entrada | Segundo 30–41 de la vela M1 |
| Expiración recomendada | **60 segundos** (mínimo disponible en Quotex) |
| Lógica | 30s restantes de la vela actual + primeros segundos de la siguiente |
| Duración de la operación | 1 vela M1 completa (aproximadamente) |

> **Nota importante:** Quotex no ofrece expiración de 30 segundos en la mayoría de activos. La duración mínima confirmada es **60 segundos**. La estrategia aprovecha esta restricción entrando en el segundo 30 de la vela, de modo que la expiración coincide con el cierre de la siguiente vela.

---

## Estructura de archivos

```
estrategia_30s/
├── README.md              ← Este archivo (visión general)
├── indicadores.md         ← Investigación y descripción de indicadores
├── reglas_entrada.md      ← Checklist de condiciones para entrar
├── implementacion.md      ← Hoja de ruta para implementación en Python/bot
└── logs/                  ← Carpeta para registrar sesiones de prueba
```

---

## Documentos relacionados (bot principal)

- [documentacion/11_tesis_hibrida_rechazo_m1.md](../documentacion/11_tesis_hibrida_rechazo_m1.md) — Tesis madre de rechazo M1
- [documentacion/03_estrategia_A.md](../documentacion/03_estrategia_A.md) — STRAT-A (contexto de consolidación)
- [src/consolidation_bot.py](../src/consolidation_bot.py) — Implementación STRAT-B actual

---

## Diferencias respecto a STRAT-B (bot actual)

| Aspecto | STRAT-B (bot actual) | Estrategia 30s (nueva) |
|---|---|---|
| Timeframe base | M1 | M1 |
| Expiración | 300s (5 min) | 60s |
| Entrada | Cualquier segundo | Segundo 30–41 |
| Confirmación | Spring/Upthrust + SMC | Zona + Wick + 2 indicadores |
| Indicadores | EMA, volumen, estructura | RSI, EMA, Bollinger, Stochastic |
| Fase | Producción | Investigación/Laboratorio |

---

## Estado actual

- [x] Concepto definido
- [x] Documentación base creada
- [ ] Backtesting manual de 100 señales
- [ ] Implementación Python (detector de señales)
- [ ] Pruebas en demo
- [ ] Producción
