from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class CandidateRow:
    asset: str
    direction: str
    payout: int
    score: float
    decision: str


@dataclass
class EntryRow:
    stage: str
    direction: str
    asset: str
    amount: float
    score: Optional[float]


@dataclass
class HubSnapshot:
    last_time: str = "--:--:--"
    level: str = "INFO"
    account_type: str = "N/A"
    balance: Optional[float] = None
    scan_no: Optional[int] = None
    assets_count: Optional[int] = None
    threshold: Optional[int] = None

    next_scan: str = "N/A"
    stats_line: str = "N/A"
    martin_line: str = "N/A"
    rejects_line: str = "N/A"

    candidates: List[CandidateRow] = field(default_factory=list)
    entries: List[EntryRow] = field(default_factory=list)

    ob_notes: List[str] = field(default_factory=list)
    ma_notes: List[str] = field(default_factory=list)
    strat_b_notes: List[str] = field(default_factory=list)
    alerts: List[str] = field(default_factory=list)
    system_notes: List[str] = field(default_factory=list)
