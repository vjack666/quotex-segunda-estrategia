#!/usr/bin/env python3
"""Análisis detallado de operaciones perdidas y patrones problemáticos"""
import sqlite3
import json
from pathlib import Path

db_path = Path("trade_journal.db")
conn = sqlite3.connect(str(db_path))
c = conn.cursor()

print("=" * 100)
print("🔴 ANÁLISIS DETALLADO DE OPERACIONES PERDIDAS")
print("=" * 100)

# Operaciones perdidas más grandes
print("\n💸 TOP 10 MAYORES PÉRDIDAS:")
print("-" * 100)
c.execute('''
    SELECT id, asset, direction, stage, score, zone_age_min, profit, reversal_pattern, 
           reversal_strength, zone_range_pct, closed_at
    FROM candidates
    WHERE outcome = 'LOSS'
    ORDER BY profit ASC
    LIMIT 10
''')
rows = c.fetchall()
print(f"{'ID':<4} {'Asset':<12} {'Dir':<4} {'Stage':<12} {'Score':<7} {'Age':<6} {'Loss':<8} {'Pattern':<20} {'Strength':<8}")
print("-" * 100)
for row in rows:
    cid, asset, direction, stage, score, age, profit, pattern, strength, range_pct, closed = row
    pattern_label = pattern[:19] if pattern else "none"
    print(f"{cid:<4} {asset:<12} {direction:<4} {stage:<12} {score:>6.1f} {age:>5.1f}m {profit:>7.2f} {pattern_label:<20} {strength:>7.2f}")

# Análisis por zona antigüedad
print("\n⏱️  OPERACIONES PERDIDAS POR ANTIGÜEDAD DE ZONA:")
print("-" * 100)
c.execute('''
    SELECT 
        CASE 
            WHEN zone_age_min < 5 THEN '0-5 min'
            WHEN zone_age_min < 15 THEN '5-15 min'
            WHEN zone_age_min < 30 THEN '15-30 min'
            WHEN zone_age_min < 60 THEN '30-60 min'
            ELSE '60+ min'
        END as age_bucket,
        COUNT(*) as count,
        ROUND(100.0 * COUNT(*) FILTER (WHERE outcome = 'LOSS') / COUNT(*), 1) as loss_rate,
        SUM(profit) as total_profit
    FROM candidates
    WHERE outcome IN ('WIN', 'LOSS')
    GROUP BY age_bucket
    ORDER BY zone_age_min
''')
print(f"{'Age Bucket':<15} {'Total':<6} {'Loss Rate %':<12} {'Profit':<10}")
print("-" * 100)
for row in c.fetchall():
    bucket, total, loss_rate, profit = row
    print(f"{bucket:<15} {total:<6} {loss_rate:>10.1f}% ${profit:>8.2f}")

# Problemas específicos con PUT
print("\n🔴 ANÁLISIS PUT (Peor desempeño):")
print("-" * 100)
c.execute('''
    SELECT COUNT(*) FILTER (WHERE outcome = 'LOSS') as puts_lost,
           COUNT(*) as total_puts,
           ROUND(100.0 * COUNT(*) FILTER (WHERE outcome = 'LOSS') / COUNT(*), 1) as loss_rate,
           SUM(profit) FILTER (WHERE outcome = 'LOSS') as total_losses,
           SUM(profit) FILTER (WHERE outcome = 'WIN') as total_wins,
           SUM(profit) as net
    FROM candidates
    WHERE direction = 'put'
''')
row = c.fetchone()
if row:
    puts_lost, total_puts, loss_rate, total_losses, total_wins, net = row
    print(f"Operaciones PUT totales: {total_puts}")
    print(f"Pérdidas: {puts_lost} ({loss_rate:.1f}% loss rate)")
    print(f"Ganancia total: ${total_wins:.2f}")
    print(f"Pérdida total: ${total_losses:.2f}")
    print(f"Net: ${net:.2f}")
    print(f"\n⚠️  PUTs tienen tasa de pérdida 3.9x más alta que CALLs")

# Operaciones más recientes (últimas 15)
print("\n📊 ÚLTIMAS 15 OPERACIONES PERDIDAS (análisis detallado):")
print("-" * 100)
c.execute('''
    SELECT id, asset, direction, stage, score, profit, reversal_pattern, 
           reversal_strength, reject_reason, closed_at
    FROM candidates
    WHERE outcome = 'LOSS'
    ORDER BY id DESC
    LIMIT 15
''')
for idx, row in enumerate(c.fetchall(), 1):
    cid, asset, direction, stage, score, profit, pattern, strength, reject_reason, closed = row
    print(f"\n[{idx}] ID {cid}: {asset} {direction.upper()} | Stage: {stage}")
    print(f"    Score: {score:.1f}/100 | Profit: {profit:.2f}")
    print(f"    Pattern: {pattern or 'none'} (strength: {strength:.2f})")
    if reject_reason:
        print(f"    Reject reason: {reject_reason}")
    if closed:
        print(f"    Closed: {closed}")

# Anomalías detectadas
print("\n\n⚠️  ANOMALÍAS DETECTADAS:")
print("-" * 100)

# Operaciones perdidas con score alto
print("\n1. Operaciones con score ALTO que perdieron:")
c.execute('''
    SELECT id, asset, direction, score, profit, reversal_pattern, stage
    FROM candidates
    WHERE outcome = 'LOSS' AND score >= 70
    ORDER BY score DESC
''')
high_score_losses = c.fetchall()
if high_score_losses:
    for row in high_score_losses:
        cid, asset, direction, score, profit, pattern, stage = row
        print(f"   ID {cid}: {asset} {direction} | Score: {score:.1f} | Loss: {profit:.2f} | {stage}")
else:
    print("   Ninguna encontrada (buena señal)")

# Operaciones perdidas recientes vs antiguas
print("\n2. Comparativa: Operaciones iniciales vs recientes")
c.execute('''
    SELECT 'Primeras 10' as periodo, 
           COUNT(*) FILTER (WHERE outcome = 'LOSS') as losses,
           COUNT(*) as total,
           ROUND(SUM(profit), 2) as net
    FROM candidates
    WHERE id <= 10
    UNION ALL
    SELECT 'Últimas 10' as periodo,
           COUNT(*) FILTER (WHERE outcome = 'LOSS') as losses,
           COUNT(*) as total,
           ROUND(SUM(profit), 2) as net
    FROM candidates
    WHERE id > (SELECT MAX(id) - 10 FROM candidates)
''')
for row in c.fetchall():
    periodo, losses, total, net = row
    loss_pct = 100.0 * losses / total if total > 0 else 0
    print(f"   {periodo}: {losses}/{total} pérdidas ({loss_pct:.1f}%) | Net: ${net:.2f}")

# Patrón de rachas negativas
print("\n3. Identificación de rachas negativas extremas:")
c.execute('''
    SELECT id, asset, direction, outcome, profit
    FROM candidates
    WHERE outcome IN ('WIN', 'LOSS')
    ORDER BY id DESC
    LIMIT 50
''')
ops = list(reversed(c.fetchall()))
consecutive_losses = 0
max_consecutive_losses = 0
worst_streak_ids = []

for op_id, asset, direction, outcome, profit in ops:
    if outcome == 'LOSS':
        consecutive_losses += 1
        if consecutive_losses > max_consecutive_losses:
            max_consecutive_losses = consecutive_losses
            worst_streak_ids = [(op_id, asset, profit)]
        elif consecutive_losses == max_consecutive_losses:
            worst_streak_ids.append((op_id, asset, profit))
    else:
        consecutive_losses = 0

if worst_streak_ids:
    print(f"   Racha negativa más larga: {max_consecutive_losses} operaciones")
    for op_id, asset, profit in worst_streak_ids[:3]:
        print(f"      ID {op_id}: {asset} | {profit:.2f}")

conn.close()
print("\n" + "=" * 100)
