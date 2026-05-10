"""Lógica de escaneo del HUB para datos reales del bot."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any, List, Mapping, Optional, Sequence
import logging

from .hub_models import CandidateData, CandleSnapshot, GaleState, HubScanSnapshot, HubState, VipWindowData

log = logging.getLogger("hub_scanner")


class HubScanner:
    """Gestor de ciclos de escaneo y estado visible del HUB."""

    def __init__(self) -> None:
        self.state = HubState()
        self.scan_count = 0
        # Evento que se activa inmediatamente cuando cierra un trade (WIN/LOSS).
        # El hub_ticker lo espera para re-renderizar sin esperar el intervalo normal.
        self.trade_result_event: asyncio.Event = asyncio.Event()

    @staticmethod
    def _to_candidate(strategy: str, item: CandidateData | Mapping[str, Any]) -> CandidateData:
        """Convierte payload crudo del bot a CandidateData validado."""
        if isinstance(item, CandidateData):
            return item
        if strategy == "STRAT-A":
            return CandidateData.from_strat_a(dict(item))
        # Cualquier estrategia no-A usa el normalizador B por compatibilidad.
        return CandidateData.from_strat_b(dict(item))

    def normalize_candidates(
        self,
        strategy: str,
        items: Sequence[CandidateData | Mapping[str, Any]],
    ) -> List[CandidateData]:
        """Normaliza y ordena candidatos por prioridad de entrada."""
        normalized = [self._to_candidate(strategy, item) for item in items]
        return sorted(normalized, key=lambda c: c.rank_value, reverse=True)

    def record_scan_cycle(
        self,
        total_assets: int,
        strat_a_candidates: Sequence[CandidateData | Mapping[str, Any]],
        strat_b_candidates: Sequence[CandidateData | Mapping[str, Any]],
        balance: Optional[float] = None,
        cycle_id: int = 0,
        cycle_ops: int = 0,
        cycle_wins: int = 0,
        cycle_losses: int = 0,
    ) -> None:
        """
        Registra un ciclo completo de escaneo.
        Mantiene top 5 de cada estrategia.
        """
        self.scan_count += 1
        now = datetime.now(tz=timezone.utc)

        # Normaliza y conserva top candidatos por estrategia para el HUB.
        normalized_a = self.normalize_candidates("STRAT-A", strat_a_candidates)
        normalized_b = self.normalize_candidates("STRAT-B", strat_b_candidates)
        strat_a_top5 = normalized_a[:5]
        strat_b_top5 = normalized_b[:5]

        self.state.strat_a_watching = strat_a_top5
        self.state.strat_b_watching = strat_b_top5
        self.state.total_scans += 1
        self.state.last_update = now
        if balance is not None:
            self.state.known_balance = float(balance)

        # Crear snapshot del escaneo
        snapshot = HubScanSnapshot(
            scan_number=self.scan_count,
            timestamp=now,
            total_assets_scanned=total_assets,
            strat_a_candidates=strat_a_top5,
            strat_b_candidates=strat_b_top5,
            balance=balance,
            cycle_id=cycle_id,
            cycle_ops=cycle_ops,
            cycle_wins=cycle_wins,
            cycle_losses=cycle_losses,
        )
        self.state.last_scan = snapshot

        log.debug(
            "SCAN #%d | STRAT-A=%d (top5=%d) | STRAT-B=%d (top5=%d)",
            self.scan_count,
            len(normalized_a),
            len(strat_a_top5),
            len(normalized_b),
            len(strat_b_top5),
        )

    def record_entry(
        self,
        strategy: str,  # "STRAT-A" | "STRAT-B"
        asset: str,
        direction: str,
        duration_sec: int,
        entry_price: Optional[float] = None,
    ) -> None:
        """Registra que se abrió una entrada."""
        self.state.active_trade_asset = asset.upper()
        self.state.active_trade_direction = direction.lower()
        self.state.active_trade_time_remaining_sec = float(duration_sec)
        self.state.active_trade_entry_price = float(entry_price) if entry_price is not None else None
        self.state.active_trade_current_price = None
        self.state.active_trade_delta_pct = None

        # Al abrir entrada, se remueve de la vista actual para evitar doble señal visual.
        if strategy.upper() == "STRAT-A":
            self.state.strat_a_watching = [
                c for c in self.state.strat_a_watching if c.asset != asset.upper()
            ]
        elif strategy.upper() == "STRAT-B":
            self.state.strat_b_watching = [
                c for c in self.state.strat_b_watching if c.asset != asset.upper()
            ]

        log.info(
            "ENTRADA %s | %s %s | duracion=%ds",
            strategy.upper(), direction.upper(), asset.upper(), duration_sec,
        )

    def update_active_trade_timer(
        self,
        secs_remaining: float,
        current_price: Optional[float] = None,
        entry_price: Optional[float] = None,
    ) -> None:
        """Actualiza temporizador y telemetría de la entrada activa."""
        self.state.active_trade_time_remaining_sec = max(0.0, secs_remaining)

        # Solo sobreescribir entry_price si se pasa explícitamente (no borrarlo cada tick).
        if entry_price is not None:
            self.state.active_trade_entry_price = float(entry_price)

        if current_price is not None:
            current = float(current_price)
            self.state.active_trade_current_price = current
            entry = self.state.active_trade_entry_price
            if entry and entry > 0:
                self.state.active_trade_delta_pct = ((current - entry) / entry) * 100.0

    def record_trade_result(
        self,
        asset: str,
        outcome: str,
        profit: float = 0.0,
    ) -> None:
        """Guarda el resultado del último trade para mostrarlo en el HUB."""
        self.state.last_trade_asset = asset.upper()
        self.state.last_trade_outcome = outcome  # "WIN" | "LOSS" | "UNRESOLVED"
        self.state.last_trade_profit = float(profit)

        # Incrementar contadores en tiempo real (no esperar al próximo scan cycle).
        if outcome == "WIN":
            self.state.live_wins += 1
        elif outcome == "LOSS":
            self.state.live_losses += 1

        # Señalizar al ticker para que re-renderice el HUB de inmediato.
        self.trade_result_event.set()

        log.info("RESULT %s %s profit=%.2f", asset.upper(), outcome, profit)

    def close_active_trade(self) -> None:
        """Cierra la entrada activa (limpia campos de trade en curso)."""
        self.state.active_trade_asset = None
        self.state.active_trade_direction = None
        self.state.active_trade_time_remaining_sec = None
        self.state.active_trade_entry_price = None
        self.state.active_trade_current_price = None
        self.state.active_trade_delta_pct = None

    def update_gale_state(self, **kwargs) -> None:
        """
        Actualiza campos del GaleState en tiempo real.
        Acepta cualquier campo definido en GaleState como keyword argument.
        Ejemplo:
            hub.update_gale_state(active=True, asset="GBPAUD_otc", secs_remaining=45.0)
        """
        g = self.state.gale
        prev_price = g.current_price
        for key, value in kwargs.items():
            if hasattr(g, key):
                if key == "current_price":
                    try:
                        v = float(value)
                    except Exception:
                        continue
                    # Evita reset visual a 0.00000 por un tick fallido aislado.
                    if v <= 0.0 and prev_price > 0.0:
                        continue
                setattr(g, key, value)
        g.updated_at = time.time()

    def clear_gale_state(self) -> None:
        """Resetea el GaleState a inactivo (tras expirar la operación)."""
        self.state.gale = GaleState()

    def update_masaniello_state(self, **kwargs) -> None:
        """
        Actualiza campos del MasanielloState en tiempo real.
        Acepta cualquier campo definido en MasanielloState como keyword argument.
        Ejemplo:
            hub.update_masaniello_state(active=True, asset="GBPAUD_otc", cycle_num=2)
        """
        m = self.state.masaniello
        prev_price = m.current_price
        for key, value in kwargs.items():
            if hasattr(m, key):
                if key == "current_price":
                    try:
                        v = float(value)
                    except Exception:
                        continue
                    if v <= 0.0 and prev_price > 0.0:
                        continue
                setattr(m, key, value)
        m.updated_at = time.time()

    def clear_masaniello_state(self) -> None:
        """Marca Masaniello como inactivo sin perder el estado del ciclo."""
        m = self.state.masaniello
        m.active = False
        m.asset = ""
        m.direction = ""
        m.entry_price = 0.0
        m.current_price = 0.0
        m.secs_remaining = 0.0
        m.payout = 0
        m.delta_pct = 0.0
        m.updated_at = time.time()


    def update_chart_candles(
        self,
        candles: Sequence[Any],
        asset: str,
        entry_price: Optional[float] = None,
        direction: str = "",
        zone_floor: Optional[float] = None,
        zone_ceiling: Optional[float] = None,
        live_price: Optional[float] = None,
        max_candles: int = 15,
    ) -> None:
        """
        Almacena las últimas N velas OHLC del activo para renderizar el chart ASCII.

        ``candles`` puede ser una lista de objetos con atributos open/high/low/close/ts
        o dicts con esas claves. Solo se guardan las últimas ``max_candles``.
        """
        snapshots: list[CandleSnapshot] = []
        for c in candles:
            try:
                if isinstance(c, dict):
                    o, h, l, cl = float(c["open"]), float(c["high"]), float(c["low"]), float(c["close"])
                    ts = float(c.get("ts", 0.0) or c.get("time", 0.0) or 0.0)
                else:
                    o, h, l, cl = float(c.open), float(c.high), float(c.low), float(c.close)
                    ts = float(getattr(c, "ts", 0.0) or 0.0)
                if h > 0:
                    snapshots.append(CandleSnapshot(open=o, high=h, low=l, close=cl, ts=ts))
            except Exception:
                continue

        self.state.chart_candles = snapshots[-max_candles:]
        self.state.chart_asset = str(asset).upper()
        self.state.chart_entry_price = float(entry_price) if entry_price is not None else None
        self.state.chart_direction = str(direction).lower()
        self.state.chart_zone_floor = float(zone_floor) if zone_floor is not None else None
        self.state.chart_zone_ceiling = float(zone_ceiling) if zone_ceiling is not None else None
        self.state.chart_live_price = float(live_price) if live_price is not None else None

    def update_htf_status(
        self,
        *,
        asset: str,
        payout: int,
        candles: int,
        library_size: int = 0,
        cache_age_sec: float,
        cache_ttl_sec: float,
        refreshed_at_ts: float,
    ) -> None:
        """Actualiza telemetría del cache HTF (15m) para mostrar en el HUB."""
        self.state.htf_asset = str(asset).upper()
        self.state.htf_payout = int(payout)
        self.state.htf_candles = int(candles)
        self.state.htf_library_size = max(0, int(library_size))
        self.state.htf_cache_age_sec = max(0.0, float(cache_age_sec))
        self.state.htf_cache_ttl_sec = max(0.0, float(cache_ttl_sec))
        self.state.htf_last_refresh_ts = max(0.0, float(refreshed_at_ts))

    def update_vip_windows(self, windows: Sequence[VipWindowData]) -> None:
        """Publica la lista VIP actual en el HUB."""
        items = sorted(
            [w for w in windows if w is not None],
            key=lambda w: (w.missing_conditions, -w.score, -w.payout),
        )
        self.state.vip_windows = list(items[:5])

    def get_state(self) -> HubState:
        """Devuelve el estado actual del HUB."""
        return self.state

    def build_snapshot_from_bot_payload(
        self,
        *,
        total_assets: int,
        strat_a_payload: Sequence[Mapping[str, Any]],
        strat_b_payload: Sequence[Mapping[str, Any]],
        balance: Optional[float] = None,
        cycle_id: int = 0,
        cycle_ops: int = 0,
        cycle_wins: int = 0,
        cycle_losses: int = 0,
    ) -> HubScanSnapshot:
        """Atajo para integrar directamente payloads crudos provenientes del bot."""
        self.record_scan_cycle(
            total_assets=total_assets,
            strat_a_candidates=strat_a_payload,
            strat_b_candidates=strat_b_payload,
            balance=balance,
            cycle_id=cycle_id,
            cycle_ops=cycle_ops,
            cycle_wins=cycle_wins,
            cycle_losses=cycle_losses,
        )
        if self.state.last_scan is None:
            raise RuntimeError("no se pudo generar snapshot del HUB")
        return self.state.last_scan
