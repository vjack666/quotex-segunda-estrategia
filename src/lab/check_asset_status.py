import asyncio

from api_quotex import AsyncQuotexClient

from bot import _resolve_demo_ssid
from config import load_config


async def main() -> None:
    cfg = load_config()
    ssid = await _resolve_demo_ssid(cfg)
    client = AsyncQuotexClient(ssid=ssid, is_demo=True)

    ok = await client.connect()
    if not ok:
        raise RuntimeError("No se pudo conectar a DEMO")

    try:
        assets = await client.get_available_assets()
        symbol = "EURAUD_otc"
        info = assets.get(symbol)
        print("asset_found", bool(info))
        if info:
            print("asset", symbol)
            print("is_open", info.get("is_open"))
            print("payout", info.get("payout"))
            print("timeframes", info.get("available_timeframes"))
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
