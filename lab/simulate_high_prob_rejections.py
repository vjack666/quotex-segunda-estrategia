import argparse
import csv
import glob
import json
import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


RE_REJECT = re.compile(
    r"score=\s*([\-\d\.]+)\s*<\s*umbral\s+din[\u00e1a]mico\s*([\-\d\.]+)",
    re.IGNORECASE,
)


@dataclass
class CandidateRow:
    scanned_at: str
    asset: str
    direction: str
    score: float
    threshold: float
    gap: float
    reject_reason: str
    candles_json: str


@dataclass
class SimResult:
    scanned_at: str
    asset: str
    direction: str
    score: float
    threshold: float
    gap: float
    vela_ops_file: str
    matched_seconds: float
    entry_price: Optional[float]
    close_1m: Optional[float]
    close_3m: Optional[float]
    close_5m: Optional[float]
    result_1m: str
    result_3m: str
    result_5m: str


def _parse_iso_ts(value: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


def _parse_reject_reason(reason: str) -> Optional[Tuple[float, float]]:
    if not reason:
        return None
    m = RE_REJECT.search(reason)
    if not m:
        return None
    try:
        score_val = float(m.group(1))
        threshold_val = float(m.group(2))
    except Exception:
        return None
    return score_val, threshold_val


def _latest_db() -> Optional[str]:
    dbs = sorted(glob.glob("data/db/trade_journal-*.db"), reverse=True)
    return dbs[0] if dbs else None


def _load_candidates(db_path: str, top_n: int) -> List[CandidateRow]:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute(
        """
        SELECT scanned_at, asset, direction, score, reject_reason, candles_json
        FROM candidates
        WHERE strategy_origin='STRAT-A' AND decision='REJECTED_SCORE'
        ORDER BY scanned_at ASC
        """
    )
    rows = cur.fetchall()
    con.close()

    out: List[CandidateRow] = []
    for r in rows:
        parsed = _parse_reject_reason(r["reject_reason"] or "")
        if parsed is None:
            continue
        score_from_reason, threshold = parsed
        score_val = float(r["score"] if r["score"] is not None else score_from_reason)
        gap = threshold - score_val
        if gap < 0:
            continue
        out.append(
            CandidateRow(
                scanned_at=str(r["scanned_at"] or ""),
                asset=str(r["asset"] or ""),
                direction=str(r["direction"] or "").upper(),
                score=score_val,
                threshold=threshold,
                gap=gap,
                reject_reason=str(r["reject_reason"] or ""),
                candles_json=str(r["candles_json"] or ""),
            )
        )

    out.sort(key=lambda x: (x.gap, -x.score))
    return out[:top_n]


def _safe_name(text: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in text)


def _export_candles_for_candidate(c: CandidateRow, out_dir: Path) -> Optional[Path]:
    if not c.candles_json:
        return None
    try:
        candles = json.loads(c.candles_json)
    except Exception:
        return None
    if not isinstance(candles, list) or not candles:
        return None

    out_dir.mkdir(parents=True, exist_ok=True)
    ts_label = _safe_name(c.scanned_at.replace(":", "-"))
    fp = out_dir / f"candles5m_{c.asset}_{ts_label}.csv"

    with fp.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["ts", "datetime", "open", "high", "low", "close", "volume"])
        w.writeheader()
        for item in candles:
            ts = int(item.get("ts", 0))
            dt = datetime.fromtimestamp(ts).isoformat(sep=" ") if ts else ""
            w.writerow(
                {
                    "ts": ts,
                    "datetime": dt,
                    "open": item.get("open", ""),
                    "high": item.get("high", ""),
                    "low": item.get("low", ""),
                    "close": item.get("close", ""),
                    "volume": item.get("volume", ""),
                }
            )
    return fp


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _normalize_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, float]]:
    out: List[Dict[str, float]] = []
    for r in rows:
        try:
            out.append(
                {
                    "ts": float(r.get("ts", 0)),
                    "open": float(r.get("open", 0.0)),
                    "high": float(r.get("high", 0.0)),
                    "low": float(r.get("low", 0.0)),
                    "close": float(r.get("close", 0.0)),
                }
            )
        except Exception:
            continue
    out.sort(key=lambda x: x["ts"])
    return out


def _collect_post_1m(payload: Dict[str, Any]) -> List[Dict[str, float]]:
    analysis = payload.get("analysis_1m", {}) if isinstance(payload, dict) else {}
    post_initial = _normalize_rows(analysis.get("post_40_initial", []) if isinstance(analysis, dict) else [])
    followup = payload.get("followup", {}) if isinstance(payload, dict) else {}
    followup_rows = _normalize_rows(followup.get("candles_1m", []) if isinstance(followup, dict) else [])

    merged = post_initial + followup_rows
    seen: set[int] = set()
    out: List[Dict[str, float]] = []
    for r in merged:
        ts_i = int(r["ts"])
        if ts_i in seen:
            continue
        seen.add(ts_i)
        out.append(r)
    out.sort(key=lambda x: x["ts"])
    return out


def _find_closest_vela_ops(asset: str, scanned_at: str, vela_dir: Path) -> Tuple[Optional[Path], Optional[Dict[str, Any]], float]:
    target_dt = _parse_iso_ts(scanned_at)
    if target_dt is None:
        return None, None, 1e18

    best_path: Optional[Path] = None
    best_payload: Optional[Dict[str, Any]] = None
    best_diff = 1e18

    for p in vela_dir.glob(f"*_{asset}_*.json"):
        payload = _read_json(p)
        if payload is None:
            continue
        saved_at = str(payload.get("saved_at", ""))
        sdt = _parse_iso_ts(saved_at)
        if sdt is None:
            continue
        diff = abs((sdt - target_dt).total_seconds())
        if diff < best_diff:
            best_diff = diff
            best_path = p
            best_payload = payload

    return best_path, best_payload, best_diff


def _binary_result(direction: str, entry: Optional[float], close_val: Optional[float]) -> str:
    if entry is None or close_val is None:
        return "NO_DATA"
    d = direction.upper()
    if d == "CALL":
        if close_val > entry:
            return "WIN"
        if close_val < entry:
            return "LOSS"
        return "DRAW"
    if d == "PUT":
        if close_val < entry:
            return "WIN"
        if close_val > entry:
            return "LOSS"
        return "DRAW"
    return "NO_DIR"


def _simulate_from_post(direction: str, post_rows: List[Dict[str, float]]) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[float], str, str, str]:
    if not post_rows:
        return None, None, None, None, "NO_DATA", "NO_DATA", "NO_DATA"

    # Simulacion simple: entrada al open de la primera vela post-trigger.
    entry = float(post_rows[0]["open"])
    close_1m = float(post_rows[0]["close"]) if len(post_rows) >= 1 else None
    close_3m = float(post_rows[2]["close"]) if len(post_rows) >= 3 else None
    close_5m = float(post_rows[4]["close"]) if len(post_rows) >= 5 else None

    r1 = _binary_result(direction, entry, close_1m)
    r3 = _binary_result(direction, entry, close_3m)
    r5 = _binary_result(direction, entry, close_5m)
    return entry, close_1m, close_3m, close_5m, r1, r3, r5


def _write_report(report_path: Path, rows: List[SimResult]) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "scanned_at", "asset", "direction", "score", "threshold", "gap",
                "vela_ops_file", "matched_seconds",
                "entry_price", "close_1m", "close_3m", "close_5m",
                "result_1m", "result_3m", "result_5m",
            ],
        )
        w.writeheader()
        for r in rows:
            w.writerow(
                {
                    "scanned_at": r.scanned_at,
                    "asset": r.asset,
                    "direction": r.direction,
                    "score": round(r.score, 2),
                    "threshold": round(r.threshold, 2),
                    "gap": round(r.gap, 2),
                    "vela_ops_file": r.vela_ops_file,
                    "matched_seconds": round(r.matched_seconds, 1),
                    "entry_price": r.entry_price,
                    "close_1m": r.close_1m,
                    "close_3m": r.close_3m,
                    "close_5m": r.close_5m,
                    "result_1m": r.result_1m,
                    "result_3m": r.result_3m,
                    "result_5m": r.result_5m,
                }
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="Simula entradas para REJECTED_SCORE cercanos al umbral dinamico")
    parser.add_argument("--top", type=int, default=12, help="Cuantos rechazados de alta probabilidad analizar")
    parser.add_argument("--max-match-sec", type=float, default=300.0, help="Maximo delta para matchear snapshot vela_ops")
    args = parser.parse_args()

    db = _latest_db()
    if not db:
        print("No se encontro DB de journal en data/db")
        raise SystemExit(1)

    candidates = _load_candidates(db, top_n=max(1, args.top))
    if not candidates:
        print("No hay REJECTED_SCORE parseables en la DB")
        raise SystemExit(0)

    export_dir = Path("data/candles_candidatos/high_prob_rejected")
    vela_dir = Path("data/vela_ops")

    print(f"DB: {db}")
    print(f"Seleccionados (top {len(candidates)} por gap mas bajo):")
    for i, c in enumerate(candidates, start=1):
        print(f"{i:02d}. {c.scanned_at} | {c.asset:15s} {c.direction:4s} score={c.score:.1f} thr={c.threshold:.1f} gap={c.gap:.1f}")

    for c in candidates:
        _export_candles_for_candidate(c, export_dir)

    sim_rows: List[SimResult] = []
    for c in candidates:
        p, payload, delta_sec = _find_closest_vela_ops(c.asset, c.scanned_at, vela_dir)
        if p is None or payload is None or delta_sec > float(args.max_match_sec):
            sim_rows.append(
                SimResult(
                    scanned_at=c.scanned_at,
                    asset=c.asset,
                    direction=c.direction,
                    score=c.score,
                    threshold=c.threshold,
                    gap=c.gap,
                    vela_ops_file="NO_MATCH",
                    matched_seconds=delta_sec if delta_sec < 1e17 else -1.0,
                    entry_price=None,
                    close_1m=None,
                    close_3m=None,
                    close_5m=None,
                    result_1m="NO_MATCH",
                    result_3m="NO_MATCH",
                    result_5m="NO_MATCH",
                )
            )
            continue

        post = _collect_post_1m(payload)
        entry, c1, c3, c5, r1, r3, r5 = _simulate_from_post(c.direction, post)

        sim_rows.append(
            SimResult(
                scanned_at=c.scanned_at,
                asset=c.asset,
                direction=c.direction,
                score=c.score,
                threshold=c.threshold,
                gap=c.gap,
                vela_ops_file=p.name,
                matched_seconds=delta_sec,
                entry_price=entry,
                close_1m=c1,
                close_3m=c3,
                close_5m=c5,
                result_1m=r1,
                result_3m=r3,
                result_5m=r5,
            )
        )

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_report = Path("aprendizaje/reportes") / f"sim_rechazados_alta_prob_{ts}.csv"
    _write_report(out_report, sim_rows)

    print("\nSimulacion (resumen):")
    for r in sim_rows:
        print(
            f"- {r.asset:15s} {r.direction:4s} gap={r.gap:4.1f} "
            f"match={r.matched_seconds:6.1f}s "
            f"1m={r.result_1m:8s} 3m={r.result_3m:8s} 5m={r.result_5m:8s} file={r.vela_ops_file}"
        )

    def _wr(rows: List[SimResult], attr: str) -> str:
        wins = sum(1 for x in rows if getattr(x, attr) == "WIN")
        losses = sum(1 for x in rows if getattr(x, attr) == "LOSS")
        total = wins + losses
        if total == 0:
            return "NA"
        return f"{wins}/{total} ({(wins/total)*100:.1f}%)"

    print("\nWinrate simulado:")
    print(f"- 1m: {_wr(sim_rows, 'result_1m')}")
    print(f"- 3m: {_wr(sim_rows, 'result_3m')}")
    print(f"- 5m: {_wr(sim_rows, 'result_5m')}")

    print(f"\nVelas exportadas en: {export_dir}")
    print(f"Reporte: {out_report}")


if __name__ == "__main__":
    main()
