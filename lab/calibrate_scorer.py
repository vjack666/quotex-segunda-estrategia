#!/usr/bin/env python3
"""
calibrate_scorer.py
───────────────────
Calibración offline de pesos del scorer usando historial SQLite.

Uso:
    python lab/calibrate_scorer.py [ruta_opcional/trade_journal.db]

Requiere: solo stdlib + sqlite3 (Python 3.13).
"""

import math
import sqlite3
import sys
from pathlib import Path


# ─────────────────────────────────────────────────────────────────────────────
#  CONFIGURACIÓN
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_DB = Path(__file__).resolve().parent.parent / "trade_journal.db"

CURRENT_WEIGHTS = {
    "compression": 25,
    "bounce":      30,
    "trend":       25,
    "payout":      20,
}
CURRENT_THRESHOLD = 62

THRESHOLD_SEARCH_RANGE = range(45, 80)


# ─────────────────────────────────────────────────────────────────────────────
#  ESTADÍSTICA
# ─────────────────────────────────────────────────────────────────────────────

def pearson(xs: list[float], ys: list[float]) -> float:
    """Coeficiente de correlación de Pearson entre dos listas."""
    n = len(xs)
    if n < 2:
        return 0.0
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    denom_x = math.sqrt(sum((x - mean_x) ** 2 for x in xs))
    denom_y = math.sqrt(sum((y - mean_y) ** 2 for y in ys))
    if denom_x == 0 or denom_y == 0:
        return 0.0
    return num / (denom_x * denom_y)


def expected_value(outcomes: list[int], payouts: list[float]) -> float:
    """
    EV = winrate * avg_payout_rate - (1 - winrate)
    payout_rate = payout% / 100.0 (e.g. 0.82 for 82%)
    """
    n = len(outcomes)
    if n == 0:
        return 0.0
    wins = sum(outcomes)
    winrate = wins / n
    avg_payout_rate = sum(payouts) / n if payouts else 0.80
    return winrate * avg_payout_rate - (1 - winrate)


# ─────────────────────────────────────────────────────────────────────────────
#  LECTURA DE BASE DE DATOS
# ─────────────────────────────────────────────────────────────────────────────

def load_trades(db_path: Path) -> list[dict]:
    """
    Carga registros con outcome WIN/LOSS y decision=ACCEPTED.
    Columnas esperadas en candidates: asset, score, score_compression,
    score_bounce, score_trend, score_payout, zone_age_min, payout.
    """
    if not db_path.exists():
        print(f"[ERROR] Base de datos no encontrada: {db_path}")
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Detectar columnas disponibles
    cur.execute("PRAGMA table_info(candidates)")
    cols_info = cur.fetchall()
    available = {row["name"] for row in cols_info}

    # Columnas a intentar leer (pueden no existir en versiones antiguas)
    optional_score_cols = ["score_compression", "score_bounce", "score_trend", "score_payout"]
    present_score_cols = [c for c in optional_score_cols if c in available]

    score_sel = ", ".join(present_score_cols) if present_score_cols else ""
    age_col = "zone_age_min" if "zone_age_min" in available else "NULL AS zone_age_min"
    payout_col = "payout" if "payout" in available else "NULL AS payout"
    total_score_col = "score" if "score" in available else "NULL AS score"

    query = f"""
        SELECT
            asset,
            {total_score_col},
            {age_col},
            {payout_col}
            {', ' + score_sel if score_sel else ''}
        FROM candidates
        WHERE outcome IN ('WIN', 'LOSS')
          AND decision = 'ACCEPTED'
    """
    try:
        cur.execute(query)
        rows = [dict(row) for row in cur.fetchall()]
    except sqlite3.OperationalError as e:
        # Fallback simplificado
        print(f"[WARN] Query completa falló ({e}). Intentando query mínima...")
        cur.execute("""
            SELECT asset, score, outcome, payout
            FROM candidates
            WHERE outcome IN ('WIN', 'LOSS') AND decision = 'ACCEPTED'
        """)
        rows = [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()

    return rows


def load_outcomes(db_path: Path) -> list[dict]:
    """
    Combina candidates con orders para obtener outcome real.
    """
    if not db_path.exists():
        print(f"[ERROR] Base de datos no encontrada: {db_path}")
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Intentar join con orders para obtener payout real
    try:
        cur.execute("""
            SELECT
                c.asset,
                c.score,
                c.outcome,
                COALESCE(c.payout, o.payout, 82) AS payout_pct,
                COALESCE(c.zone_age_min, 0) AS zone_age_min,
                COALESCE(c.score_compression, 0) AS score_compression,
                COALESCE(c.score_bounce, 0) AS score_bounce,
                COALESCE(c.score_trend, 0) AS score_trend,
                COALESCE(c.score_payout, 0) AS score_payout
            FROM candidates c
            LEFT JOIN orders o ON c.order_id = o.id
            WHERE c.outcome IN ('WIN', 'LOSS')
              AND c.decision = 'ACCEPTED'
        """)
        rows = [dict(row) for row in cur.fetchall()]
    except sqlite3.OperationalError:
        cur.execute("""
            SELECT asset, score, outcome,
                   COALESCE(payout, 82) AS payout_pct,
                   0 AS zone_age_min,
                   0 AS score_compression,
                   0 AS score_bounce,
                   0 AS score_trend,
                   0 AS score_payout
            FROM candidates
            WHERE outcome IN ('WIN', 'LOSS') AND decision = 'ACCEPTED'
        """)
        rows = [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()

    return rows


# ─────────────────────────────────────────────────────────────────────────────
#  ANÁLISIS
# ─────────────────────────────────────────────────────────────────────────────

def analyse(rows: list[dict]) -> None:
    n = len(rows)
    if n == 0:
        print("\n[!] No hay registros suficientes (WIN/LOSS + ACCEPTED) en la base de datos.")
        return

    print(f"\n{'═'*58}")
    print(f"  CALIBRACIÓN SCORER — {n} operaciones con resultado")
    print(f"{'═'*58}")

    outcomes = [1 if r["outcome"] == "WIN" else 0 for r in rows]
    payouts_rate = [float(r.get("payout_pct") or 82) / 100.0 for r in rows]
    scores = [float(r.get("score") or 0.0) for r in rows]
    ages = [float(r.get("zone_age_min") or 0.0) for r in rows]
    compr = [float(r.get("score_compression") or 0.0) for r in rows]
    bounce = [float(r.get("score_bounce") or 0.0) for r in rows]
    trend = [float(r.get("score_trend") or 0.0) for r in rows]
    payout_s = [float(r.get("score_payout") or 0.0) for r in rows]

    wins = sum(outcomes)
    global_winrate = wins / n

    print(f"\n  Winrate global       : {global_winrate*100:.1f}%  ({wins}W / {n-wins}L)")
    print(f"  EV global            : {expected_value(outcomes, payouts_rate)*100:.2f}%")

    # Correlaciones
    print(f"\n  {'Componente':<22} {'Corr. Pearson':>14}  {'Peso actual':>11}")
    print(f"  {'-'*22}  {'-'*14}  {'-'*11}")
    components = {
        "compression": compr,
        "bounce":      bounce,
        "trend":       trend,
        "payout":      payout_s,
    }
    correlations: dict[str, float] = {}
    for name, values in components.items():
        corr = pearson(values, outcomes)
        correlations[name] = corr
        current_w = CURRENT_WEIGHTS.get(name, 0)
        bar = "█" * max(0, round(abs(corr) * 20))
        sign = "+" if corr >= 0 else "-"
        print(f"  {name:<22} {sign}{abs(corr):.4f}  {bar:<20}  {current_w:>9d}")

    corr_age = pearson(ages, outcomes)
    print(f"  {'zone_age_min':<22} {'+' if corr_age>=0 else '-'}{abs(corr_age):.4f}  "
          f"{'█' * max(0, round(abs(corr_age)*20)):<20}  {'(penaliz.)'}")

    print(f"  {'total_score':<22}  {pearson(scores, outcomes):+.4f}")

    # Pesos propuestos
    abs_corr = {k: abs(v) for k, v in correlations.items()}
    total_abs = sum(abs_corr.values()) or 1.0
    suggested_weights = {k: round(v / total_abs * 100) for k, v in abs_corr.items()}

    # Normalizar a exactamente 100
    diff = 100 - sum(suggested_weights.values())
    if diff != 0:
        key = max(abs_corr, key=abs_corr.get)  # type: ignore[arg-type]
        suggested_weights[key] += diff

    print(f"\n  {'Componente':<22} {'Peso actual':>11}  {'Peso sugerido':>13}")
    print(f"  {'-'*22}  {'-'*11}  {'-'*13}")
    for name in CURRENT_WEIGHTS:
        print(f"  {name:<22} {CURRENT_WEIGHTS[name]:>11}  {suggested_weights.get(name, 0):>13}")

    # Búsqueda de umbral óptimo
    print(f"\n  Búsqueda de umbral óptimo (EV)  [actual: {CURRENT_THRESHOLD}]")
    print(f"  {'Umbral':>7}  {'N ops':>6}  {'Winrate':>8}  {'EV':>8}")
    print(f"  {'-'*7}  {'-'*6}  {'-'*8}  {'-'*8}")

    best_threshold = CURRENT_THRESHOLD
    best_ev = -999.0

    for thr in THRESHOLD_SEARCH_RANGE:
        subset = [(o, p) for o, p, s in zip(outcomes, payouts_rate, scores) if s >= thr]
        if len(subset) < 5:
            continue
        sub_out, sub_pay = zip(*subset)
        ev = expected_value(list(sub_out), list(sub_pay))
        wr = sum(sub_out) / len(sub_out)
        marker = " ← actual" if thr == CURRENT_THRESHOLD else ""
        if ev > best_ev:
            best_ev = ev
            best_threshold = thr
        print(f"  {thr:>7}  {len(subset):>6}  {wr*100:>7.1f}%  {ev*100:>7.2f}%{marker}")

    print(f"\n  ➜ Umbral con mayor EV: {best_threshold}  (EV={best_ev*100:.2f}%)")
    if best_threshold != CURRENT_THRESHOLD:
        print(f"  ➜ Sugerencia: cambiar SCORE_THRESHOLD de {CURRENT_THRESHOLD} → {best_threshold}")
    else:
        print(f"  ✔  Umbral actual ({CURRENT_THRESHOLD}) ya es el óptimo.")

    print(f"\n{'═'*58}\n")


# ─────────────────────────────────────────────────────────────────────────────
#  ENTRYPOINT
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    db_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DB
    rows = load_outcomes(db_path)
    analyse(rows)
