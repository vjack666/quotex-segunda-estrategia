"""
Recalcula wick_atr_ratio desde los candles_1m + atr almacenado
y simula el nuevo filtro sobre todos los trades historicos.
"""
import sqlite3, json
from pathlib import Path

db = list(Path('data/db').glob('*.db'))[0]
conn = sqlite3.connect(db)
cur = conn.cursor()

WICK_ATR_MIN = 0.15
WICK_ATR_MAX = 3.50
OLD_ATR_MAX  = 0.00040
MIN_WICK_BODY = 1.5   # mismo umbral que el detector

cur.execute("""
SELECT sc.asset, sc.direction, sc.order_id, sc.order_result, sc.profit,
       sc.score, sc.strategy_details, sc.candles_1m, sc.ts
FROM scan_candidates sc
WHERE sc.order_id IS NOT NULL AND sc.order_id != ''
  AND sc.order_result IN ('WIN', 'LOSS')
ORDER BY sc.ts
""")
rows = cur.fetchall()

# Deduplicar por order_id
seen = {}
for r in rows:
    if r[2] not in seen:
        seen[r[2]] = r
trades = list(seen.values())

def parse(t):
    try: outer = json.loads(t[6]) if t[6] else {}
    except: outer = {}
    det = outer.get('detalle', {})
    raw = outer.get('raw_score', t[5] or 0)
    return outer, det, raw

def calc_wick_atr(t):
    """Calcula wick_atr_ratio desde el ultimo candle y el ATR almacenado."""
    _, det, _ = parse(t)
    atr_val = det.get('atr')
    if not atr_val or atr_val <= 0:
        return None
    # Obtener el candle actual (el ultimo de candles_1m)
    try:
        candles = json.loads(t[7]) if t[7] else []
    except:
        candles = []
    if not candles:
        return None
    c = candles[-1]
    o, h, l, cl = c['open'], c['high'], c['low'], c['close']
    body = abs(cl - o)
    if body < 1e-10:
        body = 1e-10
    upper_wick = h - max(o, cl)
    lower_wick = min(o, cl) - l
    direction = t[1]
    if direction == 'call':
        active_wick = lower_wick
    else:
        active_wick = upper_wick
    return active_wick / atr_val

import datetime
def ts_to_hora(ts):
    try: return datetime.datetime.fromtimestamp(float(ts)).strftime('%H:%M')
    except: return '??:??'

# --- Calcular para cada trade ---
enriched = []
for t in trades:
    war = calc_wick_atr(t)
    _, det, raw = parse(t)
    enriched.append({
        't': t,
        'war': war,
        'atr': det.get('atr'),
        'raw': raw,
        'wr': det.get('wick_ratio'),
    })

print("=== SIMULACION: FILTRO wick/ATR vs ATR ABSOLUTO ===")
print(f"Total trades: {len(enriched)}")
print()

# Con wick_atr calculado
calculados = [e for e in enriched if e['war'] is not None]
print(f"Trades con wick recalculable: {len(calculados)}/{len(enriched)}")
print()

# Clasificar bajo filtro NUEVO
pasa_nuevo   = [e for e in calculados if WICK_ATR_MIN <= e['war'] <= WICK_ATR_MAX]
falla_nuevo  = [e for e in calculados if not (WICK_ATR_MIN <= e['war'] <= WICK_ATR_MAX)]
pasa_viejo   = [e for e in calculados if (e['atr'] or 999) <= OLD_ATR_MAX]
falla_viejo  = [e for e in calculados if (e['atr'] or 0) > OLD_ATR_MAX]

def wr_e(lst):
    if not lst: return 'n/a (0 trades)'
    w = sum(1 for e in lst if e['t'][3]=='WIN')
    pnl = sum(e['t'][4] or 0 for e in lst)
    return f'{w}/{len(lst)} = {100*w/len(lst):.0f}% WR  P&L=${pnl:+.2f}'

print(f"Filtro VIEJO (ATR <= {OLD_ATR_MAX}):")
print(f"  Aceptados : {wr_e(pasa_viejo)}")
print(f"  Rechazados: {wr_e(falla_viejo)}")
print()
print(f"Filtro NUEVO (wick/ATR en [{WICK_ATR_MIN}, {WICK_ATR_MAX}]):")
print(f"  Aceptados : {wr_e(pasa_nuevo)}")
print(f"  Rechazados: {wr_e(falla_nuevo)}")

if falla_nuevo:
    print(f"\n  Trades rechazados por nuevo filtro:")
    for e in falla_nuevo:
        t = e['t']
        print(f"    {ts_to_hora(t[8])} | {t[0]:15s} {t[1]:4s} | wick/ATR={e['war']:.2f} atr={e['atr']:.5f} -> {t[3]}")

print()
print("=== RESUMEN: lo que NEW rescata vs OLD ===")
# Trades que OLD rechazaria (ATR alto) pero NEW acepta (wick/ATR ok)
rescatados = [e for e in calculados if (e['atr'] or 0) > OLD_ATR_MAX and WICK_ATR_MIN <= e['war'] <= WICK_ATR_MAX]
nuevos_rechazados = [e for e in calculados if (e['atr'] or 0) > OLD_ATR_MAX and not (WICK_ATR_MIN <= e['war'] <= WICK_ATR_MAX)]
print(f"  OLD rechaza, NEW acepta: {wr_e(rescatados)}")
print(f"  OLD rechaza, NEW tb rechaza: {wr_e(nuevos_rechazados)}")
print()
print("  Desglose de rechazados por nuevo filtro:")
for e in falla_nuevo:
    t = e['t']
    razon = f"wick/ATR={e['war']:.2f} < {WICK_ATR_MIN}" if e['war'] < WICK_ATR_MIN else f"wick/ATR={e['war']:.2f} > {WICK_ATR_MAX}"
    print(f"    {ts_to_hora(t[8])} | {t[0]:15s} {t[1]:4s} | {razon} | atr={e['atr']:.5f} | {t[3]}")

print()
print("=== DETALLE: todos los trades con wick/ATR ===")
print(f"{'Hora':5s} | {'Asset':15s} | {'Dir':4s} | {'Res':4s} | {'Score':5s} | {'wick/ATR':8s} | {'wick/body':9s} | {'ATR abs':9s} | NuevoFiltro | AntigFiltro")
print('-' * 105)
for e in sorted(calculados, key=lambda x: x['t'][8] or 0):
    t = e['t']
    hora = ts_to_hora(t[8])
    nuevo_ok = 'PASS' if WICK_ATR_MIN <= e['war'] <= WICK_ATR_MAX else 'FAIL'
    viejo_ok = 'PASS' if (e['atr'] or 999) <= OLD_ATR_MAX else 'FAIL'
    print(f"{hora:5s} | {t[0]:15s} | {t[1]:4s} | {t[3]:4s} | {e['raw']:5.1f} | {e['war']:8.3f} | {(e['wr'] or 0):9.2f} | {(e['atr'] or 0):9.5f} | {nuevo_ok:11s} | {viejo_ok}")

conn.close()
