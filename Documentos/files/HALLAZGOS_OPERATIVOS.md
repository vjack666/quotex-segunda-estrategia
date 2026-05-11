# HALLAZGOS OPERATIVOS Y RIESGOS DEL SISTEMA
*Evidencia técnica directa del código fuente — sin suavizar*

---

## Hallazgos Operativos Críticos

### HO-01 — El Sistema Opera Setups Que No Deberían Ejecutarse

**Evidencia:**
En `entry_scorer.py`, el threshold de entrada es `SCORE_THRESHOLD = 65`.
Un candidato puede llegar a 67 puntos con HTF completamente en contra (score_trend
bajo = aporta 8.75/25 del componente trend) y sin patrón de vela 1m (pattern = "none"
es permitido si el score total supera 65).

Esto no es un bug. Es una decisión de diseño que priorizó no perder señales sobre
operar solo las mejores.

**Impacto operativo:** El sistema ejecuta operaciones donde la probabilidad de win
puede ser cercana al 50%, que con payout de 83% produce EV negativo.

**Acción requerida:** Implementar filtros binarios en FILTROS_CRITICOS.md.

---

### HO-02 — El HTF Es Opcional en la Práctica

**Evidencia:**
El componente de tendencia en `entry_scorer._score_trend()` aporta hasta 25 puntos
en modo REBOUND. Si el HTF está en contra, el componente puede aportar apenas 2-3
puntos (ratio 0.10 cuando neither aligned nor slope_support). Eso produce una
penalización efectiva de ~22 puntos, que reduce el score pero no bloquea la entrada.

Un candidato con excelente zona (compression = 18/20), buen payout (payout = 18/20)
y moderado bounce (bounce = 20/35) puede llegar a score 56. Si el HTF estuviera
alineado, sumaría 21/25 puntos de trend para total de 77. Sin alineación, suma 3/25
para total de 59. El 59 es rechazado. Pero si el bounce es ligeramente mejor (26/35),
el total sin HTF sería 65 = exactamente el umbral. Pasa.

Hay combinaciones de otros componentes fuertes que compensan la penalización de HTF
y permiten que una entrada contra el flujo mayor llegue justo al umbral.

**Acción requerida:** HTF como veto binario, no como componente de score.

---

### HO-03 — Zone Memory Es Poderosa Pero Subutilizada

**Evidencia:**
`zone_memory.py` implementa un sistema sofisticado de clasificación de zonas históricas
con decaimiento temporal, clasificación por rol (support/resistance/neutral) y ajustes
de fuerza normalizados. Los cálculos son correctos y el diseño es bueno.

Sin embargo, en `vip_library.py`, la condición `zone_memory_ok` se define como:
```python
zone_memory_adj = float((getattr(candidate, "score_breakdown", {}) or {}).get("zone_memory", 0.0) or 0.0)
zone_memory_ok = zone_memory_adj >= 0.0
```

Esto significa que `zone_memory_ok = True` siempre que el ajuste sea ≥ 0. Un ajuste
de 0.0 (sin zonas relevantes) se trata igual que un ajuste de +8.0 (camino libre).
Solo los ajustes negativos (muros) hacen `zone_memory_ok = False`.

La condición en VIP Library es correcta conceptualmente pero el umbral de 0.0 es muy
permisivo. No distingue entre "no hay información histórica" y "hay soporte activo debajo".

**Acción requerida:** Ninguna urgente. El veto de muro en FILTROS_CRITICOS.md cubre el
caso más peligroso. A largo plazo, enriquecer la condición VIP para distinguir ausencia
de datos vs presencia de contexto positivo.

---

### HO-04 — El Spring/Upthrust Existe Pero No Se Usa

**Evidencia:**
`strategy_spring_sweep.py` implementa correctamente detección de Spring Wyckoff,
Upthrust y variantes early. El código es sólido, tiene manejo de errores y produce
métricas de confianza interpretables.

En `main.py`, la configuración fuerza `STRAT_B_ENABLED = False`. El módulo corre
en algún punto del scan (se instancia la clase), pero no genera entradas reales.

Hay dos problemas: primero, el módulo tiene potencial real de edge (el Spring es uno
de los patrones de mayor respaldo en análisis técnico aplicado). Segundo, al estar
completamente apagado, no hay datos históricos de su precisión real en este mercado.

**Acción requerida:** Activar en modo "vigilancia sin ejecución" para recolectar
datos. Después de 100 señales registradas, analizar precisión real y decidir activación.

---

### HO-05 — El Masaniello Reinicia Banca en Cada Ciclo

**Evidencia:**
En `masaniello_engine._complete_cycle()`:
```python
self.state.bankroll = float(self.config.reference_balance)
self.state.peak_bankroll = float(self.config.reference_balance)
```

Cada ciclo comienza desde la banca base fija (`reference_balance`), independientemente
de si el ciclo anterior fue positivo o negativo. Esto tiene una implicación importante:
los ciclos positivos no acumulan capital base para ciclos siguientes.

**¿Es un problema?** Depende del objetivo. Si el sistema está diseñado para extraer
ganancias entre ciclos (retirar profits y resetear), este diseño es correcto. Si el
objetivo es crecimiento compuesto de la banca, el diseño actual lo impide.

**Acción requerida:** Clarificar con el operador cuál es el modelo de extracción de
ganancias. Si se quiere crecimiento compuesto, el parámetro `reference_balance` debe
actualizarse al final de cada ciclo positivo.

---

## Riesgos Técnicos del Sistema

### RT-01 — Ambigüedad de Orden en Timeout (CRÍTICO)

**Evidencia:**
En `consolidation_bot.py`, función `place_order()`:
El código registra explícitamente que ante un timeout de buy, la orden puede haber
quedado abierta en el broker. Se ejecutan rutas de reconexión y puede intentarse
un reintento sin conciliación obligatoria por ID de ticket.

**Riesgo concreto:**
Timeout → reconexión → reintento de buy → dos órdenes abiertas simultáneamente.
El primero puede estar vivo en el broker; el segundo es una nueva exposición.

**Impacto financiero:** Doble exposición, potencialmente 2× el monto Masaniello calculado.

**Acción requerida (URGENTE):**
Antes de cualquier reintento de buy después de timeout:
1. Consultar posiciones abiertas en el broker.
2. Si hay posición del mismo activo → no reintentar.
3. Si no hay posición → reintentar.

---

### RT-02 — Reconexión Concurrente (ALTO)

**Evidencia:**
Dos rutas independientes llaman a `ensure_connection()`:
- El watchdog en `main.py` periódicamente.
- El loop principal en `consolidation_bot.py` cuando detecta degradación.

No hay lock de reconexión compartido. Si ambas rutas detectan degradación simultáneamente,
pueden intentar reconectar al mismo tiempo, produciendo estados inconsistentes de la
sesión WebSocket.

**Impacto:** Reconexión fallida, sesión corrupta, pérdida de telemetría de operación activa.

**Acción requerida:**
Implementar `asyncio.Lock()` compartido de reconexión. Solo una ruta puede reconectar
a la vez. La segunda que llega espera a que la primera termine.

---

### RT-03 — Debug Prints en Loop Crítico (ALTO)

**Evidencia:**
Múltiples `print()` síncronos dentro de `scan_all()` y el loop principal en `consolidation_bot.py`.

En Python asyncio, `print()` es síncrono y bloquea el event loop hasta que la
operación de I/O del sistema operativo completa. Con muchos prints por ciclo de
escaneo, esto introduce jitter de milisegundos a decenas de milisegundos.

En trading de opciones binarias donde el timing de entrada puede ser relevante en
los últimos segundos antes del cierre de vela, este jitter es un riesgo real.

**Acción requerida:** Reemplazar con `log.debug()` y gate de nivel en Fase 1.

---

### RT-04 — Credenciales en Disco en Texto Plano (CRÍTICO)

**Evidencia:**
`config.json` contiene email y password. Archivos de sesión contienen tokens y cookies.
Estos archivos están en el directorio de trabajo del bot.

**Riesgo concreto:**
- Acceso físico al equipo → acceso total a la cuenta Quotex.
- Captura accidental en logs, snapshots, backups → exposición de credenciales.
- Error de configuración de `.gitignore` → publicación accidental en repositorio.

**Acción requerida (INMEDIATA):**
1. Rotar credenciales y token ahora.
2. Eliminar valores de archivos JSON.
3. Cargar desde variables de entorno o vault cifrado.
4. Verificar que los archivos de sesión estén en `.gitignore` y no en historial de git.

---

### RT-05 — Falta de Límite de Sesión Explícito

**Evidencia:**
No existe un contador de operaciones por sesión implementado como límite hard en el código.
El objetivo de "máximo 5 operaciones en 2 horas" existe como intención operativa
pero no como restricción de código.

**Riesgo:** En un mercado activo con muchas señales válidas, el sistema puede operar
8-10 veces en una sesión de 2 horas, aumentando la exposición al Masaniello más
allá de lo planeado.

**Acción requerida:** Implementar SESSION_LIMIT_GATE en Fase 2.

---

## Puntos Fuertes a Proteger

Estos componentes funcionan bien. No tocarlos sin razón:

**1. Bridge async bounded (`_run_on_main_loop_bounded`):**
Diseño anti-fuga correcto para entorno thread + asyncio. Si se modifica sin cuidado,
pueden aparecer tasks huérfanas y congelamiento progresivo del loop. Proteger.

**2. HTF Scanner como tarea de background:**
Desacoplamiento correcto. El fetch 15m no bloquea el loop principal de trading.
Mantener arquitectura de task independiente.

**3. Journal con ticket audit:**
La trazabilidad de tickets (`log_ticket_detail`, `update_ticket_detail`) es excelente
para diagnóstico forense. Mantener y extender, no reemplazar.

**4. Spike filter:**
Bien encapsulado, parámetros conservadores, sin dependencias problemáticas.
Puede aplicarse en cualquier punto del pipeline sin efectos secundarios.

**5. VIP Library como capa táctica:**
El concepto de "candidatos casi listos" es correcto y útil. La implementación
tiene algunas oportunidades de mejora (ver HO-03) pero la estructura es buena.
