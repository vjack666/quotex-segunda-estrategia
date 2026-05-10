"""Dashboard visual del HUB para ejecucion en tiempo real."""

from __future__ import annotations

import sys
import time
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, List, Optional

from .hub_models import CandidateData, CandleSnapshot, HubState, VipWindowData

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


def _enable_ansi_windows() -> bool:
    """Intenta habilitar ANSI en consola Windows. Retorna True si queda activo."""
    if os.name != "nt":
        return True
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint32()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
            kernel32.SetConsoleMode(handle, mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING)
            return True
    except Exception:
        pass
    return False

_LOG_TAIL_LINES = 6
_LOG_TAIL_MAX_BYTES = 64 * 1024
_LOG_RECENT_WINDOW_MIN = 20
_LOG_RECENT_WINDOW_SEC = _LOG_RECENT_WINDOW_MIN * 60
_BOT_LOG_DIR = Path(__file__).resolve().parent.parent / "data" / "logs" / "bot"

_LOG_CACHE_FILE: Optional[Path] = None
_LOG_CACHE_MTIME: float = -1.0
_LOG_CACHE_SIZE: int = -1
_LOG_CACHE_LINES: List[str] = []

_LOG_NOISE_PATTERNS = (
    "Traceback (most recent call last):",
    "raise KeyboardInterrupt()",
    "KeyboardInterrupt",
    "asyncio\\runners.py",
    "Task was destroyed but it is pending!",
    "ssl_Mutual_exclusion_write",
    "task: <Task cancelling",
    "coro=<main() running at",
    "send_websocket_request(data)",
    "site-packages\\pyquotex\\api.py\", line 421",
)


def _is_noise_trace_line(line: str) -> bool:
    txt = line.strip()
    if not txt:
        return False
    if txt.startswith("File \"") and ("asyncio\\runners.py" in txt or "site-packages\\pyquotex\\api.py" in txt):
        return True
    if txt.startswith("return self.send_websocket_request"):
        return True
    if txt.startswith("or self.state.ssl_Mutual_exclusion_write"):
        return True
    if txt.startswith("task: <Task cancelling"):
        return True
    # Fragmentos de caret/tilde que quedan de tracebacks multilinea en consola.
    if set(txt) <= {"^", "~"}:
        return True
    if set(txt) == {"^"}:
        return True
    return False


def _is_recent_log_line(line: str) -> bool:
    """True si la línea con prefijo HH:MM:SS cae dentro de la ventana reciente."""
    txt = line.strip()
    if len(txt) < 8:
        return True

    hhmmss = txt[:8]
    if not (hhmmss[2] == ":" and hhmmss[5] == ":"):
        return True

    try:
        hh = int(hhmmss[0:2])
        mm = int(hhmmss[3:5])
        ss = int(hhmmss[6:8])
        now = datetime.now()
        stamp = now.replace(hour=hh, minute=mm, second=ss, microsecond=0)

        # Si por desfase de reloj queda en "futuro", asumir día anterior.
        if stamp > now + timedelta(minutes=1):
            stamp = stamp - timedelta(days=1)

        return (now - stamp) <= timedelta(minutes=_LOG_RECENT_WINDOW_MIN)
    except Exception:
        return True


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


def _latest_bot_log_file() -> Optional[Path]:
    if not _BOT_LOG_DIR.exists():
        return None
    try:
        files = [p for p in _BOT_LOG_DIR.glob("consolidation_bot-*.log") if p.is_file()]
    except Exception:
        return None
    if not files:
        return None
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0]


def _read_tail_lines(path: Path, line_count: int) -> List[str]:
    """Lee las ultimas N lineas de forma eficiente sin cargar todo el archivo."""
    if line_count <= 0:
        return []
    try:
        with path.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            file_size = fh.tell()
            if file_size <= 0:
                return []

            to_read = min(file_size, _LOG_TAIL_MAX_BYTES)
            fh.seek(-to_read, os.SEEK_END)
            chunk = fh.read(to_read)

        text = chunk.decode("utf-8", errors="replace")
        lines = text.splitlines()
        return lines[-line_count:]
    except Exception:
        return []


def _live_log_lines() -> List[str]:
    """Retorna lineas de log cacheadas y actualizadas cuando el archivo cambia."""
    global _LOG_CACHE_FILE, _LOG_CACHE_MTIME, _LOG_CACHE_SIZE, _LOG_CACHE_LINES

    path = _latest_bot_log_file()
    if path is None:
        return ["(sin archivo de log en data/logs/bot)"]

    try:
        stat = path.stat()
        mtime = float(stat.st_mtime)
        size = int(stat.st_size)
    except Exception:
        return [f"(no se pudo leer metadata de {path.name})"]

    # Si el archivo no tuvo actividad reciente, evitar mostrar errores historicos.
    if (time.time() - mtime) > _LOG_RECENT_WINDOW_SEC:
        return ["(sin eventos recientes)"]

    if _LOG_CACHE_FILE != path:
        _LOG_CACHE_FILE = path
        _LOG_CACHE_MTIME = -1.0
        _LOG_CACHE_SIZE = -1

    if mtime != _LOG_CACHE_MTIME or size != _LOG_CACHE_SIZE:
        _LOG_CACHE_LINES = _read_tail_lines(path, _LOG_TAIL_LINES)
        _LOG_CACHE_MTIME = mtime
        _LOG_CACHE_SIZE = size

    if not _LOG_CACHE_LINES:
        return [f"({path.name} vacio)"]

    filtered: List[str] = []
    for ln in _LOG_CACHE_LINES:
        if any(pat in ln for pat in _LOG_NOISE_PATTERNS) or _is_noise_trace_line(ln):
            continue
        if not _is_recent_log_line(ln):
            continue
        filtered.append(ln if ln.strip() else " ")

    if not filtered:
        return ["(sin eventos nuevos; ruido Ctrl+C filtrado)"]

    return filtered


def _waiting_first_order(state: HubState) -> bool:
    """True cuando el sistema aun no tuvo una operacion real para mostrar."""
    return (
        not state.masaniello.active
        and state.active_trade_asset is None
        and state.last_trade_outcome is None
    )


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
    t.add_column("Sup",    width=10, justify="right")
    t.add_column("Res",    width=10, justify="right")
    t.add_column("Modo",   width=11, no_wrap=True)
    t.add_column("Patron", min_width=12)

    if not candidates:
        t.add_row("[dim]—[/dim]", "[dim]Sin candidatos en este escaneo[/dim]",
              "", "", "", "", "", "", "", "")
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
            f"[dim]{c.zone_floor:.5f}[/dim]",
            f"[dim]{c.zone_ceiling:.5f}[/dim]",
            f"[dim]{_abbrev(c.entry_mode)}[/dim]",
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
    freshness = max(0, int((datetime.now(tz=timezone.utc) - state.last_update).total_seconds()))
    t.add_row(
        f"[cyan]UTC {now}[/cyan]",
        f"[magenta]Scans {state.total_scans}[/magenta]",
        f"[yellow]Ciclo #{cycle_id}[/yellow]",
        f"[blue]Balance ${balance:.2f}[/blue]",
        f"Ops [cyan]{ops}[/cyan]  |  "
        f"[bold green]{state.live_wins}W[/bold green]"
        f"[dim]/[/dim]"
        f"[bold red]{state.live_losses}L[/bold red]  [dim]| act. {freshness}s[/dim]",
    )

    if state.active_trade_asset:
        secs = int(state.active_trade_time_remaining_sec or 0)
        direction = (state.active_trade_direction or "").upper()
        row = f"[bold red]OPERACION ACTIVA {state.active_trade_asset} {direction} {secs}s[/bold red]"
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
            result = f"[bold green]ULTIMO RESULTADO: WIN  {asset}  +${profit:.2f}[/bold green]"
        elif outcome == "LOSS":
            result = f"[bold red]ULTIMO RESULTADO: LOSS  {asset}  -${abs(profit):.2f}[/bold red]"
        else:
            result = f"[yellow]ULTIMO RESULTADO: {outcome}  {asset}[/yellow]"
        t.add_row(result, "", "", "", "")

    return t


def _build_gale_panel(state: HubState) -> "Panel":
    """Construye el panel MASANIELLO MANAGER con el estado en tiempo real."""
    panel_cls = _require_panel_class()
    table_cls = _require_table_class()
    m = state.masaniello

    t = table_cls.grid(expand=True, padding=(0, 1))
    t.add_column(style="bold", min_width=14)
    t.add_column()

    if not m.active:
        first_amount = m.next_amount if m.next_amount > 0 else (m.current_amount if m.current_amount > 0 else 1.01)
        wr = m.win_rate_pct
        if wr >= 60:
            wr_mu = f"[bold green]{wr:.0f}%[/bold green]"
        elif wr >= 50:
            wr_mu = f"[yellow]{wr:.0f}%[/yellow]"
        else:
            wr_mu = f"[bold red]{wr:.0f}%[/bold red]"

        t.add_row("Estado:", "[dim]Sin operación activa[/dim]")
        t.add_row("Ciclo:", f"#{m.cycle_num}  |  {m.trades_in_cycle}/{m.cycle_target_ops} ops  |  {m.wins_in_cycle}W/{m.losses_in_cycle}L")
        t.add_row("Tiempo:", "[dim]00:00[/dim]")
        t.add_row("Monto Actual:", f"[bold]${m.current_amount:.2f}[/bold]")
        t.add_row("Monto Próximo:", f"[bold yellow]${first_amount:.2f}[/bold yellow]")
        t.add_row("Secuencia:", f"[dim]{m.sequence or '-'}[/dim]")
        t.add_row("Win Rate:", wr_mu)
        t.add_row("P&L:", f"[bold]{'+' if m.total_pnl >= 0 else ''}{m.total_pnl:.2f}$[/bold]")
        t.add_row("Pérdida Diaria:", f"${m.daily_loss:.2f} / {'sin límite' if m.max_daily_loss >= 999999.0 else f'${m.max_daily_loss:.2f}'}")
        t.add_row("Base/Ciclo:", f"[bold]${m.reference_balance:.2f}[/bold]  |  [bold]{m.cycle_target_ops}/{m.cycle_target_wins}[/bold]")
        t.add_row("Config:", f"L3={m.multiplier}x  |  L5={m.commission_pct}%")
        return panel_cls(t, title="[bold cyan]MASANIELLO MANAGER[/bold cyan]",
                 border_style="cyan", padding=(0, 1))

    # dirección
    dir_mu = _direction_markup(m.direction)

    # delta color
    delta = m.delta_pct
    if abs(delta) < 0.001:
        delta_mu = f"[dim]{delta:+.4f}%[/dim]"
    elif m.direction.upper() == "CALL":
        delta_mu = f"[bold green]{delta:+.4f}%[/bold green]" if delta >= 0 else f"[bold red]{delta:+.4f}%[/bold red]"
    else:  # PUT
        delta_mu = f"[bold green]{delta:+.4f}%[/bold green]" if delta <= 0 else f"[bold red]{delta:+.4f}%[/bold red]"

    # tiempo restante
    drift = 0.0
    if m.updated_at > 0:
        drift = max(0.0, time.time() - m.updated_at)
    secs = max(0.0, m.secs_remaining - drift)
    mm, ss = divmod(int(secs), 60)
    time_mu = f"[bold]{mm:02d}:{ss:02d}[/bold]  [dim]/ {m.duration_sec}s[/dim]"

    # monto siguiente
    if m.next_amount > 0:
        next_mu = f"[bold yellow]${m.next_amount:.2f}[/bold yellow]"
    else:
        next_mu = "[dim]calculando...[/dim]"

    # win rate
    wr = m.win_rate_pct
    if wr >= 60:
        wr_mu = f"[bold green]{wr:.0f}%[/bold green]"
    elif wr >= 50:
        wr_mu = f"[yellow]{wr:.0f}%[/yellow]"
    else:
        wr_mu = f"[bold red]{wr:.0f}%[/bold red]"

    safety = str(m.safety_status or "OK").upper()
    if safety == "OK":
        safety_mu = "[bold green]OK[/bold green]"
    elif safety == "RIESGO":
        safety_mu = "[bold red]RIESGO[/bold red]"
    elif safety == "LIMITE":
        safety_mu = "[bold yellow]LIMITE[/bold yellow]"
    else:
        safety_mu = "[bold yellow]AVISO[/bold yellow]"

    t.add_row("Activo:",       f"{m.asset.upper()}  {dir_mu}  [dim]payout {m.payout}%[/dim]")
    t.add_row("Entrada:",      f"EP [bold]{m.entry_price:.5f}[/bold]  PX [bold]{m.current_price:.5f}[/bold]  {delta_mu}")
    t.add_row("Ciclo:",        f"#{m.cycle_num}  |  {m.trades_in_cycle}/{m.cycle_target_ops} ops  |  {m.wins_in_cycle}W/{m.losses_in_cycle}L")
    t.add_row("Tiempo:",       time_mu)
    t.add_row("Monto Actual:", f"[bold]${m.current_amount:.2f}[/bold]")
    t.add_row("Monto Próximo:", next_mu)
    t.add_row("Win Rate:",     wr_mu)
    t.add_row("P&L:",          f"[bold]{'+' if m.total_pnl >= 0 else ''}{m.total_pnl:.2f}$[/bold]")
    t.add_row("Pérdida Diaria:", f"${m.daily_loss:.2f} / {'sin límite' if m.max_daily_loss >= 999999.0 else f'${m.max_daily_loss:.2f}'}")
    t.add_row("Seguridad:",    safety_mu)
    t.add_row("Base/Ciclo:",   f"${m.reference_balance:.2f}  |  {m.cycle_target_ops}/{m.cycle_target_wins}")
    t.add_row("Config:",       f"L3={m.multiplier}x  |  L5={m.commission_pct}%")

    border = "red" if (m.max_daily_loss < 999999.0 and m.daily_loss >= m.max_daily_loss * 0.8) else "cyan"
    title_suffix = "  [bold red]● ACTIVO[/bold red]" if m.active else ""
    return panel_cls(t, title=f"[bold cyan]MASANIELLO MANAGER[/bold cyan]{title_suffix}",
                     border_style=border, padding=(0, 1))


def _build_logs_panel(state: HubState) -> "Panel":
    """Mini terminal: muestra tail en vivo del log principal del bot."""
    panel_cls = _require_panel_class()
    table_cls = _require_table_class()
    text_cls = _require_text_class()

    # Antes de la primera orden, mantener panel limpio para no confundir
    # con errores historicos de sesiones anteriores.
    if _waiting_first_order(state):
        lines = ["(en espera de primera operacion)"]
    else:
        lines = _live_log_lines()
    inner = table_cls.grid(expand=True)
    inner.add_column()

    for line in lines:
        inner.add_row(text_cls(line, style="dim", overflow="ellipsis", no_wrap=True))

    return panel_cls(
        inner,
        title="[bold white]EVENTOS RECIENTES[/bold white] [dim](log en vivo)[/dim]",
        border_style="white",
        padding=(0, 1),
    )


def _build_quick_levels_panel(state: HubState) -> "Panel":
    """Lista compacta para trazar niveles manualmente en la grafica."""
    panel_cls = _require_panel_class()
    table_cls = _require_table_class()

    all_candidates: List[CandidateData] = (
        list(state.strat_a_watching[:5])
    )

    # Priorizar candidatos mas cercanos al trigger y luego por score/conf.
    all_candidates.sort(
        key=lambda c: (
            9999.0 if c.dist_pct is None else c.dist_pct,
            -c.rank_value,
        )
    )

    t = table_cls.grid(expand=True, padding=(0, 1))
    t.add_column(style="bold", min_width=7)
    t.add_column(min_width=14)
    t.add_column(min_width=5)
    t.add_column(justify="right", min_width=10)
    t.add_column(justify="right", min_width=10)

    if not all_candidates:
        t.add_row("[dim]-[/dim]", "[dim]Sin niveles[/dim]", "", "", "")
    else:
        for c in all_candidates[:8]:
            strat = c.strategy.replace("STRAT-", "S")
            t.add_row(
                f"[cyan]{strat}[/cyan]",
                f"[bold]{c.asset}[/bold]",
                _direction_markup(c.direction),
                f"[dim]{c.zone_floor:.5f}[/dim]",
                f"[dim]{c.zone_ceiling:.5f}[/dim]",
            )

    return panel_cls(
        t,
        title="[bold white]NIVELES CLAVE[/bold white] [dim](Soporte / Resistencia)[/dim]",
        border_style="white",
        padding=(0, 1),
    )


def _build_vip_panel(state: HubState) -> "Panel":
    """Ventana VIP: candidatos casi listos para entrada."""
    panel_cls = _require_panel_class()
    table_cls = _require_table_class()

    vip_items: List[VipWindowData] = list(state.vip_windows[:5])
    t = table_cls.grid(expand=True)
    t.add_column("Act.", style="bold cyan", min_width=10)
    t.add_column("Dir", min_width=4)
    t.add_column("Score", justify="right", min_width=6)
    t.add_column("Faltan", justify="right", min_width=6)
    t.add_column("15m", min_width=28)
    t.add_column("5m", min_width=28)
    t.add_column("1m", min_width=28)

    if not vip_items:
        t.add_row("-", "-", "-", "-", "Sin VIP", "", "")
    else:
        for v in vip_items[:4]:
            dir_color = _GREEN if v.direction == "call" else _RED
            score_color = _GREEN if v.ready_to_execute else (_YELLOW if v.missing_conditions <= 3 else _RED)
            m15 = "N/D"
            if v.ma15_fast is not None and v.ma15_slow is not None:
                m15 = f"EMA10 {v.ma15_fast:.5f}\nEMA20 {v.ma15_slow:.5f}"
            m5 = "N/D"
            if v.ma5_fast is not None and v.ma5_slow is not None:
                m5 = f"EMA10 {v.ma5_fast:.5f}\nEMA20 {v.ma5_slow:.5f}"
            m1 = "N/D"
            if v.ma1_fast is not None and v.ma1_slow is not None:
                m1 = f"EMA10 {v.ma1_fast:.5f}\nEMA20 {v.ma1_slow:.5f}"

            head = f"{v.payout}% | {v.entry_mode}"
            tail = f"{v.candles_15m_count} velas 15m\nfaltan: {', '.join(v.missing_labels[:2]) or '0'}"
            t.add_row(
                v.asset,
                f"{dir_color}{v.direction.upper()}{_RESET}",
                f"{score_color}{v.score:.1f}{_RESET}",
                f"{v.missing_conditions}/{v.total_conditions}",
                f"{head}\n{tail}",
                m5,
                m1,
            )

    return panel_cls(
        t,
        title="[bold white]VIP LIBRARY[/bold white] [dim](candidatos casi listos)[/dim]",
        border_style="magenta",
        padding=(0, 1),
    )


def _build_layout(state: HubState, balance: float) -> "Layout":
    layout_cls = _require_layout_class()
    panel_cls = _require_panel_class()
    table_cls = _require_table_class()
    text_cls = _require_text_class()

    layout = layout_cls()
    layout.split_column(
        layout_cls(name="header", size=5),
        layout_cls(name="body",   ratio=1),
        layout_cls(name="vip",    size=11),
        layout_cls(name="levels", size=6),
        layout_cls(name="gale",   size=8),
        layout_cls(name="logs",   size=10),
        layout_cls(name="footer", size=1),
    )

    layout["body"].split_row(layout_cls(name="strat_a"))

    layout["header"].update(
        panel_cls(
            _build_status_table(state, balance),
            title="[bold cyan]QUOTEX OPERATIONS HUB[/bold cyan]",
            border_style="cyan",
        )
    )

    a_count = len(state.strat_a_watching)
    a_inner = table_cls.grid(expand=True)
    a_inner.add_column()
    a_inner.add_row(text_cls.from_markup("[dim]Score · Dir · Dist-trigger · Soporte/Resistencia · Modo · Patron[/dim]"))
    a_inner.add_row(_build_strat_a_table(state.strat_a_watching))
    layout["strat_a"].update(
        panel_cls(
            a_inner,
            title=f"[bold cyan]STRAT-A | CONSOLIDACION[/bold cyan]  [dim]({a_count})[/dim]",
            border_style="cyan",
            padding=(0, 1),
        )
    )

    layout["gale"].update(_build_gale_panel(state))
    layout["vip"].update(_build_vip_panel(state))
    layout["levels"].update(_build_quick_levels_panel(state))
    layout["logs"].update(_build_logs_panel(state))

    layout["footer"].update(
        text_cls(
            "CTRL+C para salir  |  Escaneo continuo  |  Distancia al trigger: verde <=0.10%, amarillo <=0.30%, tenue >0.30%",
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
    _render_mode: str = "live"  # live | static | fallback

    @classmethod
    def configure(cls, render_mode: str = "live") -> None:
        mode = str(render_mode or "live").strip().lower()
        if mode not in {"live", "static", "fallback"}:
            mode = "live"
        if cls._render_mode != mode:
            cls.shutdown()
        cls._render_mode = mode

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
        if cls._render_mode == "fallback" or not _RICH_OK:
            cls._display_fallback(state, balance)
            return
        try:
            renderable = _build_layout(state, balance)
            if cls._render_mode == "static":
                console = cls._get_console()
                console.clear()
                console.print(renderable)
            else:
                live = cls._ensure_live()
                live.update(renderable, refresh=True)
        except Exception:
            cls._display_fallback(state, balance)

    # ── fallback ANSI ─────────────────────────────────────────────────────────
    _last_text: str = ""
    _last_line_count: int = 0
    _screen_initialized: bool = False
    _fallback_cursor_mode: Optional[bool] = None

    @classmethod
    def _display_fallback(cls, state: HubState, balance: float) -> None:
        text = cls._render_fallback(state, balance)
        if text == cls._last_text:
            return

        if cls._fallback_cursor_mode is None:
            cls._fallback_cursor_mode = bool(_enable_ansi_windows())

        if not cls._screen_initialized:
            import os as _os
            _os.system("cls" if _os.name == "nt" else "clear")
            cls._screen_initialized = True

        # En terminales con ANSI: refresco in-place sin crear cuadros nuevos.
        # En terminales sin ANSI: limpiar pantalla completa en cada frame.
        if cls._fallback_cursor_mode:
            sys.stdout.write("\033[H\033[J")
        else:
            import os as _os
            _os.system("cls" if _os.name == "nt" else "clear")

        sys.stdout.write(text)
        sys.stdout.write("\n")
        sys.stdout.flush()
        cls._last_text = text
        cls._last_line_count = len(text.splitlines())

    @classmethod
    def _render_fallback(cls, state: HubState, balance: float) -> str:  # noqa: C901
        now = datetime.now(tz=timezone.utc).strftime("%H:%M:%S")
        sep  = f"{_BOLD}{_CYAN}{'─' * 80}{_RESET}"
        sep2 = f"{_DIM}{'·' * 80}{_RESET}"
        title = f"  QUOTEX BOT HUB │ UTC {now} │ Scans:{state.total_scans} │ ${balance:.2f} │ {_GREEN}{state.live_wins}W{_RESET}/{_RED}{state.live_losses}L{_RESET}"
        lines: list[str] = [
            f"{_BOLD}{_CYAN}{'━' * 80}{_RESET}",
            f"{_BOLD}{_MAGENTA}{title}{_RESET}",
            f"{_BOLD}{_CYAN}{'━' * 80}{_RESET}",
        ]

        # ── Secciones de estrategias ──────────────────────────────────────
        strat_defs = [
            ("A", "STRAT-A  Consolidación / Rebote",  state.strat_a_watching),
        ]
        for _key, label, candidates in strat_defs:
            lines.append(f"{_BOLD}  [{label}]{_RESET}")
            if not candidates:
                lines.append(f"  {_DIM}  Sin candidatos en este escaneo{_RESET}")
            else:
                for i, c in enumerate(candidates[:5], 1):
                    dist = f"{c.dist_pct * 100:.2f}%" if c.dist_pct is not None else "  -- "
                    dir_color = _GREEN if c.direction.lower() == "call" else _RED
                    score_color = _GREEN if c.score >= 60 else (_YELLOW if c.score >= 45 else _RED)
                    lines.append(
                        f"  {i}. {c.asset:<13} {dir_color}{c.direction.upper():<4}{_RESET}"
                        f"  {score_color}S:{c.score:<5.1f}{_RESET} P:{c.payout}%"
                        f"  Dist:{dist:<7}"
                        f"  {c.zone_floor:.5f} ── {c.zone_ceiling:.5f}"
                    )
            lines.append(sep2)

        lines.append(sep)

        # ── MASANIELLO MANAGER ────────────────────────────────────────────
        m = state.masaniello
        lines.append(f"{_BOLD}{_CYAN}  [MASANIELLO MANAGER]{_RESET}")
        if not m.active:
            lines.append(f"  {_DIM}  Sin operación activa{_RESET}")
            first_amount = m.next_amount if m.next_amount > 0 else (m.current_amount if m.current_amount > 0 else 1.01)
            lines.append(f"  {_YELLOW}  Primer monto: ${first_amount:.2f}{_RESET}")
            if m.trades_in_cycle > 0 or m.sequence:
                wr_color = _GREEN if m.win_rate_pct >= 60 else (_YELLOW if m.win_rate_pct >= 50 else _RED)
                pnl_color = _GREEN if m.total_pnl >= 0 else _RED
                loss_color = _GREEN if m.max_daily_loss >= 999999.0 else (_RED if m.daily_loss >= m.max_daily_loss * 0.8 else _YELLOW if m.daily_loss >= m.max_daily_loss * 0.5 else _GREEN)
                _loss_limit_str = "sin límite" if m.max_daily_loss >= 999999.0 else f"${m.max_daily_loss:.2f}"
                lines.append(
                    f"  Ciclo #{m.cycle_num}  {m.trades_in_cycle}/{m.cycle_target_ops} ops  "
                    f"{m.wins_in_cycle}W/{m.losses_in_cycle}L  {_DIM}Tiempo 00:00{_RESET}"
                )
                lines.append(
                    f"  Monto:${m.current_amount:.2f}  →  Próximo:${m.next_amount:.2f}  "
                    f"{wr_color}WR:{m.win_rate_pct:.0f}%{_RESET}  {pnl_color}P&L:{m.total_pnl:+.2f}${_RESET}"
                )
                lines.append(f"  {_DIM}Secuencia ciclo: {m.sequence or '-'}{_RESET}")
                lines.append(
                    f"  Pérdida Diaria:{loss_color}${m.daily_loss:.2f}/{_loss_limit_str}{_RESET}  "
                    f"Config:L3={m.multiplier}x  L5={m.commission_pct}%"
                )
            lines.append(f"  {_DIM}  Base/Ciclo: ${m.reference_balance:.2f} | {m.cycle_target_ops}/{m.cycle_target_wins}{_RESET}")
        else:
            dir_color = _GREEN if m.direction.upper() == "CALL" else _RED
            drift = max(0.0, time.time() - m.updated_at) if m.updated_at > 0 else 0.0
            secs = max(0.0, m.secs_remaining - drift)
            mm, ss = divmod(int(secs), 60)
            wr_color = _GREEN if m.win_rate_pct >= 60 else (_YELLOW if m.win_rate_pct >= 50 else _RED)
            pnl_color = _GREEN if m.total_pnl >= 0 else _RED
            
            lines.append(
                f"  {m.asset.upper():<14} {dir_color}{m.direction.upper():<4}{_RESET}"
                f"  EP:{m.entry_price:.5f}  PX:{m.current_price:.5f}"
                f"  {m.delta_pct:+.4f}%"
            )
            lines.append(
                f"  Ciclo #{m.cycle_num}  {m.trades_in_cycle}/{m.cycle_target_ops} ops  "
                f"{m.wins_in_cycle}W/{m.losses_in_cycle}L  {_DIM}Tiempo {mm:02d}:{ss:02d}{_RESET}"
            )
            lines.append(
                f"  Monto:${m.current_amount:.2f}  →  Próximo:${m.next_amount:.2f}  "
                f"{wr_color}WR:{m.win_rate_pct:.0f}%{_RESET}  {pnl_color}P&L:{m.total_pnl:+.2f}${_RESET}"
            )
            lines.append(f"  {_DIM}Secuencia ciclo: {m.sequence or '-'}{_RESET}")
            loss_color = _GREEN if m.max_daily_loss >= 999999.0 else (_RED if m.daily_loss >= m.max_daily_loss * 0.8 else _YELLOW if m.daily_loss >= m.max_daily_loss * 0.5 else _GREEN)
            _loss_limit_str = "sin límite" if m.max_daily_loss >= 999999.0 else f"${m.max_daily_loss:.2f}"
            lines.append(
                f"  Pérdida Diaria:{loss_color}${m.daily_loss:.2f}/{_loss_limit_str}{_RESET}  "
                f"Config:L3={m.multiplier}x  L5={m.commission_pct}%"
            )
            lines.append(
                f"  {_DIM}Base/Ciclo:${m.reference_balance:.2f} | {m.cycle_target_ops}/{m.cycle_target_wins}{_RESET}"
            )
        lines.append(sep)

        # ── HTF CACHE (15m) ───────────────────────────────────────────────
        lines.append(f"{_BOLD}{_CYAN}  [HTF CACHE 15M]{_RESET}")
        lines.append(
            f"  {_DIM}Biblioteca:{int(state.htf_library_size or 0)} activos | mostrando ultimo refresco{_RESET}"
        )
        if state.htf_asset:
            if state.htf_last_refresh_ts > 0:
                age = max(0.0, time.time() - float(state.htf_last_refresh_ts))
            else:
                age = max(0.0, float(state.htf_cache_age_sec or 0.0))
            ttl = max(0.0, float(state.htf_cache_ttl_sec or 0.0))
            freshness = (age / ttl) if ttl > 0 else 1.0
            status_color = _GREEN if freshness < 0.70 else (_YELLOW if freshness < 1.0 else _RED)
            status_label = "FRESCO" if freshness < 0.70 else ("ATENCION" if freshness < 1.0 else "VENCIDO")
            lines.append(
                f"  {state.htf_asset:<14} Payout:{state.htf_payout:>2}%  "
                f"Velas:{state.htf_candles:>2}  "
                f"Age:{age:>5.0f}s/{ttl:>4.0f}s  "
                f"{status_color}{status_label}{_RESET}"
            )
        else:
            lines.append(f"  {_DIM}  Sin cache HTF inicializado aún{_RESET}")
        lines.append(sep2)

        # ── VIP LIBRARY ──────────────────────────────────────────────────
        lines.append(f"{_BOLD}{_MAGENTA}  [VIP LIBRARY]{_RESET}")
        if state.vip_windows:
            for v in state.vip_windows[:3]:
                dir_color = _GREEN if v.direction == "call" else _RED
                status = "READY" if v.ready_to_execute else f"MISS {v.missing_conditions}/{v.total_conditions}"
                lines.append(
                    f"  {v.asset:<12} {dir_color}{v.direction.upper():<4}{_RESET}  "
                    f"S:{v.score:5.1f}  {status}  15m:{v.candles_15m_count:2d}  "
                    f"EMA15:{(f'{v.ma15_fast:.5f}/{v.ma15_slow:.5f}' if v.ma15_fast is not None and v.ma15_slow is not None else 'N/D')}"
                )
        else:
            lines.append(f"  {_DIM}  Sin candidatos VIP aún{_RESET}")
        lines.append(sep2)

        # ── Chart ASCII ──────────────────────────────────────────────────
        chart_lines = _render_ascii_chart(state)
        if chart_lines:
            for cl in chart_lines:
                lines.append(cl)
            lines.append(sep2)

        # ── Mini log ─────────────────────────────────────────────────────
        lines.append(f"{_BOLD}  [LOGS]{_RESET}")
        if _waiting_first_order(state):
            lines.append(f"  {_DIM}  En espera de primera operacion...{_RESET}")
        else:
            log_lines = _live_log_lines()
            if not log_lines:
                lines.append(f"  {_DIM}  (sin eventos recientes){_RESET}")
            else:
                for ln in log_lines:
                    lines.append(f"  {ln}")
        lines.append(f"{_BOLD}{_CYAN}{'━' * 80}{_RESET}")
        lines.append(f"  {_DIM}CTRL+C para salir{_RESET}")
        return "\n".join(lines)


# ── ASCII candlestick chart ───────────────────────────────────────────────────

_CHART_HEIGHT     = 10   # filas de precio en el chart
_CHART_BODY       = "█"  # cuerpo de vela lleno
_CHART_WICK_UP    = "│"  # mecha superior
_CHART_WICK_DOWN  = "│"  # mecha inferior
_CHART_ENTRY      = "◄"  # marcador de entrada (derecha del chart)
_CHART_LEVEL      = "─"  # línea de soporte/resistencia


def _render_ascii_chart(state: "HubState") -> List[str]:
    """
    Dibuja un mini chart ASCII de velas OHLC en tiempo real.

    Modos:
    - CANDIDATO: sin trade activo, muestra el candidato más cercano al trigger.
      El precio vivo viene de chart_live_price (último precio conocido del activo).
    - CHART (trade activo): la última vela refleja masaniello.current_price en cada
      refresh y se traza una línea PX móvil con delta % respecto a la entrada.
    Marcadores: EP (entrada), PX (precio actual), S (soporte), R (resistencia).
    """
    candles_orig = state.chart_candles
    if not candles_orig:
        return []

    asset   = state.chart_asset or "?"
    ep      = state.chart_entry_price
    dir_str = (state.chart_direction or "").upper()
    floor   = state.chart_zone_floor
    ceil_   = state.chart_zone_ceiling

    # ── Precio vivo ───────────────────────────────────────────────────────────
    # Fuente 1: masaniello.current_price  (cuando hay trade activo)
    # Fuente 2: chart_live_price          (candidato sin trade activo)
    live_price: Optional[float] = None
    m = state.masaniello
    if m.active and m.current_price > 0 and m.asset.upper() == asset:
        live_price = m.current_price
    elif state.chart_live_price is not None and state.chart_live_price > 0:
        live_price = state.chart_live_price

    # Reconstruir lista de velas con la última actualizada al precio vivo
    if live_price is not None and candles_orig:
        last = candles_orig[-1]
        live_candle = CandleSnapshot(
            open=last.open,
            high=max(last.high, live_price),
            low=min(last.low, live_price),
            close=live_price,
            ts=last.ts,
        )
        candles: List[CandleSnapshot] = list(candles_orig[:-1]) + [live_candle]
    else:
        candles = list(candles_orig)

    n = len(candles)
    hi_all = max(c.high for c in candles)
    lo_all = min(c.low  for c in candles)

    # Expandir rango para incluir todos los niveles marcados
    for lvl in (floor, ceil_, ep, live_price):
        if lvl is not None:
            lo_all = min(lo_all, lvl)
            hi_all = max(hi_all, lvl)

    price_range = hi_all - lo_all
    if price_range <= 0:
        return []

    H = _CHART_HEIGHT

    def _price_to_row(price: float) -> int:
        """Fila 0 = precio más alto, fila H-1 = precio más bajo."""
        frac = (hi_all - price) / price_range
        return min(H - 1, max(0, int(round(frac * (H - 1)))))

    # Construir grid
    cols = n * 2 - 1
    grid: list[list[str]] = [[" "] * cols for _ in range(H)]

    for ci, c in enumerate(candles):
        col = ci * 2
        body_top    = _price_to_row(max(c.open, c.close))
        body_bottom = _price_to_row(min(c.open, c.close))
        wick_top    = _price_to_row(c.high)
        wick_bottom = _price_to_row(c.low)
        bullish     = c.close >= c.open
        # última vela está "viva" si hay precio live
        is_live_candle = live_price is not None and ci == n - 1

        for row in range(H):
            if wick_top <= row < body_top:
                grid[row][col] = _CHART_WICK_UP
            elif body_top <= row <= body_bottom:
                grid[row][col] = _CHART_BODY
            elif body_bottom < row <= wick_bottom:
                grid[row][col] = _CHART_WICK_DOWN

        # Prefijo B/b (bullish/bearish) en la fila del cuerpo para colorear
        prefix = ("L" if is_live_candle else ("B" if bullish else "b"))
        if body_top < H:
            raw = grid[body_top][col]
            grid[body_top][col] = prefix + (raw[-1:] if len(raw) > 1 else raw)

    def _row_price(row: int) -> float:
        return hi_all - (row / (H - 1)) * price_range

    ep_row    = _price_to_row(ep)        if ep       is not None else -1
    floor_row = _price_to_row(floor)     if floor    is not None else -1
    ceil_row  = _price_to_row(ceil_)     if ceil_    is not None else -1
    px_row    = _price_to_row(live_price) if live_price is not None else -1

    dir_color = _GREEN if dir_str == "CALL" else (_RED if dir_str == "PUT" else _RESET)

    # Encabezado: "CANDIDATO" si no hay entrada; "CHART" si hay trade activo
    _mode_label = "CHART" if ep is not None else "CANDIDATO"
    header = (
        f"{_BOLD}{_CYAN}  [{_mode_label}  {asset}]{_RESET}"
        + (f"  {dir_color}{dir_str}{_RESET}" if dir_str else "")
        + (f"  EP:{ep:.5f}" if ep is not None else "")
    )
    if live_price is not None and ep is not None and ep > 0:
        delta = ((live_price - ep) / ep) * 100.0
        # Para CALL: positivo es bueno; para PUT: negativo es bueno
        winning = (delta >= 0 and dir_str == "CALL") or (delta <= 0 and dir_str == "PUT")
        d_color = _GREEN if winning else _RED
        header += f"  PX:{live_price:.5f}  {d_color}Δ{delta:+.3f}%{_RESET}"
    elif live_price is not None:
        header += f"  PX:{live_price:.5f}"

    result_lines: list[str] = [header]

    for row in range(H):
        rp = _row_price(row)
        price_label = f"{rp:.5f}"

        is_ep    = (row == ep_row)
        is_floor = (row == floor_row)
        is_ceil  = (row == ceil_row)
        is_px    = (row == px_row and live_price is not None and row != ep_row)

        row_chars: list[str] = []
        for ci in range(n):
            col = ci * 2
            raw = grid[row][col]

            # Detectar tipo de celda
            if raw.startswith("L"):
                # Vela viva (se pinta en magenta para distinguirla)
                color = _MAGENTA
                ch = raw[1:] or _CHART_BODY
            elif raw.startswith("B"):
                color = _GREEN
                ch = raw[1:] or _CHART_BODY
            elif raw.startswith("b"):
                color = _RED
                ch = raw[1:] or _CHART_BODY
            else:
                color = _DIM
                ch = raw

            # Trazar línea de nivel si el espacio está vacío
            if ch == " ":
                if is_px:
                    color = _MAGENTA
                    ch = _CHART_LEVEL
                elif is_ep:
                    color = dir_color
                    ch = _CHART_LEVEL
                elif is_floor or is_ceil:
                    color = _YELLOW
                    ch = _CHART_LEVEL

            row_chars.append(f"{color}{ch}{_RESET}")

            if ci < n - 1:
                # Separador entre velas
                if is_px:
                    sep, sep_color = _CHART_LEVEL, _MAGENTA
                elif is_ep:
                    sep, sep_color = _CHART_LEVEL, dir_color
                elif is_floor or is_ceil:
                    sep, sep_color = _CHART_LEVEL, _YELLOW
                else:
                    sep, sep_color = " ", _DIM
                row_chars.append(f"{sep_color}{sep}{_RESET}")

        chart_str = "".join(row_chars)

        # Etiqueta derecha
        suffix = ""
        if is_px:
            winning_px = (live_price is not None and ep is not None and (
                (dir_str == "CALL" and live_price >= ep) or
                (dir_str == "PUT"  and live_price <= ep)
            ))
            px_color = _GREEN if winning_px else _RED
            suffix = f"  {price_label}  {px_color}◆ PX (vivo){_RESET}"
        elif is_ep:
            suffix = f"  {price_label}  {dir_color}{_CHART_ENTRY} ENTRADA{_RESET}"
        elif is_ceil:
            suffix = f"  {price_label}  {_YELLOW}↑ Resistencia{_RESET}"
        elif is_floor:
            suffix = f"  {price_label}  {_YELLOW}↓ Soporte{_RESET}"
        elif row == 0:
            suffix = f"  {price_label}  {_DIM}(max){_RESET}"
        elif row == H - 1:
            suffix = f"  {price_label}  {_DIM}(min){_RESET}"

        result_lines.append(f"  {chart_str}{suffix}")

    result_lines.append(f"  {_DIM}{'─' * (cols + 2)}{_RESET}")
    return result_lines

