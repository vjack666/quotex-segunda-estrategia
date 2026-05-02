"""
review_expired_zones.py
=======================
Script de diagnóstico para revisar por qué y cómo expiraron las zonas
de consolidación detectadas por el bot.

USO:
    python src/lab/review_expired_zones.py               # últimas 40 expiradas
    python src/lab/review_expired_zones.py --n 100       # últimas 100
    python src/lab/review_expired_zones.py --reason TIME_LIMIT
    python src/lab/review_expired_zones.py --reason BROKEN_ABOVE
    python src/lab/review_expired_zones.py --reason BROKEN_BELOW
    python src/lab/review_expired_zones.py --asset EURUSD_otc
    python src/lab/review_expired_zones.py --hours 6     # últimas 6 horas
    python src/lab/review_expired_zones.py --export      # exporta CSV

RAZONES POSIBLES:
    TIME_LIMIT    — la zona duró más de MAX_CONSOLIDATION_MIN (30 min) sin señal
    BROKEN_ABOVE  — el precio rompió el TECHO con fuerza (vela > 1.5× cuerpo medio)
    BROKEN_BELOW  — el precio rompió el PISO con fuerza (vela > 1.5× cuerpo medio)
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = ROOT / "data" / "db" / "trade_journal.db"

BROKER_TZ = timezone(timedelta(hours=-3))


def _require_sqlite():
    import sqlite3
    if not DB_PATH.exists():
        print(f"ERROR: No se encontró la base de datos en {DB_PATH}")
        sys.exit(1)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _build_query(args) -> tuple[str, list]:
    conditions = []
    params: list = []

    if args.hours:
        since = (datetime.now(tz=BROKER_TZ) - timedelta(hours=args.hours)).isoformat()
        conditions.append("expired_at >= ?")
        params.append(since)

    if args.reason:
        conditions.append("expiry_reason = ?")
        params.append(args.reason.upper())

    if args.asset:
        conditions.append("asset LIKE ?")
        params.append(f"%{args.asset}%")

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params.append(args.n)

    query = f"""
        SELECT expired_at, asset, expiry_reason,
               ceiling, floor, range_pct, bars_inside,
               age_min, last_close, break_body, payout
        FROM expired_zones
        {where}
        ORDER BY id DESC
        LIMIT ?
    """
    return query, params


def _print_table(rows, title: str) -> None:
    reason_icon = {
        "TIME_LIMIT":    "⏱ ",
        "BROKEN_ABOVE":  "🔴",
        "BROKEN_BELOW":  "🟢",
    }

    print(f"\n{'═'*88}")
    print(f"  {title}")
    print(f"{'═'*88}")

    if not rows:
        print("  Sin registros que coincidan con los filtros.")
        print(f"{'═'*88}\n")
        return

    print(
        f"  {'Hora':<19}  {'Activo':<22}  {'Razón':<14}  "
        f"{'Edad':>5}m  {'Rango':>6}%  {'Barras':>6}  {'Precio':>9}  {'Cuerpo ruptura':>14}"
    )
    print(f"  {'─'*84}")

    for r in rows:
        icon = reason_icon.get(r["expiry_reason"], "? ")
        rng = (r["range_pct"] or 0.0) * 100
        body_txt = f"{r['break_body']:.5f}" if r["break_body"] else "─"
        print(
            f"  {r['expired_at'][:19]}  {r['asset']:<22}  "
            f"{icon}{r['expiry_reason']:<12}  "
            f"{(r['age_min'] or 0):>5.1f}m  {rng:>6.3f}%  "
            f"{(r['bars_inside'] or 0):>6}  "
            f"{(r['last_close'] or 0):>9.5f}  "
            f"{body_txt:>14}"
        )

    # Resumen
    total = len(rows)
    by_reason: dict[str, int] = {}
    for r in rows:
        by_reason[r["expiry_reason"]] = by_reason.get(r["expiry_reason"], 0) + 1

    print(f"\n  {'RESUMEN':.─<45}")
    print(f"  Total mostradas: {total}")
    for reason, count in sorted(by_reason.items(), key=lambda x: -x[1]):
        icon = reason_icon.get(reason, "? ")
        print(f"  {icon} {reason:<15}  {count:>4}x  ({count/total*100:.1f}%)")
    print(f"{'═'*88}\n")


def _export_csv(rows, path: Path) -> None:
    if not rows:
        print("  Sin datos para exportar.")
        return
    fieldnames = ["expired_at", "asset", "expiry_reason", "ceiling", "floor",
                  "range_pct", "bars_inside", "age_min", "last_close", "break_body", "payout"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r[k] for k in fieldnames})
    print(f"  Exportado → {path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Revisar zonas expiradas del bot de consolidación",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--n", type=int, default=40, help="Número máximo de registros")
    parser.add_argument(
        "--reason",
        choices=["TIME_LIMIT", "BROKEN_ABOVE", "BROKEN_BELOW"],
        default=None,
        help="Filtrar por causa de expiración",
    )
    parser.add_argument("--asset", type=str, default=None, help="Filtrar por activo (parcial)")
    parser.add_argument("--hours", type=float, default=None, help="Últimas N horas")
    parser.add_argument("--export", action="store_true", help="Exportar CSV a raíz del proyecto")
    args = parser.parse_args()

    conn = _require_sqlite()
    query, params = _build_query(args)
    rows = conn.execute(query, params).fetchall()
    conn.close()

    title = "ZONAS EXPIRADAS"
    filters = []
    if args.reason:
        filters.append(f"razón={args.reason}")
    if args.asset:
        filters.append(f"activo~{args.asset}")
    if args.hours:
        filters.append(f"últimas {args.hours}h")
    if filters:
        title += f"  [{', '.join(filters)}]"

    _print_table(rows, title)

    if args.export:
        out = ROOT / "expired_zones_export.csv"
        _export_csv(rows, out)


if __name__ == "__main__":
    main()
