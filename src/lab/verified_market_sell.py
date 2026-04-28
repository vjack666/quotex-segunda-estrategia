import asyncio
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from api_quotex import AsyncQuotexClient, OrderDirection
from api_quotex.constants import update_assets_from_api

from bot import _resolve_demo_ssid
from config import load_config


MIN_PAYOUT = 85
AMOUNT = 5.0
DURATION = 300


@dataclass
class ConfirmedOrder:
    symbol: str
    order_id: str
    amount: float


async def main() -> None:
    cfg = load_config()
    ssid = await _resolve_demo_ssid(cfg)
    client = AsyncQuotexClient(ssid=ssid, is_demo=True)

    confirmed: List[ConfirmedOrder] = []
    errors: List[str] = []

    async def on_order_opened(data: Any) -> None:
        try:
            symbol = str(getattr(data, "asset", "") or "")
            order_id = str(getattr(data, "order_id", "") or "")
            amount = float(getattr(data, "amount", 0.0) or 0.0)
            if symbol and order_id:
                confirmed.append(ConfirmedOrder(symbol=symbol, order_id=order_id, amount=amount))
        except Exception as exc:
            errors.append(f"order_opened parse error: {exc}")

    async def on_error(data: Any) -> None:
        errors.append(str(data))

    ok = await client.connect()
    if not ok:
        raise RuntimeError("No se pudo conectar a DEMO")

    client.add_event_callback("order_opened", on_order_opened)
    client.add_event_callback("error", on_error)

    try:
        bal0 = await client.get_balance()
        print(f"Balance DEMO inicial: {bal0.balance} {bal0.currency}")

        assets = await client.get_available_assets()
        update_assets_from_api([
            {"symbol": symbol, "id": info.get("id")}
            for symbol, info in assets.items()
        ])
        candidates = []
        for symbol, info in assets.items():
            if not symbol.endswith("_otc"):
                continue
            if not bool(info.get("is_open")):
                continue
            payout = int(info.get("payout") or 0)
            if payout > MIN_PAYOUT:
                candidates.append((symbol, payout))

        candidates.sort(key=lambda x: (-x[1], x[0]))
        print(f"Candidatos payout>{MIN_PAYOUT}%: {len(candidates)}")

        if not candidates:
            print("No hay activos OTC abiertos que cumplan filtro.")
            return

        symbol, payout = candidates[0]
        print(f"Enviando PUT verificada en {symbol} payout={payout}% amount={AMOUNT} duration={DURATION}s")

        placed = await client.place_order(
            asset=symbol,
            amount=AMOUNT,
            direction=OrderDirection.PUT,
            duration=DURATION,
        )
        print(f"place_order returned: order_id={placed.order_id} status={placed.status}")

        # Extra wait to capture asynchronous confirmations in case of delayed event ordering.
        await asyncio.sleep(3)

        if confirmed:
            last = confirmed[-1]
            print(f"CONFIRMADA: symbol={last.symbol} order_id={last.order_id} amount={last.amount}")
        else:
            print("Sin confirmacion order_opened en este intervalo, pero place_order devolvio respuesta.")

        bal1 = await client.get_balance()
        print(f"Balance DEMO final: {bal1.balance} {bal1.currency}")

        if errors:
            print("Errores capturados:")
            for err in errors[:10]:
                print(err)

    finally:
        client.remove_event_callback("order_opened", on_order_opened)
        client.remove_event_callback("error", on_error)
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
