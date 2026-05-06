#!/usr/bin/env python3
"""Analiza qué valores de order_id se están guardando."""
import sqlite3
import glob

db = sqlite3.connect(glob.glob("data/db/black_box_strat_*.db")[-1])
c = db.cursor()

print("\n📋 ANALISIS DE ORDER_IDs EN LA BD:")
c.execute('''
    SELECT 
        COUNT(*) as cnt,
        COUNT(CASE WHEN order_id = "" THEN 1 END) as empty_string,
        COUNT(CASE WHEN order_id = "BROKER_NO_ID" THEN 1 END) as broker_no_id,
        COUNT(CASE WHEN order_id LIKE "REF-%" THEN 1 END) as ref_prefix,
        COUNT(CASE WHEN order_id LIKE "%[a-f0-9]%" THEN 1 END) as has_uuid
    FROM scan_candidates 
    WHERE strategy = "C"
''')
cnt, empty, broker_no_id, ref_prefix, has_uuid = c.fetchone()
print(f"  Total STRAT-C: {cnt}")
print(f"  Con order_id = '': {empty}")
print(f"  Con order_id = 'BROKER_NO_ID': {broker_no_id}")
print(f"  Con order_id = 'REF-*': {ref_prefix}")
print(f"  Con order_id UUID-like: {has_uuid}")

print("\n📌 MUESTRAS DE DIFERENTES TYPES DE order_id:")
c.execute('''
    SELECT DISTINCT order_id 
    FROM scan_candidates 
    WHERE strategy = "C"
    LIMIT 15
''')
for row in c.fetchall():
    order_id = row[0]
    if order_id is None:
        print(f"  NULL")
    elif order_id == "":
        print(f"  '' (empty string)")
    elif len(order_id) < 30:
        print(f"  '{order_id}'")
    else:
        print(f"  UUID/UUID-like: {order_id[:20]}...")

print("\n🔗 CORRELACIÓN order_id vs order_result:")
c.execute('''
    SELECT order_id, COUNT(*), 
           COUNT(CASE WHEN order_result = "WIN" THEN 1 END),
           COUNT(CASE WHEN order_result = "LOSS" THEN 1 END),
           COUNT(CASE WHEN order_result IS NULL THEN 1 END)
    FROM scan_candidates 
    WHERE strategy = "C"
    GROUP BY order_id
    ORDER BY COUNT(*) DESC
''')
for order_id, total, wins, losses, nulls in c.fetchall():
    order_id_display = order_id or "NULL"
    if len(order_id_display) > 20:
        order_id_display = order_id_display[:15] + "..."
    print(f"  {order_id_display:20} → {total:3d}x (W:{wins:2d} L:{losses:2d} NULL:{nulls:2d})")

db.close()
