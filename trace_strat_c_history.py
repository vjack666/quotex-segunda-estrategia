#!/usr/bin/env python3
"""Muestra la historia de decisiones STRAT-C en la BD para entender el patrón."""
import sqlite3
import glob

db = sqlite3.connect(glob.glob("data/db/black_box_strat_*.db")[-1])
c = db.cursor()

print("\n📊 STRAT-C: PRIMERAS ENTRADAS (más antiguas primero):")
c.execute('''
    SELECT id, asset, direction, decision, reject_reason, created_at
    FROM scan_candidates 
    WHERE strategy = "C"
    ORDER BY created_at ASC
    LIMIT 20
''')

for cid, asset, direction, decision, reject, created in c.fetchall():
    ts = created[:19] if created else "?"
    print(f"  ID={cid:3d} | {ts} | {asset:12} {direction:4} | {decision:20} | {reject or ''}")

print("\n📊 STRAT-C: ÚLTIMAS ENTRADAS (más recientes):")
c.execute('''
    SELECT id, asset, direction, decision, reject_reason, created_at
    FROM scan_candidates 
    WHERE strategy = "C"
    ORDER BY created_at DESC
    LIMIT 20
''')

for cid, asset, direction, decision, reject, created in c.fetchall():
    ts = created[:19] if created else "?"
    print(f"  ID={cid:3d} | {ts} | {asset:12} {direction:4} | {decision:20} | {reject or ''}")

db.close()
