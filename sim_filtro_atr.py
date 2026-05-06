"""
Simula el nuevo filtro wick/ATR sobre los trades historicos
para ver cuantos habrian sido aceptados/rechazados.
"""
import sqlite3, json
from pathlib import Path

db = list(Path('data/db').glob('*.db'))[0]
conn = sqlite3.connect(db)
cur = conn.cursor()

WICK_ATR_MIN = 0.15
WICK_ATR_MAX = 3.50
OLD_ATR_MAX  = 0.00040

cur.execute("""
SELECT sc.asset, sc.direction, sc.order_id, sc.order_result, sc.profit,
       sc.score, sc.strategy_details, sc.ts
FROM scan_candidates sc
WHERE sc.order_id IS NOT NULL AND sc.order_id != ''
  AND sc.order_result IN ('WIN', 'LOSS')
ORDER BY sc.ts
""")
rows = cur.fetchall()

# Deduplicar
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

# --- Simulacion ---
old_rejected = []     # ATR absoluto > 0.00040 rechazaria este trade
new_rejected_low = [] # wick < 0.15 ATR
new_rejected_high= [] # wick > 3.50 ATR
accepted_both  = []   # pasa ambos filtros
new_only       = []   # nuevo filtro pasa pero el viejo lo rechazaria

for t in trades:
    _, det, _ = parse(t)
    atr_val = det.get('atr')
    wk_atr  = det.get('wick_atr_ratio')

    if atr_val is None:
        continue

    old_ok = (atr_val <= OLD_ATR_MAX)

    # Para nuevo filtro necesitamos wick_atr_ratio
    # Si no esta en el JSON (trades anteriores a este cambio), lo calculamos
    if wk_atr is None:
        # no tenemos el wick directamente, pero sabemos wick_ratio = wick/body
        # y podemos estimar: los datos no tienen cuerpo separado, skip
        continue

    new_ok = (WICK_ATR_MIN <= wk_atr <= WICK_ATR_MAX)

    if old_ok and new_ok:
        accepted_both.append(t)
    elif not old_ok and new_ok:
        new_only.append(t)       # el nuevo filtro rescata este trade
    elif not new_ok and wk_atr < WICK_ATR_MIN:
        new_rejected_low.append(t)
    elif not new_ok and wk_atr > WICK_ATR_MAX:
        new_rejected_high.append(t)
    else:
        old_rejected.append(t)

print("=== IMPACTO DEL NUEVO FILTRO wick/ATR ===")
print(f"Total trades analizados: {len(trades)}")
print()

def wr(lst):
    if not lst: return 'n/a'
    w = sum(1 for t in lst if t[3]=='WIN')
    return f'{w}/{len(lst)} = {100*w/len(lst):.0f}% WR  P&L=${sum(t[4] or 0 for t in lst):+.2f}'

print(f"  Nota: solo {len(accepted_both)+len(new_only)+len(new_rejected_low)+len(new_rejected_high)} tienen wick_atr_ratio en el JSON")
print(f"  (Los trades anteriores al cambio no tienen ese campo - usa candles_1m para recalcular)")
print()
print(f"Filtro viejo (ATR<={OLD_ATR_MAX}):")
print(f"  Habrian pasado  : {wr([t for t in trades if (json.loads(t[6]) if t[6] else {}).get('detalle',{}).get('atr',999) <= OLD_ATR_MAX])}")
print(f"  Habrian fallado : {wr([t for t in trades if (json.loads(t[6]) if t[6] else {}).get('detalle',{}).get('atr',999) > OLD_ATR_MAX])}")

print()
print("Nuevo filtro (wick_atr en [0.15, 3.5]):")
all_with_watr = [t for t in trades if parse(t)[1].get('wick_atr_ratio') is not None]
if all_with_watr:
    pass_new = [t for t in all_with_watr if WICK_ATR_MIN <= parse(t)[1].get('wick_atr_ratio',0) <= WICK_ATR_MAX]
    fail_new = [t for t in all_with_watr if not (WICK_ATR_MIN <= parse(t)[1].get('wick_atr_ratio',0) <= WICK_ATR_MAX)]
    print(f"  Pasarian : {wr(pass_new)}")
    print(f"  Fallarian: {wr(fail_new)}")
    if fail_new:
        for t in fail_new:
            _, det, raw = parse(t)
            print(f"    -> {t[0]:15s} wick_atr={det.get('wick_atr_ratio'):.2f} atr={det.get('atr'):.5f} {t[3]}")
else:
    print("  No hay trades con wick_atr_ratio (datos anteriores al cambio)")
    print("  Los proximos trades en vivo ya usaran el nuevo calculo")

conn.close()
