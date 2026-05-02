"""Dashboard visual del HUB para ejecucion en tiempo real."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, List, Optional

from .hub_models import CandidateData, HubState

if TYPE_CHECKING:
    from rich.console import Console
    from rich.layout import Layout
    from rich.live import Live
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

try:
    from rich.console import Console as RichConsole
    from rich.layout import Layout as RichLayout
    from rich.live import Live as RichLive
    from rich.panel import Panel as RichPanel
    from rich.table import Table as RichTable
    from rich.text import Text as RichText
    _RICH_OK = True
except Exception:  # pragma: no cover
    RichConsole = None
    RichLayout = None
    RichLive = None
    RichPanel = None
    RichTable = None
    RichText = None
    _RICH_OK = False


def _require_console_class() -> type[Any]:
    if RichConsole is None:
        raise RuntimeError("rich.console no disponible")
    return RichConsole


def _require_layout_class() -> type[Any]:
    if RichLayout is None:
        raise RuntimeError("rich.layout no disponible")
    return RichLayout


def _require_live_class() -> type[Any]:
    if RichLive is None:
        raise RuntimeError("rich.live no disponible")
    return RichLive


def _require_panel_class() -> type[Any]:
    if RichPanel is None:
        raise RuntimeError("rich.panel no disponible")
    return RichPanel


def _require_table_class() -> type[Any]:
    if RichTable is None:
        raise RuntimeError("rich.table no disponible")
    return RichTable


def _require_text_class() -> type[Any]:
    if RichText is None:
        raise RuntimeError("rich.text no disponible")
    return RichText


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
    table_cls = _require_table_class()
    t = table_cls(show_header=True, header_style="bold cyan", box=None, padding=(0, 1), expand=True)
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
    table_cls = _require_table_class()
    t = table_cls(show_header=True, header_style="bold magenta", box=None, padding=(0, 1), expand=True)
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
    table_cls = _require_table_class()
    now = datetime.now(tz=timezone.utc).strftime("%H:%M:%S")
    cycle_id = 0 if state.last_scan is None else state.last_scan.cycle_id
    ops = state.last_scan.cycle_ops if state.last_scan else 0

    t = table_cls.grid(padding=(0, 2))
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


def _build_gale_panel(state: HubState) -> "Panel":
    """Construye el panel GALE WATCHER con el estado en tiempo real."""
    panel_cls = _require_panel_class()
    table_cls = _require_table_class()
    g = state.gale

    t = table_cls.grid(expand=True, padding=(0, 1))
    t.add_column(style="bold", min_width=14)
    t.add_column()

    if not g.active:
        t.add_row("Estado:", "[dim]Sin operación activa[/dim]")
        return panel_cls(t, title="[bold yellow]GALE WATCHER[/bold yellow]",
                 border_style="yellow", padding=(0, 1))

    # dirección
    dir_mu = _direction_markup(g.direction)

    # delta color
    delta = g.delta_pct
    if abs(delta) < 0.001:
        delta_mu = f"[dim]{delta:+.4f}%[/dim]"
    elif g.direction.upper() == "CALL":
        delta_mu = f"[bold green]{delta:+.4f}%[/bold green]" if delta >= 0 else f"[bold red]{delta:+.4f}%[/bold red]"
    else:  # PUT
        delta_mu = f"[bold green]{delta:+.4f}%[/bold green]" if delta <= 0 else f"[bold red]{delta:+.4f}%[/bold red]"

    # estado ganando/perdiendo
    if g.is_losing:
        status_mu = "[bold red]⚠  PERDIENDO[/bold red]"
    else:
        status_mu = "[bold green]✓  GANANDO[/bold green]"

    # tiempo restante
    secs = max(0.0, g.secs_remaining)
    mm, ss = divmod(int(secs), 60)
    time_mu = f"[bold]{mm:02d}:{ss:02d}[/bold]  [dim]/ {g.duration_sec}s[/dim]"

    # monto gale
    if g.gale_amount > 0:
        gale_mu = f"[bold yellow]${g.gale_amount:.2f}[/bold yellow]"
    else:
        gale_mu = "[dim]calculando...[/dim]"

    # estado disparo
    if g.gale_fired:
        fired_mu = (
            "[bold green]✔ ENVIADO[/bold green]" if g.gale_success
            else "[bold red]✗ ERROR[/bold red]"
        ) + (f"  [dim]#{g.gale_order_id}[/dim]" if g.gale_order_id else "")
    else:
        fired_mu = "[dim]En espera...[/dim]" if secs > 1 else "[bold yellow]⏳ Por disparar[/bold yellow]"

    t.add_row("Activo:",   f"{g.asset.upper()}  {dir_mu}  [dim]payout {g.payout}%[/dim]")
    t.add_row("Entrada:",  f"EP [bold]{g.entry_price:.5f}[/bold]  PX [bold]{g.current_price:.5f}[/bold]  {delta_mu}")
    t.add_row("Estado:",   status_mu)
    t.add_row("⏱ Tiempo:",  time_mu)
    t.add_row("Monto:",    f"Base ${g.amount_invested:.2f}  →  Gale {gale_mu}")
    t.add_row("Disparo:",  fired_mu)

    border = "red" if g.is_losing else "green"
    if g.gale_fired:
        border = "yellow"
    title_suffix = "  [bold red]● ACTIVO[/bold red]" if g.active else ""
    return panel_cls(t, title=f"[bold yellow]GALE WATCHER[/bold yellow]{title_suffix}",
                     border_style=border, padding=(0, 1))


def _build_layout(state: HubState, balance: float) -> "Layout":
    layout_cls = _require_layout_class()
    panel_cls = _require_panel_class()
    table_cls = _require_table_class()
    text_cls = _require_text_class()

    layout = layout_cls()
    layout.split_column(
        layout_cls(name="header", size=5),
        layout_cls(name="body",   ratio=1),
        layout_cls(name="gale",   size=8),
        layout_cls(name="footer", size=1),
    )

    layout["body"].split_row(layout_cls(name="strat_a"), layout_cls(name="strat_b"))

    layout["header"].update(
        panel_cls(
            _build_status_table(state, balance),
            title="[bold cyan]QUOTEX BOT HUB — LIVE[/bold cyan]",
            border_style="cyan",
        )
    )

    a_count = len(state.strat_a_watching)
    a_inner = table_cls.grid(expand=True)
    a_inner.add_column()
    a_inner.add_row(text_cls.from_markup("[dim]Score · Dir · Dist-trigger · Modo · Patron[/dim]"))
    a_inner.add_row(_build_strat_a_table(state.strat_a_watching))
    layout["strat_a"].update(
        panel_cls(
            a_inner,
            title=f"[bold cyan]STRAT-A | CONSOLIDACION[/bold cyan]  [dim]({a_count})[/dim]",
            border_style="cyan",
            padding=(0, 1),
        )
    )

    b_count = len(state.strat_b_watching)
    b_inner = table_cls.grid(expand=True)
    b_inner.add_column()
    b_inner.add_row(text_cls.from_markup("[dim]Conf · Dir · Dist-trigger · Señal · Patron[/dim]"))
    b_inner.add_row(_build_strat_b_table(state.strat_b_watching))
    layout["strat_b"].update(
        panel_cls(
            b_inner,
            title=f"[bold magenta]STRAT-B | SPRING/WYCKOFF[/bold magenta]  [dim]({b_count})[/dim]",
            border_style="magenta",
            padding=(0, 1),
        )
    )

    layout["gale"].update(_build_gale_panel(state))

    layout["footer"].update(
        text_cls(
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
            console_cls = _require_console_class()
            cls._console = console_cls(force_terminal=True, legacy_windows=False)
        assert cls._console is not None
        return cls._console

    @classmethod
    def _ensure_live(cls) -> "Live":
        if cls._live is None:
            live_cls = _require_live_class()
            text_cls = _require_text_class()
            cls._live = live_cls(
                text_cls(""),
                console=cls._get_console(),
                auto_refresh=False,
                refresh_per_second=8,
                transient=False,
                screen=False,
                vertical_overflow="crop",
                redirect_stdout=False,
                redirect_stderr=False,
            )
            assert cls._live is not None
            cls._live.start()
        assert cls._live is not None
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
    _last_line_count: int = 0
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

        new_lines = text.splitlines()
        previous_lines = cls._last_line_count

        sys.stdout.write("\033[H")
        sys.stdout.write(text)

        extra_lines = max(0, previous_lines - len(new_lines))
        if extra_lines:
            sys.stdout.write("\n" + "\n".join(" " * 120 for _ in range(extra_lines)))

        sys.stdout.write("\n")
        sys.stdout.flush()
        cls._last_text = text
        cls._last_line_count = len(new_lines)

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
        # ── GALE panel (fallback) ───────────────────────────────────────────
        g = state.gale
        lines.append(f"{_BOLD}{_YELLOW}--- GALE WATCHER ---{_RESET}")
        if not g.active:
            lines.append(f"  {_DIM}Sin operación activa{_RESET}")
        else:
            dir_color = _GREEN if g.direction.upper() == "CALL" else _RED
            status = f"{_RED}⚠ PERDIENDO{_RESET}" if g.is_losing else f"{_GREEN}✓ GANANDO{_RESET}"
            secs = max(0.0, g.secs_remaining)
            mm, ss = divmod(int(secs), 60)
            fired = (
                f"{_GREEN}✔ ENVIADO{_RESET}" if g.gale_fired and g.gale_success
                else (f"{_RED}✗ ERROR{_RESET}" if g.gale_fired
                      else f"{_DIM}En espera{_RESET}")
            )
            lines.append(
                f"  {g.asset.upper()} {dir_color}{g.direction.upper()}{_RESET}"
                f"  EP:{g.entry_price:.5f}  PX:{g.current_price:.5f}"
                f"  {g.delta_pct:+.4f}%  {status}"
            )
            lines.append(
                f"  ⏱ {mm:02d}:{ss:02d}  Base:${g.amount_invested:.2f}"
                f"  Gale:{_YELLOW}${g.gale_amount:.2f}{_RESET}  Disparo:{fired}"
            )
        lines.append("")
        lines.append(f"{_DIM}CTRL+C para salir{_RESET}")
        return "\n".join(lines)
