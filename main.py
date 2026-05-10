import sys
import io
import os
import json
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

import time as _time

_DATA_SUBDIRS = ("logs/bot", "logs/broker", "db")
_RETENTION_DAYS = 31
_HUB_RUNTIME_STATE_FILE = ROOT / "data" / "hub_runtime_state.json"


def _write_hub_runtime_snapshot(bot=None) -> None:
    """Escribe un snapshot ligero del HUB para monitores externos (A/B/C)."""
    def _candidate_to_dict(c) -> dict:
        return {
            "strategy": str(getattr(c, "strategy", "") or ""),
            "asset": str(getattr(c, "asset", "") or ""),
            "direction": str(getattr(c, "direction", "") or ""),
            "score": float(getattr(c, "score", 0.0) or 0.0),
            "payout": int(getattr(c, "payout", 0) or 0),
            "zone_floor": float(getattr(c, "zone_floor", 0.0) or 0.0),
            "zone_ceiling": float(getattr(c, "zone_ceiling", 0.0) or 0.0),
            "entry_mode": str(getattr(c, "entry_mode", "") or ""),
            "pattern": str(getattr(c, "pattern", "") or ""),
            "pattern_strength": float(getattr(c, "pattern_strength", 0.0) or 0.0),
            "dist_pct": getattr(c, "dist_pct", None),
            "confidence": getattr(c, "confidence", None),
            "signal_type": getattr(c, "signal_type", None),
            "raw_reason": str(getattr(c, "raw_reason", "") or ""),
            "raw_note": str(getattr(c, "raw_note", "") or ""),
        }

    try:
        from hub.hub_models import HubState

        if bot is not None and hasattr(bot, "hub"):
            state = bot.hub.get_state()
            balance = float(getattr(state, "known_balance", 0.0) or 0.0)
        else:
            state = HubState()
            balance = 0.0

        payload = {
            "generated_at": _time.time(),
            "pid": os.getpid(),
            "total_scans": int(getattr(state, "total_scans", 0) or 0),
            "balance": balance,
            "wins": int(getattr(state, "live_wins", 0) or 0),
            "losses": int(getattr(state, "live_losses", 0) or 0),
            "strat_a": [_candidate_to_dict(c) for c in list(getattr(state, "strat_a_watching", []) or [])],
            "masaniello": {
                "active": bool(getattr(getattr(state, "masaniello", None), "active", False)),
                "asset": str(getattr(getattr(state, "masaniello", None), "asset", "") or ""),
                "direction": str(getattr(getattr(state, "masaniello", None), "direction", "") or ""),
                "cycle_num": int(getattr(getattr(state, "masaniello", None), "cycle_num", 1) or 1),
                "trades_in_cycle": int(getattr(getattr(state, "masaniello", None), "trades_in_cycle", 0) or 0),
                "wins_in_cycle": int(getattr(getattr(state, "masaniello", None), "wins_in_cycle", 0) or 0),
                "next_amount": float(getattr(getattr(state, "masaniello", None), "next_amount", 0.0) or 0.0),
                "total_pnl": float(getattr(getattr(state, "masaniello", None), "total_pnl", 0.0) or 0.0),
            },
        }

        _HUB_RUNTIME_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _HUB_RUNTIME_STATE_FILE.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
    except Exception:
        pass


def _cleanup_old_data_files() -> None:
    """Elimina archivos en data/ con más de 31 días de antigüedad."""
    cutoff = _time.time() - _RETENTION_DAYS * 24 * 3600
    data_dir = ROOT / "data"
    for subdir in _DATA_SUBDIRS:
        target = data_dir / subdir
        if not target.exists():
            continue
        for f in target.iterdir():
            if f.is_file() and f.stat().st_mtime < cutoff:
                try:
                    f.unlink()
                except Exception:
                    pass


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
        default=1.01,
        help="Monto mínimo de orden para la calculadora de riesgo (broker: > $1.00)",
    )
    p.add_argument(
        "--amount-initial-auto",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Calcular monto inicial con fórmula Masaniello (estilo Excel) al detectar saldo",
    )
    p.add_argument(
        "--amount-initial-balance-pct",
        type=float,
        default=1.0,
        help="Fallback porcentual del saldo si la fórmula Masaniello no puede evaluarse",
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
    p.add_argument(
        "--masaniello-excel-mirror",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Escribir W/L en Excel para comparativa en tiempo real",
    )
    p.add_argument(
        "--masaniello-excel-path",
        type=str,
        default=r"C:\Users\v_jac\Documents\Downloads\Masaniello.xlsx",
        help="Ruta del archivo Excel donde se registran W/L",
    )
    p.add_argument(
        "--masaniello-excel-sheet",
        type=str,
        default="Calcolatore",
        help="Hoja del Excel donde se escriben los resultados",
    )
    p.add_argument(
        "--masaniello-excel-column",
        type=str,
        default="B",
        help="Columna (A..Z, AA...) para escribir W/L",
    )
    p.add_argument(
        "--masaniello-excel-start-row",
        type=int,
        default=3,
        help="Fila inicial para comenzar a registrar W/L",
    )

    # Filtros operativos
    p.add_argument(
        "--min-payout",
        type=int,
        default=85,
        help="Payout mínimo base de riesgo (el escaneo usa payout estrictamente mayor)",
    )
    p.add_argument("--scan-lead-sec", type=float, default=35.0, help="Anticipación del scan antes del open")
    p.add_argument(
        "--scan-sleep-sec",
        type=float,
        default=1.0,
        help="Pausa entre ciclos de escaneo live (segundos)",
    )
    p.add_argument(
        "--adaptive-threshold-base",
        type=int,
        default=50,
        help="Umbral base de score para STRAT-A",
    )
    p.add_argument(
        "--adaptive-threshold-low",
        type=int,
        default=48,
        help="Umbral bajo dinámico de score para STRAT-A",
    )
    p.add_argument(
        "--adaptive-threshold-high",
        type=int,
        default=54,
        help="Umbral alto dinámico de score para STRAT-A",
    )

    p.add_argument(
        "--same-asset-cooldown-sec",
        type=float,
        default=65.0,
        help="Enfriamiento mínimo para reentrar el mismo activo tras una entrada exitosa",
    )
    p.add_argument(
        "--rejection-call-min-lower-wick",
        type=float,
        default=0.30,
        help="Mecha inferior mínima [0.0-1.0] para validar rechazo CALL en vela 1m",
    )
    p.add_argument(
        "--rejection-entry-window-enabled",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Habilitar ventana temporal de entrada de rechazo en M1 (segundo 30-41)",
    )
    p.add_argument(
        "--rejection-entry-window-start-sec",
        type=int,
        default=30,
        help="Segundo inicial de ventana temporal para ejecutar rechazo M1",
    )
    p.add_argument(
        "--rejection-entry-window-end-sec",
        type=int,
        default=41,
        help="Segundo final de ventana temporal para ejecutar rechazo M1",
    )
    p.add_argument(
        "--rejection-total-min-body",
        type=float,
        default=0.55,
        help="Body mínimo [0.0-1.0] para clasificar rechazo como total (si no, parcial)",
    )
    p.add_argument(
        "--rejection-disallow-partial",
        action="store_true",
        help="Si se activa, solo permite rechazos totales",
    )
    p.add_argument(
        "--structure-entry-lock-ttl-min",
        type=float,
        default=180.0,
        help="Minutos para bloquear reentrada en la misma estructura (0 desactiva)",
    )
    p.add_argument(
        "--hub-render",
        choices=("auto", "live", "static", "fallback"),
        default="auto",
        help="Modo de render del HUB (auto en Windows usa static para evitar duplicados)",
    )
    return p


def _apply_runtime_config(args: argparse.Namespace) -> None:
    import consolidation_bot as cb
    from src.masaniello_engine import MasanielloConfig

    cb.MAX_LOSS_SESSION = float(args.max_loss_session)
    # Regla operativa: en DEMO nunca detener el loop por stop-loss de sesión.
    if not bool(args.real):
        cb.ENABLE_SESSION_STOP_LOSS = False
        cb.MAX_LOSS_SESSION = 1.0

    # La gestión de montos ahora usa Masaniello Engine en lugar de MartingaleCalculator.
    # El broker exige monto estrictamente mayor a $1.00.
    MasanielloConfig.initial_amount = max(1.01, float(args.amount_initial))
    cb.MASANIELLO_AUTO_INITIAL_FROM_BALANCE = bool(args.amount_initial_auto)
    cb.MASANIELLO_INITIAL_BALANCE_PCT = max(
        0.001,
        min(1.0, float(args.amount_initial_balance_pct) / 100.0),
    )
    # Nota: commission_pct (L5) se usa en lugar de INCREMENT para margen

    # Política fija solicitada: ciclo Masaniello 5 operaciones con objetivo 2 ITM.
    cb.CYCLE_MAX_OPERATIONS = 5
    cb.CYCLE_TARGET_WINS = 2
    cb.CYCLE_TARGET_PROFIT_PCT = float(args.cycle_profit_pct)
    cb.MASANIELLO_EXCEL_MIRROR_ENABLED = bool(args.masaniello_excel_mirror)
    cb.MASANIELLO_EXCEL_MIRROR_PATH = str(args.masaniello_excel_path)
    cb.MASANIELLO_EXCEL_MIRROR_SHEET = str(args.masaniello_excel_sheet)
    cb.MASANIELLO_EXCEL_MIRROR_COLUMN = str(args.masaniello_excel_column).strip().upper() or "A"
    cb.MASANIELLO_EXCEL_MIRROR_START_ROW = max(1, int(args.masaniello_excel_start_row))

    cb.MIN_PAYOUT = int(args.min_payout)
    cb.SCAN_LEAD_SEC = float(args.scan_lead_sec)
    cb.LIVE_SCAN_SLEEP_SEC = max(0.2, float(args.scan_sleep_sec))
    cb.DURATION_SEC = 300
    cb.ADAPTIVE_THRESHOLD_BASE = max(30, min(90, int(args.adaptive_threshold_base)))
    cb.ADAPTIVE_THRESHOLD_LOW = max(30, min(90, int(args.adaptive_threshold_low)))
    cb.ADAPTIVE_THRESHOLD_HIGH = max(30, min(90, int(args.adaptive_threshold_high)))

    # STRAT-B se mantiene archivada temporalmente (sin ejecución desde main).
    cb.STRAT_B_CAN_TRADE = False
    cb.STRAT_B_DURATION_SEC = 300
    cb.SAME_ASSET_REENTRY_COOLDOWN_SEC = max(0.0, float(args.same_asset_cooldown_sec))
    cb.REJECTION_CALL_MIN_LOWER_WICK = max(0.0, min(1.0, float(args.rejection_call_min_lower_wick)))
    cb.REJECTION_ENTRY_WINDOW_ENABLED = bool(args.rejection_entry_window_enabled)
    cb.REJECTION_ENTRY_WINDOW_START_SEC = max(0, min(59, int(args.rejection_entry_window_start_sec)))
    cb.REJECTION_ENTRY_WINDOW_END_SEC = max(0, min(59, int(args.rejection_entry_window_end_sec)))
    cb.REJECTION_TOTAL_MIN_BODY_RATIO = max(0.0, min(1.0, float(args.rejection_total_min_body)))
    cb.REJECTION_ALLOW_PARTIAL = not bool(args.rejection_disallow_partial)
    cb.STRUCTURE_ENTRY_LOCK_TTL_MIN = max(0.0, float(args.structure_entry_lock_ttl_min))

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
        _write_hub_runtime_snapshot(bot)
    except Exception:
        pass


def _configure_hub_console(cb) -> None:
    """Reduce el ruido del logger en consola para que el dashboard quede visible."""
    # Desactivar contador inline para no mezclar texto con el render del HUB.
    if hasattr(cb, "INLINE_COUNTDOWN_STDOUT"):
        cb.INLINE_COUNTDOWN_STDOUT = False
    if hasattr(cb, "INLINE_COUNTDOWN_LOG_TICKS"):
        cb.INLINE_COUNTDOWN_LOG_TICKS = False

    # Handler de consola definido en consolidation_bot.py
    stdout_handler = getattr(cb, "_stdout_handler", None)
    if stdout_handler is not None:
        stdout_handler.setLevel(logging.ERROR)

    # Mantener logs de archivo en INFO para forensia/sentinel.
    bot_log = getattr(cb, "log", None)
    if bot_log is not None:
        bot_log.setLevel(logging.INFO)

    # Root logger y librerias ruidosas
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
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


_SILENT_RECONNECT_INTERVAL_SEC = 600  # reconexión preventiva cada 10 min
_HUB_TICK_INTERVAL_SEC = 0.25
_HUB_BALANCE_REFRESH_EVERY_SEC = 2.0


async def _silent_reconnect_watchdog(bot_ref: list) -> None:
    """Reconexión silenciosa preventiva cada 10 min o al recibir WIN/LOSS.
    Nunca interrumpe el loop principal; si falla, reintenta en el siguiente ciclo.
    """
    last_reconnect = _time.time()
    while True:
        try:
            bot = bot_ref[0] if bot_ref else None
            trade_event = None
            if bot is not None and hasattr(bot, "hub") and hasattr(bot.hub, "trade_result_event"):
                trade_event = bot.hub.trade_result_event

            # Esperar lo que llegue primero: WIN/LOSS o el intervalo de 10 min
            remaining = max(5.0, _SILENT_RECONNECT_INTERVAL_SEC - (_time.time() - last_reconnect))
            if trade_event is not None:
                sleep_task = asyncio.create_task(asyncio.sleep(remaining))
                event_wait = asyncio.create_task(trade_event.wait())
                done, pending = await asyncio.wait(
                    {sleep_task, event_wait},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for t in pending:
                    t.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
                triggered_by_trade = event_wait in done and event_wait.done() and not event_wait.cancelled()
            else:
                await asyncio.sleep(remaining)
                triggered_by_trade = False

            bot = bot_ref[0] if bot_ref else None
            if bot is None:
                continue

            # No reconectar si hay operación activa para no interrumpir un trade en vuelo
            m = getattr(getattr(bot, "hub", None), "state", None)
            is_active = getattr(getattr(m, "masaniello", None), "active", False) if m else False
            if is_active and not triggered_by_trade:
                continue

            reason = "trade WIN/LOSS" if triggered_by_trade else "preventiva 10min"
            try:
                ok = await asyncio.wait_for(bot.ensure_connection(), timeout=20.0)
                if ok:
                    pass  # silenciosa — no log de consola; el HUB muestra estado actualizado
                else:
                    import logging as _log_mod
                    _log_mod.getLogger(__name__).warning("[watchdog] Reconexión %s falló; reintentará en breve", reason)
            except Exception:
                pass

            last_reconnect = _time.time()

        except asyncio.CancelledError:
            return
        except Exception:
            await asyncio.sleep(10.0)


async def _hub_ticker(bot_ref: list, interval: float = _HUB_TICK_INTERVAL_SEC) -> None:
    """Refresca el HUB en segundo plano cada `interval` segundos sin esperar ciclos.
    Si llega un resultado de trade (WIN/LOSS) antes del intervalo, re-renderiza al instante.
    """
    last_balance_refresh_ts = 0.0
    while True:
        try:
            bot = bot_ref[0] if bot_ref else None

            # Obtener el evento del scanner si está disponible.
            trade_event = None
            if bot is not None and hasattr(bot, 'hub') and hasattr(bot.hub, 'trade_result_event'):
                trade_event = bot.hub.trade_result_event

            trade_triggered = False
            if trade_event is not None:
                # Esperar lo que llegue primero: resultado de trade o el intervalo normal.
                sleep_task = asyncio.create_task(asyncio.sleep(interval))
                event_wait = asyncio.create_task(trade_event.wait())
                done, pending = await asyncio.wait(
                    {sleep_task, event_wait},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                trade_triggered = event_wait in done and event_wait.done() and not event_wait.cancelled()
                for t in pending:
                    t.cancel()
                if pending:
                    await asyncio.gather(*pending, return_exceptions=True)
                    # Limpiar SOLO si este ciclo realmente consumió el evento.
                    # Si otro trade terminó justo entre wait() y aquí, su señal se preserva.
                    if trade_triggered:
                        trade_event.clear()
            else:
                await asyncio.sleep(interval)

            bot = bot_ref[0] if bot_ref else None
            if bot is not None:
                # Render inmediato al cerrar trade para evitar sensación de "congelado".
                if trade_triggered:
                    await _render_hub_once(bot)
                if hasattr(bot, "refresh_balance_for_hub"):
                    try:
                        # Refrescar balance en cadencia separada evita congelar el reloj del HUB.
                        now_ts = _time.time()
                        should_refresh_balance = (
                            trade_triggered
                            or (now_ts - last_balance_refresh_ts) >= _HUB_BALANCE_REFRESH_EVERY_SEC
                        )
                        if should_refresh_balance:
                            timeout_sec = 0.25 if trade_triggered else 0.35
                            await asyncio.wait_for(bot.refresh_balance_for_hub(), timeout=timeout_sec)
                            last_balance_refresh_ts = now_ts
                    except Exception:
                        pass
                await _render_hub_once(bot)
        except asyncio.CancelledError:
            return
        except Exception:
            pass


async def _run_forever_with_initial_loading(cb, *, dry_run: bool, real_account: bool):
    """Ejecuta loop continuo mostrando el HUB hasta finalizar el primer ciclo."""
    first_cycle_done = asyncio.Event()
    bot_ready_event = asyncio.Event()
    # Referencia mutable al bot para que el ticker siempre use la instancia actual.
    bot_ref: list = [None]
    # Referencia mutable al HTFScanner (se crea más abajo, antes de on_bot_ready).
    htf_ref: list = [None]

    def _on_bot_ready(bot):
        """Llamado apenas el bot se conecta y conoce el balance (antes del primer scan)."""
        bot_ref[0] = bot
        # Conectar el client real al HTFScanner y exponerlo en el bot.
        htf = htf_ref[0]
        if htf is not None:
            htf._client = bot.client
            bot.htf_scanner = htf
        bot_ready_event.set()

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
    # Ticker permanente: arranca de inmediato, independiente del primer ciclo.
    # Así el dashboard es visible desde el primer segundo, aunque el scan aún no termine.
    ticker = asyncio.create_task(_hub_ticker(bot_ref, interval=_HUB_TICK_INTERVAL_SEC))
    watchdog = asyncio.create_task(_silent_reconnect_watchdog(bot_ref))

    # HTF Scanner: corre en background, refresca velas 15m cada ~15 min.
    # El scan loop las lee vía bot.htf_scanner.get_candles_15m(sym) sin bloquear.
    from src.htf_scanner import HTFScanner

    def _on_htf_asset_refresh(asset: str, payout: int, candles: int, age_sec: float, ttl_sec: float, ts: float) -> None:
        bot = bot_ref[0]
        if bot is None or not hasattr(bot, "hub"):
            return
        try:
            lib_size = int(htf_scanner.library_size())
            bot.hub.update_htf_status(
                asset=asset,
                payout=payout,
                candles=candles,
                library_size=lib_size,
                cache_age_sec=age_sec,
                cache_ttl_sec=ttl_sec,
                refreshed_at_ts=ts,
            )
        except Exception:
            return

    htf_scanner = HTFScanner(
        client=None,
        min_payout=int(getattr(cb, "MIN_PAYOUT", 85)),
        on_asset_refresh=_on_htf_asset_refresh,
    )
    htf_ref[0] = htf_scanner   # on_bot_ready ya puede conectar el client cuando el bot esté listo

    # El HTF scanner arranca apenas el bot tenga client; no usa espera fija.
    async def _htf_runner():
        await bot_ready_event.wait()
        await htf_scanner.run_forever()

    htf_task = asyncio.create_task(_htf_runner(), name="htf_scanner_15m")

    try:
        # Render de carga hasta que termina el primer ciclo.
        while not first_cycle_done.is_set() and not task.done():
            await _render_hub_once(bot_ref[0])
            await asyncio.sleep(1)

        return await task

    finally:
        ticker.cancel()
        watchdog.cancel()
        htf_task.cancel()
        await asyncio.gather(ticker, watchdog, htf_task, return_exceptions=True)


async def _run(args: argparse.Namespace) -> None:
    # Limpiar archivos de data/ anteriores a 31 días
    _cleanup_old_data_files()

    # Crear directorio de logs del broker y cambiar CWD ANTES de importar
    # consolidation_bot (que a su vez importa pyquotex/api_quotex, la cual
    # registra el sink de loguru con ruta relativa al CWD actual).
    _broker_log_dir = ROOT / "data" / "logs" / "broker"
    _broker_log_dir.mkdir(parents=True, exist_ok=True)
    _orig_cwd = os.getcwd()
    os.chdir(_broker_log_dir)
    import consolidation_bot as cb
    os.chdir(_orig_cwd)

    _apply_runtime_config(args)
    hub_readonly = bool(args.hub_readonly)
    run_once = bool(args.once)

    from hub.hub_dashboard import HubDashboard
    render_mode = str(args.hub_render or "auto").strip().lower()
    if render_mode == "auto":
        # En PowerShell/Windows, fallback ANSI es el más estable y evita
        # duplicados visuales de bloques Rich en refresh continuo.
        render_mode = "fallback" if os.name == "nt" else "live"
    HubDashboard.configure(render_mode)

    # El HUB se muestra siempre desde el inicio para evitar pantalla en blanco.
    _configure_hub_console(cb)
    await _render_hub_once()

    # En modo HUB no se ejecutan ordenes (dry_run=True), solo lectura/analisis.
    dry_run = hub_readonly

    try:
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
                except RuntimeError as exc:
                    print(f"[HUB] Error recuperable: {exc}. Reintentando en 60s...")
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
    finally:
        try:
            if _HUB_RUNTIME_STATE_FILE.exists():
                _HUB_RUNTIME_STATE_FILE.unlink()
        except Exception:
            pass


if __name__ == "__main__":
    parser = _build_parser()
    args = parser.parse_args()
    run_once = bool(args.once)
    demo_mode = not bool(args.real)
    restart_count = 0
    max_consecutive_errors = 99999  # Sin límite — modo continuo de recolección de datos
    
    while True:
        try:
            print(f"\n{'='*80}")
            if restart_count > 0:
                print(f"[BOT] Iniciando intento #{restart_count+1}...")
            else:
                print(f"[BOT] Iniciando bot en modo 24/7...")
            print(f"{'='*80}\n")
            
            asyncio.run(_run(args))
            
            # Si llegamos aquí sin error, el bot terminó limpiamente (--once)
            if run_once:
                raise SystemExit(0)
            
            # Si no es --once pero termino, algo inesperado pasó
            restart_count += 1
            if restart_count >= max_consecutive_errors:
                print(f"\n[ERROR] El bot ha fallado {restart_count} veces consecutivas.")
                print("Revisar los logs en data/logs/bot/ para más detalles.")
                raise SystemExit(1)
            _time.sleep(5)
            print(f"\n[BOT] Reiniciando en 5 segundos (intento {restart_count+1}/{max_consecutive_errors})...\n")
            
        except ModuleNotFoundError as exc:
            if getattr(exc, "name", "") == "pyquotex":
                venv_python = ROOT / ".venv" / "Scripts" / "python.exe"
                print("\n[ERROR] Falta el modulo 'pyquotex' en el Python actual.")
                print("Ejecuta el bot con el entorno virtual del proyecto:")
                print(f'  "{venv_python}" main.py')
                print("O instala dependencias en el entorno actual:")
                print("  python -m pip install -r requirements.txt")
                raise SystemExit(1)
            raise
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 1
            # Blindaje DEMO: cualquier salida no-cero reinicia el supervisor.
            if demo_mode and not run_once and code != 0:
                restart_count += 1
                _time.sleep(5)
                print(
                    f"\n[BOT] SystemExit({code}) capturado en DEMO. "
                    f"Reiniciando en 5s (intento {restart_count+1}/{max_consecutive_errors})...\n"
                )
                continue
            raise
        except KeyboardInterrupt:
            print("\n[BOT] Interrupción del usuario (Ctrl+C). Cerrando...")
            raise SystemExit(0)
        except Exception as e:
            restart_count += 1
            if restart_count >= max_consecutive_errors:
                print(f"\n[ERROR] El bot ha fallado {restart_count} veces consecutivas.")
                print(f"Última excepción: {type(e).__name__}: {e}")
                print("Revisar los logs en data/logs/bot/ para más detalles.")
                raise SystemExit(1)
            _time.sleep(5)
            print(f"\n[BOT] Error inesperado: {type(e).__name__}: {e}")
            print(f"Reiniciando en 5 segundos (intento {restart_count+1}/{max_consecutive_errors})...\n")
        finally:
            try:
                from hub.hub_dashboard import HubDashboard
                HubDashboard.shutdown()
            except Exception:
                pass

