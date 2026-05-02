"""Script de diagnóstico de conexión con Quotex."""
import asyncio
import sys
import logging

sys.path.insert(0, "src")

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    stream=sys.stdout,
)

from dotenv import load_dotenv
import pathlib

env_path = pathlib.Path("sessions/.env")
if env_path.exists():
    load_dotenv(str(env_path))
    print(f"[ENV] Cargando desde {env_path}")
else:
    load_dotenv()
    print("[ENV] Cargando desde .env raíz")

import os
from pyquotex.stable_api import Quotex
import consolidation_bot as cb


async def test():
    email = os.getenv("QUOTEX_EMAIL", "NO_ENCONTRADO")
    password = os.getenv("QUOTEX_PASSWORD", "")
    print(f"[1] EMAIL    : {email}")
    print(f"[1] PASSWORD : {'***' if password else 'NO ENCONTRADO'}")

    client = Quotex(email=email, password=password)

    print("[2] Intentando client.connect()...")
    try:
        ok, reason = await client.connect()
        print(f"[3] connect() → ok={ok}  reason={reason!r}")
    except Exception as exc:
        print(f"[3] connect() lanzó excepción: {type(exc).__name__}: {exc}")
        return

    if not ok:
        print(f"[X] Conexión fallida. Razón: {reason!r}")
        return

    print("[4] Cambiando a cuenta PRACTICE...")
    try:
        await client.change_account("PRACTICE")
        print("[5] Cuenta cambiada a PRACTICE")
    except Exception as exc:
        print(f"[5] change_account() error: {exc}")

    print("[6] Llamando get_balance()...")
    try:
        bal = await client.get_balance()
        print(f"[7] Balance DEMO = {bal}")
    except Exception as exc:
        print(f"[7] get_balance() error: {type(exc).__name__}: {exc}")

    try:
        await client.close()
    except Exception:
        pass
    print("[OK] Test completado.")


asyncio.run(test())
