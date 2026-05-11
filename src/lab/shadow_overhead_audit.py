#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any, Dict


def latest_journal_db(db_dir: Path) -> Path:
    dbs = sorted(db_dir.glob("trade_journal-*.db"))
    if not dbs:
        raise FileNotFoundError(f"No trade_journal DB files found in {db_dir}")
    return dbs[-1]


def get_shadow_rows(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='shadow_decision_audit'"
    ).fetchone()
    if not row or int(row[0]) == 0:
        return 0
    return int(conn.execute("SELECT COUNT(*) FROM shadow_decision_audit").fetchone()[0])


def load_parser_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit runtime overhead from parser summary + DB")
    parser.add_argument("--parser-json", required=True, help="JSON produced by parse_shadow_logs.py")
    parser.add_argument("--db", default="", help="Path to trade_journal DB (default latest data/db)")
    parser.add_argument("--db-dir", default="data/db")
    parser.add_argument("--scan-interval-sec", type=float, default=60.0)
    parser.add_argument("--entry-wait-p95-th-ms", type=float, default=50.0)
    parser.add_argument("--scan-utilization-th-pct", type=float, default=15.0)
    parser.add_argument("--json-out", default="")
    args = parser.parse_args()

    parser_json = load_parser_json(Path(args.parser_json))
    summary = parser_json.get("summary", {})

    db_path = Path(args.db) if args.db else latest_journal_db(Path(args.db_dir))
    conn = sqlite3.connect(str(db_path))
    shadow_rows = get_shadow_rows(conn)
    db_size_bytes = db_path.stat().st_size if db_path.exists() else 0

    rows_per_min = float(summary.get("rows_per_min", {}).get("avg", 0.0) or 0.0)
    extra_ms_per_candidate = float(summary.get("extra_avg", {}).get("avg", 0.0) or 0.0)
    scan_ms_avg = float(summary.get("scan_avg", {}).get("avg", 0.0) or 0.0)
    scan_ms_p95 = float(summary.get("scan_avg", {}).get("p95", 0.0) or 0.0)
    entry_wait_p95 = float(summary.get("entry_wait_ms", {}).get("p95", 0.0) or 0.0)

    estimated_cost_per_minute_ms = extra_ms_per_candidate * rows_per_min
    estimated_cost_per_hour_ms = estimated_cost_per_minute_ms * 60.0

    avg_bytes_per_shadow_row = (db_size_bytes / shadow_rows) if shadow_rows > 0 else 0.0
    estimated_db_growth_per_hour_bytes = rows_per_min * 60.0 * avg_bytes_per_shadow_row
    estimated_db_growth_per_hour_mb = estimated_db_growth_per_hour_bytes / (1024.0 * 1024.0)

    scan_interval_ms = max(args.scan_interval_sec, 0.001) * 1000.0
    scan_utilization_pct = (scan_ms_avg / scan_interval_ms) * 100.0
    scan_utilization_p95_pct = (scan_ms_p95 / scan_interval_ms) * 100.0

    risks = []
    if entry_wait_p95 > args.entry_wait_p95_th_ms:
        risks.append("ENTRY_LOCK wait p95 above threshold")
    if scan_utilization_pct > args.scan_utilization_th_pct:
        risks.append("scan loop utilization avg above threshold")
    if float(summary.get("persist_err", {}).get("max", 0.0) or 0.0) > 0:
        risks.append("persist_err > 0")
    if float(summary.get("eval_err", {}).get("max", 0.0) or 0.0) > 0:
        risks.append("eval_err > 0")

    report = {
        "db_path": str(db_path),
        "db_size_bytes": db_size_bytes,
        "shadow_rows": shadow_rows,
        "avg_bytes_per_shadow_row": avg_bytes_per_shadow_row,
        "rows_per_minute_avg": rows_per_min,
        "extra_ms_per_candidate_avg": extra_ms_per_candidate,
        "estimated_cost_per_minute_ms": estimated_cost_per_minute_ms,
        "estimated_cost_per_hour_ms": estimated_cost_per_hour_ms,
        "estimated_db_growth_per_hour_mb": estimated_db_growth_per_hour_mb,
        "scan_interval_sec": args.scan_interval_sec,
        "scan_ms_avg": scan_ms_avg,
        "scan_ms_p95": scan_ms_p95,
        "scan_utilization_avg_pct": scan_utilization_pct,
        "scan_utilization_p95_pct": scan_utilization_p95_pct,
        "entry_wait_p95_ms": entry_wait_p95,
        "risks": risks,
    }

    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
