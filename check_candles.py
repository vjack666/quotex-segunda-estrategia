import sqlite3, json
from pathlib import Path
db = list(Path('data/db').glob('*.db'))[0]
conn = sqlite3.connect(db)
cur = conn.cursor()
cur.execute("SELECT candles_1m FROM scan_candidates WHERE candles_1m IS NOT NULL LIMIT 1")
r = cur.fetchone()
if r:
    data = json.loads(r[0])
    print('tipo:', type(data))
    if isinstance(data, list) and data:
        print('ultimo candle:', data[-1])
        print('total candles:', len(data))
else:
    print('no hay candles_1m')
