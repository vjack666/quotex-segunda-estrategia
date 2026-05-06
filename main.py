import sys
import io
import os
import json
import subprocess
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
_MONITOR_LAUNCH_LOG = ROOT / "data" / "logs" / "bot" / "monitor_launcher.log"


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
            "strat_b": [_candidate_to_dict(c) for c in list(getattr(state, "strat_b_watching", []) or [])],
            "strat_c": [_candidate_to_dict(c) for c in list(getattr(state, "strat_c_watching", []) or [])],
            "gale": {
                "active": bool(getattr(getattr(state, "gale", None), "active", False)),
                "asset": str(getattr(getattr(state, "gale", None), "asset", "") or ""),
                "direction": str(getattr(getattr(state, "gale", None), "direction", "") or ""),
                "secs_remaining": float(getattr(getattr(state, "gale", None), "secs_remaining", 0.0) or 0.0),
            },
        }

        _HUB_RUNTIME_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _HUB_RUNTIME_STATE_FILE.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
    except Exception:
        pass


def _launch_strategy_monitors(enabled: bool) -> list[subprocess.Popen]:
    """Abre 3 consolas (A/B/C) para checklists por estrategia."""
    if (not enabled) or os.name != "nt":
        return []

    monitor_script = ROOT / "src" / "hub_strategy_monitor.py"
    if not monitor_script.exists():
        return []

    procs: list[subprocess.Popen] = []
    creation_flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)

    def _log_launch(msg: str) -> None:
        try:
            _MONITOR_LAUNCH_LOG.parent.mkdir(parents=True, exist_ok=True)
            with _MONITOR_LAUNCH_LOG.open("a", encoding="utf-8") as fh:
                fh.write(f"{_time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
        except Exception:
            pass

    for strategy in ("A", "B", "C"):
        cmd_args = [
            sys.executable,
            "-u",
            str(monitor_script),
            "--strategy",
            strategy,
            "--state-file",
            str(_HUB_RUNTIME_STATE_FILE),
            "--stale-sec",
            "30.0",
        ]
        try:
            p = subprocess.Popen(cmd_args, cwd=str(ROOT), creationflags=creation_flags)
            # Si el proceso cae instantáneamente, usar fallback con cmd/start.
            _time.sleep(0.15)
            if p.poll() is None:
                procs.append(p)
                _log_launch(f"OK new_console strategy={strategy} pid={p.pid}")
                continue
            _log_launch(
                f"WARN new_console exited strategy={strategy} rc={p.poll()} -> fallback cmd/start"
            )

            # Fallback robusto: cmd /c start abre una ventana de consola nueva.
            launch_cmd = (
                f'start "" "{sys.executable}" -u "{monitor_script}" '
                f'--strategy {strategy} --state-file "{_HUB_RUNTIME_STATE_FILE}" '
                f'--stale-sec 30.0'
            )
            subprocess.Popen(["cmd", "/c", launch_cmd], cwd=str(ROOT))
            _log_launch(f"OK cmd_start strategy={strategy}")
        except Exception:
            _log_launch(f"ERROR launch strategy={strategy}")
            continue
    return procs


def _stop_strategy_monitors(procs: list[subprocess.Popen]) -> None:
    """Cierra monitores externos si siguen vivos."""
    for p in procs:
        try:
            if p.poll() is None:
                p.terminate()
        except Exception:
            pass
    for p in procs:
        try:
            if p.poll() is None:
                p.wait(timeout=1.0)
        except Exception:
            try:
                p.kill()
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

    # STRAT-B (Spring Sweep)
    p.add_argument(
        "--strat-b-live",
        action="store_true",
        help="Permitir que STRAT-B abra operaciones (default: solo aviso en terminal)",
    )
    p.add_argument(
        "--strat-b-duration",
        type=int,
        default=300,
        help="Duración en segundos para entradas STRAT-B (fijado en 300)",
    )
    p.add_argument(
        "--strat-b-min-confidence",
        type=float,
        default=0.70,
        help="Confianza mínima [0.0-1.0] para habilitar entrada STRAT-B",
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
    p.add_argument(
        "--hub-multi-monitor",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Abrir monitores A/B/C en consolas separadas con checklist en tiempo real",
    )

    # STRAT-C (Rechazo M1 — 30 segundos)
    p.add_argument(
        "--strat-c-enabled",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Habilitar STRAT-C: rechazo M1 con expiración 60s (en desarrollo)",
    )
    p.add_argument(
        "--strat-c-min-score",
        type=float,
        default=7.0,
        help="Puntuacion minima de confluencia para STRAT-C [0-17] (thesis=7)",
    )
    p.add_argument(
        "--strat-c-wick-atr-min",
        type=float,
        default=0.15,
        help="Wick minimo en unidades de ATR (filtra mechas de ruido)",
    )
    p.add_argument(
        "--strat-c-wick-atr-max",
        type=float,
        default=3.50,
        help="Wick maximo en unidades de ATR (filtra spikes/noticias)",
    )
    return p


def _apply_runtime_config(args: argparse.Namespace) -> None:
    import consolidation_bot as cb
    from martingale_calculator import MartingaleCalculator

    cb.MAX_LOSS_SESSION = float(args.max_loss_session)

    # La gestión de montos ya no usa variables globales del bot; se configura
    # directamente sobre la calculadora dinámica de riesgo.
    # El broker exige monto estrictamente mayor a $1.00.
    MartingaleCalculator.MIN_ORDER_AMOUNT = max(1.01, float(args.amount_initial))
    MartingaleCalculator.INCREMENT = max(0.01, float(args.amount_martin))

    cb.CYCLE_MAX_OPERATIONS = int(args.cycle_ops)
    cb.CYCLE_TARGET_WINS = int(args.cycle_wins)
    cb.CYCLE_TARGET_PROFIT_PCT = float(args.cycle_profit_pct)

    cb.MIN_PAYOUT = int(args.min_payout)
    cb.SCAN_LEAD_SEC = float(args.scan_lead_sec)
    cb.LIVE_SCAN_SLEEP_SEC = max(0.2, float(args.scan_sleep_sec))
    cb.DURATION_SEC = 300
    cb.ADAPTIVE_THRESHOLD_BASE = max(30, min(90, int(args.adaptive_threshold_base)))
    cb.ADAPTIVE_THRESHOLD_LOW = max(30, min(90, int(args.adaptive_threshold_low)))
    cb.ADAPTIVE_THRESHOLD_HIGH = max(30, min(90, int(args.adaptive_threshold_high)))

    cb.STRAT_B_CAN_TRADE = bool(args.strat_b_live)
    cb.STRAT_B_DURATION_SEC = 300
    cb.STRAT_B_MIN_CONFIDENCE = max(0.0, min(1.0, float(args.strat_b_min_confidence)))
    cb.SAME_ASSET_REENTRY_COOLDOWN_SEC = max(0.0, float(args.same_asset_cooldown_sec))
    cb.REJECTION_CALL_MIN_LOWER_WICK = max(0.0, min(1.0, float(args.rejection_call_min_lower_wick)))
    cb.REJECTION_ENTRY_WINDOW_ENABLED = bool(args.rejection_entry_window_enabled)
    cb.REJECTION_ENTRY_WINDOW_START_SEC = max(0, min(59, int(args.rejection_entry_window_start_sec)))
    cb.REJECTION_ENTRY_WINDOW_END_SEC = max(0, min(59, int(args.rejection_entry_window_end_sec)))
    cb.REJECTION_TOTAL_MIN_BODY_RATIO = max(0.0, min(1.0, float(args.rejection_total_min_body)))
    cb.REJECTION_ALLOW_PARTIAL = not bool(args.rejection_disallow_partial)
    cb.STRUCTURE_ENTRY_LOCK_TTL_MIN = max(0.0, float(args.structure_entry_lock_ttl_min))

    # STRAT-C (Rechazo M1 — 30s) — configura el módulo estrategia_30s/detector.py
    try:
        from estrategia_30s import detector as strat_c_detector
        # Set calibrado desde grid-search sobre snapshots reales.
        strat_c_detector.ATR_PERIOD = 7
        strat_c_detector.BB_PERIOD = 14
        strat_c_detector.BB_STD_DEV = 2.0
        strat_c_detector.STOCH_K_PERIOD = 5
        strat_c_detector.STOCH_D_PERIOD = 3
        strat_c_detector.STOCH_SLOW_K_PERIOD = 14
        strat_c_detector.STOCH_SLOW_D_PERIOD = 3
        strat_c_detector.EMA_FAST_PERIOD = 8
        strat_c_detector.EMA_SLOW_PERIOD = 21
        strat_c_detector.SR_LOOKBACK = 40
        strat_c_detector.SR_PIVOT_WINDOW = 2
        strat_c_detector.SR_MERGE_ATR_MULT = 0.3
        strat_c_detector.ZONE_TOLERANCE_ATR_MULT = 1.2
        strat_c_detector.MIN_WICK_TO_BODY_RATIO = 0.8

        strat_c_detector.MIN_SCORE     = max(0.0, float(args.strat_c_min_score))
        strat_c_detector.WICK_ATR_MIN  = max(0.0, float(args.strat_c_wick_atr_min))
        strat_c_detector.WICK_ATR_MAX  = max(0.0, float(args.strat_c_wick_atr_max))
    except ImportError:
        pass  # módulo aún en desarrollo

    cb.STRAT_C_CAN_TRADE = bool(args.strat_c_enabled)

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


async def _hub_ticker(bot_ref: list, interval: float = 0.5) -> None:
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
                # Limpiar el evento para el siguiente ciclo.
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
                        # Timeout corto: el HUB nunca debe quedar esperando red.
                        timeout_sec = 0.35 if trade_triggered else 0.8
                        await asyncio.wait_for(bot.refresh_balance_for_hub(), timeout=timeout_sec)
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

    # Ticker de fondo: refresca el HUB cada 1s independiente de los ciclos.
    ticker = asyncio.create_task(_hub_ticker(bot_ref, interval=0.5))
    try:
        return await task
    finally:
        ticker.cancel()


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

    monitor_procs = _launch_strategy_monitors(bool(args.hub_multi_monitor))

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
        _stop_strategy_monitors(monitor_procs)
        try:
            if _HUB_RUNTIME_STATE_FILE.exists():
                _HUB_RUNTIME_STATE_FILE.unlink()
        except Exception:
            pass


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
