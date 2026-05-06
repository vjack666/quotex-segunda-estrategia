#!/usr/bin/env python3
"""Analisis profundo de STRAT-C contra la tesis y la data real del sistema."""
import glob
import json
import sqlite3
from collections import Counter, defaultdict


THESIS_MIN_RAW_SCORE = 6.0
THESIS_ATR_MIN = 0.00005
THESIS_ATR_MAX = 0.00030
RUNTIME_MIN_RAW_SCORE = 4.0
RUNTIME_ATR_MAX = 999.0


def load_db() -> sqlite3.Connection:
    db_files = glob.glob("data/db/black_box_strat_*.db")
    if not db_files:
        raise SystemExit("❌ BD no encontrada")
    return sqlite3.connect(db_files[-1])


def parse_candidate(row: tuple) -> dict:
    details = json.loads(row[8] or "{}") if row[8] else {}
    detail = details.get("detalle", {}) if isinstance(details, dict) else {}
    return {
        "id": row[0],
        "asset": row[1],
        "direction": str(row[2] or "").lower(),
        "score_norm": float(row[3] or 0.0),
        "confidence": float(row[4] or 0.0),
        "payout": int(row[5] or 0),
        "decision": row[6] or "",
        "order_id": row[7] or "",
        "result": row[9] or "",
        "profit": float(row[10] or 0.0),
        "created_at": row[11] or "",
        "source": details.get("source", ""),
        "broker_second": details.get("broker_second"),
        "raw_score": float(details.get("raw_score", 0.0) or 0.0),
        "wick_ratio": float(detail.get("wick_ratio", 0.0) or 0.0),
        "atr": float(detail.get("atr", 0.0) or 0.0),
        "rsi": float(detail.get("rsi", 0.0) or 0.0),
        "wick_quality": detail.get("wick_quality", ""),
        "bb_signal": detail.get("bb_signal", ""),
        "ema_trend": detail.get("ema_trend", ""),
        "stoch_k": detail.get("stoch_k"),
        "stoch_d": detail.get("stoch_d"),
        "entry_window": details.get("entry_window"),
    }


def pct(part: int, total: int) -> float:
    return (part / total * 100.0) if total else 0.0


def avg(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def summarize_results(rows: list[dict]) -> dict:
    resolved = [r for r in rows if r["result"] in ("WIN", "LOSS")]
    wins = [r for r in resolved if r["result"] == "WIN"]
    losses = [r for r in resolved if r["result"] == "LOSS"]
    return {
        "total": len(rows),
        "resolved": len(resolved),
        "wins": len(wins),
        "losses": len(losses),
        "pending": len(rows) - len(resolved),
        "winrate": pct(len(wins), len(resolved)),
        "pnl": sum(r["profit"] for r in resolved),
        "avg_win": avg([r["profit"] for r in wins]),
        "avg_loss": avg([abs(r["profit"]) for r in losses]),
        "avg_raw_score_win": avg([r["raw_score"] for r in wins]),
        "avg_raw_score_loss": avg([r["raw_score"] for r in losses]),
        "avg_atr_win": avg([r["atr"] for r in wins]),
        "avg_atr_loss": avg([r["atr"] for r in losses]),
    }


def print_result_block(title: str, rows: list[dict]) -> None:
    stats = summarize_results(rows)
    print(f"\n{title}")
    print(f"  Total      : {stats['total']}")
    print(f"  Resueltos  : {stats['resolved']}")
    print(f"  Win/Loss   : {stats['wins']}W / {stats['losses']}L")
    print(f"  Pendientes : {stats['pending']}")
    print(f"  Winrate    : {stats['winrate']:.1f}%")
    print(f"  P&L        : ${stats['pnl']:.2f}")
    if stats["resolved"]:
        rr = stats["avg_win"] / stats["avg_loss"] if stats["avg_loss"] else float("inf")
        print(f"  Avg WIN    : ${stats['avg_win']:.2f}")
        print(f"  Avg LOSS   : ${stats['avg_loss']:.2f}")
        print(f"  R:R        : {rr:.2f}")
        print(f"  Avg raw score WIN  : {stats['avg_raw_score_win']:.2f}")
        print(f"  Avg raw score LOSS : {stats['avg_raw_score_loss']:.2f}")
        print(f"  Avg ATR WIN        : {stats['avg_atr_win']:.6f}")
        print(f"  Avg ATR LOSS       : {stats['avg_atr_loss']:.6f}")


def main() -> None:
    db = load_db()
    c = db.cursor()
    c.execute(
        """
        SELECT id, asset, direction, score, confidence, payout, decision, order_id,
               strategy_details, order_result, profit, created_at
        FROM scan_candidates
        WHERE strategy = 'C'
        ORDER BY created_at ASC
        """
    )
    all_candidates = [parse_candidate(row) for row in c.fetchall()]
    db.close()

    accepted = [r for r in all_candidates if r["decision"] == "ACCEPTED"]
    executed_rows = [
        r for r in accepted
        if r["order_id"] and len(r["order_id"]) > 10
    ]
    by_order_id: dict[str, list[dict]] = defaultdict(list)
    for row in executed_rows:
        by_order_id[row["order_id"]].append(row)
    deduped_orders = [group[0] for group in by_order_id.values()]

    decisions = Counter(r["decision"] for r in all_candidates)
    reject_reasons = Counter(
        r["decision"] + " | " + (r["source"] or "?")
        for r in all_candidates if r["decision"].startswith("REJECTED")
    )

    print("=" * 84)
    print("STRAT-C DEEP ANALYSIS — TESIS VS DATA REAL DEL SISTEMA")
    print("=" * 84)
    print(f"Candidatos totales          : {len(all_candidates)}")
    print(f"Aceptados                  : {len(accepted)} ({pct(len(accepted), len(all_candidates)):.1f}%)")
    print(f"Rows ejecutados en BD       : {len(executed_rows)}")
    print(f"Ordenes broker unicas       : {len(deduped_orders)}")
    print(f"Order IDs duplicados        : {sum(1 for v in by_order_id.values() if len(v) > 1)}")

    print("\nDECISIONES EN CAJA NEGRA")
    for key, value in decisions.most_common():
        print(f"  {key:20} {value:3d} ({pct(value, len(all_candidates)):.1f}%)")

    print_result_block("ESTADISTICA BRUTA (filas de caja negra)", executed_rows)
    print_result_block("ESTADISTICA DEDUPLICADA (orden real de broker)", deduped_orders)

    thesis_ok = [
        r for r in deduped_orders
        if r["raw_score"] >= THESIS_MIN_RAW_SCORE and THESIS_ATR_MIN <= r["atr"] <= THESIS_ATR_MAX
    ]
    runtime_only = [r for r in deduped_orders if r not in thesis_ok]
    low_score = [r for r in deduped_orders if r["raw_score"] < THESIS_MIN_RAW_SCORE]
    atr_outside = [r for r in deduped_orders if not (THESIS_ATR_MIN <= r["atr"] <= THESIS_ATR_MAX)]

    print("\nCOMPARACION CONTRA TESIS")
    print(f"  Tesis exige raw score >= {THESIS_MIN_RAW_SCORE:.1f}")
    print(f"  Runtime actual usa raw score >= {RUNTIME_MIN_RAW_SCORE:.1f}")
    print(f"  Tesis exige ATR en [{THESIS_ATR_MIN:.5f}, {THESIS_ATR_MAX:.5f}]")
    print(f"  Runtime actual usa ATR_MAX={RUNTIME_ATR_MAX:.1f} (tope practicamente desactivado)")
    print(f"  Ordenes que SI cumplen tesis    : {len(thesis_ok)}/{len(deduped_orders)}")
    print(f"  Ordenes fuera de tesis por score: {len(low_score)}/{len(deduped_orders)}")
    print(f"  Ordenes fuera de tesis por ATR  : {len(atr_outside)}/{len(deduped_orders)}")

    print_result_block("SOLO ORDENES QUE CUMPLEN TESIS", thesis_ok)
    print_result_block("ORDENES PERMITIDAS POR RUNTIME PERO FUERA DE TESIS", runtime_only)

    print("\nDESGLOSE POR SCORE RAW")
    score_buckets = {
        "<6": [r for r in deduped_orders if r["raw_score"] < 6],
        "6-7.9": [r for r in deduped_orders if 6 <= r["raw_score"] < 8],
        "8+": [r for r in deduped_orders if r["raw_score"] >= 8],
    }
    for label, rows in score_buckets.items():
        stats = summarize_results(rows)
        print(f"  {label:5} -> {stats['resolved']:2d} resueltos | {stats['wins']}W/{stats['losses']}L | WR {stats['winrate']:.1f}% | P&L ${stats['pnl']:.2f}")

    print("\nDESGLOSE POR FUENTE")
    source_groups: dict[str, list[dict]] = defaultdict(list)
    for row in deduped_orders:
        source_groups[row["source"] or "unknown"].append(row)
    for source, rows in sorted(source_groups.items()):
        stats = summarize_results(rows)
        print(f"  {source:15} -> {stats['resolved']:2d} resueltos | {stats['wins']}W/{stats['losses']}L | WR {stats['winrate']:.1f}% | P&L ${stats['pnl']:.2f}")

    print("\nDUPLICACION DE ORDER_IDs")
    for order_id, rows in by_order_id.items():
        if len(rows) < 2:
            continue
        assets = ", ".join(r["asset"] for r in rows)
        sources = ", ".join(r["source"] or "?" for r in rows)
        print(f"  {order_id[:8]}... count={len(rows)} | assets=[{assets}] | source=[{sources}] | result={rows[0]['result']}")

    print("\nTOP RECHAZOS")
    for reason, count in reject_reasons.most_common(6):
        print(f"  {reason:40} {count:3d}")

    print("\nCONCLUSIONES")
    conclusions = []
    deduped_stats = summarize_results(deduped_orders)
    thesis_stats = summarize_results(thesis_ok)
    if deduped_stats["winrate"] < 60.0:
        conclusions.append(f"La muestra deduplicada queda en {deduped_stats['winrate']:.1f}% de winrate y P&L ${deduped_stats['pnl']:.2f}: no alcanza el criterio de activacion.")
    if len(by_order_id) < len(executed_rows):
        conclusions.append("La caja negra esta inflando la muestra: hay multiples candidatos asociados a una misma orden real del broker.")
    if len(low_score) > 0:
        conclusions.append(f"El runtime esta dejando pasar {len(low_score)} ordenes con raw score < 6, por debajo del umbral formal de la tesis.")
    if len(atr_outside) > 0:
        conclusions.append(f"El filtro ATR de la tesis esta relajado en runtime: {len(atr_outside)} ordenes quedaron fuera del rango ATR esperado.")
    if thesis_ok and thesis_stats["winrate"] > deduped_stats["winrate"]:
        conclusions.append(f"Filtrar solo ordenes que respetan la tesis mejora la muestra a {thesis_stats['winrate']:.1f}% WR y P&L ${thesis_stats['pnl']:.2f}.")
    if not conclusions:
        conclusions.append("No se detectaron divergencias obvias entre tesis y runtime en la muestra actual.")
    for item in conclusions:
        print(f"  - {item}")

    print("\n" + "=" * 84)


if __name__ == "__main__":
    main()
