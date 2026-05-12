"""
instrumentation_layer.py — Capa de logging para auditoría de pipeline
================================================================

Propósito: Capturar métricas reales del pipeline sin modificar lógica.
Patrón: [PIPELINE-METRIC] [PIPELINE-REJECT] [PIPELINE-STATE]

NO modifica consolidation_bot.py directamente.
Se inyecta vía logging configuración.
"""

import logging
import json
from datetime import datetime
from typing import Any, Dict, Optional

# Crear logger dedicado para métricas del pipeline
pipeline_logger = logging.getLogger("pipeline_metrics")

# ─────────────────────────────────────────────────────────────────────────────
#  CONTADORES GLOBALES POR CICLO DE SCAN
# ─────────────────────────────────────────────────────────────────────────────

class PipelineMetrics:
    """Acumulador de métricas por ciclo de escaneo."""
    
    def __init__(self):
        self.reset()
    
    def reset(self):
        """Reinicia contadores para un nuevo ciclo."""
        self.timestamp = datetime.utcnow().isoformat()
        
        # TIER 1: Asset Discovery
        self.assets_total = 0
        self.assets_from_htf = 0
        self.assets_from_fallback = 0
        self.assets_skipped_trade_open = 0
        self.assets_skipped_greylist = 0
        self.assets_skipped_blacklist = 0
        self.assets_skipped_failed_recent = 0
        
        # TIER 2: Candle Fetch
        self.fetch_5m_total = 0
        self.fetch_5m_success = 0
        self.fetch_5m_timeout = 0
        self.fetch_5m_error = 0
        
        self.fetch_1m_total = 0
        self.fetch_1m_success = 0
        self.fetch_1m_timeout = 0
        self.fetch_1m_insufficient = 0
        self.fetch_1m_error = 0
        
        # TIER 3: Signal Detection
        self.strat_a_consolidation_detected = 0
        self.strat_a_no_consolidation = 0
        self.strat_b_spring_detected = 0
        self.strat_b_no_signal = 0
        self.strat_b_insufficient_candles = 0
        
        # TIER 4: Candidates
        self.candidates_created = 0
        self.candidates_rejected_pre_scoring = 0
        self.candidates_scored = 0
        self.candidates_failed_threshold = 0
        self.candidates_passed_threshold = 0
        
        # TIER 5: Pre-Validation Gates
        self.gate_spike_1m_reject = 0
        self.gate_spike_5m_reject = 0
        self.gate_htf_reject = 0
        self.gate_score_reject = 0
        self.gate_pattern_reject = 0
        self.gate_payout_reject = 0
        self.gate_other_reject = 0
        
        # TIER 6: Final Entry
        self.candidates_to_enter = 0
        self.trades_opened = 0
        
        # Timing
        self.cycle_duration_ms = 0
    
    def emit_summary(self, cycle_num: int):
        """Emite resumen en formato parseble."""
        summary = {
            "cycle": cycle_num,
            "timestamp": self.timestamp,
            "assets": {
                "total": self.assets_total,
                "from_htf": self.assets_from_htf,
                "from_fallback": self.assets_from_fallback,
                "skipped": {
                    "trade_open": self.assets_skipped_trade_open,
                    "greylist": self.assets_skipped_greylist,
                    "blacklist": self.assets_skipped_blacklist,
                    "failed_recent": self.assets_skipped_failed_recent,
                },
            },
            "fetches": {
                "candles_5m": {
                    "total": self.fetch_5m_total,
                    "success": self.fetch_5m_success,
                    "timeout": self.fetch_5m_timeout,
                    "error": self.fetch_5m_error,
                },
                "candles_1m": {
                    "total": self.fetch_1m_total,
                    "success": self.fetch_1m_success,
                    "timeout": self.fetch_1m_timeout,
                    "insufficient": self.fetch_1m_insufficient,
                    "error": self.fetch_1m_error,
                },
            },
            "signals": {
                "strat_a": {
                    "consolidation_detected": self.strat_a_consolidation_detected,
                    "no_signal": self.strat_a_no_consolidation,
                },
                "strat_b": {
                    "spring_detected": self.strat_b_spring_detected,
                    "no_signal": self.strat_b_no_signal,
                    "insufficient_candles": self.strat_b_insufficient_candles,
                },
            },
            "candidates": {
                "created": self.candidates_created,
                "rejected_pre_scoring": self.candidates_rejected_pre_scoring,
                "scored": self.candidates_scored,
                "failed_threshold": self.candidates_failed_threshold,
                "passed_threshold": self.candidates_passed_threshold,
            },
            "gates": {
                "spike_1m": self.gate_spike_1m_reject,
                "spike_5m": self.gate_spike_5m_reject,
                "htf": self.gate_htf_reject,
                "score": self.gate_score_reject,
                "pattern": self.gate_pattern_reject,
                "payout": self.gate_payout_reject,
                "other": self.gate_other_reject,
                "total_reject": (
                    self.gate_spike_1m_reject + self.gate_spike_5m_reject +
                    self.gate_htf_reject + self.gate_score_reject +
                    self.gate_pattern_reject + self.gate_payout_reject +
                    self.gate_other_reject
                ),
            },
            "final": {
                "to_enter": self.candidates_to_enter,
                "trades_opened": self.trades_opened,
            },
            "timing_ms": self.cycle_duration_ms,
        }
        
        pipeline_logger.info("[PIPELINE-SUMMARY] cycle=%d summary=%s", cycle_num, json.dumps(summary))

# Instancia global
metrics = PipelineMetrics()
