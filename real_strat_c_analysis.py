#!/usr/bin/env python3
"""Análisis REAL de STRAT-C: solo trades ejecutados (con UUID en broker)."""
import sqlite3
import glob

db = sqlite3.connect(glob.glob("data/db/black_box_strat_*.db")[-1])
c = db.cursor()

print("=" * 60)
print("📊 ANÁLISIS REAL STRAT-C (solo trades ejecutados en broker)")
print("=" * 60)

# Solo trades con UUID válido (ejecutados en broker)
c.execute('''
    SELECT id, asset, direction, order_id, order_result, profit, created_at
    FROM scan_candidates 
    WHERE strategy = "C" 
      AND order_id IS NOT NULL 
      AND order_id != "" 
      AND length(order_id) > 10
    ORDER BY created_at ASC
''')

trades = c.fetchall()
print(f"\n📌 Total trades ejecutados en broker: {len(trades)}")

wins = [t for t in trades if t[4] == "WIN"]
losses = [t for t in trades if t[4] == "LOSS"]
pending = [t for t in trades if t[4] is None or t[4] == "PENDING" or t[4] == "UNRESOLVED"]

print(f"  WIN: {len(wins)}")
print(f"  LOSS: {len(losses)}")
print(f"  PENDING/UNRESOLVED: {len(pending)}")

resolved = [t for t in trades if t[4] in ("WIN", "LOSS")]
winrate = len(wins) / len(resolved) * 100 if resolved else 0.0

print(f"\n✅ Winrate (resueltos): {winrate:.1f}% ({len(wins)}W/{len(losses)}L)")

total_profit = sum(t[5] or 0 for t in resolved)
print(f"💰 P&L Total: ${total_profit:.2f}")

print(f"\n🔎 DETALLE DE TRADES:")
for cid, asset, direction, order_id, result, profit, created in trades:
    ts = created[:16] if created else "?"
    result_str = result or "PENDING"
    profit_str = f"${profit:.2f}" if profit else "$0.00"
    oid_short = order_id[:8] + "..." if len(order_id) > 8 else order_id
    print(f"  {ts} | {asset:12} {direction:4} | {result_str:10} | {profit_str:8} | {oid_short}")

print(f"\n📊 POR DIRECCIÓN:")
for direction in ("call", "put"):
    dir_trades = [t for t in resolved if t[2] == direction]
    dir_wins = [t for t in dir_trades if t[4] == "WIN"]
    dir_wr = len(dir_wins) / len(dir_trades) * 100 if dir_trades else 0
    print(f"  {direction.upper()}: {len(dir_wins)}/{len(dir_trades)} = {dir_wr:.1f}% WR")

db.close()
