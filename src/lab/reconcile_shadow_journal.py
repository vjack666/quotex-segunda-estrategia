#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Tuple

HASH_RE = re.compile(r"^[0-9a-f]{64}$")


def latest_journal_db(db_dir: Path) -> Path:
    dbs = sorted(db_dir.glob("trade_journal-*.db"))
    if not dbs:
        raise FileNotFoundError(f"No trade_journal DB files found in {db_dir}")
    return dbs[-1]


def fetch_one(conn: sqlite3.Connection, sql: str, params: Tuple[Any, ...] = ()) -> Any:
    cur = conn.execute(sql, params)
    row = cur.fetchone()
    return row[0] if row else 0


def fetch_rows(conn: sqlite3.Connection, sql: str, params: Tuple[Any, ...] = ()) -> List[sqlite3.Row]:
    cur = conn.execute(sql, params)
    return cur.fetchall()


def main() -> int:
    parser = argparse.ArgumentParser(description="Reconcile shadow_decision_audit integrity and linkage")
    parser.add_argument("--db", default="", help="Path to trade_journal DB (default: latest in data/db)")
    parser.add_argument("--db-dir", default="data/db", help="DB directory used when --db is omitted")
    parser.add_argument("--stale-minutes", type=int, default=20, help="Threshold for stale NO_TRADE rows")
    parser.add_argument("--json-out", default="", help="Optional output JSON path")
    args = parser.parse_args()

    db_path = Path(args.db) if args.db else latest_journal_db(Path(args.db_dir))
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    report: Dict[str, Any] = {
        "db_path": str(db_path),
        "stale_minutes": args.stale_minutes,
        "counts": {},
        "samples": {},
        "risks": [],
    }

    table_exists = fetch_one(
        conn,
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='shadow_decision_audit'",
    )
    if not table_exists:
        report["counts"]["shadow_table_exists"] = 0
        report["risks"].append("shadow_decision_audit table not found")
        if args.json_out:
            out = Path(args.json_out)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
        return 1

    report["counts"]["shadow_table_exists"] = 1

    q = report["counts"]
    q["shadow_total_rows"] = fetch_one(conn, "SELECT COUNT(*) FROM shadow_decision_audit")
    q["candidate_id_null"] = fetch_one(conn, "SELECT COUNT(*) FROM shadow_decision_audit WHERE candidate_id IS NULL")
    q["snapshot_ts_null"] = fetch_one(
        conn,
        "SELECT COUNT(*) FROM shadow_decision_audit WHERE context_snapshot_ts IS NULL OR TRIM(context_snapshot_ts)=''",
    )
    q["context_hash_empty"] = fetch_one(
        conn,
        "SELECT COUNT(*) FROM shadow_decision_audit WHERE context_hash IS NULL OR TRIM(context_hash)=''",
    )
    q["stale_no_trade"] = fetch_one(
        conn,
        "SELECT COUNT(*) FROM shadow_decision_audit "
        "WHERE trade_outcome='NO_TRADE' AND created_at <= datetime('now', ?)",
        (f"-{args.stale_minutes} minutes",),
    )

    q["candidate_id_not_found"] = fetch_one(
        conn,
        "SELECT COUNT(*) FROM shadow_decision_audit s "
        "LEFT JOIN candidates c ON c.id = s.candidate_id "
        "WHERE s.candidate_id IS NOT NULL AND c.id IS NULL",
    )

    with_candidate = fetch_one(conn, "SELECT COUNT(*) FROM shadow_decision_audit WHERE candidate_id IS NOT NULL")
    linked_outcome = fetch_one(
        conn,
        "SELECT COUNT(*) FROM shadow_decision_audit WHERE candidate_id IS NOT NULL AND trade_outcome <> 'NO_TRADE'",
    )
    q["with_candidate"] = with_candidate
    q["linked_outcome"] = linked_outcome
    q["linkage_pct"] = round((100.0 * linked_outcome / with_candidate), 4) if with_candidate else 0.0

    q["martin_without_candidate_id"] = fetch_one(
        conn,
        "SELECT COUNT(*) FROM shadow_decision_audit WHERE LOWER(stage)='martin' AND candidate_id IS NULL",
    )

    # Hash validation (strict hex64)
    bad_hash_rows = fetch_rows(
        conn,
        "SELECT id, context_hash FROM shadow_decision_audit WHERE context_hash IS NOT NULL AND TRIM(context_hash)<>''",
    )
    invalid_hash = 0
    invalid_hash_ids: List[int] = []
    for row in bad_hash_rows:
        h = str(row["context_hash"]).strip().lower()
        if not HASH_RE.match(h):
            invalid_hash += 1
            invalid_hash_ids.append(int(row["id"]))
    q["invalid_hash"] = invalid_hash

    # Divergence summary
    div_rows = fetch_rows(
        conn,
        "SELECT compare_status, COUNT(*) AS n FROM shadow_decision_audit GROUP BY compare_status ORDER BY n DESC",
    )
    report["compare_status"] = {str(r["compare_status"]): int(r["n"]) for r in div_rows}

    # Repeated candidate_id risk
    rep_rows = fetch_rows(
        conn,
        "SELECT candidate_id, COUNT(*) AS n FROM shadow_decision_audit "
        "WHERE candidate_id IS NOT NULL GROUP BY candidate_id HAVING COUNT(*) > 1 ORDER BY n DESC LIMIT 50",
    )
    q["candidate_id_repeated"] = len(rep_rows)
    report["samples"]["candidate_id_repeated_top"] = [
        {"candidate_id": int(r["candidate_id"]), "rows": int(r["n"])} for r in rep_rows
    ]

    # Samples
    missing_outcome_rows = fetch_rows(
        conn,
        "SELECT id, candidate_id, asset, stage, created_at FROM shadow_decision_audit "
        "WHERE candidate_id IS NOT NULL AND trade_outcome='NO_TRADE' "
        "AND created_at <= datetime('now', ?) ORDER BY created_at ASC LIMIT 50",
        (f"-{args.stale_minutes} minutes",),
    )
    report["samples"]["stale_no_trade_rows"] = [dict(r) for r in missing_outcome_rows]
    report["samples"]["invalid_hash_ids"] = invalid_hash_ids[:50]

    # Risk flags
    if q["snapshot_ts_null"] > 0:
        report["risks"].append("null context_snapshot_ts detected")
    if q["invalid_hash"] > 0:
        report["risks"].append("invalid context_hash detected")
    if q["candidate_id_not_found"] > 0:
        report["risks"].append("candidate_id references missing candidates rows")
    if q["stale_no_trade"] > 0:
        report["risks"].append("stale NO_TRADE rows detected")
    if q["martin_without_candidate_id"] > 0:
        report["risks"].append("martin rows without candidate_id detected")
    if q["candidate_id_repeated"] > 0:
        report["risks"].append("candidate_id repeated in shadow rows (multiple update risk)")

    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
