# 01 — Visión General del Sistema

## ¿Qué es este bot?

Es un sistema automatizado de trading de opciones binarias para la plataforma **Quotex**. Opera de forma continua (24/7 en modo loop), detecta patrones técnicos de consolidación de precio en múltiples activos OTC simultáneamente, y coloca órdenes de compra/venta con un riesgo definido y un sistema de gestión de capital progresivo.

---

## Objetivo Operativo

El bot busca aprovechar dos fenómenos de mercado recurrentes en activos OTC:

1. **Rebote en zona de consolidación** — el precio llega al techo o piso de una zona de rango lateral y rebota con un patrón de reversión confirmado en velas de 1 minuto.
2. **Ruptura con momentum** — el precio rompe el techo o piso con una vela de cuerpo fuerte (fuerza medida como proxy de volumen), indicando continuación de impulso.

---

## Modos de Operación

| Modo | Cómo activar | Descripción |
|---|---|---|
| **Dry-Run (análisis)** | `python main.py` | Solo escanea y muestra señales, NO envía órdenes |
| **DEMO live** | `python main.py --loop` | Envía órdenes reales en cuenta DEMO de Quotex |
| **REAL live** | `python main.py --loop --real` | ⚠️ Envía órdenes en cuenta REAL |
| **Ciclo único** | `python main.py --once` | Ejecuta un solo ciclo de escaneo y termina |

---

## Tipos de Cuenta

- **PRACTICE** (demo): dinero virtual, sin riesgo. Usada por defecto para desarrollo y pruebas.
- **REAL**: dinero real. Requiere el flag `--real` explícito. El bot imprime una advertencia visible al arrancar.

---

## Mercados Objetivo

El bot opera exclusivamente activos **OTC** (Over-The-Counter) de Quotex, que:
- Están disponibles fuera de horario de mercado regulado (fines de semana, noches)
- Tienen payout mínimo configurado en **≥80%**
- Se ordenan de mayor a menor payout para priorizar rentabilidad matemática

---

## Estrategias del Sistema

El sistema tiene **dos estrategias independientes** que corren en paralelo durante cada ciclo de escaneo:

### STRAT-A — Consolidación (principal)
- Detecta zonas de consolidación en velas de **5 minutos**
- Entra en rebote o ruptura de la zona
- Es la estrategia principal que genera órdenes reales por defecto
- Duración de cada opción: **120 segundos (2 minutos)**

### STRAT-B — Spring Sweep (espejo)
- Detecta patrones Wyckoff Spring / Liquidity Sweep en velas de **1 minuto**
- Por defecto corre en **modo espejo** (solo log, sin órdenes)
- Se activa con `--strat-b-live` para operar

---

## Gestión de Capital

El sistema usa un enfoque de **compensación dinámica** (similar a Masaniello simplificado):

- **Monto inicial**: $1.00 por defecto → calcula monto exacto para obtener ganancia entera
- **Monto compensación**: si el trade anterior fue LOSS, escala el monto para recuperar la pérdida + obtener $2 netos
- **Ciclo**: 6 operaciones máximo, objetivo de 2 wins por ciclo
- **Stop-loss de sesión**: detiene el bot si el drawdown alcanza el 20% del balance inicial

---

## Requisitos Técnicos

```
Python 3.13+
pyquotex 1.0.3 (stable_api)
pandas
```

Variables de entorno en archivo `.env`:
```
QUOTEX_EMAIL=tu@email.com
QUOTEX_PASSWORD=tupassword
```

---

## Zona Horaria

El broker Quotex opera en **UTC-3**. Todos los logs y marcas de tiempo usan esta zona horaria para consistencia con las gráficas de la plataforma.
