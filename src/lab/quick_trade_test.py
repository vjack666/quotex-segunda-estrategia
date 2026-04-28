import asyncio

from api_quotex import AsyncQuotexClient, OrderDirection

from bot import _resolve_demo_ssid
from config import load_config


async def main() -> None:
    cfg = load_config()
    ssid = await _resolve_demo_ssid(cfg)
    client = AsyncQuotexClient(ssid=ssid, is_demo=True)

    ok = await client.connect()
    print(f"connected={ok}")
    if not ok:
        return

    try:
        assets = await client.get_available_assets()
        symbol = None
        for s, info in assets.items():
            if s.endswith("_otc") and info.get("is_open") and int(info.get("payout") or 0) > 85:
                symbol = s
                break

        if not symbol:
            print("No symbol found")
            return

        print(f"symbol={symbol}")
        b0 = await client.get_balance()
        print(f"balance_before={b0.balance}")

        order = await client.place_order(
            asset=symbol,
            amount=5.0,
            direction=OrderDirection.PUT,
            duration=60,
        )
        print(f"order_id={order.order_id} status={order.status}")

        await asyncio.sleep(2)
        b1 = await client.get_balance()
        print(f"balance_after={b1.balance}")
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
