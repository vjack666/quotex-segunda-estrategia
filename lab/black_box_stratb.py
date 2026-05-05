"""
Revisión detallada de caja negra STRAT-B.
Muestra todas las señales registradas: ACCEPTED, REJECTED_SCORE, REJECTED_LIMIT.
"""
import sqlite3, glob, json
from collections import Counter, defaultdict

dbs = sorted(glob.glob('data/db/trade_journal-*.db'), reverse=True)
db = dbs[0]
print(f'DB: {db}\n')
con = sqlite3.connect(db)
con.row_factory = sqlite3.Row
cur = con.cursor()

cur.execute('''
    SELECT scanned_at, asset, direction, score, decision, reject_reason,
           reversal_pattern, outcome, profit, amount, strategy_json
    FROM candidates
    ORDER BY scanned_at ASC
''')
rows = cur.fetchall()
con.close()

# Separar por estrategia
strat_a = []
strat_b = []
other   = []
for r in rows:
    try:
        sj = json.loads(r["strategy_json"] or "{}")
        origin = sj.get("strategy_origin", "STRAT-A")
    except Exception:
        origin = "STRAT-A"
    if origin == "STRAT-B":
        strat_b.append((r, sj))
    else:
        strat_a.append((r, sj))

print("=" * 70)
print(f"STRAT-A: {len(strat_a)} registros")
print(f"STRAT-B: {len(strat_b)} registros")
print("=" * 70)

# ── STRAT-A ─────────────────────────────────────────────────────────────────
print("\n╔══ STRAT-A ══════════════════════════════════════════════════════════╗")
a_dec = Counter(r["decision"] for r, _ in strat_a)
print(f"  Decisiones: {dict(a_dec)}")
a_outcomes = Counter(r["outcome"] or "?" for r, _ in strat_a if r["decision"] == "ACCEPTED")
print(f"  Outcomes ACCEPTED: {dict(a_outcomes)}")

a_accepted = [(r, sj) for r, sj in strat_a if r["decision"] == "ACCEPTED"]
a_wins = sum(1 for r, _ in a_accepted if r["outcome"] == "WIN")
a_losses = sum(1 for r, _ in a_accepted if r["outcome"] == "LOSS")
a_pnl = sum(float(r["profit"] or 0) for r, _ in a_accepted)
print(f"  W/L/Pendiente: {a_wins}/{a_losses}/{len(a_accepted)-a_wins-a_losses}")
print(f"  P&L cerradas: {a_pnl:+.2f}")

print(f"\n  {'HH:MM':5s} {'ACTIVO':20s} {'DIR':4s} {'SCORE':6s} {'OUTCOME':12s} {'PROFIT':8s}  REVERSAL")
for r, sj in a_accepted:
    icon = {"WIN":"✅","LOSS":"❌","PENDING":"⏳","UNRESOLVED":"❓"}.get(r["outcome"],"?")
    rev = r["reversal_pattern"] or "none"
    print(f"  {r['scanned_at'][11:16]:5s} {r['asset']:20s} {r['direction']:4s} {r['score']:6.1f} {icon}{r['outcome']:11s} {float(r['profit'] or 0):+8.2f}  {rev}")

# ── STRAT-B ─────────────────────────────────────────────────────────────────
print("\n╔══ STRAT-B ══════════════════════════════════════════════════════════╗")
if not strat_b:
    print("  ⚠ Sin registros STRAT-B en la DB de hoy.")
    print("  → El código nuevo del journal STRAT-B solo aplica a sesiones futuras.")
else:
    b_dec = Counter(r["decision"] for r, _ in strat_b)
    print(f"  Decisiones: {dict(b_dec)}")
    b_accepted = [(r, sj) for r, sj in strat_b if r["decision"] == "ACCEPTED"]
    b_wins = sum(1 for r, _ in b_accepted if r["outcome"] == "WIN")
    b_losses = sum(1 for r, _ in b_accepted if r["outcome"] == "LOSS")
    b_pnl = sum(float(r["profit"] or 0) for r, _ in b_accepted)
    print(f"  W/L/Pendiente: {b_wins}/{b_losses}/{len(b_accepted)-b_wins-b_losses}")
    print(f"  P&L cerradas: {b_pnl:+.2f}")

    print(f"\n  {'HH:MM':5s} {'ACTIVO':20s} {'DIR':4s} {'SCORE':6s} {'DECISIÓN':20s} {'OUTCOME':12s}  SEÑAL")
    for r, sj in strat_b:
        icon = {"ACCEPTED":"✅","REJECTED_SCORE":"❌","REJECTED_LIMIT":"🔒"}.get(r["decision"],"?")
        signal_type = sj.get("strat_b_signal_type", "?")
        conf = sj.get("strat_b_confidence", 0)
        outcome = r["outcome"] or ""
        reason_short = (r["reject_reason"] or "")[:60]
        print(f"  {r['scanned_at'][11:16]:5s} {r['asset']:20s} {r['direction']:4s} {r['score']:6.1f} {icon}{r['decision']:19s} {outcome:12s}  {signal_type} conf={conf*100:.0f}%")
        if reason_short:
            print(f"          {reason_short}")

    # Distribución de señales por tipo
    print(f"\n  Distribución señales detectadas:")
    sig_types = Counter(sj.get("strat_b_signal_type", "?") for _, sj in strat_b if sj.get("strat_b_is_signal"))
    for t, n in sig_types.most_common():
        print(f"    {t:35s}: {n}")

    # Near-miss stats
    b_nearmiss = [(r, sj) for r, sj in strat_b if r["outcome"] == "NO_SIGNAL"]
    print(f"\n  Near-miss (conf ≥ 45% pero sin señal confirmada): {len(b_nearmiss)}")
    b_low_conf = [(r, sj) for r, sj in strat_b if r["outcome"] == "LOW_CONF"]
    print(f"  Conf insuficiente (señal detectada, conf < req): {len(b_low_conf)}")
    b_blocked = [(r, sj) for r, sj in strat_b if r["outcome"] == "BLOCKED"]
    print(f"  Bloqueadas por slot lleno / gale: {len(b_blocked)}")

print("\n╔══ PROBLEMAS COMUNES ════════════════════════════════════════════════╗")
# UNRESOLVED
all_unresolved = [(r, sj) for r, sj in (strat_a + strat_b) if r["outcome"] in ("UNRESOLVED", "PENDING") and r["decision"] == "ACCEPTED"]
print(f"  Trades sin resolver en DB: {len(all_unresolved)}")
for r, _ in all_unresolved:
    print(f"    {r['scanned_at'][11:16]} {r['asset']:20s} score={r['score']:5.1f} → {r['outcome']}")

# Score neg pero entró
neg_score_accepted = [(r, sj) for r, sj in (strat_a + strat_b) if r["decision"]=="ACCEPTED" and r["score"] < 30]
print(f"\n  Entradas con score < 30 (zona de riesgo): {len(neg_score_accepted)}")
for r, sj in neg_score_accepted:
    origin = sj.get("strategy_origin","STRAT-A")
    print(f"    {r['scanned_at'][11:16]} {r['asset']:20s} score={r['score']:5.1f} outcome={r['outcome']:12s} origin={origin}")
