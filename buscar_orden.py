import sqlite3, json
from pathlib import Path

db = list(Path('data/db').glob('*.db'))[0]
conn = sqlite3.connect(db)
cur = conn.cursor()

order_id = '47b17c6f-707b-4168-a699-852eb38c20be'

# Buscar en scan_candidates
cur.execute("""
SELECT id, scan_id, ts, strategy, asset, direction, score, confidence, payout,
       decision, decision_reason, reject_reason, strategy_details, order_id,
       order_result, profit, created_at
FROM scan_candidates
WHERE order_id LIKE ?
""", (f'%{order_id[:8]}%',))
rows = cur.fetchall()

if not rows:
    # Buscar por order_id exacto
    cur.execute("SELECT * FROM scan_candidates WHERE order_id = ?", (order_id,))
    rows = cur.fetchall()

print(f"Resultados encontrados: {len(rows)}")
for r in rows:
    print()
    print(f"  ID          : {r[0]}")
    print(f"  scan_id     : {r[1]}")
    print(f"  ts          : {r[2]}")
    print(f"  strategy    : {r[3]}")
    print(f"  asset       : {r[4]}")
    print(f"  direction   : {r[5]}")
    print(f"  score       : {r[6]}")
    print(f"  confidence  : {r[7]}")
    print(f"  payout      : {r[8]}")
    print(f"  decision    : {r[9]}")
    print(f"  dec_reason  : {r[10]}")
    print(f"  rej_reason  : {r[11]}")
    print(f"  order_id    : {r[13]}")
    print(f"  result      : {r[14]}")
    print(f"  profit      : {r[15]}")
    print(f"  created_at  : {r[16]}")
    if r[12]:
        try:
            sd = json.loads(r[12])
            print(f"\n  === strategy_details ===")
            print(json.dumps(sd, indent=4))
        except:
            print(f"  strategy_details (raw): {r[12]}")

# También buscar por asset MSFT
print("\n\n=== Busqueda adicional por asset MSFT/Microsoft ===")
cur.execute("""
SELECT id, ts, strategy, asset, direction, score, decision, order_id, order_result, profit, strategy_details
FROM scan_candidates
WHERE LOWER(asset) LIKE '%msft%' OR LOWER(asset) LIKE '%microsoft%'
ORDER BY ts DESC LIMIT 10
""")
msft_rows = cur.fetchall()
print(f"Encontrados por asset: {len(msft_rows)}")
for r in msft_rows:
    print(f"  {r[1]} | {r[3]:20s} | {r[2]:8s} | {r[4]:4s} | score={r[5]} | {r[6]:20s} | order={r[7]} | {r[8]} | profit={r[9]}")
    if r[10]:
        try:
            sd = json.loads(r[10])
            det = sd.get('detalle', sd)
            print(f"    raw_score={sd.get('raw_score')} source={sd.get('source')} rsi={det.get('rsi')} atr={det.get('atr')} wick_ratio={det.get('wick_ratio')}")
        except:
            pass

conn.close()
