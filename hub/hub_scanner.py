"""Lógica de escaneo del HUB para datos reales del bot."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, List, Mapping, Optional, Sequence
import logging

from .hub_models import CandidateData, HubScanSnapshot, HubState

log = logging.getLogger("hub_scanner")


class HubScanner:
    """Gestor de ciclos de escaneo y estado visible del HUB."""

    def __init__(self) -> None:
        self.state = HubState()
        self.scan_count = 0

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
    ) -> None:
        """Registra que se abrió una entrada."""
        self.state.active_trade_asset = asset.upper()
        self.state.active_trade_direction = direction.lower()
        self.state.active_trade_time_remaining_sec = float(duration_sec)

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

    def update_active_trade_timer(self, secs_remaining: float) -> None:
        """Actualiza el temporizador de la entrada activa."""
        self.state.active_trade_time_remaining_sec = max(0.0, secs_remaining)

    def close_active_trade(self) -> None:
        """Cierra la entrada activa."""
        self.state.active_trade_asset = None
        self.state.active_trade_direction = None
        self.state.active_trade_time_remaining_sec = None

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
