from __future__ import annotations

from ..models import HubSnapshot


def build_alerts(snapshot: HubSnapshot) -> list[str]:
    lines: list[str] = []

    lines.append("Alertas:")
    if snapshot.alerts:
        lines.extend([f"- {a}" for a in snapshot.alerts[-4:]])
    else:
        lines.append("- Sin alertas capturadas")

    lines.append("")
    lines.append("Sistema:")
    if snapshot.system_notes:
        lines.extend([f"- {s}" for s in snapshot.system_notes[-4:]])
    else:
        lines.append("- Sin eventos de sistema")

    return lines
