from __future__ import annotations

import asyncio
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

from pyquotex.stable_api import Quotex

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import consolidation_bot as cb
from analyze_snapshot_pairs_week import (
    _analyze_strat_b,
    _asset_candidates,
    _fetch_week_multiframe,
    _write_candles_csv,
)

STRAT_B_PAIRS: List[Tuple[str, str]] = [
    ("ATOUSD_OTC", "call"),
    ("AUDCHF_OTC", "call"),
    ("CHFJPY_OTC", "call"),
    ("AUDUSD_OTC", "put"),
    ("USDMXN_OTC", "put"),
]


def _fmt_ts(ts: int) -> str:
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _latest_rows(rows, n: int = 5):
    return sorted(rows, key=lambda r: r.ts, reverse=True)[:n]


async def main() -> None:
    if not cb.EMAIL or not cb.PASSWORD:
        raise RuntimeError("Faltan QUOTEX_EMAIL/QUOTEX_PASSWORD en .env")

    out_root = ROOT / "data" / "exports" / f"stratb_latest_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    out_root.mkdir(parents=True, exist_ok=True)
    candles_dir = out_root / "candles"
    candles_dir.mkdir(parents=True, exist_ok=True)

    client = Quotex(email=cb.EMAIL, password=cb.PASSWORD)
    ok, reason = await cb.connect_with_retry(client)
    if not ok:
        raise RuntimeError(f"No conecta a Quotex: {reason}")

    report_lines: List[str] = []
    report_lines.append("# STRAT-B Analisis de ultimas entradas")
    report_lines.append("")
    report_lines.append(f"Generado: {datetime.now().isoformat(timespec='seconds')}")
    report_lines.append("")

    summary_csv = out_root / "summary_latest.csv"
    detail_csv = out_root / "latest_entries.csv"

    summary_rows: List[Dict[str, object]] = []
    detail_rows: List[Dict[str, object]] = []

    try:
        for asset, direction in STRAT_B_PAIRS:
            candles_by_tf = {}
            selected_symbol = None
            for sym in _asset_candidates(asset):
                try:
                    got = await _fetch_week_multiframe(client, sym)
                except Exception:
                    got = {}
                if got and got.get("1m") and got.get("5m") and got.get("1h"):
                    candles_by_tf = got
                    selected_symbol = sym
                    break

            if not candles_by_tf:
                summary_rows.append(
                    {
                        "asset": asset,
                        "direction": direction,
                        "status": "NO_DATA",
                        "signals": 0,
                        "resolved": 0,
                        "wins": 0,
                        "losses": 0,
                        "winrate_pct": 0.0,
                        "latest_ts": "",
                    }
                )
                report_lines.append(f"## {asset} {direction.upper()}")
                report_lines.append("- Estado: sin datos descargados")
                report_lines.append("")
                continue

            _write_candles_csv(candles_dir / f"{asset}_1m.csv", candles_by_tf["1m"])
            _write_candles_csv(candles_dir / f"{asset}_5m.csv", candles_by_tf["5m"])
            _write_candles_csv(candles_dir / f"{asset}_1h.csv", candles_by_tf["1h"])

            rows = _analyze_strat_b(asset, direction, candles_by_tf["1m"])
            resolved = [r for r in rows if r.win_5m is not None]
            wins = sum(1 for r in resolved if r.win_5m)
            losses = sum(1 for r in resolved if r.win_5m is False)
            winrate = (wins / len(resolved) * 100.0) if resolved else 0.0

            latest = _latest_rows(rows, n=5)
            latest_ts = _fmt_ts(latest[0].ts) if latest else ""

            summary_rows.append(
                {
                    "asset": asset,
                    "direction": direction,
                    "status": "OK",
                    "symbol_used": selected_symbol,
                    "signals": len(rows),
                    "resolved": len(resolved),
                    "wins": wins,
                    "losses": losses,
                    "winrate_pct": round(winrate, 2),
                    "latest_ts": latest_ts,
                }
            )

            report_lines.append(f"## {asset} {direction.upper()}")
            report_lines.append(
                f"- Senales semana: {len(rows)} | Resueltas: {len(resolved)} | W/L: {wins}/{losses} | Winrate: {winrate:.1f}%"
            )
            if latest:
                report_lines.append("- Ultimas entradas:")
            else:
                report_lines.append("- Ultimas entradas: sin senales")

            for i, r in enumerate(latest, start=1):
                signal_type = str(r.meta.get("signal_type", ""))
                reason = str(r.meta.get("reason", ""))
                edge = float(r.meta.get("edge_bps", 0.0))
                result_txt = "WIN" if r.win_5m is True else ("LOSS" if r.win_5m is False else "PEND")
                report_lines.append(
                    f"  {i}. {_fmt_ts(r.ts)} | conf={r.confidence:.3f} | type={signal_type} | "
                    f"entry={r.entry_price:.6f} exit5m={'' if r.exit_price_5m is None else f'{r.exit_price_5m:.6f}'} | "
                    f"{result_txt} | edge={edge:.1f} bps"
                )
                if reason:
                    report_lines.append(f"     razon: {reason}")

                detail_rows.append(
                    {
                        "asset": asset,
                        "direction": direction,
                        "ts_utc": _fmt_ts(r.ts),
                        "confidence": round(r.confidence, 6),
                        "signal_type": signal_type,
                        "reason": reason,
                        "entry_price": r.entry_price,
                        "exit_price_5m": r.exit_price_5m,
                        "win_5m": r.win_5m,
                        "edge_bps": round(edge, 3),
                    }
                )

            report_lines.append("")

    finally:
        try:
            await client.close()
        except Exception:
            pass

    with summary_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(summary_rows[0].keys()) if summary_rows else ["asset"])
        w.writeheader()
        for row in summary_rows:
            w.writerow(row)

    with detail_csv.open("w", newline="", encoding="utf-8") as f:
        fieldnames = [
            "asset",
            "direction",
            "ts_utc",
            "confidence",
            "signal_type",
            "reason",
            "entry_price",
            "exit_price_5m",
            "win_5m",
            "edge_bps",
        ]
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for row in detail_rows:
            w.writerow(row)

    (out_root / "REPORT.md").write_text("\n".join(report_lines), encoding="utf-8")
    (out_root / "params.json").write_text(
        json.dumps({"pairs": STRAT_B_PAIRS, "window": "7d", "timeframes": ["1m", "5m", "1h"]}, indent=2),
        encoding="utf-8",
    )

    print(f"STRATB_ANALYSIS_OK {out_root}")


if __name__ == "__main__":
    asyncio.run(main())
