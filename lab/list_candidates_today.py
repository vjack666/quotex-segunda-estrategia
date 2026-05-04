"""Lista los activos que llegaron a candidatos hoy y sus scores máximos."""
import sqlite3
import glob

dbs = sorted(glob.glob("data/db/trade_journal-*.db"), reverse=True)
db = dbs[0]
con = sqlite3.connect(db)
cur = con.cursor()

print(f"DB: {db}\n")

# Assets únicos con sus scores
print("--- ACTIVOS EN CANDIDATOS (score > 0) ---")
try:
    cur.execute("""
        SELECT asset, direction, score, entry_mode, stage, decision, reject_reason
        FROM candidates
        ORDER BY score DESC
    """)
    rows = cur.fetchall()
    assets_seen = set()
    for r in rows:
        key = (r[0], r[1])
        if key not in assets_seen:
            assets_seen.add(key)
            print(f"  {r[0]:25s} {r[1]:4s} score={r[2]:6.1f} mode={r[3] or '':20s} stage={r[4] or '':20s} | {r[5]:20s} | {r[6] or ''}")
except Exception as e:
    print("Error:", e)

print("\n--- ACTIVOS ÚNICOS QUE LLEGARON A CANDIDATOS ---")
cur.execute("SELECT DISTINCT asset FROM candidates ORDER BY asset")
assets = [r[0] for r in cur.fetchall()]
print(", ".join(assets))
print(f"\nTotal: {len(assets)} activos")

con.close()
