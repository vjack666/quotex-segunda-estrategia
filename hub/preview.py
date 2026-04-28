from __future__ import annotations

import argparse
from pathlib import Path

from .parser import HubLogParser
from .render import render_dashboard


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Preview del hub profesional basado en logs")
    p.add_argument("--log", type=Path, default=Path("consolidation_bot.log"), help="Ruta del log fuente")
    p.add_argument("--tail", type=int, default=2500, help="Cuantas lineas finales parsear")
    return p


def main() -> None:
    args = build_parser().parse_args()
    if not args.log.exists():
        raise SystemExit(f"No existe log: {args.log}")

    raw = args.log.read_text(encoding="utf-8", errors="replace").splitlines()
    lines = raw[-max(100, args.tail):]

    parser = HubLogParser()
    snapshot = parser.parse_lines(lines)
    board = render_dashboard(snapshot)

    print(board)
    print(f"Fuente: {args.log} | lineas parseadas: {len(lines)}")


if __name__ == "__main__":
    main()
