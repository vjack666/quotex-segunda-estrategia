import sqlite3, json
from pathlib import Path
db = list(Path('data/db').glob('*.db'))[0]
conn = sqlite3.connect(db)
cur = conn.cursor()
cur.execute("SELECT strategy_details FROM scan_candidates WHERE order_id IS NOT NULL AND order_id != '' AND order_result='WIN' LIMIT 3")
for r in cur.fetchall():
    if r[0]:
        d = json.loads(r[0])
        print(json.dumps(d, indent=2))
        print('---')
