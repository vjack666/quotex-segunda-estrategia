import sqlite3
from pathlib import Path

db_path = Path('data/db/trade_journal-2026-05-12.db')
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

print('=== CANDIDATES TABLE ===')
cursor.execute('SELECT id, scanned_at, asset, stage, score, decision, reject_reason FROM candidates ORDER BY id DESC')
rows = cursor.fetchall()
print(f'Total rows: {len(rows)}')
for row in rows:
    print(f"ID {row['id']}: {row['asset']} | stage={row['stage']} | score={row['score']} | decision={row['decision']} | reason={row['reject_reason']}")

print(f'\n=== SHADOW_DECISION_AUDIT TABLE ===')
cursor.execute('SELECT id, created_at, candidate_id, asset, old_decision, new_decision, compare_status FROM shadow_decision_audit ORDER BY id DESC')
rows = cursor.fetchall()
print(f'Total shadow rows: {len(rows)}')
for row in rows:
    print(f"Shadow {row['id']}: cand_id={row['candidate_id']} | asset={row['asset']} | compare_status={row['compare_status']}")

conn.close()
