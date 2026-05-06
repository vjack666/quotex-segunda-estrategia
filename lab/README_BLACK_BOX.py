"""
╔════════════════════════════════════════════════════════════════════════════╗
║                                                                            ║
║          🔍 SISTEMA COMPLETO DE CAJA NEGRA PARA ESTRAT-A/B/C             ║
║                                                                            ║
║                    Captura TOTAL de decisiones y resultados               ║
║                                                                            ║
╚════════════════════════════════════════════════════════════════════════════╝


✅ SISTEMA IMPLEMENTADO
═════════════════════════════════════════════════════════════════════════════════

Archivos creados:

    1. src/black_box_recorder.py
       └─ Motor principal de registro
       └─ Captura: scans, candidatos, decisiones, velas, resultados
       └─ Almacenamiento: SQLite + JSONL

    2. lab/black_box_viewer.py
       └─ Visualizador de datos
       └─ Análisis completo en terminal
       └─ Reportes por estrategia

    3. lab/BLACK_BOX_INTEGRATION.py
       └─ Guía de integración paso a paso
       └─ Ejemplos de código
       └─ Puntos de inserción en consolidation_bot.py


🗄️ QUÉ SE CAPTURA (COMPLETO)
═════════════════════════════════════════════════════════════════════════════════

POR CADA ESCANEO (STRAT A/B/C):
  ✓ Timestamp exacto (UTC + ISO)
  ✓ Número de escaneo
  ✓ Contexto de mercado (state, volatility)
  ✓ Total de candidatos encontrados
  ✓ Aceptados vs Rechazados

POR CADA CANDIDATO ESCANEADO:
  ✓ Asset y dirección (CALL/PUT)
  ✓ Score calculado
  ✓ Confidence level
  ✓ Payout ofrecido
  ✓ Decisión final (ACCEPTED/REJECTED_*)
  ✓ Razón de decisión
  ✓ Razón de rechazo (si aplica)
  ✓ Detalles específicos de estrategia (JSON)
  ✓ Últimas 5 velas 1m (OHLCV)
  ✓ Últimas 3 velas 5m (OHLCV)

POR CADA ORDEN EJECUTADA:
  ✓ Order ID
  ✓ Resultado (WIN/LOSS/PENDING)
  ✓ Profit/Loss
  ✓ Timestamp de actualización

AGREGADO POR ESTRATEGIA:
  ✓ Total de scans
  ✓ Total de candidatos
  ✓ Total aceptados
  ✓ Wins / Losses
  ✓ Winrate %
  ✓ P&L acumulado
  ✓ Última decisión
  ✓ Último asset escaneado


📊 UBICACIÓN DE DATOS
═════════════════════════════════════════════════════════════════════════════════

SQLite Database:
  data/db/black_box_strat_2026-05-06.db
  
  Tablas:
    • scans                - Resumen de cada escaneo
    • scan_candidates      - Detalle de candidatos
    • strategy_metrics     - Métricas agregadas
    • phase_log            - Log de fases de procesamiento

JSONL Log (formato línea):
  data/logs/black_box/black_box_2026-05-06.jsonl
  
  Eventos registrados:
    • scan_start
    • candidate_recorded
    • order_result
    • phase_complete


🚀 CÓMO USAR
═════════════════════════════════════════════════════════════════════════════════

INTEGRACIÓN EN BOT (6 pasos):

1. Importar:
   from black_box_recorder import get_black_box

2. Inicializar en __init__:
   self.black_box = get_black_box()
   self.scan_counter = 0

3. Registrar inicio de escaneo:
   self.current_scan_id = self.black_box.record_scan_start("A", scan_number=n)

4. Registrar cada candidato:
   self.black_box.record_candidate(scan_id, "A", {
       "asset": asset,
       "direction": direction,
       "score": score,
       "decision": "ACCEPTED" or "REJECTED_*",
       ...
   })

5. Registrar resultados:
   self.black_box.record_order_result(order_id, "WIN", profit)

6. Actualizar métricas finales:
   self.black_box.update_scan_results(scan_id, found=10, accepted=2, rejected=8)


VISUALIZAR DATOS:

   python lab/black_box_viewer.py

   Genera reporte con:
   ✓ Scans ejecutados por estrategia
   ✓ Decisiones (ACCEPTED/REJECTED breakdown)
   ✓ Top activos escaneados
   ✓ Performance de trades (wins/losses)
   ✓ Confianza promedio por estrategia
   ✓ Razones principales de rechazo
   ✓ Últimas entradas aceptadas


📈 EJEMPLO DE VISUALIZACIÓN (salida esperada)
═════════════════════════════════════════════════════════════════════════════════

📊 BLACK BOX ANALYSIS
════════════════════════════════════════════════════════════════════════════════

🔍 SCANS EXECUTADOS
────────────────────────────────────────────────────────────────────────────────

  STRAT-A:
    • Scans ejecutados:      127
    • Candidatos encontrados: 524
    • Aceptados:             45
    • Rechazados:            479
    • Acceptance rate:       8.6%

  STRAT-B:
    • Scans ejecutados:      127
    • Candidatos encontrados: 312
    • Aceptados:             38
    • Rechazados:            274
    • Acceptance rate:       12.2%

  STRAT-C:
    • Scans ejecutados:      85
    • Candidatos encontrados: 201
    • Aceptados:             18
    • Rechazados:            183
    • Acceptance rate:       9.0%


📋 DECISIONES POR ESTRATEGIA
────────────────────────────────────────────────────────────────────────────────

  STRAT-A:
    • REJECTED_SCORE              : 421
    • ACCEPTED                    : 45
    • REJECTED_LIMIT              : 58

  STRAT-B:
    • ACCEPTED                    : 38
    • REJECTED_CONF               : 156
    • REJECTED_LIMIT              : 118

  ...etc


💱 ACTIVOS MÁS ESCANEADOS
────────────────────────────────────────────────────────────────────────────────

Asset            Dir  Scanned  Accepted  Strat
EURUSD_OTC       call 142      18        A
GBPUSD_OTC       put  98       8         B
AUDUSD_OTC       call 87       12        A
NZDJPY_OTC       put  76       6         B
...


📈 PERFORMANCE DE TRADES
────────────────────────────────────────────────────────────────────────────────

Strat Trades Wins Loss Pend WR%    P&L
  A     45    28   17   0  62.2%  +18.45
  B     38    22   16   0  57.9%  +12.30
  C     18    9    9    0  50.0%  -2.15


🎯 CONFIANZA PROMEDIO
────────────────────────────────────────────────────────────────────────────────

Strat Avg      Min      Max
  A    0.745   0.520   0.980
  B    0.682   0.450   0.920
  C    0.612   0.380   0.870


❌ TOP RAZONES DE RECHAZO
────────────────────────────────────────────────────────────────────────────────

 1. score=52.3 < threshold 60             (421)
 2. confidence=0.45 < min 0.70            (156)
 3. cooldown_active (same asset)          (98)
 4. balance_insufficient                  (87)
 5. max_concurrent_trades_reached         (76)


✅ ÚLTIMOS ACEPTADOS (top 5)
────────────────────────────────────────────────────────────────────────────────

Time     Strat Asset         Dir  Score Conf   Reason
08:15:42  A    EURUSD_OTC   call 68.2  0.82  Strong rebound signal
08:14:28  B    GBPUSD_OTC   put  72.5  0.85  Spring pattern detected
08:13:15  A    AUDUSD_OTC   call 65.1  0.75  High confidence, tight zone
...


🔄 ANÁLISIS DINÁMICO
═════════════════════════════════════════════════════════════════════════════════

El sistema permite:

1. DEBUGGING en vivo
   └─ Ver exactamente qué vio cada estrategia
   └─ Entender por qué rechazó un candidato
   └─ Seguir evolución de decisiones

2. OPTIMIZACIÓN basada en datos
   └─ Identificar por qué fallan candidatos
   └─ Ajustar thresholds con evidencia
   └─ Detectar patrones de error

3. BACKTESTING histórico
   └─ Simular cambios de parámetros
   └─ Evaluar qué hubiera pasado
   └─ Calibrar configuración óptima

4. AUDITORÍA completa
   └─ Cada decisión está registrada
   └─ Trazable a velas exactas
   └─ Cumplimiento normativo


🎯 CASOS DE USO
═════════════════════════════════════════════════════════════════════════════════

CASO 1: "¿Por qué STRAT-B tiene bajo winrate?"
   → Ejecutar: python lab/black_box_viewer.py
   → Ver tabla de razones de rechazo
   → Identificar si es confidence bajo, score bajo, etc
   → Ajustar threshold específicamente

CASO 2: "¿Cuál es el activo más confiable?"
   → Filtrar por strategy + asset en viewer
   → Buscar máximo winrate con mínimo 10 muestras
   → Aumentar frequency en ese asset

CASO 3: "¿Está funcionando la optimización STRAT-B?"
   → Ejecutar antes y después de cambios
   → Comparar aceptance_rate y winrate
   → Cuantificar mejora exacta

CASO 4: "Falsa entrada en EURUSD hace 3 horas"
   → Buscar en black_box viewer por timestamp
   → Ver velas exactas que se escanearon
   → Reproducir decisión offline
   → Encontrar causa raíz


⚡ CAPACIDAD DE ALMACENAMIENTO
═════════════════════════════════════════════════════════════════════════════════

Estimativo por día:
   • 500 scans × 3 estrategias = 1,500 scans
   • 10 candidatos promedio × 1,500 = 15,000 candidatos
   • DB size: ~50 MB por mes
   • JSONL size: ~30 MB por mes

Total: ~80 MB de almacenamiento por mes

→ Retención automática: 31 días


📋 CHECKLIST DE IMPLEMENTACIÓN
═════════════════════════════════════════════════════════════════════════════════

□ Copiar black_box_recorder.py a src/
□ Copiar black_box_viewer.py a lab/
□ Leer BLACK_BOX_INTEGRATION.py
□ Agregar imports a consolidation_bot.py
□ Agregar inicialización en __init__
□ Agregar record_scan_start en main()
□ Agregar record_candidate en scoring loops
□ Agregar record_order_result en trade completion
□ Agregar update_scan_results al final de ciclo
□ Ejecutar: python lab/black_box_viewer.py (test)
□ Validar en próxima sesión: python lab/black_box_viewer.py (con datos reales)


═════════════════════════════════════════════════════════════════════════════════

✅ El sistema está LISTO para usar.

Próximo paso: Integrar en consolidation_bot.py (guía en BLACK_BOX_INTEGRATION.py)

═════════════════════════════════════════════════════════════════════════════════
"""

if __name__ == "__main__":
    import sys
    print(__doc__)
