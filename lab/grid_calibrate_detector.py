import argparse
import csv
import glob
import json
import re
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from estrategia_30s import detector


RE_REJECT = re.compile(r"score=\s*([\-\d\.]+)\s*<\s*umbral\s+din[\u00e1a]mico\s*([\-\d\.]+)", re.IGNORECASE)


@dataclass
class Sample:
    scanned_at: str
    asset: str
    gap: float
    candles: List[Dict[str, float]]
    label_1m: str
    label_3m: str
    label_5m: str


def _parse_iso_ts(value: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


def _latest_db() -> Optional[str]:
    dbs = sorted(glob.glob("data/db/trade_journal-*.db"), reverse=True)
    return dbs[0] if dbs else None


def _parse_gap(reject_reason: str, fallback_score: float) -> Optional[float]:
    if not reject_reason:
        return None
    m = RE_REJECT.search(reject_reason)
    if not m:
        return None
    try:
        score = float(m.group(1))
        threshold = float(m.group(2))
    except Exception:
        return None
    use_score = fallback_score if fallback_score is not None else score
    return threshold - use_score


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


def _collect_post(payload: Dict[str, Any]) -> List[Dict[str, float]]:
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


def _collect_pre(payload: Dict[str, Any]) -> List[Dict[str, float]]:
    analysis = payload.get("analysis_1m", {}) if isinstance(payload, dict) else {}
    pre = _normalize_rows(analysis.get("pre_40", []) if isinstance(analysis, dict) else [])
    return pre[-40:]


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _find_closest_vela_ops(asset: str, scanned_at: str, vela_dir: Path) -> Tuple[Optional[Dict[str, Any]], float]:
    target_dt = _parse_iso_ts(scanned_at)
    if target_dt is None:
        return None, 1e18

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
            best_payload = payload

    return best_payload, best_diff


def _label_from_post(post: List[Dict[str, float]], horizon_idx: int) -> str:
    if not post:
        return "NO_DATA"
    if len(post) <= horizon_idx:
        return "NO_DATA"
    entry = float(post[0]["open"])
    close_h = float(post[horizon_idx]["close"])
    if close_h > entry:
        return "CALL"
    if close_h < entry:
        return "PUT"
    return "DRAW"


def _load_samples(max_match_sec: float, top_n: int) -> List[Sample]:
    db = _latest_db()
    if not db:
        return []

    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        """
        SELECT scanned_at, asset, score, decision, reject_reason
        FROM candidates
        WHERE strategy_origin='STRAT-A' AND decision='REJECTED_SCORE'
        ORDER BY scanned_at ASC
        """
    ).fetchall()
    con.close()

    ranked: List[Tuple[float, sqlite3.Row]] = []
    for r in rows:
        score = float(r["score"] or 0.0)
        gap = _parse_gap(str(r["reject_reason"] or ""), score)
        if gap is None or gap < 0:
            continue
        ranked.append((gap, r))
    ranked.sort(key=lambda x: x[0])
    ranked = ranked[:max(1, top_n)]

    vela_dir = Path("data/vela_ops")
    samples: List[Sample] = []

    for gap, row in ranked:
        scanned_at = str(row["scanned_at"] or "")
        asset = str(row["asset"] or "")

        payload, diff = _find_closest_vela_ops(asset, scanned_at, vela_dir)
        if payload is None or diff > max_match_sec:
            continue

        pre = _collect_pre(payload)
        post = _collect_post(payload)
        if len(pre) < 20 or len(post) < 1:
            continue

        candles = pre + [post[0]]
        label_1m = _label_from_post(post, 0)
        label_3m = _label_from_post(post, 2)
        label_5m = _label_from_post(post, 4)

        samples.append(
            Sample(
                scanned_at=scanned_at,
                asset=asset,
                gap=float(gap),
                candles=candles,
                label_1m=label_1m,
                label_3m=label_3m,
                label_5m=label_5m,
            )
        )

    return samples


def _apply_params(params: Dict[str, Any]) -> None:
    for k, v in params.items():
        if hasattr(detector, k):
            setattr(detector, k, v)


def _evaluate_params(samples: List[Sample], params: Dict[str, Any]) -> Dict[str, Any]:
    _apply_params(params)

    total = len(samples)
    triggered = 0
    wins_1m = losses_1m = 0
    wins_3m = losses_3m = 0
    wins_5m = losses_5m = 0

    for s in samples:
        result = detector.evaluar_vela(s.candles, zonas=None, check_time=False)
        if result is None:
            continue
        pred_dir, score, _detail = result
        _ = score
        triggered += 1

        if s.label_1m in ("CALL", "PUT"):
            if pred_dir == s.label_1m:
                wins_1m += 1
            else:
                losses_1m += 1
        if s.label_3m in ("CALL", "PUT"):
            if pred_dir == s.label_3m:
                wins_3m += 1
            else:
                losses_3m += 1
        if s.label_5m in ("CALL", "PUT"):
            if pred_dir == s.label_5m:
                wins_5m += 1
            else:
                losses_5m += 1

    def _wr(w: int, l: int) -> float:
        t = w + l
        return (w / t * 100.0) if t > 0 else 0.0

    wr_1m = _wr(wins_1m, losses_1m)
    wr_3m = _wr(wins_3m, losses_3m)
    wr_5m = _wr(wins_5m, losses_5m)
    coverage = (triggered / total * 100.0) if total > 0 else 0.0

    # Objective: privilegiar 1m, con premio moderado por cobertura y estabilidad 3m
    objective = wr_1m * 0.70 + wr_3m * 0.20 + coverage * 0.10

    return {
        "total": total,
        "triggered": triggered,
        "coverage": coverage,
        "wins_1m": wins_1m,
        "losses_1m": losses_1m,
        "wr_1m": wr_1m,
        "wins_3m": wins_3m,
        "losses_3m": losses_3m,
        "wr_3m": wr_3m,
        "wins_5m": wins_5m,
        "losses_5m": losses_5m,
        "wr_5m": wr_5m,
        "objective": objective,
    }


def _write_csv(path: Path, rows: List[Dict[str, Any]], fieldnames: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _indicator_variants() -> List[Dict[str, Any]]:
    variants: List[Dict[str, Any]] = []
    for rsi_p in (7, 9, 14):
        for bb_p in (14, 20):
            for stoch_k in (5, 7):
                for ema_fast, ema_slow in ((8, 21), (5, 13)):
                    variants.append(
                        {
                            "RSI_PERIOD": rsi_p,
                            "BB_PERIOD": bb_p,
                            "STOCH_K_PERIOD": stoch_k,
                            "STOCH_D_PERIOD": 3,
                            "EMA_FAST_PERIOD": ema_fast,
                            "EMA_SLOW_PERIOD": ema_slow,
                            "ATR_PERIOD": 7,
                        }
                    )
    return variants


def _sr_variants() -> List[Dict[str, Any]]:
    variants: List[Dict[str, Any]] = []
    for lookback in (40, 50, 70):
        for pivot in (2, 3, 4):
            for merge in (0.3, 0.5, 0.8):
                for tol in (0.6, 0.8, 1.2, 2.0, 4.0):
                    variants.append(
                        {
                            "SR_LOOKBACK": lookback,
                            "SR_PIVOT_WINDOW": pivot,
                            "SR_MERGE_ATR_MULT": merge,
                            "ZONE_TOLERANCE_ATR_MULT": tol,
                        }
                    )
    return variants


def _fine_variants() -> List[Dict[str, Any]]:
    variants: List[Dict[str, Any]] = []
    for min_score in (3.0, 4.0, 5.0, 6.0):
        for wick_ratio in (0.8, 1.0, 1.2, 1.5):
            for atr_min in (0.0, 0.000001, 0.00004):
                for atr_max in (0.00040, 0.00100, 0.01000, 999.0):
                    variants.append(
                        {
                            "MIN_SCORE": min_score,
                            "MIN_WICK_TO_BODY_RATIO": wick_ratio,
                            "ATR_MIN": atr_min,
                            "ATR_MAX": atr_max,
                        }
                    )
    return variants


def _merge_params(*chunks: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for c in chunks:
        out.update(c)
    return out


def _search(samples: List[Sample], base: Dict[str, Any], variants: List[Dict[str, Any]], stage_name: str) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    results: List[Dict[str, Any]] = []
    best_params = dict(base)
    best_obj = -1.0
    min_triggered = max(8, int(len(samples) * 0.08))

    for idx, var in enumerate(variants, start=1):
        p = _merge_params(base, var)
        m = _evaluate_params(samples, p)
        row = {
            "stage": stage_name,
            "idx": idx,
            **var,
            **m,
        }
        results.append(row)

        # Cobertura mínima para que el set sea usable en operación real.
        if m["triggered"] < min_triggered:
            continue

        if m["objective"] > best_obj:
            best_obj = float(m["objective"])
            best_params = dict(p)

    # Si ninguna variante alcanza cobertura mínima, devolvemos el mejor objetivo bruto.
    if best_obj < 0 and results:
        top = max(results, key=lambda x: float(x["objective"]))
        best_params = _merge_params(base, {k: top[k] for k in variants[0].keys()})

    results.sort(key=lambda x: float(x["objective"]), reverse=True)
    return best_params, results


def main() -> None:
    parser = argparse.ArgumentParser(description="Grid calibration de detector 30s (indicadores + S/R)")
    parser.add_argument("--top", type=int, default=60, help="Cantidad de rechazados cercanos al umbral a usar")
    parser.add_argument("--max-match-sec", type=float, default=360.0, help="Delta maximo para matchear vela_ops")
    args = parser.parse_args()

    samples = _load_samples(max_match_sec=float(args.max_match_sec), top_n=max(10, int(args.top)))
    if not samples:
        print("Sin muestras utilizables para calibracion.")
        raise SystemExit(0)

    print(f"Muestras cargadas: {len(samples)}")

    defaults = {
        "ATR_PERIOD": detector.ATR_PERIOD,
        "RSI_PERIOD": detector.RSI_PERIOD,
        "BB_PERIOD": detector.BB_PERIOD,
        "BB_STD_DEV": detector.BB_STD_DEV,
        "STOCH_K_PERIOD": detector.STOCH_K_PERIOD,
        "STOCH_D_PERIOD": detector.STOCH_D_PERIOD,
        "EMA_FAST_PERIOD": detector.EMA_FAST_PERIOD,
        "EMA_SLOW_PERIOD": detector.EMA_SLOW_PERIOD,
        "SR_LOOKBACK": detector.SR_LOOKBACK,
        "SR_PIVOT_WINDOW": detector.SR_PIVOT_WINDOW,
        "SR_MERGE_ATR_MULT": detector.SR_MERGE_ATR_MULT,
        "ZONE_TOLERANCE_ATR_MULT": detector.ZONE_TOLERANCE_ATR_MULT,
        "MIN_SCORE": detector.MIN_SCORE,
        "MIN_WICK_TO_BODY_RATIO": detector.MIN_WICK_TO_BODY_RATIO,
        "ATR_MIN": detector.ATR_MIN,
        "ATR_MAX": detector.ATR_MAX,
    }

    # Secuencia 1: indicadores
    best_1, res_1 = _search(samples, defaults, _indicator_variants(), "indicator")
    print(f"Secuencia 1 (indicadores): {len(res_1)} variantes evaluadas")

    # Secuencia 2: soporte/resistencia
    best_2, res_2 = _search(samples, best_1, _sr_variants(), "support_resistance")
    print(f"Secuencia 2 (S/R): {len(res_2)} variantes evaluadas")

    # Secuencia 3: afinado
    best_3, res_3 = _search(samples, best_2, _fine_variants(), "fine_tuning")
    print(f"Secuencia 3 (fine): {len(res_3)} variantes evaluadas")

    final_metrics = _evaluate_params(samples, best_3)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path("aprendizaje/reportes")

    _write_csv(
        out_dir / f"calibracion_detector_seq1_{ts}.csv",
        res_1,
        fieldnames=list(res_1[0].keys()) if res_1 else ["stage"],
    )
    _write_csv(
        out_dir / f"calibracion_detector_seq2_{ts}.csv",
        res_2,
        fieldnames=list(res_2[0].keys()) if res_2 else ["stage"],
    )
    _write_csv(
        out_dir / f"calibracion_detector_seq3_{ts}.csv",
        res_3,
        fieldnames=list(res_3[0].keys()) if res_3 else ["stage"],
    )

    best_json = out_dir / f"calibracion_detector_best_{ts}.json"
    best_json.write_text(
        json.dumps(
            {
                "timestamp": ts,
                "samples": len(samples),
                "best_params": best_3,
                "best_metrics": final_metrics,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print("\n=== BEST PARAMS ===")
    for k in sorted(best_3.keys()):
        print(f"{k}={best_3[k]}")

    print("\n=== BEST METRICS ===")
    print(
        f"triggered={final_metrics['triggered']}/{final_metrics['total']} "
        f"coverage={final_metrics['coverage']:.1f}% "
        f"wr1m={final_metrics['wr_1m']:.1f}% "
        f"wr3m={final_metrics['wr_3m']:.1f}% "
        f"wr5m={final_metrics['wr_5m']:.1f}% "
        f"objective={final_metrics['objective']:.2f}"
    )

    print("\nReportes:")
    print(f"- {out_dir / f'calibracion_detector_seq1_{ts}.csv'}")
    print(f"- {out_dir / f'calibracion_detector_seq2_{ts}.csv'}")
    print(f"- {out_dir / f'calibracion_detector_seq3_{ts}.csv'}")
    print(f"- {best_json}")


if __name__ == "__main__":
    main()
