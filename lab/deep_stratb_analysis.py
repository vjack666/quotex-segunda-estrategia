"""
ANÁLISIS PROFUNDO Y COMPLETO DE STRAT-B
========================================

Este script ejecuta un análisis exhaustivo de la estrategia B (Spring Sweep):
- Cajas negras (black box review)
- Desempeño de decisiones (ACCEPTED vs REJECTED)
- Distribución de señales Wyckoff
- Patrones de confianza y validez
- Propuesta de mejoras específicas
- Optimización de parámetros de escaneo
"""

import sqlite3
import glob
import json
from collections import Counter, defaultdict
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple, Any

def load_latest_db() -> Tuple[str, sqlite3.Connection]:
    """Carga la base de datos más reciente."""
    dbs = sorted(glob.glob('data/db/trade_journal-*.db'), reverse=True)
    if not dbs:
        raise RuntimeError("⚠ No hay bases de datos. Ejecuta primero el bot para generar registros.")
    db_path = dbs[0]
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    return db_path, con


def fetch_candidates(con: sqlite3.Connection, strategy: str = "STRAT-B") -> List[Dict]:
    """Obtiene todos los candidatos de una estrategia."""
    cur = con.cursor()
    cur.execute('''
        SELECT scanned_at, asset, direction, score, decision, reject_reason,
               reversal_pattern, outcome, profit, amount, payout, stage, 
               strategy_json
        FROM candidates
        WHERE 1=1
        ORDER BY scanned_at DESC
    ''')
    rows = cur.fetchall()
    
    # Separar por estrategia basado en strategy_json
    results = []
    for r in rows:
        try:
            sj = json.loads(r["strategy_json"] or "{}")
            origin = sj.get("strategy_origin", sj.get("strategy", "STRAT-A"))
            if origin != strategy:
                continue
        except:
            continue
        results.append(dict(r))
    
    return results


def analyze_decisions(candidates: List[Dict]) -> Dict[str, Any]:
    """Analiza decisiones: ACCEPTED vs REJECTED."""
    accepted = [c for c in candidates if c["decision"] == "ACCEPTED"]
    rejected = [c for c in candidates if c["decision"].startswith("REJECTED")]
    
    a_wins = sum(1 for c in accepted if c["outcome"] == "WIN")
    a_losses = sum(1 for c in accepted if c["outcome"] == "LOSS")
    a_pending = len(accepted) - a_wins - a_losses
    a_pnl = sum(float(c["profit"] or 0) for c in accepted)
    
    # Razones de rechazo
    reject_reasons = Counter(c["reject_reason"] or "UNKNOWN" for c in rejected)
    
    # Score distribution en ACCEPTED
    scores_accepted = [float(c["score"] or 0) for c in accepted]
    scores_rejected = [float(c["score"] or 0) for c in rejected]
    
    return {
        "total_candidates": len(candidates),
        "accepted": len(accepted),
        "rejected": len(rejected),
        "acceptance_rate": len(accepted) / len(candidates) if candidates else 0,
        "wins": a_wins,
        "losses": a_losses,
        "pending": a_pending,
        "winrate": a_wins / len(accepted) if accepted else 0,
        "pnl": a_pnl,
        "avg_score_accepted": sum(scores_accepted) / len(scores_accepted) if scores_accepted else 0,
        "avg_score_rejected": sum(scores_rejected) / len(scores_rejected) if scores_rejected else 0,
        "max_score_accepted": max(scores_accepted) if scores_accepted else 0,
        "min_score_accepted": min(scores_accepted) if scores_accepted else 0,
        "reject_reasons": dict(reject_reasons.most_common(10)),
    }


def analyze_signals(candidates: List[Dict]) -> Dict[str, Any]:
    """Analiza distribución y confianza de señales Wyckoff."""
    accepted = [c for c in candidates if c["decision"] == "ACCEPTED"]
    
    signals = defaultdict(list)
    confidence_by_signal = defaultdict(list)
    
    for c in accepted:
        try:
            sj = json.loads(c["strategy_json"] or "{}")
            signal_type = sj.get("strat_b_signal_type", "unknown")
            confidence = float(sj.get("strat_b_confidence", 0) or 0)
            signals[signal_type].append(c)
            confidence_by_signal[signal_type].append(confidence)
        except:
            pass
    
    # Calcular estadísticas por tipo de señal
    stats = {}
    for sig_type, sig_candidates in signals.items():
        wins = sum(1 for c in sig_candidates if c["outcome"] == "WIN")
        losses = sum(1 for c in sig_candidates if c["outcome"] == "LOSS")
        pnl = sum(float(c["profit"] or 0) for c in sig_candidates)
        confs = confidence_by_signal[sig_type]
        
        stats[sig_type] = {
            "count": len(sig_candidates),
            "wins": wins,
            "losses": losses,
            "winrate": wins / len(sig_candidates) if sig_candidates else 0,
            "pnl": pnl,
            "avg_confidence": sum(confs) / len(confs) if confs else 0,
            "min_confidence": min(confs) if confs else 0,
            "max_confidence": max(confs) if confs else 0,
        }
    
    return stats


def analyze_assets(candidates: List[Dict]) -> Dict[str, Any]:
    """Analiza desempeño por activo."""
    accepted = [c for c in candidates if c["decision"] == "ACCEPTED"]
    
    by_asset = defaultdict(list)
    for c in accepted:
        by_asset[c["asset"]].append(c)
    
    stats = {}
    for asset, asset_candidates in by_asset.items():
        wins = sum(1 for c in asset_candidates if c["outcome"] == "WIN")
        losses = sum(1 for c in asset_candidates if c["outcome"] == "LOSS")
        pnl = sum(float(c["profit"] or 0) for c in asset_candidates)
        scores = [float(c["score"] or 0) for c in asset_candidates]
        
        stats[asset] = {
            "count": len(asset_candidates),
            "wins": wins,
            "losses": losses,
            "winrate": wins / len(asset_candidates) if asset_candidates else 0,
            "pnl": pnl,
            "avg_score": sum(scores) / len(scores) if scores else 0,
        }
    
    return dict(sorted(stats.items(), key=lambda x: x[1]["count"], reverse=True))


def analyze_entry_quality(candidates: List[Dict]) -> Dict[str, Any]:
    """Analiza calidad de entrada: relation entre score y outcome."""
    accepted = [c for c in candidates if c["decision"] == "ACCEPTED"]
    
    # Segmentar por rangos de score
    score_ranges = {
        "muy_bajo": [c for c in accepted if float(c["score"] or 0) < 45],
        "bajo": [c for c in accepted if 45 <= float(c["score"] or 0) < 55],
        "medio": [c for c in accepted if 55 <= float(c["score"] or 0) < 65],
        "alto": [c for c in accepted if 65 <= float(c["score"] or 0) < 75],
        "muy_alto": [c for c in accepted if float(c["score"] or 0) >= 75],
    }
    
    stats = {}
    for range_name, range_candidates in score_ranges.items():
        if not range_candidates:
            continue
        wins = sum(1 for c in range_candidates if c["outcome"] == "WIN")
        losses = sum(1 for c in range_candidates if c["outcome"] == "LOSS")
        pnl = sum(float(c["profit"] or 0) for c in range_candidates)
        
        stats[range_name] = {
            "count": len(range_candidates),
            "wins": wins,
            "losses": losses,
            "winrate": wins / len(range_candidates) if range_candidates else 0,
            "pnl": pnl,
        }
    
    return stats


def identify_improvements(analysis: Dict[str, Any], signals: Dict[str, Any], assets: Dict[str, Any]) -> List[str]:
    """Identifica mejoras específicas basadas en el análisis."""
    improvements = []
    
    # Mejora 1: Threshold de score
    if analysis["avg_score_rejected"] > 45:
        improvements.append(
            f"🎯 SCORE THRESHOLD: Score rechazados promedio es {analysis['avg_score_rejected']:.1f}. "
            f"Considerar bajar threshold o revisar lógica de rejection."
        )
    
    if analysis["avg_score_accepted"] < 55:
        improvements.append(
            f"⚠️ QUALITY: Score aceptados bajo ({analysis['avg_score_accepted']:.1f}). "
            f"Aumentar entrada solo scores > 60 para mejorar winrate."
        )
    
    # Mejora 2: Winrate por señal
    for sig_type, sig_stats in signals.items():
        if sig_stats["winrate"] < 0.45 and sig_stats["count"] >= 5:
            improvements.append(
                f"❌ SEÑAL {sig_type}: Winrate baja ({sig_stats['winrate']:.1%}) con {sig_stats['count']} muestras. "
                f"Revisar lógica de detección o aumentar confidence mínima."
            )
        elif sig_stats["winrate"] > 0.60 and sig_stats["count"] >= 5:
            improvements.append(
                f"✅ SEÑAL {sig_type}: Winrate fuerte ({sig_stats['winrate']:.1%}). "
                f"Aumentar volumen de escaneo para esta señal."
            )
    
    # Mejora 3: Activos consistentes
    top_assets = sorted(assets.items(), key=lambda x: x[1]["winrate"], reverse=True)[:3]
    for asset, stats in top_assets:
        if stats["winrate"] > 0.55 and stats["count"] >= 3:
            improvements.append(
                f"💰 ACTIVO {asset}: Excelente winrate ({stats['winrate']:.1%}). "
                f"Aumentar frequency de escaneo en este par."
            )
    
    # Mejora 4: Confidence threshold
    min_confidence = min(sig["min_confidence"] for sig in signals.values() if sig["count"] > 0)
    if min_confidence < 0.50:
        improvements.append(
            f"🔐 CONFIDENCE: Mínima detectada es {min_confidence:.1%}. "
            f"Establecer piso de 65% para evitar falsos positivos."
        )
    
    # Mejora 5: Acceptance rate
    if analysis["acceptance_rate"] < 0.10:
        improvements.append(
            f"📊 ACCEPTANCE: Solo {analysis['acceptance_rate']:.1%} de candidatos aceptados. "
            f"Revisar si threshold es demasiado restrictivo."
        )
    elif analysis["acceptance_rate"] > 0.40:
        improvements.append(
            f"⚠️ ACCEPTANCE: {analysis['acceptance_rate']:.1%} de candidatos aceptados. "
            f"Aumentar selectividad para evitar overfitting."
        )
    
    # Mejora 6: Razones de rechazo
    reject_reasons = analysis["reject_reasons"]
    if "REJECTED_LIMIT" in reject_reasons and reject_reasons["REJECTED_LIMIT"] > len(analysis) * 0.3:
        improvements.append(
            f"🚫 REJECTED_LIMIT: {reject_reasons['REJECTED_LIMIT']} casos. "
            f"Revisar límites de ciclo/balance/cooldown. Quizás son demasiado restrictivos."
        )
    
    if not improvements:
        improvements.append("✅ STRAT-B está bien optimizada. Monitorear próximas sesiones para más datos.")
    
    return improvements


def print_header(title: str) -> None:
    """Imprime encabezado formateado."""
    print(f"\n{'═' * 80}")
    print(f"  {title}")
    print(f"{'═' * 80}\n")


def main() -> None:
    try:
        db_path, con = load_latest_db()
        print(f"\n📊 BASE DE DATOS: {db_path}")
        print(f"Generado: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Cargar datos
        candidates = fetch_candidates(con)
        if not candidates:
            print("⚠️  Sin registros STRAT-B en la DB. Ejecuta el bot primero.")
            con.close()
            return
        
        print(f"\n✅ Cargados {len(candidates)} candidatos STRAT-B")
        
        # Análisis 1: Decisiones
        print_header("1. ANÁLISIS DE DECISIONES (ACCEPTED vs REJECTED)")
        analysis = analyze_decisions(candidates)
        
        print(f"Total candidatos: {analysis['total_candidates']}")
        print(f"Acceptance rate:  {analysis['acceptance_rate']:.1%}")
        print(f"  • Aceptados:    {analysis['accepted']}")
        print(f"  • Rechazados:   {analysis['rejected']}")
        print()
        print(f"Performance ACCEPTED:")
        print(f"  • Wins:         {analysis['wins']}")
        print(f"  • Losses:       {analysis['losses']}")
        print(f"  • Pending:      {analysis['pending']}")
        print(f"  • Winrate:      {analysis['winrate']:.1%}")
        print(f"  • P&L:          {analysis['pnl']:+.2f}")
        print()
        print(f"Score Analysis:")
        print(f"  • Aceptados:    avg={analysis['avg_score_accepted']:.1f}  "
              f"rango=[{analysis['min_score_accepted']:.1f}, {analysis['max_score_accepted']:.1f}]")
        print(f"  • Rechazados:   avg={analysis['avg_score_rejected']:.1f}")
        print()
        print(f"Top razones de rechazo:")
        for reason, count in list(analysis['reject_reasons'].items())[:5]:
            pct = count / analysis['rejected'] * 100 if analysis['rejected'] > 0 else 0
            print(f"  • {reason:40s}: {count:3d} ({pct:.1f}%)")
        
        # Análisis 2: Señales Wyckoff
        print_header("2. ANÁLISIS DE SEÑALES WYCKOFF")
        signals = analyze_signals(candidates)
        
        for sig_type, stats in sorted(signals.items(), key=lambda x: x[1]["count"], reverse=True):
            print(f"\n  {sig_type.upper()}")
            print(f"    Muestras:    {stats['count']}")
            print(f"    Winrate:     {stats['winrate']:.1%}  (W:{stats['wins']} L:{stats['losses']})")
            print(f"    P&L:         {stats['pnl']:+.2f}")
            print(f"    Confidence:  avg={stats['avg_confidence']:.1%}  "
                  f"rango=[{stats['min_confidence']:.1%}, {stats['max_confidence']:.1%}]")
        
        # Análisis 3: Activos
        print_header("3. ANÁLISIS POR ACTIVO")
        assets = analyze_assets(candidates)
        
        print(f"{'Activo':<15} {'Ops':>4} {'Win':>4} {'Loss':>4} {'WR':>6} {'P&L':>8} {'Score':>7}")
        print(f"{'-' * 60}")
        for asset, stats in list(assets.items())[:15]:
            print(f"{asset:<15} {stats['count']:4d} {stats['wins']:4d} {stats['losses']:4d} "
                  f"{stats['winrate']:>5.1%} {stats['pnl']:>7.2f}  {stats['avg_score']:>6.1f}")
        
        # Análisis 4: Calidad de entrada por score
        print_header("4. ANÁLISIS DE CALIDAD (SCORE vs OUTCOME)")
        entry_quality = analyze_entry_quality(candidates)
        
        print(f"{'Rango Score':<15} {'Ops':>4} {'Win':>4} {'Loss':>4} {'WR':>6} {'P&L':>8}")
        print(f"{'-' * 50}")
        for range_name in ["muy_bajo", "bajo", "medio", "alto", "muy_alto"]:
            if range_name in entry_quality:
                stats = entry_quality[range_name]
                print(f"{range_name:<15} {stats['count']:4d} {stats['wins']:4d} {stats['losses']:4d} "
                      f"{stats['winrate']:>5.1%} {stats['pnl']:>7.2f}")
        
        # Análisis 5: Mejoras propuestas
        print_header("5. RECOMENDACIONES DE MEJORA")
        improvements = identify_improvements(analysis, signals, assets)
        for i, imp in enumerate(improvements, 1):
            print(f"{i}. {imp}")
        
        # Resumen ejecutivo
        print_header("RESUMEN EJECUTIVO")
        print(f"""
📈 KEY METRICS:
   • Acceptance rate:  {analysis['acceptance_rate']:.1%} ({analysis['accepted']}/{analysis['total_candidates']})
   • Overall winrate:  {analysis['winrate']:.1%} ({analysis['wins']}/{analysis['wins'] + analysis['losses']})
   • Total P&L:        {analysis['pnl']:+.2f}
   • Mejor score:      {analysis['max_score_accepted']:.1f}
   • Peor score:       {analysis['min_score_accepted']:.1f}

🎯 NEXT STEPS:
   1. Ejecutar: python lab/deep_stratb_analysis.py --optimize
   2. Tunear parámetros en strategy_spring_sweep.py
   3. Validar cambios con histórico completo
   4. Desplegar en bot central
        """)
        
        con.close()
        
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
