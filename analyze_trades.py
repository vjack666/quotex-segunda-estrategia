#!/usr/bin/env python3
import sqlite3
from pathlib import Path

db_path = Path("data/db/trade_journal-2026-05-02.db")
conn = sqlite3.connect(str(db_path))
conn.row_factory = sqlite3.Row

c = conn.cursor()

# Obtener últimos 10 trades con order_id
c.execute("""
    SELECT 
        id,
        asset,
        direction,
        outcome,
        profit,
        ticket_open_price,
        ticket_close_price,
        ticket_opened_at,
        ticket_duration_sec,
        ticket_price_diff,
        pre_objectives_ok
    FROM candidates 
    WHERE order_id IS NOT NULL
    ORDER BY ticket_opened_at DESC
    LIMIT 10
""")

rows = c.fetchall()

if not rows:
    print("❌ No hay trades ejecutados en la base de datos")
else:
    print(f"\n✅ TRADES EJECUTADOS ({len(rows)}):\n")
    total_profit = 0
    for i, r in enumerate(rows, 1):
        outcome_emoji = "🟢 WIN" if r["outcome"] == "win" else "🔴 LOSS" if r["outcome"] == "loss" else "⏸️  PENDING"
        print(f"{i}. {r['asset']:15} {r['direction']:4} | {outcome_emoji} | Profit: ${r['profit']:+.2f}")
        open_p = r['ticket_open_price'] or 0
        close_p = r['ticket_close_price'] or 0
        dur = r['ticket_duration_sec'] or 0
        diff = r['ticket_price_diff'] or 0
        print(f"   Open:  ${open_p:.6f} | Close: ${close_p:.6f}")
        print(f"   Time:  {r['ticket_opened_at']}")
        print(f"   Duration: {dur}s | Diff: {diff:+.6f}")
        print(f"   Objectives Met: {r['pre_objectives_ok']}")
        print()
        total_profit += (r['profit'] or 0)
    
    print(f"💰 Total Profit: ${total_profit:+.2f}")

conn.close()
