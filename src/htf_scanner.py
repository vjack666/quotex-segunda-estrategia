"""
htf_scanner.py
==============
Scanner de temporalidad alta (15 minutos) que corre en background como tarea
asyncio independiente. Mantiene un cache de velas 15m por activo y lo refresca
cada TTL segundos sin bloquear el loop de trading principal.

USO EN main.py:
    from src.htf_scanner import HTFScanner
    htf = HTFScanner(client, min_payout=85)
    asyncio.create_task(htf.run_forever())

USO EN scan loop:
    candles_15m = htf.get_candles_15m(sym)   # nunca bloquea
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Callable, Awaitable, List, Optional, Tuple

from asset_library import QualityAssetLibrary

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
#  CONSTANTES
# ─────────────────────────────────────────────────────────────────────────────

TF_15M_SEC        = 900          # segundos de una vela 15m
HTF_CANDLES_COUNT = 50           # 50 × 15m = 12.5 horas de historia
HTF_CACHE_TTL_SEC = 870          # refrescar ~30s antes del cierre de la vela
HTF_FETCH_TIMEOUT = 12.0         # timeout por activo
HTF_INTER_ASSET_SLEEP = 0.4      # pausa entre activos para no saturar el WS
HTF_CYCLE_SLEEP   = 60           # pausa entre rondas completas de refresco


# ─────────────────────────────────────────────────────────────────────────────
#  HTFScanner
# ─────────────────────────────────────────────────────────────────────────────

class HTFScanner:
    """
    Cache de velas 15m mantenida en background.

    Parámetros
    ----------
    client      : instancia pyquotex ya conectada
    assets_fn   : corrutina async opcional que devuelve List[Tuple[str, int]]
                  (mismo formato que get_open_assets). Si no se provee,
                  se usa un escaneo interno por payout.
    min_payout  : payout mínimo para el escaneo interno (estricto: > min_payout)
    ttl_sec     : segundos entre refrescos por activo (default 870 ≈ 14.5 min)
    """

    def __init__(
        self,
        client,
        assets_fn: Optional[Callable[[], Awaitable[List[Tuple[str, int]]]]] = None,
        min_payout: int = 85,
        on_asset_refresh: Optional[Callable[[str, int, int, float, float, float], None]] = None,
        ttl_sec: float = HTF_CACHE_TTL_SEC,
    ) -> None:
        self._client    = client
        self._assets_fn = assets_fn
        self._min_payout = int(min_payout)
        self._on_asset_refresh = on_asset_refresh
        self._ttl       = ttl_sec

        # cache[asset] = lista de Candle ordenadas ASC
        self._cache:    dict[str, list] = {}
        # cuándo fue el último fetch exitoso por activo
        self._cache_ts: dict[str, float] = {}
        # Biblioteca dinámica de activos de calidad ("libros").
        self._library = QualityAssetLibrary(min_payout=self._min_payout)

        # semáforo propio — no comparte con el scan loop 5m
        self._sem = asyncio.Semaphore(2)

    # ── API pública ────────────────────────────────────────────────────────

    def get_candles_15m(self, asset: str) -> list:
        """
        Devuelve la lista de velas 15m cacheadas para el activo.
        Nunca bloquea — si el cache está vacío devuelve [].
        """
        return self._cache.get(asset, [])

    def cache_age_sec(self, asset: str) -> float:
        """Segundos desde el último fetch exitoso del activo."""
        ts = self._cache_ts.get(asset)
        return (time.time() - ts) if ts else float("inf")

    def cache_summary(self) -> dict[str, int]:
        """Devuelve {asset: n_candles} para diagnóstico."""
        return {a: len(c) for a, c in self._cache.items()}

    def cache_ttl_sec(self) -> float:
        """TTL del cache HTF en segundos."""
        return float(self._ttl)

    def library_size(self) -> int:
        """Cantidad de activos actualmente presentes en la biblioteca HTF."""
        try:
            return int(self._library.size)
        except Exception:
            return 0

    def get_eligible_assets(self, max_age_sec: float = 180.0) -> List[Tuple[str, int]]:
        """
        Devuelve la última lista elegible (asset, payout) del scanner HTF.
        Si está demasiado vieja, devuelve [] para forzar fallback en caller.
        """
        return self._library.get_assets_if_fresh(max_age_sec=max_age_sec)

    # ── Loop background ────────────────────────────────────────────────────

    async def run_forever(self) -> None:
        """
        Loop principal del scanner HTF.
        Diseñado para correr como asyncio.create_task() y nunca terminar.
        """
        log.info(
            "[HTF] Scanner 15m iniciado (ttl=%ds candles=%d min_payout>%d)",
            self._ttl,
            HTF_CANDLES_COUNT,
            self._min_payout,
        )

        while True:
            try:
                await self._refresh_cycle()
            except asyncio.CancelledError:
                log.info("[HTF] Scanner cancelado.")
                return
            except Exception as exc:
                log.warning("[HTF] Error en ciclo de refresco: %s", exc)

            # Pausa entre rondas completas
            await asyncio.sleep(HTF_CYCLE_SLEEP)

    # ── Internals ──────────────────────────────────────────────────────────

    async def _refresh_cycle(self) -> None:
        """Una ronda completa: recorre todos los activos y refresca si es necesario."""
        try:
            assets = await self._resolve_assets()
        except Exception as exc:
            log.debug("[HTF] No se pudo obtener lista de activos: %s", exc)
            return

        entered, exited, updated = self._library.refresh_from_assets(assets)
        if entered:
            log.info("[HTF LIB] +%d entran a biblioteca (payout>%d)", len(entered), self._min_payout)
        if exited:
            log.info("[HTF LIB] -%d salen de biblioteca (caída de calidad/disponibilidad)", len(exited))
        if updated and not entered and not exited:
            log.debug("[HTF LIB] %d libros actualizados", len(updated))

        self._record_maintenance_event(
            subtype="SUMMARY",
            payload={
                "refreshed_assets": len(assets),
                "library_size": self._library.size,
                "entered": entered,
                "exited": exited,
                "updated": updated,
                "ttl_sec": self._ttl,
                "min_payout": self._min_payout,
            },
        )

        if entered:
            self._record_maintenance_event(
                subtype="ENTER",
                payload={"count": len(entered), "assets": entered},
            )
        if exited:
            self._record_maintenance_event(
                subtype="EXIT",
                payload={"count": len(exited), "assets": exited},
            )

        # Escaneo solo los activos de la biblioteca vigente.
        assets = self._library.get_assets()

        refreshed = 0
        skipped   = 0

        for sym, payout in assets:
            if not self._needs_refresh(sym):
                skipped += 1
                continue

            candles = await self._fetch_15m(sym)
            if candles:
                self._cache[sym]    = candles
                self._cache_ts[sym] = time.time()
                refreshed += 1
                self._notify_refresh(sym=sym, payout=payout, candles_count=len(candles))

            await asyncio.sleep(HTF_INTER_ASSET_SLEEP)

        if refreshed:
            log.debug(
                "[HTF] Ciclo completado: %d refrescados, %d vigentes (total cache=%d activos)",
                refreshed, skipped, len(self._cache),
            )

    async def _resolve_assets(self) -> List[Tuple[str, int]]:
        """Resuelve la lista de activos a escanear usando callback externo o fallback interno."""
        if self._assets_fn is not None:
            return await self._assets_fn()
        return await self._default_assets_scan()

    async def _default_assets_scan(self) -> List[Tuple[str, int]]:
        """Escaneo interno de activos OTC abiertos con payout > min_payout."""
        client = self._client
        if client is None:
            return []

        try:
            instruments = await client.get_instruments()
        except Exception:
            return []
        if not instruments:
            return []

        result: List[Tuple[str, int]] = []
        for i in instruments:
            try:
                sym = str(i[1])
                is_open = bool(i[14])
                payout = int(i[18]) if len(i) > 18 else 0
            except (IndexError, TypeError, ValueError):
                continue

            if sym.lower().endswith("_otc") and is_open and payout > self._min_payout:
                result.append((sym, payout))

        result.sort(key=lambda x: -x[1])
        return result

    def _needs_refresh(self, asset: str) -> bool:
        """True si el cache está vacío o venció el TTL."""
        ts = self._cache_ts.get(asset)
        if ts is None:
            return True
        return (time.time() - ts) >= self._ttl

    async def _fetch_15m(self, asset: str) -> list:
        """Fetch con timeout y semáforo propio. Devuelve [] en caso de fallo."""
        from consolidation_bot import fetch_candles_with_retry  # import lazy: evita circular
        try:
            async with self._sem:
                candles = await asyncio.wait_for(
                    fetch_candles_with_retry(
                        self._client,
                        asset,
                        tf_sec=TF_15M_SEC,
                        count=HTF_CANDLES_COUNT,
                        timeout_sec=HTF_FETCH_TIMEOUT,
                        retries=1,
                    ),
                    timeout=HTF_FETCH_TIMEOUT + 2.0,
                )
            return candles
        except asyncio.TimeoutError:
            log.debug("[HTF] Timeout fetch 15m %s", asset)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.debug("[HTF] Error fetch 15m %s: %s", asset, exc)
        return []

    def _notify_refresh(self, *, sym: str, payout: int, candles_count: int) -> None:
        """Notifica refresh de un activo para telemetría externa (HUB)."""
        cb = self._on_asset_refresh
        if cb is None:
            return
        try:
            ts = self._cache_ts.get(sym, time.time())
            age = max(0.0, time.time() - ts)
            cb(sym, int(payout), int(candles_count), age, float(self._ttl), ts)
        except Exception:
            return

    def _record_maintenance_event(self, *, subtype: str, payload: dict[str, object]) -> None:
        try:
            from black_box_recorder import get_black_box

            recorder = get_black_box()
            recorder.record_maintenance_event(
                "HTF_LIBRARY",
                subtype,
                asset="",
                severity="INFO",
                payload=payload,
            )
        except Exception:
            return
