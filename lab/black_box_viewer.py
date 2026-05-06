"""
BLACK BOX VIEWER - Visualización y análisis de datos capturados
===============================================================

Herramienta para inspeccionar TODO lo que vieron las estrategias A, B, C
"""

import sqlite3
import json
from pathlib import Path
from collections import Counter, defaultdict
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DB_DIR = DATA_DIR / "db"

def get_latest_black_box_db():
    """Obtiene la DB más reciente."""
    dbs = sorted(DB_DIR.glob("black_box_strat_*.db"), reverse=True)
    return dbs[0] if dbs else None

def analyze_black_box():
    """Análisis completo de la caja negra."""
    db_path = get_latest_black_box_db()
    if not db_path:
        print("❌ No se encontró base de datos black_box. Ejecuta el bot primero.")
        return
    
    print(f"\n📊 BLACK BOX ANALYSIS")
    print(f"{'=' * 80}")
    print(f"Base de datos: {db_path.name}\n")
    
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    
    # ── RESUMEN DE ESCANEOS ──
    print("🔍 SCANS EXECUTADOS")
    print(f"{'-' * 80}")
    cur.execute('''
        SELECT strategy, COUNT(*) as total, SUM(found_count) as found,
               SUM(accepted_count) as accepted, SUM(rejected_count) as rejected
        FROM scans
        GROUP BY strategy
        ORDER BY strategy
    ''')
    
    for row in cur.fetchall():
        strategy = row["strategy"]
        total = row["total"] or 0
        found = row["found"] or 0
        accepted = row["accepted"] or 0
        rejected = row["rejected"] or 0
        
        print(f"\n  STRAT-{strategy}:")
        print(f"    • Scans ejecutados:      {total}")
        print(f"    • Candidatos encontrados: {found}")
        print(f"    • Aceptados:             {accepted}")
        print(f"    • Rechazados:            {rejected}")
        if found > 0:
            print(f"    • Acceptance rate:       {accepted/found*100:.1f}%")
    
    # ── DECISIONES ──
    print(f"\n\n📋 DECISIONES POR ESTRATEGIA")
    print(f"{'-' * 80}")
    cur.execute('''
        SELECT strategy, decision, COUNT(*) as count
        FROM scan_candidates
        GROUP BY strategy, decision
        ORDER BY strategy, count DESC
    ''')
    
    decisions_by_strat = defaultdict(Counter)
    for row in cur.fetchall():
        decisions_by_strat[row["strategy"]][row["decision"]] = row["count"]
    
    for strategy in ["A", "B", "C"]:
        if strategy in decisions_by_strat:
            print(f"\n  STRAT-{strategy}:")
            for decision, count in decisions_by_strat[strategy].most_common():
                print(f"    • {decision:25s}: {count:4d}")
    
    # ── ACTIVOS PRINCIPALES ──
    print(f"\n\n💱 ACTIVOS MÁS ESCANEADOS")
    print(f"{'-' * 80}")
    cur.execute('''
        SELECT strategy, asset, direction, COUNT(*) as count, 
               SUM(CASE WHEN decision = 'ACCEPTED' THEN 1 ELSE 0 END) as accepted
        FROM scan_candidates
        GROUP BY strategy, asset, direction
        ORDER BY strategy, count DESC
        LIMIT 20
    ''')
    
    print(f"\n{'Asset':<15} {'Dir':<4} {'Scanned':<8} {'Accepted':<8} {'Strat':<5}")
    print(f"{'-' * 50}")
    for row in cur.fetchall():
        print(f"{row['asset']:<15} {row['direction']:<4} {row['count']:<8} {row['accepted']:<8} {row['strategy']:<5}")
    
    # ── PERFORMANCE (si hay resultados) ──
    print(f"\n\n📈 PERFORMANCE DE TRADES")
    print(f"{'-' * 80}")
    cur.execute('''
        SELECT strategy, 
               COUNT(*) as total,
               SUM(CASE WHEN order_result = 'WIN' THEN 1 ELSE 0 END) as wins,
               SUM(CASE WHEN order_result = 'LOSS' THEN 1 ELSE 0 END) as losses,
               SUM(CASE WHEN order_result = 'PENDING' THEN 1 ELSE 0 END) as pending,
               ROUND(SUM(profit), 2) as pnl
        FROM scan_candidates
        WHERE order_result IS NOT NULL
        GROUP BY strategy
    ''')
    
    rows = cur.fetchall()
    if rows:
        print(f"\n{'Strat':<5} {'Trades':<8} {'Wins':<6} {'Loss':<6} {'Pend':<6} {'WR%':<7} {'P&L':<10}")
        print(f"{'-' * 60}")
        for row in rows:
            total = row["total"] or 0
            wins = row["wins"] or 0
            wr = wins / total * 100 if total > 0 else 0
            print(f"  {row['strategy']:<4} {total:<8} {wins:<6} {row['losses']:<6} {row['pending']:<6} {wr:<6.1f}% {row['pnl']:<+10.2f}")
    else:
        print("\n  ⏳ Aún sin resultados de trades completados.")
    
    # ── CONFIANZA PROMEDIO ──
    print(f"\n\n🎯 CONFIANZA PROMEDIO")
    print(f"{'-' * 80}")
    cur.execute('''
        SELECT strategy, 
               ROUND(AVG(confidence), 3) as avg_conf,
               ROUND(MIN(confidence), 3) as min_conf,
               ROUND(MAX(confidence), 3) as max_conf
        FROM scan_candidates
        WHERE confidence > 0
        GROUP BY strategy
    ''')
    
    print(f"\n{'Strat':<5} {'Avg':<8} {'Min':<8} {'Max':<8}")
    print(f"{'-' * 40}")
    for row in cur.fetchall():
        print(f"  {row['strategy']:<4} {row['avg_conf']:<8.3f} {row['min_conf']:<8.3f} {row['max_conf']:<8.3f}")
    
    # ── RAZONES DE RECHAZO ──
    print(f"\n\n❌ TOP RAZONES DE RECHAZO")
    print(f"{'-' * 80}")
    cur.execute('''
        SELECT reject_reason, COUNT(*) as count
        FROM scan_candidates
        WHERE reject_reason IS NOT NULL
        GROUP BY reject_reason
        ORDER BY count DESC
        LIMIT 10
    ''')
    
    for i, row in enumerate(cur.fetchall(), 1):
        reason = row["reject_reason"] or "desconocido"
        print(f"  {i:2d}. {reason:50s} ({row['count']:3d})")
    
    # ── ÚLTIMOS 5 ACEPTADOS ──
    print(f"\n\n✅ ÚLTIMOS ACEPTADOS (top 5)")
    print(f"{'-' * 80}")
    cur.execute('''
        SELECT ts, strategy, asset, direction, score, confidence, decision_reason
        FROM scan_candidates
        WHERE decision = 'ACCEPTED'
        ORDER BY ts DESC
        LIMIT 5
    ''')
    
    print(f"\n{'Time':<8} {'Strat':<5} {'Asset':<15} {'Dir':<4} {'Score':<7} {'Conf':<7} {'Reason':<30}")
    print(f"{'-' * 80}")
    for row in cur.fetchall():
        ts_str = datetime.fromtimestamp(row["ts"], tz=timezone.utc).strftime("%H:%M:%S")
        reason = (row["decision_reason"] or "N/A")[:28]
        print(f"{ts_str:<8} {row['strategy']:<5} {row['asset']:<15} {row['direction']:<4} {row['score']:<7.1f} {row['confidence']:<7.2f} {reason:<30}")
    
    con.close()
    
    print(f"\n{'=' * 80}\n")

if __name__ == "__main__":
    analyze_black_box()
