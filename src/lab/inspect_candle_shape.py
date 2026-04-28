import asyncio

from api_quotex import AsyncQuotexClient

from bot import _resolve_demo_ssid
from config import load_config


async def main() -> None:
    cfg = load_config()
    ssid = await _resolve_demo_ssid(cfg)
    client = AsyncQuotexClient(ssid=ssid, is_demo=True)

    ok = await client.connect()
    print("connected", ok)
    if not ok:
        return

    try:
        candles = await client.get_candles(cfg.asset, cfg.timeframe, 3)
        print("candles_len", len(candles))
        if candles:
            c0 = candles[-1]
            print("repr", c0)
            print("dict", getattr(c0, "__dict__", None))
            print("dump", c0.model_dump() if hasattr(c0, "model_dump") else None)
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
