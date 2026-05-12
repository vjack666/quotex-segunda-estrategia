"""
audit_pipeline_analyzer.py
==========================

Lee logs de consolidation_bot y extrae métricas estructuradas
sin modificar el código de trading. 

Extrae:
- Activos escaneados
- Candidatos creados/rechazados
- Razones de rechazo
- HTF cache status
- Timing

Entrada: consolidation_bot-YYYY-MM-DD.log
Salida: Resumen estadístico + timeline + cuello identificado
"""

import re
from collections import defaultdict
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple, Optional
import json

class AuditPipelineAnalyzer:
    def __init__(self, log_file_path: str):
        self.log_path = Path(log_file_path)
        self.lines = []
        self.metrics = defaultdict(lambda: defaultdict(int))
        self.timeline = []
        self.errors = []
        
        self._load_logs()
    
    def _load_logs(self):
        """Carga todos los logs del archivo."""
        if not self.log_path.exists():
            raise FileNotFoundError(f"Log file not found: {self.log_path}")
        
        with open(self.log_path, 'r', encoding='utf-8', errors='replace') as f:
            self.lines = f.readlines()
        
        print(f"✓ Cargados {len(self.lines)} líneas de log")
    
    def extract_scan_cycles(self) -> List[Dict]:
        """Extrae ciclos de escaneo con resumen."""
        cycles = []
        
        # Patrón: "═══ SCAN #N | M activos payout≥X%"
        scan_pattern = r'═══ SCAN #(\d+) \| (\d+) activos'
        
        for i, line in enumerate(self.lines):
            match = re.search(scan_pattern, line)
            if match:
                scan_num = int(match.group(1))
                total_assets = int(match.group(2))
                timestamp = self._extract_timestamp(line)
                
                cycles.append({
                    'scan_num': scan_num,
                    'total_assets': total_assets,
                    'timestamp': timestamp,
                    'line_num': i,
                })
        
        return cycles
    
    def _extract_timestamp(self, log_line: str) -> Optional[str]:
        """Extrae timestamp del formato de log."""
        # Busca formato: HH:MM:SS [LEVEL]
        ts_pattern = r'(\d{2}:\d{2}:\d{2})'
        match = re.search(ts_pattern, log_line)
        return match.group(1) if match else None
    
    def extract_candidates_and_rejects(self) -> Dict:
        """Extrae candidatos y razones de rechazo."""
        stats = {
            'total_created': 0,
            'total_rejected': 0,
            'rejected_by_reason': defaultdict(int),
            'rejects_by_asset': defaultdict(list),
            'candidates_by_asset': defaultdict(int),
        }
        
        # Patrón para "REJECTED_SCORE: reason"
        reject_patterns = [
            r'REJECTED_[A-Z_]+:\s*(.+?)(?:\s+\||$)',
            r'htf_alignment:\s*(.+?)(?:\s+\||$)',
            r'spike_1m:\s*(.+?)(?:\s+\||$)',
            r'score=[\d.]+\s*<\s*(.+?)(?:\s+\||$)',
        ]
        
        for line in self.lines:
            # Buscar menciones de rechazo
            if 'REJECTED' in line or 'rechazo' in line.lower():
                for pattern in reject_patterns:
                    match = re.search(pattern, line)
                    if match:
                        reason = match.group(1).strip()
                        stats['total_rejected'] += 1
                        stats['rejected_by_reason'][reason] += 1
                
                # Extraer asset si está disponible
                asset_match = re.search(r'([A-Z]+USD[A-Z_]*)', line)
                if asset_match:
                    asset = asset_match.group(1)
                    stats['rejects_by_asset'][asset].append(line)
        
        return stats
    
    def extract_htf_status(self) -> Dict:
        """Extrae estado del cache HTF."""
        htf_status = {
            'cache_empty_count': 0,
            'cache_insufficient_count': 0,
            'cache_ok_count': 0,
            'assets_with_htf': [],
            'htf_age_seconds': defaultdict(list),
        }
        
        # Patrón: "HTF 15m no disponible o insuficiente"
        htf_patterns = [
            (r'HTF 15m no disponible o insuficiente', 'insufficient'),
            (r'HTF.*cache.*empty', 'empty'),
            (r'candles15m:\s*(\d+)', 'candle_count'),
            (r'c15_age_s:\s*([\d.]+)', 'age_sec'),
        ]
        
        for line in self.lines:
            for pattern, tag in htf_patterns[:2]:
                if re.search(pattern, line):
                    if tag == 'insufficient':
                        htf_status['cache_insufficient_count'] += 1
                    elif tag == 'empty':
                        htf_status['cache_empty_count'] += 1
        
        return htf_status
    
    def extract_phase2_gates(self) -> Dict:
        """Extrae estadísticas de phase2 gates."""
        gates = defaultdict(int)
        
        # Patrones para cada gate
        gate_patterns = {
            'spike_1m': r'spike_1m:\s*',
            'spike_5m': r'spike_5m:\s*',
            'htf_alignment': r'htf_alignment:\s*',
            'score': r'score=',
            'pattern': r'patrón|pattern',
            'payout': r'payout',
            'zone_age': r'zone.*age',
        }
        
        for line in self.lines:
            if '[PHASE2' in line:
                for gate_name, pattern in gate_patterns.items():
                    if re.search(pattern, line):
                        gates[gate_name] += 1
        
        return dict(gates)
    
    def extract_entries_and_trades(self) -> Dict:
        """Extrae entradas reales y resultados."""
        entries = {
            'entries_opened': 0,
            'trades_resolved': 0,
            'wins': 0,
            'losses': 0,
        }
        
        # Patrones para detect entries
        for line in self.lines:
            if 'ENTRADA' in line or '_enter' in line:
                entries['entries_opened'] += 1
            if 'WIN' in line or 'ganancia' in line.lower():
                entries['wins'] += 1
            if 'LOSS' in line or 'pérdida' in line.lower():
                entries['losses'] += 1
        
        entries['trades_resolved'] = entries['wins'] + entries['losses']
        return entries
    
    def identify_bottleneck(self, cycles: List[Dict], rejects: Dict, htf: Dict, gates: Dict) -> str:
        """Identifica el cuello dominante."""
        if not cycles:
            return "ERROR: No cycles found in logs"
        
        total_scans = len(cycles)
        avg_assets = sum(c['total_assets'] for c in cycles) / total_scans if cycles else 0
        
        # Análisis de cuello
        observations = []
        
        # Si HTF está vacío/insuficiente frecuentemente
        if htf['cache_insufficient_count'] > total_scans * 0.3:
            observations.append(f"🔴 HTF INSUFICIENTE: {htf['cache_insufficient_count']} ciclos con cache vacio/insuficiente (>{30}% de ciclos)")
        
        # Si hay muchos rechazos por score
        score_rejects = rejects['rejected_by_reason'].get('score', 0) + rejects['rejected_by_reason'].get('umbral', 0)
        if score_rejects > rejects['total_rejected'] * 0.5:
            observations.append(f"🟡 SCORE FILTRO: {score_rejects} rechazos por score ({score_rejects/rejects['total_rejected']*100:.0f}% de rejects)")
        
        # Si hay muchos rechazos por spike
        spike_rejects = gates.get('spike_1m', 0) + gates.get('spike_5m', 0)
        if spike_rejects > rejects['total_rejected'] * 0.3:
            observations.append(f"🟡 SPIKE FILTRO: {spike_rejects} rechazos por spike")
        
        # Análisis de generación de candidatos
        if rejects['total_rejected'] > 0 and rejects['total_created'] == 0:
            observations.append("🔴 CANDIDATES: No se generaron candidatos en ningún ciclo")
        
        # Si assets disponibles pero no hay candidatos
        if avg_assets > 10 and rejects['total_rejected'] < total_scans * 0.5:
            observations.append(f"🟡 GENERACION LENTA: {avg_assets:.0f} activos/ciclo pero pocos candidates")
        
        return '\n'.join(observations) if observations else "✓ No cuello evidente identificado"
    
    def generate_report(self) -> str:
        """Genera reporte completo."""
        cycles = self.extract_scan_cycles()
        rejects_stats = self.extract_candidates_and_rejects()
        htf_stats = self.extract_htf_status()
        gates_stats = self.extract_phase2_gates()
        entries_stats = self.extract_entries_and_trades()
        
        # Enriquecer rejects_stats
        rejects_stats['total_created'] = entries_stats['entries_opened']
        
        bottleneck = self.identify_bottleneck(cycles, rejects_stats, htf_stats, gates_stats)
        
        avg_assets = sum(c['total_assets'] for c in cycles) / len(cycles) if cycles else 0
        
        report = f"""
╔═══════════════════════════════════════════════════════════════════════════════╗
║         AUDIT PIPELINE — ANÁLISIS DE CUELLO DE BOTELLA                        ║
╚═══════════════════════════════════════════════════════════════════════════════╝

📊 RESUMEN EJECUTIVO
────────────────────────────────────────────────────────────────────────────────
Ciclos de scan: {len(cycles)}
Activos promedio/ciclo: {avg_assets:.0f}
Rango: {min((c['total_assets'] for c in cycles), default=0)} - {max((c['total_assets'] for c in cycles), default=0)}

CANDIDATOS & RECHAZO
────────────────────────────────────────────────────────────────────────────────
Candidatos creados: {rejects_stats['total_created']}
Candidatos rechazados: {rejects_stats['total_rejected']}
Razones top de rechazo:
"""
        
        # Top rejection reasons
        top_reasons = sorted(
            rejects_stats['rejected_by_reason'].items(),
            key=lambda x: x[1],
            reverse=True
        )[:5]
        
        for reason, count in top_reasons:
            report += f"  • {reason[:60]}: {count}\n"
        
        # HTF Status
        report += f"""
HTF CACHE STATUS
────────────────────────────────────────────────────────────────────────────────
Cache insuficiente: {htf_stats['cache_insufficient_count']}
Cache vacío: {htf_stats['cache_empty_count']}
Cache OK: {htf_stats['cache_ok_count']}

PHASE2 GATES (Rechazo/Gate)
────────────────────────────────────────────────────────────────────────────────
"""
        
        for gate, count in sorted(gates_stats.items(), key=lambda x: x[1], reverse=True):
            report += f"  {gate}: {count}\n"
        
        # Trading Results
        report += f"""
TRADING RESULTS
────────────────────────────────────────────────────────────────────────────────
Trades abiertos: {entries_stats['entries_opened']}
Trades resueltos: {entries_stats['trades_resolved']}
Ganancias: {entries_stats['wins']}
Pérdidas: {entries_stats['losses']}
Win rate: {entries_stats['wins']/entries_stats['trades_resolved']*100:.1f}% if entries_stats['trades_resolved'] > 0 else N/A

🔍 CUELLO IDENTIFICADO
────────────────────────────────────────────────────────────────────────────────
{bottleneck}

────────────────────────────────────────────────────────────────────────────────
"""
        
        return report

def main():
    log_file = "data/logs/bot/consolidation_bot-2026-05-12.log"
    
    try:
        analyzer = AuditPipelineAnalyzer(log_file)
        report = analyzer.generate_report()
        print(report)
        
        # Guardar reporte
        report_file = "audit_pipeline_report.txt"
        Path(report_file).write_text(report)
        print(f"\n✓ Reporte guardado en: {report_file}")
        
    except FileNotFoundError as e:
        print(f"✗ Error: {e}")
    except Exception as e:
        print(f"✗ Error inesperado: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
