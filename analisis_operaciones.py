"""
Analisis profundo de operaciones STRAT-C
"""
import sqlite3, json
from pathlib import Path

db = list(Path('data/db').glob('*.db'))[0]
print(f'DB: {db}')
conn = sqlite3.connect(db)
cur = conn.cursor()

cur.execute("""
SELECT sc.asset, sc.direction, sc.order_id, sc.order_result, sc.profit,
       sc.score, sc.strategy_details, sc.ts
FROM scan_candidates sc
WHERE sc.order_id IS NOT NULL AND sc.order_id != ''
  AND sc.order_result IN ('WIN', 'LOSS')
ORDER BY sc.ts
""")
rows = cur.fetchall()

# Deduplicar por order_id
seen = {}
for r in rows:
    oid = r[2]
    if oid not in seen:
        seen[oid] = r

trades = list(seen.values())
wins = [t for t in trades if t[3] == 'WIN']
losses = [t for t in trades if t[3] == 'LOSS']
print(f'\nTotal trades unicos: {len(trades)}  WIN: {len(wins)}  LOSS: {len(losses)}  WR: {100*len(wins)/len(trades):.1f}%\n')

import datetime

def parse(t):
    """Retorna (outer_dict, detalle_dict, raw_score_from_json)"""
    try:
        outer = json.loads(t[6]) if t[6] else {}
    except:
        outer = {}
    detalle = outer.get('detalle', {})
    raw = outer.get('raw_score', t[5] or 0)
    return outer, detalle, raw

def ts_to_hora(ts):
    if ts is None: return '??:??'
    try:
        return datetime.datetime.fromtimestamp(float(ts)).strftime('%H:%M')
    except:
        return '??:??'

# ---- Score buckets (usando raw_score del JSON) ----
print('=== WR POR SCORE BUCKET (raw_score del detector) ===')
buckets = {'<4': [], '4-5.9': [], '6-7.9': [], '8+': []}
for t in trades:
    _, _, raw = parse(t)
    if raw < 4:   buckets['<4'].append(t)
    elif raw < 6: buckets['4-5.9'].append(t)
    elif raw < 8: buckets['6-7.9'].append(t)
    else:         buckets['8+'].append(t)

for k, v in buckets.items():
    if v:
        w = sum(1 for t in v if t[3] == 'WIN')
        pnl_b = sum((parse(t)[0].get('raw_score', 0) and t[4] or 0) for t in v)
        print(f'  Score {k:6s}: {w}/{len(v)} = {100*w/len(v):.0f}% WR  P&L=${sum(t[4] or 0 for t in v):+.2f}')

# ---- RSI analisis ----
print('\n=== RSI EN WINS VS LOSSES ===')
rsi_wins   = [parse(t)[1].get('rsi') for t in wins   if parse(t)[1].get('rsi') is not None]
rsi_losses = [parse(t)[1].get('rsi') for t in losses if parse(t)[1].get('rsi') is not None]
if rsi_wins:
    print(f'  WIN  RSI avg={sum(rsi_wins)/len(rsi_wins):.1f}  min={min(rsi_wins):.1f}  max={max(rsi_wins):.1f}  n={len(rsi_wins)}')
if rsi_losses:
    print(f'  LOSS RSI avg={sum(rsi_losses)/len(rsi_losses):.1f}  min={min(rsi_losses):.1f}  max={max(rsi_losses):.1f}  n={len(rsi_losses)}')

# RSI alineacion con direccion
print('\n=== RSI vs DIRECCION (alineacion con señal) ===')
# RSI>70 = sobrecomprado -> PUT es correcto
# RSI<30 = sobrevendido  -> CALL es correcto
alineados, contrarios, neutros = [], [], []
for t in trades:
    _, det, _ = parse(t)
    rsi = det.get('rsi')
    if rsi is None:
        neutros.append(t)
        continue
    d = t[1]
    if (rsi > 70 and d == 'put') or (rsi < 30 and d == 'call'):
        alineados.append(t)
    elif (rsi > 70 and d == 'call') or (rsi < 30 and d == 'put'):
        contrarios.append(t)
    else:
        neutros.append(t)  # RSI 30-70

if alineados:
    w = sum(1 for t in alineados if t[3]=='WIN')
    print(f'  RSI alineado (>70 PUT, <30 CALL): {w}/{len(alineados)} = {100*w/len(alineados):.0f}% WR  P&L=${sum(t[4] or 0 for t in alineados):+.2f}')
if contrarios:
    w = sum(1 for t in contrarios if t[3]=='WIN')
    print(f'  RSI contrario (>70 CALL,<30 PUT) : {w}/{len(contrarios)} = {100*w/len(contrarios):.0f}% WR  P&L=${sum(t[4] or 0 for t in contrarios):+.2f}')
    print(f'  --> PROBLEMA: {len(contrarios)} trades contra RSI extremo')
if neutros:
    w = sum(1 for t in neutros if t[3]=='WIN')
    print(f'  RSI neutro (30-70)               : {w}/{len(neutros)} = {100*w/len(neutros):.0f}% WR  P&L=${sum(t[4] or 0 for t in neutros):+.2f}')

# ---- ATR analisis ----
print('\n=== ATR EN WINS VS LOSSES ===')
atr_wins   = [parse(t)[1].get('atr') for t in wins   if parse(t)[1].get('atr') is not None]
atr_losses = [parse(t)[1].get('atr') for t in losses if parse(t)[1].get('atr') is not None]
if atr_wins:
    print(f'  WIN  ATR avg={sum(atr_wins)/len(atr_wins):.5f}  max={max(atr_wins):.5f}')
if atr_losses:
    print(f'  LOSS ATR avg={sum(atr_losses)/len(atr_losses):.5f}  max={max(atr_losses):.5f}')

# ATR > tesis max
high_atr_all = [t for t in trades if (parse(t)[1].get('atr') or 0) > 0.00040]
if high_atr_all:
    w = sum(1 for t in high_atr_all if t[3]=='WIN')
    print(f'  ATR > 0.00040 ({len(high_atr_all)} trades): {w}/{len(high_atr_all)} = {100*w/len(high_atr_all):.0f}% WR  P&L=${sum(t[4] or 0 for t in high_atr_all):+.2f}')
    print(f'  --> Si se aplica filtro ATR thesis, se eliminarían {len(high_atr_all)} trades')
else:
    print('  Ninguno supera 0.00040')

# ---- Score < 6 ----
print('\n=== TRADES CON SCORE < 6 (bajo umbral thesis) ===')
low_score = [t for t in trades if (parse(t)[2]) < 6]
if low_score:
    w = sum(1 for t in low_score if t[3]=='WIN')
    print(f'  {w}/{len(low_score)} = {100*w/len(low_score):.0f}% WR  P&L=${sum(t[4] or 0 for t in low_score):+.2f}')
else:
    print('  Ninguno (todos >= 6)')

# ---- Wick quality ----
print('\n=== WR POR CALIDAD DE WICK ===')
wq_stats = {}
for t in trades:
    _, det, _ = parse(t)
    wq = det.get('wick_quality', 'unknown')
    if wq not in wq_stats: wq_stats[wq] = {'W': 0, 'L': 0}
    wq_stats[wq]['W' if t[3]=='WIN' else 'L'] += 1

for wq, st in sorted(wq_stats.items()):
    total = st['W'] + st['L']
    print(f'  {wq:12s}: {st["W"]}/{total} = {100*st["W"]/total:.0f}% WR')

# ---- EMA trend ----
print('\n=== WR POR EMA TREND ===')
ema_stats = {}
for t in trades:
    _, det, _ = parse(t)
    ema = det.get('ema_trend', 'unknown')
    if ema not in ema_stats: ema_stats[ema] = {'W': 0, 'L': 0}
    ema_stats[ema]['W' if t[3]=='WIN' else 'L'] += 1

for ema, st in sorted(ema_stats.items()):
    total = st['W'] + st['L']
    print(f'  {ema:20s}: {st["W"]}/{total} = {100*st["W"]/total:.0f}% WR')

# ---- Source ----
print('\n=== WR POR FUENTE (source) ===')
src_stats = {}
for t in trades:
    outer, _, _ = parse(t)
    src = outer.get('source', 'unknown')
    if src not in src_stats: src_stats[src] = {'W': 0, 'L': 0}
    src_stats[src]['W' if t[3]=='WIN' else 'L'] += 1

for src, st in sorted(src_stats.items()):
    total = st['W'] + st['L']
    print(f'  {src:15s}: {st["W"]}/{total} = {100*st["W"]/total:.0f}% WR')

# ---- Detalle completo ----
print('\n=== DETALLE COMPLETO (deduplicado, ordenado por hora) ===')
print(f'{"Hora":5s} | {"Asset":15s} | {"Dir":4s} | {"Res":4s} | {"Score":5s} | {"RSI":5s} | {"ATR":8s} | {"WickQ":6s} | {"EMAtren":15s} | P&L | Flags')
print('-' * 110)
for t in sorted(trades, key=lambda x: x[7] or 0):
    outer, det, raw = parse(t)
    hora  = ts_to_hora(t[7])
    rsi   = det.get('rsi')
    atr   = det.get('atr')
    wq    = det.get('wick_quality', '-')
    ema   = det.get('ema_trend', '-')
    rsi_s = f'{rsi:.0f}' if rsi is not None else '  -'
    atr_s = f'{atr:.5f}' if atr is not None else '      -'
    pnl   = t[4] or 0
    flags = []
    if rsi is not None and ((rsi > 70 and t[1] == 'call') or (rsi < 30 and t[1] == 'put')):
        flags.append('RSI-CONTRA')
    if raw < 6:
        flags.append('SCORE<6')
    if atr is not None and atr > 0.00040:
        flags.append('ATR-ALTO')
    flag_s = ' '.join(flags)
    res = t[3]
    print(f'{hora:5s} | {t[0]:15s} | {t[1]:4s} | {res:4s} | {raw:5.1f} | {rsi_s:5s} | {atr_s:8s} | {wq:6s} | {ema:15s} | ${pnl:+6.2f} | {flag_s}')

conn.close()
