"""
Resumen financiero y diagnóstico completo de la sesión de hoy.
"""
import sqlite3, glob, json
from collections import defaultdict

dbs = sorted(glob.glob('data/db/trade_journal-*.db'), reverse=True)
db = dbs[0]
con = sqlite3.connect(db)
con.row_factory = sqlite3.Row
cur = con.cursor()
cur.execute('''
    SELECT scanned_at, asset, direction, score, decision, reject_reason,
           reversal_pattern, outcome, profit, amount,
           ticket_open_price, ticket_close_price, strategy_json
    FROM candidates
    ORDER BY scanned_at ASC
''')
rows = cur.fetchall()
con.close()

accepted = [r for r in rows if r["decision"] == "ACCEPTED"]

print("=" * 70)
print("CAJA NEGRA — RESUMEN COMPLETO")
print("=" * 70)
print(f"Total candidatos procesados: {len(rows)}")
print(f"  ✅ Aceptados:         {sum(1 for r in rows if r['decision']=='ACCEPTED')}")
print(f"  ❌ Rechazados score:  {sum(1 for r in rows if r['decision']=='REJECTED_SCORE')}")
print(f"  🔒 Rechazados límite: {sum(1 for r in rows if r['decision']=='REJECTED_LIMIT')}")
print(f"  ⛔ Rechazados struct: {sum(1 for r in rows if r['decision']=='REJECTED_STRUCTURE')}")

# Resultados de las 15 ops
print("\n── OPERACIONES ACEPTADAS ──")
total_profit = 0.0
wins = losses = unresolved = 0
for r in accepted:
    outcome = r["outcome"] or "?"
    profit = float(r["profit"] or 0)
    amount = float(r["amount"] or 0)
    reversal = r["reversal_pattern"] or "none"
    score = r["score"]
    sj = json.loads(r["strategy_json"] or "{}")
    ps = sj.get("pattern_snapshot", {})
    bd = ps.get("score_breakdown", {})
    ma_filter = bd.get("ma_filter", 0)
    wc = bd.get("weak_confirmation", 0)
    rev_pen = bd.get("reversal_penalty", 0)
    icon = {"WIN": "✅", "LOSS": "❌", "PENDING": "⏳", "UNRESOLVED": "❓"}.get(outcome, "?")
    if outcome == "WIN": wins += 1; total_profit += profit
    elif outcome == "LOSS": losses += 1; total_profit += profit
    else: unresolved += 1
    flags = []
    if ma_filter <= -30: flags.append(f"⚠MA={ma_filter}")
    if wc == -10: flags.append("weak_conf=-10")
    if rev_pen == -15: flags.append("rev_pen=-15")
    if score < 0: flags.append("SCORE NEG!")
    flag_str = "  " + " ".join(flags) if flags else ""
    print(f"  {icon} {r['scanned_at'][11:16]} {r['asset']:20s} {r['direction']:4s} score={score:5.1f} rev={reversal:20s} profit={profit:+.2f}{flag_str}")

print(f"\nRESULTADO FINANCIERO:")
print(f"  Ganadas:       {wins}")
print(f"  Perdidas:      {losses}")
print(f"  Sin resolver:  {unresolved}")
print(f"  P&L cerradas:  {total_profit:+.2f}")

# Análisis de problemas
print("\n── PROBLEMAS DETECTADOS ──")

print("\n[P1] Entradas con score NEGATIVO o muy bajo:")
for r in accepted:
    if r["score"] < 20:
        sj = json.loads(r["strategy_json"] or "{}")
        bd = sj.get("pattern_snapshot", {}).get("score_breakdown", {})
        outcome = r["outcome"]
        print(f"  {r['asset']:20s} score={r['score']:5.1f}  outcome={outcome}  breakdown={json.dumps(bd)}")

print("\n[P2] MA_filter extremo (≤-30) que no bloqueó la entrada:")
for r in accepted:
    sj = json.loads(r["strategy_json"] or "{}")
    bd = sj.get("pattern_snapshot", {}).get("score_breakdown", {})
    if bd.get("ma_filter", 0) <= -30:
        print(f"  {r['asset']:20s} score={r['score']:5.1f} ma_filter={bd['ma_filter']} outcome={r['outcome']} profit={r['profit']:.2f}")

print("\n[P3] UNRESOLVED — trades sin cerrar:")
for r in accepted:
    if r["outcome"] in ("UNRESOLVED", "PENDING"):
        print(f"  {r['scanned_at'][11:16]} {r['asset']:20s} score={r['score']:5.1f} outcome={r['outcome']}")

print("\n[P4] weak_confirmation=-10 en breakout (penaliza innecesariamente):")
wc_count = sum(
    1 for r in accepted
    if json.loads(r["strategy_json"] or "{}").get("pattern_snapshot", {}).get("score_breakdown", {}).get("weak_confirmation", 0) == -10.0
)
print(f"  {wc_count}/{len(accepted)} operaciones con -10 weak_confirmation en breakout")

print("\n[P5] Score más alto rechazado por STRUCTURE (perdido por cooldown):")
struct_rejected = [r for r in rows if r["decision"] == "REJECTED_STRUCTURE"]
for r in sorted(struct_rejected, key=lambda x: -x["score"])[:5]:
    print(f"  {r['asset']:20s} score={r['score']:5.1f}  {(r['reject_reason'] or '')[:70]}")

# Score distribution
print("\n── DISTRIBUCIÓN DE SCORES (todos los candidatos) ──")
buckets = defaultdict(int)
for r in rows:
    s = r["score"]
    if s < 0: buckets["<0"] += 1
    elif s < 30: buckets["0-29"] += 1
    elif s < 50: buckets["30-49"] += 1
    elif s < 65: buckets["50-64"] += 1
    elif s < 75: buckets["65-74"] += 1
    else: buckets["≥75"] += 1
for k in ["<0", "0-29", "30-49", "50-64", "65-74", "≥75"]:
    print(f"  {k:6s}: {buckets[k]:3d}")
