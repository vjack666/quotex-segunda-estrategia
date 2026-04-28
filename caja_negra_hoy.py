import sqlite3
import os
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

BROKER_TZ = timezone(timedelta(hours=-3))
ADAPTIVE_THRESHOLD_LOW = 62
ADAPTIVE_THRESHOLD_HIGH = 68
today = datetime.now(tz=BROKER_TZ).strftime('%Y-%m-%d')
print(f"\n{'='*60}")
print(f"  CAJA NEGRA — {today} (UTC-3)")
print(f"{'='*60}\n")

db_path = Path("trade_journal.db")
if not db_path.exists():
    print("ERROR: trade_journal.db no encontrada")
    exit(1)

conn = sqlite3.connect(str(db_path))
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# Columnas
cur.execute("PRAGMA table_info(candidates)")
cols = [r['name'] for r in cur.fetchall()]
print(f"[DB] Columnas: {cols}\n")

# Rango general
cur.execute("SELECT MIN(closed_at), MAX(closed_at), COUNT(*) FROM candidates WHERE outcome IN ('WIN','LOSS')")
row = cur.fetchone()
print(f"[DB] Rango total: {row[0]} → {row[1]} | Total ops: {row[2]}")

# Operaciones de hoy
print(f"\n{'─'*60}")
print(f"  OPERACIONES HOY ({today})")
print(f"{'─'*60}")

cur.execute("""
    SELECT id, asset, direction, stage, score, profit, outcome,
           reversal_pattern, reversal_strength, zone_age_min, closed_at
    FROM candidates
    WHERE outcome IN ('WIN','LOSS')
      AND (date(closed_at) = ? OR date(scanned_at) = ?)
    ORDER BY id ASC
""", (today, today))
ops_hoy = cur.fetchall()

if not ops_hoy:
    # Intentar con ayer también por si zona horaria difiere
    cur.execute("""
        SELECT id, asset, direction, stage, score, profit, outcome,
               reversal_pattern, reversal_strength, zone_age_min, closed_at
        FROM candidates
        WHERE outcome IN ('WIN','LOSS')
        ORDER BY id DESC LIMIT 30
    """)
    ops_hoy = cur.fetchall()
    print(f"  (Sin ops con fecha exacta hoy — mostrando últimas 30)\n")

for op in ops_hoy:
    outcome_icon = "✓" if op['outcome'] == 'WIN' else "✗"
    print(f"  [{outcome_icon}] #{op['id']:>4} | {op['asset']:<20} | {op['direction']:<4} | "
          f"stage={op['stage']} | score={op['score'] or 0:.0f} | "
          f"profit={op['profit'] or 0:+.2f} | "
          f"zona={op['zone_age_min'] or '?':.0f}min | "
          f"patron={op['reversal_pattern'] or 'none'} | "
          f"{op['closed_at']}")

# Stats de hoy
print(f"\n{'─'*60}")
print(f"  RESUMEN HOY")
print(f"{'─'*60}")

wins = [op for op in ops_hoy if op['outcome'] == 'WIN']
losses = [op for op in ops_hoy if op['outcome'] == 'LOSS']
total = len(ops_hoy)

win_profit = sum(op['profit'] or 0 for op in wins)
loss_profit = sum(op['profit'] or 0 for op in losses)
net = win_profit + loss_profit

print(f"  Total operaciones : {total}")
print(f"  Wins              : {len(wins)} ({len(wins)/total*100:.1f}% WR)" if total else "  Sin ops")
print(f"  Losses            : {len(losses)}")
print(f"  Profit ganado     : ${win_profit:+.2f}")
print(f"  Profit perdido    : ${loss_profit:+.2f}")
print(f"  NETO              : ${net:+.2f}")

# Por dirección
print(f"\n{'─'*60}")
print(f"  DESGLOSE POR DIRECCIÓN")
print(f"{'─'*60}")
for direction in ['CALL', 'PUT']:
    d_ops = [op for op in ops_hoy if op['direction'] == direction]
    d_wins = [op for op in d_ops if op['outcome'] == 'WIN']
    if d_ops:
        d_wr = len(d_wins)/len(d_ops)*100
        d_net = sum(op['profit'] or 0 for op in d_ops)
        print(f"  {direction}: {len(d_ops)} ops | WR={d_wr:.1f}% | neto={d_net:+.2f}")

# Por stage/etapa
print(f"\n{'─'*60}")
print(f"  DESGLOSE POR STAGE")
print(f"{'─'*60}")
stages = sorted(set(op['stage'] for op in ops_hoy))
for st in stages:
    s_ops = [op for op in ops_hoy if op['stage'] == st]
    s_wins = [op for op in s_ops if op['outcome'] == 'WIN']
    s_net = sum(op['profit'] or 0 for op in s_ops)
    s_wr = len(s_wins)/len(s_ops)*100 if s_ops else 0
    print(f"  Stage {st}: {len(s_ops)} ops | WR={s_wr:.1f}% | neto={s_net:+.2f}")

# Por asset
print(f"\n{'─'*60}")
print(f"  DESGLOSE POR ACTIVO")
print(f"{'─'*60}")
assets = sorted(set(op['asset'] for op in ops_hoy))
for asset in assets:
    a_ops = [op for op in ops_hoy if op['asset'] == asset]
    a_wins = [op for op in a_ops if op['outcome'] == 'WIN']
    a_net = sum(op['profit'] or 0 for op in a_ops)
    a_wr = len(a_wins)/len(a_ops)*100 if a_ops else 0
    print(f"  {asset:<22}: {len(a_ops)} ops | WR={a_wr:.1f}% | neto={a_net:+.2f}")

# Por patrón
print(f"\n{'─'*60}")
print(f"  DESGLOSE POR PATRÓN DE REVERSIÓN")
print(f"{'─'*60}")
patterns = sorted(set(op['reversal_pattern'] or 'none' for op in ops_hoy))
for pat in patterns:
    p_ops = [op for op in ops_hoy if (op['reversal_pattern'] or 'none') == pat]
    p_wins = [op for op in p_ops if op['outcome'] == 'WIN']
    p_net = sum(op['profit'] or 0 for op in p_ops)
    p_wr = len(p_wins)/len(p_ops)*100 if p_ops else 0
    print(f"  {pat:<20}: {len(p_ops)} ops | WR={p_wr:.1f}% | neto={p_net:+.2f}")

# Score promedio WIN vs LOSS
print(f"\n{'─'*60}")
print(f"  SCORE PROMEDIO WIN vs LOSS")
print(f"{'─'*60}")
win_scores = [op['score'] or 0 for op in wins]
loss_scores = [op['score'] or 0 for op in losses]
if win_scores:
    print(f"  Score avg WIN  : {sum(win_scores)/len(win_scores):.1f}")
if loss_scores:
    print(f"  Score avg LOSS : {sum(loss_scores)/len(loss_scores):.1f}")

# Edad de zona
print(f"\n{'─'*60}")
print(f"  ZONA AGE (minutos) WIN vs LOSS")
print(f"{'─'*60}")
win_ages = [op['zone_age_min'] for op in wins if op['zone_age_min'] is not None]
loss_ages = [op['zone_age_min'] for op in losses if op['zone_age_min'] is not None]
if win_ages:
    print(f"  Edad zona avg WIN  : {sum(win_ages)/len(win_ages):.1f} min")
if loss_ages:
    print(f"  Edad zona avg LOSS : {sum(loss_ages)/len(loss_ages):.1f} min")


def print_ascii_table(title, headers, rows):
    print(f"\n{'─'*60}")
    print(f"  {title}")
    print(f"{'─'*60}")
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell)))
    sep = "+" + "+".join("-" * (w + 2) for w in widths) + "+"
    head = "| " + " | ".join(str(headers[i]).ljust(widths[i]) for i in range(len(headers))) + " |"
    print(f"  {sep}")
    print(f"  {head}")
    print(f"  {sep}")
    for row in rows:
        line = "| " + " | ".join(str(row[i]).ljust(widths[i]) for i in range(len(headers))) + " |"
        print(f"  {line}")
    print(f"  {sep}")


today_log_name = f"log-{today}.txt"
log_candidates = []
if Path(today_log_name).exists():
    log_candidates.append(Path(today_log_name))
if Path("consolidation_bot.log").exists():
    log_candidates.append(Path("consolidation_bot.log"))
if not log_candidates:
    log_candidates = sorted(Path('.').glob('log-*.txt'))[-1:]

all_log_lines = []
for lf in log_candidates:
    try:
        all_log_lines.extend(lf.read_text(encoding='utf-8', errors='replace').splitlines())
    except Exception:
        pass

# 1) UMBRAL ADAPTATIVO
threshold_changes = []
threshold_cycle_values = []
for ln in all_log_lines:
    m = re.search(r"⚠ UMBRAL cambiado:\s*(\d+)\s*→\s*(\d+)", ln)
    if m:
        threshold_changes.append((int(m.group(1)), int(m.group(2))))
    m2 = re.search(r"\[CICLO\s*#\d+\]\s*UMBRAL ACTIVO:\s*(\d+)", ln)
    if m2:
        threshold_cycle_values.append(int(m2.group(1)))

vals = []
for prev_val, new_val in threshold_changes:
    vals.extend([prev_val, new_val])
if not vals and threshold_cycle_values:
    vals = list(threshold_cycle_values)

threshold_min = min(vals) if vals else "N/A"
threshold_max = max(vals) if vals else "N/A"
threshold_up = sum(1 for p, n in threshold_changes if n > p)
threshold_down = sum(1 for p, n in threshold_changes if n < p)
total_cycles_threshold = len(threshold_cycle_values)
pct_below = (sum(1 for v in threshold_cycle_values if v == ADAPTIVE_THRESHOLD_LOW) / total_cycles_threshold * 100) if total_cycles_threshold else 0.0
pct_above = (sum(1 for v in threshold_cycle_values if v == ADAPTIVE_THRESHOLD_HIGH) / total_cycles_threshold * 100) if total_cycles_threshold else 0.0

print_ascii_table(
    "UMBRAL ADAPTATIVO — RESUMEN DE SESIÓN",
    ["Métrica", "Valor"],
    [
        ("Mínimo alcanzado", threshold_min),
        ("Máximo alcanzado", threshold_max),
        ("Cambios (subió)", threshold_up),
        ("Cambios (bajó)", threshold_down),
        ("% ciclos en 62", f"{pct_below:.1f}%"),
        ("% ciclos en 68", f"{pct_above:.1f}%"),
    ],
)

# Parse de líneas de candidatos enriquecidas con [OB][MA][umbral] → DECISIÓN
candidate_rows = []
for ln in all_log_lines:
    m = re.search(
        r"\s([A-Z0-9_]+_otc)\s\[\d+%\]\s(CALL|PUT).*\[OB([+-]\d+)\]\[MA([+-]\d+)\]\[umbral=(\d+)\]\s→\s(ACEPTADO|RECHAZADO)",
        ln,
        flags=re.IGNORECASE,
    )
    if m:
        candidate_rows.append(
            {
                "asset": m.group(1),
                "direction": m.group(2).upper(),
                "ob": int(m.group(3)),
                "ma": int(m.group(4)),
                "threshold": int(m.group(5)),
                "decision": m.group(6).upper(),
            }
        )

# 2) ORDER BLOCKS
ob_bonus = sum(1 for r in candidate_rows if r["ob"] > 0)
ob_penalty = sum(1 for r in candidate_rows if r["ob"] < 0)
ob_none = sum(1 for r in candidate_rows if r["ob"] == 0)
accepted_ob_aligned = sum(1 for r in candidate_rows if r["decision"] == "ACEPTADO" and r["ob"] > 0)

print_ascii_table(
    "ORDER BLOCKS — IMPACTO EN SEÑALES",
    ["Métrica", "Valor"],
    [
        ("Señales con bonus OB (+5)", ob_bonus),
        ("Señales con penalización OB (-8)", ob_penalty),
        ("Señales sin OB relevante", ob_none),
        ("ACCEPTED con OB alineado", accepted_ob_aligned),
    ],
)

# 3) MEDIAS MÓVILES
ma_events = {}
for ln in all_log_lines:
    m = re.search(r"\[MA\]\s+([A-Z0-9_]+_otc)\s+dir=(CALL|PUT).*trend=(UP|DOWN|FLAT)\s+cross=(GOLDEN|DEATH|NONE)", ln)
    if m:
        ma_events[m.group(1)] = {
            "trend": m.group(3),
            "cross": m.group(4),
        }

accepted_by_trend = {"UP": 0, "DOWN": 0, "FLAT": 0}
aligned_total = 0
aligned_wins = 0
against_total = 0
against_wins = 0

for r in candidate_rows:
    if r["decision"] != "ACEPTADO":
        continue
    trend = ma_events.get(r["asset"], {}).get("trend", "FLAT")
    accepted_by_trend[trend] = accepted_by_trend.get(trend, 0) + 1
    aligned = (r["direction"] == "CALL" and trend == "UP") or (r["direction"] == "PUT" and trend == "DOWN")
    if aligned:
        aligned_total += 1
    elif trend in ("UP", "DOWN"):
        against_total += 1

accepted_db = [op for op in ops_hoy if op['outcome'] in ('WIN', 'LOSS')]
for op in accepted_db:
    trend = ma_events.get(op['asset'], {}).get('trend')
    if trend not in ('UP', 'DOWN'):
        continue
    is_aligned = (op['direction'] == 'CALL' and trend == 'UP') or (op['direction'] == 'PUT' and trend == 'DOWN')
    if is_aligned:
        aligned_wins += 1 if op['outcome'] == 'WIN' else 0
    else:
        against_wins += 1 if op['outcome'] == 'WIN' else 0

golden_count = sum(1 for v in ma_events.values() if v.get("cross") == "GOLDEN")
death_count = sum(1 for v in ma_events.values() if v.get("cross") == "DEATH")
aligned_wr = (aligned_wins / aligned_total * 100) if aligned_total else 0.0
against_wr = (against_wins / against_total * 100) if against_total else 0.0

print_ascii_table(
    "MEDIAS MÓVILES — ALINEACIÓN CON TENDENCIA",
    ["Métrica", "Valor"],
    [
        ("ACCEPTED con tendencia UP", accepted_by_trend.get("UP", 0)),
        ("ACCEPTED con tendencia DOWN", accepted_by_trend.get("DOWN", 0)),
        ("ACCEPTED con tendencia FLAT", accepted_by_trend.get("FLAT", 0)),
        ("GOLDEN CROSS del día", golden_count),
        ("DEATH CROSS del día", death_count),
        ("Win rate alineadas MA", f"{aligned_wr:.1f}%"),
        ("Win rate contra tendencia", f"{against_wr:.1f}%"),
    ],
)

# 4) BLACKLIST
blacklist_add = {}
blocked_by_blacklist = 0
for ln in all_log_lines:
    m_add = re.search(r"\[BLACKLIST\]\s+([A-Z0-9_]+_otc)\s+añadido", ln)
    if m_add:
        asset = m_add.group(1)
        blacklist_add[asset] = blacklist_add.get(asset, 0) + 1
    if "blacklist temporal activa" in ln.lower():
        blocked_by_blacklist += 1

bl_rows = [(asset, count) for asset, count in sorted(blacklist_add.items())]
if not bl_rows:
    bl_rows = [("(sin ingresos)", 0)]

print_ascii_table(
    "BLACKLIST — ACTIVIDAD DEL DÍA",
    ["Activo", "Entradas blacklist"],
    bl_rows,
)
print_ascii_table(
    "BLACKLIST — BLOQUEO DE SEÑALES",
    ["Métrica", "Valor"],
    [
        ("Señales potenciales bloqueadas", blocked_by_blacklist),
    ],
)

# 5) STRICT PATTERN CHECK
strict_discards = sum(
    1
    for ln in all_log_lines
    if "STRICT_PATTERN_CHECK activo" in ln and "descarte antes de score" in ln
)
print_ascii_table(
    "STRICT PATTERN CHECK",
    ["Métrica", "Valor"],
    [
        ("Descartadas pre-score (strength >= 0.65)", strict_discards),
    ],
)

conn.close()

# Log tail
print(f"\n{'─'*60}")
print(f"  ÚLTIMAS 50 LÍNEAS DEL LOG")
print(f"{'─'*60}")
log_files = list(Path('.').glob('log-*.txt')) + list(Path('.').glob('consolidation_bot.log'))
if log_files:
    log_file = sorted(log_files)[-1]
    print(f"  Archivo: {log_file}")
    lines = log_file.read_text(encoding='utf-8', errors='replace').splitlines()
    for line in lines[-50:]:
        print(f"  {line}")
else:
    print("  No se encontró archivo de log")

print(f"\n{'='*60}")
print("  FIN CAJA NEGRA")
print(f"{'='*60}\n")
