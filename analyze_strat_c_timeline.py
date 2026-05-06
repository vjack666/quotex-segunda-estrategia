#!/usr/bin/env python3
"""Analiza cuáles STRAT-C trades completaron vs quedaron pending."""
import sqlite3
import glob
from datetime import datetime, timezone

db = sqlite3.connect(glob.glob("data/db/black_box_strat_*.db")[-1])
c = db.cursor()

print("\n📊 STRAT-C TRADE LIFECYCLE:")

# Trades con empty order_id
c.execute('''
    SELECT id, asset, direction, decision, order_result, created_at, updated_at
    FROM scan_candidates 
    WHERE strategy = "C" AND order_id = ""
    ORDER BY created_at DESC
    LIMIT 5
''')

print("\n❌ SAMPLE: Órdenes con order_id='' (Sin grabar en broker):")
for cid, asset, direction, decision, result, created, updated in c.fetchall():
    try:
        updated_dt = datetime.fromisoformat(updated)
        if updated_dt.tzinfo is None:
            updated_dt = updated_dt.replace(tzinfo=timezone.utc)
        age_sec = (datetime.now(timezone.utc) - updated_dt).total_seconds()
    except:
        age_sec = -1
    print(f"  ID={cid:3d} | {asset:10} {direction:4} | decision={decision:20} | result={result or 'NULL':10} | age={age_sec:5.0f}s")

# Trades con UUID order_id
c.execute('''
    SELECT id, asset, direction, decision, order_result, created_at, updated_at
    FROM scan_candidates 
    WHERE strategy = "C" AND order_id != "" AND order_id IS NOT NULL
    ORDER BY created_at DESC
    LIMIT 5
''')

print("\n✅ SAMPLE: Órdenes con UUID en broker:")
for cid, asset, direction, decision, result, created, updated in c.fetchall():
    try:
        updated_dt = datetime.fromisoformat(updated)
        if updated_dt.tzinfo is None:
            updated_dt = updated_dt.replace(tzinfo=timezone.utc)
        age_sec = (datetime.now(timezone.utc) - updated_dt).total_seconds()
    except:
        age_sec = -1
    print(f"  ID={cid:3d} | {asset:10} {direction:4} | decision={decision:20} | result={result or 'NULL':10} | age={age_sec:5.0f}s")

# Timeline
print("\n⏱️ TIMELINE (STRAT-C candidates por minuto):")
c.execute('''
    SELECT 
        strftime('%Y-%m-%d %H:%M', created_at) as minute,
        COUNT(*) as total,
        COUNT(CASE WHEN order_id = "" THEN 1 END) as empty_ids,
        COUNT(CASE WHEN order_id != "" THEN 1 END) as valid_ids,
        COUNT(CASE WHEN order_result IS NOT NULL THEN 1 END) as completed
    FROM scan_candidates 
    WHERE strategy = "C"
    GROUP BY minute
    ORDER BY minute DESC
    LIMIT 20
''')
for minute, total, empty, valid, completed in c.fetchall():
    print(f"  {minute}: {total} total | {empty} empty_ids | {valid} valid_ids | {completed} completed")

db.close()
