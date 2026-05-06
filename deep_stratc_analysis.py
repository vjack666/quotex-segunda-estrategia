#!/usr/bin/env python3
"""
DEEP STRAT-C ANALYSIS — Validación completa de STRAT-C para decisión de activación en real.
Analiza 92+ trades en demo para determinar si winrate >= 60% y rentabilidad es sostenible.
"""
import sqlite3
import glob
import json
from pathlib import Path
from collections import defaultdict

def load_db():
    db_files = glob.glob("data/db/black_box_strat_*.db")
    if not db_files:
        print("❌ BD no encontrada")
        exit(1)
    db_path = db_files[-1]
    return sqlite3.connect(db_path)

def analyze():
    db = load_db()
    c = db.cursor()
    
    # STRAT-C trades
    c.execute("""
        SELECT 
            id, asset, direction, score, confidence, payout, 
            order_result, profit, strategy_details, created_at
        FROM scan_candidates
        WHERE strategy = 'C'
        ORDER BY created_at ASC
    """)
    
    trades = c.fetchall()
    print(f"\n{'='*80}")
    print(f"  DEEP STRAT-C ANALYSIS — {len(trades)} TRADES")
    print(f"{'='*80}\n")
    
    if not trades:
        print("❌ Sin trades STRAT-C encontrados")
        exit(1)
    
    # 1. ESTADÍSTICAS BÁSICAS
    results = [t[6] for t in trades if t[6]]  # order_result
    wins = sum(1 for r in results if r == "WIN")
    losses = sum(1 for r in results if r == "LOSS")
    pending = len(trades) - wins - losses
    
    winrate = (wins / len(results)) * 100 if results else 0
    
    print(f"📊 RESUMEN BÁSICO:")
    print(f"  Total trades: {len(trades)}")
    print(f"  Completados: {len(results)} ({len(results)/len(trades)*100:.1f}%)")
    print(f"  Pendientes: {pending}")
    print(f"  Wins: {wins}")
    print(f"  Losses: {losses}")
    print(f"  ✅ WINRATE: {winrate:.1f}% {'✓ PASS (>=60%)' if winrate >= 60 else '✗ FAIL (<60%)'}\n")
    
    # 2. P&L
    profits = [t[7] or 0 for t in trades if t[6]]
    if profits:
        total_pl = sum(profits)
        avg_pl = total_pl / len(profits)
        max_pl = max(profits)
        min_pl = min(profits)
        
        print(f"💰 PROFIT & LOSS:")
        print(f"  Total P&L: ${total_pl:.2f}")
        print(f"  Avg P&L: ${avg_pl:.2f}")
        print(f"  Max win: ${max_pl:.2f}")
        print(f"  Max loss: ${min_pl:.2f}")
        print(f"  Profit factor: {sum(p for p in profits if p > 0) / abs(sum(p for p in profits if p < 0)) if sum(p for p in profits if p < 0) != 0 else float('inf'):.2f}\n")
    
    # 3. SCORE DISTRIBUTION
    scores = [t[3] for t in trades if t[3] is not None]
    if scores:
        avg_score = sum(scores) / len(scores)
        min_score = min(scores)
        max_score = max(scores)
        print(f"🎯 SCORE DISTRIBUTION (0-100):")
        print(f"  Avg: {avg_score:.1f}")
        print(f"  Min: {min_score:.1f}")
        print(f"  Max: {max_score:.1f}")
        
        # Score por resultado
        win_trades = [(t[3], t[7]) for t in trades if t[6] == "WIN" and t[3]]
        loss_trades = [(t[3], t[7]) for t in trades if t[6] == "LOSS" and t[3]]
        
        if win_trades:
            avg_win_score = sum(s for s, p in win_trades) / len(win_trades)
            print(f"  Avg score (WIN): {avg_win_score:.1f}")
        if loss_trades:
            avg_loss_score = sum(s for s, p in loss_trades) / len(loss_trades)
            print(f"  Avg score (LOSS): {avg_loss_score:.1f}\n")
    
    # 4. PAYOUT DISTRIBUTION
    payouts = [t[5] for t in trades if t[5]]
    if payouts:
        avg_payout = sum(payouts) / len(payouts)
        print(f"💵 PAYOUT DISTRIBUTION:")
        print(f"  Avg: {avg_payout:.0f}%")
        print(f"  Min: {min(payouts)}%")
        print(f"  Max: {max(payouts)}%\n")
    
    # 5. ASSET PERFORMANCE
    asset_stats = defaultdict(lambda: {"wins": 0, "losses": 0, "total": 0})
    for trade in trades:
        asset = trade[1]
        result = trade[6]
        if result:
            asset_stats[asset]["total"] += 1
            if result == "WIN":
                asset_stats[asset]["wins"] += 1
            else:
                asset_stats[asset]["losses"] += 1
    
    print(f"🏆 TOP 5 ASSETS BY WINRATE:")
    sorted_assets = sorted(
        asset_stats.items(),
        key=lambda x: x[1]["wins"] / x[1]["total"] if x[1]["total"] > 0 else 0,
        reverse=True
    )
    
    for i, (asset, stats) in enumerate(sorted_assets[:5], 1):
        wr = (stats["wins"] / stats["total"] * 100) if stats["total"] > 0 else 0
        print(f"  {i}. {asset:15} — {stats['wins']:2d}W/{stats['losses']:2d}L ({wr:5.1f}%)")
    
    print()
    
    # 6. DIRECTION PERFORMANCE
    call_stats = defaultdict(int)
    put_stats = defaultdict(int)
    
    for trade in trades:
        result = trade[6]
        direction = trade[2]
        if result == "WIN":
            if direction == "CALL":
                call_stats["wins"] += 1
            else:
                put_stats["wins"] += 1
        elif result == "LOSS":
            if direction == "CALL":
                call_stats["losses"] += 1
            else:
                put_stats["losses"] += 1
    
    print(f"📈 DIRECTION PERFORMANCE:")
    call_total = call_stats["wins"] + call_stats["losses"]
    put_total = put_stats["wins"] + put_stats["losses"]
    
    if call_total > 0:
        call_wr = call_stats["wins"] / call_total * 100
        print(f"  CALL: {call_stats['wins']}W/{call_stats['losses']}L ({call_wr:.1f}%)")
    
    if put_total > 0:
        put_wr = put_stats["wins"] / put_total * 100
        print(f"  PUT:  {put_stats['wins']}W/{put_stats['losses']}L ({put_wr:.1f}%)\n")
    
    # 7. DECISION
    print(f"{'='*80}")
    print(f"  DECISIÓN PARA ACTIVACIÓN EN REAL")
    print(f"{'='*80}\n")
    
    criteria = {
        "Winrate >= 60%": winrate >= 60.0,
        "Trades > 50": len(trades) >= 50,
        "Mínimo 30 completados": len(results) >= 30,
    }
    
    passed = sum(1 for v in criteria.values() if v)
    total_criteria = len(criteria)
    
    for criterion, result in criteria.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"  {status} — {criterion}")
    
    print(f"\n  Score: {passed}/{total_criteria}")
    
    if passed == total_criteria:
        print(f"\n  🟢 STRAT-C LISTO PARA ACTIVACIÓN EN REAL")
        print(f"  Recomendación: Activar con --strat-c-enabled en cuenta real")
    else:
        print(f"\n  🔴 STRAT-C NO CUMPLE CRITERIOS")
        print(f"  Recomendación: Continuar con demo hasta completar criterios")
    
    print(f"\n{'='*80}\n")
    
    db.close()

if __name__ == "__main__":
    analyze()
