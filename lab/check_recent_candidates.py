"""Muestra candidatos y razones de rechazo del journal más reciente."""
import sqlite3
import glob
import os
from datetime import datetime

dbs = sorted(glob.glob("data/db/trade_journal-*.db"), reverse=True)
print("DBs encontradas:", dbs[:3])
if not dbs:
    print("Sin bases de datos de journal.")
    exit()

db = dbs[0]
print(f"Usando: {db}\n")
con = sqlite3.connect(db)
cur = con.cursor()
cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
print("Tablas:", [r[0] for r in cur.fetchall()])

# Candidatos con su decisión
print("\n--- CANDIDATOS RECIENTES (últimos 100) ---")
try:
    cur.execute("""
        SELECT asset, direction, score, decision, reject_reason, stage, ts, entry_mode
        FROM candidates
        ORDER BY ts DESC
        LIMIT 100
    """)
    rows = cur.fetchall()
    if not rows:
        print("  (sin candidatos registrados)")
    for r in rows:
        ts_str = datetime.fromtimestamp(r[6]).strftime("%H:%M:%S") if r[6] else "?"
        print(f"  {ts_str} | {r[0]:25s} {r[1]:4s} score={r[2]:5.1f} | {r[3]:22s} | {r[7] or '':20s} | {r[4] or ''}")
except Exception as e:
    print(f"  Error: {e}")

# Resumen de rechazos por razón
print("\n--- RESUMEN RECHAZOS ---")
try:
    cur.execute("""
        SELECT reject_reason, COUNT(*) as n
        FROM candidates
        WHERE decision LIKE 'REJECTED%' OR decision = 'SKIPPED'
        GROUP BY reject_reason
        ORDER BY n DESC
    """)
    for r in cur.fetchall():
        print(f"  {r[1]:4d}x  {r[0]}")
except Exception as e:
    print(f"  Error: {e}")

# Scans recientes
print("\n--- ÚLTIMOS SCAN SESSIONS ---")
try:
    cur.execute("""
        SELECT session_id, assets_scanned, candidates_found, entries_made, ts
        FROM scan_sessions
        ORDER BY ts DESC
        LIMIT 20
    """)
    for r in cur.fetchall():
        ts_str = datetime.fromtimestamp(r[4]).strftime("%H:%M:%S") if r[4] else "?"
        print(f"  {ts_str} | scanned={r[1]} candidates={r[2]} entries={r[3]}")
except Exception as e:
    print(f"  Error scan_sessions: {e}")

con.close()
