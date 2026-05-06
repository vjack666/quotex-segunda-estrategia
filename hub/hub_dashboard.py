"""Dashboard visual del HUB para ejecucion en tiempo real."""

from __future__ import annotations

import sys
import time
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, List, Optional

from .hub_models import CandidateData, HubState
from src.martingale_calculator import MartingaleCalculator

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

_LOG_TAIL_LINES = 8
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
        not state.gale.active
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


def _build_strat_b_table(candidates: List[CandidateData]) -> "Table":
    table_cls = _require_table_class()
    t = table_cls(show_header=True, header_style="bold magenta", box=None, padding=(0, 1), expand=True)
    t.add_column("#",      width=2,  justify="right")
    t.add_column("Activo", width=14, no_wrap=True)
    t.add_column("Dir",    width=6)
    t.add_column("Conf%",  width=6,  justify="right")
    t.add_column("P%",     width=4,  justify="right")
    t.add_column("Dist",   width=7,  justify="right")
    t.add_column("Sup",    width=10, justify="right")
    t.add_column("Res",    width=10, justify="right")
    t.add_column("Señal",  width=11, no_wrap=True)
    t.add_column("Patron", min_width=12)

    if not candidates:
        t.add_row("[dim]—[/dim]", "[dim]Sin candidatos en este escaneo[/dim]",
              "", "", "", "", "", "", "", "")
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
            f"[dim]{c.zone_floor:.5f}[/dim]",
            f"[dim]{c.zone_ceiling:.5f}[/dim]",
            f"[dim]{signal}[/dim]",
            f"[dim]{c.pattern[:18]}[/dim]",
        )
    return t


def _build_strat_c_table(candidates: List[CandidateData]) -> "Table":
    table_cls = _require_table_class()
    t = table_cls(show_header=True, header_style="bold blue", box=None, padding=(0, 1), expand=True)
    t.add_column("#",      width=2,  justify="right")
    t.add_column("Activo", width=14, no_wrap=True)
    t.add_column("Dir",    width=6)
    t.add_column("Score",  width=6,  justify="right")
    t.add_column("P%",     width=4,  justify="right")
    t.add_column("Dist",   width=7,  justify="right")
    t.add_column("Sup",    width=10, justify="right")
    t.add_column("Res",    width=10, justify="right")
    t.add_column("Señal",  width=11, no_wrap=True)
    t.add_column("Patron", min_width=12)

    if not candidates:
        t.add_row("[dim]—[/dim]", "[dim]Sin candidatos en este escaneo[/dim]",
              "", "", "", "", "", "", "", "")
        return t

    for i, c in enumerate(candidates[:5], 1):
        s_col = "green" if c.score >= 65 else "yellow" if c.score >= 50 else "red"
        p_col = "green" if c.payout >= 80 else "yellow" if c.payout >= 70 else "red"
        signal = _abbrev(c.signal_type or c.entry_mode or "none")
        t.add_row(
            str(i),
            f"[bold]{c.asset}[/bold]",
            _direction_markup(c.direction),
            f"[{s_col}]{c.score:.1f}[/{s_col}]",
            f"[{p_col}]{c.payout}[/{p_col}]",
            _dist_markup(c.dist_pct),
            f"[dim]{c.zone_floor:.5f}[/dim]",
            f"[dim]{c.zone_ceiling:.5f}[/dim]",
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
    drift = 0.0
    if g.updated_at > 0:
        drift = max(0.0, time.time() - g.updated_at)
    secs = max(0.0, g.secs_remaining - drift)
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

    safety = str(getattr(g, "safety_status", "OK") or "OK").upper()
    if safety == "OK":
        safety_mu = "[bold green]OK[/bold green]"
    elif safety == "RIESGO":
        safety_mu = "[bold red]RIESGO[/bold red]"
    elif safety == "LIMITE":
        safety_mu = "[bold yellow]LIMITE[/bold yellow]"
    elif safety == "CICLO":
        safety_mu = "[cyan]CICLO[/cyan]"
    else:
        safety_mu = "[bold red]ERROR[/bold red]"

    t.add_row("Activo:",   f"{g.asset.upper()}  {dir_mu}  [dim]payout {g.payout}%[/dim]")
    t.add_row("Entrada:",  f"EP [bold]{g.entry_price:.5f}[/bold]  PX [bold]{g.current_price:.5f}[/bold]  {delta_mu}")
    t.add_row("Estado:",   status_mu)
    t.add_row("⏱ Tiempo:",  time_mu)
    t.add_row("Monto:",    f"Base ${g.amount_invested:.2f}  →  Gale {gale_mu}")
    t.add_row("Disparo:",  fired_mu)
    t.add_row("Seguridad:", safety_mu)

    # objetivo del ciclo y consecutivas
    if g.cycle_target_amount > 0:
        objetivo_mu = f"[bold green]+${g.cycle_target_amount:.2f}[/bold green]"
    else:
        objetivo_mu = "[dim]calculando...[/dim]"
    max_consec = MartingaleCalculator.MAX_CONSECUTIVE_ENTRIES
    used = min(g.consecutive_count, max_consec)
    if used >= max_consec:
        consec_mu = f"[bold red]{used}/{max_consec}[/bold red]  [dim](límite)[/dim]"
    elif used >= max_consec - 1:
        consec_mu = f"[bold yellow]{used}/{max_consec}[/bold yellow]"
    else:
        consec_mu = f"[bold]{used}/{max_consec}[/bold]"
    t.add_row("Objetivo:",     objetivo_mu)
    t.add_row("Consecutivas:", consec_mu)

    # contexto de gale (protocolo por estrategia+par)
    ctx = str(getattr(g, "context_key", "") or "")
    if ctx:
        t.add_row("Protocolo:", f"[dim]{ctx}[/dim]")

    border = "red" if g.is_losing else "green"
    if g.gale_fired:
        border = "yellow"
    title_suffix = "  [bold red]● ACTIVO[/bold red]" if g.active else ""
    return panel_cls(t, title=f"[bold yellow]GALE WATCHER[/bold yellow]{title_suffix}",
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
        title="[bold white]MINI TERMINAL LOGS[/bold white] [dim](tail en vivo)[/dim]",
        border_style="white",
        padding=(0, 1),
    )


def _build_quick_levels_panel(state: HubState) -> "Panel":
    """Lista compacta para trazar niveles manualmente en la grafica."""
    panel_cls = _require_panel_class()
    table_cls = _require_table_class()

    all_candidates: List[CandidateData] = (
        list(state.strat_a_watching[:5])
        + list(state.strat_b_watching[:5])
        + list(state.strat_c_watching[:5])
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
        title="[bold white]NIVELES RAPIDOS[/bold white] [dim](Soporte / Resistencia)[/dim]",
        border_style="white",
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
        layout_cls(name="levels", size=6),
        layout_cls(name="gale",   size=8),
        layout_cls(name="logs",   size=10),
        layout_cls(name="footer", size=1),
    )

    layout["body"].split_row(layout_cls(name="strat_a"), layout_cls(name="strat_b"), layout_cls(name="strat_c"))

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

    b_count = len(state.strat_b_watching)
    b_inner = table_cls.grid(expand=True)
    b_inner.add_column()
    b_inner.add_row(text_cls.from_markup("[dim]Conf · Dir · Dist-trigger · Soporte/Resistencia · Señal · Patron[/dim]"))
    b_inner.add_row(_build_strat_b_table(state.strat_b_watching))
    layout["strat_b"].update(
        panel_cls(
            b_inner,
            title=f"[bold magenta]STRAT-B | SPRING/WYCKOFF[/bold magenta]  [dim]({b_count})[/dim]",
            border_style="magenta",
            padding=(0, 1),
        )
    )

    c_count = len(state.strat_c_watching)
    c_inner = table_cls.grid(expand=True)
    c_inner.add_column()
    c_inner.add_row(text_cls.from_markup("[dim]Score · Dir · Dist-trigger · Soporte/Resistencia · Señal · Patron[/dim]"))
    c_inner.add_row(_build_strat_c_table(state.strat_c_watching))
    layout["strat_c"].update(
        panel_cls(
            c_inner,
            title=f"[bold blue]STRAT-C | RECHAZO 30s[/bold blue]  [dim]({c_count})[/dim]",
            border_style="blue",
            padding=(0, 1),
        )
    )

    layout["gale"].update(_build_gale_panel(state))
    layout["levels"].update(_build_quick_levels_panel(state))
    layout["logs"].update(_build_logs_panel(state))

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
            ("B", "STRAT-B  Spring / Sweep",           state.strat_b_watching),
            ("C", "STRAT-C  Rechazo M1 (30s)",         state.strat_c_watching),
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

        # ── Niveles rápidos (sección combinada) ───────────────────────────
        lines.append(f"{_BOLD}  [NIVELES S/R]{_RESET}")
        quick = (
            list(state.strat_a_watching[:5])
            + list(state.strat_b_watching[:5])
            + list(state.strat_c_watching[:5])
        )
        quick.sort(key=lambda c: (9999.0 if c.dist_pct is None else c.dist_pct, -c.rank_value))
        if not quick:
            lines.append(f"  {_DIM}  Sin niveles en este escaneo{_RESET}")
        else:
            for i, c in enumerate(quick[:10], 1):
                strat_tag = c.strategy.replace("STRAT-", "S")
                dir_color = _GREEN if c.direction.lower() == "call" else _RED
                dist = f"Dist:{c.dist_pct * 100:.2f}%" if c.dist_pct is not None else ""
                lines.append(
                    f"  {i:>2}. {_DIM}{strat_tag:<2}{_RESET} {c.asset:<13}"
                    f"  {dir_color}{c.direction.upper():<4}{_RESET}"
                    f"  {c.zone_floor:.5f} ── {c.zone_ceiling:.5f}"
                    f"  {_DIM}{dist}{_RESET}"
                )
        lines.append(sep)

        # ── GALE WATCHER ──────────────────────────────────────────────────
        g = state.gale
        lines.append(f"{_BOLD}{_YELLOW}  [GALE WATCHER]{_RESET}")
        if not g.active:
            lines.append(f"  {_DIM}  Sin operación activa{_RESET}")
        else:
            dir_color = _GREEN if g.direction.upper() == "CALL" else _RED
            status = f"{_RED}⚠ PERDIENDO{_RESET}" if g.is_losing else f"{_GREEN}✓ GANANDO{_RESET}"
            drift = max(0.0, time.time() - g.updated_at) if g.updated_at > 0 else 0.0
            secs = max(0.0, g.secs_remaining - drift)
            mm, ss = divmod(int(secs), 60)
            fired = (
                f"{_GREEN}✔ ENVIADO{_RESET}" if g.gale_fired and g.gale_success
                else (f"{_RED}✗ ERROR{_RESET}" if g.gale_fired else f"{_DIM}En espera{_RESET}")
            )
            safety = str(getattr(g, "safety_status", "OK") or "OK").upper()
            if safety == "OK":
                safety_txt = f"{_GREEN}OK{_RESET}"
            elif safety == "RIESGO":
                safety_txt = f"{_RED}RIESGO{_RESET}"
            elif safety == "LIMITE":
                safety_txt = f"{_YELLOW}LIMITE{_RESET}"
            elif safety == "CICLO":
                safety_txt = f"{_BLUE}CICLO{_RESET}"
            else:
                safety_txt = f"{_RED}ERROR{_RESET}"
            obj = f"+${g.cycle_target_amount:.2f}" if g.cycle_target_amount > 0 else "calculando..."
            max_c = MartingaleCalculator.MAX_CONSECUTIVE_ENTRIES
            used = min(g.consecutive_count, max_c)
            c_color = _RED if used >= max_c else (_YELLOW if used >= max_c - 1 else "")
            ctx = str(getattr(g, "context_key", "") or "")
            lines.append(
                f"  {g.asset.upper():<14} {dir_color}{g.direction.upper():<4}{_RESET}"
                f"  EP:{g.entry_price:.5f}  PX:{g.current_price:.5f}"
                f"  {g.delta_pct:+.4f}%  {status}"
            )
            lines.append(
                f"  ⏱ {mm:02d}:{ss:02d}"
                f"  Base:${g.amount_invested:.2f}  Gale:{_YELLOW}${g.gale_amount:.2f}{_RESET}"
                f"  Disparo:{fired}  Seguridad:{safety_txt}"
            )
            lines.append(
                f"  Objetivo:{_GREEN}{obj}{_RESET}"
                f"  Consecutivas:{c_color}{used}/{max_c}{_RESET}"
                + (f"  {_DIM}{ctx}{_RESET}" if ctx else "")
            )
        lines.append(sep)

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
