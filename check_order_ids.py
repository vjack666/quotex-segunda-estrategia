#!/usr/bin/env python3
"""Verifica qué candidatos STRAT-C tienen order_id asignado."""
import sqlite3
import glob

db_files = glob.glob("data/db/black_box_strat_*.db")
db = sqlite3.connect(db_files[-1])
c = db.cursor()

# Total y con order_id
c.execute('''
    SELECT COUNT(*), SUM(CASE WHEN order_id IS NOT NULL THEN 1 ELSE 0 END) 
    FROM scan_candidates 
    WHERE strategy = "C"
''')
total, with_order_id = c.fetchone()
print(f"\n📊 STRAT-C CANDIDATES:")
print(f"  Total: {total}")
print(f"  Con order_id: {with_order_id or 0}")
print(f"  Sin order_id: {total - (with_order_id or 0)}\n")

# Ver samples de order_ids
c.execute('''
    SELECT order_id, COUNT(*), 
           COUNT(CASE WHEN order_result = "WIN" THEN 1 END) as wins,
           COUNT(CASE WHEN order_result = "LOSS" THEN 1 END) as losses,
           COUNT(CASE WHEN order_result IS NULL THEN 1 END) as null_results
    FROM scan_candidates 
    WHERE strategy = "C" AND order_id IS NOT NULL
    GROUP BY order_id
    LIMIT 10
''')

print("📋 ORDER_IDs CON RESULTADOS:")
for order_id, total_cnt, wins, losses, nulls in c.fetchall():
    print(f"  {order_id:20} — {total_cnt}x (W:{wins} L:{losses} NULL:{nulls})")

# Ver primeros 3 con/sin order_id
print("\n🔎 SAMPLE SIN ORDER_ID:")
c.execute('''
    SELECT id, asset, direction, order_result, profit, created_at
    FROM scan_candidates 
    WHERE strategy = "C" AND order_id IS NULL
    LIMIT 3
''')
for cid, asset, direction, result, profit, ts in c.fetchall():
    print(f"  ID={cid:4d} | {asset:15} {direction:4} | result={result or 'NULL':10} | profit={profit or 'NULL'}")

db.close()
