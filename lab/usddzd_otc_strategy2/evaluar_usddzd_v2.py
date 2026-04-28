from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import List, Optional


@dataclass
class Candle:
    ts: int
    open: float
    high: float
    low: float
    close: float

    @property
    def body(self) -> float:
        return abs(self.close - self.open)


@dataclass
class S2Result:
    state: str
    support_floor: float
    support_ceiling: float
    touches_5m: int
    sweep_detected: bool
    impulse_ratio_1m: float
    score: float
    reason: str


def load_candles_from_json(path: Path) -> List[Candle]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    out: List[Candle] = []
    for r in rows:
        out.append(
            Candle(
                ts=int(r["ts"]),
                open=float(r["open"]),
                high=float(r["high"]),
                low=float(r["low"]),
                close=float(r["close"]),
            )
        )
    out.sort(key=lambda x: x.ts)
    return out


def percentile(values: List[float], q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    idx = min(len(s) - 1, max(0, int(q * (len(s) - 1))))
    return s[idx]


def compute_atr(candles: List[Candle], period: int = 14) -> float:
    if len(candles) < period + 1:
        return 0.0
    tr: List[float] = []
    for i in range(1, len(candles)):
        c = candles[i]
        p = candles[i - 1]
        tr_i = max(c.high - c.low, abs(c.high - p.close), abs(c.low - p.close))
        tr.append(tr_i)
    tail = tr[-period:]
    return mean(tail) if tail else 0.0


def detect_support_zone(candles_5m: List[Candle]) -> tuple[float, float, int]:
    lows = [c.low for c in candles_5m]
    s_floor = percentile(lows, 0.20)

    mid = candles_5m[-1].close if candles_5m else 0.0
    atr = compute_atr(candles_5m, 14)
    width = max(mid * 0.0008, atr * 0.35)
    s_ceiling = s_floor + width

    touches = 0
    last_touch_idx = -99
    for i, c in enumerate(candles_5m):
        touched = c.low <= s_ceiling and c.low >= (s_floor - width * 0.3)
        if touched and i - last_touch_idx >= 2:
            touches += 1
            last_touch_idx = i

    return s_floor, s_ceiling, touches


def detect_sweep_impulse(candles_1m: List[Candle], s_floor: float, s_ceiling: float) -> tuple[bool, float]:
    if len(candles_1m) < 12:
        return False, 0.0

    tol = max((s_ceiling - s_floor) * 0.35, s_floor * 0.00025)

    recent = candles_1m[-12:]
    bodies = [c.body for c in recent[:-2]]
    body_avg = mean(bodies) if bodies else 0.0

    for i in range(len(recent) - 1):
        sweep = recent[i]
        impulse = recent[i + 1]

        sweep_hit = sweep.low <= (s_floor + tol)
        reclaim = sweep.close >= s_floor
        if not (sweep_hit and reclaim):
            continue

        ratio = (impulse.body / body_avg) if body_avg > 0 else 0.0
        if ratio >= 1.4 and impulse.close > sweep.high:
            return True, ratio

    return False, 0.0


def score_s2(touches: int, sweep_ok: bool, impulse_ratio: float, min_payout: int = 80, payout: int = 80) -> float:
    structure = min(40.0, touches * 8.0)
    event = 0.0
    if sweep_ok:
        event = min(40.0, 20.0 + (impulse_ratio * 12.0))
    risk = 20.0 if payout >= min_payout else 8.0
    return round(structure + event + risk, 1)


def evaluate(candles_5m: List[Candle], candles_1m: List[Candle]) -> S2Result:
    if len(candles_5m) < 50:
        return S2Result("INVALIDATED", 0.0, 0.0, 0, False, 0.0, 0.0, "faltan velas 5m")

    block = candles_5m[-50:]
    s_floor, s_ceiling, touches = detect_support_zone(block)

    if touches < 3:
        return S2Result("WATCH", s_floor, s_ceiling, touches, False, 0.0, 0.0, "soporte debil (<3 toques)")

    sweep_ok, impulse_ratio = detect_sweep_impulse(candles_1m, s_floor, s_ceiling)
    score = score_s2(touches, sweep_ok, impulse_ratio)

    if sweep_ok and score >= 68.0:
        return S2Result("TRIGGERED", s_floor, s_ceiling, touches, True, impulse_ratio, score, "entrada CALL valida")
    if sweep_ok:
        return S2Result("ARMED", s_floor, s_ceiling, touches, True, impulse_ratio, score, "evento detectado pero score bajo")
    return S2Result("WATCH", s_floor, s_ceiling, touches, False, 0.0, score, "esperando barrido + impulso 1m")


def main() -> None:
    base = Path(__file__).resolve().parent
    f5 = base / "sample_usddzd_5m.json"
    f1 = base / "sample_usddzd_1m.json"

    if not f5.exists() or not f1.exists():
        print("Faltan archivos de muestra:")
        print(f"- {f5.name}")
        print(f"- {f1.name}")
        print("Formato esperado: lista JSON con objetos {ts, open, high, low, close}")
        return

    c5 = load_candles_from_json(f5)
    c1 = load_candles_from_json(f1)
    res = evaluate(c5, c1)

    print("=== EVALUACION S2 USDDZD_otc ===")
    print(f"state          : {res.state}")
    print(f"support_floor  : {res.support_floor:.5f}")
    print(f"support_ceiling: {res.support_ceiling:.5f}")
    print(f"touches_5m     : {res.touches_5m}")
    print(f"sweep_detected : {res.sweep_detected}")
    print(f"impulse_ratio  : {res.impulse_ratio_1m:.2f}")
    print(f"score          : {res.score:.1f}")
    print(f"reason         : {res.reason}")


if __name__ == "__main__":
    main()
