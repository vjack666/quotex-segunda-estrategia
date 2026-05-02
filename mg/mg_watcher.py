"""
mg/mg_watcher.py — GaleWatcher

Vigila una operación binaria abierta de 5 minutos.
Monitorea el precio actual vs precio de entrada para saber si va
ganando o perdiendo, y dispara un gale EXACTAMENTE 1 segundo antes
de que cierre la vela, usando las reglas del MartingaleCalculator.

Flujo:
    1. El bot abre una orden → crea un TradeInfo y llama watcher.watch(trade)
    2. GaleWatcher hace loop cada POLL_INTERVAL_SEC
    3. Muestra en log: tiempo restante, precio actual, P/L estimado
    4. Cuando secs_left <= GALE_TRIGGER_SEC → si perdiendo → dispara gale
    5. El gale es una nueva orden: mismo activo, misma dirección, duración GALE_DURATION_SEC
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

log = logging.getLogger(__name__)

# ── Parámetros del watcher ─────────────────────────────────────────────────

# Cada cuántos segundos se consulta el precio mientras la operación está en curso.
# Se mantiene en 1s para que el panel y el contador del gale avancen fluidos.
POLL_INTERVAL_SEC = 1.0

# Cuándo cambiar a modo "últimos instantes" (polling más rápido)
FAST_POLL_THRESHOLD_SEC = 10.0
FAST_POLL_INTERVAL_SEC = 1.0

# Segundos antes del cierre en que se dispara el gale (fallback si el próximo
# boundary de 5 min cae después de la expiración)
GALE_TRIGGER_SEC = 1.0

# Cuadrícula de 5 minutos (24 h ÷ 5 min = 288 slots en UTC)
GALE_5M_TF_SEC = 300

# Offset post-open: igual al que usa el bot principal para entrar justo después
# del open de vela OTC (evita el spike del primer tick)
GALE_OTC_POST_OPEN_SEC = 0.20

# Duración de la orden gale en segundos (igual que la operación base)
GALE_DURATION_SEC = 300

# Porcentaje mínimo en contra para considerar que "va perdiendo"
# 0.0 = cualquier tick en contra dispara el gale
LOSING_THRESHOLD_PCT = 0.0

# Máximo de segundos para lectura de precio en cada tick del watcher.
# Se mantiene por debajo de 1s para que el reloj avance de forma fluida.
PRICE_FETCH_TIMEOUT_SEC = 0.85

# Máximo de intentos de obtener precio cuando se está en ventana crítica
PRICE_FETCH_RETRIES_CRITICAL = 3

# Reintentos de disparo del gale en la ventana final si hubo fallo técnico.
GALE_MAX_TRIGGER_ATTEMPTS = 3
GALE_RETRY_INTERVAL_SEC = 1.0

# Guardia de sanidad de precio durante vigilancia del trade.
# Si el precio se desvía demasiado del entry en una operación de 5m,
# se asume contaminación de feed y se ignora ese tick.
MAX_TRADE_PRICE_DEVIATION_PCT = 0.20


# ── Tipos de callback ──────────────────────────────────────────────────────

# Firma: async fetch_price(asset: str) -> Optional[float]
FetchPriceFn = Callable[[str], Awaitable[Optional[float]]]

# Firma: async place_order(asset, direction, amount, duration, account_type)
#        -> (success: bool, order_id: str, open_price: float, order_ref: int, error: str)
PlaceOrderFn = Callable[..., Awaitable[tuple]]

# Firma: get_balance() -> float  (puede ser sync o async)
GetBalanceFn = Callable[[], float | Awaitable[float]]


# Firma: async/sync on_status(**campos) -> None  (notifica al hub en cada tick)
OnStatusFn = Optional[Callable[..., None]]
# Firma: async/sync on_clear() -> None (limpia estado del hub al terminar)
OnClearFn  = Optional[Callable[[], None]]


# ── Data ───────────────────────────────────────────────────────────────────

@dataclass
class TradeInfo:
    """Información de la operación activa que el watcher vigila."""
    asset:        str
    direction:    str    # "call" | "put"
    amount:       float
    entry_price:  float
    opened_at:    float  # time.time() del momento de apertura
    duration_sec: int    # normalmente 300 (5 min)
    payout:       int    # porcentaje, ej: 85
    order_id:     str    = ""
    order_ref:    int    = 0
    account_type: str    = "PRACTICE"

    @property
    def expires_at(self) -> float:
        return self.opened_at + self.duration_sec

    @property
    def secs_remaining(self) -> float:
        return max(0.0, self.expires_at - time.time())

    @property
    def secs_elapsed(self) -> float:
        return time.time() - self.opened_at

    def is_losing(self, current_price: float) -> bool:
        """True si el precio actual implica que la operación va perdiendo."""
        if current_price <= 0:
            return False
        if self.direction == "call":
            # Compramos → perdiendo si precio bajó
            threshold = self.entry_price * (1.0 - LOSING_THRESHOLD_PCT)
            return current_price < threshold
        else:
            # Vendemos → perdiendo si precio subió
            threshold = self.entry_price * (1.0 + LOSING_THRESHOLD_PCT)
            return current_price > threshold

    def pnl_description(self, current_price: float) -> str:
        """Texto corto de P/L: dirección, variación de precio e implicancia."""
        if current_price <= 0 or self.entry_price <= 0:
            return "sin precio"
        diff = current_price - self.entry_price
        pct  = diff / self.entry_price * 100.0
        arrow = "↑" if diff > 0 else "↓"
        estado = "GANANDO" if not self.is_losing(current_price) else "PERDIENDO"
        return f"{arrow} {abs(pct):.4f}% ({self.direction.upper()}) → {estado}"


# ── GaleWatcher ────────────────────────────────────────────────────────────

class GaleWatcher:
    """
    Vigila una operación binaria abierta y dispara un gale en T-1s si va perdiendo.

    Parámetros:
        fetch_price_fn: coroutine que devuelve el precio actual del activo
        place_order_fn: coroutine que coloca una orden en el broker
        calculator:     instancia de MartingaleCalculator para calcular el monto del gale
        get_balance_fn: función (sync o async) que devuelve el saldo actual
        dry_run:        si True, simula el gale sin enviar al broker
    """

    def __init__(
        self,
        fetch_price_fn:   FetchPriceFn,
        place_order_fn:   PlaceOrderFn,
        calculator,
        get_balance_fn:   GetBalanceFn,
        dry_run:          bool = False,
        on_status_fn:     OnStatusFn = None,
        on_clear_fn:      OnClearFn  = None,
    ) -> None:
        self._fetch_price  = fetch_price_fn
        self._place_order  = place_order_fn
        self._calculator   = calculator
        self._get_balance  = get_balance_fn
        self.dry_run       = dry_run
        self._on_status    = on_status_fn   # llamado en cada tick con estado del gale
        self._on_clear     = on_clear_fn    # llamado al terminar la vigilancia
        self.gale_fired    = False   # bandera: ya se disparó el gale en esta sesión

    # ── callback helpers ─────────────────────────────────────────────────

    def _notify_status(self, trade: TradeInfo, price: Optional[float],
                       gale_amount: float = 0.0, gale_fired: bool = False,
                       gale_success: bool = False, gale_order_id: str = "") -> None:
        """Llama a on_status_fn si está configurado; ignora errores."""
        if self._on_status is None:
            return
        current = price if price is not None else 0.0
        delta = 0.0
        if trade.entry_price > 0 and current > 0:
            delta = (current - trade.entry_price) / trade.entry_price * 100.0
        try:
            result = self._on_status(
                active=True,
                asset=trade.asset,
                direction=trade.direction,
                entry_price=trade.entry_price,
                current_price=current,
                secs_remaining=trade.secs_remaining,
                duration_sec=trade.duration_sec,
                payout=trade.payout,
                amount_invested=trade.amount,
                gale_amount=gale_amount,
                is_losing=trade.is_losing(current) if current > 0 else False,
                delta_pct=delta,
                gale_fired=gale_fired,
                gale_success=gale_success,
                gale_order_id=gale_order_id,
            )
            if asyncio.iscoroutine(result):
                asyncio.ensure_future(result)
        except Exception as exc:
            log.debug("GaleWatcher: error en on_status_fn: %s", exc)

    def _notify_clear(self) -> None:
        """Llama a on_clear_fn si está configurado; ignora errores."""
        if self._on_clear is None:
            return
        try:
            result = self._on_clear()
            if asyncio.iscoroutine(result):
                asyncio.ensure_future(result)
        except Exception as exc:
            log.debug("GaleWatcher: error en on_clear_fn: %s", exc)

    # ── helpers ──────────────────────────────────────────────────────────

    def _next_5m_boundary_ts(self, from_ts: Optional[float] = None) -> float:
        """
        Timestamp UTC del próximo open de vela de 5 minutos en la cuadrícula global.
        Las 24 horas están divididas en 288 slots fijos de 300 segundos desde epoch.
        Se suma GALE_OTC_POST_OPEN_SEC para entrar justo después del open (igual que
        la estrategia principal).
        """
        anchor = float(from_ts if from_ts is not None else time.time())
        return ((int(anchor) // GALE_5M_TF_SEC) + 1) * GALE_5M_TF_SEC + GALE_OTC_POST_OPEN_SEC

    async def _current_price(self, asset: str) -> Optional[float]:
        """Obtiene precio con timeout y manejo de errores."""
        try:
            return await asyncio.wait_for(
                self._fetch_price(asset),
                timeout=PRICE_FETCH_TIMEOUT_SEC,
            )
        except (asyncio.TimeoutError, Exception) as exc:
            log.debug("GaleWatcher: no se pudo obtener precio de %s: %s", asset, exc)
            return None

    def _sanitize_trade_price(
        self,
        trade: TradeInfo,
        price: Optional[float],
        last_good_price: Optional[float],
    ) -> Optional[float]:
        """Filtra ticks contaminados para evitar falsas lecturas de GANANDO/PERDIENDO."""
        if price is None or price <= 0:
            return last_good_price

        # Capa 1: desviación absurda vs precio de entrada del trade.
        if trade.entry_price > 0:
            dev_from_entry = abs(price - trade.entry_price) / trade.entry_price
            if dev_from_entry > MAX_TRADE_PRICE_DEVIATION_PCT:
                log.warning(
                    "⚠ GaleWatcher %s: precio contaminado %.6f (desvío %.1f%% vs entry %.6f) — ignorado",
                    trade.asset, price, dev_from_entry * 100.0, trade.entry_price,
                )
                return last_good_price

        # Capa 2: salto absurdo vs último tick válido.
        if last_good_price and last_good_price > 0:
            dev_from_last = abs(price - last_good_price) / last_good_price
            if dev_from_last > 0.05:
                log.warning(
                    "⚠ GaleWatcher %s: salto contaminado %.6f (delta %.1f%% vs último %.6f) — ignorado",
                    trade.asset, price, dev_from_last * 100.0, last_good_price,
                )
                return last_good_price

        return price

    async def _balance(self) -> Optional[float]:
        try:
            result = self._get_balance()
            if asyncio.iscoroutine(result):
                return float(await result)
            return float(result)
        except Exception as exc:
            log.debug("GaleWatcher: error obteniendo balance: %s", exc)
            return None

    def _gale_amount(self, payout: int, balance: Optional[float]) -> Optional[float]:
        """
        Calcula el monto del gale usando MartingaleCalculator.
        Devuelve None si no se puede calcular (riesgo excedido, etc.).
        """
        if balance is not None:
            try:
                self._calculator.set_balance(balance)
            except Exception:
                pass

        try:
            amount, status = self._calculator.calculate_investment(payout)
        except Exception as exc:
            log.error("GaleWatcher: error en MartingaleCalculator: %s", exc)
            return None

        if status == "OK":
            return amount
        if status == "CYCLE_COMPLETE":
            log.info("GaleWatcher: ciclo completo — no se requiere gale")
            return None
        if "RISK_EXCEEDED" in status:
            log.warning(
                "GaleWatcher: monto del gale excede límite de riesgo (%s) — gale cancelado",
                status,
            )
            return None
        if status.startswith("ERROR"):
            log.error("GaleWatcher: error en calculadora: %s", status)
            return None

        # Cualquier otro status: igual retornar monto si es > 0
        if amount > 0:
            log.warning("GaleWatcher: calculadora retornó status '%s' pero amount=%.2f — usando", status, amount)
            return amount
        return None

    # ── loop principal ────────────────────────────────────────────────────

    async def watch(self, trade: TradeInfo) -> None:
        """
        Corre el loop de vigilancia para `trade` hasta que expira.
        Dispara el gale en el próximo open de vela de 5 minutos (cuadrícula UTC),
        siempre que ese boundary caiga ANTES de la expiración de la operación.
        Si el próximo 5m está después de la expiración, usa T-1s como fallback.

        Debe ejecutarse como tarea en background:
            asyncio.create_task(watcher.watch(trade))
        """
        self.gale_fired = False
        asset     = trade.asset
        direction = trade.direction
        last_good_price: Optional[float] = None

        # ── calcular targets de disparo ───────────────────────────────────
        # Target primario: próximo open de 5m calculado desde la hora del ticket
        # (opened_at), no desde "ahora", para evitar drift visual/operativo.
        # Target final: T-1s como red de seguridad para no perder el gale.
        primary_target_ts = self._next_5m_boundary_ts(trade.opened_at)
        final_target_ts = max(trade.opened_at, trade.expires_at - GALE_TRIGGER_SEC)
        use_primary_target = primary_target_ts < trade.expires_at

        if not use_primary_target:
            log.info(
                "🔍 GaleWatcher iniciado | %s %s $%.2f | entry=%.6f | cierre en %.0fs "
                "| target=T-1s (fallback: próximo 5m después de expiración)",
                asset, direction.upper(), trade.amount, trade.entry_price, trade.secs_remaining,
            )
        else:
            secs_to_target = primary_target_ts - time.time()
            log.info(
                "🔍 GaleWatcher iniciado | %s %s $%.2f | entry=%.6f | cierre en %.0fs "
                "| target=próximo 5m en %.0fs",
                asset, direction.upper(), trade.amount, trade.entry_price,
                trade.secs_remaining, secs_to_target,
            )

        primary_attempted = False
        trigger_attempts = 0
        next_retry_ts = 0.0

        # ── loop de monitoreo ────────────────────────────────────────────
        while True:
            tick_started = time.time()
            secs_left = trade.secs_remaining
            now = time.time()

            # Operación ya expiró — terminar loop
            if secs_left <= 0:
                log.info("GaleWatcher: %s expiró — loop terminado", asset)
                self._notify_clear()
                return

            # ── obtener precio actual ────────────────────────────────────
            raw_price = await self._current_price(asset)
            display_price = self._sanitize_trade_price(trade, raw_price, last_good_price)
            if display_price is not None:
                last_good_price = display_price

            if display_price is not None:
                estado = trade.pnl_description(display_price)
                log.info(
                    "🕐 GaleWatcher %s | %.0fs restantes | precio=%.6f | %s",
                    asset, secs_left, display_price, estado,
                )
            else:
                log.debug("GaleWatcher %s | %.0fs restantes | precio no disponible", asset, secs_left)

            # Notificar al hub con el estado actual
            self._notify_status(trade, display_price)

            # ── ventanas de disparo ───────────────────────────────────────
            should_try = False
            reason = ""
            if use_primary_target and (not primary_attempted) and now >= primary_target_ts:
                primary_attempted = True
                should_try = True
                reason = "target_5m"
            elif now >= final_target_ts and now >= next_retry_ts and trigger_attempts < GALE_MAX_TRIGGER_ATTEMPTS:
                should_try = True
                reason = "target_final"

            if should_try and not self.gale_fired:
                outcome = await self._fire_gale(trade, display_price)
                if outcome == "sent":
                    # Después del disparo, esperar hasta expiración y salir
                    await asyncio.sleep(max(0.0, trade.secs_remaining + 1.0))
                    self._notify_clear()
                    return

                # Sólo reintentar si fue problema técnico (precio o envío).
                if outcome in ("no_price", "failed_send"):
                    trigger_attempts += 1
                    next_retry_ts = time.time() + GALE_RETRY_INTERVAL_SEC
                    log.warning(
                        "GaleWatcher %s: intento %d/%d sin envío (%s, %s)",
                        asset,
                        trigger_attempts,
                        GALE_MAX_TRIGGER_ATTEMPTS,
                        reason,
                        outcome,
                    )

            # ── determinar intervalo de polling ───────────────────────────
            next_target = final_target_ts
            if use_primary_target and not primary_attempted:
                next_target = min(primary_target_ts, final_target_ts)
            secs_to_target = max(0.0, next_target - time.time())
            if secs_to_target <= FAST_POLL_THRESHOLD_SEC:
                base_sleep = FAST_POLL_INTERVAL_SEC
            else:
                # Dormir sin pasarnos del umbral rápido antes del target
                base_sleep = min(POLL_INTERVAL_SEC, secs_to_target - FAST_POLL_THRESHOLD_SEC)
                base_sleep = max(FAST_POLL_INTERVAL_SEC, base_sleep)

            # Compensa el tiempo gastado en fetch/log para sostener cadencia ~1s.
            elapsed = time.time() - tick_started
            sleep_for = max(0.05, base_sleep - elapsed)
            await asyncio.sleep(sleep_for)

    # ── disparo de gale ──────────────────────────────────────────────────

    async def _fire_gale(self, trade: TradeInfo, last_price: Optional[float]) -> str:
        """Evalúa si corresponde disparar el gale y lo envía al broker.

        Retorna:
            "sent": el broker aceptó el gale.
            "skipped_win": no corresponde (la operación base va ganando).
            "invalid_amount": calculadora devolvió monto inválido.
            "no_price": no fue posible obtener precio.
            "failed_send": se intentó enviar pero el broker lo rechazó o falló.
        """
        asset     = trade.asset
        direction = trade.direction

        # ── reintentar precio si no teníamos ──────────────────────────────
        price = last_price
        if price is None:
            for attempt in range(1, PRICE_FETCH_RETRIES_CRITICAL + 1):
                price = await self._current_price(asset)
                if price is not None:
                    break
                log.debug("GaleWatcher: reintento de precio %d/%d", attempt, PRICE_FETCH_RETRIES_CRITICAL)
                await asyncio.sleep(0.3)

        # ── decidir si corresponde el gale ────────────────────────────────
        if price is None:
            log.warning(
                "⚠ GaleWatcher %s: no se pudo obtener precio al cierre — "
                "disparando gale preventivo (sin confirmar P/L)",
                asset,
            )
            # Decidimos conservadoramente NO disparar si no tenemos precio
            log.info("GaleWatcher: gale cancelado por falta de precio")
            return "no_price"

        if not trade.is_losing(price):
            log.info(
                "✅ GaleWatcher %s: en GANANCIA al cierre (%.6f vs entry %.6f) — "
                "gale NO requerido",
                asset, price, trade.entry_price,
            )
            return "skipped_win"

        # ── calcular monto del gale ───────────────────────────────────────
        balance = await self._balance()
        amount  = self._gale_amount(trade.payout, balance)

        if amount is None or amount <= 0:
            log.warning(
                "⚠ GaleWatcher %s: gale necesario pero monto inválido (%.2f) — cancelado",
                asset, amount or 0.0,
            )
            return "invalid_amount"

        diff_pct = (price - trade.entry_price) / trade.entry_price * 100.0
        log.warning(
            "🚨 GALE DISPARADO | %s %s | entry=%.6f actual=%.6f (%.4f%%) | "
            "monto=$%.2f | balance=$%.2f | target 5m",
            asset, direction.upper(),
            trade.entry_price, price, diff_pct,
            amount, balance or 0.0,
        )

        # ── colocar la orden ─────────────────────────────────────────────
        self.gale_fired = True

        if self.dry_run:
            log.info(
                "  [DRY-RUN GALE] %s %s $%.2f %ds",
                direction.upper(), asset, amount, GALE_DURATION_SEC,
            )
            return "sent"

        try:
            success, order_id, open_price, order_ref, error = await self._place_order(
                asset=asset,
                direction=direction,
                amount=amount,
                duration=GALE_DURATION_SEC,
                account_type=trade.account_type,
            )
        except Exception as exc:
            log.error("GaleWatcher: excepción colocando gale: %s", exc)
            self.gale_fired = False  # Permitir reintento si hay tiempo
            return "failed_send"

        if success:
            log.info(
                "✅ GALE COLOCADO | %s %s $%.2f | order_id=%s open_price=%.6f",
                asset, direction.upper(), amount, order_id, open_price,
            )
            # Notificar al hub que el gale fue disparado
            self._notify_status(trade, last_price, gale_amount=amount,
                                 gale_fired=True, gale_success=True,
                                 gale_order_id=str(order_id or ""))
            # Registrar pérdida en la calculadora para próximo ciclo
            try:
                self._calculator.register_loss(trade.amount)
            except Exception:
                pass
            return "sent"
        else:
            log.error(
                "❌ GALE RECHAZADO | %s | error=%s",
                asset, error,
            )
            self._notify_status(trade, last_price, gale_amount=amount,
                                 gale_fired=True, gale_success=False)
            self.gale_fired = False
            return "failed_send"
