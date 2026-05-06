#!/usr/bin/env python3
"""Lectura completa de la caja negra STRAT-C."""
import sqlite3
import glob
from datetime import datetime, timezone

db = sqlite3.connect(glob.glob("data/db/black_box_strat_*.db")[-1])
c = db.cursor()

# ── Resumen general ──────────────────────────────────────────────
c.execute("SELECT COUNT(*) FROM scans WHERE strategy='C'")
total_scans = c.fetchone()[0]

c.execute("SELECT COUNT(*) FROM scan_candidates WHERE strategy='C'")
total_candidates = c.fetchone()[0]

print("=" * 62)
print("📦 CAJA NEGRA — STRAT-C (sesión limpia)")
print("=" * 62)
print(f"  Scans registrados : {total_scans}")
print(f"  Candidatos total  : {total_candidates}")
print(f"  Ratio cand/scan   : {total_candidates/max(total_scans,1):.2f}")

# ── Breakdown de decisiones ──────────────────────────────────────
print("\n📊 DECISIONES:")
c.execute("""
    SELECT decision, COUNT(*) 
    FROM scan_candidates WHERE strategy='C'
    GROUP BY decision ORDER BY COUNT(*) DESC
""")
for decision, cnt in c.fetchall():
    pct = cnt / max(total_candidates, 1) * 100
    print(f"  {decision:25} {cnt:4d}  ({pct:.0f}%)")

# ── Trades ejecutados en broker ──────────────────────────────────
c.execute("""
    SELECT id, asset, direction, order_id, order_result, profit, created_at
    FROM scan_candidates
    WHERE strategy='C'
      AND order_id IS NOT NULL
      AND order_id != ''
      AND length(order_id) > 10
    ORDER BY created_at ASC
""")
trades = c.fetchall()

wins   = [t for t in trades if t[4] == "WIN"]
losses = [t for t in trades if t[4] == "LOSS"]
unres  = [t for t in trades if t[4] not in ("WIN","LOSS")]
resolved = wins + losses
winrate = len(wins)/len(resolved)*100 if resolved else 0.0

print(f"\n🎯 TRADES EJECUTADOS EN BROKER: {len(trades)}")
print(f"  WIN  : {len(wins)}")
print(f"  LOSS : {len(losses)}")
print(f"  Pendientes/No resueltos: {len(unres)}")
print(f"\n  Winrate  : {winrate:.1f}%  ({len(wins)}W / {len(losses)}L)")
pnl = sum(t[5] or 0 for t in resolved)
print(f"  P&L neto : ${pnl:.2f}")

if resolved:
    avg_win  = sum(t[5] or 0 for t in wins) / len(wins) if wins else 0
    avg_loss = sum(abs(t[5] or 0) for t in losses) / len(losses) if losses else 0
    rr = avg_win / avg_loss if avg_loss else float('inf')
    print(f"  Avg WIN  : ${avg_win:.2f}  |  Avg LOSS: ${avg_loss:.2f}  |  R:R = {rr:.2f}")

# ── Detalle de cada trade ────────────────────────────────────────
print(f"\n🔎 DETALLE POR TRADE:")
print(f"  {'Hora':5} | {'Asset':12} {'Dir':4} | {'Resultado':10} | {'P&L':8} | {'Order ID':8}")
print(f"  {'-'*58}")
for cid, asset, direction, order_id, result, profit, created in trades:
    ts = created[11:16] if created else "?"
    result_str = result or "PENDING"
    profit_str = f"${profit:.2f}" if profit else "$0.00"
    oid_short = order_id[:8] + "..." if order_id and len(order_id) > 8 else (order_id or "-")
    print(f"  {ts} | {asset:12} {direction:4} | {result_str:10} | {profit_str:8} | {oid_short}")

# ── Por dirección ────────────────────────────────────────────────
print(f"\n📊 WINRATE POR DIRECCIÓN:")
for direction in ("call", "put"):
    dir_r = [t for t in resolved if t[2] == direction]
    dir_w = [t for t in dir_r if t[4] == "WIN"]
    wr = len(dir_w)/len(dir_r)*100 if dir_r else 0
    print(f"  {direction.upper():4}: {len(dir_w)}/{len(dir_r)} = {wr:.0f}%  WR")

# ── Por activo ───────────────────────────────────────────────────
if resolved:
    print(f"\n📊 WINRATE POR ACTIVO:")
    c.execute("""
        SELECT asset, 
               COUNT(*) as total,
               SUM(CASE WHEN order_result='WIN' THEN 1 ELSE 0 END) as wins
        FROM scan_candidates
        WHERE strategy='C' 
          AND order_id IS NOT NULL AND order_id != '' AND length(order_id) > 10
          AND order_result IN ('WIN','LOSS')
        GROUP BY asset
        ORDER BY total DESC
    """)
    for asset, total, w in c.fetchall():
        wr = w/total*100 if total else 0
        bar = "█" * w + "░" * (total - w)
        print(f"  {asset:15} {w}/{total} = {wr:.0f}%  [{bar}]")

# ── Timeline ─────────────────────────────────────────────────────
print(f"\n⏱️  ACTIVIDAD POR MINUTO (ejecutados):")
c.execute("""
    SELECT strftime('%H:%M', created_at) as minute,
           COUNT(*) as total,
           SUM(CASE WHEN order_result='WIN' THEN 1 ELSE 0 END) as wins,
           SUM(CASE WHEN order_result='LOSS' THEN 1 ELSE 0 END) as losses
    FROM scan_candidates
    WHERE strategy='C'
      AND order_id IS NOT NULL AND order_id != '' AND length(order_id) > 10
    GROUP BY minute
    ORDER BY minute ASC
""")
for minute, total, w, l in c.fetchall():
    status = f"{w}W/{l}L" if (w or l) else "PENDING"
    print(f"  {minute}  →  {total} trade(s)  [{status}]")

db.close()
print("\n" + "=" * 62)
