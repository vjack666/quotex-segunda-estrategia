import asyncio

from api_quotex import AsyncQuotexClient, OrderDirection

from bot import _resolve_demo_ssid
from config import load_config


async def main() -> None:
    cfg = load_config()
    ssid = await _resolve_demo_ssid(cfg)
    client = AsyncQuotexClient(ssid=ssid, is_demo=True)

    ok = await client.connect()
    if not ok:
        raise RuntimeError("No se pudo conectar a la cuenta DEMO")

    try:
        pre_balance = await client.get_balance()
        print(f"Balance antes: {pre_balance.balance} {pre_balance.currency}")

        order = await client.place_order(
            asset="EURAUD_otc",
            amount=5.0,
            direction=OrderDirection.PUT,
            duration=300,
        )

        print(f"Orden enviada. order_id={order.order_id}")
        print(f"Estado inicial: {order.status}")

        post_balance = await client.get_balance()
        print(f"Balance despues: {post_balance.balance} {post_balance.currency}")
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
