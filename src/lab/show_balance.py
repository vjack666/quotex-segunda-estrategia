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
        raise RuntimeError("No se pudo conectar a la cuenta DEMO")

    try:
        balance = await client.get_balance()
        print(f"Saldo DEMO: {balance.balance} {balance.currency}")
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
