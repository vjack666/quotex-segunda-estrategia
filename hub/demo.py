#!/usr/bin/env python3
"""
Demo script — Prueba del HUB con datos simulados.
Muestra cómo el dashboard renderiza candidatos STRAT-A y STRAT-B.

Uso:
    python hub_demo.py
"""

import sys
from pathlib import Path
from datetime import datetime, timezone
import time

# Setup paths
ROOT = Path(__file__).resolve().parent.parent
HUB_DIR = ROOT / "hub"
if str(HUB_DIR) not in sys.path:
    sys.path.insert(0, str(HUB_DIR))

from hub_models import CandidateData, HubState
from hub_scanner import HubScanner
from hub_dashboard import HubDashboard


def create_demo_candidates():
    """Crea candidatos de demostración."""
    now = datetime.now(tz=timezone.utc)

    # STRAT-A candidates (Consolidation)
    strat_a = [
        CandidateData(
            asset="EURUSD",
            direction="call",
            score=92.5,
            payout=85,
            zone_ceiling=1.0755,
            zone_floor=1.0745,
            zone_age_min=8.2,
            pattern="Morning Star",
            pattern_strength=0.95,
            detected_at=now,
            entry_mode="rebound_floor",
        ),
        CandidateData(
            asset="GBPUSD",
            direction="put",
            score=87.3,
            payout=82,
            zone_ceiling=1.2820,
            zone_floor=1.2810,
            zone_age_min=15.5,
            pattern="Engulfing",
            pattern_strength=0.88,
            detected_at=now,
            entry_mode="breakout_below",
        ),
        CandidateData(
            asset="USDJPY",
            direction="call",
            score=79.1,
            payout=80,
            zone_ceiling=149.55,
            zone_floor=149.45,
            zone_age_min=22.3,
            pattern="Harami",
            pattern_strength=0.72,
            detected_at=now,
            entry_mode="rebound_ceiling",
        ),
        CandidateData(
            asset="AUDUSD",
            direction="put",
            score=76.8,
            payout=83,
            zone_ceiling=0.6685,
            zone_floor=0.6675,
            zone_age_min=10.1,
            pattern="Doji",
            pattern_strength=0.65,
            detected_at=now,
            entry_mode="breakout_below",
        ),
        CandidateData(
            asset="NZDUSD",
            direction="call",
            score=72.4,
            payout=81,
            zone_ceiling=0.6195,
            zone_floor=0.6185,
            zone_age_min=18.7,
            pattern="Three Line Strike",
            pattern_strength=0.58,
            detected_at=now,
            entry_mode="rebound_floor",
        ),
    ]

    # STRAT-B candidates (Wyckoff/Spring Sweep)
    strat_b = [
        CandidateData(
            asset="XAUUSD",
            direction="call",
            score=88.9,
            payout=84,
            zone_ceiling=2055.50,
            zone_floor=2050.00,
            zone_age_min=5.1,
            pattern="Spring Sweep",
            pattern_strength=0.91,
            detected_at=now,
            entry_mode="rebound_floor",
        ),
        CandidateData(
            asset="WTI",
            direction="put",
            score=81.2,
            payout=80,
            zone_ceiling=85.75,
            zone_floor=85.20,
            zone_age_min=12.3,
            pattern="Wyckoff Distribution",
            pattern_strength=0.79,
            detected_at=now,
            entry_mode="breakout_below",
        ),
        CandidateData(
            asset="BTCUSD",
            direction="call",
            score=75.6,
            payout=82,
            zone_ceiling=62000.00,
            zone_floor=61500.00,
            zone_age_min=7.8,
            pattern="Impulse",
            pattern_strength=0.68,
            detected_at=now,
            entry_mode="rebound_floor",
        ),
    ]

    return strat_a, strat_b


def main():
    print(
        "\n"
        "╔════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════╗\n"
        "║                    🎮 HUB DEMO — Professional Dashboard Showcase                                                                                                                   ║\n"
        "╚════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════╝\n"
    )

    # Initialize hub
    hub = HubScanner()

    # Get demo candidates
    strat_a_cands, strat_b_cands = create_demo_candidates()

    # Simulate multiple cycles
    for cycle_num in range(1, 4):
        # Vary candidates slightly each cycle
        cycle_strat_a = strat_a_cands[: 3 + (cycle_num % 2)]
        cycle_strat_b = strat_b_cands[: 2 + (cycle_num % 2)]

        # Record scan
        hub.record_scan_cycle(
            total_assets=18,
            strat_a_candidates=cycle_strat_a,
            strat_b_candidates=cycle_strat_b,
            balance=150.75 + (cycle_num * 5.0),
            cycle_id=cycle_num,
            cycle_ops=cycle_num * 2,
            cycle_wins=cycle_num,
            cycle_losses=max(0, cycle_num - 1),
        )

        # Get state and display
        state = hub.get_state()
        HubDashboard.display(state, balance=150.75 + (cycle_num * 5.0))

        if cycle_num < 3:
            print(f"\n⏳ Ciclo {cycle_num} mostrado. Esperando 2 segundos...\n")
            time.sleep(2)

    # Simulate active trade
    print("\n" + "=" * 180)
    print("📊 Simulando una entrada activa...\n")

    hub.record_entry(
        strategy="STRAT-A",
        asset="EURUSD",
        direction="call",
        duration_sec=30,
    )

    # Show with countdown (only 3 iterations for demo)
    for countdown in [30, 15, 0]:
        hub.update_active_trade_timer(float(countdown))
        state = hub.get_state()
        HubDashboard.display(state, balance=165.75)
        
        if countdown > 0:
            print(f"\n⏳ Entrada activa: {countdown}s restantes. Esperando 1 segundo...\n")
            time.sleep(1)

    # Close trade
    hub.close_active_trade()
    state = hub.get_state()
    HubDashboard.display(state, balance=165.75)

    print("\n" + "=" * 180)
    print("\n✅ Demo completado. Ahora el hub está listo para integración con consolidation_bot.\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⏹️  Demo interrumpido.\n")
        sys.exit(0)
