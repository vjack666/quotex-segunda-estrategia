#!/usr/bin/env python3
"""Verifica cuántos trades STRAT-C se han recolectado."""
import sqlite3
import glob
from pathlib import Path

db_files = glob.glob("data/db/black_box_strat_*.db")
if not db_files:
    print("❌ BD no existe aún")
    exit(1)
db_path = Path(db_files[-1])  # Usa la más reciente

db = sqlite3.connect(str(db_path))
cur = db.cursor()

# Total de scans
cur.execute("SELECT COUNT(*) FROM scans")
total_scans = cur.fetchone()[0]

# Total de candidatos por estrategia
cur.execute("""
    SELECT strategy, COUNT(*) as cnt
    FROM scan_candidates
    GROUP BY strategy
    ORDER BY strategy
""")

print(f"\n📊 SCANS: {total_scans}\n")
print("📋 CANDIDATOS POR ESTRATEGIA:\n")

strat_c_total = 0
for strategy, cnt in cur.fetchall():
    print(f"  {strategy:8} — {cnt:3d} candidatos")
    if strategy in ("STRAT-C", "C", "c"):  # Verificar variantes
        strat_c_total = cnt

print(f"\n🎯 STRAT-C: {strat_c_total} candidatos recolectados")
print(f"   Necesarios: 50")
print(f"   Falta: {max(0, 50 - strat_c_total)}")
print(f"   Progreso: {strat_c_total}/50 ({strat_c_total/50*100:.1f}%)")

# Tasa de candidatos por scan
if total_scans > 0:
    avg_per_scan = strat_c_total / total_scans
    remaining_scans = max(0, 50 - strat_c_total) / avg_per_scan if avg_per_scan > 0 else float('inf')
    print(f"\n   Tasa: {avg_per_scan:.2f} cand/scan")
    print(f"   ETA: {remaining_scans:.0f} scans (~{remaining_scans*90/60:.0f} min a 90s/scan)")

db.close()
