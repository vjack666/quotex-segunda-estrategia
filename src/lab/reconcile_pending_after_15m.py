"""
Reconciliar operaciones PENDING con antiguedad minima (por defecto 15 minutos).

Uso:
    python src/lab/reconcile_pending_after_15m.py
    python src/lab/reconcile_pending_after_15m.py --minutes 20
    python src/lab/reconcile_pending_after_15m.py --real
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SRC_DIR = ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import consolidation_bot as cb
from pyquotex.stable_api import Quotex


async def run(minutes: float, real: bool) -> int:
    if not cb.EMAIL or not cb.PASSWORD:
        print("ERROR: Falta QUOTEX_EMAIL / QUOTEX_PASSWORD en el .env")
        return 1

    client = Quotex(email=cb.EMAIL, password=cb.PASSWORD)

    ok, reason = await cb.connect_with_retry(client)
    if not ok:
        print(f"ERROR: no se pudo conectar ({reason})")
        return 2

    account_type = "REAL" if real else "PRACTICE"
    await client.change_account(account_type)

    bot = cb.ConsolidationBot(
        client=client,
        dry_run=False,
        account_type=account_type,
    )

    await bot.reconcile_pending_candidates(max_age_minutes=minutes)

    try:
        await client.close()
    except Exception:
        pass

    print(f"OK: reconciliacion completada para PENDING >= {minutes:.1f} min")
    return 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Reconciliar PENDING con edad minima",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--minutes", type=float, default=15.0, help="Edad minima en minutos")
    p.add_argument("--real", action="store_true", help="Usar cuenta REAL en vez de PRACTICE")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    raise SystemExit(asyncio.run(run(args.minutes, args.real)))
