#!/usr/bin/env python3
"""Analizador de caja negra - Revisar operaciones ganadas y perdidas"""
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

db_path = Path("trade_journal.db")
if not db_path.exists():
    print("❌ Base de datos no encontrada")
    exit(1)

conn = sqlite3.connect(str(db_path))
c = conn.cursor()

print("=" * 90)
print("📊 ANÁLISIS DE CAJA NEGRA - OPERACIONES GANADAS Y PERDIDAS")
print("=" * 90)

# Resumen general
print("\n🎯 RESUMEN POR RESULTADO:")
print("-" * 90)
c.execute('''
    SELECT outcome, COUNT(*) as count, SUM(profit) as total_profit, 
           ROUND(AVG(profit), 2) as avg_profit, MIN(profit) as min, MAX(profit) as max
    FROM candidates
    WHERE outcome IN ('WIN', 'LOSS')
    GROUP BY outcome
    ORDER BY outcome DESC
''')
for row in c.fetchall():
    outcome, count, total, avg, min_p, max_p = row
    status = "✅ GANANCIAS" if outcome == "WIN" else "❌ PÉRDIDAS"
    print(f"{status:20s} | {count:3d} ops | Total: ${total:8.2f} | Avg: ${avg:7.2f} | Range: ${min_p:7.2f} a ${max_p:7.2f}")

# Win rate
print("\n📈 TASA DE GANANCIA:")
print("-" * 90)
c.execute('''
    SELECT 
        COUNT(*) FILTER (WHERE outcome = 'WIN') as wins,
        COUNT(*) FILTER (WHERE outcome = 'LOSS') as losses,
        COUNT(*) as total,
        ROUND(100.0 * COUNT(*) FILTER (WHERE outcome = 'WIN') / COUNT(*), 1) as win_rate
    FROM candidates
    WHERE outcome IN ('WIN', 'LOSS')
''')
wins, losses, total, wr = c.fetchone()
print(f"Ganadas: {wins:3d} | Perdidas: {losses:3d} | Total: {total:3d} | Win Rate: {wr:5.1f}%")

# Últimas 20 operaciones
print("\n📋 ÚLTIMAS 20 OPERACIONES:")
print("-" * 90)
c.execute('''
    SELECT id, asset, direction, decision, outcome, profit, stage,
           scanned_at, closed_at
    FROM candidates
    WHERE outcome IN ('WIN', 'LOSS')
    ORDER BY id DESC LIMIT 20
''')
rows = c.fetchall()
print(f"{'ID':>4} {'Asset':<12} {'Dir':<4} {'Stage':<10} {'Status':<6} {'Profit':>8} {'Decision':<10}")
print("-" * 90)
for row in rows:
    cand_id, asset, direction, decision, outcome, profit, stage, scanned, closed = row
    status = "✅ WIN " if outcome == "WIN" else "❌ LOSS"
    stage_label = stage[:9] if stage else "unknown"
    dec_label = decision[:9] if decision else "unknown"
    print(f"{cand_id:4d} {asset[:12]:<12} {direction:<4} {stage_label:<10} {status:<6} ${profit:>7.2f} {dec_label:<10}")

# Análisis por dirección
print("\n🔍 ANÁLISIS POR DIRECCIÓN:")
print("-" * 90)
c.execute('''
    SELECT direction, outcome, COUNT(*) as count, ROUND(SUM(profit), 2) as total_profit
    FROM candidates
    WHERE outcome IN ('WIN', 'LOSS')
    GROUP BY direction, outcome
    ORDER BY direction, outcome DESC
''')
for row in c.fetchall():
    direction, outcome, count, total = row
    dir_label = "CALL (🔵)" if direction == "call" else "PUT (🔴)"
    status = "✅" if outcome == "WIN" else "❌"
    print(f"{dir_label:<15} {status} {outcome:<4} | {count:3d} ops | ${total:8.2f}")

# Análisis por activo (Top 10 por volumen)
print("\n💰 TOP 10 ACTIVOS MÁS OPERADOS:")
print("-" * 90)
c.execute('''
    SELECT asset, 
           COUNT(*) FILTER (WHERE outcome = 'WIN') as wins,
           COUNT(*) FILTER (WHERE outcome = 'LOSS') as losses,
           COUNT(*) as total,
           SUM(profit) as total_profit,
           ROUND(100.0 * COUNT(*) FILTER (WHERE outcome = 'WIN') / COUNT(*), 1) as win_rate
    FROM candidates
    WHERE outcome IN ('WIN', 'LOSS')
    GROUP BY asset
    ORDER BY total DESC
    LIMIT 10
''')
print(f"{'Asset':<12} {'Wins':<5} {'Losses':<7} {'Total':<6} {'W/R %':<7} {'Profit':<10}")
print("-" * 90)
for row in c.fetchall():
    asset, wins, losses, total, total_profit, wr = row
    print(f"{asset:<12} {wins:<5} {losses:<7} {total:<6} {wr:>6.1f}% ${total_profit:>8.2f}")

# Análisis por patrones de entrada (solo operaciones recientes)
print("\n🎲 ANÁLISIS POR ETAPA (últimas 100 ops):")
print("-" * 90)
c.execute('''
    SELECT stage, 
           COUNT(*) FILTER (WHERE outcome = 'WIN') as wins,
           COUNT(*) FILTER (WHERE outcome = 'LOSS') as losses,
           COUNT(*) as total,
           SUM(profit) as total_profit,
           ROUND(100.0 * COUNT(*) FILTER (WHERE outcome = 'WIN') / COUNT(*), 1) as win_rate
    FROM candidates
    WHERE outcome IN ('WIN', 'LOSS')
      AND id > (SELECT MAX(id) - 100 FROM candidates)
    GROUP BY stage
    ORDER BY total DESC
''')
rows = c.fetchall()
if rows:
    print(f"{'Stage':<20} {'Wins':<5} {'Losses':<7} {'Total':<6} {'W/R %':<7} {'Profit':<10}")
    print("-" * 90)
    for row in rows:
        stage, wins, losses, total, total_profit, wr = row
        stage_label = stage[:19] if stage else "unknown"
        print(f"{stage_label:<20} {wins:<5} {losses:<7} {total:<6} {wr:>6.1f}% ${total_profit:>8.2f}")
else:
    print("Sin datos de stage en base de datos")

# Análisis de racha
print("\n🔗 ANÁLISIS DE RACHAS (últimas 30 operaciones):")
print("-" * 90)
c.execute('''
    SELECT id, outcome, profit
    FROM candidates
    WHERE outcome IN ('WIN', 'LOSS')
    ORDER BY id DESC
    LIMIT 30
''')
ops = list(reversed(c.fetchall()))
if ops:
    consecutive_wins = 0
    consecutive_losses = 0
    max_consecutive_wins = 0
    max_consecutive_losses = 0
    max_profit_streak = []
    current_streak = []
    
    for op_id, outcome, profit in ops:
        if outcome == "WIN":
            consecutive_wins += 1
            consecutive_losses = 0
            max_consecutive_wins = max(max_consecutive_wins, consecutive_wins)
        else:
            consecutive_losses += 1
            consecutive_wins = 0
            max_consecutive_losses = max(max_consecutive_losses, consecutive_losses)
        
        current_streak.append((outcome, profit))
    
    print(f"Máxima racha de ganancias: {max_consecutive_wins} operaciones")
    print(f"Máxima racha de pérdidas: {max_consecutive_losses} operaciones")
    print(f"Racha actual: {'GANADORAS' if consecutive_wins > 0 else 'PERDEDORAS'} ({max(consecutive_wins, consecutive_losses)} ops)")
    
    # Mostrar últimas 10 operaciones en secuencia
    print(f"\nÚltimas 10 operaciones (más reciente a la derecha):")
    recent_10 = ops[-10:]
    sequence = " -> ".join(["✅" if o[1] == "WIN" else "❌" for o in recent_10])
    print(f"{sequence}")

# Estadísticas de balance
print("\n💳 IMPACTO EN BALANCE:")
print("-" * 90)
c.execute('SELECT SUM(profit) FROM candidates WHERE outcome IN ("WIN", "LOSS")')
total_net = c.fetchone()[0] or 0.0
print(f"Ganancia/Pérdida neta: ${total_net:+.2f}")

c.execute('SELECT profit FROM candidates WHERE outcome = "WIN" ORDER BY profit DESC LIMIT 1')
max_win = c.fetchone()
max_win = max_win[0] if max_win else 0.0
c.execute('SELECT profit FROM candidates WHERE outcome = "LOSS" ORDER BY profit ASC LIMIT 1')
max_loss = c.fetchone()
max_loss = abs(max_loss[0]) if max_loss else 0.0
print(f"Mayor ganancia: ${max_win:.2f}")
print(f"Mayor pérdida: -${max_loss:.2f}")
print(f"Ratio ganancia/pérdida: {max_win/max_loss:.2f}:1" if max_loss > 0 else "N/A")

conn.close()
print("\n" + "=" * 90)
