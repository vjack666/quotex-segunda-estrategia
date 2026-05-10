"""
asset_library.py
================
Biblioteca de activos de calidad ("libros") basada en payout.

Reglas:
- Entran a la biblioteca si payout > min_payout.
- Salen de la biblioteca si ya no cumplen payout o dejan de estar en el universo actual.
- Se mantiene ordenada por payout descendente para que el scanner priorice calidad.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Dict, Iterable, List, Sequence, Tuple


@dataclass
class AssetBook:
    asset: str
    payout: int
    entered_at_ts: float
    updated_at_ts: float


class QualityAssetLibrary:
    """Biblioteca dinámica de activos elegibles por payout."""

    def __init__(self, min_payout: int) -> None:
        self._min_payout = int(min_payout)
        self._books: Dict[str, AssetBook] = {}
        self._last_refresh_ts: float = 0.0

    @property
    def min_payout(self) -> int:
        return self._min_payout

    @property
    def size(self) -> int:
        return len(self._books)

    @property
    def last_refresh_ts(self) -> float:
        return self._last_refresh_ts

    def refresh_from_assets(self, assets: Sequence[Tuple[str, int]]) -> tuple[List[str], List[str], List[str]]:
        """
        Refresca la biblioteca desde la foto actual de activos elegibles.

        Parámetro `assets`: lista (asset, payout) ya filtrada por criterio de negocio.

        Devuelve:
          (entered, exited, updated)
        """
        now = time.time()
        current = {str(a).upper(): int(p) for a, p in assets if int(p) > self._min_payout}
        prev_keys = set(self._books.keys())
        curr_keys = set(current.keys())

        entered_keys = sorted(curr_keys - prev_keys)
        exited_keys = sorted(prev_keys - curr_keys)
        updated_keys: List[str] = []

        # Entradas nuevas
        for asset in entered_keys:
            payout = current[asset]
            self._books[asset] = AssetBook(
                asset=asset,
                payout=payout,
                entered_at_ts=now,
                updated_at_ts=now,
            )

        # Actualizaciones de los que permanecen
        for asset in sorted(curr_keys & prev_keys):
            payout = current[asset]
            book = self._books[asset]
            if book.payout != payout:
                updated_keys.append(asset)
            book.payout = payout
            book.updated_at_ts = now

        # Salidas (dejan de cumplir calidad o desaparecen)
        for asset in exited_keys:
            self._books.pop(asset, None)

        self._last_refresh_ts = now
        return entered_keys, exited_keys, updated_keys

    def get_assets(self) -> List[Tuple[str, int]]:
        """Lista de activos en biblioteca, ordenados por payout desc."""
        rows = [(b.asset, int(b.payout)) for b in self._books.values()]
        rows.sort(key=lambda x: -x[1])
        return rows

    def get_assets_if_fresh(self, max_age_sec: float) -> List[Tuple[str, int]]:
        if not self._books:
            return []
        age = time.time() - self._last_refresh_ts
        if age > max(1.0, float(max_age_sec)):
            return []
        return self.get_assets()
