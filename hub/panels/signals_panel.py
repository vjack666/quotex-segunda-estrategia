from __future__ import annotations

from ..models import HubSnapshot


def build_signals(snapshot: HubSnapshot) -> list[str]:
    lines: list[str] = []

    lines.append("STRAT-B:")
    if snapshot.strat_b_notes:
        lines.extend([f"- {s}" for s in snapshot.strat_b_notes[-3:]])
    else:
        lines.append("- Sin lineas STRAT-B recientes")

    lines.append("")
    lines.append("OB / MA:")
    if snapshot.ob_notes:
        lines.extend([f"- OB {n}" for n in snapshot.ob_notes[-2:]])
    if snapshot.ma_notes:
        lines.extend([f"- MA {n}" for n in snapshot.ma_notes[-2:]])
    if not snapshot.ob_notes and not snapshot.ma_notes:
        lines.append("- Sin notas OB/MA")

    return lines
