#!/usr/bin/env python3
import sqlite3, glob, json
from collections import defaultdict

path = glob.glob('data/db/black_box_strat_*.db')[-1]
db = sqlite3.connect(path)
c = db.cursor()

c.execute('''
    SELECT asset, direction, score, payout, order_id, order_result, profit, strategy_details, created_at
    FROM scan_candidates
    WHERE strategy='C' AND order_id IS NOT NULL AND order_id != '' AND length(order_id) > 10
    ORDER BY created_at ASC
''')
rows = c.fetchall()

by_order = defaultdict(list)
for row in rows:
    by_order[row[4]].append(row)

print('rows_executed =', len(rows))
print('unique_order_ids =', len(by_order))
print('duplicate_order_ids =', sum(1 for v in by_order.values() if len(v) > 1))
print('\norder_id duplicates:')
for oid, group in by_order.items():
    if len(group) > 1:
        assets = [g[0] for g in group]
        results = [g[5] for g in group]
        print(oid, 'count=', len(group), 'assets=', assets, 'results=', results)

# dedup: keep first row per order_id as broker order proxy
unique = [group[0] for group in by_order.values()]
resolved = [r for r in unique if r[5] in ('WIN', 'LOSS')]
wins = sum(1 for r in resolved if r[5] == 'WIN')
losses = sum(1 for r in resolved if r[5] == 'LOSS')
print('\ndeduped resolved =', len(resolved), 'wins =', wins, 'losses =', losses)
print('deduped winrate =', round((wins / len(resolved) * 100) if resolved else 0, 2))
print('deduped pnl =', round(sum(r[6] or 0 for r in resolved), 2))

# compare score by result on deduped rows
for label in ('WIN', 'LOSS'):
    subset = [r[2] for r in resolved if r[5] == label and r[2] is not None]
    if subset:
        print(label, 'avg_score=', round(sum(subset)/len(subset), 2), 'min=', min(subset), 'max=', max(subset))

# inspect raw details
print('\nraw metric sample:')
for row in unique[:5]:
    details = json.loads(row[7] or '{}')
    d = details.get('detalle', {}) if isinstance(details, dict) else {}
    print(row[0], row[5], 'raw_score=', details.get('raw_score'), 'rsi=', d.get('rsi'), 'atr=', d.get('atr'), 'wick_ratio=', d.get('wick_ratio'), 'source=', details.get('source'))

db.close()
