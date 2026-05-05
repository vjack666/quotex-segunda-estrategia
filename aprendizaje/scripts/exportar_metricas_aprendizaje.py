import csv
import glob
import json
import os
import sqlite3
from collections import Counter
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(__file__))
WORKSPACE = os.path.dirname(ROOT)
DB_GLOB = os.path.join(WORKSPACE, "data", "db", "trade_journal-*.db")
OUT_DIR = os.path.join(ROOT, "reportes")
os.makedirs(OUT_DIR, exist_ok=True)

dbs = sorted(glob.glob(DB_GLOB), reverse=True)
if not dbs:
    print("No hay DB de journal en data/db")
    raise SystemExit(0)

db = dbs[0]
con = sqlite3.connect(db)
con.row_factory = sqlite3.Row
cur = con.cursor()
cur.execute(
    """
    SELECT scanned_at, asset, direction, score, decision, outcome, profit, strategy_json
    FROM candidates
    ORDER BY scanned_at ASC
    """
)
rows = cur.fetchall()
con.close()

if not rows:
    print("La DB existe pero no tiene candidatos.")
    raise SystemExit(0)

by_origin = {
    "STRAT-A": [],
    "STRAT-B": [],
}

for r in rows:
    sj = {}
    try:
        sj = json.loads(r["strategy_json"] or "{}")
    except Exception:
        sj = {}
    origin = sj.get("strategy_origin", "STRAT-A")
    if origin not in by_origin:
        by_origin[origin] = []
    by_origin[origin].append(r)

ts = datetime.now().strftime("%Y%m%d_%H%M%S")
out_csv = os.path.join(OUT_DIR, f"metricas_{ts}.csv")

with open(out_csv, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow([
        "estrategia",
        "total_registros",
        "accepted",
        "rejected_score",
        "rejected_limit",
        "rejected_structure",
        "wins",
        "losses",
        "unresolved_or_pending",
        "pnl_cerradas",
        "score_promedio_accepted",
    ])

    for origin, items in by_origin.items():
        decisions = Counter(r["decision"] for r in items)
        accepted = [r for r in items if r["decision"] == "ACCEPTED"]
        wins = sum(1 for r in accepted if r["outcome"] == "WIN")
        losses = sum(1 for r in accepted if r["outcome"] == "LOSS")
        unresolved = sum(1 for r in accepted if r["outcome"] in ("UNRESOLVED", "PENDING"))
        pnl = sum(float(r["profit"] or 0.0) for r in accepted if r["outcome"] in ("WIN", "LOSS"))
        avg_score = 0.0
        if accepted:
            avg_score = sum(float(r["score"] or 0.0) for r in accepted) / len(accepted)

        w.writerow([
            origin,
            len(items),
            decisions.get("ACCEPTED", 0),
            decisions.get("REJECTED_SCORE", 0),
            decisions.get("REJECTED_LIMIT", 0),
            decisions.get("REJECTED_STRUCTURE", 0),
            wins,
            losses,
            unresolved,
            round(pnl, 4),
            round(avg_score, 2),
        ])

print(f"Reporte generado: {out_csv}")
print(f"DB analizada: {db}")
