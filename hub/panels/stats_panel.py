from __future__ import annotations

from ..models import HubSnapshot


def build_stats(snapshot: HubSnapshot) -> list[str]:
    return [
        snapshot.stats_line,
        snapshot.martin_line,
        snapshot.rejects_line,
        "",
        "Siguiente ciclo:",
        snapshot.next_scan,
    ]
