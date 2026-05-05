from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parents[1]
EXPORTS = ROOT / "data" / "exports"

PAIRS = ["ATOUSD_OTC", "AUDCHF_OTC", "CHFJPY_OTC", "AUDUSD_OTC", "USDMXN_OTC"]


def _latest_snapshot_dir() -> Path:
    dirs = sorted(EXPORTS.glob("snapshot_pairs_week_*"))
    if not dirs:
        raise RuntimeError("No hay export snapshot_pairs_week_* para analizar")
    return dirs[-1]


def _read_rows(path: Path) -> List[Dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def main() -> None:
    target = _latest_snapshot_dir()
    signals = _read_rows(target / "signals_week.csv")

    strat_b = [r for r in signals if str(r.get("strategy", "")).strip() == "STRAT-B"]

    out_lines: List[str] = []
    out_lines.append("# STRAT-B ultimas entradas")
    out_lines.append("")
    out_lines.append(f"Fuente: {target}")
    out_lines.append(f"Generado: {datetime.now().isoformat(timespec='seconds')}")
    out_lines.append("")

    for asset in PAIRS:
        rows = [r for r in strat_b if str(r.get("asset", "")).strip() == asset]
        rows.sort(key=lambda r: str(r.get("datetime_utc", "")), reverse=True)
        out_lines.append(f"## {asset}")
        if not rows:
            out_lines.append("- Sin entradas detectadas en la ventana")
            out_lines.append("")
            continue

        wins = sum(1 for r in rows if str(r.get("win_5m", "")).strip() == "1")
        losses = sum(1 for r in rows if str(r.get("win_5m", "")).strip() == "0")
        resolved = wins + losses
        wr = (wins / resolved * 100.0) if resolved else 0.0
        out_lines.append(f"- Total señales: {len(rows)} | Resueltas: {resolved} | W/L: {wins}/{losses} | Winrate: {wr:.1f}%")
        out_lines.append("- Ultimas 5:")

        for i, r in enumerate(rows[:5], start=1):
            ts = str(r.get("datetime_utc", ""))
            direction = str(r.get("direction", "")).upper()
            conf = str(r.get("confidence", ""))
            entry = str(r.get("entry_price", ""))
            exitp = str(r.get("exit_price_5m", ""))
            win_raw = str(r.get("win_5m", "")).strip()
            if win_raw == "1":
                res = "WIN"
            elif win_raw == "0":
                res = "LOSS"
            else:
                res = "PEND"
            meta = str(r.get("meta_json", ""))
            out_lines.append(
                f"  {i}. {ts} | {direction} | conf={conf} | entry={entry} exit5m={exitp} | {res}"
            )
            if meta:
                out_lines.append(f"     meta: {meta}")

        out_lines.append("")

    out_path = target / "STRATB_LATEST_REPORT.md"
    out_path.write_text("\n".join(out_lines), encoding="utf-8")
    print(f"STRATB_LATEST_OK {out_path}")


if __name__ == "__main__":
    main()
