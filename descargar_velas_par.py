from __future__ import annotations

import argparse
import asyncio
import csv
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pyquotex.stable_api import Quotex  # type: ignore


BROKER_TZ = timezone(timedelta(hours=-3))
ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "data" / "exports"
TIMEFRAMES: list[tuple[str, int, int]] = [
    ("1m", 60, 2 * 24 * 60),
    ("5m", 5 * 60, 2 * 24 * 12),
    ("15m", 15 * 60, 2 * 24 * 4),
    ("4h", 4 * 60 * 60, 12),
]


def load_env() -> None:
    for candidate in (ROOT / ".env", ROOT.parent / ".env"):
        if not candidate.exists():
            continue
        for line in candidate.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())
        break


def parse_candle(raw: dict) -> tuple[int, float, float, float, float] | None:
    try:
        return (
            int(raw["time"]),
            float(raw["open"]),
            float(raw["high"]),
            float(raw["low"]),
            float(raw["close"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


async def fetch_candles(client: Quotex, asset: str, tf_sec: int, count: int) -> list[tuple[int, float, float, float, float]]:
    end_time = datetime.now(tz=BROKER_TZ).timestamp()
    offset = tf_sec * count
    try:
        raw = await client.get_candles(asset, end_time, offset, tf_sec)
    except Exception:
        return []
    candles = [parse_candle(item) for item in (raw or []) if isinstance(item, dict)]
    out = [c for c in candles if c is not None]
    out.sort(key=lambda c: c[0])
    return out


async def fetch_with_retry(client: Quotex, asset: str, tf_sec: int, count: int) -> list[tuple[int, float, float, float, float]]:
    for attempt in range(1, 4):
        candles = await fetch_candles(client, asset, tf_sec, count)
        if candles:
            return candles
        if attempt < 3:
            await asyncio.sleep(0.6 * attempt)
    return []


def write_csv(asset: str, rows: list[list[object]]) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(tz=BROKER_TZ).strftime("%Y%m%d_%H%M%S")
    safe_asset = "".join(ch if (ch.isalnum() or ch in ("_", "-")) else "_" for ch in asset)
    path = OUT_DIR / f"{ts}_{safe_asset}_multiframe_2dias.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "asset",
            "timeframe",
            "timeframe_sec",
            "ts",
            "iso_broker",
            "open",
            "high",
            "low",
            "close",
            "body",
            "range",
        ])
        writer.writerows(rows)
    return path


async def run(asset: str, account_type: str) -> int:
    load_env()
    email = os.environ.get("QUOTEX_EMAIL", "").strip()
    password = os.environ.get("QUOTEX_PASSWORD", "").strip()
    if not email or not password:
        print("Faltan QUOTEX_EMAIL / QUOTEX_PASSWORD en .env")
        return 1

    client = Quotex(email=email, password=password)
    ok, reason = await client.connect()
    if not ok:
        print(f"No se pudo conectar a Quotex: {reason}")
        return 1

    all_rows: list[list[object]] = []
    try:
        await client.change_account(account_type)
        for tf_label, tf_sec, tf_count in TIMEFRAMES:
            candles = await fetch_with_retry(client, asset, tf_sec, tf_count)
            print(f"{asset} {tf_label}: {len(candles)} velas")
            for ts, opn, high, low, close in candles:
                all_rows.append(
                    [
                        asset,
                        tf_label,
                        tf_sec,
                        ts,
                        datetime.fromtimestamp(ts, tz=BROKER_TZ).isoformat(),
                        f"{opn:.10f}",
                        f"{high:.10f}",
                        f"{low:.10f}",
                        f"{close:.10f}",
                        f"{abs(close - opn):.10f}",
                        f"{(high - low):.10f}",
                    ]
                )
        if not all_rows:
            print("No se pudieron descargar velas para ningún timeframe.")
            return 1
        out = write_csv(asset, all_rows)
        print(f"CSV generado: {out}")
        return 0
    finally:
        try:
            await client.close()
        except Exception:
            pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Descargar velas de un solo par en un CSV multi-timeframe (2 dias equivalentes)."
    )
    parser.add_argument("--asset", type=str, default="USDINR_otc", help="Par a descargar")
    parser.add_argument("--account", type=str, default="PRACTICE", choices=["PRACTICE", "REAL"], help="Cuenta para lectura")
    return parser


if __name__ == "__main__":
    args = build_parser().parse_args()
    raise SystemExit(asyncio.run(run(args.asset, args.account)))