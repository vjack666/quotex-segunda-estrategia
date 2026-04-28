from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path
from typing import Optional, Tuple

# Cargar .env igual que consolidation_bot
for _candidate in (Path(__file__).parent / ".env", Path(__file__).parent.parent.parent / ".env"):
    if _candidate.exists():
        for _ln in _candidate.read_text(encoding="utf-8").splitlines():
            _ln = _ln.strip()
            if _ln and not _ln.startswith("#") and "=" in _ln:
                _k, _, _v = _ln.partition("=")
                os.environ.setdefault(_k.strip(), _v.strip())
        break

from pyquotex.stable_api import Quotex  # type: ignore

EMAIL = os.environ.get("QUOTEX_EMAIL", "")
PASSWORD = os.environ.get("QUOTEX_PASSWORD", "")
TARGET_ASSET = "USDARS_otc"
AMOUNT = 1.0
DURATIONS_TO_TEST = [120, 60]
DIRECTIONS_TO_TEST = ["call", "put"]


async def _pick_asset(client: Quotex) -> Optional[str]:
    instruments = await client.get_instruments()
    if not instruments:
        return None

    open_otc = []
    for i in instruments:
        try:
            sym = str(i[1])
            is_open = bool(i[14])
            payout = int(i[18]) if len(i) > 18 else 0
        except Exception:
            continue
        if sym.endswith("_otc") and is_open and payout >= 80:
            open_otc.append((sym, payout))

    open_otc.sort(key=lambda x: -x[1])
    if not open_otc:
        return None

    # Prioriza el mismo activo del error si está abierto.
    for sym, _ in open_otc:
        if sym == TARGET_ASSET:
            return sym
    return open_otc[0][0]


async def _send_order(client: Quotex, asset: str, direction: str, duration: int) -> Tuple[bool, object, float]:
    t0 = time.time()
    status, info = await client.buy(
        amount=AMOUNT,
        asset=asset,
        direction=direction,
        duration=duration,
    )
    elapsed = time.time() - t0
    return bool(status), info, elapsed


async def main() -> None:
    if not EMAIL or not PASSWORD:
        raise RuntimeError("Faltan QUOTEX_EMAIL/QUOTEX_PASSWORD en .env")

    client = Quotex(email=EMAIL, password=PASSWORD)

    ok, reason = await client.connect()
    print(f"connect_ok={ok} reason={reason}")
    if not ok:
        return

    try:
        await client.change_account("PRACTICE")
        bal = await client.get_balance()
        print(f"balance_demo={bal}")

        asset = await _pick_asset(client)
        if not asset:
            print("No hay activos OTC abiertos con payout>=80")
            return

        print(f"asset_test={asset} amount={AMOUNT}")

        for direction in DIRECTIONS_TO_TEST:
            for duration in DURATIONS_TO_TEST:
                print(f"\n--- TEST buy direction={direction.upper()} duration={duration}s ---")
                try:
                    status, info, elapsed = await _send_order(client, asset, direction, duration)
                    print(f"status={status} elapsed={elapsed:.2f}s info={info}")
                except Exception as exc:
                    print(f"exception direction={direction} duration={duration}: {exc}")

    finally:
        try:
            await client.close()
        except Exception:
            pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
