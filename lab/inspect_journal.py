"""Inspección del trade journal — busca MCD_OTC y muestra todos los datos."""
import sqlite3
import os
import glob

DB_DIR = "data/db"
dbs = sorted(glob.glob(f"{DB_DIR}/trade_journal-*.db"))
print(f"DBs encontradas: {dbs}")

for db_path in dbs[-2:]:  # últimas 2
    print(f"\n{'='*70}")
    print(f"DB: {db_path}")
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row

    tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    print(f"Tablas: {tables}")

    for t in tables:
        cols = [r[1] for r in con.execute(f"PRAGMA table_info({t})")]
        print(f"\nTabla [{t}] columnas: {cols}")
        count = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"  Filas totales: {count}")

        # Buscar MCD
        try:
            rows = con.execute(
                f"SELECT * FROM {t} WHERE asset LIKE '%MCD%' ORDER BY rowid DESC LIMIT 20"
            ).fetchall()
            if rows:
                print(f"\n  --- MCD_OTC en {t} ({len(rows)} filas) ---")
                for r in rows:
                    print(dict(r))
            else:
                print(f"  Sin registros MCD en {t}")
        except Exception as e:
            print(f"  No tiene col asset: {e}")
            # Mostrar últimas 5 filas para ver la estructura
            rows = con.execute(f"SELECT * FROM {t} ORDER BY rowid DESC LIMIT 5").fetchall()
            for r in rows:
                print(dict(r))

    con.close()
