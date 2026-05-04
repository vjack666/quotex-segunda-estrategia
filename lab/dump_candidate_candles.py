"""
Extrae las velas de todos los activos candidatos del journal de hoy
y las guarda como CSVs en data/candles_candidatos/.
También genera un resumen de scores y decisiones.
"""
import sqlite3
import glob
import json
import csv
import os
from datetime import datetime
from collections import defaultdict

# ── Config ──────────────────────────────────────────────────────────────────
OUT_DIR = "data/candles_candidatos"
os.makedirs(OUT_DIR, exist_ok=True)

dbs = sorted(glob.glob("data/db/trade_journal-*.db"), reverse=True)
if not dbs:
    print("Sin base de datos de journal.")
    exit()

db = dbs[0]
print(f"DB: {db}")
con = sqlite3.connect(db)
con.row_factory = sqlite3.Row
cur = con.cursor()

# ── Extraer todos los candidatos ─────────────────────────────────────────────
cur.execute("""
    SELECT asset, direction, score, stage, decision, reject_reason,
           candles_json, strategy_json, scanned_at,
           zone_ceiling, zone_floor, reversal_pattern, reversal_strength
    FROM candidates
    ORDER BY asset, score DESC
""")
rows = cur.fetchall()
con.close()

# Agrupar por activo: tomar el de mayor score por asset+direction
best = {}
all_candles = defaultdict(list)  # asset → lista de barras

for row in rows:
    key = (row["asset"], row["direction"])
    if key not in best or row["score"] > best[key]["score"]:
        best[key] = dict(row)

    # Acumular velas (deduplicate por ts)
    if row["candles_json"]:
        try:
            candles = json.loads(row["candles_json"])
            existing_ts = {c["ts"] for c in all_candles[row["asset"]]}
            for c in candles:
                if c["ts"] not in existing_ts:
                    all_candles[row["asset"]].append(c)
                    existing_ts.add(c["ts"])
        except Exception:
            pass

# ── Resumen de scores ────────────────────────────────────────────────────────
print(f"\n{'ACTIVO':25s} {'DIR':4s} {'SCORE':6s} {'STAGE':20s} {'DECISIÓN':25s}  RAZÓN")
print("─" * 110)

for (asset, direction), row in sorted(best.items(), key=lambda x: -x[1]["score"]):
    score = row["score"]
    stage = row["stage"] or ""
    decision = row["decision"] or ""
    reason = (row["reject_reason"] or "")[:60]
    reversal = row["reversal_pattern"] or "none"
    marker = "✅" if decision == "ACCEPTED" else ("⛔" if "STRUCTURE" in decision else "❌")
    print(f"{marker} {asset:25s} {direction:4s} {score:6.1f} {stage:20s} {decision:25s}  {reason}")

print(f"\nTotal activos únicos con candidatos: {len(set(k[0] for k in best))}")
accepted = [r for r in best.values() if r["decision"] == "ACCEPTED"]
print(f"Aceptados: {len(accepted)}")

# ── Guardar velas por activo ─────────────────────────────────────────────────
print(f"\n── Guardando velas en {OUT_DIR}/ ──")
saved = 0
for asset, candles in sorted(all_candles.items()):
    if not candles:
        continue
    candles.sort(key=lambda c: c["ts"])
    fname = os.path.join(OUT_DIR, f"candles_1m_{asset}.csv")
    with open(fname, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["ts", "datetime", "open", "high", "low", "close"])
        writer.writeheader()
        for c in candles:
            dt = datetime.fromtimestamp(c["ts"]).strftime("%Y-%m-%d %H:%M:%S")
            writer.writerow({
                "ts": c["ts"],
                "datetime": dt,
                "open": c.get("open", ""),
                "high": c.get("high", ""),
                "low": c.get("low", ""),
                "close": c.get("close", ""),
            })
    saved += 1
    bars = len(candles)
    print(f"  {asset:25s}: {bars:3d} barras 1m → {fname}")

print(f"\nTotal CSVs guardados: {saved}")

# ── Análisis de score_breakdown del mejor candidato por activo ───────────────
print("\n── DESGLOSE DE SCORES (mejor por activo) ──")
print(f"{'ACTIVO':25s} {'DIR':4s} {'TOT':6s} {'compr':6s} {'bounce':6s} {'trend':6s} {'payout':6s} {'other':7s} {'reversal':8s} {'stage':18s}")
print("─" * 100)
for (asset, direction), row in sorted(best.items(), key=lambda x: -x[1]["score"]):
    try:
        sj = json.loads(row["strategy_json"] or "{}")
        bd = sj.get("pattern_snapshot", {}).get("score_breakdown", {})
        compr = bd.get("compression", 0)
        bounce = bd.get("bounce", bd.get("momentum", 0))
        trend = bd.get("trend", 0)
        payout = bd.get("payout", 0)
        reversal_b = bd.get("reversal_bonus", 0)
        others = {k: v for k, v in bd.items()
                  if k not in ("compression", "bounce", "momentum", "trend", "payout", "reversal_bonus")}
        other_sum = sum(others.values())
        stage = row["stage"] or ""
        print(f"  {asset:25s} {direction:4s} {row['score']:6.1f} {compr:6.1f} {bounce:6.1f} {trend:6.1f} {payout:6.1f} {other_sum:7.1f} {reversal_b:8.1f} {stage:18s}")
    except Exception:
        print(f"  {asset:25s} (sin breakdown)")
