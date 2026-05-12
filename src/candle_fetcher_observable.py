"""
candle_fetcher_observable.py
============================

Capa de observabilidad y resiliencia para fetch de velas.
Wrappea fetch_candles_with_retry con:
- Instrumentación de conexión
- Retry controlado para arrays vacíos
- Logging estructurado [CANDLE-*]
- Métricas por activo

SIN modificar lógica de scoring/HTF/spike.
"""

import asyncio
import logging
import time
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from collections import defaultdict

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
#  MODELOS DE DATOS
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ConnectionState:
    """Estado de la conexión del cliente."""
    is_connected: bool = False
    websocket_alive: bool = False
    session_age_sec: float = 0.0
    pending_requests: int = 0
    last_successful_fetch_ts: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "connected": self.is_connected,
            "ws_alive": self.websocket_alive,
            "session_age_s": round(self.session_age_sec, 1),
            "pending_reqs": self.pending_requests,
            "last_fetch_s_ago": round(time.time() - self.last_successful_fetch_ts, 1) if self.last_successful_fetch_ts else -1,
        }

@dataclass
class FetchMetrics:
    """Métricas de un single fetch attempt."""
    asset: str
    timeframe_sec: int
    attempt: int
    duration_ms: float
    candles_returned: int
    connection_state: ConnectionState
    empty_before_retry: bool = False
    retry_success: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "asset": self.asset,
            "tf_s": self.timeframe_sec,
            "attempt": self.attempt,
            "duration_ms": round(self.duration_ms, 1),
            "candles": self.candles_returned,
            "empty_before_retry": self.empty_before_retry,
            "retry_success": self.retry_success,
            "conn": self.connection_state.to_dict(),
        }

@dataclass
class CandleFetchResult:
    """Resultado de un fetch con metadata."""
    candles: List[Any] = field(default_factory=list)
    asset: str = ""
    timeframe_sec: int = 0
    total_attempts: int = 0
    total_duration_ms: float = 0.0
    recovered_by_retry: bool = False
    connection_state: Optional[ConnectionState] = None
    metrics: List[FetchMetrics] = field(default_factory=list)
    
    def success(self) -> bool:
        """Verdadero si candles devueltos."""
        return len(self.candles) > 0

# ─────────────────────────────────────────────────────────────────────────────
#  FETCHER OBSERVABLE
# ─────────────────────────────────────────────────────────────────────────────

class ObservableCandleFetcher:
    """Wrapper observador de fetch_candles_with_retry."""
    
    def __init__(
        self,
        fetch_candles_with_retry_fn,  # Función original
        max_retries_on_empty: int = 3,
        backoff_sec: Tuple[float, float, float] = (0.5, 1.0, 1.5),
    ):
        self.fetch_original = fetch_candles_with_retry_fn
        self.max_retries_on_empty = max_retries_on_empty
        self.backoff_sec = backoff_sec
        
        # Acumuladores de estadísticas
        self.stats: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
            "fetch_attempts": 0,
            "fetch_success": 0,
            "fetch_empty": 0,
            "fetch_error": 0,
            "total_duration_ms": 0.0,
            "retry_recoveries": 0,
        })
        
        self.last_connection_state: Optional[ConnectionState] = None
    
    async def _get_connection_state(self, client) -> ConnectionState:
        """Obtiene estado actual de la conexión."""
        state = ConnectionState()
        
        try:
            # Verificar si cliente está "conectado" (atributo básico)
            state.is_connected = bool(client and hasattr(client, 'websocket'))
            
            # Validar WebSocket específicamente
            if hasattr(client, 'websocket') and client.websocket:
                state.websocket_alive = not client.websocket.closed
            
            # Edad de sesión (si disponible)
            if hasattr(client, '_session_start_time'):
                state.session_age_sec = time.time() - client._session_start_time
            
            # Requests pendientes (si está disponible)
            if hasattr(client, '_pending_requests'):
                state.pending_requests = len(client._pending_requests) if client._pending_requests else 0
            
            # Última fetch exitosa
            if self.last_connection_state:
                state.last_successful_fetch_ts = self.last_connection_state.last_successful_fetch_ts
            
        except Exception as e:
            log.debug("Error obteniendo estado conexión: %s", e)
        
        self.last_connection_state = state
        return state
    
    async def fetch_with_observability(
        self,
        client,
        asset: str,
        timeframe_sec: int,
        candle_count: int,
        timeout_sec: float = 10.0,
        retries: int = 1,
    ) -> CandleFetchResult:
        """
        Fetch con observabilidad + retry controlado para empty arrays.
        
        Parámetros
        ----------
        client: Cliente Quotex
        asset: Símbolo (ej: "EURUSD_OTC")
        timeframe_sec: Timeframe en segundos (300 para 5m, 60 para 1m)
        candle_count: Cuántas velas devolver
        timeout_sec: Timeout de fetch
        retries: Reintentos originales (usar valor default de config)
        
        Retorna
        -------
        CandleFetchResult con candles + metadata
        """
        
        result = CandleFetchResult(
            asset=asset,
            timeframe_sec=timeframe_sec,
        )
        
        cycle_start = time.perf_counter()
        
        # Verificar conexión antes de empezar
        conn_state = await self._get_connection_state(client)
        result.connection_state = conn_state
        
        if not conn_state.is_connected:
            # Señal preventiva: no bloquea el fetch porque algunos clientes no exponen
            # estado websocket de forma uniforme (evita falsos negativos de conexión).
            log.warning(
                "[CANDLE-FETCH] %s: cliente posiblemente no conectado (tf=%ds ws=%s session_age=%.1fs pending=%d last_fetch_ts=%.0f) — intentando fetch",
                asset,
                timeframe_sec,
                "ON" if conn_state.websocket_alive else "OFF",
                conn_state.session_age_sec,
                conn_state.pending_requests,
                conn_state.last_successful_fetch_ts,
            )
        
        attempt_num = 0
        total_fetch_time = 0.0
        
        # Retry loop: máximo 3 intentos si devuelve []
        for retry_attempt in range(self.max_retries_on_empty):
            attempt_num += 1
            attempt_start = time.perf_counter()
            
            # Call original fetch
            try:
                candles = await self.fetch_original(
                    client,
                    asset,
                    timeframe_sec,
                    candle_count,
                    timeout_sec,
                    retries=retries,
                )
            except Exception as e:
                log.debug(
                    "[CANDLE-FETCH] %s tf=%ds attempt %d: exception %s",
                    asset,
                    timeframe_sec,
                    attempt_num,
                    type(e).__name__,
                )
                # NO retentamos exceptions fatales, solo empty arrays
                return result
            
            attempt_duration = (time.perf_counter() - attempt_start) * 1000.0
            total_fetch_time += attempt_duration
            
            # Capturar estado post-fetch
            conn_state = await self._get_connection_state(client)
            
            # Registrar métrica de este intento
            metric = FetchMetrics(
                asset=asset,
                timeframe_sec=timeframe_sec,
                attempt=attempt_num,
                duration_ms=attempt_duration,
                candles_returned=len(candles),
                connection_state=conn_state,
                empty_before_retry=(retry_attempt > 0),
                retry_success=(len(candles) > 0 and retry_attempt > 0),
            )
            result.metrics.append(metric)
            
            # Logging estructurado
            if candles:
                if retry_attempt > 0:
                    log.info(
                        "[CANDLE-RECOVERED] %s tf=%ds attempt=%d duration=%.0fms candles=%d ws=%s session_age=%.1fs pending=%d",
                        asset,
                        timeframe_sec,
                        attempt_num,
                        attempt_duration,
                        len(candles),
                        "ON" if conn_state.websocket_alive else "OFF",
                        conn_state.session_age_sec,
                        conn_state.pending_requests,
                    )
                    result.recovered_by_retry = True
                else:
                    log.debug(
                        "[CANDLE-FETCH] %s tf=%ds attempt=%d duration=%.0fms candles=%d ws=%s session_age=%.1fs pending=%d",
                        asset,
                        timeframe_sec,
                        attempt_num,
                        attempt_duration,
                        len(candles),
                        "ON" if conn_state.websocket_alive else "OFF",
                        conn_state.session_age_sec,
                        conn_state.pending_requests,
                    )
                
                result.candles = candles
                result.total_attempts = attempt_num
                result.total_duration_ms = total_fetch_time
                
                # Actualizar timestamp de último fetch exitoso
                if conn_state:
                    conn_state.last_successful_fetch_ts = time.time()
                
                # Actualizar stats
                self.stats[asset]["fetch_attempts"] += 1
                self.stats[asset]["fetch_success"] += 1
                if retry_attempt > 0:
                    self.stats[asset]["retry_recoveries"] += 1
                self.stats[asset]["total_duration_ms"] += attempt_duration
                
                return result
            else:
                # Array vacío: loguear y decidir si retentamos
                if retry_attempt < self.max_retries_on_empty - 1:
                    backoff = self.backoff_sec[retry_attempt]
                    log.warning(
                        "[CANDLE-RETRY] %s tf=%ds next_attempt=%d backoff=%.1fs ws=%s session_age=%.1fs pending=%d",
                        asset,
                        timeframe_sec,
                        attempt_num + 1,
                        backoff,
                        "ON" if conn_state.websocket_alive else "OFF",
                        conn_state.session_age_sec,
                        conn_state.pending_requests,
                    )
                    log.warning(
                        "[CANDLE-EMPTY] %s tf=%ds attempt=%d duration=%.0fms empty=yes backoff=%.1fs conn=%s ws=%s session_age=%.1fs pending=%d",
                        asset,
                        timeframe_sec,
                        attempt_num,
                        attempt_duration,
                        backoff,
                        "ON" if conn_state.is_connected else "OFF",
                        "ON" if conn_state.websocket_alive else "OFF",
                        conn_state.session_age_sec,
                        conn_state.pending_requests,
                    )
                    
                    self.stats[asset]["fetch_attempts"] += 1
                    self.stats[asset]["fetch_empty"] += 1
                    
                    await asyncio.sleep(backoff)
                else:
                    log.error(
                        "[CANDLE-EMPTY] %s tf=%ds attempt=%d duration=%.0fms empty=yes retries_exhausted conn=%s ws=%s session_age=%.1fs pending=%d",
                        asset,
                        timeframe_sec,
                        attempt_num,
                        attempt_duration,
                        "ON" if conn_state.is_connected else "OFF",
                        "ON" if conn_state.websocket_alive else "OFF",
                        conn_state.session_age_sec,
                        conn_state.pending_requests,
                    )
                    self.stats[asset]["fetch_attempts"] += 1
                    self.stats[asset]["fetch_empty"] += 1
        
        # Fin del retry loop sin éxito
        result.total_attempts = attempt_num
        result.total_duration_ms = total_fetch_time
        return result
    
    def get_stats(self) -> Dict[str, Dict[str, Any]]:
        """Devuelve acumulado de estadísticas."""
        return dict(self.stats)
    
    def reset_stats(self) -> None:
        """Limpia estadísticas."""
        self.stats.clear()
    
    def summary_stats(self) -> Dict[str, Any]:
        """Resumen agregado de todas las estadísticas."""
        total_attempts = sum(s.get("fetch_attempts", 0) for s in self.stats.values())
        total_success = sum(s.get("fetch_success", 0) for s in self.stats.values())
        total_empty = sum(s.get("fetch_empty", 0) for s in self.stats.values())
        total_recoveries = sum(s.get("retry_recoveries", 0) for s in self.stats.values())
        total_duration = sum(s.get("total_duration_ms", 0) for s in self.stats.values())
        
        success_rate = (total_success / total_attempts * 100) if total_attempts > 0 else 0
        recovery_rate = (total_recoveries / total_empty * 100) if total_empty > 0 else 0
        
        return {
            "total_assets": len(self.stats),
            "total_attempts": total_attempts,
            "total_success": total_success,
            "total_empty": total_empty,
            "success_rate_pct": round(success_rate, 1),
            "retry_recoveries": total_recoveries,
            "recovery_rate_pct": round(recovery_rate, 1),
            "total_duration_ms": round(total_duration, 1),
            "avg_duration_per_fetch_ms": round(total_duration / total_attempts, 1) if total_attempts > 0 else 0,
        }
