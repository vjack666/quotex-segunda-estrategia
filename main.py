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
        description="QUOTEX executor 24/7 (consolidation + mg externo + risk)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--real", action="store_true", help="Operar en cuenta REAL (default: DEMO)")
    p.add_argument("--once", action="store_true", help="Ejecutar un solo ciclo y salir")
    p.add_argument(
        "--hub-readonly",
        action="store_true",
        help="Modo HUB: solo lectura (sin enviar ordenes), loop de 60s para monitoreo",
    )

    # Gestion de capital / motor martingala externo
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
    p.add_argument(
        "--mg-disabled",
        action="store_true",
        help="Desactiva el motor externo de martingala en background",
    )
    p.add_argument(
        "--mg-prefire-sec",
        type=float,
        default=2.0,
        help="Segundos antes del cierre para preparar/ejecutar martin",
    )
    p.add_argument(
        "--mg-poll-sec",
        type=float,
        default=0.5,
        help="Intervalo de monitoreo en vivo del motor martin",
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
    cb.MG_EXTERNAL_ENABLED = not bool(args.mg_disabled)
    cb.MG_PREFIRE_SECONDS = max(0.5, float(args.mg_prefire_sec))
    cb.MG_MONITOR_POLL_SECONDS = max(0.2, float(args.mg_poll_sec))

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
    """Renderiza el panel HUB desde bot.hub (o estado vacío si bot aún no existe)."""
    from hub.hub_dashboard import HubDashboard
    from hub.hub_models import HubState
    try:
        if bot is not None and hasattr(bot, 'hub'):
            state = bot.hub.get_state()
            balance = state.known_balance
        else:
            state = HubState()
            balance = 0.0
        HubDashboard.display(state, balance=balance)
    except Exception:
        pass


def _configure_hub_console(cb) -> None:
    """Reduce el ruido del logger en consola para que el dashboard quede visible."""
    # Handler de consola definido en consolidation_bot.py
    stdout_handler = getattr(cb, "_stdout_handler", None)
    if stdout_handler is not None:
        stdout_handler.setLevel(logging.ERROR)

    # Logger principal del bot
    bot_log = getattr(cb, "log", None)
    if bot_log is not None:
        bot_log.setLevel(logging.ERROR)

    # Root logger y librerias ruidosas
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.ERROR)
    for handler in root_logger.handlers:
        if isinstance(handler, logging.StreamHandler):
            handler.setLevel(logging.ERROR)
    logging.getLogger("pyquotex").setLevel(logging.CRITICAL)
    logging.getLogger("websocket").setLevel(logging.CRITICAL)



async def _run_cycle_with_loading(cb, *, dry_run: bool, real_account: bool):
    """Ejecuta un ciclo y refresca el HUB hasta que termine."""
    task = asyncio.create_task(
        cb.main(
            dry_run=dry_run,
            real_account=real_account,
            loop_forever=False,
            on_cycle_end=_render_hub_once,
        )
    )

    while not task.done():
        await _render_hub_once()
        await asyncio.sleep(1)

    return await task


async def _hub_ticker(bot_ref: list, interval: float = 5.0) -> None:
    """Refresca el HUB en segundo plano cada `interval` segundos sin esperar ciclos.
    Si llega un resultado de trade (WIN/LOSS) antes del intervalo, re-renderiza al instante.
    """
    while True:
        try:
            bot = bot_ref[0] if bot_ref else None

            # Obtener el evento del scanner si está disponible.
            trade_event = None
            if bot is not None and hasattr(bot, 'hub') and hasattr(bot.hub, 'trade_result_event'):
                trade_event = bot.hub.trade_result_event

            if trade_event is not None:
                # Esperar lo que llegue primero: resultado de trade o el intervalo normal.
                sleep_task = asyncio.create_task(asyncio.sleep(interval))
                event_wait = asyncio.create_task(trade_event.wait())
                done, pending = await asyncio.wait(
                    {sleep_task, event_wait},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for t in pending:
                    t.cancel()
                # Limpiar el evento para el siguiente ciclo.
                trade_event.clear()
            else:
                await asyncio.sleep(interval)

            bot = bot_ref[0] if bot_ref else None
            if bot is not None:
                await _render_hub_once(bot)
        except asyncio.CancelledError:
            return
        except Exception:
            pass


async def _run_forever_with_initial_loading(cb, *, dry_run: bool, real_account: bool):
    """Ejecuta loop continuo mostrando el HUB hasta finalizar el primer ciclo."""
    first_cycle_done = asyncio.Event()
    # Referencia mutable al bot para que el ticker siempre use la instancia actual.
    bot_ref: list = [None]

    def _on_bot_ready(bot):
        """Llamado apenas el bot se conecta y conoce el balance (antes del primer scan)."""
        bot_ref[0] = bot

    async def _on_cycle_end_with_event(bot):
        bot_ref[0] = bot
        await _render_hub_once(bot)
        if not first_cycle_done.is_set():
            first_cycle_done.set()

    task = asyncio.create_task(
        cb.main(
            dry_run=dry_run,
            real_account=real_account,
            loop_forever=True,
            on_cycle_end=_on_cycle_end_with_event,
            on_bot_ready=_on_bot_ready,
        )
    )

    # Render de carga hasta que termina el primer ciclo.
    while not first_cycle_done.is_set() and not task.done():
        await _render_hub_once(bot_ref[0])
        await asyncio.sleep(1)

    # Ticker de fondo: refresca el HUB cada 5s independiente de los ciclos.
    ticker = asyncio.create_task(_hub_ticker(bot_ref, interval=5.0))
    try:
        return await task
    finally:
        ticker.cancel()


async def _run(args: argparse.Namespace) -> None:
    import consolidation_bot as cb

    _apply_runtime_config(args)
    hub_readonly = bool(args.hub_readonly)
    run_once = bool(args.once)

    # El HUB se muestra siempre desde el inicio para evitar pantalla en blanco.
    _configure_hub_console(cb)
    await _render_hub_once()

    # En modo HUB no se ejecutan ordenes (dry_run=True), solo lectura/analisis.
    dry_run = hub_readonly

    if hub_readonly:
        # Loop propio: un escaneo (loop_forever=False) → renderizar hub → esperar → repetir.
        # Esto garantiza que el panel se dibuje después de cada ciclo.
        while True:
            try:
                bot = await _run_cycle_with_loading(
                    cb,
                    dry_run=True,
                    real_account=bool(args.real),
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
        if run_once:
            bot = await _run_cycle_with_loading(
                cb,
                dry_run=dry_run,
                real_account=bool(args.real),
            )
        else:
            bot = await _run_forever_with_initial_loading(
                cb,
                dry_run=dry_run,
                real_account=bool(args.real),
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
    finally:
        try:
            from hub.hub_dashboard import HubDashboard
            HubDashboard.shutdown()
        except Exception:
            pass
