import sqlite3, glob, json
from collections import Counter, defaultdict

dbs = sorted(glob.glob('data/db/trade_journal-*.db'), reverse=True)
if not dbs:
    print("Sin DB"); exit()
db = dbs[0]
print(f'DB: {db}\n')
con = sqlite3.connect(db)
con.row_factory = sqlite3.Row
cur = con.cursor()

cur.execute('''
    SELECT scanned_at, asset, direction, score, stage, decision, reject_reason,
           reversal_pattern, reversal_strength, zone_ceiling, zone_floor,
           order_id, outcome, profit, strategy_json
    FROM candidates
    ORDER BY scanned_at ASC
''')
rows = cur.fetchall()
print(f'Total registros en DB: {len(rows)}\n')

decisions = Counter(r["decision"] for r in rows)
print('Decisiones:', dict(decisions))
print()

print('=== ACEPTADOS ===')
for r in rows:
    if r["decision"] == "ACCEPTED":
        sj = json.loads(r["strategy_json"] or "{}")
        ps = sj.get("pattern_snapshot", {})
        bd = ps.get("score_breakdown", {})
        fe = ps.get("force_execute", False)
        em = ps.get("entry_mode", "")
        print(f'{r["scanned_at"]} | {r["asset"]:22s} {r["direction"]:4s} score={r["score"]:5.1f}')
        print(f'  entry_mode={em}  force_execute={fe}  reversal={r["reversal_pattern"]}  outcome={r["outcome"]}  profit={r["profit"]}')
        print(f'  breakdown: {json.dumps(bd)}')
        print()

print('=== RECHAZADOS (primeras 10 por razón) ===')
reject_groups = defaultdict(list)
for r in rows:
    if r["decision"] != "ACCEPTED":
        reject_groups[r["decision"]].append(r)

for decision, group in sorted(reject_groups.items()):
    print(f'\n--- {decision} ({len(group)} registros) ---')
    # Mostrar sample
    shown = {}
    for r in group:
        key = (r["asset"], r["direction"])
        if key not in shown:
            shown[key] = r
            sj = json.loads(r["strategy_json"] or "{}")
            ps = sj.get("pattern_snapshot", {})
            bd = ps.get("score_breakdown", {})
            reason = (r["reject_reason"] or "")[:80]
            print(f'  {r["asset"]:22s} {r["direction"]:4s} score={r["score"]:5.1f}  {reason}')

con.close()
