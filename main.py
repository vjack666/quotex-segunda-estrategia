import sys
import io
import argparse
import asyncio
import logging
from pathlib import Path

# Forzar UTF-8 en stdout/stderr para evitar UnicodeEncodeError en Windows (CP1252).
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
else:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
else:
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

ROOT = Path(__file__).resolve().parent
SRC_DIR = ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="QUOTEX executor 24/7 (consolidation + martingala + risk)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--real", action="store_true", help="Operar en cuenta REAL (default: DEMO)")
    p.add_argument("--once", action="store_true", help="Ejecutar un solo ciclo y salir")
    p.add_argument(
        "--hub-readonly",
        action="store_true",
        help="Modo HUB: solo lectura (sin enviar ordenes), loop de 60s para monitoreo",
    )

    # Gestión de capital / martingala
    p.add_argument(
        "--amount-initial",
        type=float,
        default=1.0,
        help="Monto mínimo de orden para la calculadora de riesgo",
    )
    p.add_argument(
        "--amount-martin",
        type=float,
        default=2.0,
        help="Incremento objetivo por ciclo para la calculadora de riesgo",
    )
    p.add_argument("--max-loss-session", type=float, default=0.20, help="Stop-loss de sesión (fracción)")

    # Perfil estilo Excel / Masaniello (ejemplo: 5 operaciones, 2 ITM)
    p.add_argument("--cycle-ops", type=int, default=5, help="Máximo de operaciones por ciclo")
    p.add_argument("--cycle-wins", type=int, default=2, help="Objetivo de aciertos por ciclo")
    p.add_argument("--cycle-profit-pct", type=float, default=0.10, help="Take-profit por ciclo (fracción)")

    # Filtros operativos
    p.add_argument("--min-payout", type=int, default=80, help="Payout mínimo permitido")
    p.add_argument("--scan-lead-sec", type=float, default=35.0, help="Anticipación del scan antes del open")

    # STRAT-B (Spring Sweep)
    p.add_argument(
        "--strat-b-live",
        action="store_true",
        help="Permitir que STRAT-B abra operaciones (default: solo aviso en terminal)",
    )
    p.add_argument(
        "--strat-b-duration",
        type=int,
        default=120,
        help="Duración en segundos para entradas STRAT-B",
    )
    p.add_argument(
        "--strat-b-min-confidence",
        type=float,
        default=0.70,
        help="Confianza mínima [0.0-1.0] para habilitar entrada STRAT-B",
    )
    return p


def _apply_runtime_config(args: argparse.Namespace) -> None:
    import consolidation_bot as cb
    from martingale_calculator import MartingaleCalculator

    cb.MAX_LOSS_SESSION = float(args.max_loss_session)

    # La gestión de montos ya no usa variables globales del bot; se configura
    # directamente sobre la calculadora dinámica de riesgo.
    MartingaleCalculator.MIN_ORDER_AMOUNT = max(0.01, float(args.amount_initial))
    MartingaleCalculator.INCREMENT = max(0.01, float(args.amount_martin))

    cb.CYCLE_MAX_OPERATIONS = int(args.cycle_ops)
    cb.CYCLE_TARGET_WINS = int(args.cycle_wins)
    cb.CYCLE_TARGET_PROFIT_PCT = float(args.cycle_profit_pct)

    cb.MIN_PAYOUT = int(args.min_payout)
    cb.SCAN_LEAD_SEC = float(args.scan_lead_sec)

    cb.STRAT_B_CAN_TRADE = bool(args.strat_b_live)
    cb.STRAT_B_DURATION_SEC = max(30, int(args.strat_b_duration))
    cb.STRAT_B_MIN_CONFIDENCE = max(0.0, min(1.0, float(args.strat_b_min_confidence)))

    # Modo HUB (solo lectura): fuerza escaneo por minuto y deshabilita trading.
    if bool(args.hub_readonly):
        cb.STRAT_B_CAN_TRADE = False
        cb.SCAN_INTERVAL_SEC = 60
        cb.ALIGN_SCAN_TO_CANDLE = False


async def _render_hub_once(bot=None) -> None:
    """Renderiza el panel HUB desde bot.hub o desde el log."""
    import os
    
    # Si tenemos acceso a bot.hub, usar eso directamente
    if bot is not None and hasattr(bot, 'hub'):
        try:
            from hub.hub_dashboard import HubDashboard
            state = bot.hub.get_state()
            if getattr(state, "total_scans", 0) > 0 or getattr(state, "last_scan", None) is not None:
                balance = bot.current_balance or 0.0
                HubDashboard.display(state, balance=balance)
                return
        except Exception as exc:
            log_msg = f"[HUB] Error al renderizar desde bot.hub: {exc}"
            if hasattr(bot, 'log'):
                # Si bot tiene log, usarlo
                pass
            print(log_msg)
    
    # Fallback: parsear el log file
    try:
        from hub.parser import HubLogParser
        from hub.render import render_dashboard
        log_path = ROOT / "consolidation_bot.log"
        parser = HubLogParser()
        with open(log_path, encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
        snap = parser.parse_lines(lines[-600:])
        panel = render_dashboard(snap)
        os.system("cls" if os.name == "nt" else "clear")
        print(panel)
    except Exception as exc:
        print(f"[HUB] Error al renderizar el panel: {exc}")


def _configure_hub_console(cb) -> None:
    """Reduce el ruido del logger en consola para que el dashboard quede visible."""
    stdout_handler = getattr(cb, "_stdout_handler", None)
    if stdout_handler is not None:
        stdout_handler.setLevel(logging.ERROR)


def _render_empty_hub() -> None:
    """Muestra la estructura del HUB antes del primer escaneo."""
    from hub.hub_dashboard import HubDashboard
    from hub.hub_models import HubState

    HubDashboard.display(HubState(), balance=0.0)


async def _on_cycle_end(bot) -> None:
    await _render_hub_once(bot)


async def _run(args: argparse.Namespace) -> None:
    import consolidation_bot as cb

    _apply_runtime_config(args)
    hub_readonly = bool(args.hub_readonly)
    run_once = bool(args.once)

    # En modo HUB no se ejecutan ordenes (dry_run=True), solo lectura/analisis.
    dry_run = hub_readonly

    if hub_readonly:
        _configure_hub_console(cb)
        _render_empty_hub()

        # Loop propio: un escaneo (loop_forever=False) → renderizar hub → esperar → repetir.
        # Esto garantiza que el panel se dibuje después de cada ciclo.
        while True:
            try:
                bot = await cb.main(
                    dry_run=True,
                    real_account=bool(args.real),
                    loop_forever=False,
                    on_cycle_end=_on_cycle_end,
                )
            except SystemExit as exc:
                code = exc.code if isinstance(exc.code, int) else 1
                print(f"[HUB] Conexion no disponible (code={code}). Reintentando en 60s...")
                await asyncio.sleep(60)
                if run_once:
                    return
                continue
            if run_once:
                return
            try:
                await asyncio.sleep(cb.SCAN_INTERVAL_SEC)
            except asyncio.CancelledError:
                return
    else:
        bot = await cb.main(
            dry_run=dry_run,
            real_account=bool(args.real),
            loop_forever=not run_once,
            on_cycle_end=_on_cycle_end,
        )


if __name__ == "__main__":
    parser = _build_parser()
    try:
        asyncio.run(_run(parser.parse_args()))
    except ModuleNotFoundError as exc:
        if getattr(exc, "name", "") == "pyquotex":
            venv_python = ROOT / ".venv" / "Scripts" / "python.exe"
            print("ERROR: Falta el modulo 'pyquotex' en el Python actual.")
            print("Ejecuta el bot con el entorno virtual del proyecto:")
            print(f'  "{venv_python}" main.py --hub-readonly')
            print("O instala dependencias en el entorno actual:")
            print("  python -m pip install -r requirements.txt")
            raise SystemExit(1)
        raise
    except KeyboardInterrupt:
        raise SystemExit(0)
