from __future__ import annotations

import re
from typing import Iterable

from .models import CandidateRow, EntryRow, HubSnapshot


LOG_RE = re.compile(r"^(?P<time>\d{2}:\d{2}:\d{2}) \[(?P<lvl>[A-Z]+)\] (?P<msg>.*)$")
SCAN_RE = re.compile(r"SCAN\s+#(?P<scan>\d+)\s+\|\s+(?P<assets>\d+)\s+activos")
BAL_RE = re.compile(r"Balance\s+(?P<acc>[A-Z]+):\s+(?P<bal>\d+(?:\.\d+)?)\s+USD")
THRESH_RE = re.compile(r"Umbral\s+din[aá]mico\s+sesi[oó]n=(?P<t>\d+)", re.IGNORECASE)
ENTRY_RE = re.compile(
    r"ENTRADA\[(?P<stage>[^\]]+)\]\s+(?P<dir>[A-Z]+)\s+(?P<asset>\S+)\s+\$(?P<amount>\d+(?:\.\d+)?)"
    r"(?:.*score=(?P<score>\d+(?:\.\d+)?))?",
)
CANDIDATE_RE = re.compile(
    r"^\s*[✅❌]\s+(?P<asset>\S+)\s+\[(?P<payout>\d+)%\]\s+(?P<dir>CALL|PUT).*?score=(?P<score>\d+(?:\.\d+)?)/100.*?→\s+(?P<decision>ACEPTADO|RECHAZADO)"
)


class HubLogParser:
    def __init__(self) -> None:
        self.snapshot = HubSnapshot()

    def parse_lines(self, lines: Iterable[str]) -> HubSnapshot:
        for raw in lines:
            line = raw.rstrip("\n")
            m = LOG_RE.match(line)
            if not m:
                continue

            msg = m.group("msg")
            self.snapshot.last_time = m.group("time")
            self.snapshot.level = m.group("lvl")

            self._consume_message(msg)

        return self.snapshot

    def _push_unique(self, bucket: list[str], value: str, max_items: int = 6) -> None:
        if not value:
            return
        if value in bucket:
            return
        bucket.append(value)
        if len(bucket) > max_items:
            del bucket[0 : len(bucket) - max_items]

    def _consume_message(self, msg: str) -> None:
        scan_m = SCAN_RE.search(msg)
        if scan_m:
            self.snapshot.scan_no = int(scan_m.group("scan"))
            self.snapshot.assets_count = int(scan_m.group("assets"))

        bal_m = BAL_RE.search(msg)
        if bal_m:
            self.snapshot.account_type = bal_m.group("acc")
            self.snapshot.balance = float(bal_m.group("bal"))

        thr_m = THRESH_RE.search(msg)
        if thr_m:
            self.snapshot.threshold = int(thr_m.group("t"))

        if "Próximo escaneo en" in msg or "Proximo escaneo en" in msg:
            self.snapshot.next_scan = msg

        if "STATS |" in msg:
            self.snapshot.stats_line = msg
        if "MARTIN |" in msg:
            self.snapshot.martin_line = msg
        if "RECHAZOS |" in msg:
            self.snapshot.rejects_line = msg

        entry_m = ENTRY_RE.search(msg)
        if entry_m:
            score_raw = entry_m.group("score")
            self.snapshot.entries.append(
                EntryRow(
                    stage=entry_m.group("stage"),
                    direction=entry_m.group("dir"),
                    asset=entry_m.group("asset"),
                    amount=float(entry_m.group("amount")),
                    score=float(score_raw) if score_raw is not None else None,
                )
            )
            self.snapshot.entries = self.snapshot.entries[-8:]

        cand_m = CANDIDATE_RE.match(msg)
        if cand_m:
            self.snapshot.candidates.append(
                CandidateRow(
                    asset=cand_m.group("asset"),
                    direction=cand_m.group("dir"),
                    payout=int(cand_m.group("payout")),
                    score=float(cand_m.group("score")),
                    decision=cand_m.group("decision"),
                )
            )
            self.snapshot.candidates = self.snapshot.candidates[-12:]

        if "[OB]" in msg:
            self._push_unique(self.snapshot.ob_notes, msg.replace("[OB]", "").strip(), max_items=5)
        if "[MA]" in msg:
            self._push_unique(self.snapshot.ma_notes, msg.replace("[MA]", "").strip(), max_items=5)
        if "[STRAT-B]" in msg:
            self._push_unique(self.snapshot.strat_b_notes, msg.strip(), max_items=6)

        if "contaminado" in msg.lower() or "[WARNING]" in msg or "[ERROR]" in msg:
            self._push_unique(self.snapshot.alerts, msg.strip(), max_items=8)

        if "Bot detenido" in msg or "Conectado" in msg or "Sin señales este ciclo" in msg:
            self._push_unique(self.snapshot.system_notes, msg.strip(), max_items=8)
