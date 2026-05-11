#!/usr/bin/env python
from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Dict, Iterable, List

RUNTIME_RE = re.compile(
    r"SHADOW-RUNTIME \| cand:(?P<cand>[-0-9.]+)\s+"
    r"scan_ms\(avg/max\):(?P<scan_avg>[-0-9.]+)/(?P<scan_max>[-0-9.]+)\s+"
    r"eval_ms\(avg/max\):(?P<eval_avg>[-0-9.]+)/(?P<eval_max>[-0-9.]+)\s+"
    r"persist_ms\(avg/max\):(?P<persist_avg>[-0-9.]+)/(?P<persist_max>[-0-9.]+)\s+"
    r"extra_ms\(avg/max\):(?P<extra_avg>[-0-9.]+)/(?P<extra_max>[-0-9.]+)"
)

DATA_RE = re.compile(
    r"SHADOW-DATA \| rows/min:(?P<rows_per_min>[-0-9.]+)\s+"
    r"explain_chars\(avg\):(?P<explain_avg>[-0-9.]+)\s+"
    r"htf_fetch_ratio:(?P<htf_ratio>[-0-9.]+)%\s+"
    r"c5_drift:(?P<c5_drift>[-0-9.]+)\s+"
    r"cid_missing:(?P<cid_missing>[-0-9.]+)\s+"
    r"eval_err:(?P<eval_err>[-0-9.]+)\s+"
    r"persist_err:(?P<persist_err>[-0-9.]+)\s+"
    r"hashΔ:(?P<hash_delta>[-0-9.]+)\s+hash=:\s*(?P<hash_same>[-0-9.]+)"
)

ENTRY_WAIT_RE = re.compile(r"ENTRY_LOCK\] acquired .*?wait_ms=(?P<wait>[-0-9.]+)")
ENTRY_HELD_RE = re.compile(r"ENTRY_LOCK\] released .*?held_ms=(?P<held>[-0-9.]+)")


def percentile(values: List[float], p: float) -> float:
    if not values:
        return 0.0
    if p <= 0:
        return min(values)
    if p >= 100:
        return max(values)
    data = sorted(values)
    k = (len(data) - 1) * (p / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return float(data[int(k)])
    d0 = data[f] * (c - k)
    d1 = data[c] * (k - f)
    return float(d0 + d1)


def stats(values: List[float]) -> Dict[str, float]:
    if not values:
        return {"count": 0, "avg": 0.0, "p95": 0.0, "max": 0.0, "min": 0.0}
    return {
        "count": len(values),
        "avg": float(mean(values)),
        "p95": float(percentile(values, 95.0)),
        "max": float(max(values)),
        "min": float(min(values)),
    }


def parse_logs(files: Iterable[Path]) -> Dict[str, List[float]]:
    samples: Dict[str, List[float]] = defaultdict(list)
    for path in files:
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                m = RUNTIME_RE.search(line)
                if m:
                    for k in ("cand", "scan_avg", "scan_max", "eval_avg", "eval_max", "persist_avg", "persist_max", "extra_avg", "extra_max"):
                        samples[k].append(float(m.group(k)))
                    continue
                m = DATA_RE.search(line)
                if m:
                    for k in ("rows_per_min", "explain_avg", "htf_ratio", "c5_drift", "cid_missing", "eval_err", "persist_err", "hash_delta", "hash_same"):
                        samples[k].append(float(m.group(k)))
                    continue
                m = ENTRY_WAIT_RE.search(line)
                if m:
                    samples["entry_wait_ms"].append(float(m.group("wait")))
                    continue
                m = ENTRY_HELD_RE.search(line)
                if m:
                    samples["entry_held_ms"].append(float(m.group("held")))
    return samples


def detect_anomalies(summary: Dict[str, Dict[str, float]], thresholds: Dict[str, float]) -> List[str]:
    alerts: List[str] = []

    if summary["c5_drift"]["max"] > 0:
        alerts.append("c5_drift > 0 detected")
    if summary["eval_err"]["max"] > 0:
        alerts.append("eval_err > 0 detected")
    if summary["persist_err"]["max"] > 0:
        alerts.append("persist_err > 0 detected")
    if summary["entry_wait_ms"]["p95"] > thresholds["entry_wait_p95_ms"]:
        alerts.append(
            f"ENTRY_LOCK wait p95 {summary['entry_wait_ms']['p95']:.2f}ms > {thresholds['entry_wait_p95_ms']:.2f}ms"
        )
    if summary["extra_avg"]["p95"] > thresholds["extra_p95_ms"]:
        alerts.append(
            f"extra_ms(avg) p95 {summary['extra_avg']['p95']:.3f}ms > {thresholds['extra_p95_ms']:.3f}ms"
        )
    if summary["persist_avg"]["p95"] > thresholds["persist_p95_ms"]:
        alerts.append(
            f"persist_ms(avg) p95 {summary['persist_avg']['p95']:.3f}ms > {thresholds['persist_p95_ms']:.3f}ms"
        )
    if summary["scan_avg"]["p95"] > thresholds["scan_avg_p95_ms"]:
        alerts.append(
            f"scan_ms(avg) p95 {summary['scan_avg']['p95']:.3f}ms > {thresholds['scan_avg_p95_ms']:.3f}ms"
        )

    return alerts


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse SHADOW-RUNTIME/SHADOW-DATA logs and export summary")
    parser.add_argument("--log", action="append", required=True, help="Log file path. Can be repeated.")
    parser.add_argument("--json-out", default="", help="Output JSON path")
    parser.add_argument("--csv-out", default="", help="Output CSV path")
    parser.add_argument("--entry-wait-p95-ms", type=float, default=50.0)
    parser.add_argument("--extra-p95-ms", type=float, default=5.0)
    parser.add_argument("--persist-p95-ms", type=float, default=10.0)
    parser.add_argument("--scan-avg-p95-ms", type=float, default=1500.0)
    args = parser.parse_args()

    files = [Path(p) for p in args.log]
    samples = parse_logs(files)

    wanted = [
        "cand",
        "scan_avg",
        "scan_max",
        "eval_avg",
        "eval_max",
        "persist_avg",
        "persist_max",
        "extra_avg",
        "extra_max",
        "rows_per_min",
        "explain_avg",
        "htf_ratio",
        "c5_drift",
        "cid_missing",
        "eval_err",
        "persist_err",
        "hash_delta",
        "hash_same",
        "entry_wait_ms",
        "entry_held_ms",
    ]

    summary = {k: stats(samples.get(k, [])) for k in wanted}

    derived = {
        "estimated_cost_per_candidate_ms": summary["extra_avg"]["avg"],
        "estimated_cost_per_minute_ms": summary["extra_avg"]["avg"] * summary["rows_per_min"]["avg"],
        "entry_lock_wait_p95_ms": summary["entry_wait_ms"]["p95"],
        "entry_lock_held_p95_ms": summary["entry_held_ms"]["p95"],
    }

    thresholds = {
        "entry_wait_p95_ms": args.entry_wait_p95_ms,
        "extra_p95_ms": args.extra_p95_ms,
        "persist_p95_ms": args.persist_p95_ms,
        "scan_avg_p95_ms": args.scan_avg_p95_ms,
    }

    anomalies = detect_anomalies(summary, thresholds)

    report = {
        "inputs": [str(p) for p in files],
        "summary": summary,
        "derived": derived,
        "thresholds": thresholds,
        "anomalies": anomalies,
    }

    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2), encoding="utf-8")

    if args.csv_out:
        out = Path(args.csv_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["metric", "count", "avg", "p95", "max", "min"])
            for metric, s in summary.items():
                writer.writerow([metric, s["count"], s["avg"], s["p95"], s["max"], s["min"]])

    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
