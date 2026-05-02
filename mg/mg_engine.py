from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Awaitable, Callable, Dict, Optional

from martingale_calculator import MartingaleCalculator

if TYPE_CHECKING:
    from hub.hub_scanner import HubScanner


@dataclass
class MGOpenTrade:
    asset: str
    direction: str
    entry_price: float
    opened_at: float
    duration_sec: int
    payout: int
    amount: float
    stage: str
    strategy_origin: str
    ceiling: float
    floor: float
    score_original: float


class MartingaleEngine:
    """Motor externo de martingala en background.

    Se activa al abrir una operacion y monitorea en vivo.
    Si a <= prefire_sec del cierre el precio sigue en contra,
    calcula el monto con MartingaleCalculator y dispara una nueva orden.
    """

    def __init__(
        self,
        *,
        get_price: Callable[[str], Awaitable[Optional[float]]],
        place_martin_order: Callable[[MGOpenTrade, float], Awaitable[bool]],
        log: Callable[[str], None],
        prefire_sec: float = 2.0,
        poll_sec: float = 0.5,
        enabled: bool = True,
        hub: Optional["HubScanner"] = None,
    ) -> None:
        self._get_price = get_price
        self._place_martin_order = place_martin_order
        self._log = log
        self.prefire_sec = max(0.5, float(prefire_sec))
        self.poll_sec = max(0.2, float(poll_sec))
        self.enabled = bool(enabled)
        self._hub = hub

        self.calculator = MartingaleCalculator()
        self._tasks: Dict[str, asyncio.Task[None]] = {}

    def set_balance(self, balance: float) -> None:
        try:
            self.calculator.set_balance(float(balance))
        except Exception:
            pass

    def on_trade_open(self, trade: MGOpenTrade) -> None:
        if not self.enabled:
            return
        key = self._trade_key(trade)
        old = self._tasks.pop(key, None)
        if old is not None and not old.done():
            old.cancel()
        self._tasks[key] = asyncio.create_task(self._watch_trade(trade), name=f"mg:{key}")

    def on_trade_close(self, trade: MGOpenTrade, outcome: str, profit: float) -> None:
        if not self.enabled:
            return

        key = self._trade_key(trade)
        old = self._tasks.pop(key, None)
        if old is not None and not old.done():
            old.cancel()

        out = str(outcome or "").upper()
        if out == "WIN":
            self.calculator.register_win(abs(float(trade.amount)), int(trade.payout))
            # Gale no necesario: limpia el panel
            if self._hub is not None:
                self._hub.clear_gale_state()
        elif out == "LOSS":
            self.calculator.register_loss(abs(float(trade.amount)))

    async def shutdown(self) -> None:
        pending = [t for t in self._tasks.values() if not t.done()]
        self._tasks.clear()
        if not pending:
            return
        for t in pending:
            t.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

    async def _watch_trade(self, trade: MGOpenTrade) -> None:
        if trade.stage == "martin":
            # Evita cascadas infinitas en la misma ventana temporal.
            return

        fired = False
        while not fired:
            elapsed = time.time() - float(trade.opened_at)
            secs_left = float(trade.duration_sec) - elapsed
            if secs_left <= 0:
                return

            if secs_left > self.prefire_sec:
                await asyncio.sleep(min(self.poll_sec, max(0.2, secs_left - self.prefire_sec)))
                continue

            price = await self._get_price(trade.asset)
            if price is None:
                await asyncio.sleep(self.poll_sec)
                continue

            losing = self._is_losing_now(trade.direction, trade.entry_price, price)
            if not losing:
                # Va ganando: limpia panel GALE si estaba activo
                if self._hub is not None:
                    self._hub.clear_gale_state()
                return

            amount, status = self.calculator.calculate_investment(int(trade.payout))
            if status != "OK" or amount <= 0:
                self._log(
                    f"[MG] {trade.asset}: no se dispara martin (status={status}, amount={amount:.2f})"
                )
                return

            # Notificar al HUB: gale inminente
            if self._hub is not None:
                self._hub.update_gale_state(
                    asset=trade.asset,
                    direction=trade.direction,
                    amount=amount,
                    payout=trade.payout,
                    seconds_until_fire=max(0.0, secs_left),
                    cycle_losses=self.calculator.get_status().get("losses", 0),
                )

            self._log(
                f"[MG] {trade.asset}: preparando martin en vivo (faltan {secs_left:.2f}s, amount={amount:.2f})"
            )
            fired = await self._place_martin_order(trade, float(amount))
            # Tras disparar, limpia el panel (la nueva operación generará su propio estado)
            if fired and self._hub is not None:
                self._hub.clear_gale_state()
            return

    @staticmethod
    def _is_losing_now(direction: str, entry: float, current: float) -> bool:
        d = str(direction or "").lower()
        if d == "call":
            return current < entry
        return current > entry

    @staticmethod
    def _trade_key(trade: MGOpenTrade) -> str:
        return f"{trade.asset}:{trade.opened_at:.3f}:{trade.stage}"
