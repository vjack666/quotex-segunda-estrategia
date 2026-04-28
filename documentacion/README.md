# Documentación del Sistema — Quotex Consolidation Bot

## Índice General

Este directorio contiene la documentación técnica completa del sistema de trading automatizado para Quotex. Los documentos están ordenados del nivel más general al más específico.

---

| Documento | Contenido |
|---|---|
| [01 — Visión General](01_vision_general.md) | Qué hace el bot, modos de operación, cuentas DEMO/REAL, estrategias en resumen |
| [02 — Arquitectura](02_arquitectura.md) | Estructura de archivos, dependencias entre módulos, responsabilidades de cada componente |
| [03 — Estrategia A: Consolidación](03_estrategia_A.md) | Detección de zona, clasificación de precio, patrones 1m, scoring, timing, ejecución |
| [04 — Estrategia B: Spring Sweep](04_estrategia_B.md) | Wyckoff Spring, algoritmo de detección, modo espejo, integración en el loop |
| [05 — Flujo de Datos](05_flujo_datos.md) | Secuencia completa de inicio a fin: arranque → conexión → scan → orden → resultado |
| [06 — Parámetros](06_parametros.md) | Todas las constantes del sistema con valores actuales y overrides CLI disponibles |
| [07 — Broker API](07_broker_api.md) | pyquotex: autenticación, WebSocket, colocación de órdenes, duraciones válidas, errores |
| [08 — Diario y Forense](08_diario_y_forense.md) | SQLite journal (esquema de tablas), capturas forenses JSON (vela_ops), análisis 40/40 |

---

## Resumen Ejecutivo

### Qué hace el sistema

Bot 24/7 que escanea todos los activos OTC de Quotex con payout ≥ 80%, detecta zonas de consolidación de precio en velas de 5 minutos, y entra en opciones binarias de 2 minutos cuando detecta:

- **Rebote en techo/piso** de la zona + patrón de reversión confirmado en 1m (señal contraria: PUT en techo, CALL en piso)
- **Ruptura con fuerza** del techo o piso (señal de momentum: CALL en ruptura arriba, PUT en ruptura abajo)

Solo opera si la señal supera un score matemático de 62/100 que combina compresión del rango, calidad del rebote, tendencia EMA y payout.

### Configuración Actual

```
Velas análisis:  5 minutos
Duración orden:  120 segundos (2 minutos)
Payout mínimo:   80%
Score umbral:    62/100
Monto base:      $1.00
Concurrencia:    máx 8 activos simultáneos en fetch
Ciclo capital:   6 operaciones, objetivo 2 wins o +10%
Stop-loss:       20% drawdown de sesión
```

### Cómo Correr

```bash
# Solo análisis (sin órdenes)
python main.py

# DEMO con órdenes reales, loop 24/7
python main.py --loop

# REAL (⚠️ dinero real)
python main.py --loop --real

# Con parámetros personalizados
python main.py --loop --amount-initial 2.0 --min-payout 82 --max-loss-session 0.15

# Activar STRAT-B para operar
python main.py --loop --strat-b-live --strat-b-min-confidence 0.75
```

### Archivos Generados en Runtime

| Archivo | Descripción |
|---|---|
| `trade_journal.db` | Base de datos SQLite con todo el historial |
| `consolidation_bot.log` | Log de sesión rotativo |
| `data/vela_ops/*.json` | Capturas forenses de rupturas de zona |
| `sessions/session.json` | Token de autenticación persistente |

---

## Lecciones Aprendidas (Historial de Problemas Resueltos)

| Problema | Solución Implementada |
|---|---|
| Broker rechaza orden: `info=expiration` | Usar solo `duration=120` (valores válidos: 60,120,180,240,300) |
| Scan bloqueante 10+ minutos | Descarga paralela con `asyncio.Semaphore(8)` |
| Datos contaminados entre activos | Guardia de precio ±25% del rango de la zona |
| Timeout 125s en `client.buy()` | Reconectar antes de cada orden; no envolver con `asyncio.wait_for` |
| 25s timeout cortaba órdenes legítimas | Eliminar `wait_for` — dejar que el broker responda sin límite local |
| Zonas expirando prematuramente | `MAX_CONSOLIDATION_MIN = 0` (sin límite de tiempo) |
