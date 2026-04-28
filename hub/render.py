from __future__ import annotations

import shutil
from typing import List

from .box_utils import framed, hstack, render_box
from .models import HubSnapshot
from .panels.alerts_panel import build_alerts
from .panels.candidates_panel import build_candidates
from .panels.entries_panel import build_entries
from .panels.overview_panel import build_overview
from .panels.signals_panel import build_signals
from .panels.stats_panel import build_stats


def _row(box_specs: List[tuple[str, list[str], int, int]]) -> List[str]:
    boxes = [render_box(title, lines, width, height) for title, lines, width, height in box_specs]
    return hstack(boxes, gap=2)


def render_dashboard(snapshot: HubSnapshot) -> str:
    term_width = max(120, shutil.get_terminal_size(fallback=(160, 40)).columns)

    panel_w = (term_width - 4) // 3
    left_w = (term_width - 2) // 2
    right_w = term_width - 2 - left_w

    row1 = _row(
        [
            ("RESUMEN", build_overview(snapshot), panel_w, 11),
            ("ESTADISTICAS", build_stats(snapshot), panel_w, 11),
            ("SENALES", build_signals(snapshot), panel_w, 11),
        ]
    )

    row2 = _row(
        [
            ("CANDIDATOS", build_candidates(snapshot), left_w, 14),
            ("ENTRADAS", build_entries(snapshot), right_w, 14),
        ]
    )

    row3 = _row(
        [
            ("ALERTAS Y EVENTOS", build_alerts(snapshot), term_width, 12),
        ]
    )

    composed = row1 + [""] + row2 + [""] + row3
    return framed(" HUB PROFESIONAL (VISTA PREVIEW, NO EJECUTA ORDENES) ", composed, term_width + 2)
