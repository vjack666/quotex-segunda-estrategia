from __future__ import annotations

import asyncio
import csv
import json
import math
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
import sys
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import consolidation_bot as cb
from estrategia_30s import detector as strat_c_detector
from pyquotex.stable_api import Quotex
from strategy_spring_sweep import detect_spring_or_upthrust


WEEK_MINUTES = 7 * 24 * 60
WEEK_5M = 7 * 24 * 12
WEEK_H1 = 7 * 24

PAIR_GROUPS: Dict[str, List[Tuple[str, str]]] = {
    "STRAT-A": [
        ("ATOUSD_OTC", "put"),
        ("DOTUSD_OTC", "put"),
        ("INTC_OTC", "put"),
    ],
    "STRAT-B": [
        ("ATOUSD_OTC", "call"),
        ("AUDCHF_OTC", "call"),
        ("CHFJPY_OTC", "call"),
        ("AUDUSD_OTC", "put"),
        ("USDMXN_OTC", "put"),
    ],
    "STRAT-C": [
        ("EURGBP_OTC", "put"),
        ("ZECUSD_OTC", "call"),
        ("EURAUD_OTC", "call"),
        ("JNJ_OTC", "put"),
        ("LINUSD_OTC", "call"),
    ],
}


@dataclass
class SignalRecord:
    strategy: str
    asset: str
    direction: str
    ts: int
    entry_price: float
    exit_price_5m: Optional[float]
    win_5m: Optional[bool]
    confidence: float
    meta: Dict[str, Any]


@dataclass
class PairSummary:
    strategy: str
    asset: str
    direction: str
    signals: int
    resolved: int
    wins: int
    losses: int
    winrate: float
    avg_conf: float
    best_edge_bps: float
    latest_signal_ts: Optional[int]
    latest_signal_win: Optional[bool]
    latest_reason: str


def _norm_asset(asset: str) -> str:
    a = asset.strip()
    if a.endswith("_OTC"):
        return a[:-4] + "_otc"
    if a.endswith("_otc"):
        return a
    return a


def _asset_candidates(asset: str) -> List[str]:
    base = asset.strip()
    variants = [base, _norm_asset(base)]
    if base.endswith("_otc"):
        variants.append(base[:-4] + "_OTC")
    if base.endswith("_OTC"):
        variants.append(base[:-4] + "_otc")
    out: List[str] = []
    for s in variants:
        if s not in out:
            out.append(s)
    return out


def _to_df(candles: Sequence[cb.Candle]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": [c.open for c in candles],
            "high": [c.high for c in candles],
            "low": [c.low for c in candles],
            "close": [c.close for c in candles],
        }
    )


def _candles_to_dicts(candles: Sequence[cb.Candle]) -> List[Dict[str, float]]:
    return [
        {"open": c.open, "high": c.high, "low": c.low, "close": c.close}
        for c in candles
    ]


def _idx_at_or_after(candles: Sequence[cb.Candle], ts: int) -> Optional[int]:
    for i, c in enumerate(candles):
        if int(c.ts) >= int(ts):
            return i
    return None


def _eval_1m_horizon(
    candles_1m: Sequence[cb.Candle],
    ts: int,
    entry_price: float,
    direction: str,
    minutes: int = 5,
) -> Tuple[Optional[float], Optional[bool]]:
    idx = _idx_at_or_after(candles_1m, ts)
    if idx is None:
        return None, None
    out_idx = idx + minutes
    if out_idx >= len(candles_1m):
        return None, None
    exit_price = float(candles_1m[out_idx].close)
    if direction == "call":
        return exit_price, bool(exit_price > entry_price)
    return exit_price, bool(exit_price < entry_price)


def _best_structural_edge_bps(
    candles_1m: Sequence[cb.Candle],
    ts: int,
    entry_price: float,
    direction: str,
    lookahead_min: int = 2,
) -> float:
    idx = _idx_at_or_after(candles_1m, ts)
    if idx is None:
        return 0.0
    j = min(len(candles_1m), idx + lookahead_min + 1)
    seg = candles_1m[idx:j]
    if not seg:
        return 0.0
    if direction == "call":
        best = min(c.low for c in seg)
        if entry_price <= 0:
            return 0.0
        return (entry_price - best) / entry_price * 10000.0
    best = max(c.high for c in seg)
    if entry_price <= 0:
        return 0.0
    return (best - entry_price) / entry_price * 10000.0


async def _fetch_chunked(
    client: Quotex,
    asset: str,
    tf_sec: int,
    target_count: int,
    chunk_count: int,
) -> List[cb.Candle]:
    end_time = time.time()
    seen: Dict[int, cb.Candle] = {}
    safety_loops = 0
    while len(seen) < target_count and safety_loops < 120:
        safety_loops += 1
        offset = int(chunk_count * tf_sec)
        try:
            raw = await client.get_candles(asset, end_time, offset, tf_sec)
        except Exception:
            raw = []
        if not raw:
            break
        parsed = [cb.raw_to_candle(r) for r in raw if isinstance(r, dict)]
        valid = [c for c in parsed if c is not None and c.high > 0]
        if not valid:
            break
        valid.sort(key=lambda c: c.ts)
        before = len(seen)
        for c in valid:
            seen[int(c.ts)] = c
        oldest_ts = int(valid[0].ts)
        end_time = float(oldest_ts - 1)
        if len(seen) == before:
            break
        await asyncio.sleep(0.03)

    out = sorted(seen.values(), key=lambda c: c.ts)
    if len(out) > target_count:
        out = out[-target_count:]
    return out


async def _fetch_week_multiframe(client: Quotex, asset: str) -> Dict[str, List[cb.Candle]]:
    return {
        "1m": await _fetch_chunked(client, asset, 60, WEEK_MINUTES, 700),
        "5m": await _fetch_chunked(client, asset, 300, WEEK_5M, 700),
        "1h": await _fetch_chunked(client, asset, 3600, WEEK_H1, 180),
    }


def _analyze_strat_a(
    asset: str,
    direction: str,
    candles_5m: Sequence[cb.Candle],
    candles_1m: Sequence[cb.Candle],
) -> List[SignalRecord]:
    out: List[SignalRecord] = []
    needed = max(25, cb.MIN_CONSOLIDATION_BARS + 2)
    for i in range(needed, len(candles_5m) - 1):
        hist = list(candles_5m[:i])
        zone = cb.detect_consolidation(hist)
        if zone is None:
            continue
        last = hist[-1]
        entry_price = float(last.close)
        touched = cb.price_at_floor(entry_price, zone.floor) if direction == "call" else cb.price_at_ceiling(entry_price, zone.ceiling)
        if not touched:
            continue
        exit_price = float(candles_5m[i].close)
        win = bool(exit_price > entry_price) if direction == "call" else bool(exit_price < entry_price)
        out.append(
            SignalRecord(
                strategy="STRAT-A",
                asset=asset,
                direction=direction,
                ts=int(last.ts),
                entry_price=entry_price,
                exit_price_5m=exit_price,
                win_5m=win,
                confidence=0.0,
                meta={
                    "zone_floor": zone.floor,
                    "zone_ceiling": zone.ceiling,
                    "range_pct": zone.range_pct,
                    "bars_inside": zone.bars_inside,
                    "edge_bps": _best_structural_edge_bps(candles_1m, int(last.ts), entry_price, direction),
                },
            )
        )
    return out


def _analyze_strat_b(
    asset: str,
    direction: str,
    candles_1m: Sequence[cb.Candle],
) -> List[SignalRecord]:
    out: List[SignalRecord] = []
    for i in range(25, len(candles_1m)):
        window = list(candles_1m[max(0, i - 80):i])
        if len(window) < 20:
            continue
        df = _to_df(window)
        is_signal, info = detect_spring_or_upthrust(df, allow_early=cb.STRAT_B_ALLOW_WYCKOFF_EARLY)
        sig_dir = str(info.get("direction") or "").lower()
        conf = float(info.get("confidence") or 0.0)
        if sig_dir != direction:
            continue
        if not is_signal:
            continue
        ts = int(window[-1].ts)
        entry = float(window[-1].close)
        exit_price, win = _eval_1m_horizon(candles_1m, ts, entry, direction, minutes=5)
        out.append(
            SignalRecord(
                strategy="STRAT-B",
                asset=asset,
                direction=direction,
                ts=ts,
                entry_price=entry,
                exit_price_5m=exit_price,
                win_5m=win,
                confidence=conf,
                meta={
                    "signal_type": str(info.get("signal_type") or ""),
                    "reason": str(info.get("reason") or ""),
                    "edge_bps": _best_structural_edge_bps(candles_1m, ts, entry, direction),
                },
            )
        )
    return out


def _analyze_strat_c(
    asset: str,
    direction: str,
    candles_1m: Sequence[cb.Candle],
) -> List[SignalRecord]:
    out: List[SignalRecord] = []
    for i in range(25, len(candles_1m)):
        window = list(candles_1m[max(0, i - 120):i])
        if len(window) < 25:
            continue
        raw = _candles_to_dicts(window)
        res = strat_c_detector.evaluar_vela(raw, zonas=None, check_time=False)
        if res is None:
            continue
        sig_dir, score, detail = res
        sig_dir = str(sig_dir).lower()
        if sig_dir != direction:
            continue
        ts = int(window[-1].ts)
        entry = float(window[-1].close)
        exit_price, win = _eval_1m_horizon(candles_1m, ts, entry, direction, minutes=5)
        out.append(
            SignalRecord(
                strategy="STRAT-C",
                asset=asset,
                direction=direction,
                ts=ts,
                entry_price=entry,
                exit_price_5m=exit_price,
                win_5m=win,
                confidence=float(score) / 17.0,
                meta={
                    "score_raw": float(score),
                    "wick_ratio": float(detail.get("wick_ratio", 0.0)),
                    "rsi": float(detail.get("rsi", 0.0)),
                    "atr": float(detail.get("atr", 0.0)),
                    "edge_bps": _best_structural_edge_bps(candles_1m, ts, entry, direction),
                },
            )
        )
    return out


def _summary(strategy: str, asset: str, direction: str, rows: Sequence[SignalRecord]) -> PairSummary:
    resolved = [r for r in rows if r.win_5m is not None]
    wins = sum(1 for r in resolved if r.win_5m is True)
    losses = sum(1 for r in resolved if r.win_5m is False)
    winrate = (wins / len(resolved) * 100.0) if resolved else 0.0
    avg_conf = mean([r.confidence for r in rows]) if rows else 0.0
    best_edge = max([float(r.meta.get("edge_bps", 0.0)) for r in rows], default=0.0)
    latest = rows[-1] if rows else None
    if latest is None:
        latest_reason = "Sin señal en la semana"
    else:
        latest_reason = str(latest.meta.get("reason") or latest.meta.get("signal_type") or "Señal detectada")
    return PairSummary(
        strategy=strategy,
        asset=asset,
        direction=direction,
        signals=len(rows),
        resolved=len(resolved),
        wins=wins,
        losses=losses,
        winrate=winrate,
        avg_conf=avg_conf,
        best_edge_bps=best_edge,
        latest_signal_ts=latest.ts if latest else None,
        latest_signal_win=latest.win_5m if latest else None,
        latest_reason=latest_reason,
    )


def _write_candles_csv(path: Path, candles: Sequence[cb.Candle]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ts", "datetime_utc", "open", "high", "low", "close"])
        for c in candles:
            dt = datetime.fromtimestamp(int(c.ts), tz=timezone.utc).isoformat()
            w.writerow([int(c.ts), dt, c.open, c.high, c.low, c.close])


def _write_signals_csv(path: Path, rows: Sequence[SignalRecord]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "strategy", "asset", "direction", "ts", "datetime_utc", "entry_price",
            "exit_price_5m", "win_5m", "confidence", "meta_json",
        ])
        for r in rows:
            dt = datetime.fromtimestamp(int(r.ts), tz=timezone.utc).isoformat()
            w.writerow([
                r.strategy,
                r.asset,
                r.direction,
                r.ts,
                dt,
                f"{r.entry_price:.8f}",
                "" if r.exit_price_5m is None else f"{r.exit_price_5m:.8f}",
                "" if r.win_5m is None else int(bool(r.win_5m)),
                f"{r.confidence:.6f}",
                json.dumps(r.meta, ensure_ascii=False),
            ])


def _fmt_ts(ts: Optional[int]) -> str:
    if ts is None:
        return "-"
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


async def main() -> None:
    if not cb.EMAIL or not cb.PASSWORD:
        raise RuntimeError("Faltan QUOTEX_EMAIL/QUOTEX_PASSWORD en .env")

    out_root = ROOT / "data" / "exports" / f"snapshot_pairs_week_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    out_root.mkdir(parents=True, exist_ok=True)
    (out_root / "candles").mkdir(parents=True, exist_ok=True)

    client = Quotex(email=cb.EMAIL, password=cb.PASSWORD)
    ok, reason = await cb.connect_with_retry(client)
    if not ok:
        raise RuntimeError(f"No conecta a Quotex: {reason}")

    summaries: List[PairSummary] = []
    all_signals: List[SignalRecord] = []

    try:
        for strategy, entries in PAIR_GROUPS.items():
            for raw_asset, direction in entries:
                direction = direction.lower().strip()
                candles_by_tf: Dict[str, List[cb.Candle]] = {}
                asset_used = None

                for sym in _asset_candidates(raw_asset):
                    try:
                        got = await _fetch_week_multiframe(client, sym)
                    except Exception:
                        got = {}
                    if got and got.get("1m") and got.get("5m") and got.get("1h"):
                        candles_by_tf = got
                        asset_used = sym
                        break

                if not candles_by_tf:
                    summaries.append(
                        PairSummary(
                            strategy=strategy,
                            asset=raw_asset,
                            direction=direction,
                            signals=0,
                            resolved=0,
                            wins=0,
                            losses=0,
                            winrate=0.0,
                            avg_conf=0.0,
                            best_edge_bps=0.0,
                            latest_signal_ts=None,
                            latest_signal_win=None,
                            latest_reason="No se pudieron descargar velas",
                        )
                    )
                    continue

                base_name = raw_asset.replace("/", "_")
                _write_candles_csv(out_root / "candles" / f"{base_name}_1m.csv", candles_by_tf["1m"])
                _write_candles_csv(out_root / "candles" / f"{base_name}_5m.csv", candles_by_tf["5m"])
                _write_candles_csv(out_root / "candles" / f"{base_name}_1h.csv", candles_by_tf["1h"])

                if strategy == "STRAT-A":
                    rows = _analyze_strat_a(raw_asset, direction, candles_by_tf["5m"], candles_by_tf["1m"])
                elif strategy == "STRAT-B":
                    rows = _analyze_strat_b(raw_asset, direction, candles_by_tf["1m"])
                else:
                    rows = _analyze_strat_c(raw_asset, direction, candles_by_tf["1m"])

                for r in rows:
                    r.asset = raw_asset

                all_signals.extend(rows)
                summaries.append(_summary(strategy, raw_asset, direction, rows))

    finally:
        try:
            await client.close()
        except Exception:
            pass

    _write_signals_csv(out_root / "signals_week.csv", all_signals)

    summary_rows = []
    for s in summaries:
        summary_rows.append(
            {
                "strategy": s.strategy,
                "asset": s.asset,
                "direction": s.direction,
                "signals": s.signals,
                "resolved": s.resolved,
                "wins": s.wins,
                "losses": s.losses,
                "winrate_pct": round(s.winrate, 2),
                "avg_conf": round(s.avg_conf, 4),
                "best_edge_bps": round(s.best_edge_bps, 2),
                "latest_signal_utc": _fmt_ts(s.latest_signal_ts),
                "latest_signal_win": s.latest_signal_win,
                "latest_reason": s.latest_reason,
            }
        )

    with (out_root / "summary_week.json").open("w", encoding="utf-8") as f:
        json.dump(summary_rows, f, ensure_ascii=False, indent=2)

    lines: List[str] = []
    lines.append("# Analisis semanal por estrategia")
    lines.append("")
    lines.append(f"Directorio: {out_root}")
    lines.append("")
    lines.append("## Resumen")
    lines.append("")

    by_strat: Dict[str, List[PairSummary]] = {"STRAT-A": [], "STRAT-B": [], "STRAT-C": []}
    for s in summaries:
        by_strat.setdefault(s.strategy, []).append(s)

    for strat in ("STRAT-A", "STRAT-B", "STRAT-C"):
        lines.append(f"### {strat}")
        for s in by_strat.get(strat, []):
            lines.append(
                f"- {s.asset} {s.direction.upper()} | señales={s.signals} resueltas={s.resolved} "
                f"W/L={s.wins}/{s.losses} winrate={s.winrate:.1f}% conf_prom={s.avg_conf:.3f} "
                f"best_edge={s.best_edge_bps:.1f} bps | ult={_fmt_ts(s.latest_signal_ts)} "
                f"resultado_ult={s.latest_signal_win} | {s.latest_reason}"
            )
        lines.append("")

    lines.append("## Criterio de entrada usado")
    lines.append("")
    lines.append("- STRAT-A: toque de estructura en 5m (techo para PUT, piso para CALL) usando detect_consolidation del bot.")
    lines.append("- STRAT-B: señal valida de detect_spring_or_upthrust en ventana rodante de 1m.")
    lines.append("- STRAT-C: evaluar_vela(check_time=False) en ventana rodante de 1m.")
    lines.append("- Resultado +5m: cierre 5 velas de 1m después de la señal (o 1 vela de 5m para STRAT-A).")
    lines.append("- best_edge_bps: mejora teórica máxima de precio en los 2 minutos posteriores a la señal.")

    (out_root / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")

    print(f"ANALISIS_OK {out_root}")


if __name__ == "__main__":
    asyncio.run(main())
