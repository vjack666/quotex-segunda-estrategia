#!/usr/bin/env python3
"""Verifica si record_order_result se está ejecutando (LOG JSONL)."""
import json
import glob
from pathlib import Path

# Buscar archivos black_box*.jsonl
jsonl_files = glob.glob("data/logs/black_box/black_box*.jsonl")
if not jsonl_files:
    print("No se encontraron archivos black_box*.jsonl")
    exit(1)

log_file = sorted(jsonl_files)[-1]  # El más reciente
print(f"📋 Analizando: {Path(log_file).name}\n")

events = {}
try:
    with open(log_file) as f:
        for line_num, line in enumerate(f, 1):
            entry = json.loads(line)
            event = entry.get("event")
            events[event] = events.get(event, 0) + 1
            
            # Log details of key events
            if event == "order_result":
                print(f"✅ order_result: {entry}")
            elif event == "candidate_recorded" and "STRAT-C" in str(entry):
                strategy = entry.get("strategy")
                decision = entry.get("decision")
                print(f"🔵 candidate [{strategy}]: {decision} — {entry.get('asset')} {entry.get('direction')}")
except Exception as e:
    print(f"Error reading log: {e}")
    exit(1)

print(f"\n📊 EVENTS SUMMARY:")
for event, count in sorted(events.items(), key=lambda x: -x[1]):
    print(f"  {event}: {count}")

print(f"\n⚠️ KEY INSIGHT:")
print(f"  order_result events: {events.get('order_result', 0)}")
print(f"  candidate_recorded events: {events.get('candidate_recorded', 0)}")
if events.get('order_result', 0) > 0:
    ratio = events.get('order_result', 0) / events.get('candidate_recorded', 1)
    print(f"  Completion ratio: {ratio:.1%}")
else:
    print(f"  ⚠️  NO order_result events recorded!")
