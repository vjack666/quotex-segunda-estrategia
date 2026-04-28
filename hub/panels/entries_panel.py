from __future__ import annotations

from ..models import HubSnapshot


def build_entries(snapshot: HubSnapshot) -> list[str]:
    if not snapshot.entries:
        return ["Sin entradas recientes en el log."]

    lines = ["Stage    Dir   Asset         Amount   Score"]
    lines.append("--------------------------------------------")
    for e in snapshot.entries[-10:]:
        score_txt = "N/A" if e.score is None else f"{e.score:.1f}"
        lines.append(
            f"{e.stage[:7].ljust(7)}  {e.direction[:4].ljust(4)}  {e.asset[:12].ljust(12)}  ${e.amount:6.2f}   {score_txt}"
        )
    return lines
