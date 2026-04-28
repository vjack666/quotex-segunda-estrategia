import asyncio

from api_quotex import AsyncQuotexClient

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
        open_symbols = []
        for symbol, info in assets.items():
            if info.get("is_open") and symbol.endswith("_otc") and ("EUR" in symbol or "AUD" in symbol):
                open_symbols.append((symbol, info.get("payout")))

        open_symbols.sort(key=lambda x: x[0])
        print(f"open_count={len(open_symbols)}")
        for symbol, payout in open_symbols[:30]:
            print(f"{symbol} payout={payout}")
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
