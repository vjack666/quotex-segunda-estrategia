#!/usr/bin/env python
import sqlite3
import glob

dbs = sorted(glob.glob("data/db/trade_journal-*.db"))
db = dbs[-1]
conn = sqlite3.connect(db)
c = conn.cursor()

# Check candidates columns
print("=== CANDIDATES schema ===")
cols = c.execute("PRAGMA table_info(candidates)").fetchall()
for col in cols:
    print(f"  {col[1]:25s} {col[2]}")

print("\n=== CANDIDATES data (all 8) ===")
candidates = c.execute("SELECT * FROM candidates ORDER BY id DESC LIMIT 8").fetchall()
col_names = [col[1] for col in cols]
print(f"Columns: {col_names}")
for cand in candidates:
    print(f"  {dict(zip(col_names, cand))}")

print("\n=== SHADOW DECISION AUDIT ===")
shadow = c.execute("SELECT id, asset, stage, old_decision, new_decision, trade_outcome FROM shadow_decision_audit ORDER BY id DESC").fetchall()
for row in shadow:
    print(f"  ID={row[0]} {row[1]:8s} {row[2]:20s} old={row[3][:15]:15s} new={row[4][:15]:15s} outcome={row[5]}")

conn.close()
