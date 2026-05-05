import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_GREEN = "\033[32m"
_RED = "\033[31m"
_YELLOW = "\033[33m"
_CYAN = "\033[36m"


def _enable_ansi_windows() -> None:
    """Habilita secuencias ANSI en consolas Windows cuando es posible."""
    if os.name != "nt":
        return
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint32()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
            kernel32.SetConsoleMode(handle, mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING)
    except Exception:
        pass


def _ok(flag: bool) -> str:
    return f"{_GREEN}[x]{_RESET}" if flag else f"{_RED}[ ]{_RESET}"


def _load_state(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _checklist(strategy: str, candidates: list[dict]) -> list[tuple[str, bool]]:
    top = candidates[0] if candidates else {}
    score = float(top.get("score", 0.0) or 0.0)
    payout = int(top.get("payout", 0) or 0)
    direction = str(top.get("direction", "") or "").lower()
    has_dist = top.get("dist_pct", None) is not None

    required_score = {"A": 60.0, "B": 48.0, "C": 40.0}.get(strategy, 50.0)
    required_payout = 80

    return [
        ("Activo detectado en scan", len(candidates) > 0),
        ("Direccion valida (CALL/PUT)", direction in ("call", "put")),
        (f"Payout minimo >= {required_payout}%", payout >= required_payout),
        (f"Score minimo >= {required_score:.0f}", score >= required_score),
        ("Distancia al trigger disponible", has_dist),
    ]


def _render(strategy: str, state: dict) -> str:
    scans = int(state.get("total_scans", 0) or 0)
    balance = float(state.get("balance", 0.0) or 0.0)
    wins = int(state.get("wins", 0) or 0)
    losses = int(state.get("losses", 0) or 0)

    key = {"A": "strat_a", "B": "strat_b", "C": "strat_c"}.get(strategy, "strat_a")
    candidates = list(state.get(key, []) or [])

    lines = [
        f"{_BOLD}{_CYAN}{'=' * 78}{_RESET}",
        f"{_BOLD}MONITOR ESTRATEGIA {strategy}{_RESET}",
        f"Scans:{scans}  Balance:${balance:.2f}  W/L:{wins}/{losses}",
        f"{_DIM}{'-' * 78}{_RESET}",
        f"{_BOLD}Checklist{_RESET}",
    ]

    for label, done in _checklist(strategy, candidates):
        lines.append(f"  {_ok(done)} {label}")

    lines.append(f"{_DIM}{'-' * 78}{_RESET}")
    lines.append(f"{_BOLD}Top candidatos{_RESET}")
    if not candidates:
        lines.append(f"  {_DIM}Sin candidatos en este ciclo{_RESET}")
    else:
        for i, c in enumerate(candidates[:5], 1):
            direction = str(c.get("direction", "")).upper()
            score = float(c.get("score", 0.0) or 0.0)
            payout = int(c.get("payout", 0) or 0)
            dist = c.get("dist_pct", None)
            dist_txt = "--" if dist is None else f"{float(dist) * 100:.2f}%"
            lines.append(
                f"  {i}. {str(c.get('asset', '')):<12} {direction:<4} "
                f"S:{score:>5.1f} P:{payout:>2}% Dist:{dist_txt}"
            )

    gale = dict(state.get("gale", {}) or {})
    lines.append(f"{_DIM}{'-' * 78}{_RESET}")
    lines.append(f"{_BOLD}Gale watcher{_RESET}")
    if bool(gale.get("active", False)):
        lines.append(
            f"  Activo: {gale.get('asset', '')} {str(gale.get('direction', '')).upper()} "
            f"{float(gale.get('secs_remaining', 0.0) or 0.0):.0f}s"
        )
    else:
        lines.append(f"  {_DIM}Sin gale activo{_RESET}")

    lines.append("")
    lines.append(f"{_DIM}Auto-cierre si se detiene el monitor central (sin heartbeat).{_RESET}")
    return "\n".join(lines)


def _main() -> int:
    parser = argparse.ArgumentParser(description="Monitor checklist por estrategia")
    parser.add_argument("--strategy", choices=("A", "B", "C"), required=True)
    parser.add_argument("--state-file", required=True)
    parser.add_argument("--interval", type=float, default=0.8)
    parser.add_argument("--stale-sec", type=float, default=8.0)
    args = parser.parse_args()

    state_path = Path(args.state_file)
    strategy = str(args.strategy)
    _enable_ansi_windows()

    last_frame = ""
    screen_initialized = False
    while True:
        if not state_path.exists():
            if not screen_initialized:
                os.system("cls" if os.name == "nt" else "clear")
                screen_initialized = True
            msg = "Esperando monitor central..."
            if msg != last_frame:
                sys.stdout.write("\033[H\033[J")
                sys.stdout.write(msg + "\n")
                sys.stdout.flush()
                last_frame = msg
            time.sleep(max(0.2, args.interval))
            continue

        state = _load_state(state_path)
        heartbeat = float(state.get("generated_at", 0.0) or 0.0)
        age = time.time() - heartbeat if heartbeat > 0 else 9999.0
        if age > float(args.stale_sec):
            if not screen_initialized:
                os.system("cls" if os.name == "nt" else "clear")
            sys.stdout.write("\033[H\033[J")
            sys.stdout.write("Monitor central detenido. Cerrando esta ventana...\n")
            sys.stdout.flush()
            return 0

        frame = _render(strategy, state)
        if frame != last_frame:
            if not screen_initialized:
                os.system("cls" if os.name == "nt" else "clear")
                screen_initialized = True
            sys.stdout.write("\033[H\033[J")
            sys.stdout.write(frame)
            sys.stdout.write("\n")
            sys.stdout.flush()
            last_frame = frame

        time.sleep(max(0.2, args.interval))


if __name__ == "__main__":
    raise SystemExit(_main())
