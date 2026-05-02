"""Lógica de escaneo del HUB para datos reales del bot."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, List, Mapping, Optional, Sequence
import logging

from .hub_models import CandidateData, GaleState, HubScanSnapshot, HubState

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
        if strategy == "STRAT-B":
            return CandidateData.from_strat_b(dict(item))
        raise ValueError(f"estrategia desconocida: {strategy}")

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

    def update_gale_state(
        self,
        asset: str,
        direction: str,
        amount: float,
        payout: int,
        seconds_until_fire: float,
        cycle_losses: int,
    ) -> None:
        """Registra el estado del gale pendiente para mostrarlo en el panel GALE."""
        self.state.gale_pending = GaleState(
            asset=asset.upper(),
            direction=str(direction).lower(),
            amount=float(amount),
            payout=int(payout),
            seconds_until_fire=max(0.0, float(seconds_until_fire)),
            cycle_losses=int(cycle_losses),
        )

    def clear_gale_state(self) -> None:
        """Limpia el panel GALE (después de disparar o cuando el trade cierra en WIN)."""
        self.state.gale_pending = None

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
