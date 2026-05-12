import sqlite3
import json
from pathlib import Path

db_path = Path('data/db/trade_journal-2026-05-12.db')
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

print("=" * 80)
print("DETAILED ANALYSIS OF CANDIDATE ID 5")
print("=" * 80)

cursor.execute('SELECT id, scanned_at, asset, stage, score, decision, reject_reason, strategy_json FROM candidates WHERE id = 5')
row = cursor.fetchone()

if row:
    print(f"\nCandidate ID: {row['id']}")
    print(f"Asset: {row['asset']}")
    print(f"Stage: {row['stage']}")
    print(f"Score: {row['score']}")
    print(f"Decision: {row['decision']}")
    print(f"Reject Reason: {row['reject_reason']}")
    print(f"Scanned At: {row['scanned_at']}")
    
    if row['strategy_json']:
        try:
            strategy = json.loads(row['strategy_json'])
            print(f"\nStrategy JSON (phase2 relevant parts):")
            if 'phase2_gate' in strategy:
                phase2 = strategy['phase2_gate']
                print(f"  Filter Name: {phase2.get('filter_name', 'N/A')}")
                print(f"  Reason: {phase2.get('reason', 'N/A')}")
                print(f"  Stage: {phase2.get('stage', 'N/A')}")
                print(f"  Score: {phase2.get('score', 'N/A')}")
                print(f"  Profile: {phase2.get('profile', 'N/A')}")
        except json.JSONDecodeError as e:
            print(f"  Error parsing strategy_json: {e}")

# Now check shadow_decision_audit for ID 5
print("\n" + "=" * 80)
print("SHADOW AUDIT TRAIL FOR CANDIDATE ID 5")
print("=" * 80)

cursor.execute('SELECT id, created_at, candidate_id, old_decision, old_reason, new_decision, compare_status FROM shadow_decision_audit WHERE candidate_id = 5')
shadow_rows = cursor.fetchall()

if shadow_rows:
    for shadow in shadow_rows:
        print(f"\nShadow ID: {shadow['id']}")
        print(f"Created: {shadow['created_at']}")
        print(f"Old Decision: {shadow['old_decision']}")
        print(f"Old Reason: {shadow['old_reason']}")
        print(f"New Decision: {shadow['new_decision']}")
        print(f"Compare Status: {shadow['compare_status']}")
else:
    print("No shadow audit records for candidate ID 5")

conn.close()
