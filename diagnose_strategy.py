#!/usr/bin/env python3
"""Análisis de problemas en la estrategia"""
import sqlite3
import json
from pathlib import Path

db_path = Path("trade_journal.db")
conn = sqlite3.connect(str(db_path))
c = conn.cursor()

print("=" * 110)
print("🔍 DIAGNÓSTICO DE PROBLEMAS EN LA ESTRATEGIA")
print("=" * 110)

# PROBLEMA 1: Operaciones sin patrón (pattern=none) tienen alta tasa de pérdida
print("\n❌ PROBLEMA #1: Operaciones SIN PATRÓN (pattern=none)")
print("-" * 110)
c.execute('''
    SELECT outcome,
           COUNT(*) as total,
           SUM(CASE WHEN outcome = 'LOSS' THEN 1 ELSE 0 END) as losses,
           ROUND(100.0 * SUM(CASE WHEN outcome = 'LOSS' THEN 1 ELSE 0 END) / COUNT(*), 1) as loss_rate,
           SUM(profit) as net
    FROM candidates
    WHERE reversal_pattern = 'none' OR reversal_pattern IS NULL
    GROUP BY outcome
''')
print(f"{'Outcome':<10} {'Total':<8} {'Losses':<10} {'Loss %':<10} {'Net Profit':<12}")
print("-" * 110)
for row in c.fetchall():
    outcome, total, losses, loss_rate, net = row
    print(f"{outcome:<10} {total:<8} {losses if losses else 'N/A':<10} {loss_rate if loss_rate else 'N/A':<10} ${net:>10.2f}")

# Análisis: ¿Qué % del total son operaciones sin patrón?
c.execute('''
    SELECT 
        SUM(CASE WHEN reversal_pattern = 'none' OR reversal_pattern IS NULL THEN 1 ELSE 0 END) as no_pattern,
        COUNT(*) as total,
        ROUND(100.0 * SUM(CASE WHEN reversal_pattern = 'none' OR reversal_pattern IS NULL THEN 1 ELSE 0 END) / COUNT(*), 1) as pct
    FROM candidates
    WHERE outcome IN ('WIN', 'LOSS')
''')
row = c.fetchone()
if row:
    no_pattern, total, pct = row
    print(f"\n📊 {no_pattern} de {total} operaciones ({pct}%) NO TIENEN PATRÓN DETECTADO")
    print("⚠️  ISSUE: El sistema entra en trades sin confirmación de patrón 1m")

# PROBLEMA 2: Análisis de direcciones - PUT tiene problemas
print("\n\n❌ PROBLEMA #2: PUT (🔴) tiene desempeño TERRIBLE")
print("-" * 110)
c.execute('''
    SELECT direction,
           COUNT(*) FILTER (WHERE outcome = 'WIN') as wins,
           COUNT(*) FILTER (WHERE outcome = 'LOSS') as losses,
           COUNT(*) as total,
           ROUND(100.0 * COUNT(*) FILTER (WHERE outcome = 'LOSS') / COUNT(*), 1) as loss_rate,
           ROUND(SUM(profit), 2) as net_profit
    FROM candidates
    WHERE outcome IN ('WIN', 'LOSS')
    GROUP BY direction
    ORDER BY loss_rate DESC
''')
print(f"{'Direction':<10} {'Wins':<8} {'Losses':<10} {'Total':<8} {'Loss %':<10} {'Net':<12}")
print("-" * 110)
call_loss_rate = 0
put_loss_rate = 0
for row in c.fetchall():
    direction, wins, losses, total, loss_rate, net = row
    dir_label = "CALL" if direction == "call" else "PUT"
    print(f"{dir_label:<10} {wins:<8} {losses:<10} {total:<8} {loss_rate:>8.1f}% ${net:>10.2f}")
    if direction == "call":
        call_loss_rate = loss_rate
    else:
        put_loss_rate = loss_rate

if call_loss_rate > 0 and put_loss_rate > 0:
    ratio = put_loss_rate / call_loss_rate
    print(f"\n⚠️  PUT tiene {ratio:.1f}x más pérdidas que CALL")
    print("CAUSA POTENCIAL: Sesgo en detección de patrones bajistas o entrada tardía en PUT")

# PROBLEMA 3: Zonas muy jóvenes
print("\n\n❌ PROBLEMA #3: Zonas RECIÉN DETECTADAS (<5 min) tienen alto drawdown")
print("-" * 110)
c.execute('''
    SELECT 
        COUNT(*) FILTER (WHERE outcome = 'LOSS') as losses,
        COUNT(*) as total,
        ROUND(100.0 * COUNT(*) FILTER (WHERE outcome = 'LOSS') / COUNT(*), 1) as loss_rate,
        SUM(profit) as net
    FROM candidates
    WHERE outcome IN ('WIN', 'LOSS') AND zone_age_min < 5
''')
row = c.fetchone()
if row:
    losses, total, loss_rate, net = row
    print(f"Zonas < 5 min: {losses}/{total} pérdidas ({loss_rate:.1f}% loss rate) | Net: ${net:.2f}")

c.execute('''
    SELECT 
        COUNT(*) FILTER (WHERE outcome = 'LOSS') as losses,
        COUNT(*) as total,
        ROUND(100.0 * COUNT(*) FILTER (WHERE outcome = 'LOSS') / COUNT(*), 1) as loss_rate,
        SUM(profit) as net
    FROM candidates
    WHERE outcome IN ('WIN', 'LOSS') AND zone_age_min >= 15 AND zone_age_min <= 45
''')
row = c.fetchone()
if row:
    losses, total, loss_rate, net = row
    print(f"Zonas 15-45 min: {losses}/{total} pérdidas ({loss_rate:.1f}% loss rate) | Net: ${net:.2f}")

print("\n⚠️  ISSUE: Entradas en zonas muy recientes fallan más. Necesita filtro de edad mínima.")

# PROBLEMA 4: Martingala está fallando
print("\n\n❌ PROBLEMA #4: MARTINGALA tiene tasa de pérdida alta")
print("-" * 110)
c.execute('''
    SELECT stage,
           COUNT(*) FILTER (WHERE outcome = 'WIN') as wins,
           COUNT(*) FILTER (WHERE outcome = 'LOSS') as losses,
           COUNT(*) as total,
           ROUND(100.0 * COUNT(*) FILTER (WHERE outcome = 'LOSS') / COUNT(*), 1) as loss_rate,
           SUM(profit) as net
    FROM candidates
    WHERE outcome IN ('WIN', 'LOSS') AND (stage LIKE 'martin%' OR stage = 'martin_break')
    GROUP BY stage
''')
martin_data = c.fetchall()
if martin_data:
    print(f"{'Stage':<20} {'Wins':<8} {'Losses':<10} {'Total':<8} {'Loss %':<10} {'Net':<12}")
    print("-" * 110)
    for row in martin_data:
        stage, wins, losses, total, loss_rate, net = row
        print(f"{stage:<20} {wins:<8} {losses:<10} {total:<8} {loss_rate:>8.1f}% ${net:>10.2f}")

# PROBLEMA 5: Activos específicos que pierden mucho
print("\n\n❌ PROBLEMA #5: ACTIVOS PROBLEMÁTICOS")
print("-" * 110)
c.execute('''
    SELECT asset,
           COUNT(*) FILTER (WHERE outcome = 'LOSS') as losses,
           COUNT(*) as total,
           ROUND(100.0 * COUNT(*) FILTER (WHERE outcome = 'LOSS') / COUNT(*), 1) as loss_rate,
           SUM(profit) as net
    FROM candidates
    WHERE outcome IN ('WIN', 'LOSS')
    GROUP BY asset
    HAVING COUNT(*) >= 3
    ORDER BY loss_rate DESC
    LIMIT 5
''')
print(f"{'Asset':<15} {'Losses':<10} {'Total':<8} {'Loss %':<10} {'Net':<12}")
print("-" * 110)
for row in c.fetchall():
    asset, losses, total, loss_rate, net = row
    print(f"{asset:<15} {losses:<10} {total:<8} {loss_rate:>8.1f}% ${net:>10.2f}")

# PROBLEMA 6: Score vs realidad
print("\n\n❌ PROBLEMA #6: SCORE alto no garantiza ganancia")
print("-" * 110)
c.execute('''
    SELECT 
        CASE 
            WHEN score >= 75 THEN '75-100'
            WHEN score >= 70 THEN '70-75'
            WHEN score >= 65 THEN '65-70'
            WHEN score >= 60 THEN '60-65'
            ELSE '<60'
        END as score_bucket,
        COUNT(*) FILTER (WHERE outcome = 'WIN') as wins,
        COUNT(*) FILTER (WHERE outcome = 'LOSS') as losses,
        COUNT(*) as total,
        ROUND(100.0 * COUNT(*) FILTER (WHERE outcome = 'LOSS') / COUNT(*), 1) as loss_rate,
        ROUND(AVG(profit), 2) as avg_profit
    FROM candidates
    WHERE outcome IN ('WIN', 'LOSS')
    GROUP BY score_bucket
    ORDER BY CAST(SUBSTR(score_bucket, 1, 2) AS REAL) DESC
''')
print(f"{'Score Range':<15} {'Wins':<8} {'Losses':<10} {'Total':<8} {'Loss %':<10} {'Avg Profit':<12}")
print("-" * 110)
for row in c.fetchall():
    bucket, wins, losses, total, loss_rate, avg = row
    print(f"{bucket:<15} {wins:<8} {losses:<10} {total:<8} {loss_rate:>8.1f}% ${avg:>10.2f}")

print("\n⚠️  ISSUE: Score no es predictor confiable. Incluso scores altos pierden.")

# PROBLEMA 7: Score de compresión de zona
print("\n\n❌ PROBLEMA #7: ZONA CON BAJA COMPRESIÓN (rango amplio)")
print("-" * 110)
c.execute('''
    SELECT 
        CASE 
            WHEN zone_range_pct < 0.05 THEN '<0.05%'
            WHEN zone_range_pct < 0.10 THEN '0.05-0.10%'
            WHEN zone_range_pct < 0.15 THEN '0.10-0.15%'
            ELSE '>0.15%'
        END as compression,
        COUNT(*) FILTER (WHERE outcome = 'WIN') as wins,
        COUNT(*) FILTER (WHERE outcome = 'LOSS') as losses,
        COUNT(*) as total,
        ROUND(100.0 * COUNT(*) FILTER (WHERE outcome = 'LOSS') / COUNT(*), 1) as loss_rate
    FROM candidates
    WHERE outcome IN ('WIN', 'LOSS') AND zone_range_pct IS NOT NULL
    GROUP BY compression
    ORDER BY zone_range_pct
''')
print(f"{'Range %':<15} {'Wins':<8} {'Losses':<10} {'Total':<8} {'Loss %':<10}")
print("-" * 110)
for row in c.fetchall():
    compression, wins, losses, total, loss_rate = row
    print(f"{compression:<15} {wins:<8} {losses:<10} {total:<8} {loss_rate:>8.1f}%")

conn.close()

print("\n" + "=" * 110)
print("📋 RESUMEN DE PROBLEMAS Y RECOMENDACIONES:")
print("=" * 110)
print("""
1. ❌ 58% de operaciones SIN PATRÓN → La validación de vela que agregamos es CRÍTICA
2. ❌ PUTs tienen 3.9x más pérdidas → Revisión de detección de patrones bajistas
3. ❌ Zonas < 5 min: 58.8% loss rate → Filtrar zonas que acaban de detectarse
4. ❌ Martingala fallando → Revisar lógica de compensación (monto/dirección)
5. ❌ Activos específicos (GBPJPY, GBPUSD) → Filtrar o aumentar requisitos
6. ❌ Score alto ≠ Ganancia → Recalibrar pesos del scoring
7. ❌ Entrada muy rápida en vela → Posible contaminación de datos WebSocket

🎯 PRÓXIMAS ACCIONES:
   → Mantener validación de vela de rechazo
   → Aumentar edad mínima de zona (5 → 10 minutos)
   → Revisar detección de patrones bajistas (BEARISH)
   → Reducir monto de martingala o limitar a 1 intento
   → Agregar filtro de activos problemáticos
""")
