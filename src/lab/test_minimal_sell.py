import asyncio
import json
import time
from typing import Any, Dict, List, Optional, Tuple

from api_quotex import AsyncQuotexClient

from bot import _resolve_demo_ssid
from config import load_config

ASSET = "USDBDT_otc"
AMOUNT = 5.0
DURATION = 300
TIMEOUT = 60


def _extract_event(data: Any) -> Tuple[Optional[str], Any]:
    if isinstance(data, dict) and "event" in data:
        return data.get("event"), data.get("data")
    if isinstance(data, list) and len(data) >= 2:
        return data[0], data[1]
    return None, None


async def main() -> None:
    cfg = load_config()
    ssid = await _resolve_demo_ssid(cfg)
    client = AsyncQuotexClient(ssid=ssid, is_demo=True)

    events: List[Tuple[str, str]] = []
    ack = asyncio.Event()
    ack_data: Dict[str, Any] = {"event": None, "payload": None}

    async def on_json_data(data: Any) -> None:
        event_name, payload = _extract_event(data)
        if not event_name:
            return

        payload_str = str(payload)
        if len(payload_str) > 220:
            payload_str = payload_str[:220] + "..."
        events.append((event_name, payload_str))

        if event_name in {
            "s_pending/create",
            "s_orders/open",
            "s_orders/opened",
            "successopenOrder",
            "orders/opened/list",
            "error",
        } and not ack.is_set():
            ack_data["event"] = event_name
            ack_data["payload"] = payload
            ack.set()

    ok = await client.connect()
    if not ok:
        raise RuntimeError("No se pudo conectar a DEMO")

    client.add_event_callback("json_data", on_json_data)

    try:
        bal0 = await client.get_balance()
        print(f"Balance inicial: {bal0.balance} {bal0.currency}")

        assets = await client.get_available_assets()
        info = assets.get(ASSET)
        if not info:
            raise RuntimeError(f"Activo no encontrado: {ASSET}")

        print(
            f"Asset {ASSET}: is_open={info.get('is_open')} payout={info.get('payout')} "
            f"timeframes={info.get('available_timeframes')}"
        )
        if not bool(info.get("is_open")):
            raise RuntimeError(f"Activo cerrado: {ASSET}")

        request_id = int(time.time() * 1000)
        payload = {
            "asset": ASSET,
            "amount": AMOUNT,
            "time": DURATION,
            "action": "put",
            "isDemo": 1,
            "tournamentId": 0,
            "requestId": request_id,
            "optionType": 100,
        }

        print(f"Enviando PUT {ASSET} ${AMOUNT} {DURATION}s requestId={request_id}")
        await client.send_message('42["tick"]')
        await client.send_message(f'42["instruments/follow","{ASSET}"]')
        await client.send_message(f'42["orders/open",{json.dumps(payload, separators=(",", ":"))}]')

        try:
            await asyncio.wait_for(ack.wait(), timeout=TIMEOUT)
            print(f"ACK recibido: {ack_data['event']}")
            print(f"Payload ACK: {ack_data['payload']}")
        except asyncio.TimeoutError:
            print(f"Sin ACK en {TIMEOUT}s")

        print("\nUltimos eventos relevantes:")
        for event_name, payload_str in events[-40:]:
            if (
                "order" in event_name.lower()
                or "pending" in event_name.lower()
                or event_name == "error"
            ):
                print(f"{event_name}: {payload_str}")

        bal1 = await client.get_balance()
        print(f"Balance final: {bal1.balance} {bal1.currency}")

    finally:
        client.remove_event_callback("json_data", on_json_data)
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
