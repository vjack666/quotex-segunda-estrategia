#!/usr/bin/env python
import sqlite3
import glob

dbs = sorted(glob.glob("data/db/trade_journal-*.db"))
db = dbs[-1]
print(f"DB: {db}")

conn = sqlite3.connect(db)
c = conn.cursor()

# Check tables
tables = [t[0] for t in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
print(f"Tables: {tables}")

# Check trades
if 'trades' in tables:
    trades = c.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
    print(f"Total trades: {trades}")
    if trades > 0:
        outcomes = c.execute("SELECT outcome, COUNT(*) FROM trades GROUP BY outcome ORDER BY COUNT() DESC").fetchall()
        print(f"Outcomes: {dict(outcomes)}")
        recent = c.execute("SELECT id, asset, direction, outcome, profit FROM trades ORDER BY id DESC LIMIT 5").fetchall()
        print("Recent 5 trades:")
        for r in recent:
            print(f"  ID={r[0]} {r[1]} {r[2]} outcome={r[3]} profit={r[4]}")
else:
    print("No trades table")

# Check candidates table
if 'candidates' in tables:
    cands = c.execute("SELECT COUNT(*) FROM candidates").fetchone()[0]
    print(f"Total candidates: {cands}")
else:
    print("No candidates table")

conn.close()
