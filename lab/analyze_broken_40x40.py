from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from statistics import mean, median
from typing import Any, Dict, List, Tuple


@dataclass
class EventResult:
    file_name: str
    asset: str
    reason: str
    pre_count: int
    post_count: int
    sane_post_count: int
    contaminated_event: bool
    pre_clean: bool
    retest_count: int
    continuation_ratio: float
    move_in_zone_heights: float
    valid_40x40: bool


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _normalize_candle_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, float]]:
    out: List[Dict[str, float]] = []
    for r in rows:
        out.append(
            {
                "ts": _to_int(r.get("ts")),
                "open": _to_float(r.get("open")),
                "high": _to_float(r.get("high")),
                "low": _to_float(r.get("low")),
                "close": _to_float(r.get("close")),
            }
        )
    out.sort(key=lambda x: x["ts"])
    return out


def _dedupe_by_ts(rows: List[Dict[str, float]]) -> List[Dict[str, float]]:
    seen: set[int] = set()
    out: List[Dict[str, float]] = []
    for r in sorted(rows, key=lambda x: x["ts"]):
        ts = int(r["ts"])
        if ts in seen:
            continue
        seen.add(ts)
        out.append(r)
    return out


def _build_pre_post_40(payload: Dict[str, Any]) -> Tuple[List[Dict[str, float]], List[Dict[str, float]]]:
    trigger = payload.get("trigger_candle_5m", {})
    trigger_ts = _to_int(trigger.get("ts"))

    analysis = payload.get("analysis_1m", {})
    pre_a = _normalize_candle_rows(analysis.get("pre_40", []))
    post_a = _normalize_candle_rows(analysis.get("post_40_initial", []))

    if pre_a:
        pre = pre_a[-40:]
    else:
        used = _normalize_candle_rows(payload.get("candles_1m_used", []))
        pre = [c for c in used if c["ts"] < trigger_ts][-40:]

    if post_a:
        post_seed = post_a[:40]
    else:
        used = _normalize_candle_rows(payload.get("candles_1m_used", []))
        post_seed = [c for c in used if c["ts"] > trigger_ts][:40]

    followup = payload.get("followup", {})
    followup_rows = _normalize_candle_rows(followup.get("candles_1m", []))

    post = _dedupe_by_ts(post_seed + followup_rows)
    post = post[:40]
    return pre, post


def _evaluate_event(payload: Dict[str, Any], file_name: str, pre_break_tol: float = 0.003) -> EventResult:
    zone = payload.get("zone", {})
    reason = str(payload.get("reason", ""))
    asset = str(payload.get("asset", ""))

    zone_ceiling = _to_float(zone.get("ceiling"))
    zone_floor = _to_float(zone.get("floor"))
    zone_height = max(1e-9, zone_ceiling - zone_floor)

    trigger = payload.get("trigger_candle_5m", {})
    trigger_close = _to_float(trigger.get("close"))

    pre40, post40 = _build_pre_post_40(payload)

    # Misma sanidad usada en el bot para evitar mezclar eventos claramente corruptos.
    contaminated_event = False
    if zone_ceiling > 0 and zone_floor > 0:
        contaminated_event = not (zone_floor * 0.75 <= trigger_close <= zone_ceiling * 1.25)

    pre_clean = False
    retest_count = 0
    continuation_ratio = 0.0
    move_in_zone_heights = 0.0
    sane_post_count = 0

    post40_sane = [
        c
        for c in post40
        if zone_floor > 0 and zone_ceiling > 0 and (zone_floor * 0.75 <= c["close"] <= zone_ceiling * 1.25)
    ]
    sane_post_count = len(post40_sane)
    post_eval = post40_sane if post40_sane else post40

    if not contaminated_event and reason == "BROKEN_ABOVE" and pre40 and post_eval:
        max_pre_high = max(c["high"] for c in pre40)
        pre_clean = max_pre_high <= zone_ceiling * (1.0 + pre_break_tol)
        retest_count = sum(1 for c in post_eval if c["low"] <= zone_ceiling)
        cont = sum(1 for c in post_eval if c["close"] > zone_ceiling)
        continuation_ratio = cont / len(post_eval)
        move_in_zone_heights = (post_eval[-1]["close"] - trigger_close) / zone_height

    elif not contaminated_event and reason == "BROKEN_BELOW" and pre40 and post_eval:
        min_pre_low = min(c["low"] for c in pre40)
        pre_clean = min_pre_low >= zone_floor * (1.0 - pre_break_tol)
        retest_count = sum(1 for c in post_eval if c["high"] >= zone_floor)
        cont = sum(1 for c in post_eval if c["close"] < zone_floor)
        continuation_ratio = cont / len(post_eval)
        move_in_zone_heights = (trigger_close - post_eval[-1]["close"]) / zone_height

    valid_40x40 = (
        len(pre40) >= 40
        and len(post40) >= 40
        and sane_post_count >= 24
        and not contaminated_event
        and pre_clean
        and retest_count >= 1
        and continuation_ratio >= 0.55
        and move_in_zone_heights >= 0.80
    )

    return EventResult(
        file_name=file_name,
        asset=asset,
        reason=reason,
        pre_count=len(pre40),
        post_count=len(post40),
        sane_post_count=sane_post_count,
        contaminated_event=contaminated_event,
        pre_clean=pre_clean,
        retest_count=retest_count,
        continuation_ratio=continuation_ratio,
        move_in_zone_heights=move_in_zone_heights,
        valid_40x40=valid_40x40,
    )


def analyze_folder(folder: Path) -> List[EventResult]:
    results: List[EventResult] = []
    for path in sorted(folder.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            results.append(_evaluate_event(payload, path.name))
        except Exception:
            continue
    return results


def _print_summary(results: List[EventResult]) -> None:
    if not results:
        print("No se encontraron eventos para analizar.")
        return

    total = len(results)
    enough_pre = sum(1 for r in results if r.pre_count >= 40)
    enough_post = sum(1 for r in results if r.post_count >= 40)
    enough_sane_post = sum(1 for r in results if r.sane_post_count >= 24)
    contaminated = sum(1 for r in results if r.contaminated_event)
    valid = [r for r in results if r.valid_40x40]

    print("=== Analisis 40/40 (BROKEN_ZONE) ===")
    print(f"Total eventos          : {total}")
    print(f"Con pre40 completos    : {enough_pre}")
    print(f"Con post40 completos   : {enough_post}")
    print(f"Con post util (>=24)   : {enough_sane_post}")
    print(f"Eventos contaminados   : {contaminated}")
    print(f"Patron valido 40x40    : {len(valid)}")

    if valid:
        print("\nEventos validos:")
        for r in valid:
            print(
                f"- {r.file_name} | {r.asset} {r.reason} "
                f"cont={r.continuation_ratio:.2f} move={r.move_in_zone_heights:.2f}z"
            )

    by_asset: Dict[str, List[EventResult]] = {}
    for r in results:
        by_asset.setdefault(r.asset, []).append(r)

    ranked = []
    for asset, rows in by_asset.items():
        hit = sum(1 for x in rows if x.valid_40x40)
        cov = sum(
            1
            for x in rows
            if x.pre_count >= 40 and x.post_count >= 40 and x.sane_post_count >= 24 and not x.contaminated_event
        )
        if cov < 2:
            continue
        ranked.append((asset, hit / cov, cov, hit))

    ranked.sort(key=lambda x: (x[1], x[3]), reverse=True)
    if ranked:
        print("\nActivos con mejor tasa valida (min 2 eventos):")
        for asset, ratio, cov, hit in ranked[:10]:
            print(f"- {asset}: {hit}/{cov} = {ratio:.2%}")

    cov_rows = [
        r
        for r in results
        if r.pre_count >= 40 and r.post_count >= 40 and r.sane_post_count >= 24 and not r.contaminated_event
    ]
    if cov_rows:
        clipped_moves = [max(-10.0, min(10.0, r.move_in_zone_heights)) for r in cov_rows]
        print("\nPromedios en eventos con cobertura 40/40:")
        print(f"- continuation_ratio: {mean(r.continuation_ratio for r in cov_rows):.3f}")
        print(f"- move_in_zone_heights(raw): {mean(r.move_in_zone_heights for r in cov_rows):.3f}")
        print(f"- move_in_zone_heights(clip±10): {mean(clipped_moves):.3f}")
        print(f"- move_median(clip±10): {median(clipped_moves):.3f}")
    else:
        print("\nPromedios en eventos con cobertura 40/40:")
        print("- Sin muestra util (falta cobertura o eventos contaminados).")


def main() -> None:
    parser = argparse.ArgumentParser(description="Analiza snapshots BROKEN_ZONE con ventana 40 velas antes/despues.")
    parser.add_argument(
        "--dir",
        default="data/vela_ops",
        help="Carpeta con snapshots JSON BROKEN_ZONE",
    )
    args = parser.parse_args()

    folder = Path(args.dir)
    if not folder.exists():
        print(f"No existe carpeta: {folder}")
        return

    results = analyze_folder(folder)
    _print_summary(results)


if __name__ == "__main__":
    main()
