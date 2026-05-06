#!/usr/bin/env python3
"""Analiza razones de rechazo en STRAT-C."""
import sqlite3
import glob

db = sqlite3.connect(glob.glob("data/db/black_box_strat_*.db")[-1])
c = db.cursor()

print("\n📊 RAZONES DE RECHAZO EN STRAT-C:")

# Órdenes con order_id="" 
c.execute('''
    SELECT decision, COUNT(*), GROUP_CONCAT(reject_reason, '; ') as reasons
    FROM scan_candidates 
    WHERE strategy = "C" AND order_id = ""
    GROUP BY decision
''')

for decision, cnt, reasons in c.fetchall():
    print(f"\n  {decision}: {cnt} órdenes")
    if reasons:
        reason_list = list(dict.fromkeys(reasons.split('; ')))  # Remove duplicates preserving order
        for reason in reason_list[:3]:  # Primeras 3 razones únicas
            print(f"    - {reason}")

# Análisis específico de REJECTED_DISABLED
print("\n\n🔍 ANÁLISIS: REJECTED_DISABLED (las más comunes)")
c.execute('''
    SELECT reject_reason, COUNT(*)
    FROM scan_candidates 
    WHERE strategy = "C" AND decision = "REJECTED_DISABLED"
    GROUP BY reject_reason
    ORDER BY COUNT(*) DESC
''')

for reason, cnt in c.fetchall():
    print(f"  {reason}: {cnt}")

# Ver si hay diferencia en asset o direction
print("\n\n🔗 REJECTED_DISABLED por ASSET/DIRECTION:")
c.execute('''
    SELECT asset, direction, COUNT(*)
    FROM scan_candidates 
    WHERE strategy = "C" AND decision = "REJECTED_DISABLED"
    GROUP BY asset, direction
    ORDER BY COUNT(*) DESC
    LIMIT 10
''')

for asset, direction, cnt in c.fetchall():
    print(f"  {asset:15} {direction:4}: {cnt}")

db.close()
