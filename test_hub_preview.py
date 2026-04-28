from __future__ import annotations

from pathlib import Path

from hub.parser import HubLogParser
from hub.render import render_dashboard


def main() -> None:
    log_path = Path("consolidation_bot.log")
    if not log_path.exists():
        raise SystemExit("No se encontro consolidation_bot.log para el test.")

    lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-2500:]
    snapshot = HubLogParser().parse_lines(lines)
    board = render_dashboard(snapshot)

    print(board)
    print("\n[Test HUB] Render completado correctamente.")


if __name__ == "__main__":
    main()
