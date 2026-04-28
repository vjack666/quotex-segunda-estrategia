from __future__ import annotations

from ..models import HubSnapshot


def build_candidates(snapshot: HubSnapshot) -> list[str]:
    if not snapshot.candidates:
        return ["No hay candidatos parseados en el rango seleccionado."]

    lines = ["Asset         Dir  Pay  Score  Decision"]
    lines.append("----------------------------------------")
    for c in sorted(snapshot.candidates, key=lambda x: x.score, reverse=True)[:10]:
        lines.append(
            f"{c.asset[:12].ljust(12)}  {c.direction.ljust(4)} {str(c.payout).rjust(3)}%  {c.score:5.1f}  {c.decision}"
        )
    return lines
