"""Dashboard visual del HUB para ejecucion en tiempo real."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from typing import List, Optional

from .hub_models import CandidateData, HubState

try:
    from rich.console import Console
    from rich.layout import Layout
    from rich.live import Live
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    _RICH_OK = True
except Exception:  # pragma: no cover
    Console = None  # type: ignore[assignment]
    Layout = None   # type: ignore[assignment]
    Live = None     # type: ignore[assignment]
    Panel = None    # type: ignore[assignment]
    Table = None    # type: ignore[assignment]
    Text = None     # type: ignore[assignment]
    _RICH_OK = False


# ── colores ANSI (fallback y compat) ─────────────────────────────────────────
_RESET   = "\033[0m"
_BOLD    = "\033[1m"
_DIM     = "\033[2m"
_CYAN    = "\033[96m"
_GREEN   = "\033[92m"
_YELLOW  = "\033[93m"
_RED     = "\033[91m"
_BLUE    = "\033[94m"
_MAGENTA = "\033[95m"


# ── helpers Rich markup ───────────────────────────────────────────────────────

def _direction_markup(direction: str) -> str:
    d = direction.upper()
    return f"[bold green]{d}[/bold green]" if d == "CALL" else f"[bold red]{d}[/bold red]"


def _dist_markup(dist_pct: Optional[float]) -> str:
    """Color según cercanía al trigger: verde ≤0.10%, amarillo ≤0.30%, dim si lejos."""
    if dist_pct is None:
        return "[dim]  --  [/dim]"
    pct = dist_pct * 100.0
    if pct <= 0.10:
        return f"[bold green]{pct:.2f}%[/bold green]"
    if pct <= 0.30:
        return f"[yellow]{pct:.2f}%[/yellow]"
    return f"[dim]{pct:.2f}%[/dim]"


_ENTRY_ABBREV = {
    "rebound_floor":          "reb_floor",
    "rebound_ceiling":        "reb_ceil",
    "breakout_above":         "brk_above",
    "breakout_below":         "brk_below",
    "spring":                 "spring",
    "upthrust":               "upthrust",
    "wyckoff_early_spring":   "wyk_spring",
    "wyckoff_early_upthrust": "wyk_upthr",
    "none":                   "—",
}


def _abbrev(mode: str) -> str:
    return _ENTRY_ABBREV.get(mode, mode[:10])


# ── tablas Rich ───────────────────────────────────────────────────────────────

def _build_strat_a_table(candidates: List[CandidateData]) -> "Table":
    t = Table(show_header=True, header_style="bold cyan", box=None, padding=(0, 1), expand=True)
    t.add_column("#",      width=2,  justify="right")
    t.add_column("Activo", width=14, no_wrap=True)
    t.add_column("Dir",    width=6)
    t.add_column("Score",  width=6,  justify="right")
    t.add_column("P%",     width=4,  justify="right")
    t.add_column("Dist",   width=7,  justify="right")
    t.add_column("Modo",   width=11, no_wrap=True)
    t.add_column("Patron", min_width=12)

    if not candidates:
        t.add_row("[dim]—[/dim]", "[dim]Sin candidatos en este escaneo[/dim]",
                  "", "", "", "", "", "")
        return t

    for i, c in enumerate(candidates[:5], 1):
        s_col = "green" if c.score >= 65 else "yellow" if c.score >= 50 else "red"
        p_col = "green" if c.payout >= 80 else "yellow" if c.payout >= 70 else "red"
        t.add_row(
            str(i),
            f"[bold]{c.asset}[/bold]",
            _direction_markup(c.direction),
            f"[{s_col}]{c.score:.1f}[/{s_col}]",
            f"[{p_col}]{c.payout}[/{p_col}]",
            _dist_markup(c.dist_pct),
            f"[dim]{_abbrev(c.entry_mode)}[/dim]",
            f"[dim]{c.pattern[:18]}[/dim]",
        )
    return t


def _build_strat_b_table(candidates: List[CandidateData]) -> "Table":
    t = Table(show_header=True, header_style="bold magenta", box=None, padding=(0, 1), expand=True)
    t.add_column("#",      width=2,  justify="right")
    t.add_column("Activo", width=14, no_wrap=True)
    t.add_column("Dir",    width=6)
    t.add_column("Conf%",  width=6,  justify="right")
    t.add_column("P%",     width=4,  justify="right")
    t.add_column("Dist",   width=7,  justify="right")
    t.add_column("Señal",  width=11, no_wrap=True)
    t.add_column("Patron", min_width=12)

    if not candidates:
        t.add_row("[dim]—[/dim]", "[dim]Sin candidatos en este escaneo[/dim]",
                  "", "", "", "", "", "")
        return t

    for i, c in enumerate(candidates[:5], 1):
        conf  = 0.0 if c.confidence is None else c.confidence * 100.0
        c_col = "green" if conf >= 70 else "yellow" if conf >= 60 else "red"
        p_col = "green" if c.payout >= 80 else "yellow" if c.payout >= 70 else "red"
        signal = _abbrev(c.signal_type or c.entry_mode or "none")
        t.add_row(
            str(i),
            f"[bold]{c.asset}[/bold]",
            _direction_markup(c.direction),
            f"[{c_col}]{conf:.1f}[/{c_col}]",
            f"[{p_col}]{c.payout}[/{p_col}]",
            _dist_markup(c.dist_pct),
            f"[dim]{signal}[/dim]",
            f"[dim]{c.pattern[:18]}[/dim]",
        )
    return t


def _build_status_table(state: HubState, balance: float) -> "Table":
    now = datetime.now(tz=timezone.utc).strftime("%H:%M:%S")
    cycle_id = 0 if state.last_scan is None else state.last_scan.cycle_id
    ops = state.last_scan.cycle_ops if state.last_scan else 0

    t = Table.grid(padding=(0, 2))
    t.add_column(); t.add_column(); t.add_column(); t.add_column(); t.add_column()
    t.add_row(
        f"[cyan]UTC {now}[/cyan]",
        f"[magenta]Scans {state.total_scans}[/magenta]",
        f"[yellow]Ciclo #{cycle_id}[/yellow]",
        f"[blue]Balance ${balance:.2f}[/blue]",
        f"Ops [cyan]{ops}[/cyan]  |  "
        f"[bold green]{state.live_wins}W[/bold green]"
        f"[dim]/[/dim]"
        f"[bold red]{state.live_losses}L[/bold red]",
    )

    if state.active_trade_asset:
        secs = int(state.active_trade_time_remaining_sec or 0)
        direction = (state.active_trade_direction or "").upper()
        row = f"[bold red]▶ ACTIVA {state.active_trade_asset} {direction} {secs}s[/bold red]"
        if state.active_trade_entry_price is not None:
            row += f"  EP {state.active_trade_entry_price:.5f}"
        if state.active_trade_current_price is not None:
            row += f"  PX {state.active_trade_current_price:.5f}"
        if state.active_trade_delta_pct is not None:
            dc = "green" if state.active_trade_delta_pct >= 0 else "red"
            row += f"  [{dc}]Δ {state.active_trade_delta_pct:+.2f}%[/{dc}]"
        t.add_row(row, "", "", "", "")

    elif state.last_trade_outcome is not None:
        outcome = state.last_trade_outcome
        asset   = state.last_trade_asset or "?"
        profit  = state.last_trade_profit or 0.0
        if outcome == "WIN":
            result = f"[bold green]✔ LAST WIN  {asset}  +${profit:.2f}[/bold green]"
        elif outcome == "LOSS":
            result = f"[bold red]✘ LAST LOSS  {asset}  -${abs(profit):.2f}[/bold red]"
        else:
            result = f"[yellow]» LAST {outcome}  {asset}[/yellow]"
        t.add_row(result, "", "", "", "")

    return t


def _build_layout(state: HubState, balance: float) -> "Layout":
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=5),
        Layout(name="body",   ratio=1),
        Layout(name="footer", size=1),
    )

    layout["body"].split_row(Layout(name="strat_a"), Layout(name="strat_b"))

    layout["header"].update(
        Panel(
            _build_status_table(state, balance),
            title="[bold cyan]QUOTEX BOT HUB — LIVE[/bold cyan]",
            border_style="cyan",
        )
    )

    a_count = len(state.strat_a_watching)
    a_inner = Table.grid(expand=True)
    a_inner.add_column()
    a_inner.add_row(Text.from_markup("[dim]Score · Dir · Dist-trigger · Modo · Patron[/dim]"))
    a_inner.add_row(_build_strat_a_table(state.strat_a_watching))
    layout["strat_a"].update(
        Panel(
            a_inner,
            title=f"[bold cyan]STRAT-A | CONSOLIDACION[/bold cyan]  [dim]({a_count})[/dim]",
            border_style="cyan",
            padding=(0, 1),
        )
    )

    b_count = len(state.strat_b_watching)
    b_inner = Table.grid(expand=True)
    b_inner.add_column()
    b_inner.add_row(Text.from_markup("[dim]Conf · Dir · Dist-trigger · Señal · Patron[/dim]"))
    b_inner.add_row(_build_strat_b_table(state.strat_b_watching))
    layout["strat_b"].update(
        Panel(
            b_inner,
            title=f"[bold magenta]STRAT-B | SPRING/WYCKOFF[/bold magenta]  [dim]({b_count})[/dim]",
            border_style="magenta",
            padding=(0, 1),
        )
    )

    layout["footer"].update(
        Text(
            "CTRL+C para salir  |  Escaneo continuo  |  "
            "● verde=≤0.10%  ● amarillo=≤0.30%  ● dim=lejos del trigger",
            justify="center",
            style="dim",
        )
    )

    return layout


# ── clase pública ─────────────────────────────────────────────────────────────

class HubDashboard:
    """Renderiza el HUB con Rich Layout (dos paneles lado a lado)."""

    # Compat: exponer constantes ANSI que main.py u otro código puede referenciar
    RESET   = _RESET
    BOLD    = _BOLD
    DIM     = _DIM
    CYAN    = _CYAN
    GREEN   = _GREEN
    YELLOW  = _YELLOW
    RED     = _RED
    BLUE    = _BLUE
    MAGENTA = _MAGENTA

    TOTAL_WIDTH = 180
    _console: Optional["Console"] = None
    _live: Optional["Live"] = None

    @classmethod
    def _get_console(cls) -> "Console":
        if cls._console is None:
            cls._console = Console(force_terminal=True, legacy_windows=False)
        return cls._console

    @classmethod
    def _ensure_live(cls) -> "Live":
        if cls._live is None:
            cls._live = Live(
                Text(""),
                console=cls._get_console(),
                auto_refresh=False,
                refresh_per_second=8,
                transient=False,
                screen=False,
                vertical_overflow="crop",
                redirect_stdout=False,
                redirect_stderr=False,
            )
            cls._live.start()
        return cls._live

    @classmethod
    def shutdown(cls) -> None:
        """Cierra el render live limpiamente."""
        if cls._live is not None:
            try:
                cls._live.stop()
            except Exception:
                pass
        cls._live = None
        cls._console = None

    @classmethod
    def display(cls, state: HubState, balance: float = 0.0) -> None:
        """Renderiza o actualiza el dashboard en el terminal."""
        if not _RICH_OK:
            cls._display_fallback(state, balance)
            return
        try:
            renderable = _build_layout(state, balance)
            live = cls._ensure_live()
            live.update(renderable, refresh=True)
        except Exception:
            cls._display_fallback(state, balance)

    # ── fallback ANSI ─────────────────────────────────────────────────────────
    _last_text: str = ""
    _screen_initialized: bool = False

    @classmethod
    def _display_fallback(cls, state: HubState, balance: float) -> None:
        text = cls._render_fallback(state, balance)
        if text == cls._last_text:
            return
        if not cls._screen_initialized:
            import os as _os
            _os.system("cls" if _os.name == "nt" else "clear")
            cls._screen_initialized = True
        sys.stdout.write("\033[H\033[J" + text + "\n")
        sys.stdout.flush()
        cls._last_text = text

    @classmethod
    def _render_fallback(cls, state: HubState, balance: float) -> str:
        now = datetime.now(tz=timezone.utc).strftime("%H:%M:%S")
        lines = [
            f"{_BOLD}{_CYAN}{'=' * 80}{_RESET}",
            f"{_BOLD}{_MAGENTA}QUOTEX BOT HUB - LIVE{_RESET}",
            f"UTC {now} | Scans {state.total_scans} | Balance ${balance:.2f} | "
            f"{_GREEN}{state.live_wins}W{_RESET}/{_RED}{state.live_losses}L{_RESET}",
            "",
        ]
        for label, candidates in [("STRAT-A", state.strat_a_watching),
                                   ("STRAT-B", state.strat_b_watching)]:
            lines.append(f"{_BOLD}--- {label} ---{_RESET}")
            if not candidates:
                lines.append("  Sin candidatos en este escaneo")
            else:
                for i, c in enumerate(candidates[:5], 1):
                    dist = f"{c.dist_pct * 100:.2f}%" if c.dist_pct is not None else "--"
                    lines.append(
                        f"  {i}. {c.asset:<12} {c.direction:<4} "
                        f"S:{c.score:.1f} P:{c.payout}% Dist:{dist}"
                    )
            lines.append("")
        lines.append(f"{_DIM}CTRL+C para salir{_RESET}")
        return "\n".join(lines)
