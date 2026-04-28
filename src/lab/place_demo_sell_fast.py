import asyncio
import json
import time
from typing import Any, Dict, Optional

from api_quotex import AsyncQuotexClient

from bot import _resolve_demo_ssid
from config import load_config


ASSET = "EURAUD_otc"
AMOUNT = 5.0
DURATION = 300


def _extract_event(data: Any) -> tuple[Optional[str], Any]:
    if isinstance(data, dict) and "event" in data:
        return data.get("event"), data.get("data")
    if isinstance(data, list) and len(data) > 1:
        return data[0], data[1]
    return None, None


async def main() -> None:
    cfg = load_config()
    ssid = await _resolve_demo_ssid(cfg)
    client = AsyncQuotexClient(ssid=ssid, is_demo=True)

    ok = await client.connect()
    if not ok:
        raise RuntimeError("No se pudo conectar a la cuenta DEMO")

    ack_event = asyncio.Event()
    ack_data: Dict[str, Any] = {"event": None, "payload": None}

    async def on_json_data(data: Any) -> None:
        event_name, payload = _extract_event(data)
        if event_name in {"s_pending/create", "s_orders/open", "successopenOrder", "error"}:
            if not ack_event.is_set():
                ack_data["event"] = event_name
                ack_data["payload"] = payload
                ack_event.set()

    client.add_event_callback("json_data", on_json_data)

    try:
        pre_balance = await client.get_balance()
        print(f"Balance antes: {pre_balance.balance} {pre_balance.currency}")

        option_type, time_field = client._compute_order_time_and_type(ASSET, DURATION)
        request_id = int(time.time() * 1000)

        payload = {
            "asset": ASSET,
            "amount": AMOUNT,
            "time": int(time_field),
            "action": "put",
            "isDemo": 1,
            "tournamentId": 0,
            "requestId": request_id,
            "optionType": int(option_type),
        }

        await client.send_message('42["tick"]')
        await client.send_message(f'42["instruments/follow","{ASSET}"]')
        await client.send_message(f'42["orders/open",{json.dumps(payload, separators=(",", ":"))}]')

        print(f"Orden enviada requestId={request_id} asset={ASSET} amount={AMOUNT} duration={DURATION}s")

        try:
            await asyncio.wait_for(ack_event.wait(), timeout=20)
        except asyncio.TimeoutError:
            print("Sin confirmacion rapida (20s). La orden pudo quedar en cola del broker.")
        else:
            event_name = ack_data.get("event")
            payload_ack = ack_data.get("payload")
            print(f"ACK recibido: {event_name}")

            if event_name == "s_pending/create" and isinstance(payload_ack, dict):
                pending = payload_ack.get("pending") or {}
                print(f"Ticket pendiente: {pending.get('ticket')}")
            elif event_name == "s_orders/open" and isinstance(payload_ack, dict):
                print(f"Orden abierta id={payload_ack.get('id') or payload_ack.get('orderId')}")
            elif event_name == "error":
                print(f"Error broker: {payload_ack}")

        await asyncio.sleep(1)
        post_balance = await client.get_balance()
        print(f"Balance despues: {post_balance.balance} {post_balance.currency}")

    finally:
        client.remove_event_callback("json_data", on_json_data)
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
