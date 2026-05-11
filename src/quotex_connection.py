from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from pyquotex.stable_api import Quotex  # type: ignore


@dataclass(frozen=True)
class QuotexCredentials:
    email: str
    password: str


def load_credentials_from_env(env_path: Optional[Path] = None) -> QuotexCredentials:
    """Load QUOTEX_EMAIL/QUOTEX_PASSWORD from .env or process environment."""
    if env_path is None:
        env_path = Path(__file__).resolve().parent.parent / ".env"

    if env_path.exists():
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())

    email = (os.environ.get("QUOTEX_EMAIL") or "").strip()
    password = (os.environ.get("QUOTEX_PASSWORD") or "").strip()

    if not email or not password:
        raise RuntimeError("Falta QUOTEX_EMAIL / QUOTEX_PASSWORD en el .env")

    return QuotexCredentials(email=email, password=password)


def create_client(env_path: Optional[Path] = None) -> Quotex:
    """Create Quotex client using credentials loaded from .env."""
    creds = load_credentials_from_env(env_path=env_path)
    return Quotex(email=creds.email, password=creds.password)


async def get_practice_balance(env_path: Optional[Path] = None) -> float:
    """Connect and return PRACTICE account balance."""
    client = create_client(env_path=env_path)
    ok, reason = await client.connect()
    if not ok:
        raise RuntimeError(f"No se pudo conectar a Quotex: {reason}")
    await client.change_account("PRACTICE")
    balance = await client.get_balance()
    try:
        return float(balance)
    finally:
        try:
            await client.close()
        except Exception:
            pass
