import re
from pathlib import Path

log_path = Path('data/logs/bot/consolidation_bot-2026-05-12.log')
log_content = log_path.read_text(encoding='utf-8', errors='replace')

print("=" * 80)
print("SEARCHING FOR CANDIDATE ID 5 AND USDBDT_OTC")
print("=" * 80)

# Search for references to candidate 5 and USDBDT_otc
lines = log_content.split('\n')

# Track all lines mentioning USDBDT_otc
usdbdt_lines = []
for i, line in enumerate(lines):
    if 'USDBDT' in line:
        usdbdt_lines.append((i, line))

print(f"\nFound {len(usdbdt_lines)} lines mentioning USDBDT_otc\n")

# Show all USDBDT_otc lines with context
for idx, (line_num, line) in enumerate(usdbdt_lines[-20:]):  # Last 20 lines
    print(f"Line {line_num}: {line[:150]}")

# Search for PHASE2 markers
print("\n" + "=" * 80)
print("SEARCHING FOR [PHASE2-HTF] AND [PHASE2-GATE] MARKERS")
print("=" * 80 + "\n")

phase2_lines = []
for i, line in enumerate(lines):
    if '[PHASE2-' in line:
        phase2_lines.append((i, line))

print(f"Found {len(phase2_lines)} lines with [PHASE2-...] markers\n")

# Show all PHASE2 markers
for idx, (line_num, line) in enumerate(phase2_lines[-30:]):  # Last 30 markers
    print(f"Line {line_num}: {line[:180]}")

# Search for candidate_id mentions in recent logs
print("\n" + "=" * 80)
print("SEARCHING FOR 'candidate_id' MENTIONS IN RECENT LOGS")
print("=" * 80 + "\n")

cand_id_lines = []
for i, line in enumerate(lines):
    if 'candidate_id' in line.lower():
        cand_id_lines.append((i, line))

print(f"Found {len(cand_id_lines)} lines with candidate_id\n")

# Show recent candidate_id lines
for idx, (line_num, line) in enumerate(cand_id_lines[-20:]):
    print(f"Line {line_num}: {line[:180]}")

# Search for "score=23.6" (from ID 5)
print("\n" + "=" * 80)
print("SEARCHING FOR 'score=23.6' (CANDIDATE ID 5)")
print("=" * 80 + "\n")

score_lines = []
for i, line in enumerate(lines):
    if 'score=23.6' in line or '23.6' in line and 'USDBDT' in line:
        score_lines.append((i, line))

print(f"Found {len(score_lines)} lines with score=23.6\n")

for idx, (line_num, line) in enumerate(score_lines[-15:]):
    print(f"Line {line_num}: {line[:180]}")
