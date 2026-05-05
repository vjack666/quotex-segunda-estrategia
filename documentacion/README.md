# Documentación del Sistema — Quotex Consolidation Bot

## Índice General

Documentación técnica actualizada al estado operativo de entrenamiento (mayo 2026).

| Documento | Contenido |
|---|---|
| [01 — Visión General](01_vision_general.md) | Objetivo del sistema, modos de ejecución, estrategias y enfoque de entrenamiento |
| [02 — Arquitectura](02_arquitectura.md) | Estructura de carpetas, módulos y dependencias |
| [03 — Estrategia A](03_estrategia_A.md) | Consolidación 5m, scoring, filtros F1/F2 y ejecución |
| [04 — Estrategia B](04_estrategia_B.md) | Spring/Upthrust 1m, confianza, modo live y registro en caja negra |
| [05 — Flujo de Datos](05_flujo_datos.md) | Pipeline completo desde scan hasta resolución de trades |
| [06 — Parámetros](06_parametros.md) | Constantes vigentes y parámetros CLI más usados |
| [07 — Broker API](07_broker_api.md) | Integración pyquotex y criterios de robustez de envío |
| [08 — Diario y Forense](08_diario_y_forense.md) | SQLite de caja negra y capturas forenses de ruptura |
| [11 - Tesis Hibrida Rechazo M1](11_tesis_hibrida_rechazo_m1.md) | Marco operativo combinado (internet + filtros del bot) para rechazos en M1 |

## Estado actual resumido

- Duración operativa: 300s (5 minutos)
- Concurrencia de trades: 2 simultáneos
- STRAT-B integrada en el mismo journal
- Stop-loss de sesión desactivado por entrenamiento (`ENABLE_SESSION_STOP_LOSS = False`)
- Rechazo M1 con ventana temporal configurable (segundo 30-41)
- Clasificación de rechazo parcial/total configurable
- Persistencia diaria: `data/db/trade_journal-YYYY-MM-DD.db`

## Nota sobre documentos históricos

Los estudios puntuales en esta carpeta (por ejemplo archivos `caja_negra_estudio_*`) son snapshots históricos de sesiones pasadas. Sirven para investigación, pero no representan necesariamente la configuración vigente.
