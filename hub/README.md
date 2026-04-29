# 🤖 Professional HUB — QUOTEX Bot Dashboard

## Overview

The HUB is a professional dashboard system for displaying trading activity across two parallel strategies:
- **STRAT-A**: Consolidation detection (5-minute candles) with rebound/breakout entries
- **STRAT-B**: Spring Sweep / Wyckoff patterns (1-minute candles) for early signals

The dashboard renders two responsive quadrants side-by-side with:
- Top 5 candidates per strategy
- Real-time scoring and confidence metrics
- Active trade timer countdown
- Global cycle statistics (scans, wins/losses, balance)

## Architecture

### hub_models.py
Data structures for hub state management:
- **CandidateData**: Individual trading candidate with score, payout, pattern, etc.
- **HubScanSnapshot**: Complete scan cycle snapshot with candidates list
- **HubState**: Global hub state tracking active trades and candidate history

### hub_scanner.py
State management for continuous scanning:
- **HubScanner** class: Manages candidate tracking and active trades
- Maintains top 5 candidates per strategy across scans
- Records entry/exit events and active trade timers
- Independent of bot—can be extended for real-time data feeds

### hub_dashboard.py
Professional terminal rendering:
- **HubDashboard** class: Box drawing and ANSI color rendering
- Two side-by-side quadrants (87 chars × ~15 lines each)
- Status bar with scan count, balance, cycle metrics
- Supports Windows 10+ terminal with ANSI color codes
- Methods:
  - `render_full_dashboard()`: Complete dashboard
  - `render_strategy_box()`: Individual strategy quadrant
  - `display()`: Clear screen and render

## Integration Pattern

### Current Status
- ✅ Hub modules created and compiled
- ✅ main.py refactored to support hub imports
- 🔄 Integration with bot scan loop pending

### How to Integrate

**Option 1: Direct Integration (Recommended)**
Modify `consolidation_bot.py` to expose scan results:

```python
# In ConsolidationBot.scan_all() after collecting candidates:
from hub.hub_models import CandidateData, HubState
from hub.hub_scanner import HubScanner
from hub.hub_dashboard import HubDashboard

# Create hub instance (once, in __init__):
self.hub = HubScanner()

# After scan completes, update hub:
strat_a_list = [CandidateData(...) for c in self.candidates_strat_a]
strat_b_list = [CandidateData(...) for c in self.candidates_strat_b]

self.hub.record_scan_cycle(
    total_assets=len(self.otc_assets),
    strat_a_candidates=strat_a_list,
    strat_b_candidates=strat_b_list,
    balance=self.current_balance,
    cycle_id=self.cycle_id,
    cycle_ops=self.cycle_operations,
    cycle_wins=self.cycle_wins,
    cycle_losses=self.cycle_losses,
)

# In main loop after bot.scan_all():
hub_state = self.hub.get_state()
HubDashboard.display(hub_state, balance=self.current_balance)
```

**Option 2: Wrapper Loop (Alternative)**
Create a wrapper in main.py that calls bot methods directly:

```python
# Instead of cb.main(), implement custom loop:
bot = ConsolidationBot(...)
hub = HubScanner()

while True:
    await bot.scan_all()
    # Convert bot candidates to hub format
    # hub.record_scan_cycle(...)
    # HubDashboard.display(hub.get_state(), bot.current_balance)
```

## Usage Example

### Display a Dashboard
```python
from hub.hub_models import CandidateData, HubState, HubScanSnapshot
from hub.hub_scanner import HubScanner
from hub.hub_dashboard import HubDashboard
from datetime import datetime, timezone

# Create scanner
hub = HubScanner()

# Create some candidate data
cand_a = CandidateData(
    asset="EURUSD",
    direction="call",
    score=87.5,
    payout=85,
    zone_ceiling=1.0750,
    zone_floor=1.0745,
    zone_age_min=12.3,
    pattern="Engulfing",
    pattern_strength=0.92,
    detected_at=datetime.now(tz=timezone.utc),
    entry_mode="rebound_floor",
)

# Update hub
hub.record_scan_cycle(
    total_assets=18,
    strat_a_candidates=[cand_a],
    strat_b_candidates=[],
    balance=150.50,
    cycle_id=5,
    cycle_ops=2,
    cycle_wins=1,
    cycle_losses=1,
)

# Render
HubDashboard.display(hub.get_state(), balance=150.50)
```

### Output Example
```
╔════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════╗
║                         🤖 QUOTEX BOT — INICIALIZANDO — Professional Trading Hub                                                                                                          ║
╚════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════╝

⏰ 14:32:45 | Scans: 42 | Cycle: #5 | Balance: $150.50 | Cycle: 2 ops, 1W/1L

╔═══════════════════════════════════════════════════╦═══════════════════════════════════════════════════╗
║ STRAT-A — Top Candidatos                          ║ STRAT-B (Wyckoff) — Top Candidatos               ║
╠═══════════════════════════════════════════════════╬═══════════════════════════════════════════════════╣
║                                                   ║                                                   ║
║  1. EURUSD     CALL [██████████] 87.5/100 [85%]  ║  No hay candidatos en este escaneo                ║
║  Engulfing                                        ║                                                   ║
║                                                   ║                                                   ║
╚═══════════════════════════════════════════════════╩═══════════════════════════════════════════════════╝

Press CTRL+C to stop | Scan every 60s | Orders 30s duration
```

## Features

### Professional Design
- ✅ Box drawing characters for clean borders
- ✅ ANSI color coding:
  - 🟢 Green: CALL direction, successful metrics
  - 🔴 Red: PUT direction, losses
  - 🔵 Cyan: Headers, timestamps
  - 🟡 Yellow: Cycle/scan info
- ✅ Responsive layout (adapts to terminal width)
- ✅ No flicker—clean redraws on each cycle

### Real-Time Tracking
- ✅ Continuous candidate monitoring
- ✅ Active trade timer countdown
- ✅ Cycle statistics (ops, wins/losses, balance)
- ✅ Per-candidate scoring breakdown

### Independent from Bot
- Hub state is completely independent
- Can be extended with:
  - WebSocket feeds for live market data
  - REST API for remote monitoring
  - Historical dashboard recording
  - Candidate persistence across bot restarts

## Future Enhancements

1. **Live Integration with ConsolidationBot**
   - Hook scan results directly to hub rendering
   - Real-time candidate updates on each scan

2. **Advanced Filtering**
   - Filter candidates by score range, payout, age
   - Sort by different metrics (confidence, payout, age)

3. **Entry History**
   - Show last 10 entries (won/lost)
   - Quick-lookup of historical performance per asset

4. **Remote Monitoring**
   - REST API endpoint for hub state
   - Web dashboard for remote viewing
   - WebSocket for real-time updates

5. **Data Persistence**
   - SQLite storage of hub snapshots
   - Historical analysis and backtesting
   - Performance reports per strategy

## File Structure

```
hub/
├── __init__.py              # Package exports
├── hub_models.py            # Data structures (CandidateData, HubState, HubScanSnapshot)
├── hub_scanner.py           # State management (HubScanner class)
├── hub_dashboard.py         # Visual rendering (HubDashboard class)
└── README.md                # This file
```

## License & Credits

Part of QUOTEX Bot trading system.
- Consolidation detection: STRAT-A
- Spring Sweep/Wyckoff: STRAT-B
- Professional HUB: Multi-strategy dashboard

---

**Next Steps:**
1. Integrate hub with consolidation_bot scan results
2. Test full rendering with real candidate data
3. Add WebSocket feed for live market updates
4. Extend to remote web dashboard
