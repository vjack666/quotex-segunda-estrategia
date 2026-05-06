"""
GUÍA DE INTEGRACIÓN: BLACK BOX EN CONSOLIDATION_BOT.PY
======================================================

Instrucciones para conectar el black box recorder al motor principal.
"""

INTEGRATION_GUIDE = """

╔════════════════════════════════════════════════════════════════════════════╗
║                       BLACK BOX INTEGRATION GUIDE                         ║
╚════════════════════════════════════════════════════════════════════════════╝


📍 PASO 1: Importar en consolidation_bot.py
═══════════════════════════════════════════════════════════════════════════════

En la sección de imports (línea ~50):

    from black_box_recorder import get_black_box


📍 PASO 2: Inicializar en __init__
═══════════════════════════════════════════════════════════════════════════════

En ConsolidationBot.__init__():

    self.black_box = get_black_box()
    self.scan_counter = 0


📍 PASO 3: Registrar inicio de escaneo
═══════════════════════════════════════════════════════════════════════════════

En main() o scan_cycle(), al inicio:

    self.scan_counter += 1
    market_context = {
        "market_state": "consolidating",  # or "trending", "ranging"
        "volatility_atr": calculated_atr,
    }
    self.current_scan_id = self.black_box.record_scan_start(
        strategy="A",  # or "B", "C"
        scan_number=self.scan_counter,
        market_context=market_context
    )


📍 PASO 4: Registrar cada candidato
═══════════════════════════════════════════════════════════════════════════════

Para STRAT-A, en _score_consolidation_entries():

    for candidate in candidates:
        self.black_box.record_candidate(
            scan_id=self.current_scan_id,
            strategy="A",
            data={
                "asset": candidate.asset,
                "direction": candidate.direction,
                "score": candidate.score,
                "confidence": getattr(candidate, 'confidence', 0.0),
                "payout": candidate.payout,
                "decision": "ACCEPTED" if selected else "REJECTED_SCORE",
                "decision_reason": "Strong rebound + high confluence" if selected else "Low score",
                "reject_reason": None if selected else f"score={candidate.score:.1f} < {threshold}",
                "strategy_details": {
                    "zone": [candidate.zone_floor, candidate.zone_ceiling],
                    "pattern": candidate.reversal_pattern,
                    "entry_mode": candidate.entry_mode,
                },
                "candles_1m": [asdict(c) for c in last_5_1m_candles],
            }
        )


📍 PASO 5: Registrar resultados de órdenes
═══════════════════════════════════════════════════════════════════════════════

Cuando una orden se completa, en _process_trade_result():

    self.black_box.record_order_result(
        order_id=order_id,
        outcome="WIN" if profit > 0 else "LOSS",
        profit=profit
    )


📍 PASO 6: Actualizar métricas al final del escaneo
═══════════════════════════════════════════════════════════════════════════════

Al terminar cada ciclo:

    # Contar
    con = sqlite3.connect(self.black_box.db_path)
    cur = con.cursor()
    cur.execute("SELECT COUNT(*) FROM scan_candidates WHERE scan_id = ? AND decision = 'ACCEPTED'", 
                (self.current_scan_id,))
    accepted = cur.fetchone()[0]
    con.close()
    
    # Actualizar
    self.black_box.update_scan_results(
        scan_id=self.current_scan_id,
        found=len(candidates),
        accepted=accepted,
        rejected=len(candidates) - accepted
    )
    
    # Métricas agregadas
    self.black_box.update_strategy_metrics("A", {
        "total_scans": self.scan_counter,
        "total_candidates": total_scanned,
        "total_accepted": total_accepted,
        "wins": wins,
        "losses": losses,
        "pending": pending,
        "win_rate": wins / (wins + losses) if (wins + losses) > 0 else 0,
        "pnl": pnl,
        "last_decision": last_decision,
        "last_asset": last_asset,
    })


╔════════════════════════════════════════════════════════════════════════════╗
║                           VERIFICACIÓN                                    ║
╚════════════════════════════════════════════════════════════════════════════╝

Después de integrar, ejecuta:

    1. python main.py --strat-b-live  (o tu configuración)
    
    2. Espera 5-10 scans
    
    3. python lab/black_box_viewer.py
    
    4. Deberías ver:
       ✓ Scans ejecutados
       ✓ Decisiones por estrategia
       ✓ Activos escaneados
       ✓ Performance (si hay trades)
       ✓ Razones de rechazo


╔════════════════════════════════════════════════════════════════════════════╗
║                      ARCHIVOS RELACIONADOS                                ║
╚════════════════════════════════════════════════════════════════════════════╝

src/black_box_recorder.py      — Motor principal de registro
lab/black_box_viewer.py        — Visualizador de datos
data/db/black_box_strat_YYYY-MM-DD.db  — Base de datos (SQLite)
data/logs/black_box_YYYY-MM-DD.jsonl   — Log en formato JSON línea

"""

print(INTEGRATION_GUIDE)

# Mostrar ejemplo rápido
print("\n" + "="*80)
print("📝 EJEMPLO RÁPIDO DE USO")
print("="*80 + "\n")

example = """
from black_box_recorder import get_black_box

# Obtener instancia
bb = get_black_box()

# 1. Registrar inicio de escaneo
scan_id = bb.record_scan_start("B", scan_number=42, 
    market_context={"market_state": "consolidating", "volatility_atr": 0.0012})

# 2. Registrar candidato escaneado
bb.record_candidate(scan_id, "B", {
    "asset": "EURUSD_OTC",
    "direction": "call",
    "score": 72.5,
    "confidence": 0.85,
    "payout": 82,
    "decision": "ACCEPTED",
    "decision_reason": "Spring pattern + high confidence",
    "strategy_details": {
        "signal_type": "spring_sweep",
        "break_price": 1.0975,
        "support": 1.0950,
    },
})

# 3. Registrar resultado
bb.record_order_result(order_id="ORD123", outcome="WIN", profit=0.85)

# 4. Ver resumen
summary = bb.export_summary()
print(summary)
"""

print(example)
