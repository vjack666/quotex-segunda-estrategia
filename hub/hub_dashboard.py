"""Dashboard visual del HUB para ejecucion en tiempo real."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from typing import List

from .hub_models import CandidateData, HubState


class HubDashboard:
    """Renderiza el HUB con dos paneles: STRAT-A y STRAT-B."""

    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"

    TOTAL_WIDTH = 180
    BOX_WIDTH = 89
    BOX_ROWS = 10
    _screen_initialized = False

    @classmethod
    def clear_screen(cls) -> None:
        os.system("cls" if os.name == "nt" else "clear")

    @classmethod
    def display_text(cls, text: str) -> None:
        """Refresca en sitio para evitar parpadeo por limpiar pantalla completa."""
        if not cls._screen_initialized:
            cls.clear_screen()
            cls._screen_initialized = True

        # Cursor al origen + limpiar desde cursor hasta el final.
        sys.stdout.write("\033[H\033[J")
        sys.stdout.write(text)
        if not text.endswith("\n"):
            sys.stdout.write("\n")
        sys.stdout.flush()

    @classmethod
    def _safe_trim(cls, text: str, width: int) -> str:
        if len(text) <= width:
            return text
        if width <= 3:
            return text[:width]
        return text[: width - 3] + "..."

    @classmethod
    def _box_top(cls, title: str, width: int) -> str:
        title_plain = cls._safe_trim(title, width - 4)
        raw = f" {title_plain} "
        left = max(0, (width - 2 - len(raw)) // 2)
        right = max(0, width - 2 - len(raw) - left)
        return f"╔{'═' * left}{cls.BOLD}{raw}{cls.RESET}{'═' * right}╗"

    @classmethod
    def _box_mid(cls, content: str, width: int) -> str:
        clipped = cls._safe_trim(content, width - 4)
        return f"║ {clipped.ljust(width - 4)} ║"

    @classmethod
    def _box_bottom(cls, width: int) -> str:
        return f"╚{'═' * (width - 2)}╝"

    @classmethod
    def _direction_tag(cls, direction: str) -> str:
        value = direction.upper()
        if value == "CALL":
            return f"{cls.GREEN}{value}{cls.RESET}"
        return f"{cls.RED}{value}{cls.RESET}"

    _ENTRY_MODE_ABBREV = {
        "rebound_floor":           "reb_floor",
        "rebound_ceiling":         "reb_ceil",
        "breakout_above":          "brk_above",
        "breakout_below":          "brk_below",
        "spring":                  "spring",
        "upthrust":                "upthrust",
        "wyckoff_early_spring":    "wyk_spring",
        "wyckoff_early_upthrust":  "wyk_upthr",
        "none":                    "—",
    }

    @classmethod
    def _abbrev_mode(cls, mode: str) -> str:
        return cls._ENTRY_MODE_ABBREV.get(mode, mode[:10])

    @classmethod
    def _format_strat_a_row(cls, rank: int, candidate: CandidateData) -> str:
        direction = cls._direction_tag(candidate.direction)
        mode = cls._abbrev_mode(candidate.entry_mode)
        return (
            f"{rank}. {candidate.asset:<10} {direction:<14} "
            f"S:{candidate.score:5.1f} P:{candidate.payout:>2}% "
            f"{mode:<10} {candidate.pattern[:14]}"
        )

    @classmethod
    def _format_strat_b_row(cls, rank: int, candidate: CandidateData) -> str:
        direction = cls._direction_tag(candidate.direction)
        conf = 0.0 if candidate.confidence is None else candidate.confidence * 100.0
        signal = cls._abbrev_mode(candidate.signal_type or candidate.entry_mode)
        return (
            f"{rank}. {candidate.asset:<10} {direction:<14} "
            f"C:{conf:5.1f}% P:{candidate.payout:>2}% "
            f"{signal:<10} {candidate.pattern[:16]}"
        )

    @classmethod
    def _render_strategy_box(
        cls,
        *,
        title: str,
        subtitle: str,
        candidates: List[CandidateData],
        formatter,
        width: int,
    ) -> List[str]:
        lines: List[str] = [cls._box_top(title, width)]
        lines.append(cls._box_mid(subtitle, width))
        lines.append(cls._box_mid("", width))

        if not candidates:
            lines.append(cls._box_mid("Sin candidatos en este escaneo", width))
        else:
            for idx, candidate in enumerate(candidates[:5], start=1):
                lines.append(cls._box_mid(formatter(idx, candidate), width))

        while len(lines) < cls.BOX_ROWS:
            lines.append(cls._box_mid("", width))

        lines.append(cls._box_bottom(width))
        return lines

    @classmethod
    def render_status_bar(cls, state: HubState, balance: float = 0.0) -> str:
        now = datetime.now(tz=timezone.utc).strftime("%H:%M:%S")
        cycle_id = 0 if state.last_scan is None else state.last_scan.cycle_id

        info = [
            f"{cls.CYAN}UTC {now}{cls.RESET}",
            f"{cls.MAGENTA}Scans {state.total_scans}{cls.RESET}",
            f"{cls.YELLOW}Cycle #{cycle_id}{cls.RESET}",
            f"{cls.BLUE}Balance ${balance:.2f}{cls.RESET}",
        ]

        if state.last_scan is not None:
            info.append(
                f"Ops {state.last_scan.cycle_ops} | "
                f"{cls.GREEN}{state.last_scan.cycle_wins}W{cls.RESET}/"
                f"{cls.RED}{state.last_scan.cycle_losses}L{cls.RESET}"
            )

        if state.active_trade_asset:
            seconds = int(state.active_trade_time_remaining_sec or 0)
            direction = (state.active_trade_direction or "").upper()
            info.append(
                f"{cls.RED}ACTIVA {state.active_trade_asset} {direction} {seconds}s{cls.RESET}"
            )

        return " | ".join(info)

    @classmethod
    def render_full_dashboard(cls, state: HubState, balance: float = 0.0) -> str:
        top = f"{cls.BOLD}{cls.CYAN}{'=' * cls.TOTAL_WIDTH}{cls.RESET}"
        lines: List[str] = [
            top,
            f"{cls.BOLD}{cls.MAGENTA}QUOTEX BOT HUB - LIVE{cls.RESET}",
            top,
            cls.render_status_bar(state, balance),
            "",
        ]

        left = cls._render_strategy_box(
            title="STRAT-A | CONSOLIDACION",
            subtitle="Score, payout, modo de entrada, patron",
            candidates=state.strat_a_watching,
            formatter=cls._format_strat_a_row,
            width=cls.BOX_WIDTH,
        )
        right = cls._render_strategy_box(
            title="STRAT-B | SPRING/WYCKOFF",
            subtitle="Confidence, payout, tipo de senal, patron",
            candidates=state.strat_b_watching,
            formatter=cls._format_strat_b_row,
            width=cls.BOX_WIDTH,
        )

        rows = max(len(left), len(right))
        for i in range(rows):
            left_row = left[i] if i < len(left) else " " * cls.BOX_WIDTH
            right_row = right[i] if i < len(right) else " " * cls.BOX_WIDTH
            lines.append(f"{left_row}  {right_row}")

        lines.extend(
            [
                "",
                f"{cls.DIM}CTRL+C para salir | Escaneo continuo | Candidatos se refrescan por ciclo{cls.RESET}",
                top,
            ]
        )
        return "\n".join(lines)

    @classmethod
    def display(cls, state: HubState, balance: float = 0.0) -> None:
        cls.display_text(cls.render_full_dashboard(state, balance))
