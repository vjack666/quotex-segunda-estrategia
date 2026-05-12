import sqlite3
import datetime
from pathlib import Path

db_path = Path('data/db/trade_journal-2026-05-12.db')
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

print("=" * 80)
print("COMPLETE TIMELINE OF ACTIVITY")
print("=" * 80 + "\n")

# Get all candidates
cursor.execute("""
    SELECT 
        id, 
        scanned_at,
        asset, 
        stage, 
        score, 
        decision,
        reject_reason
    FROM candidates 
    ORDER BY id ASC
""")
candidates = cursor.fetchall()

print("CANDIDATES TABLE:")
for row in candidates:
    print(f"  ID {row['id']}: {row['scanned_at']}")

# Get all shadow records
cursor.execute("""
    SELECT 
        id,
        created_at,
        candidate_id,
        asset
    FROM shadow_decision_audit
    ORDER BY id ASC
""")
shadows = cursor.fetchall()

print("\nSHADOW_DECISION_AUDIT TABLE:")
for row in shadows:
    print(f"  ID {row['id']}: {row['created_at']} (for candidate {row['candidate_id']})")

# Parse and analyze
print("\n" + "=" * 80)
print("ANALYSIS")
print("=" * 80 + "\n")

from dateutil import parser

times = []
for row in candidates:
    try:
        ts = parser.isoparse(row['scanned_at'])
        times.append(ts)
    except:
        pass

if times:
    min_time = min(times)
    max_time = max(times)
    duration = max_time - min_time
    
    print(f"First candidate: {min_time.strftime('%H:%M:%S UTC')} (ID 1)")
    print(f"Last candidate: {max_time.strftime('%H:%M:%S UTC')} (ID {len(candidates)})")
    print(f"Duration: {duration.total_seconds() / 60:.1f} minutes")
    print(f"Total candidates: {len(candidates)}")
    
    # Calculate gaps between candidates
    sorted_times = sorted(times)
    print(f"\nGaps between candidates:")
    for i in range(1, len(sorted_times)):
        gap = (sorted_times[i] - sorted_times[i-1]).total_seconds() / 60
        print(f"  Between ID {i} and {i+1}: {gap:.1f} minutes")

conn.close()
