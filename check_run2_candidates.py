import sqlite3
from pathlib import Path

db_path = Path('data/db/trade_journal-2026-05-12.db')
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

print("=" * 80)
print("ALL CANDIDATES WITH TIMESTAMPS")
print("=" * 80 + "\n")

cursor.execute('SELECT id, scanned_at, asset, stage, score, decision, reject_reason FROM candidates ORDER BY id')
rows = cursor.fetchall()

for row in rows:
    # Parse the ISO 8601 timestamp to extract just the time
    timestamp = row['scanned_at']  # Format: 2026-05-12T13:50:20-03:00
    time_part = timestamp.split('T')[1].split('-')[0]  # Extract HH:MM:SS
    
    print(f"ID {row['id']}: {time_part} | {row['asset']} | score={row['score']} | {row['decision']}")
    print(f"        Reason: {row['reject_reason']}\n")

print("=" * 80)
print("SUMMARY")
print("=" * 80)
print("Run 2 started at approximately 16:49:28 UTC")
print("Run 2 was killed at approximately 17:01:22 UTC")
print("\nLooking for candidates with scanned_at between 16:49 and 17:01...")

# Parse and filter candidates by time
import datetime
from dateutil import parser

run2_start = datetime.datetime(2026, 5, 12, 16, 49, 0)
run2_end = datetime.datetime(2026, 5, 12, 17, 2, 0)

run2_candidates = []
for row in rows:
    try:
        ts = parser.isoparse(row['scanned_at'])
        if run2_start <= ts <= run2_end:
            run2_candidates.append(row)
    except:
        pass

print(f"\nCandidates from run 2: {len(run2_candidates)}")
for row in run2_candidates:
    timestamp = row['scanned_at']
    time_part = timestamp.split('T')[1].split('-')[0]
    print(f"  ID {row['id']}: {time_part} | {row['asset']}")

conn.close()
