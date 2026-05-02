"""
consolidation_bot.py — Estrategia de consolidación con martingala para Quotex
===============================================================================
LÓGICA COMPLETA:
  1. Escanea TODOS los activos OTC con payout >= 80%
  2. En gráfica de 5 min detecta consolidación (techo/piso):
       - Requiere MÍNIMO 15 velas dentro del rango
       - Rango máximo: 0.3% del precio (tight consolidation)
       - Zona válida por máximo 30 minutos
  3. Entrada en TECHO → PUT  $1.00
     Entrada en PISO  → CALL $1.00
  4. Si el precio ROMPE CON FUERZA (cierre fuera del rango + volumen alto):
       - Rompe TECHO con fuerza en 2do min → PUT  $3.00 (martingala)
       - Rompe PISO  con fuerza en 2do min → CALL $3.00 (martingala)
  5. "Volumen alto" = cuerpo de la vela de ruptura > 1.5x el promedio
     de los últimos 10 cuerpos (proxy de volumen en binary options)

CÓMO CORRER:
  # Dry-run — solo análisis, NO envía órdenes
  python consolidation_bot.py

  # Modo DEMO con órdenes reales
  python consolidation_bot.py --live --loop

  # Modo REAL  ⚠️ ¡CUIDADO!
  python consolidation_bot.py --live --real --loop

REQUISITOS:
  pip install pyquotex

.env (en la misma carpeta o un nivel arriba):
  QUOTEX_EMAIL=tu@email.com
  QUOTEX_PASSWORD=tupassword
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
import pandas as pd
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from datetime import timedelta
from math import ceil
from pathlib import Path
from statistics import mean
from typing import Any, Deque, List, Optional, Tuple

# ── Cargar .env ───────────────────────────────────────────────────────────────
for _candidate in (Path(__file__).parent / ".env", Path(__file__).parent.parent / ".env"):
    if _candidate.exists():
        for _ln in _candidate.read_text(encoding="utf-8").splitlines():
            _ln = _ln.strip()
            if _ln and not _ln.startswith("#") and "=" in _ln:
                _k, _, _v = _ln.partition("=")
                os.environ.setdefault(_k.strip(), _v.strip())
        break

from pyquotex.stable_api import Quotex  # type: ignore
from entry_scorer import (
    CandidateEntry,
    score_candidate,
    select_best,
    explain_score,
)
from candle_patterns import (
    detect_reversal_pattern,
    explain_no_pattern_reason,
)
from strategy_spring_sweep import detect_spring_or_upthrust
from trade_journal import get_journal
from martingale_calculator import MartingaleCalculator
from hub.hub_scanner import HubScanner
from hub.hub_models import CandidateData

# Motor de Gale — ruta relativa al ROOT del proyecto
import sys as _sys
_MG_DIR = str(Path(__file__).resolve().parent.parent)
if _MG_DIR not in _sys.path:
    _sys.path.insert(0, _MG_DIR)
try:
    from mg.mg_watcher import GaleWatcher, TradeInfo as GaleTradeInfo
    _GALE_WATCHER_AVAILABLE = True
except ImportError:
    _GALE_WATCHER_AVAILABLE = False
    GaleWatcher = None  # type: ignore
    GaleTradeInfo = None  # type: ignore

ROOT = Path(__file__).resolve().parent.parent

# ── Logging ───────────────────────────────────────────────────────────────────
_stdout_handler = logging.StreamHandler(sys.stdout)


def _clear_quotex_session(client: Any) -> None:
    """Limpia token/cookies cacheados para forzar reautenticación tras un 403."""
    email = str(getattr(client, "email", EMAIL) or EMAIL or "").strip().lower()

    for attr in ("token", "cookies", "ssid"):
        if hasattr(client, attr):
            try:
                setattr(client, attr, None)
            except Exception:
                pass

    session_paths = [ROOT / "session.json", ROOT / "sessions" / "session.json"]
    for session_path in session_paths:
        try:
            if not session_path.exists():
                continue
            payload = json.loads(session_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                if email and email in payload:
                    payload.pop(email, None)
                else:
                    payload.clear()
                session_path.write_text(
                    json.dumps(payload, indent=4, ensure_ascii=False),
                    encoding="utf-8",
                )
        except Exception as exc:
            log.debug("No se pudo limpiar %s: %s", session_path, exc)
# Forzar UTF-8 en la consola de Windows (evita UnicodeEncodeError con símbolos de caja).
_reconfigure = getattr(_stdout_handler.stream, "reconfigure", None)
if callable(_reconfigure):
    try:
        _reconfigure(encoding="utf-8")
    except Exception:
        pass

_BOT_LOG_DIR = Path(__file__).resolve().parent.parent / "data" / "logs" / "bot"
_BOT_LOG_DIR.mkdir(parents=True, exist_ok=True)
_BOT_LOG_DATE = datetime.now().strftime("%Y-%m-%d")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        _stdout_handler,
        logging.FileHandler(_BOT_LOG_DIR / f"consolidation_bot-{_BOT_LOG_DATE}.log", encoding="utf-8"),
    ],
)
logging.getLogger("pyquotex").setLevel(logging.WARNING)
# El logger websocket puede volcar HTML completo de Cloudflare (403 challenge).
# Lo elevamos para evitar ruido extremo mientras se recupera la conexión.
logging.getLogger("websocket").setLevel(logging.CRITICAL)
log = logging.getLogger("consolidation_bot")

# ═══════════════════════════════════════════════════════════════════════════════
#  PARÁMETROS DE ESTRATEGIA — editar aquí
# ═══════════════════════════════════════════════════════════════════════════════
TF_5M                  = 300     # período de vela: 5 min en segundos
TF_1M                  = 60      # período de vela: 1 min en segundos
CANDLES_LOOKBACK       = 55      # velas a pedir al broker (55 > 15+buffer)
MIN_CONSOLIDATION_BARS = 12      # mínimo de velas DENTRO del rango
MAX_RANGE_PCT          = 0.003   # 0.3% — amplitud máxima del rango
TOUCH_TOLERANCE_PCT    = 0.00035 # 0.035% — tolerancia para "tocar" techo/piso
MAX_CONSOLIDATION_MIN  = 0       # 0 = sin límite de tiempo para descartar zona
MIN_PAYOUT             = 80      # payout mínimo %
DURATION_SEC           = 300     # duración fija de cada opción binaria (5 min)
SCAN_INTERVAL_SEC      = 60      # segundos entre escaneos completos
CONNECT_RETRIES        = 3       # reintentos de conexión con delay
MAX_CONCURRENT_TRADES  = 1       # máximo de operaciones abiertas simultáneas
COOLDOWN_BETWEEN_ENTRIES = 30    # espera entre órdenes exitosas (segundos)
LIVE_SCAN_MODE           = True  # escaneo continuo "super live" guiado por flujo de Quotex
LIVE_SCAN_SLEEP_SEC      = 1.0   # pausa mínima entre ciclos live para no saturar WS
ENTRY_SYNC_TO_CANDLE     = True  # alinear entrada al inicio de vela
ENTRY_MAX_LAG_SEC        = 1.5   # cancelar si se envía tarde respecto a la vela
ENTRY_REJECT_LAST_SEC    = 2.0   # margen mínimo de seguridad sobre vela 1m
ENTRY_PRE_SEND_SEC       = 0.35  # enviar orden 350ms ANTES del open para compensar latencia WS
ENTRY_OTC_POST_OPEN_SEC  = 0.20  # en OTC enviar levemente DESPUES del open para evitar vela previa
ALIGN_SCAN_TO_CANDLE     = False # escaneo cada 60s (SCAN_INTERVAL_SEC)
SCAN_LEAD_SEC            = 35.0  # escanear ~35s antes del próximo open de 5m
MAX_LOSS_SESSION         = 0.20  # detener sesión si drawdown alcanza 20%

# Filtro "cerca de disparo" para HUB/ejecución.
HUB_NEAR_ENTRY_TOLERANCE_PCT = 0.0010  # 0.10% alrededor de piso/techo de zona
HUB_BREAKOUT_CHASE_MAX_PCT   = 0.0008  # 0.08% máximo permitido tras ruptura

# Ciclo matemático de gestión (estilo Masaniello simplificado)
CYCLE_MAX_OPERATIONS     = 6     # reinicio duro al completar 6 operaciones
CYCLE_TARGET_WINS        = 2     # objetivo mínimo de aciertos por ciclo
CYCLE_TARGET_PROFIT_PCT  = 0.10  # reiniciar ciclo al lograr +10% sobre balance base

# Rango dinámico por volatilidad (ATR)
USE_DYNAMIC_ATR_RANGE    = True
ATR_PERIOD               = 14
ATR_RANGE_FACTOR         = 1.35
MIN_DYNAMIC_RANGE_PCT    = 0.0015
MAX_DYNAMIC_RANGE_PCT    = 0.0150

# Confirmación de tendencia macro en H1
H1_CONFIRM_ENABLED       = True
H1_TF_SEC                = 3600
H1_CANDLES_LOOKBACK      = 80
H1_EMA_FAST              = 20
H1_EMA_SLOW              = 50
H1_FETCH_TIMEOUT_SEC     = 12.0
CANDLE_FETCH_TIMEOUT_SEC = 8.0
CANDLE_FETCH_1M_TIMEOUT_SEC = 12.0
FETCH_RETRIES            = 2
FETCH_RETRY_BACKOFF_SEC  = 0.35
ORDER_SEND_RETRIES       = 1
RECONNECT_TIMEOUT_SEC    = 12.0
SCAN_MAX_ASSETS_PER_CYCLE = 40
SCAN_PROGRESS_EVERY = 10

# Control de carga para evitar tormenta de requests simultáneas al broker.
CANDLE_FETCH_CONCURRENCY = 2   # reducido a 2 para evitar mezcla de respuestas WebSocket
SCAN_5M_PREFETCH_WINDOW = 8    # fetches 5m máximos en vuelo por ciclo
H1_FETCH_CONCURRENCY = 2       # fetches H1 máximos en vuelo por ciclo
OB_FETCH_CONCURRENCY = 2       # fetches de Order Block máximos en vuelo
SCAN_CANDLES_BUFFER_MAX = 20   # buffers 1m/precio para pending_reversals

# Sensor matemático para filtrar entradas con mejor expectativa
HEALTHCHECK_RECONNECT_RETRIES = 2  # intentos por ciclo si cae websocket
CF_403_BACKOFF_SEC = 8.0          # espera extra ante challenge/bloqueo 403

# Filtro de volumen: cuerpo de ruptura debe ser >= este multiplicador
# del cuerpo promedio de las últimas N velas
VOLUME_MULTIPLIER      = 1.2     # sensor de fuerza relajado: 1.2× el cuerpo medio
VOLUME_LOOKBACK        = 10      # velas para calcular cuerpo promedio
REBOUND_MIN_STRENGTH_CALL = 0.50
REBOUND_MIN_STRENGTH_PUT  = 0.65
REJECTION_CANDLE_MIN_BODY = 0.40    # body >= 40% del rango para confirmar rebote
REJECTION_CALL_MIN_LOWER_WICK = 0.30
REJECTION_PUT_MIN_UPPER_WICK = 0.30
ZONE_AGE_REBOUND_MIN = 20
ZONE_AGE_BREAKOUT_MIN = 8
ZONE_MIN_AGE_MIN = ZONE_AGE_REBOUND_MIN
# Si está activo, las rupturas fuertes validadas (BROKEN_ABOVE/BELOW)
# se envían aunque no superen el umbral dinámico de score.
FORCE_EXECUTE_STRONG_BREAKOUT = True
GREYLIST_ASSETS = {"USDDZD_otc"}
PATTERN_PUT_BLACKLIST = {"bearish_engulfing"}
STRICT_PATTERN_CHECK = True

ADAPTIVE_THRESHOLD_BASE = 65
ADAPTIVE_THRESHOLD_LOW = 62
ADAPTIVE_THRESHOLD_HIGH = 68
ADAPTIVE_THRESHOLD_WINDOW_SCANS = 10

ASSET_LOSS_STREAK_LIMIT = 3
ASSET_BLACKLIST_DURATION_MIN = 60
# Máximo de entradas consecutivas sobre el mismo activo (0 = desactivar límite).
MAX_CONSECUTIVE_ENTRIES_PER_ASSET = 2
# Enfriamiento mínimo antes de reentrar el mismo activo tras una entrada exitosa.
SAME_ASSET_REENTRY_COOLDOWN_SEC = 65
# Una sola entrada por estructura (zona) dentro de una ventana temporal.
# 0 = desactivar bloqueo por estructura.
STRUCTURE_ENTRY_LOCK_TTL_MIN = 180

ORDER_BLOCK_LOOKBACK = 50
ORDER_BLOCK_MAX_PER_SIDE = 3
ORDER_BLOCK_MIN_MOVE_PCT = 0.002
ORDER_BLOCK_TOUCH_TOLERANCE_PCT = 0.0003
ORDER_BLOCK_TF_SEC = 180
ORDER_BLOCK_CANDLES = 55

MA_LOOKBACK_CANDLES = 60
MA_FAST_PERIOD = 35
MA_SLOW_PERIOD = 50
MA_FLAT_DELTA_PCT = 0.0005
DRY_RUN_VERBOSE = True

EMAIL    = os.environ.get("QUOTEX_EMAIL", "")
PASSWORD = os.environ.get("QUOTEX_PASSWORD", "")

# Zona horaria operativa del broker/gráfica
BROKER_TZ = timezone(timedelta(hours=-3))
BROKER_TZ_LABEL = "UTC-3"

# Gestión de monto dinámico para cerrar en enteros y evitar centavos residuales.
MIN_ORDER_AMOUNT       = 1.00
MARTIN_MAX_PCT_BALANCE = 0.20  # cap global: martingala <= 20% del balance actual
MARTIN_MAX_ATTEMPTS_SESSION = 2
MARTIN_LOW_BALANCE_THRESHOLD = 100.0
MARTIN_MAX_ATTEMPTS_LOW_BALANCE = 3
PENDING_RECONCILE_AGE_MIN = 15.0
MARTIN_MONITOR_INTERVAL_SEC = 1.0
MARTIN_ALERT_PCT       = 0.0005  # 0.05% en contra = pérdida probable
MARTIN_LIVE_WINDOW_MIN_SEC = 30.0
MARTIN_LIVE_WINDOW_MAX_SEC = 60.0
MARTIN_RESOLVE_GRACE_SEC = 5.0
MARTIN_RESOLVE_TIMEOUT_SEC = 8.0
MARTIN_RESOLVE_RETRY_SEC = 5.0
MARTIN_RESOLVE_MAX_ATTEMPTS = 3

# STRAT-B (Spring Sweep) en paralelo (modo espejo por defecto)
STRAT_B_CAN_TRADE      = True
STRAT_B_DURATION_SEC   = 300
STRAT_B_MIN_CONFIDENCE = 0.70
STRAT_B_MIN_CONFIDENCE_EARLY = 0.62
STRAT_B_ALLOW_WYCKOFF_EARLY = True
STRAT_B_LOG_TOP_N      = 3
STRAT_B_PREVIEW_MIN_CONF = 0.45

# Captura forense de velas para eventos BROKEN_* (auditoría operativa)
BROKEN_CAPTURE_DIR = Path(__file__).resolve().parent.parent / "data" / "vela_ops"
BROKEN_FOLLOWUP_DELAY_SEC = 15 * 60
# Guardar 40 velas post-evento permite validar patrones 40/40 de forma consistente.
BROKEN_FOLLOWUP_1M_COUNT = 40


# ═══════════════════════════════════════════════════════════════════════════════
#  ESTRUCTURAS DE DATOS
# ═══════════════════════════════════════════════════════════════════════════════
from models import Candle, ConsolidationZone  # noqa: E402  (shared with entry_scorer)


@dataclass
class TradeState:
    asset:         str
    direction:     str    # "call" | "put"
    amount:        float
    entry_price:   float
    ceiling:       float
    floor:         float
    order_id:      str   = ""
    order_ref:     int   = 0
    opened_at:     float = field(default_factory=time.time)
    martin_fired:  bool  = False
    stage:         str   = "initial"
    journal_id:    int   = 0
    strategy_origin: str = "STRAT-A"
    duration_sec: int = DURATION_SEC
    payout: int = MIN_PAYOUT
    resolved: bool = False
    score_original: float = 0.0


@dataclass
class EntryTimingInfo:
    ok: bool
    lag_sec: float
    duration_sec: int
    time_since_open_sec: float
    secs_to_close_sec: float
    decision: str


@dataclass
class PendingReversal:
    """Activo esperando confirmación de patrón 1m antes de entrar."""
    asset: str
    zone: ConsolidationZone
    proposed_direction: str          # "call" o "put"
    conflicting_pattern: str         # patrón que causó el conflicto
    detected_at: datetime
    entry_mode: str                  # "rebound_floor" o "rebound_ceiling"
    payout: int
    max_wait_scans: int = 3
    scans_waited: int = 0


@dataclass
class MartinPending:
    asset: str
    amount: float
    original_loss: float
    created_at: datetime
    score_original: float = 0.0
    max_wait_scans: int = 2
    scans_waited: int = 0


@dataclass
class OrderBlock:
    side: str          # "bull" | "bear"
    low: float
    high: float
    created_ts: int
    created_index: int
    bars_ago: int = 0
    is_mitigated: bool = False  # True si el precio entró en zona pero no cerró del lado opuesto


@dataclass
class MAState:
    ma35: float
    ma50: float
    trend: str         # "UP" | "DOWN" | "FLAT"
    cross: str         # "GOLDEN" | "DEATH" | "NONE"
    avg_body: float = 0.0  # Promedio de cuerpos de última ventana (para impulsos OB)
    price: float = 0.0     # Precio de cierre actual (para filtro de posición vs MAs)


# ═══════════════════════════════════════════════════════════════════════════════
#  FUNCIONES DE ANÁLISIS
# ═══════════════════════════════════════════════════════════════════════════════
def raw_to_candle(raw: dict) -> Optional[Candle]:
    try:
        return Candle(
            ts=int(raw["time"]),
            open=float(raw["open"]),
            high=float(raw["high"]),
            low=float(raw["low"]),
            close=float(raw["close"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def avg_body(candles: List[Candle], n: int = VOLUME_LOOKBACK) -> float:
    """Promedio del cuerpo de las últimas n velas (excluye la vela actual)."""
    recent = candles[-(n + 1):-1] if len(candles) > n else candles[:-1]
    if not recent:
        return 0.0
    return mean(c.body for c in recent) or 0.0


def is_high_volume_break(candle: Candle, candles_history: List[Candle]) -> bool:
    """
    Ruptura con fuerza = cierre fuera del rango + cuerpo de la vela
    es al menos VOLUME_MULTIPLIER veces el cuerpo promedio reciente.
    """
    avg = avg_body(candles_history)
    if avg == 0:
        return True   # sin historia, asumir que hay fuerza
    return candle.body >= avg * VOLUME_MULTIPLIER


def _clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))


def _ema(values: List[float], period: int) -> List[float]:
    if len(values) < period:
        return []
    k = 2 / (period + 1)
    result = [mean(values[:period])]
    for v in values[period:]:
        result.append(v * k + result[-1] * (1 - k))
    return result


def compute_atr(candles: List[Candle], period: int = ATR_PERIOD) -> float:
    if len(candles) < period + 1:
        return 0.0
    trs: List[float] = []
    for i in range(1, len(candles)):
        c = candles[i]
        prev = candles[i - 1]
        tr = max(
            c.high - c.low,
            abs(c.high - prev.close),
            abs(c.low - prev.close),
        )
        trs.append(tr)
    if len(trs) < period:
        return 0.0
    return mean(trs[-period:])


def infer_h1_trend(candles_h1: List[Candle]) -> str:
    """Devuelve bullish, bearish o neutral según EMA20/EMA50 en H1."""
    if len(candles_h1) < H1_EMA_SLOW + 5:
        return "neutral"
    closes = [c.close for c in candles_h1]
    ef = _ema(closes, H1_EMA_FAST)
    es = _ema(closes, H1_EMA_SLOW)
    if not ef or not es:
        return "neutral"
    ef_last = ef[-1]
    es_last = es[-1]
    price = closes[-1]
    if ef_last > es_last and price >= ef_last:
        return "bullish"
    if ef_last < es_last and price <= ef_last:
        return "bearish"
    return "neutral"


def detect_consolidation(
    candles: List[Candle],
    max_range_pct: float = MAX_RANGE_PCT,
) -> Optional[ConsolidationZone]:
    """
    Detecta consolidación en las últimas velas.

    Desliza una ventana de MIN_CONSOLIDATION_BARS velas buscando la más
    reciente donde:
      - rango high-low total <= MAX_RANGE_PCT
      - todas las velas cierran dentro del rango
    """
    needed = MIN_CONSOLIDATION_BARS + 2
    if len(candles) < needed:
        return None

    for end in range(len(candles), MIN_CONSOLIDATION_BARS - 1, -1):
        start  = end - MIN_CONSOLIDATION_BARS
        window = candles[start:end]

        ceiling = max(c.high for c in window)
        floor   = min(c.low  for c in window)
        mid     = (ceiling + floor) / 2
        if mid == 0:
            continue

        range_pct = (ceiling - floor) / mid
        if range_pct > max_range_pct:
            continue

        bars_inside = sum(1 for c in window if floor <= c.close <= ceiling)
        if bars_inside < MIN_CONSOLIDATION_BARS:
            continue

        touches_ceiling = sum(
            1 for c in window if c.high >= ceiling * (1 - TOUCH_TOLERANCE_PCT)
        )
        touches_floor = sum(
            1 for c in window if c.low <= floor * (1 + TOUCH_TOLERANCE_PCT)
        )
        if (touches_ceiling + touches_floor) < 2:
            continue

        return ConsolidationZone(
            asset="",
            ceiling=ceiling,
            floor=floor,
            bars_inside=bars_inside,
            detected_at=time.time(),
            range_pct=range_pct,
        )

    return None


def price_at_ceiling(
    price: float,
    ceiling: float,
    tolerance_pct: float = TOUCH_TOLERANCE_PCT,
) -> bool:
    return abs(price - ceiling) / ceiling <= tolerance_pct


def price_at_floor(
    price: float,
    floor: float,
    tolerance_pct: float = TOUCH_TOLERANCE_PCT,
) -> bool:
    return abs(price - floor) / floor <= tolerance_pct


def broke_above(candle: Candle, ceiling: float) -> bool:
    return candle.close > ceiling * (1 + TOUCH_TOLERANCE_PCT)


def broke_below(candle: Candle, floor: float) -> bool:
    return candle.close < floor * (1 - TOUCH_TOLERANCE_PCT)


# ═══════════════════════════════════════════════════════════════════════════════
#  HELPERS DE BROKER
# ═══════════════════════════════════════════════════════════════════════════════
async def fetch_candles(
    client: Quotex,
    asset: str,
    tf_sec: int,
    count: int,
) -> List[Candle]:
    end_time = time.time()
    offset   = count * tf_sec
    try:
        raw_list = await client.get_candles(asset, end_time, offset, tf_sec)
    except Exception as exc:
        log.debug("Error velas %s tf=%ss: %s", asset, tf_sec, exc)
        return []
    if not raw_list:
        return []
    candles = [raw_to_candle(r) for r in raw_list if isinstance(r, dict)]
    valid = [c for c in candles if c and c.high > 0]
    return sorted(valid, key=lambda c: c.ts)


async def fetch_candles_with_retry(
    client: Quotex,
    asset: str,
    tf_sec: int,
    count: int,
    timeout_sec: float,
    retries: int = FETCH_RETRIES,
) -> List[Candle]:
    """Fetch robusto con timeout local + reintentos cortos con backoff."""
    attempts = max(1, int(retries))
    for attempt in range(1, attempts + 1):
        try:
            candles = await asyncio.wait_for(
                fetch_candles(client, asset, tf_sec, count),
                timeout=timeout_sec,
            )
            if candles:
                return candles
        except asyncio.TimeoutError:
            log.debug(
                "%s: timeout local velas tf=%ss intento %d/%d (%.1fs)",
                asset,
                tf_sec,
                attempt,
                attempts,
                timeout_sec,
            )
        except Exception as exc:
            log.debug(
                "%s: error velas tf=%ss intento %d/%d: %s",
                asset,
                tf_sec,
                attempt,
                attempts,
                exc,
            )

        if attempt < attempts:
            await asyncio.sleep(FETCH_RETRY_BACKOFF_SEC * attempt)

    return []


def find_strong_support_2m(
    candles: List[Candle],
    lookback: int = 90,
) -> Tuple[Optional[float], int]:
    """Devuelve (precio_soporte, toques) usando pivotes de low en 2m."""
    if len(candles) < 7:
        return None, 0

    sample = candles[-lookback:] if len(candles) > lookback else candles[:]
    avg_price = mean([c.close for c in sample]) if sample else 0.0
    if avg_price <= 0:
        return None, 0

    # Tolerancia de agrupación: 0.06% del precio medio.
    tol = max(avg_price * 0.0006, 1e-6)

    pivots: List[float] = []
    for i in range(2, len(sample) - 2):
        low = sample[i].low
        if (
            low <= sample[i - 1].low
            and low <= sample[i + 1].low
            and low <= sample[i - 2].low
            and low <= sample[i + 2].low
        ):
            pivots.append(low)

    if not pivots:
        return None, 0

    # Clustering simple por proximidad de precio.
    clusters: List[dict[str, Any]] = []
    for p in pivots:
        matched = False
        for c in clusters:
            if abs(p - c["center"]) <= tol:
                c["values"].append(p)
                c["center"] = mean(c["values"])
                matched = True
                break
        if not matched:
            clusters.append({"center": p, "values": [p]})

    best_price: Optional[float] = None
    best_touches = 0
    for c in clusters:
        center = float(c["center"])
        touches = sum(1 for bar in sample if abs(bar.low - center) <= tol)
        if touches > best_touches:
            best_touches = touches
            best_price = center

    if best_price is None:
        return None, 0
    return round(best_price, 5), int(best_touches)


async def get_open_assets(client: Quotex, min_payout: int = MIN_PAYOUT) -> List[Tuple[str, int]]:
    try:
        instruments = await client.get_instruments()
    except Exception:
        return []
    if not instruments:
        return []

    result = []
    for i in instruments:
        try:
            sym     = str(i[1])
            is_open = bool(i[14])
            payout  = int(i[18]) if len(i) > 18 else 0
        except (IndexError, TypeError, ValueError):
            continue
        if sym.endswith("_otc") and is_open and payout >= min_payout:
            result.append((sym, payout))

    result.sort(key=lambda x: -x[1])
    return result


def looks_like_connection_issue(reason: str) -> bool:
    text = (reason or "").lower()
    conn_hints = (
        "websocket", "handshake", "403", "connect", "connection",
        "session", "closed", "disconnect", "network", "socket",
        "reconnect", "timeout", "remote host was lost",
    )
    return any(hint in text for hint in conn_hints)


async def place_order(
    client: Quotex, asset: str, direction: str,
    amount: float, duration: int, dry_run: bool,
    account_type: str = "PRACTICE",
) -> Tuple[bool, str, float, int, str]:
    if dry_run:
        log.info("  [DRY-RUN] %s %s $%.2f %ds",
                 direction.upper(), asset, amount, duration)
        return True, f"DRY-{int(time.time())}", 0.0, 0, ""

    # Activos equity OTC (stocks) pueden tener restricciones de horario
    # aunque aparezcan como "open" en el scanner.
    _EQUITY_OTC_MARKERS = ("MCD", "JNJ", "AXP", "AMZN", "AAPL", "GOOGL", "MSFT", "TSLA",
                           "NFLX", "META", "NVDA", "BAC", "GS", "V", "WMT")
    _asset_upper = asset.upper()
    if any(_asset_upper.startswith(m) for m in _EQUITY_OTC_MARKERS):
        log.warning(
            "  ⚠ Activo equity OTC (%s) — puede tener restricciones de horario "
            "aunque aparezca como open.", asset,
        )

    async def _force_reconnect(step_label: str) -> Tuple[bool, str]:
        log.info("🔌 Reconexión %s: %s %s $%.2f", step_label, asset, direction.upper(), amount)
        last_reason = ""
        for attempt in range(1, CONNECT_RETRIES + 1):
            try:
                await client.close()
            except Exception:
                pass

            await asyncio.sleep(1.0)
            try:
                ok_conn, reason_conn = await asyncio.wait_for(
                    client.connect(),
                    timeout=RECONNECT_TIMEOUT_SEC,
                )
            except asyncio.TimeoutError:
                last_reason = f"reconnect_timeout_connect_{RECONNECT_TIMEOUT_SEC:.0f}s"
                log.warning("  Reconexión %s timeout en connect() intento %d/%d", step_label, attempt, CONNECT_RETRIES)
                continue
            except Exception as exc:
                last_reason = f"reconnect_exception_connect:{exc}"
                log.warning("  Reconexión %s excepción en connect() intento %d/%d: %s", step_label, attempt, CONNECT_RETRIES, exc)
                continue

            if not ok_conn:
                last_reason = f"reconnect_failed:{reason_conn}"
                log.warning("  Reconexión %s fallida intento %d/%d: %s", step_label, attempt, CONNECT_RETRIES, reason_conn)
                continue

            try:
                await asyncio.wait_for(
                    client.change_account(account_type),
                    timeout=RECONNECT_TIMEOUT_SEC,
                )
            except asyncio.TimeoutError:
                last_reason = f"reconnect_timeout_change_account_{RECONNECT_TIMEOUT_SEC:.0f}s"
                log.warning("  Reconexión %s timeout en change_account() intento %d/%d", step_label, attempt, CONNECT_RETRIES)
                continue
            except Exception as exc:
                last_reason = f"reconnect_exception_change_account:{exc}"
                log.warning("  Reconexión %s excepción en change_account() intento %d/%d: %s", step_label, attempt, CONNECT_RETRIES, exc)
                continue

            await asyncio.sleep(0.6)
            return True, ""

        return False, last_reason or "reconnect_failed_without_reason"

    async def _log_pre_buy() -> None:
        try:
            ws_alive = await client.check_connect()
        except Exception:
            ws_alive = False
        log.info(
            "🔍 Pre-buy | asset=%s dir=%s amount=%.2f ws_alive=%s account=%s",
            asset, direction.upper(), amount, ws_alive, account_type,
        )

    # ── RECONEXIÓN AGRESIVA — siempre antes de buy() ──────────────────────────
    # No confiamos en check_connect(): aunque el socket parezca vivo,
    # el estado de sesión con Quotex puede estar degradado.
    ok_reconnect, reconnect_reason = await _force_reconnect("pre-orden")
    if not ok_reconnect:
        log.error("  Reconexión pre-orden fallida: %s", reconnect_reason)
        return False, "", 0.0, 0, reconnect_reason

    await _log_pre_buy()

    # ── UN SOLO INTENTO CON TIMEOUT LOCAL DE 30s ───────────────────────────────
    t0 = time.time()
    try:
        status, info = await asyncio.wait_for(
            client.buy(
                amount=amount,
                asset=asset,
                direction=direction,
                duration=duration,
            ),
            timeout=30.0,
        )
    except asyncio.TimeoutError:
        elapsed = time.time() - t0
        log.warning(
            "  ⏱ buy() sin respuesta en 30s (elapsed=%.1fs) — orden posiblemente "
            "abierta en broker. Verificar manualmente.",
            elapsed,
        )
        return False, "", 0.0, 0, "buy_timeout_30s"
    except Exception as exc:
        elapsed = time.time() - t0
        first_reason = f"buy_exception:{exc}"
        log.error("  Excepción en buy() elapsed=%.2fs: %s", elapsed, exc)
        if not looks_like_connection_issue(first_reason):
            return False, "", 0.0, 0, first_reason

        log.warning("  ↻ Falla de conexión detectada en buy(); reintentando una vez...")
        ok_reconnect, reconnect_reason = await _force_reconnect("reintento")
        if not ok_reconnect:
            log.error("  Reconexión de reintento fallida: %s", reconnect_reason)
            return False, "", 0.0, 0, f"{first_reason} | {reconnect_reason}"
        await _log_pre_buy()
        t0_retry = time.time()
        try:
            status, info = await asyncio.wait_for(
                client.buy(
                    amount=amount,
                    asset=asset,
                    direction=direction,
                    duration=duration,
                ),
                timeout=30.0,
            )
            elapsed = time.time() - t0_retry
        except asyncio.TimeoutError:
            elapsed_retry = time.time() - t0_retry
            log.warning(
                "  ⏱ buy() reintento sin respuesta en 30s (elapsed=%.1fs)",
                elapsed_retry,
            )
            return False, "", 0.0, 0, "buy_timeout_30s_retry"
        except Exception as retry_exc:
            elapsed_retry = time.time() - t0_retry
            retry_reason = f"buy_exception_retry:{retry_exc}"
            log.error("  Excepción en buy() reintento elapsed=%.2fs: %s", elapsed_retry, retry_exc)
            return False, "", 0.0, 0, retry_reason

    elapsed = time.time() - t0

    if status and isinstance(info, dict):
        log.debug("  Respuesta broker (%.2fs): %s", elapsed, info)
        order_ref = 0
        for key in ("id_number", "idNumber", "openOrderId", "ticket"):
            raw_val = info.get(key)
            try:
                if raw_val is not None:
                    order_ref = int(raw_val)
                    break
            except (TypeError, ValueError):
                continue
        return True, info.get("id", ""), float(info.get("openPrice", 0)), order_ref, ""

    log.error(
        "  Orden rechazada por broker. status=%s info=%s elapsed=%.2fs",
        status, info, elapsed,
    )
    reject_reason = "broker_rejected"
    if isinstance(info, dict):
        reject_reason = str(
            info.get("message")
            or info.get("reason")
            or info.get("error")
            or reject_reason
        )
    elif info is not None:
        reject_reason = str(info)

    if looks_like_connection_issue(reject_reason):
        log.warning("  ↻ Rechazo de conexión detectado (%s); reintentando una vez...", reject_reason)
        ok_reconnect, reconnect_reason = await _force_reconnect("reintento")
        if not ok_reconnect:
            log.error("  Reconexión de reintento fallida: %s", reconnect_reason)
            return False, "", 0.0, 0, f"{reject_reason} | {reconnect_reason}"

        await _log_pre_buy()
        t0_retry = time.time()
        try:
            status_retry, info_retry = await asyncio.wait_for(
                client.buy(
                    amount=amount,
                    asset=asset,
                    direction=direction,
                    duration=duration,
                ),
                timeout=30.0,
            )
        except asyncio.TimeoutError:
            elapsed_retry = time.time() - t0_retry
            log.warning(
                "  ⏱ buy() reintento sin respuesta en 30s (elapsed=%.1fs)",
                elapsed_retry,
            )
            return False, "", 0.0, 0, "buy_timeout_30s_retry"
        except Exception as retry_exc:
            elapsed_retry = time.time() - t0_retry
            retry_reason = f"buy_exception_retry:{retry_exc}"
            log.error("  Excepción en buy() reintento elapsed=%.2fs: %s", elapsed_retry, retry_exc)
            return False, "", 0.0, 0, retry_reason

        elapsed_retry = time.time() - t0_retry
        if status_retry and isinstance(info_retry, dict):
            log.info("  ✅ Reintento exitoso en broker (%.2fs)", elapsed_retry)
            order_ref = 0
            for key in ("id_number", "idNumber", "openOrderId", "ticket"):
                raw_val = info_retry.get(key)
                try:
                    if raw_val is not None:
                        order_ref = int(raw_val)
                        break
                except (TypeError, ValueError):
                    continue
            return True, info_retry.get("id", ""), float(info_retry.get("openPrice", 0)), order_ref, ""

        retry_reason = "broker_rejected_retry"
        if isinstance(info_retry, dict):
            retry_reason = str(
                info_retry.get("message")
                or info_retry.get("reason")
                or info_retry.get("error")
                or retry_reason
            )
        elif info_retry is not None:
            retry_reason = str(info_retry)
        return False, "", 0.0, 0, retry_reason

    return False, "", 0.0, 0, reject_reason


# ═══════════════════════════════════════════════════════════════════════════════
#  BOT PRINCIPAL
# ═══════════════════════════════════════════════════════════════════════════════
class ConsolidationBot:

    def __init__(
        self,
        client: Quotex,
        dry_run: bool,
        account_type: str = "PRACTICE",
        greylist_assets: Optional[set[str]] = None,
    ):
        self.client      = client
        self.dry_run     = dry_run
        self.account_type = account_type
        self.zones:  dict[str, ConsolidationZone] = {}
        self.broken_zones: dict[str, float] = {}
        self.trades: dict[str, TradeState]        = {}
        self.stats = {
            "scans": 0, "entries": 0, "martins": 0,
            "expired_zones": 0, "skipped": 0, "filtered_sensor": 0,
            "strat_a_signals": 0, "strat_b_signals": 0,
            "strat_a_wins": 0, "strat_a_losses": 0,
            "strat_b_wins": 0, "strat_b_losses": 0,
            "score_rejected_age": 0,   # candidatos rechazados por penaliz. antigüedad
            "score_rejected_score": 0, # candidatos rechazados por score < umbral
            "rejected_young_zone": 0,
            "martin_attempts_session": 0,
            "martin_wins": 0,
            "martin_losses": 0,
            "rejected_same_asset_limit": 0,
            "rejected_same_asset_cooldown": 0,
            "rejected_same_structure": 0,
        }
        # Estado de compensación: si la última operación cerró LOSS,
        # la próxima entrada usará monto dinámico de compensación para cubrir esa pérdida.
        self.compensation_pending:  bool  = False
        self.last_closed_amount:    float = 0.0
        self.last_closed_outcome:   str   = ""
        self.session_start_balance: Optional[float] = None
        self.current_balance:       Optional[float] = None
        self.martingale:            MartingaleCalculator = MartingaleCalculator()
        self.session_stop_hit:      bool = False
        self.cycle_id:              int = 1
        self.cycle_ops:             int = 0
        self.cycle_wins:            int = 0
        self.cycle_losses:          int = 0
        self.cycle_profit:          float = 0.0
        self.cycle_start_balance:   Optional[float] = None
        # Oportunidades vigiladas mientras hay un trade activo.
        # key=asset, value=(CandidateEntry, timestamp_detectado)
        self.watched_candidates:    dict = {}
        self.capture_dir = BROKEN_CAPTURE_DIR
        self.capture_dir.mkdir(parents=True, exist_ok=True)
        self._followup_capture_tasks: set[asyncio.Task[Any]] = set()
        # Último precio válido conocido por activo — detecta contaminación cruzada.
        self.last_known_price: dict[str, float] = {}
        # Activos que fallaron en place_order() — skippear por 2 ciclos.
        # key=asset, value=ciclos_restantes_a_skipear
        self.failed_assets: dict[str, int] = {}
        # Activos esperando confirmación de patrón 1m (espera activa de reversión).
        self.pending_reversals: dict[str, PendingReversal] = {}
        # Martingalas diferidas: esperan hasta 2 scans a que reaparezca señal válida.
        self.pending_martin: dict[str, MartinPending] = {}
        # Umbral adaptativo de score basado en aceptación reciente por scan.
        self.accepted_scans_window: Deque[int] = deque(maxlen=ADAPTIVE_THRESHOLD_WINDOW_SCANS)
        self.current_score_threshold: int = ADAPTIVE_THRESHOLD_BASE
        # Control de repetición de activo para evitar sobre-exposición por momentum.
        self.last_entry_asset: Optional[str] = None
        self.last_entry_asset_streak: int = 0
        self.last_entry_ts_by_asset: dict[str, float] = {}
        # Candado de estructuras ya operadas: key -> timestamp de última entrada.
        self.structure_entry_locks: dict[str, float] = {}
        # Blacklist temporal de activos por racha de pérdidas.
        # Hub para registrar candidatos en tiempo real
        self.hub = HubScanner()
        self.last_scan_strat_a: List[CandidateEntry] = []
        self.last_scan_strat_b: List[CandidateEntry] = []
        # Motor de Gale — vigila operaciones activas y dispara compensación en T-1s
        if _GALE_WATCHER_AVAILABLE:
            self._gale_watcher = GaleWatcher(
                fetch_price_fn=self._get_current_price,
                place_order_fn=self._gale_place_order,
                calculator=self.martingale,
                get_balance_fn=self._gale_get_balance,
                dry_run=dry_run,
                on_status_fn=self.hub.update_gale_state,
                on_clear_fn=self.hub.clear_gale_state,
            )
        else:
            self._gale_watcher = None
        self._gale_tasks: set[asyncio.Task] = set()
        self.asset_loss_streaks: dict[str, int] = {}
        self.asset_blacklist_until: dict[str, float] = {}
        # Estado técnico por activo para filtros adicionales.
        self.order_blocks_by_asset: dict[str, dict[str, list[OrderBlock]]] = {}
        self.ma_state_by_asset: dict[str, MAState] = {}
        self._trade_tasks: set[asyncio.Task[Any]] = set()
        self.greylist_assets = set(GREYLIST_ASSETS)
        # Offset de reloj servidor: diferencia entre ts de última vela y reloj local (segundos).
        # Se actualiza con cada fetch de velas para compensar drift del reloj local.
        self._clock_offset: float = 0.0
        self._candle_phase_sec: int = 0
        if greylist_assets is not None:
            self.greylist_assets = {a.strip() for a in greylist_assets if a and a.strip()}

    @staticmethod
    def _serialize_candles(candles: List[Candle]) -> list[dict[str, float | int]]:
        return [
            {
                "ts": int(c.ts),
                "open": float(c.open),
                "high": float(c.high),
                "low": float(c.low),
                "close": float(c.close),
                "body": float(c.body),
                "range": float(c.range),
            }
            for c in candles
        ]

    def _broken_capture_file(self, asset: str, reason: str, expired_zone_id: int) -> Path:
        ts = datetime.now(tz=BROKER_TZ).strftime("%Y%m%d_%H%M%S")
        safe_asset = "".join(ch if (ch.isalnum() or ch in ("_", "-")) else "_" for ch in asset)
        return self.capture_dir / f"{ts}_{safe_asset}_{reason}_{expired_zone_id}.json"

    def _write_capture_payload(self, file_path: Path, payload: dict[str, Any]) -> None:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _record_broken_zone_snapshot(
        self,
        *,
        asset: str,
        payout: int,
        reason: str,
        expired_zone_id: int,
        zone: ConsolidationZone,
        last: Candle,
        candles_1m_used: List[Candle],
        candles_5m_used: List[Candle],
    ) -> Path:
        capture_file = self._broken_capture_file(asset, reason, expired_zone_id)
        trigger_ts = int(last.ts)
        pre_40_1m = [c for c in candles_1m_used if int(c.ts) < trigger_ts][-40:]
        post_40_1m_initial = [c for c in candles_1m_used if int(c.ts) > trigger_ts][:40]
        payload = {
            "event_type": "BROKEN_ZONE",
            "saved_at": datetime.now(tz=BROKER_TZ).isoformat(),
            "asset": asset,
            "reason": reason,
            "expired_zone_id": int(expired_zone_id),
            "payout": int(payout),
            "zone": {
                "ceiling": float(zone.ceiling),
                "floor": float(zone.floor),
                "range_pct": float(zone.range_pct),
                "bars_inside": int(zone.bars_inside),
                "age_min": float(zone.age_minutes),
            },
            "trigger_candle_5m": {
                "ts": int(last.ts),
                "open": float(last.open),
                "high": float(last.high),
                "low": float(last.low),
                "close": float(last.close),
                "body": float(last.body),
            },
            "analysis_1m": {
                "target_window": {
                    "pre": 40,
                    "post": 40,
                },
                "pre_40": self._serialize_candles(pre_40_1m),
                "post_40_initial": self._serialize_candles(post_40_1m_initial),
            },
            "candles_1m_used": self._serialize_candles(candles_1m_used[-60:]),
            "candles_5m_zone_context": self._serialize_candles(candles_5m_used[-24:]),
            "followup": {
                "delay_sec": BROKEN_FOLLOWUP_DELAY_SEC,
                "requested_candles_1m": BROKEN_FOLLOWUP_1M_COUNT,
                "status": "pending",
                "saved_at": None,
                "candles_1m": [],
                "error": None,
            },
        }
        self._write_capture_payload(capture_file, payload)
        return capture_file

    async def _capture_followup_after_delay(self, asset: str, capture_file: Path) -> None:
        try:
            await asyncio.sleep(BROKEN_FOLLOWUP_DELAY_SEC)
            followup_1m = await fetch_candles_with_retry(
                self.client,
                asset,
                60,
                BROKEN_FOLLOWUP_1M_COUNT,
                timeout_sec=CANDLE_FETCH_1M_TIMEOUT_SEC,
            )
            payload = json.loads(capture_file.read_text(encoding="utf-8"))
            payload.setdefault("followup", {})
            payload["followup"]["status"] = "saved"
            payload["followup"]["saved_at"] = datetime.now(tz=BROKER_TZ).isoformat()
            payload["followup"]["candles_1m"] = self._serialize_candles(followup_1m)
            payload["followup"]["error"] = None
            self._write_capture_payload(capture_file, payload)
            log.info("🧾 %s: follow-up 1m guardado (%d velas) -> %s", asset, len(followup_1m), capture_file.name)
        except Exception as exc:
            try:
                payload = json.loads(capture_file.read_text(encoding="utf-8"))
                payload.setdefault("followup", {})
                payload["followup"]["status"] = "error"
                payload["followup"]["saved_at"] = datetime.now(tz=BROKER_TZ).isoformat()
                payload["followup"]["error"] = str(exc)
                self._write_capture_payload(capture_file, payload)
            except Exception:
                pass
            log.warning("⚠ %s: no se pudo guardar follow-up 1m (%s)", asset, exc)

    def _schedule_followup_capture(self, asset: str, capture_file: Path) -> None:
        task = asyncio.create_task(
            self._capture_followup_after_delay(asset, capture_file),
            name=f"followup_1m:{asset}",
        )
        self._followup_capture_tasks.add(task)
        task.add_done_callback(self._on_background_task_done)

    def set_session_start_balance(self, balance: float) -> None:
        self.session_start_balance = float(balance)
        self.current_balance = float(balance)
        self.martingale.set_balance(float(balance))
        self.hub.state.known_balance = float(balance)
        if self.cycle_start_balance is None:
            self.cycle_start_balance = float(balance)

    @staticmethod
    def _round_up_to_cents(value: float) -> float:
        return ceil(max(0.0, value) * 100.0) / 100.0

    def _compute_initial_amount(self, payout_pct: int) -> Tuple[float, float]:
        """
        Calcula monto inicial usando MartingaleCalculator.
        Retorna (monto, ganancia_esperada).
        """
        if self.current_balance is not None:
            self.martingale.set_balance(self.current_balance)

        amount, status = self.martingale.calculate_investment(payout_pct)

        if status != "OK":
            log.warning(f"⚠ _compute_initial_amount: {status} | amount={amount:.2f}")
            return 0.0, 0.0

        # Calcular ganancia esperada
        payout_rate = max(0.01, float(payout_pct) / 100.0)
        expected_profit = self._round_up_to_cents(amount * payout_rate)

        return amount, expected_profit

    def _compute_compensation_amount(self, payout_pct: int, base_loss: float) -> Tuple[float, float]:
        """
        Calcula monto de compensación (gale) usando MartingaleCalculator.
        Retorna (monto, ganancia_esperada).
        """
        # Registra pérdida anterior
        if self.current_balance is not None:
            self.martingale.set_balance(self.current_balance)

        # Calcula inversión para el próximo gale
        amount, status = self.martingale.calculate_investment(payout_pct)

        if status != "OK":
            log.warning(f"⚠ _compute_compensation_amount: {status} | amount={amount:.2f}")
            return 0.0, 0.0

        payout_rate = max(0.01, float(payout_pct) / 100.0)
        expected_profit = self._round_up_to_cents(amount * payout_rate)

        return amount, expected_profit

    def _candidate_trigger_distance_pct(self, candidate: CandidateEntry) -> Optional[float]:
        """Distancia relativa del precio actual al gatillo operativo del candidato."""
        price = self.last_known_price.get(candidate.asset)
        if price is None or price <= 0:
            return None

        zone = candidate.zone
        entry_mode = str(getattr(candidate, "_entry_mode", "rebound_floor") or "rebound_floor")
        direction = str(candidate.direction or "").lower()

        if entry_mode == "rebound_floor" or direction == "call":
            if zone.floor <= 0:
                return None
            return abs(price - zone.floor) / zone.floor

        if entry_mode == "rebound_ceiling" or direction == "put":
            if zone.ceiling <= 0:
                return None
            return abs(price - zone.ceiling) / zone.ceiling

        if entry_mode == "breakout_above":
            if zone.ceiling <= 0:
                return None
            if price < zone.ceiling:
                return None
            return (price - zone.ceiling) / zone.ceiling

        if entry_mode == "breakout_below":
            if zone.floor <= 0:
                return None
            if price > zone.floor:
                return None
            return (zone.floor - price) / zone.floor

        return None

    def _is_candidate_near_trigger(self, candidate: CandidateEntry) -> bool:
        """True si el activo está lo suficientemente cerca para posible ejecución."""
        distance = self._candidate_trigger_distance_pct(candidate)
        if distance is None:
            return False

        entry_mode = str(getattr(candidate, "_entry_mode", "rebound_floor") or "rebound_floor")
        if entry_mode.startswith("breakout"):
            return distance <= HUB_BREAKOUT_CHASE_MAX_PCT
        return distance <= HUB_NEAR_ENTRY_TOLERANCE_PCT

    def _record_hub_scan_cycle(self, total_assets: int) -> None:
        """Actualiza el estado del HUB con los candidatos del ciclo actual."""
        try:
            strat_a_for_hub = []
            sorted_a = sorted(self.last_scan_strat_a, key=lambda c: c.score, reverse=True)
            for candidate in sorted_a[:5]:
                try:
                    dist = self._candidate_trigger_distance_pct(candidate)
                    cd = CandidateData(
                        strategy="STRAT-A",
                        asset=candidate.asset,
                        direction=candidate.direction,
                        score=candidate.score,
                        payout=candidate.payout,
                        zone_ceiling=candidate.zone.ceiling if candidate.zone else 0.0,
                        zone_floor=candidate.zone.floor if candidate.zone else 0.0,
                        zone_age_min=candidate.zone.age_minutes if candidate.zone else 0.0,
                        pattern=getattr(candidate, "_reversal_pattern", "none"),
                        pattern_strength=getattr(candidate, "_reversal_strength", 0.0),
                        entry_mode=getattr(
                            candidate,
                            "_entry_mode",
                            "rebound_floor",
                        ),
                        confidence=None,
                        signal_type=None,
                        raw_reason="scan",
                        dist_pct=dist,
                    )
                    strat_a_for_hub.append(cd)
                except Exception as exc:
                    log.debug("HUB: Error converting STRAT-A candidate: %s", exc)

            strat_b_for_hub = []
            sorted_b = sorted(self.last_scan_strat_b, key=lambda c: c.score, reverse=True)
            for candidate in sorted_b[:5]:
                try:
                    dist = self._candidate_trigger_distance_pct(candidate)
                    cd = CandidateData(
                        strategy="STRAT-B",
                        asset=candidate.asset,
                        direction=candidate.direction,
                        score=candidate.score,
                        payout=candidate.payout,
                        zone_ceiling=candidate.zone.ceiling if candidate.zone else 0.0,
                        zone_floor=candidate.zone.floor if candidate.zone else 0.0,
                        zone_age_min=candidate.zone.age_minutes if candidate.zone else 0.0,
                        pattern=getattr(candidate, "_reversal_pattern", "Spring Sweep"),
                        pattern_strength=getattr(candidate, "_reversal_strength", 0.0),
                        entry_mode=getattr(candidate, "_entry_mode", "rebound_floor"),
                        confidence=getattr(candidate, "_reversal_strength", None),
                        signal_type=getattr(candidate, "_reversal_pattern", None),
                        raw_reason="scan",
                        dist_pct=dist,
                    )
                    strat_b_for_hub.append(cd)
                except Exception as exc:
                    log.debug("HUB: Error converting STRAT-B candidate: %s", exc)

            self.hub.record_scan_cycle(
                total_assets=total_assets,
                strat_a_candidates=strat_a_for_hub,
                strat_b_candidates=strat_b_for_hub,
                balance=self.current_balance,
                cycle_id=self.cycle_id,
                cycle_ops=self.cycle_ops,
                cycle_wins=self.cycle_wins,
                cycle_losses=self.cycle_losses,
            )
        except Exception as exc:
            log.debug("Hub registration error: %s", exc)

    async def _get_asset_payout(self, asset: str, default: int = MIN_PAYOUT) -> int:
        try:
            assets_now = await get_open_assets(self.client, 0)
            for as_sym, as_payout in assets_now:
                if as_sym == asset:
                    return int(as_payout)
        except Exception:
            pass
        return int(default)

    async def _get_current_price(self, asset: str) -> Optional[float]:
        candles = await fetch_candles_with_retry(
            self.client,
            asset,
            60,
            3,
            timeout_sec=CANDLE_FETCH_1M_TIMEOUT_SEC,
            retries=1,
        )
        if candles:
            return float(candles[-1].close)
        return self.last_known_price.get(asset)

    def _cap_martin_amount(self, amount: float, balance: Optional[float]) -> float:
        if balance is None or balance <= 0:
            return max(MIN_ORDER_AMOUNT, self._round_up_to_cents(amount))
        capped = self._round_up_to_cents(balance * MARTIN_MAX_PCT_BALANCE)
        if amount > capped:
            log.warning("⚠ Martin cappado a $%.2f (20%% de $%.2f)", capped, balance)
            return max(MIN_ORDER_AMOUNT, capped)
        return max(MIN_ORDER_AMOUNT, self._round_up_to_cents(amount))

    @staticmethod
    def _required_rebound_strength(direction: str) -> float:
        return REBOUND_MIN_STRENGTH_PUT if direction == "put" else REBOUND_MIN_STRENGTH_CALL

    @staticmethod
    def _is_put_pattern_blacklisted(direction: str, pattern_name: str) -> bool:
        return direction == "put" and pattern_name in PATTERN_PUT_BLACKLIST

    def _update_dynamic_threshold(self) -> int:
        if len(self.accepted_scans_window) < ADAPTIVE_THRESHOLD_WINDOW_SCANS:
            self.current_score_threshold = ADAPTIVE_THRESHOLD_BASE
            return self.current_score_threshold

        accepted_last_window = sum(self.accepted_scans_window)
        if accepted_last_window == 0:
            self.current_score_threshold = ADAPTIVE_THRESHOLD_LOW
        elif accepted_last_window > 2:
            self.current_score_threshold = ADAPTIVE_THRESHOLD_HIGH
        else:
            self.current_score_threshold = ADAPTIVE_THRESHOLD_BASE
        return self.current_score_threshold

    def _record_scan_acceptances(self, accepted_count: int) -> None:
        self.accepted_scans_window.append(max(0, int(accepted_count)))

    def _cleanup_asset_blacklist(self) -> None:
        now_ts = time.time()
        expired_assets = [
            asset for asset, until_ts in self.asset_blacklist_until.items()
            if now_ts >= until_ts
        ]
        for asset in expired_assets:
            self.asset_blacklist_until.pop(asset, None)
            self.asset_loss_streaks[asset] = 0
            log.warning("✅ [BLACKLIST] %s liberado — tiempo expirado", asset)

    def _is_asset_blacklisted(self, asset: str) -> bool:
        until_ts = self.asset_blacklist_until.get(asset)
        if until_ts is None:
            return False
        if time.time() >= until_ts:
            self.asset_blacklist_until.pop(asset, None)
            self.asset_loss_streaks[asset] = 0
            log.warning("✅ [BLACKLIST] %s liberado — tiempo expirado", asset)
            return False
        return True

    def _register_asset_outcome(self, asset: str, outcome: str) -> None:
        if outcome == "WIN":
            self.asset_loss_streaks[asset] = 0
            return
        if outcome != "LOSS":
            return

        streak = int(self.asset_loss_streaks.get(asset, 0)) + 1
        self.asset_loss_streaks[asset] = streak
        if streak < ASSET_LOSS_STREAK_LIMIT:
            return

        until_ts = time.time() + (ASSET_BLACKLIST_DURATION_MIN * 60)
        self.asset_blacklist_until[asset] = until_ts
        log.warning(
            "⚠ [BLACKLIST] %s añadido — %d LOSS consecutivos (%d min)",
            asset,
            streak,
            ASSET_BLACKLIST_DURATION_MIN,
        )

    def _can_enter_asset_now(self, asset: str, stage: str) -> Tuple[bool, str]:
        """
        Limita la sobre-repetición del mismo activo.
        Nota: martingala queda exenta para no romper recuperación de ciclo.
        """
        if stage == "martin":
            return True, "MARTIN_EXEMPT"
        if SAME_ASSET_REENTRY_COOLDOWN_SEC > 0:
            last_ts = float(self.last_entry_ts_by_asset.get(asset, 0.0) or 0.0)
            if last_ts > 0:
                elapsed = time.time() - last_ts
                if elapsed < SAME_ASSET_REENTRY_COOLDOWN_SEC:
                    remaining = max(0.0, SAME_ASSET_REENTRY_COOLDOWN_SEC - elapsed)
                    return False, (
                        f"cooldown mismo activo activo: faltan {remaining:.1f}s "
                        f"(min={SAME_ASSET_REENTRY_COOLDOWN_SEC}s)"
                    )
        if MAX_CONSECUTIVE_ENTRIES_PER_ASSET <= 0:
            return True, "LIMIT_DISABLED"
        if self.last_entry_asset != asset:
            return True, "NEW_ASSET"
        if self.last_entry_asset_streak < MAX_CONSECUTIVE_ENTRIES_PER_ASSET:
            return True, "WITHIN_LIMIT"
        reason = (
            f"máximo {MAX_CONSECUTIVE_ENTRIES_PER_ASSET} entradas consecutivas "
            f"en {asset}"
        )
        return False, reason

    @staticmethod
    def _structure_key(asset: str, zone: ConsolidationZone) -> str:
        return f"{asset}|{zone.floor:.5f}|{zone.ceiling:.5f}"

    def _cleanup_structure_locks(self) -> None:
        if STRUCTURE_ENTRY_LOCK_TTL_MIN <= 0:
            self.structure_entry_locks.clear()
            return
        now = time.time()
        ttl_sec = float(STRUCTURE_ENTRY_LOCK_TTL_MIN) * 60.0
        expired = [k for k, ts in self.structure_entry_locks.items() if (now - ts) >= ttl_sec]
        for k in expired:
            self.structure_entry_locks.pop(k, None)

    def _can_enter_structure_now(self, asset: str, zone: ConsolidationZone) -> Tuple[bool, str]:
        self._cleanup_structure_locks()
        if STRUCTURE_ENTRY_LOCK_TTL_MIN <= 0:
            return True, "STRUCTURE_LOCK_DISABLED"
        key = self._structure_key(asset, zone)
        last_ts = float(self.structure_entry_locks.get(key, 0.0) or 0.0)
        if last_ts <= 0:
            return True, "NEW_STRUCTURE"
        ttl_sec = float(STRUCTURE_ENTRY_LOCK_TTL_MIN) * 60.0
        elapsed = time.time() - last_ts
        if elapsed >= ttl_sec:
            return True, "STRUCTURE_LOCK_EXPIRED"
        remain = max(0.0, ttl_sec - elapsed)
        return False, (
            f"estructura ya operada (techo={zone.ceiling:.5f}, piso={zone.floor:.5f}); "
            f"faltan {remain/60.0:.1f}min"
        )

    def _register_successful_entry_asset(self, asset: str, zone: ConsolidationZone) -> None:
        self._cleanup_structure_locks()
        self.structure_entry_locks[self._structure_key(asset, zone)] = time.time()
        self.last_entry_ts_by_asset[asset] = time.time()
        if self.last_entry_asset == asset:
            self.last_entry_asset_streak += 1
        else:
            self.last_entry_asset = asset
            self.last_entry_asset_streak = 1

    @staticmethod
    def _detect_order_blocks(candles: List[Candle]) -> dict[str, list[OrderBlock]]:
        """
        Detecta Order Blocks institucionales con definición corregida:
        
        OB bajista: última vela ALCISTA antes de vela de impulso bajista 
          (impulso = body >= avg_body * 1.5)
        OB alcista: última vela BAJISTA antes de vela de impulso alcista
        
        El impulso puede ocurrir dentro de las siguientes 3 velas después del OB.
        
        Invalidación: OB se invalida si precio cierra completamente del lado opuesto.
        Mitigación: precio entró en zona pero no cerró del lado opuesto → is_mitigated=True
        """
        if len(candles) < 6:
            return {"bull": [], "bear": []}

        result: dict[str, list[OrderBlock]] = {"bull": [], "bear": []}
        total = len(candles)
        
        # 1. Calcular avg_body de las últimas 30 velas (ventana móvil)
        lookback_window = min(30, total)
        bodies = [float(c.body) for c in candles[-lookback_window:]]
        avg_body = mean(bodies) if bodies else 0.0
        
        if avg_body < 1e-12:
            return result
        
        impulse_threshold = avg_body * 1.5
        
        # 2. Buscar impulsos y sus OBs correspondientes
        start_idx = max(1, total - ORDER_BLOCK_LOOKBACK)
        
        for j in range(start_idx + 1, total):  # j es el índice del impulso potencial
            c_impulse = candles[j]
            
            # Verificar si es impulso bajista (body >= threshold, close < open)
            if c_impulse.close < c_impulse.open and c_impulse.body >= impulse_threshold:
                # Buscar la ÚLTIMA (más reciente) vela ALCISTA ANTES de este impulso
                # Buscamos hacia atrás desde j-1 hasta i (hasta 3 velas atrás)
                for k in range(j - 1, max(j - 4, start_idx - 1), -1):
                    if candles[k].close > candles[k].open:  # vela alcista
                        # Esta es la más reciente vela alcista antes del impulso
                        ob = OrderBlock(
                            side="bear",
                            low=float(candles[k].low),
                            high=float(candles[k].high),
                            created_ts=int(candles[k].ts),
                            created_index=k,
                            bars_ago=(total - 1 - k),
                            is_mitigated=False,
                        )
                        result["bear"].append(ob)
                        break  # Solo la más reciente
            
            # Verificar si es impulso alcista (body >= threshold, close > open)
            if c_impulse.close > c_impulse.open and c_impulse.body >= impulse_threshold:
                # Buscar la ÚLTIMA (más reciente) vela BAJISTA ANTES de este impulso
                for k in range(j - 1, max(j - 4, start_idx - 1), -1):
                    if candles[k].close < candles[k].open:  # vela bajista
                        # Esta es la más reciente vela bajista antes del impulso
                        ob = OrderBlock(
                            side="bull",
                            low=float(candles[k].low),
                            high=float(candles[k].high),
                            created_ts=int(candles[k].ts),
                            created_index=k,
                            bars_ago=(total - 1 - k),
                            is_mitigated=False,
                        )
                        result["bull"].append(ob)
                        break  # Solo la más reciente
        
        # 3. Remover duplicados por created_index (puede haber múltiples impulsos para el mismo OB)
        def _deduplicate(blocks: list[OrderBlock]) -> list[OrderBlock]:
            seen = set()
            dedup = []
            for b in blocks:
                key = (b.created_index, b.side)
                if key not in seen:
                    seen.add(key)
                    dedup.append(b)
            return dedup
        
        result["bull"] = _deduplicate(result["bull"])
        result["bear"] = _deduplicate(result["bear"])
        
        # 4. Invalidación: OB es inválido si precio cerró completamente del lado opuesto
        def _is_invalidated(block: OrderBlock) -> bool:
            """
            Invalidación: precio cierra completamente del lado opuesto.
            - OB bajista invalidado: alguna vela posterior cerró POR ENCIMA del high del OB
            - OB alcista invalidado: alguna vela posterior cerró POR DEBAJO del low del OB
            """
            future_closes = [float(c.close) for c in candles[block.created_index + 1:]]
            if not future_closes:
                return False
            
            if block.side == "bear":
                # OB bajista: invalidado si alguna vela cierra ENCIMA del high
                return any(cl > block.high for cl in future_closes)
            else:
                # OB alcista: invalidado si alguna vela cierra DEBAJO del low
                return any(cl < block.low for cl in future_closes)
        
        # 5. Mitigación: precio entró en zona pero no cerró del lado opuesto.
        def _check_mitigation(block: OrderBlock) -> bool:
            """
            Mitigado parcialmente = alguna vela posterior al OB tocó la zona
            (por rango high/low), sin que el OB haya sido invalidado.
            """
            for c in candles[block.created_index + 1:]:
                if float(c.high) >= block.low and float(c.low) <= block.high:
                    return True
            return False
        
        # Filtrar inválidos
        active_bull = []
        active_bear = []
        
        for b in result["bull"]:
            if not _is_invalidated(b):
                b.is_mitigated = _check_mitigation(b)
                active_bull.append(b)
        
        for b in result["bear"]:
            if not _is_invalidated(b):
                b.is_mitigated = _check_mitigation(b)
                active_bear.append(b)
        
        # 6. Ordenar por reciente primero
        active_bull.sort(key=lambda b: b.created_ts, reverse=True)
        active_bear.sort(key=lambda b: b.created_ts, reverse=True)
        
        return {
            "bull": active_bull[:ORDER_BLOCK_MAX_PER_SIDE],
            "bear": active_bear[:ORDER_BLOCK_MAX_PER_SIDE],
        }

    @staticmethod
    def _block_distance(price: float, block: OrderBlock) -> float:
        if block.low <= price <= block.high:
            return 0.0
        return min(abs(price - block.low), abs(price - block.high))

    @staticmethod
    def _is_touching_block(price: float, block: OrderBlock) -> bool:
        tolerance = max(price * ORDER_BLOCK_TOUCH_TOLERANCE_PCT, 1e-6)
        if block.low <= price <= block.high:
            return True
        return abs(price - block.low) <= tolerance or abs(price - block.high) <= tolerance

    def _score_order_blocks(
        self,
        *,
        direction: str,
        price: float,
        blocks: dict[str, list[OrderBlock]],
        avg_body: float = 1e-9,
    ) -> tuple[float, str]:
        """
        Penalizaciones corregidas:
        - CALL con OB bajista activo: -15 (sin mitigar) / -12 (mitigado)
        - PUT con OB alcista activo: -15/-12
        - CALL en OB alcista (soporte): +8
        - PUT en OB bajista (resistencia): +8
        """
        bull_blocks = blocks.get("bull", [])
        bear_blocks = blocks.get("bear", [])
        all_blocks = bull_blocks + bear_blocks
        
        if not all_blocks:
            return 0.0, "sin bloques activos"

        points = 0.0
        notes: list[str] = []
        
        # Verificar si precio está EN ZONA del OB
        price_in_bull = any(b.low <= price <= b.high for b in bull_blocks)
        price_in_bear = any(b.low <= price <= b.high for b in bear_blocks)
        
        proximity_threshold = max(avg_body, 1e-9)

        # Penalizaciones por CALL con OB bajista activo
        if direction == "call":
            if bear_blocks:
                nearest_bear = min(bear_blocks, key=lambda b: self._block_distance(price, b))
                
                if price_in_bear:
                    # Precio EN ZONA del OB bajista
                    if nearest_bear.is_mitigated:
                        points -= 12.0
                        notes.append("-12 CALL en BEAR OB (mitigado)")
                    else:
                        points -= 15.0
                        notes.append("-15 CALL en BEAR OB (sin mitigar)")
                else:
                    # Precio aproximándose
                    dist = self._block_distance(price, nearest_bear)
                    if 0 < dist <= proximity_threshold:
                        points -= 8.0
                        notes.append(f"-8 CALL aproximándose a BEAR OB (dist={dist:.6f})")
            
            # Bonus si CALL está en OB alcista (soporte)
            if bull_blocks:
                nearest_bull = min(bull_blocks, key=lambda b: self._block_distance(price, b))
                
                if price_in_bull:
                    points += 8.0
                    notes.append("+8 CALL en BULL OB (soporte retrace)")
                else:
                    points += 3.0
                    notes.append("+3 CALL alineado con BULL OB (fuera de zona)")
        
        # Penalizaciones por PUT con OB alcista activo
        if direction == "put":
            if bull_blocks:
                nearest_bull = min(bull_blocks, key=lambda b: self._block_distance(price, b))
                
                if price_in_bull:
                    # Precio EN ZONA del OB alcista
                    if nearest_bull.is_mitigated:
                        points -= 12.0
                        notes.append("-12 PUT en BULL OB (mitigado)")
                    else:
                        points -= 15.0
                        notes.append("-15 PUT en BULL OB (sin mitigar)")
                else:
                    # Precio aproximándose
                    dist = self._block_distance(price, nearest_bull)
                    if 0 < dist <= proximity_threshold:
                        points -= 8.0
                        notes.append(f"-8 PUT aproximándose a BULL OB (dist={dist:.6f})")
            
            # Bonus si PUT está en OB bajista (resistencia)
            if bear_blocks:
                nearest_bear = min(bear_blocks, key=lambda b: self._block_distance(price, b))
                
                if price_in_bear:
                    points += 8.0
                    notes.append("+8 PUT en BEAR OB (resistencia retrace)")
                else:
                    points += 3.0
                    notes.append("+3 PUT alineado con BEAR OB (fuera de zona)")
        
        # Info detallada
        if all_blocks:
            nearest = min(all_blocks, key=lambda b: self._block_distance(price, b))
            mitigation_str = "🔹 mitigado" if nearest.is_mitigated else "⚠ sin mitigar"
            info = f"{nearest.side.upper()} @ {nearest.low:.5f}–{nearest.high:.5f} | {mitigation_str} | {nearest.bars_ago} velas"
        else:
            info = "sin bloques"
        
        if notes:
            info = f"{', '.join(notes)} | {info}"
        
        return points, info

    def _update_clock_offset(self, candles: List[Candle], tf_sec: int) -> None:
        """
        Ajusta el offset entre reloj local y timestamps del broker.
        Usa la ultima vela disponible y suaviza para evitar saltos bruscos.
        """
        if not candles or tf_sec <= 0:
            return

        last_ts = int(candles[-1].ts)
        # Fase real de apertura de vela en el broker (puede ser :00 o :30).
        self._candle_phase_sec = int(last_ts % int(tf_sec))
        now_ts = time.time()
        expected_open = ((int(now_ts) - self._candle_phase_sec) // int(tf_sec)) * int(tf_sec) + self._candle_phase_sec
        raw_offset = float(last_ts - expected_open)

        # Evitar offsets invalidos por respuestas viejas o ruido.
        if raw_offset < -5.0 or raw_offset > 5.0:
            return

        alpha = 0.30
        self._clock_offset = (alpha * raw_offset) + ((1.0 - alpha) * self._clock_offset)

    def _compute_ma_state(self, asset: str, candles_5m: List[Candle]) -> Optional[MAState]:
        if len(candles_5m) < MA_SLOW_PERIOD:
            log.debug("[MA] %s sin suficientes velas 5m (%d < %d)", asset, len(candles_5m), MA_SLOW_PERIOD)
            return None

        closes = [float(c.close) for c in candles_5m[-MA_LOOKBACK_CANDLES:]]
        ma35 = mean(closes[-MA_FAST_PERIOD:])
        ma50 = mean(closes[-MA_SLOW_PERIOD:])
        price = closes[-1]
        delta_abs = abs(ma35 - ma50)
        flat_threshold = max(1e-9, price * MA_FLAT_DELTA_PCT)

        if delta_abs < flat_threshold:
            trend = "FLAT"
        elif ma35 > ma50:
            trend = "UP"
        else:
            trend = "DOWN"

        prev_state = self.ma_state_by_asset.get(asset)
        cross = "NONE"
        if prev_state is not None:
            if prev_state.ma35 <= prev_state.ma50 and ma35 > ma50:
                cross = "GOLDEN"
            elif prev_state.ma35 >= prev_state.ma50 and ma35 < ma50:
                cross = "DEATH"

        # Calcular avg_body de última ventana (30 velas) para umbral de impulso OB
        lookback_window = min(30, len(candles_5m))
        bodies = [float(c.body) for c in candles_5m[-lookback_window:]]
        avg_body = mean(bodies) if bodies else 0.0

        state = MAState(ma35=float(ma35), ma50=float(ma50), trend=trend, cross=cross, avg_body=float(avg_body), price=float(price))
        self.ma_state_by_asset[asset] = state
        return state

    @staticmethod
    def _score_ma(direction: str, ma_state: Optional[MAState]) -> tuple[float, str]:
        if ma_state is None:
            return 0.0, "sin datos"

        points = 0.0
        price = ma_state.price
        if direction == "call":
            if ma_state.trend == "UP":
                points += 6.0
            elif ma_state.trend == "DOWN":
                points -= 10.0
            if ma_state.cross == "GOLDEN":
                points += 4.0
        else:  # put
            if ma_state.trend == "DOWN":
                points += 6.0
            elif ma_state.trend == "UP":
                points -= 10.0
            if ma_state.cross == "DEATH":
                points += 4.0

        # ── Penalización por posición del precio vs MAs ──────────────────────
        # CALL con precio ENCIMA de ambas MAs en tendencia bajista:
        # el precio está sobreextendido al alza en un entorno bajista → falsa ruptura.
        if direction == "call" and ma_state.trend == "DOWN" and price > 0:
            if price > ma_state.ma50:
                points -= 25.0  # precio claramente en zona de venta para PUT
            elif price > ma_state.ma35:
                points -= 15.0  # precio sobre MA rápida en bajista

        # PUT con precio DEBAJO de ambas MAs en tendencia alcista:
        # el precio está sobreextendido a la baja en un entorno alcista → falsa ruptura.
        if direction == "put" and ma_state.trend == "UP" and price > 0:
            if price < ma_state.ma50:
                points -= 25.0  # precio claramente en zona de compra para CALL
            elif price < ma_state.ma35:
                points -= 15.0  # precio bajo MA rápida en alcista

        position_tag = ""
        if price > 0:
            if price > ma_state.ma50:
                position_tag = " px>MA50"
            elif price > ma_state.ma35:
                position_tag = " px>MA35"
            elif price < ma_state.ma50:
                position_tag = " px<MA50"
            elif price < ma_state.ma35:
                position_tag = " px<MA35"

        info = (
            f"trend={ma_state.trend} cross={ma_state.cross} "
            f"ma35={ma_state.ma35:.5f} ma50={ma_state.ma50:.5f}{position_tag}"
        )
        return points, info

    @staticmethod
    def _threshold_label(threshold: int) -> str:
        if threshold == ADAPTIVE_THRESHOLD_LOW:
            return "bajo"
        if threshold == ADAPTIVE_THRESHOLD_HIGH:
            return "alto"
        return "base"

    @staticmethod
    def _threshold_change_reason(accepted_last_window: int) -> str:
        if accepted_last_window == 0:
            return "sin señales en últimos 10 scans"
        if accepted_last_window > 2:
            return "2+ señales en últimos 10 scans"
        return "señales mixtas en últimos 10 scans"

    def _build_blacklist_summary_line(self) -> str:
        if not self.asset_blacklist_until:
            return "ninguna"
        now_ts = time.time()
        chunks: list[str] = []
        for asset, until_ts in sorted(self.asset_blacklist_until.items()):
            if until_ts <= now_ts:
                continue
            until_txt = datetime.fromtimestamp(until_ts, tz=BROKER_TZ).strftime("%H:%M")
            chunks.append(f"{asset} (hasta {until_txt})")
        return ", ".join(chunks) if chunks else "ninguna"

    @staticmethod
    def _build_ob_summary_line(cycle_ob_summary: dict[str, str]) -> str:
        if not cycle_ob_summary:
            return "ninguno"
        return " | ".join(f"{asset} → {desc}" for asset, desc in sorted(cycle_ob_summary.items()))

    @staticmethod
    def _build_ma_summary_line(cycle_ma_summary: dict[str, str]) -> str:
        if not cycle_ma_summary:
            return "ninguno"
        return " | ".join(f"{asset} {desc}" for asset, desc in sorted(cycle_ma_summary.items()))

    def _log_dry_run_verbose_cycle_summary(
        self,
        *,
        cycle_num: int,
        threshold: int,
        accepted_last_window: int,
        cycle_ob_summary: dict[str, str],
        cycle_ma_summary: dict[str, str],
    ) -> None:
        if not (DRY_RUN_VERBOSE and self.dry_run):
            return
        threshold_tag = self._threshold_label(threshold)
        log.info("══════════════════════════════════════")
        log.info(
            "[CICLO #%d] UMBRAL ACTIVO: %d (%s) | ventana: %d/%d scans con señal",
            cycle_num,
            threshold,
            threshold_tag,
            accepted_last_window,
            ADAPTIVE_THRESHOLD_WINDOW_SCANS,
        )
        log.info("[CICLO #%d] BLACKLIST: %s", cycle_num, self._build_blacklist_summary_line())
        log.info("[CICLO #%d] OB detectados: %s", cycle_num, self._build_ob_summary_line(cycle_ob_summary))
        log.info("[CICLO #%d] MA state: %s", cycle_num, self._build_ma_summary_line(cycle_ma_summary))
        log.info("══════════════════════════════════════")

    def _current_martin_attempt_limit(self) -> int:
        balance = self.current_balance
        if balance is None:
            balance = self.martingale.current_balance
        if balance is not None and balance < MARTIN_LOW_BALANCE_THRESHOLD:
            return MARTIN_MAX_ATTEMPTS_LOW_BALANCE
        return MARTIN_MAX_ATTEMPTS_SESSION

    def _martin_session_available(self) -> bool:
        used = int(self.stats.get("martin_attempts_session", 0))
        max_attempts = self._current_martin_attempt_limit()
        if used >= max_attempts:
            log.info(
                "⛔ Martingala desactivada: límite de sesión alcanzado (%d/%d)",
                used,
                max_attempts,
            )
            return False
        return True


    def _track_task(self, task: asyncio.Task[Any]) -> None:
        self._trade_tasks.add(task)
        task.add_done_callback(self._on_background_task_done)

    def _on_background_task_done(self, task: asyncio.Task[Any]) -> None:
        # Always drain task exception to avoid "Task exception was never retrieved"
        # when the process is interrupted with Ctrl+C.
        self._trade_tasks.discard(task)
        self._followup_capture_tasks.discard(task)
        try:
            exc = task.exception()
        except asyncio.CancelledError:
            return
        except Exception:
            return
        if exc is None:
            return
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            return
        log.debug("Tarea background finalizada con error: %s", exc)

    async def shutdown_background_tasks(self) -> None:
        pending = [
            t for t in (list(self._trade_tasks) + list(self._followup_capture_tasks))
            if not t.done()
        ]
        if not pending:
            return
        for t in pending:
            t.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

    def _consume_fresh_watched_candidate(self, asset: str) -> Optional[CandidateEntry]:
        watched = self.watched_candidates.get(asset)
        if not watched:
            return None
        candidate, detected_at = watched
        if (time.time() - detected_at) > 300:
            self.watched_candidates.pop(asset, None)
            return None
        self.watched_candidates.pop(asset, None)
        return candidate

    async def _try_enter_martin_now(
        self,
        *,
        asset: str,
        amount: float,
        original_loss: float,
        strategy_origin: str,
        score_original: float,
        payout_hint: int = MIN_PAYOUT,
    ) -> bool:
        if not self._martin_session_available():
            return False

        candidate = self._consume_fresh_watched_candidate(asset)
        if candidate is not None:
            log.info(
                "🔄 MARTIN DIFERIDO %s $%.2f — recuperando $%.2f",
                asset,
                amount,
                original_loss,
            )
            entered = await self._enter(
                asset,
                candidate.direction,
                amount,
                candidate.zone,
                f"MARTIN diferido | recuperando ${original_loss:.2f}",
                "martin",
                signal_ts=getattr(candidate, "_signal_ts_1m", candidate.candles[-1].ts if candidate.candles else None),
                strategy_origin=strategy_origin,
                duration_sec=DURATION_SEC,
                payout=candidate.payout,
                score_original=score_original,
            )
            if entered:
                self.stats["martins"] += 1
            return entered

        zone = self.zones.get(asset)
        if zone is None:
            return False

        price = await self._get_current_price(asset)
        if price is None:
            return False

        direction: Optional[str] = None
        reason = ""
        if price_at_floor(price, zone.floor):
            direction = "call"
            reason = f"MARTIN inmediato desde piso {zone.floor:.5f}"
        elif price_at_ceiling(price, zone.ceiling):
            direction = "put"
            reason = f"MARTIN inmediato desde techo {zone.ceiling:.5f}"

        if direction is None:
            return False

        payout_now = await self._get_asset_payout(asset, payout_hint)
        log.info(
            "🔄 MARTIN DIFERIDO %s $%.2f — recuperando $%.2f",
            asset,
            amount,
            original_loss,
        )
        entered = await self._enter(
            asset,
            direction,
            amount,
            zone,
            reason,
            "martin",
            strategy_origin=strategy_origin,
            duration_sec=DURATION_SEC,
            payout=payout_now,
            score_original=score_original,
        )
        if entered:
            self.stats["martins"] += 1
        return entered

    async def _monitor_trade_live(self, asset: str, trade: TradeState) -> None:
        alerted = False
        recovery_logged = False
        while not trade.resolved:
            elapsed = time.time() - trade.opened_at
            secs_left = trade.duration_sec - elapsed
            if secs_left <= 0 or trade.martin_fired:
                return

            price = await self._get_current_price(asset)
            if price is None:
                try:
                    self.hub.update_active_trade_timer(secs_left, entry_price=trade.entry_price)
                except Exception:
                    pass
                await asyncio.sleep(MARTIN_MONITOR_INTERVAL_SEC)
                continue

            try:
                self.hub.update_active_trade_timer(
                    secs_left,
                    current_price=price,
                    entry_price=trade.entry_price,
                )
            except Exception:
                pass

            losing_probably = (
                price < trade.entry_price * (1.0 - MARTIN_ALERT_PCT)
                if trade.direction == "call"
                else price > trade.entry_price * (1.0 + MARTIN_ALERT_PCT)
            )

            if losing_probably:
                alerted = True

            if (
                losing_probably
                and MARTIN_LIVE_WINDOW_MIN_SEC <= secs_left <= MARTIN_LIVE_WINDOW_MAX_SEC
                and not trade.martin_fired
                and trade.stage != "martin"
                and trade.score_original >= 70.0
                and self._martin_session_available()
            ):
                payout_now = await self._get_asset_payout(asset, trade.payout)
                amount, _ = self._compute_compensation_amount(payout_now, trade.amount)
                balance = self.current_balance
                if balance is None:
                    try:
                        balance = float(await self.client.get_balance())
                    except Exception:
                        balance = None
                amount = self._cap_martin_amount(amount, balance)
                zone = ConsolidationZone(
                    asset=asset,
                    ceiling=trade.ceiling,
                    floor=trade.floor,
                    bars_inside=0,
                    detected_at=time.time(),
                    range_pct=0.0,
                )
                trade.martin_fired = True
                log.info(
                    "⚡ MARTIN ANTICIPADO %s %s $%.2f — precio en contra con %.0fs restantes",
                    asset,
                    trade.direction.upper(),
                    amount,
                    secs_left,
                )
                entered = await self._enter(
                    asset,
                    trade.direction,
                    amount,
                    zone,
                    f"MARTIN anticipado | precio en contra con {secs_left:.0f}s restantes",
                    "martin",
                    strategy_origin=trade.strategy_origin,
                    duration_sec=DURATION_SEC,
                    payout=payout_now,
                    score_original=trade.score_original,
                )
                if entered:
                    self.stats["martins"] += 1
                return

            if alerted and not losing_probably and secs_left > MARTIN_LIVE_WINDOW_MIN_SEC and not recovery_logged:
                log.info("✅ %s: precio recuperado, martin cancelado", asset)
                recovery_logged = True
                alerted = False

            await asyncio.sleep(MARTIN_MONITOR_INTERVAL_SEC)

    async def _resolve_trade_after_expiry(self, asset: str, trade: TradeState) -> None:
        wait_sec = max(0.0, trade.duration_sec + MARTIN_RESOLVE_GRACE_SEC - (time.time() - trade.opened_at))
        if wait_sec > 0:
            if wait_sec > 1.0:
                await sleep_with_inline_countdown(wait_sec, "Entrada sincronizada 1m")
            else:
                await asyncio.sleep(wait_sec)
        await self._resolve_trade(trade, asset)

    async def _process_pending_martin(
        self,
        candidates: list[CandidateEntry],
    ) -> tuple[list[CandidateEntry], bool]:
        if not self.pending_martin:
            return candidates, False

        remaining = list(candidates)
        entered_any = False
        for asset, pending in list(self.pending_martin.items()):
            if not self._martin_session_available():
                break
            pending.scans_waited += 1
            matching = [c for c in remaining if c.asset == asset]
            if matching and len(self.trades) < MAX_CONCURRENT_TRADES:
                chosen = max(matching, key=lambda c: c.score)
                entered = await self._enter(
                    chosen.asset,
                    chosen.direction,
                    pending.amount,
                    chosen.zone,
                    f"MARTIN diferido | recuperando ${pending.original_loss:.2f}",
                    "martin",
                    signal_ts=getattr(chosen, "_signal_ts_1m", chosen.candles[-1].ts if chosen.candles else None),
                    strategy_origin="STRAT-A",
                    duration_sec=DURATION_SEC,
                    payout=chosen.payout,
                    score_original=pending.score_original,
                )
                if entered:
                    log.info(
                        "🔄 MARTIN DIFERIDO %s $%.2f — recuperando $%.2f",
                        asset,
                        pending.amount,
                        pending.original_loss,
                    )
                    self.stats["martins"] += 1
                    self.pending_martin.pop(asset, None)
                    remaining = [c for c in remaining if c.asset != asset]
                    entered_any = True
                    continue

            if pending.scans_waited >= pending.max_wait_scans:
                log.info("⏰ %s: martin diferido expirado", asset)
                self.pending_martin.pop(asset, None)

        return remaining, entered_any

    def _validate_rejection_candle(
        self,
        candles_1m: List[Candle],
        direction: str,
        min_body_ratio: float = REJECTION_CANDLE_MIN_BODY,
    ) -> Tuple[bool, str]:
        """
        Valida que la vela 1m más reciente confirme el rebote en piso/techo.
        
        Para CALL (piso): close > open (alcista) Y body_ratio >= min_body_ratio
        Para PUT (techo): close < open (bajista) Y body_ratio >= min_body_ratio
        
        Retorna (válido, razón_fallo | "").
        """
        if len(candles_1m) < 3:
            return False, "insuficientes velas 1m"
        
        last = candles_1m[-2]
        rango = last.range
        if rango <= 0:
            return False, "vela sin rango"
        
        body_ratio = abs(last.close - last.open) / rango
        
        if direction == "call":
            # CALL en piso: esperar vela alcista (close > open)
            if last.close <= last.open:
                return False, f"vela bajista (close={last.close:.5f} < open={last.open:.5f})"
            if body_ratio < min_body_ratio:
                return False, f"cuerpo débil {body_ratio:.0%} < {min_body_ratio:.0%}"
            lower_wick = min(last.open, last.close) - last.low
            lower_wick_ratio = lower_wick / rango
            if lower_wick_ratio < REJECTION_CALL_MIN_LOWER_WICK:
                return False, (
                    f"mecha inferior débil {lower_wick_ratio:.0%} "
                    f"< {REJECTION_CALL_MIN_LOWER_WICK:.0%}"
                )
            return True, ""
        
        elif direction == "put":
            # PUT en techo: esperar vela bajista (close < open)
            if last.close >= last.open:
                return False, f"vela alcista (close={last.close:.5f} >= open={last.open:.5f})"
            if body_ratio < min_body_ratio:
                return False, f"cuerpo débil {body_ratio:.0%} < {min_body_ratio:.0%}"
            upper_wick = last.high - max(last.open, last.close)
            upper_wick_ratio = upper_wick / rango
            if upper_wick_ratio < REJECTION_PUT_MIN_UPPER_WICK:
                return False, (
                    f"mecha superior débil {upper_wick_ratio:.0%} "
                    f"< {REJECTION_PUT_MIN_UPPER_WICK:.0%}"
                )
            return True, ""
        
        return False, "dirección inválida"

    def _reset_cycle(self, reason: str) -> None:
        log.info(
            "🔁 Reinicio de ciclo #%d | motivo=%s | ops=%d wins=%d loss=%d profit=%.2f",
            self.cycle_id,
            reason,
            self.cycle_ops,
            self.cycle_wins,
            self.cycle_losses,
            self.cycle_profit,
        )
        self.cycle_id += 1
        self.cycle_ops = 0
        self.cycle_wins = 0
        self.cycle_losses = 0
        self.cycle_profit = 0.0
        if self.current_balance is not None:
            self.cycle_start_balance = float(self.current_balance)

    def _update_cycle_after_result(self, outcome: str, profit: float) -> None:
        if outcome not in {"WIN", "LOSS"}:
            return

        self.cycle_ops += 1
        self.cycle_profit += float(profit)
        if outcome == "WIN":
            self.cycle_wins += 1
        else:
            self.cycle_losses += 1

        # 1) Regla: reiniciar al alcanzar +10% del balance base del ciclo.
        if (
            self.cycle_start_balance
            and self.current_balance is not None
            and self.cycle_start_balance > 0
        ):
            growth = (self.current_balance - self.cycle_start_balance) / self.cycle_start_balance
            if growth >= CYCLE_TARGET_PROFIT_PCT:
                self._reset_cycle(f"objetivo +{int(CYCLE_TARGET_PROFIT_PCT*100)}% cumplido")
                return

        # 2) Regla: ciclo objetivo cumplido con 2 wins.
        if self.cycle_wins >= CYCLE_TARGET_WINS:
            self._reset_cycle(f"objetivo {CYCLE_TARGET_WINS}W cumplido")
            return

        # 3) Regla: reinicio al completar 6 operaciones.
        if self.cycle_ops >= CYCLE_MAX_OPERATIONS:
            self._reset_cycle(f"límite de {CYCLE_MAX_OPERATIONS} operaciones")
            return

        # 4) Regla anticipada: si matemáticamente ya no se puede llegar a 2W dentro de 6.
        remaining = CYCLE_MAX_OPERATIONS - self.cycle_ops
        if self.cycle_wins + remaining < CYCLE_TARGET_WINS:
            self._reset_cycle("objetivo 2W imposible en este ciclo")

    async def refresh_balance_and_risk(self) -> bool:
        """Actualiza balance y aplica stop-loss de sesión."""
        if self.dry_run:
            return False
        try:
            bal = float(await self.client.get_balance())
        except Exception as exc:
            log.debug("No se pudo actualizar balance de sesión: %s", exc)
            return False

        if self.session_start_balance is None:
            self.set_session_start_balance(bal)

        self.current_balance = bal
        self.martingale.set_balance(bal)
        if not self.session_start_balance or self.session_start_balance <= 0:
            return False

        drawdown = (self.session_start_balance - bal) / self.session_start_balance
        if drawdown >= MAX_LOSS_SESSION:
            self.session_stop_hit = True
            log.error(
                "🛑 STOP-LOSS DE SESIÓN activado: drawdown=%.1f%% (inicio=%.2f, actual=%.2f)",
                drawdown * 100,
                self.session_start_balance,
                bal,
            )
            return True
        return False

    async def reconcile_pending_candidates(self, max_age_minutes: Optional[float] = None) -> None:
        """
        Reconciliar ACCEPTED/PENDING al arrancar para no contaminar métricas.
        Si no se puede resolver una orden, se marca UNRESOLVED.
        """
        journal = get_journal()
        if journal._conn is None:
            return

        if max_age_minutes is not None and max_age_minutes > 0:
            cutoff = (datetime.now(tz=BROKER_TZ) - timedelta(minutes=float(max_age_minutes))).isoformat()
            rows = journal._conn.execute(
                """SELECT id, order_id
                   FROM candidates
                   WHERE outcome='PENDING'
                     AND decision='ACCEPTED'
                     AND datetime(scanned_at) <= datetime(?)""",
                (cutoff,),
            ).fetchall()
        else:
            rows = journal._conn.execute(
                """SELECT id, order_id
                   FROM candidates
                   WHERE outcome='PENDING' AND decision='ACCEPTED'"""
            ).fetchall()

        if not rows:
            if max_age_minutes is None:
                log.info("♻ Reconciliación inicial: no hay PENDING para revisar.")
            else:
                log.debug(
                    "♻ Reconciliación periódica: no hay PENDING con edad >= %.1f min.",
                    float(max_age_minutes),
                )
            return

        resolved = 0
        unresolved = 0

        for row in rows:
            rid = int(row[0])
            oid = str(row[1] or "").strip()

            # Sin identificador usable, no hay forma confiable de consultar resultado.
            if not oid or oid in {"BROKER_NO_ID"} or oid.startswith("DRY-"):
                journal._conn.execute(
                    "UPDATE candidates SET outcome='UNRESOLVED', closed_at=? WHERE id=? AND outcome='PENDING'",
                    (datetime.now(tz=BROKER_TZ).isoformat(), rid),
                )
                unresolved += 1
                continue

            try:
                outcome = None
                profit = 0.0

                # Compatibilidad: si guardamos REF-<id>, intentar check_win por id numérico.
                if oid.startswith("REF-"):
                    ref_id = int(oid.split("-", 1)[1])
                    win_val = await self.client.check_win(ref_id)
                    if isinstance(win_val, (int, float)):
                        profit = float(win_val)
                        outcome = "WIN" if profit > 0 else "LOSS"
                    elif isinstance(win_val, bool):
                        outcome = "WIN" if win_val else "LOSS"
                else:
                    status, payload = await self.client.get_result(oid)
                    if status == "win":
                        outcome = "WIN"
                        if isinstance(payload, dict):
                            profit = float(payload.get("profitAmount", 0) or 0)
                    elif status == "loss":
                        outcome = "LOSS"
                        if isinstance(payload, dict):
                            profit = float(payload.get("profitAmount", 0) or 0)

                if outcome in {"WIN", "LOSS"}:
                    journal._conn.execute(
                        "UPDATE candidates SET outcome=?, profit=?, closed_at=? WHERE id=? AND outcome='PENDING'",
                        (outcome, float(profit), datetime.now(tz=BROKER_TZ).isoformat(), rid),
                    )
                    resolved += 1
                else:
                    journal._conn.execute(
                        "UPDATE candidates SET outcome='UNRESOLVED', closed_at=? WHERE id=? AND outcome='PENDING'",
                        (datetime.now(tz=BROKER_TZ).isoformat(), rid),
                    )
                    unresolved += 1
            except Exception:
                journal._conn.execute(
                    "UPDATE candidates SET outcome='UNRESOLVED', closed_at=? WHERE id=? AND outcome='PENDING'",
                    (datetime.now(tz=BROKER_TZ).isoformat(), rid),
                )
                unresolved += 1

        journal._conn.commit()
        if max_age_minutes is None:
            log.info(
                "♻ Reconciliación inicial completada: %d resueltas, %d UNRESOLVED (total=%d).",
                resolved,
                unresolved,
                len(rows),
            )
        else:
            log.info(
                "♻ Reconciliación periódica (>= %.1f min): %d resueltas, %d UNRESOLVED (total=%d).",
                float(max_age_minutes),
                resolved,
                unresolved,
                len(rows),
            )

    def _strategy_snapshot(self) -> dict:
        """Snapshot de parámetros activos para auditoría de caja negra."""
        return {
            "tf_sec": TF_5M,
            "candles_lookback": CANDLES_LOOKBACK,
            "min_consolidation_bars": MIN_CONSOLIDATION_BARS,
            "max_range_pct": MAX_RANGE_PCT,
            "touch_tolerance_pct": TOUCH_TOLERANCE_PCT,
            "max_consolidation_min": MAX_CONSOLIDATION_MIN,
            "min_payout": MIN_PAYOUT,
            "duration_sec": DURATION_SEC,
            "max_concurrent_trades": MAX_CONCURRENT_TRADES,
            "cooldown_between_entries": COOLDOWN_BETWEEN_ENTRIES,
            "max_consecutive_entries_per_asset": MAX_CONSECUTIVE_ENTRIES_PER_ASSET,
            "martin_low_balance_threshold": MARTIN_LOW_BALANCE_THRESHOLD,
            "martin_max_attempts_low_balance": MARTIN_MAX_ATTEMPTS_LOW_BALANCE,
            "martin_max_attempts_session": MARTIN_MAX_ATTEMPTS_SESSION,
            "score_threshold_base": ADAPTIVE_THRESHOLD_BASE,
            "score_threshold_session": self.current_score_threshold,
            "volume_multiplier": VOLUME_MULTIPLIER,
            "volume_lookback": VOLUME_LOOKBACK,
            "zone_age_rebound_min": ZONE_AGE_REBOUND_MIN,
            "zone_age_breakout_min": ZONE_AGE_BREAKOUT_MIN,
            "strict_pattern_check": STRICT_PATTERN_CHECK,
            "entry_sync_to_candle": ENTRY_SYNC_TO_CANDLE,
            "entry_max_lag_sec": ENTRY_MAX_LAG_SEC,
            "entry_reject_last_sec": ENTRY_REJECT_LAST_SEC,
            "align_scan_to_candle": ALIGN_SCAN_TO_CANDLE,
            "scan_lead_sec": SCAN_LEAD_SEC,
            "broker_tz": BROKER_TZ_LABEL,
            "compensation_pending": self.compensation_pending,
            "last_closed_outcome": self.last_closed_outcome,
            "last_closed_amount": self.last_closed_amount,
            "max_loss_session": MAX_LOSS_SESSION,
            "dynamic_atr_range": USE_DYNAMIC_ATR_RANGE,
            "atr_period": ATR_PERIOD,
            "atr_range_factor": ATR_RANGE_FACTOR,
            "min_dynamic_range_pct": MIN_DYNAMIC_RANGE_PCT,
            "max_dynamic_range_pct": MAX_DYNAMIC_RANGE_PCT,
            "h1_confirm_enabled": H1_CONFIRM_ENABLED,
            "cycle_max_operations": CYCLE_MAX_OPERATIONS,
            "cycle_target_wins": CYCLE_TARGET_WINS,
            "cycle_target_profit_pct": CYCLE_TARGET_PROFIT_PCT,
            "cycle_id": self.cycle_id,
            "cycle_ops": self.cycle_ops,
            "cycle_wins": self.cycle_wins,
            "cycle_losses": self.cycle_losses,
            "cycle_profit": self.cycle_profit,
            "strat_b_can_trade": STRAT_B_CAN_TRADE,
            "strat_b_duration_sec": STRAT_B_DURATION_SEC,
            "strat_b_min_confidence": STRAT_B_MIN_CONFIDENCE,
            "last_entry_asset": self.last_entry_asset,
            "last_entry_asset_streak": self.last_entry_asset_streak,
            "greylist_assets": sorted(self.greylist_assets),
        }

    def _build_pre_objectives_audit(self, trade: TradeState) -> tuple[dict, Optional[bool], str]:
        """Compara ticket vs objetivos definidos antes de la ejecución."""
        if not trade.journal_id:
            return {}, None, "sin_journal_id"

        journal = get_journal()
        if journal._conn is None:
            return {}, None, "sin_conexion_journal"

        row = journal._conn.execute(
            """SELECT payout, score, entry_timing_decision, entry_duration_sec, strategy_json
               FROM candidates WHERE id=?""",
            (int(trade.journal_id),),
        ).fetchone()
        if not row:
            return {}, None, "fila_no_encontrada"

        strategy_raw = row["strategy_json"] or "{}"
        try:
            strategy = json.loads(strategy_raw)
        except Exception:
            strategy = {}

        checks: dict[str, bool] = {}
        min_payout = strategy.get("min_payout")
        if isinstance(min_payout, (int, float)):
            checks["payout_ok"] = float(row["payout"] or 0.0) >= float(min_payout)

        score_thr = strategy.get("score_threshold_session", strategy.get("score_threshold_base"))
        if isinstance(score_thr, (int, float)):
            checks["score_ok"] = float(row["score"] or 0.0) >= float(score_thr)

        timing_dec = str(row["entry_timing_decision"] or "")
        checks["timing_ok"] = timing_dec in {"SYNCED_1M_OPEN", "SYNC_DISABLED"}

        target_duration = strategy.get("strat_b_duration_sec") if trade.strategy_origin == "STRAT-B" else strategy.get("duration_sec")
        actual_duration = int(row["entry_duration_sec"] or trade.duration_sec)
        if isinstance(target_duration, (int, float)):
            checks["duration_ok"] = actual_duration == int(target_duration)

        failed = [k for k, v in checks.items() if not v]
        ok = len(failed) == 0 if checks else None
        note = "ok" if ok else ("fallaron: " + ", ".join(failed) if failed else "sin_checks")

        details = {
            "strategy_origin": trade.strategy_origin,
            "checks": checks,
            "targets": {
                "min_payout": min_payout,
                "score_threshold": score_thr,
                "target_duration_sec": int(target_duration) if isinstance(target_duration, (int, float)) else None,
            },
            "observed": {
                "payout": float(row["payout"] or 0.0),
                "score": float(row["score"] or 0.0),
                "entry_timing_decision": timing_dec,
                "entry_duration_sec": actual_duration,
            },
        }
        return details, ok, note

    async def _sync_to_next_candle_open(self, signal_ts: Optional[int] = None, asset: Optional[str] = None) -> EntryTimingInfo:
        """
        Sincroniza/valida timing de entrada al inicio de vela de 1m.

        Regla operativa:
        - Esperar siempre al próximo open de vela 1m.
        - Rechazar si el envío queda tardío (> ENTRY_MAX_LAG_SEC).
        - La duración de la orden es fija (DURATION_SEC = 300s).

        Devuelve un EntryTimingInfo con telemetría de timing.
        """
        if not ENTRY_SYNC_TO_CANDLE:
            return EntryTimingInfo(
                ok=True,
                lag_sec=0.0,
                duration_sec=DURATION_SEC,
                time_since_open_sec=0.0,
                secs_to_close_sec=float(TF_1M),
                decision="SYNC_DISABLED",
            )

        phase = int(self._candle_phase_sec % TF_1M)
        now = time.time()
        # Ajustar con offset de reloj y adelantar ENTRY_PRE_SEND_SEC para llegar al broker a tiempo.
        # now_adj usa el reloj calibrado con las últimas velas del servidor Quotex.
        now_adj = now + self._clock_offset
        next_open_adj = ((int(now_adj - phase) // TF_1M) + 1) * TF_1M + phase
        is_otc = bool(asset and "_otc" in str(asset).lower())
        # En OTC no conviene pre-send: la expiración es en segundos relativos y puede caer en vela previa.
        target_send_adj = (next_open_adj + ENTRY_OTC_POST_OPEN_SEC) if is_otc else (next_open_adj - ENTRY_PRE_SEND_SEC)
        wait_sec = max(0.0, target_send_adj - now_adj)
        if wait_sec > 0:
            if abs(self._clock_offset) >= 0.1:
                log.info(
                    "⏳ Esperando apertura 1m: %.2fs (fase=%ds, offset=%.2fs, modo=%s)",
                    wait_sec, phase, self._clock_offset, "post-open OTC" if is_otc else f"pre-send {ENTRY_PRE_SEND_SEC:.2f}s",
                )
            else:
                log.info(
                    "⏳ Esperando apertura de vela 1m: %.2fs (fase=%ds, modo=%s)",
                    wait_sec,
                    phase,
                    "post-open OTC" if is_otc else f"pre-send {ENTRY_PRE_SEND_SEC:.2f}s",
                )
            await asyncio.sleep(wait_sec)

        send_ts = time.time()
        lag_sec = (send_ts + self._clock_offset) - next_open_adj
        time_since_open = (send_ts + self._clock_offset - phase) % TF_1M
        secs_to_close = max(0.0, TF_1M - time_since_open)

        if lag_sec > ENTRY_MAX_LAG_SEC or secs_to_close <= ENTRY_REJECT_LAST_SEC:
            log.info(
                "⏳ Señal rechazada por timing 1m: lag=%.2fs, restante=%.2fs (max_lag=%.2fs)",
                lag_sec,
                secs_to_close,
                ENTRY_MAX_LAG_SEC,
            )
            return EntryTimingInfo(
                ok=False,
                lag_sec=lag_sec,
                duration_sec=DURATION_SEC,
                time_since_open_sec=time_since_open,
                secs_to_close_sec=secs_to_close,
                decision="REJECT_LATE_1M",
            )

        duration_dynamic = DURATION_SEC
        dur_min = duration_dynamic // 60
        dur_seg = duration_dynamic % 60
        log.info(
            "⏱ Entrada sincronizada al open 1m: lag=%.2fs, restante=%.2fs → duración fija=%dm%02ds (%ds)",
            lag_sec,
            secs_to_close,
            dur_min,
            dur_seg,
            duration_dynamic,
        )
        return EntryTimingInfo(
            ok=True,
            lag_sec=lag_sec,
            duration_sec=duration_dynamic,
            time_since_open_sec=time_since_open,
            secs_to_close_sec=secs_to_close,
            decision="SYNCED_1M_OPEN",
        )

    def _snapshot_current_candle_timing(self, asset: Optional[str] = None) -> EntryTimingInfo:
        """Captura el timing actual dentro de la vela 1m sin esperar ni alterar la ejecución."""
        if not ENTRY_SYNC_TO_CANDLE:
            return EntryTimingInfo(
                ok=True,
                lag_sec=0.0,
                duration_sec=DURATION_SEC,
                time_since_open_sec=0.0,
                secs_to_close_sec=float(TF_1M),
                decision="SYNC_DISABLED",
            )

        phase = int(self._candle_phase_sec % TF_1M)
        now_adj = time.time() + self._clock_offset
        current_open_adj = (int(now_adj - phase) // TF_1M) * TF_1M + phase
        time_since_open = max(0.0, now_adj - current_open_adj)
        secs_to_close = max(0.0, TF_1M - time_since_open)
        is_ok = time_since_open <= ENTRY_MAX_LAG_SEC and secs_to_close > ENTRY_REJECT_LAST_SEC
        is_otc = bool(asset and "_otc" in str(asset).lower())
        return EntryTimingInfo(
            ok=is_ok,
            lag_sec=time_since_open,
            duration_sec=DURATION_SEC,
            time_since_open_sec=time_since_open,
            secs_to_close_sec=secs_to_close,
            decision="BREAKOUT_IMMEDIATE_OTC" if is_otc else "BREAKOUT_IMMEDIATE",
        )

    async def _process_pending_reversals(
        self,
        assets_payout: dict[str, int],
        candles_1m_by_asset: dict[str, list],
        current_prices: dict[str, float],
    ) -> list[CandidateEntry]:
        """
        Re-evalúa activos en pending_reversals.
        Devuelve candidatos listos para entrar; limpia expirados/inválidos.
        """
        ready_candidates: list[CandidateEntry] = []
        to_remove: list[str] = []

        for sym, pr in list(self.pending_reversals.items()):
            side = "techo" if pr.entry_mode == "rebound_ceiling" else "piso"

            # Verificar que el activo sigue disponible este ciclo
            if sym not in assets_payout:
                to_remove.append(sym)
                log.info("↩ %s: no disponible este ciclo, cancelando espera", sym)
                continue

            # Verificar que el precio sigue cerca del extremo de la zona
            price = current_prices.get(sym)
            if price is None:
                to_remove.append(sym)
                continue

            if pr.proposed_direction == "call":
                still_at_extreme = price_at_floor(price, pr.zone.floor)
            else:
                still_at_extreme = price_at_ceiling(price, pr.zone.ceiling)

            if not still_at_extreme:
                log.info(
                    "↩ %s: precio %.5f abandonó el %s (%.5f), cancelando espera",
                    sym, price, side,
                    pr.zone.floor if pr.proposed_direction == "call" else pr.zone.ceiling,
                )
                to_remove.append(sym)
                continue

            # Re-evaluar patrón 1m
            candles_1m = candles_1m_by_asset.get(sym, [])
            pattern_name = "none"
            strength = 0.0
            confirms = False
            if len(candles_1m) >= 3:
                signal_1m = detect_reversal_pattern(candles_1m, pr.proposed_direction)
                pattern_name = signal_1m.pattern_name
                strength = signal_1m.strength
                confirms = signal_1m.confirms_direction

            pr.scans_waited += 1

            log.info(
                "⏳ %s: reintento %d/%d — patrón actual: %s (%.2f) %s",
                sym, pr.scans_waited, pr.max_wait_scans,
                pattern_name, strength,
                "✓" if confirms else "✗",
            )

            req_strength = self._required_rebound_strength(pr.proposed_direction)
            candle_valid, candle_fail_reason = self._validate_rejection_candle(
                candles_1m,
                pr.proposed_direction,
                REJECTION_CANDLE_MIN_BODY,
            )

            if self._is_put_pattern_blacklisted(pr.proposed_direction, pattern_name):
                log.info(
                    "↪ %s: patrón %s en lista negra para PUT — skip",
                    sym,
                    pattern_name,
                )
                if pr.scans_waited >= pr.max_wait_scans:
                    to_remove.append(sym)
                continue

            # Tanto CALL como PUT requieren patrón confirmado con fuerza suficiente.
            can_enter = candle_valid and confirms and strength >= req_strength

            if can_enter:
                log.info(
                    "✅ %s: reversión confirmada tras %d scan(s) — entrando %s",
                    sym, pr.scans_waited, pr.proposed_direction.upper(),
                )
                payout = assets_payout[sym]
                # Necesitamos velas 5m para construir el CandidateEntry — solo tenemos 1m aquí,
                # así que usamos una lista vacía: el score se basará en zona/payout/trend de 1m.
                candles_5m: list = []
                # Fetch H1 para niveles históricos
                h1_hist: List[Candle] = await fetch_candles_with_retry(
                    self.client,
                    sym,
                    H1_TF_SEC,
                    H1_CANDLES_LOOKBACK,
                    timeout_sec=H1_FETCH_TIMEOUT_SEC,
                )
                candidate = CandidateEntry(
                    asset=sym,
                    payout=payout,
                    zone=pr.zone,
                    direction=pr.proposed_direction,
                    candles=candles_5m,
                )
                candidate.candles_h1 = h1_hist
                candidate._reversal_pattern = pattern_name  # type: ignore[attr-defined]
                candidate._reversal_strength = strength  # type: ignore[attr-defined]
                candidate._reversal_confirms = confirms  # type: ignore[attr-defined]
                candidate._entry_mode = pr.entry_mode  # type: ignore[attr-defined]
                candidate._signal_ts_1m = candles_1m[-1].ts if candles_1m else None  # type: ignore[attr-defined]
                amount, _ = self._compute_initial_amount(payout)
                candidate._amount = amount  # type: ignore[attr-defined]
                candidate._stage = "initial"  # type: ignore[attr-defined]
                candidate._from_pending = True  # type: ignore[attr-defined]
                score_candidate(candidate)
                if confirms and strength >= 0.60:
                    candidate.score = round(candidate.score + 8.0, 1)
                    candidate.score_breakdown["reversal_bonus"] = 8.0
                elif confirms and strength >= REBOUND_MIN_STRENGTH_CALL:
                    candidate.score = round(candidate.score + 5.0, 1)
                    candidate.score_breakdown["reversal_bonus"] = 5.0
                elif pattern_name == "none":
                    candidate.score = round(candidate.score - 10.0, 1)
                    candidate.score_breakdown["weak_confirmation"] = -10.0
                ready_candidates.append(candidate)
                to_remove.append(sym)

            elif pr.scans_waited >= pr.max_wait_scans:
                log.info(
                    "⏰ %s: expiró espera sin confirmación (%d scans)",
                    sym, pr.scans_waited,
                )
                to_remove.append(sym)
            elif not confirms or strength < req_strength:
                if pattern_name == "none":
                    log.info(
                        "↪ %s: %s requiere patrón ≥%.2f, detectado %s %.2f (%s)",
                        sym,
                        pr.proposed_direction.upper(),
                        req_strength,
                        pattern_name,
                        strength,
                        explain_no_pattern_reason(candles_1m, pr.proposed_direction),
                    )
                else:
                    log.info(
                        "↪ %s: %s requiere patrón ≥%.2f, detectado %s %.2f",
                        sym,
                        pr.proposed_direction.upper(),
                        req_strength,
                        pattern_name,
                        strength,
                    )
            elif not candle_valid:
                log.info(
                    "↪ %s: vela 1m no confirma rebote en %s (%s)",
                    sym,
                    side,
                    candle_fail_reason,
                )

        for sym in to_remove:
            self.pending_reversals.pop(sym, None)

        return ready_candidates

    async def scan_all(self) -> None:
        """
        Escanea todos los activos, puntúa cada candidato con el sensor
        matemático y opera SOLO el mejor (o los N mejores si MAX_ENTRIES_CYCLE > 1).
        Si ninguno supera el umbral dinámico de score, no opera ese ciclo.
        """
        if await self.refresh_balance_and_risk():
            return

        assets = await get_open_assets(self.client, MIN_PAYOUT)
        if not assets:
            log.warning("No se obtuvieron activos OTC disponibles.")
            return

        total_assets_available = len(assets)
        if SCAN_MAX_ASSETS_PER_CYCLE > 0 and len(assets) > SCAN_MAX_ASSETS_PER_CYCLE:
            assets = assets[:SCAN_MAX_ASSETS_PER_CYCLE]
            log.info(
                "⚡ Aceleración scan: %d/%d activos (top payout)",
                len(assets),
                total_assets_available,
            )

        self.stats["scans"] += 1
        accepted_this_scan = 0
        self._cleanup_asset_blacklist()
        log.info("═══ SCAN #%d | %d activos payout≥%d%% ═══",
                 self.stats["scans"], len(assets), MIN_PAYOUT)

        # 1) Revisar martingalas de trades abiertos
        for sym in list(self.trades.keys()):
            entered = await self._check_martin(sym)
            if entered:
                await sleep_with_inline_countdown(COOLDOWN_BETWEEN_ENTRIES, "⏳ Cooldown post-orden")
            await asyncio.sleep(0.2)

        # Si hay operaciones abiertas: seguir escaneando para vigilar oportunidades.
        # El bloque de ejecución (paso 5) impedirá abrir nuevas entradas si se alcanzó
        # MAX_CONCURRENT_TRADES; los candidatos buenos se guardan en watched_candidates.
        if self.trades:
            activos_abiertos = ', '.join(self.trades.keys())
            log.info(
                "👁 Operación activa [%s] — escaneando igual para vigilar oportunidades.",
                activos_abiertos,
            )
        else:
            # Sin trades activos: limpiar vigilados viejos (> 5 min) para no ensuciar el log.
            if self.watched_candidates:
                stale = [a for a, (_, ts) in self.watched_candidates.items() if time.time() - ts > 300]
                for a in stale:
                    del self.watched_candidates[a]

        # 2) Recolectar candidatos sin trade abierto
        candidates: list[CandidateEntry] = []
        cycle_ob_summary: dict[str, str] = {}
        cycle_ma_summary: dict[str, str] = {}
        strat_b_total = 0
        strat_b_insufficient = 0
        strat_b_timeout = 0  # fetches 1m que devolvieron 0 velas (timeout)
        strat_b_hits: list[tuple[str, int, float, str, str]] = []
        strat_b_nearmiss: list[tuple[str, int, float, str]] = []
        
        # Limpiar registro de candidatos para este ciclo
        self.last_scan_strat_a = []
        self.last_scan_strat_b = []
        # Acumuladores para pending_reversals (populados durante el loop).
        candles_1m_collected: dict[str, list] = {}
        last_prices_collected: dict[str, float] = {}

        # Descarga paralela con límite de concurrencia para evitar timeouts masivos.
        fetch_sem = asyncio.Semaphore(CANDLE_FETCH_CONCURRENCY)
        h1_fetch_sem = asyncio.Semaphore(H1_FETCH_CONCURRENCY)
        ob_fetch_sem = asyncio.Semaphore(OB_FETCH_CONCURRENCY)

        async def _fetch_5m_limited(symbol: str) -> List[Candle]:
            async with fetch_sem:
                return await fetch_candles_with_retry(
                    self.client,
                    symbol,
                    TF_5M,
                    CANDLES_LOOKBACK,
                    timeout_sec=CANDLE_FETCH_TIMEOUT_SEC,
                )

        async def _fetch_1m_limited(symbol: str) -> List[Candle]:
            async with fetch_sem:
                result = await fetch_candles_with_retry(
                    self.client,
                    symbol,
                    60,
                    36,
                    timeout_sec=CANDLE_FETCH_1M_TIMEOUT_SEC,
                )
                if len(result) < 20:
                    log.debug(
                        "STRAT-B DEBUG: %s devolvió %d velas 1m (mínimo=20, timeout=%.0fs)",
                        symbol, len(result), CANDLE_FETCH_1M_TIMEOUT_SEC,
                    )
                return result

        async def _fetch_h1_limited(symbol: str) -> List[Candle]:
            async with h1_fetch_sem:
                return await fetch_candles_with_retry(
                    self.client,
                    symbol,
                    H1_TF_SEC,
                    H1_CANDLES_LOOKBACK,
                    timeout_sec=H1_FETCH_TIMEOUT_SEC,
                )

        async def _fetch_ob_limited(symbol: str) -> List[Candle]:
            async with ob_fetch_sem:
                return await fetch_candles_with_retry(
                    self.client,
                    symbol,
                    ORDER_BLOCK_TF_SEC,
                    ORDER_BLOCK_CANDLES,
                    timeout_sec=CANDLE_FETCH_TIMEOUT_SEC,
                    retries=1,
                )

        # Solo pre-lanzamos los fetches 5m en paralelo (concurrencia limitada).
        # Los fetches 1m se hacen de forma SECUENCIAL en el loop para evitar
        # que las respuestas WebSocket se mezclen entre activos.
        candles_tasks: dict[str, asyncio.Task[List[Candle]]] = {}
        prefetch_window = max(1, min(SCAN_5M_PREFETCH_WINDOW, len(assets)))
        for sym, _ in assets[:prefetch_window]:
            candles_tasks[sym] = asyncio.create_task(_fetch_5m_limited(sym), name=f"fetch_5m:{sym}")

        try:
            # Decrementar contadores de activos en cooldown post-fallo.
            expired_failed = [a for a, n in self.failed_assets.items() if n <= 1]
            for a in expired_failed:
                del self.failed_assets[a]
            for a in self.failed_assets:
                self.failed_assets[a] -= 1

            for idx, (sym, payout) in enumerate(assets, start=1):
                next_prefetch_idx = idx - 1 + prefetch_window
                if next_prefetch_idx < len(assets):
                    next_sym, _ = assets[next_prefetch_idx]
                    if next_sym not in candles_tasks:
                        candles_tasks[next_sym] = asyncio.create_task(
                            _fetch_5m_limited(next_sym),
                            name=f"fetch_5m:{next_sym}",
                        )

                if SCAN_PROGRESS_EVERY > 0 and (idx == 1 or idx % SCAN_PROGRESS_EVERY == 0 or idx == len(assets)):
                    log.info("⏱ Progreso scan: %d/%d activos", idx, len(assets))

                if sym in self.trades:
                    continue

                if sym in self.greylist_assets:
                    log.info("⏭ %s: en lista gris — skip", sym)
                    self.stats["skipped"] += 1
                    continue

                if self._is_asset_blacklisted(sym):
                    until_ts = self.asset_blacklist_until.get(sym, time.time())
                    remain_min = max(0.0, (until_ts - time.time()) / 60.0)
                    log.warning("⏭ %s: blacklist temporal activa (%.1f min restantes)", sym, remain_min)
                    self.stats["skipped"] += 1
                    continue

                # Skip activos que fallaron recientemente en place_order().
                if sym in self.failed_assets:
                    log.info("⏭ %s skipped — falló en ciclo anterior (%d ciclos restantes)",
                             sym, self.failed_assets[sym])
                    continue

                candles = await candles_tasks.pop(sym)

                # STRAT-B (Spring Sweep): fetch 1m SECUENCIAL para este activo.
                # Un pequeño sleep antes del request 1m deja que el WebSocket
                # liquide la respuesta 5m antes de enviar el nuevo request.
                await asyncio.sleep(0.25)
                strat_b_total += 1
                candles_1m = await _fetch_1m_limited(sym)
                candles_1m_collected[sym] = candles_1m
                # Calibrar reloj local contra timestamps del servidor Quotex.
                if candles_1m:
                    self._update_clock_offset(candles_1m, TF_1M)
                if len(candles_1m_collected) > SCAN_CANDLES_BUFFER_MAX:
                    candles_1m_collected.pop(next(iter(candles_1m_collected)), None)
                strat_b_signal = False
                strat_b_info = {
                    "confidence": 0.0,
                    "reason": "Datos 1m insuficientes",
                    "signal_type": None,
                    "direction": None,
                }
                if len(candles_1m) >= 20:
                    spring_df = pd.DataFrame(
                        {
                            "open": [c.open for c in candles_1m],
                            "high": [c.high for c in candles_1m],
                            "low": [c.low for c in candles_1m],
                            "close": [c.close for c in candles_1m],
                        }
                    )
                    strat_b_signal, strat_b_info = detect_spring_or_upthrust(
                        spring_df,
                        allow_early=STRAT_B_ALLOW_WYCKOFF_EARLY,
                    )
                elif len(candles_1m) == 0:
                    strat_b_timeout += 1
                else:
                    strat_b_insufficient += 1

                strat_b_conf = float(strat_b_info.get("confidence", 0.0) or 0.0)
                strat_b_signal_type = str(strat_b_info.get("signal_type") or "")
                strat_b_direction = str(strat_b_info.get("direction") or "call")
                strat_b_reason = str(strat_b_info.get("reason", f"{strat_b_signal_type or 'Señal'} detectado") or "Señal detectada")
                is_early_wyckoff = strat_b_signal_type.startswith("wyckoff_early")
                strat_b_required_conf = STRAT_B_MIN_CONFIDENCE_EARLY if is_early_wyckoff else STRAT_B_MIN_CONFIDENCE
                if strat_b_signal:
                    self.stats["strat_b_signals"] += 1
                    strat_b_hits.append((sym, payout, strat_b_conf, strat_b_direction, strat_b_signal_type))
                else:
                    if strat_b_conf >= STRAT_B_PREVIEW_MIN_CONF:
                        strat_b_nearmiss.append((sym, payout, strat_b_conf, strat_b_reason))

                # Modo opcional: STRAT-B puede abrir operación por sí sola.
                if (
                    STRAT_B_CAN_TRADE
                    and strat_b_signal
                    and strat_b_conf >= strat_b_required_conf
                    and len(self.trades) < MAX_CONCURRENT_TRADES
                ):
                    b_amount, _ = self._compute_initial_amount(payout)
                    pseudo_zone = ConsolidationZone(
                        asset=sym,
                        ceiling=float(candles_1m[-1].high),
                        floor=float(candles_1m[-1].low),
                        bars_inside=0,
                        detected_at=time.time(),
                        range_pct=0.0,
                    )
                    if strat_b_signal_type == "upthrust":
                        pattern_label = "Upthrust"
                    elif strat_b_signal_type == "spring":
                        pattern_label = "Spring Sweep"
                    elif strat_b_signal_type == "wyckoff_early_upthrust":
                        pattern_label = "Wyckoff Early M1+M2 (Upthrust)"
                    elif strat_b_signal_type == "wyckoff_early_spring":
                        pattern_label = "Wyckoff Early M1+M2 (Spring)"
                    else:
                        pattern_label = "Wyckoff"

                    # Registrar STRAT-B en caja negra (journal) antes de enviar la orden.
                    b_candidate = CandidateEntry(
                        asset=sym,
                        payout=payout,
                        zone=pseudo_zone,
                        direction=strat_b_direction,
                        candles=candles_1m,
                        score=round(strat_b_conf * 100.0, 1),
                        score_breakdown={
                            "compression": 0.0,
                            "bounce": round(strat_b_conf * 35.0, 2),
                            "trend": round(strat_b_conf * 25.0, 2),
                            "payout": round(min(20.0, (payout / 95.0) * 20.0), 2),
                        },
                    )
                    setattr(b_candidate, "_reversal_pattern", strat_b_signal_type or "none")
                    setattr(b_candidate, "_reversal_strength", strat_b_conf)
                    
                    # Guardar para registro en HUB
                    self.last_scan_strat_b.append(b_candidate)

                    b_strategy = self._strategy_snapshot()
                    b_strategy.update(
                        {
                            "strategy_origin": "STRAT-B",
                            "strat_b_signal_type": strat_b_signal_type,
                            "strat_b_confidence": strat_b_conf,
                            "strat_b_required_conf": strat_b_required_conf,
                            "strat_b_reason": strat_b_reason,
                        }
                    )

                    b_outcome = "DRY_RUN" if self.dry_run else "PENDING"
                    b_cid = get_journal().log_candidate(
                        b_candidate,
                        decision="ACCEPTED",
                        amount=b_amount,
                        stage="initial",
                        outcome=b_outcome,
                        strategy=b_strategy,
                    )

                    await self._enter(
                        sym,
                        strat_b_direction,
                        b_amount,
                        pseudo_zone,
                        f"{pattern_label} conf={strat_b_conf*100:.1f}% req={strat_b_required_conf*100:.1f}%",
                        "initial",
                        journal_cid=b_cid,
                        signal_ts=candles_1m[-1].ts if candles_1m else None,
                        strategy_origin="STRAT-B",
                        duration_sec=STRAT_B_DURATION_SEC,
                        payout=payout,
                        score_original=round(strat_b_conf * 100.0, 1),
                    )
                    await sleep_with_inline_countdown(COOLDOWN_BETWEEN_ENTRIES, "⏳ Cooldown post-orden")

                # STRAT-A requiere historial 5m mínimo para consolidación.
                if len(candles) < MIN_CONSOLIDATION_BARS + 2:
                    continue

                dynamic_max_range = MAX_RANGE_PCT
                atr_pct = 0.0
                if USE_DYNAMIC_ATR_RANGE:
                    atr = compute_atr(candles, ATR_PERIOD)
                    mid = candles[-1].close if candles[-1].close > 0 else 0.0
                    if atr > 0 and mid > 0:
                        atr_pct = atr / mid
                        dynamic_max_range = _clamp(
                            atr_pct * ATR_RANGE_FACTOR,
                            MIN_DYNAMIC_RANGE_PCT,
                            MAX_DYNAMIC_RANGE_PCT,
                        )
                dynamic_touch_tolerance = TOUCH_TOLERANCE_PCT
                if atr_pct > 0:
                    dynamic_touch_tolerance = _clamp(atr_pct * 0.12, 0.00015, 0.00080)

                zone = detect_consolidation(candles, max_range_pct=dynamic_max_range)
                if zone is None:
                    self.zones.pop(sym, None)
                    continue

                zone.asset = sym

                if sym in self.zones:
                    existing = self.zones[sym]
                    if MAX_CONSOLIDATION_MIN > 0 and existing.age_minutes > MAX_CONSOLIDATION_MIN:
                        log.info(
                            "⏱  %s: zona expirada por TIME_LIMIT (%.0fmin) | "
                            "techo=%.5f piso=%.5f rango=%.3f%% barras=%d | precio_actual=%.5f",
                            sym,
                            existing.age_minutes,
                            existing.ceiling,
                            existing.floor,
                            existing.range_pct * 100,
                            existing.bars_inside,
                            candles[-1].close if candles else 0.0,
                        )
                        get_journal().log_expired_zone(
                            asset=sym,
                            expiry_reason="TIME_LIMIT",
                            ceiling=existing.ceiling,
                            floor=existing.floor,
                            range_pct=existing.range_pct,
                            bars_inside=existing.bars_inside,
                            age_min=existing.age_minutes,
                            last_close=candles[-1].close if candles else 0.0,
                            payout=payout,
                        )
                        del self.zones[sym]
                        self.stats["expired_zones"] += 1
                        continue
                    zone.detected_at = existing.detected_at
                self.zones[sym] = zone

                last = candles[-1]
                price = last.close

                # ── Guardia de precio contra contaminación cruzada de pyquotex ──
                # Capa 1: precio fuera del rango de zona ±15% → descarte.
                _zone_mid = (zone.ceiling + zone.floor) / 2.0
                if _zone_mid > 0 and not (zone.floor * 0.85 <= price <= zone.ceiling * 1.15):
                    _last_valid = self.last_known_price.get(sym)
                    _last_txt = f" (último válido: {_last_valid:.5f})" if _last_valid else ""
                    log.warning(
                        "⚠ %s: precio %.5f contaminado — fuera de zona [%.5f, %.5f]%s",
                        sym, price, zone.floor * 0.85, zone.ceiling * 1.15, _last_txt,
                    )
                    self.stats["skipped"] += 1
                    continue

                # Capa 2: variación > 5% respecto al último precio válido conocido → descarte.
                _last_valid = self.last_known_price.get(sym)
                if _last_valid and _last_valid > 0:
                    _delta_pct = abs(price - _last_valid) / _last_valid
                    if _delta_pct > 0.05:
                        log.warning(
                            "⚠ %s: precio %.5f contaminado — cambio de %.1f%% vs último válido %.5f",
                            sym, price, _delta_pct * 100, _last_valid,
                        )
                        self.stats["skipped"] += 1
                        continue

                # Precio válido — actualizar registro.
                self.last_known_price[sym] = price
                last_prices_collected[sym] = price
                if len(last_prices_collected) > SCAN_CANDLES_BUFFER_MAX:
                    last_prices_collected.pop(next(iter(last_prices_collected)), None)

                candles_ob = await _fetch_ob_limited(sym)
                ob_tf_label = "3m"
                if len(candles_ob) < 6:
                    candles_ob = candles
                    ob_tf_label = "5m_fallback"
                blocks = self._detect_order_blocks(candles_ob)
                self.order_blocks_by_asset[sym] = blocks
                ma_state = self._compute_ma_state(sym, candles)
                if blocks.get("bull"):
                    b = blocks["bull"][0]
                    cycle_ob_summary[sym] = f"bull@{b.high:.4f}-{b.low:.4f} ({ob_tf_label})"
                elif blocks.get("bear"):
                    b = blocks["bear"][0]
                    cycle_ob_summary[sym] = f"bear@{b.high:.4f}-{b.low:.4f} ({ob_tf_label})"
                if ma_state is None:
                    cycle_ma_summary[sym] = "SIN_DATOS"
                elif ma_state.trend == "FLAT":
                    cycle_ma_summary[sym] = "FLAT"
                else:
                    comparator = ">" if ma_state.ma35 >= ma_state.ma50 else "<"
                    cycle_ma_summary[sym] = (
                        f"{ma_state.trend} (MA35={ma_state.ma35:.4f} {comparator} MA50={ma_state.ma50:.4f})"
                    )

                direction: Optional[str] = None
                amount, _ = self._compute_initial_amount(payout)
                stage = "initial"
                entry_mode = "none"
                breakout_strength_ok = False

                if price_at_ceiling(price, zone.ceiling, dynamic_touch_tolerance):
                    direction = "put"
                    entry_mode = "rebound_ceiling"
                elif price_at_floor(price, zone.floor, dynamic_touch_tolerance):
                    direction = "call"
                    entry_mode = "rebound_floor"
                elif broke_above(last, zone.ceiling) and is_high_volume_break(last, candles):
                    # Ruptura con fuerza hacia arriba: compra inmediata (momentum).
                    direction = "call"
                    stage = "breakout"
                    entry_mode = "breakout_above"
                    breakout_strength_ok = True
                    log.info(
                        "🟢 %s: BROKEN_ABOVE techo=%.5f | cierre=%.5f cuerpo=%.5f → CALL inmediato",
                        sym, zone.ceiling, last.close, last.body,
                    )
                    expired_zone_id = get_journal().log_expired_zone(
                        asset=sym,
                        expiry_reason="BROKEN_ABOVE",
                        ceiling=zone.ceiling,
                        floor=zone.floor,
                        range_pct=zone.range_pct,
                        bars_inside=zone.bars_inside,
                        age_min=zone.age_minutes,
                        last_close=last.close,
                        break_body=last.body,
                        payout=payout,
                    )
                    capture_file = self._record_broken_zone_snapshot(
                        asset=sym,
                        payout=payout,
                        reason="BROKEN_ABOVE",
                        expired_zone_id=expired_zone_id,
                        zone=zone,
                        last=last,
                        candles_1m_used=candles_1m,
                        candles_5m_used=candles,
                    )
                    self._schedule_followup_capture(sym, capture_file)
                    log.info("🧾 %s: snapshot BROKEN_ABOVE guardado -> %s", sym, capture_file.name)
                    self.broken_zones[sym] = time.time()
                elif broke_below(last, zone.floor) and is_high_volume_break(last, candles):
                    # Ruptura con fuerza hacia abajo: venta inmediata (momentum).
                    direction = "put"
                    stage = "breakout"
                    entry_mode = "breakout_below"
                    breakout_strength_ok = True
                    log.info(
                        "🔴 %s: BROKEN_BELOW piso=%.5f | cierre=%.5f cuerpo=%.5f → PUT inmediato",
                        sym, zone.floor, last.close, last.body,
                    )
                    expired_zone_id = get_journal().log_expired_zone(
                        asset=sym,
                        expiry_reason="BROKEN_BELOW",
                        ceiling=zone.ceiling,
                        floor=zone.floor,
                        range_pct=zone.range_pct,
                        bars_inside=zone.bars_inside,
                        age_min=zone.age_minutes,
                        last_close=last.close,
                        break_body=last.body,
                        payout=payout,
                    )
                    capture_file = self._record_broken_zone_snapshot(
                        asset=sym,
                        payout=payout,
                        reason="BROKEN_BELOW",
                        expired_zone_id=expired_zone_id,
                        zone=zone,
                        last=last,
                        candles_1m_used=candles_1m,
                        candles_5m_used=candles,
                    )
                    self._schedule_followup_capture(sym, capture_file)
                    log.info("🧾 %s: snapshot BROKEN_BELOW guardado -> %s", sym, capture_file.name)
                    self.broken_zones[sym] = time.time()

                if direction is None:
                    self.stats["skipped"] += 1
                    continue

                # Si la ruptura ya fue validada con fuerza (BROKEN_ABOVE/BELOW),
                # no bloquearla por antigüedad de zona para mantener el modo "inmediato".
                skip_zone_age_check = stage == "breakout" and breakout_strength_ok
                min_zone_age = ZONE_AGE_BREAKOUT_MIN if stage == "breakout" else ZONE_AGE_REBOUND_MIN
                if (not skip_zone_age_check) and zone.age_minutes < min_zone_age:
                    log.info(
                        "⏭ %s: zona demasiado joven (%.1fmin < %dmin) — skip",
                        sym,
                        zone.age_minutes,
                        min_zone_age,
                    )
                    self.stats["rejected_young_zone"] += 1
                    self.stats["skipped"] += 1
                    continue

                # Confirmación de reversión para entradas por rebote en techo/piso.
                pattern_name = "none"
                strength = 0.0
                confirms = False
                if len(candles_1m) >= 3:
                    signal_1m = detect_reversal_pattern(candles_1m, direction)
                    pattern_name = signal_1m.pattern_name
                    strength = signal_1m.strength
                    confirms = signal_1m.confirms_direction

                if entry_mode.startswith("rebound"):
                    side = "techo" if entry_mode == "rebound_ceiling" else "piso"
                    
                    # Validar forma de la vela 1m que tocó piso/techo
                    candle_valid, candle_fail_reason = self._validate_rejection_candle(
                        candles_1m, direction, REJECTION_CANDLE_MIN_BODY
                    )
                    
                    if not candle_valid:
                        # Vela no confirma rebote → espera activa
                        if sym not in self.pending_reversals:
                            self.pending_reversals[sym] = PendingReversal(
                                asset=sym,
                                zone=zone,
                                proposed_direction=direction,
                                conflicting_pattern=candle_fail_reason,
                                detected_at=datetime.now(tz=BROKER_TZ),
                                entry_mode=entry_mode,
                                payout=payout,
                            )
                            log.info(
                                "⏳ %s: vela 1m no confirma rebote en %s (%s) — esperando confirmación (1/%d)",
                                sym, side, candle_fail_reason,
                                self.pending_reversals[sym].max_wait_scans,
                            )
                        else:
                            # Ya existe: actualizar razón de rechazo y zona
                            self.pending_reversals[sym].conflicting_pattern = candle_fail_reason
                            self.pending_reversals[sym].zone = zone
                        self.stats["skipped"] += 1
                        continue
                    
                    # Vela confirma dirección — validar patrón de reversión como antes
                    req_strength = self._required_rebound_strength(direction)
                    if self._is_put_pattern_blacklisted(direction, pattern_name):
                        if sym not in self.pending_reversals:
                            self.pending_reversals[sym] = PendingReversal(
                                asset=sym,
                                zone=zone,
                                proposed_direction=direction,
                                conflicting_pattern=pattern_name,
                                detected_at=datetime.now(tz=BROKER_TZ),
                                entry_mode=entry_mode,
                                payout=payout,
                            )
                        else:
                            self.pending_reversals[sym].conflicting_pattern = pattern_name
                            self.pending_reversals[sym].zone = zone
                        log.info(
                            "↪ %s: patrón %s en lista negra para PUT — skip",
                            sym,
                            pattern_name,
                        )
                        self.stats["skipped"] += 1
                        continue
                    pattern_ok = confirms and strength >= req_strength

                    if not pattern_ok:
                        if STRICT_PATTERN_CHECK and pattern_name != "none" and (not confirms) and strength >= 0.65:
                            log.info(
                                "⛔ %s: STRICT_PATTERN_CHECK activo — descarte antes de score por patrón contradictorio confirmado %s %.2f en %s",
                                sym,
                                pattern_name,
                                strength,
                                side,
                            )
                            self.stats["skipped"] += 1
                            continue
                        if direction == "put":
                            if sym not in self.pending_reversals:
                                self.pending_reversals[sym] = PendingReversal(
                                    asset=sym,
                                    zone=zone,
                                    proposed_direction=direction,
                                    conflicting_pattern=f"{pattern_name}:{strength:.2f}",
                                    detected_at=datetime.now(tz=BROKER_TZ),
                                    entry_mode=entry_mode,
                                    payout=payout,
                                )
                            if pattern_name == "none":
                                log.info(
                                    "↪ %s: PUT requiere patrón ≥%.2f, detectado %s %.2f (%s)",
                                    sym,
                                    req_strength,
                                    pattern_name,
                                    strength,
                                    explain_no_pattern_reason(candles_1m, direction),
                                )
                            else:
                                log.info(
                                    "↪ %s: PUT requiere patrón ≥%.2f, detectado %s %.2f",
                                    sym,
                                    req_strength,
                                    pattern_name,
                                    strength,
                                )
                            self.stats["skipped"] += 1
                            continue
                        if pattern_name != "none" and not confirms:
                            # Patrón contradictorio: registrar para espera activa.
                            if sym not in self.pending_reversals:
                                self.pending_reversals[sym] = PendingReversal(
                                    asset=sym,
                                    zone=zone,
                                    proposed_direction=direction,
                                    conflicting_pattern=pattern_name,
                                    detected_at=datetime.now(tz=BROKER_TZ),
                                    entry_mode=entry_mode,
                                    payout=payout,
                                )
                                log.info(
                                    "⏳ %s: patrón conflictivo (%s) en %s — "
                                    "esperando reversión (intento 1/%d)",
                                    sym, pattern_name, side,
                                    self.pending_reversals[sym].max_wait_scans,
                                )
                            else:
                                # Ya existe: actualizar patrón conflictivo y zona.
                                self.pending_reversals[sym].conflicting_pattern = pattern_name
                                self.pending_reversals[sym].zone = zone
                        else:
                            log.info(
                                "↪ %s: rebote en %s sin patrón suficiente (%s %.2f) — esperando confirmación.",
                                sym, side, pattern_name, strength,
                            )
                        self.stats["skipped"] += 1
                        continue

                if H1_CONFIRM_ENABLED:
                    h1_candles = await _fetch_h1_limited(sym)
                    h1_trend = infer_h1_trend(h1_candles)
                    if (direction == "put" and h1_trend == "bullish") or (
                        direction == "call" and h1_trend == "bearish"
                    ):
                        self.stats["filtered_sensor"] += 1
                        continue
                else:
                    h1_candles = await _fetch_h1_limited(sym)

                candidate = CandidateEntry(
                    asset=sym,
                    payout=payout,
                    zone=zone,
                    direction=direction,
                    candles=candles,
                )
                candidate.candles_h1 = h1_candles

                setattr(candidate, "_reversal_pattern", pattern_name)
                setattr(candidate, "_reversal_strength", strength)
                setattr(candidate, "_reversal_confirms", confirms)
                setattr(candidate, "_entry_mode", entry_mode)
                setattr(candidate, "_signal_ts_1m", candles_1m[-1].ts if candles_1m else None)

                setattr(candidate, "_amount", amount)
                setattr(candidate, "_stage", stage)
                setattr(candidate, "_ma_state", ma_state)
                setattr(candidate, "_order_blocks", blocks)
                setattr(candidate, "_ob_tf", ob_tf_label)
                setattr(
                    candidate,
                    "_force_execute",
                    bool(FORCE_EXECUTE_STRONG_BREAKOUT and stage == "breakout" and breakout_strength_ok),
                )

                score_candidate(candidate)

                # Calcular body_ratio para log
                body_ratio = 0.0
                if len(candles_1m) > 0:
                    last_1m = candles_1m[-1]
                    if last_1m.range > 0:
                        body_ratio = abs(last_1m.close - last_1m.open) / last_1m.range

                # Modificador por confirmación 1m.
                if confirms and strength >= 0.60:
                    candidate.score = round(candidate.score + 8.0, 1)
                    candidate.score_breakdown["reversal_bonus"] = 8.0
                    log.debug(
                        "1m_pattern=%s strength=%.2f body_ratio=%.0f%% +8pts reversal_bonus",
                        pattern_name, strength, body_ratio * 100,
                    )
                elif confirms and strength >= REBOUND_MIN_STRENGTH_CALL:
                    candidate.score = round(candidate.score + 5.0, 1)
                    candidate.score_breakdown["reversal_bonus"] = 5.0
                    log.debug(
                        "1m_pattern=%s strength=%.2f body_ratio=%.0f%% +5pts reversal_bonus",
                        pattern_name, strength, body_ratio * 100,
                    )
                elif (not confirms) and pattern_name != "none":
                    candidate.score = round(candidate.score - 15.0, 1)
                    candidate.score_breakdown["reversal_penalty"] = -15.0
                    log.debug(
                        "1m_pattern=%s strength=%.2f body_ratio=%.0f%% -15pts reversal_penalty",
                        pattern_name, strength, body_ratio * 100,
                    )
                elif pattern_name == "none":
                    # Sin patrón detectado: vela confirma dirección (ya validada arriba)
                    candidate.score = round(candidate.score - 10.0, 1)
                    candidate.score_breakdown["weak_confirmation"] = -10.0
                    log.debug(
                        "1m_pattern=%s strength=%.2f body_ratio=%.0f%% -10pts weak_confirmation",
                        pattern_name, strength, body_ratio * 100,
                    )

                if stage == "breakout" and breakout_strength_ok:
                    candidate.score = round(candidate.score + 6.0, 1)
                    candidate.score_breakdown["breakout_bonus"] = 6.0

                ob_points, ob_info = self._score_order_blocks(
                    direction=direction,
                    price=price,
                    blocks=blocks,
                    avg_body=ma_state.avg_body if ma_state else 1e-9,
                )
                if ob_points != 0:
                    candidate.score = round(candidate.score + ob_points, 1)
                    candidate.score_breakdown["order_block"] = round(ob_points, 1)
                setattr(candidate, "_ob_info", f"tf={ob_tf_label} | {ob_info}")

                ma_points, ma_info = self._score_ma(direction, ma_state)
                if ma_points != 0:
                    candidate.score = round(candidate.score + ma_points, 1)
                    candidate.score_breakdown["ma_filter"] = round(ma_points, 1)
                setattr(candidate, "_ma_info", ma_info)

                log.info(
                    "[OB] %s tf=%s dir=%s ajuste=%+.1f | %s",
                    sym,
                    ob_tf_label,
                    direction.upper(),
                    ob_points,
                    ob_info,
                )
                log.info(
                    "[MA] %s dir=%s ajuste=%+.1f | %s",
                    sym,
                    direction.upper(),
                    ma_points,
                    ma_info,
                )

                candidates.append(candidate)
                self.last_scan_strat_a.append(candidate)
                await asyncio.sleep(0.30)  # breve pausa para separar respuestas WebSocket
        finally:
            pending_5m = [t for t in candles_tasks.values() if not t.done()]
            for t in pending_5m:
                t.cancel()
            if pending_5m:
                await asyncio.gather(*pending_5m, return_exceptions=True)

        # Resumen STRAT-B por ciclo (evita spam por activo).
        log.info(
            "[STRAT-B] Resumen ciclo: %d evaluados | señales=%d | "
            "timeout_fetch=%d | datos_insuficientes=%d | sin_patrón=%d",
            strat_b_total,
            len(strat_b_hits),
            strat_b_timeout,
            strat_b_insufficient,
            strat_b_total - len(strat_b_hits) - strat_b_timeout - strat_b_insufficient,
        )
        if strat_b_hits:
            for sym, payout, conf, b_dir, b_type in sorted(strat_b_hits, key=lambda x: -x[2])[:STRAT_B_LOG_TOP_N]:
                if b_type == "upthrust":
                    pattern_label = "Upthrust"
                elif b_type == "spring":
                    pattern_label = "Spring Sweep"
                elif b_type == "wyckoff_early_upthrust":
                    pattern_label = "Wyckoff Early M1+M2 (Upthrust)"
                elif b_type == "wyckoff_early_spring":
                    pattern_label = "Wyckoff Early M1+M2 (Spring)"
                else:
                    pattern_label = "Wyckoff"
                log.info(
                    "[STRAT-B] ✅ %s [%d%%] %s | conf=%.1f | %s ✓",
                    sym,
                    payout,
                    b_dir.upper(),
                    conf * 100,
                    pattern_label,
                )
                candles_2m = await fetch_candles_with_retry(
                    self.client,
                    sym,
                    120,
                    90,
                    timeout_sec=CANDLE_FETCH_TIMEOUT_SEC,
                )
                support_2m, touches = find_strong_support_2m(candles_2m)
                if support_2m is not None:
                    log.info(
                        "[STRAT-B] 📍 %s soporte fuerte 2m=%.5f (toques=%d)",
                        sym,
                        support_2m,
                        touches,
                    )
                else:
                    log.info("[STRAT-B] 📍 %s sin soporte fuerte 2m detectable", sym)
        elif strat_b_nearmiss:
            for sym, payout, conf, reason in sorted(strat_b_nearmiss, key=lambda x: -x[2])[:STRAT_B_LOG_TOP_N]:
                log.info(
                    "[STRAT-B] ~ %s [%d%%] conf=%.1f | %s",
                    sym,
                    payout,
                    conf * 100,
                    reason,
                )

        # 3) Procesar reversiones pendientes (espera activa post-conflicto).
        if self.pending_reversals:
            assets_payout_map = dict(assets)
            pending_confirmed = await self._process_pending_reversals(
                assets_payout_map,
                candles_1m_collected,
                last_prices_collected,
            )
            if pending_confirmed:
                log.info("⏳→✅ %d candidato(s) de pending_reversals agregados al ciclo.", len(pending_confirmed))
                candidates.extend(pending_confirmed)

        self.pending_martin.clear()

        prev_threshold = self.current_score_threshold
        session_threshold = self._update_dynamic_threshold()
        window_accepts = sum(self.accepted_scans_window)
        if prev_threshold != session_threshold:
            reason = self._threshold_change_reason(window_accepts)
            log.warning(
                "⚠ UMBRAL cambiado: %d → %d (%s)",
                prev_threshold,
                session_threshold,
                reason,
            )
        self._log_dry_run_verbose_cycle_summary(
            cycle_num=self.stats["scans"],
            threshold=session_threshold,
            accepted_last_window=window_accepts,
            cycle_ob_summary=cycle_ob_summary,
            cycle_ma_summary=cycle_ma_summary,
        )

        # 3) Log de candidatos
        if not candidates:
            log.info("  Sin señales este ciclo.")
            self._record_scan_acceptances(0)
            self._record_hub_scan_cycle(total_assets_available)
            return

        log.info(
            "[SCORE] Umbral dinámico sesión=%d (ventana=%d scans, accepted=%d)",
            session_threshold,
            ADAPTIVE_THRESHOLD_WINDOW_SCANS,
            window_accepts,
        )

        journal = get_journal()
        log.info("── %d candidatos evaluados ──", len(candidates))
        for c in sorted(candidates, key=lambda x: -x.score):
            rng_pips = (c.zone.ceiling - c.zone.floor) * 10_000
            status = "✅" if c.score >= session_threshold else "❌"
            decision_tag = "ACEPTADO" if c.score >= session_threshold else "RECHAZADO"
            rev_pattern = getattr(c, "_reversal_pattern", "none")
            rev_strength = float(getattr(c, "_reversal_strength", 0.0) or 0.0)
            rev_confirms = bool(getattr(c, "_reversal_confirms", False))
            ob_adj = int(round(c.score_breakdown.get("order_block", 0.0)))
            ma_adj = int(round(c.score_breakdown.get("ma_filter", 0.0)))
            zone_age_min = c.zone.age_minutes
            if rev_pattern == "none":
                rev_txt = "~ sin patrón 1m"
            elif rev_confirms:
                rev_txt = "✓ confirmado"
            else:
                rev_txt = "✗ contradice (-15pts)"
            log.info(
                "  %s %s [%d%%] %s  score=%.1f/100  "
                "[comp=%.1f  rebote=%.1f  trend=%.1f  payout=%.1f]  "
                "rng=%.1fpips  zona=%.0fmin  1m_pattern=%s strength=%.2f %s "
                "[OB%+d][MA%+d][umbral=%d] → %s",
                status, c.asset, c.payout, c.direction.upper(), c.score,
                c.score_breakdown.get("compression", 0),
                c.score_breakdown.get("bounce", 0),
                c.score_breakdown.get("trend", 0),
                c.score_breakdown.get("payout", 0),
                rng_pips,
                zone_age_min,
                rev_pattern,
                rev_strength,
                rev_txt,
                ob_adj,
                ma_adj,
                session_threshold,
                decision_tag,
            )
            log.info("      [OB] %s", getattr(c, "_ob_info", "sin datos"))
            log.info("      [MA] %s", getattr(c, "_ma_info", "sin datos"))

        # 4) Seleccionar mejores
        selected, rejected = select_best(candidates, threshold=session_threshold)

        forced_breakouts = [c for c in candidates if bool(getattr(c, "_force_execute", False))]
        if forced_breakouts:
            existing = {id(c) for c in selected}
            for c in forced_breakouts:
                if id(c) not in existing:
                    selected.append(c)
                    existing.add(id(c))
            rejected = [c for c in rejected if id(c) not in {id(x) for x in forced_breakouts}]
            log.warning(
                "⚠ Modo FORCE_BREAKOUT: %d ruptura(s) fuerte(s) enviadas aun con score bajo umbral.",
                len(forced_breakouts),
            )

        # Filtro final live: operar solo activos cerca del gatillo real.
        near_selected: list[CandidateEntry] = []
        moved_away: list[CandidateEntry] = []
        for c in selected:
            if bool(getattr(c, "_force_execute", False)) or self._is_candidate_near_trigger(c):
                near_selected.append(c)
            else:
                moved_away.append(c)

        if moved_away:
            for c in moved_away:
                distance = self._candidate_trigger_distance_pct(c)
                dist_txt = f"{distance * 100:.3f}%" if distance is not None else "n/a"
                log.info(
                    "⏭ %s %s fuera de ventana de disparo (%s) — se pospone.",
                    c.direction.upper(),
                    c.asset,
                    dist_txt,
                )
                journal.log_candidate(
                    c,
                    decision="REJECTED_WINDOW",
                    reject_reason=f"fuera de ventana near-trigger ({dist_txt})",
                    amount=getattr(c, "_amount", 0.0),
                    stage=getattr(c, "_stage", "initial"),
                    strategy=self._strategy_snapshot(),
                )

        selected = near_selected

        # Registrar rechazados por score
        for c in rejected:
            journal.log_candidate(
                c,
                decision="REJECTED_SCORE",
                reject_reason=f"score={c.score:.1f} < umbral dinámico {session_threshold}",
                amount=getattr(c, "_amount", 0.0),
                stage=getattr(c, "_stage", "initial"),
                strategy=self._strategy_snapshot(),
            )
            # Telemetría de antigüedad de zona
            age_penalty = abs(c.score_breakdown.get("age_penalty", 0.0))
            if age_penalty > 0 and c.zone.age_minutes > 120:
                self.stats["score_rejected_age"] += 1
            else:
                self.stats["score_rejected_score"] += 1

        if not selected:
            best = max(candidates, key=lambda x: x.score)
            log.info(
                "[STRAT-A] ⛔ Ningún candidato supera el umbral %d/100. "
                "Mejor disponible: %s score=%.1f — NO se opera este ciclo.",
                session_threshold, best.asset, best.score,
            )
            self.stats["skipped"] += len(candidates)
            self._record_scan_acceptances(0)
            self._record_hub_scan_cycle(total_assets_available)
            return

        log.info("[STRAT-A] 🏆 Mejor(es) seleccionado(s): %d de %d candidatos",
                 len(selected), len(candidates))

        # 5) Ejecutar seleccionados
        if len(self.trades) >= MAX_CONCURRENT_TRADES:
            log.info(
                "🛑 Límite alcanzado (%d/%d). Se posponen nuevas entradas.",
                len(self.trades), MAX_CONCURRENT_TRADES,
            )
            # Guardar el mejor candidato como "vigilado" para entrar cuando cierre el trade activo.
            best_watched = max(selected, key=lambda x: x.score)
            self.watched_candidates[best_watched.asset] = (best_watched, time.time())
            rev_w = getattr(best_watched, "_reversal_pattern", "none")
            log.info(
                "👁  VIGILADO: %s %s score=%.1f/100 payout=%d%% 1m=%s — "
                "se intentará entrar en cuanto cierre la operación activa.",
                best_watched.direction.upper(), best_watched.asset,
                best_watched.score, best_watched.payout, rev_w,
            )
            # Registrar rechazados por límite
            for c in selected:
                journal.log_candidate(
                    c,
                    decision="REJECTED_LIMIT",
                    reject_reason=f"trades abiertos={len(self.trades)}/{MAX_CONCURRENT_TRADES} — vigilado",
                    amount=getattr(c, "_amount", 0.0),
                    stage=getattr(c, "_stage", "initial"),
                    strategy=self._strategy_snapshot(),
                )
            self.stats["skipped"] += len(selected)
            self._record_scan_acceptances(0)
            self._record_hub_scan_cycle(total_assets_available)
            return

        for winner in selected:
            if len(self.trades) >= MAX_CONCURRENT_TRADES:
                journal.log_candidate(
                    winner,
                    decision="REJECTED_LIMIT",
                    reject_reason=f"trades abiertos={len(self.trades)}/{MAX_CONCURRENT_TRADES}",
                    amount=getattr(winner, "_amount", 0.0),
                    stage=getattr(winner, "_stage", "initial"),
                    strategy=self._strategy_snapshot(),
                )
                break
            log.info(explain_score(winner, threshold=session_threshold))
            amount = getattr(winner, "_amount", 0.0)
            stage = getattr(winner, "_stage", "initial")
            # Si hay compensación pendiente por LOSS anterior, escalar el monto
            if self.compensation_pending and stage == "initial":
                amount, exp_profit = self._compute_compensation_amount(winner.payout, self.last_closed_amount)
                log.info(
                    "🔁 COMPENSACIÓN activa — monto dinámico $%.2f | payout=%d%% | recup=%.2f (est. neto=%.2f)",
                    amount,
                    winner.payout,
                    self.last_closed_amount,
                    exp_profit,
                )
            # Pre-registrar como ACCEPTED (outcome se actualiza después)
            outcome = "DRY_RUN" if self.dry_run else "PENDING"
            cid = journal.log_candidate(
                winner,
                decision="ACCEPTED",
                amount=amount,
                stage=stage,
                outcome=outcome,
                strategy=self._strategy_snapshot(),
            )
            accepted_this_scan += 1
            winner._journal_cid = cid  # type: ignore[attr-defined]
            entered = await self._enter(
                winner.asset, winner.direction, amount,
                winner.zone,
                f"SCORE={winner.score:.1f}/100 | {winner.direction.upper()} "
                f"en {winner.asset} payout={winner.payout}%",
                stage,
                journal_cid=cid,
                signal_ts=getattr(winner, "_signal_ts_1m", winner.candles[-1].ts if winner.candles else None),
                strategy_origin="STRAT-A",
                duration_sec=DURATION_SEC,
                payout=winner.payout,
                score_original=winner.score,
            )
            if entered:
                await sleep_with_inline_countdown(COOLDOWN_BETWEEN_ENTRIES, "⏳ Cooldown post-orden")

        self.stats["skipped"] += len(rejected)
        self._record_scan_acceptances(accepted_this_scan)
        self._record_hub_scan_cycle(total_assets_available)

    async def ensure_connection(self) -> bool:
        """Valida websocket activa y reintenta reconectar sin tumbar el loop 24/7."""
        try:
            if await asyncio.wait_for(self.client.check_connect(), timeout=3.0):
                return True
        except Exception:
            pass

        for attempt in range(1, HEALTHCHECK_RECONNECT_RETRIES + 1):
            try:
                try:
                    await asyncio.wait_for(self.client.close(), timeout=2.0)
                except Exception:
                    pass

                ok, reason = await asyncio.wait_for(
                    self.client.connect(),
                    timeout=RECONNECT_TIMEOUT_SEC,
                )
                if ok:
                    await asyncio.wait_for(
                        self.client.change_account(self.account_type),
                        timeout=RECONNECT_TIMEOUT_SEC,
                    )
                    log.warning("🔌 Reconexión exitosa durante loop 24/7")
                    return True
                reason_txt = str(reason)
                if "403" in reason_txt or "cloudflare" in reason_txt.lower() or "cf-mitigated" in reason_txt.lower():
                    log.warning(
                        "☁️ Challenge 403 detectado en reconexión (%d/%d). Reintentando...",
                        attempt,
                        HEALTHCHECK_RECONNECT_RETRIES,
                    )
                    _clear_quotex_session(self.client)
                    await asyncio.sleep(CF_403_BACKOFF_SEC)
                    continue
                log.warning("Reconexión fallida (%d/%d): %s", attempt, HEALTHCHECK_RECONNECT_RETRIES, reason)
            except asyncio.TimeoutError:
                log.warning(
                    "Reconexión timeout (%d/%d) en ensure_connection",
                    attempt,
                    HEALTHCHECK_RECONNECT_RETRIES,
                )
            except Exception as exc:
                log.warning("Excepción en reconexión: %s", exc)
            await asyncio.sleep(2.0)
        return False


    async def _resolve_trade(self, trade: "TradeState", sym: str) -> None:
        """
        Constry:
                self.hub.close_active_trade()
            except Exception:
                pass
            ulta el resultado de una operación expirada al broker
        y actualiza el journal con WIN / LOSS / UNRESOLVED sin bloquear el bot.
        """
        if trade.resolved:
            return

        journal = get_journal()
        has_id  = bool(trade.order_id) and not trade.order_id.startswith("DRY-")
        has_ref = trade.order_ref > 0
        if self.dry_run:
            trade.resolved = True
            if self.trades.get(sym) is trade:
                self.trades.pop(sym, None)
            return

        outcome = "UNRESOLVED"
        profit  = 0.0
        close_price: Optional[float] = None
        result_payload: Optional[dict[str, Any]] = None
        if has_id or has_ref:
            for attempt in range(1, MARTIN_RESOLVE_MAX_ATTEMPTS + 1):
                try:
                    if has_ref:
                        win_val = await asyncio.wait_for(
                            self.client.check_win(trade.order_ref),
                            timeout=MARTIN_RESOLVE_TIMEOUT_SEC,
                        )
                        if isinstance(win_val, bool):
                            outcome = "WIN" if win_val else "LOSS"
                            profit = trade.amount * 0.8 if win_val else -abs(trade.amount)
                            break
                        if isinstance(win_val, (int, float)):
                            profit = float(win_val)
                            outcome = "WIN" if profit > 0 else "LOSS"
                            break
                    elif has_id:
                        status, payload = await asyncio.wait_for(
                            self.client.get_result(trade.order_id),
                            timeout=MARTIN_RESOLVE_TIMEOUT_SEC,
                        )
                        if isinstance(payload, dict):
                            result_payload = payload
                        if status == "win":
                            outcome = "WIN"
                            if isinstance(payload, dict):
                                profit = float(payload.get("profitAmount", 0) or 0)
                            break
                        if status == "loss":
                            outcome = "LOSS"
                            if isinstance(payload, dict):
                                profit = float(payload.get("profitAmount", 0) or 0)
                            if profit == 0:
                                profit = -abs(trade.amount)
                            break
                except asyncio.TimeoutError:
                    log.debug("%s: check_win timeout intento %d/%d", sym, attempt, MARTIN_RESOLVE_MAX_ATTEMPTS)
                except Exception as exc:
                    log.debug(
                        "No se pudo obtener resultado de %s / ref=%s intento %d/%d: %s",
                        trade.order_id,
                        trade.order_ref,
                        attempt,
                        MARTIN_RESOLVE_MAX_ATTEMPTS,
                        exc,
                    )

                if attempt < MARTIN_RESOLVE_MAX_ATTEMPTS:
                    await asyncio.sleep(MARTIN_RESOLVE_RETRY_SEC)

        if isinstance(result_payload, dict):
            for key in ("closePrice", "close_price", "close", "sellPrice"):
                if key in result_payload and result_payload.get(key) is not None:
                    try:
                        close_price = float(result_payload.get(key))
                        break
                    except Exception:
                        pass
        if close_price is None:
            try:
                close_price = await self._get_current_price(sym)
            except Exception:
                close_price = None

        trade.resolved = True

        if trade.journal_id:
            journal.update_outcome_by_id(row_id=trade.journal_id, outcome=outcome, profit=profit)
        else:
            journal.update_outcome(order_id=trade.order_id, outcome=outcome, profit=profit)

        pre_objectives, pre_ok, pre_note = self._build_pre_objectives_audit(trade)
        ticket_opened_at = datetime.fromtimestamp(trade.opened_at, tz=BROKER_TZ).isoformat(timespec="milliseconds")
        ticket_closed_at = datetime.now(tz=BROKER_TZ).isoformat(timespec="milliseconds")
        ticket_diff = None
        if close_price is not None:
            ticket_diff = float(close_price) - float(trade.entry_price)

        journal.update_ticket_details(
            row_id=trade.journal_id if trade.journal_id else None,
            order_id=trade.order_id if not trade.journal_id else "",
            order_ref=int(trade.order_ref or 0),
            strategy_origin=trade.strategy_origin,
            open_price=float(trade.entry_price),
            close_price=float(close_price) if close_price is not None else None,
            opened_at=ticket_opened_at,
            closed_at=ticket_closed_at,
            duration_sec=int(trade.duration_sec),
            price_diff=ticket_diff,
            pre_objectives=pre_objectives,
            pre_objectives_ok=pre_ok,
            pre_objectives_note=pre_note,
        )
        await self.refresh_balance_and_risk()
        balance_now = self.current_balance if self.current_balance is not None else 0.0
        log.info("🏁 %s %s $%.2f | saldo: $%.2f", sym, outcome, profit, balance_now)
        self._update_cycle_after_result(outcome=outcome, profit=profit)

        if outcome == "WIN":
            if trade.strategy_origin == "STRAT-B":
                self.stats["strat_b_wins"] += 1
            else:
                self.stats["strat_a_wins"] += 1
            if trade.stage == "martin":
                self.stats["martin_wins"] += 1
        elif outcome == "LOSS":
            if trade.strategy_origin == "STRAT-B":
                self.stats["strat_b_losses"] += 1
            else:
                self.stats["strat_a_losses"] += 1
            if trade.stage == "martin":
                self.stats["martin_losses"] += 1

        self._register_asset_outcome(sym, outcome)
        self.compensation_pending = False
        self.last_closed_amount = float(trade.amount)
        self.last_closed_outcome = outcome
        self.pending_martin.pop(sym, None)
        if self.trades.get(sym) is trade:
            self.trades.pop(sym, None)
        try:
            self.hub.record_trade_result(sym, outcome, profit)
            self.hub.close_active_trade()
        except Exception:
            pass

        # Avisar si hay candidatos vigilados listos para considerar en el próximo escaneo.
        if self.watched_candidates:
            now_ts = time.time()
            freshness_sec = 300  # solo mostrar si se detectaron en los últimos 5 min
            still_fresh = {
                a: (c, ts) for a, (c, ts) in self.watched_candidates.items()
                if (now_ts - ts) <= freshness_sec
            }
            if still_fresh:
                names = ", ".join(
                    f"{a}({c.direction.upper()} score={c.score:.1f})"
                    for a, (c, _) in still_fresh.items()
                )
                log.info(
                    "🎯 Trade cerrado — candidatos vigilados disponibles: %s — "
                    "el próximo escaneo evaluará entrar.",
                    names,
                )
            else:
                self.watched_candidates.clear()
                log.info("🎯 Trade cerrado — candidatos vigilados vencidos, se descartaron.")

    async def _check_martin(self, sym: str) -> bool:
        """
        Fallback liviano: limpia trades ya resueltos o dispara resolución si
        la tarea en background no lo hizo.
        """
        trade = self.open_trades_get(sym)
        if trade is None:
            return False

        if trade.resolved:
            if self.trades.get(sym) is trade:
                self.trades.pop(sym, None)
            return False

        elapsed = time.time() - trade.opened_at

        if elapsed > (trade.duration_sec + MARTIN_RESOLVE_GRACE_SEC + 15.0):
            await self._resolve_trade(trade, sym)

        return False

    def open_trades_get(self, sym: str) -> Optional[TradeState]:
        return self.trades.get(sym)

    # ── helpers para GaleWatcher ──────────────────────────────────────────────

    async def _gale_place_order(
        self,
        asset: str,
        direction: str,
        amount: float,
        duration: int,
        account_type: str = "PRACTICE",
    ) -> tuple:
        """Wrapper de place_order() para el GaleWatcher."""
        return await place_order(
            self.client,
            asset,
            direction,
            amount,
            duration,
            self.dry_run,
            account_type=account_type,
        )

    async def _gale_get_balance(self) -> float:
        """Retorna el balance actual para el GaleWatcher."""
        if self.current_balance is not None:
            return self.current_balance
        try:
            bal = float(await self.client.get_balance())
            self.current_balance = bal
            return bal
        except Exception:
            return 0.0

    async def _enter(
        self, sym: str, direction: str, amount: float,
        zone: ConsolidationZone, reason: str, stage: str,
        journal_cid: int = 0,
        signal_ts: Optional[int] = None,
        strategy_origin: str = "STRAT-A",
        duration_sec: int = DURATION_SEC,
        payout: int = MIN_PAYOUT,
        score_original: float = 0.0,
    ) -> bool:
        if stage == "martin":
            if not self._martin_session_available():
                return False
            self.stats["martin_attempts_session"] += 1

        can_enter_asset, same_asset_reason = self._can_enter_asset_now(sym, stage)
        if not can_enter_asset:
            self.stats["rejected_same_asset_limit"] += 1
            if "cooldown mismo activo" in same_asset_reason:
                self.stats["rejected_same_asset_cooldown"] += 1
            log.info("⏭ %s: entrada bloqueada — %s", sym, same_asset_reason)
            if journal_cid:
                _j = get_journal()
                if _j._conn is not None:
                    _j._conn.execute(
                        """UPDATE candidates
                           SET decision='REJECTED_LIMIT',
                               reject_reason=?,
                               outcome='LIMIT_SKIPPED'
                           WHERE id=?""",
                        (same_asset_reason, journal_cid),
                    )
                    _j._conn.commit()
            return False

        can_enter_structure, structure_reason = self._can_enter_structure_now(sym, zone)
        if not can_enter_structure:
            self.stats["rejected_same_structure"] += 1
            log.info("⏭ %s: entrada bloqueada — %s", sym, structure_reason)
            if journal_cid:
                _j = get_journal()
                if _j._conn is not None:
                    _j._conn.execute(
                        """UPDATE candidates
                           SET decision='REJECTED_STRUCTURE',
                               reject_reason=?,
                               outcome='STRUCTURE_SKIPPED'
                           WHERE id=?""",
                        (structure_reason, journal_cid),
                    )
                    _j._conn.commit()
            return False

        timing: Optional[EntryTimingInfo] = None
        if stage in ("initial", "martin"):
            timing = await self._sync_to_next_candle_open(signal_ts, asset=sym)
        else:
            timing = self._snapshot_current_candle_timing(asset=sym)

        if journal_cid and timing is not None:
            _j = get_journal()
            if _j._conn is not None:
                _j.log_entry_timing(
                    candidate_id=journal_cid,
                    time_since_open=timing.time_since_open_sec,
                    secs_to_close=timing.secs_to_close_sec,
                    duration_sec=timing.duration_sec,
                    timing_decision=timing.decision,
                )

        if stage in ("initial", "martin"):
            if not timing.ok:
                if journal_cid:
                    reject_reason = f"timing 1m inválido: lag +{timing.lag_sec:.2f}s"
                    _j = get_journal()
                    if _j._conn is not None:
                        _j._conn.execute(
                            """UPDATE candidates
                               SET decision='REJECTED_TIMING',
                                   reject_reason=?,
                                   outcome='TIMING_SKIPPED'
                               WHERE id=?""",
                            (reject_reason, journal_cid),
                        )
                        _j._conn.commit()
                return False
            duration_sec = timing.duration_sec

        payout_now = await self._get_asset_payout(sym, payout)
        if payout_now < MIN_PAYOUT:
            reject_reason = (
                f"payout actual insuficiente: {payout_now}% < mínimo {MIN_PAYOUT}%"
            )
            log.warning("⏭ %s: orden bloqueada — %s", sym, reject_reason)
            if journal_cid:
                _j = get_journal()
                if _j._conn is not None:
                    _j._conn.execute(
                        """UPDATE candidates
                           SET decision='REJECTED_PAYOUT',
                               reject_reason=?,
                               outcome='PAYOUT_SKIPPED'
                           WHERE id=?""",
                        (reject_reason, journal_cid),
                    )
                    _j._conn.commit()
            return False

        payout = int(payout_now)

        icon = "🟢" if direction == "call" else "🔴"
        log.info("[%s] %s ENTRADA[%s] %s  %s  $%.2f  %ds  | %s",
                 strategy_origin, icon, stage, direction.upper(), sym, amount, duration_sec, reason)

        ok, oid, open_price, order_ref, reject_reason = await place_order(
            self.client,
            sym,
            direction,
            amount,
            duration_sec,
            self.dry_run,
            account_type=self.account_type,
        )
        if not ok:
            log.error("  ✗ Fallo al colocar orden en %s | reason=%s", sym, reject_reason)
            # Marcar activo para skip durante 2 ciclos consecutivos.
            self.failed_assets[sym] = 2
            # Marcar en el journal que la orden fue rechazada por el broker
            if journal_cid:
                _j = get_journal()
                if _j._conn is not None:
                    _j._conn.execute(
                        "UPDATE candidates SET outcome='BROKER_REJECTED', reject_reason=? WHERE id=?",
                        (reject_reason[:500] if reject_reason else "broker_rejected", journal_cid)
                    )
                    _j._conn.commit()
            return False

        self._register_successful_entry_asset(sym, zone)

        self.trades[sym] = TradeState(
            asset=sym, direction=direction, amount=amount,
            entry_price=open_price, ceiling=zone.ceiling, floor=zone.floor,
            order_id=oid, order_ref=order_ref, stage=stage,
            journal_id=journal_cid,
            strategy_origin=strategy_origin,
            duration_sec=int(duration_sec),
            payout=int(payout),
            score_original=float(score_original),
        )
        trade = self.trades[sym]
        try:
            self.hub.record_entry(
                strategy=strategy_origin,
                asset=sym,
                direction=direction,
                duration_sec=int(duration_sec),
                entry_price=open_price,
            )
        except Exception as exc:
            log.debug("HUB: no se pudo registrar entrada activa %s: %s", sym, exc)
        self._track_task(asyncio.create_task(self._resolve_trade_after_expiry(sym, trade), name=f"resolve:{sym}:{stage}"))
        # Actualizar el journal con el order_id real del broker (aunque sea vacío)
        if journal_cid:
            stored_oid = oid if oid else f"REF-{order_ref}" if order_ref else "BROKER_NO_ID"
            _j = get_journal()
            if _j._conn is not None:
                _j._conn.execute(
                    "UPDATE candidates SET order_id=? WHERE id=?",
                    (stored_oid, journal_cid)
                )
                _j._conn.commit()
                _j.update_ticket_details(
                    row_id=journal_cid,
                    order_ref=int(order_ref or 0),
                    strategy_origin=strategy_origin,
                    open_price=float(open_price or 0.0),
                    opened_at=datetime.fromtimestamp(trade.opened_at, tz=BROKER_TZ).isoformat(timespec="milliseconds"),
                    duration_sec=int(duration_sec),
                )

        self.stats["entries"] += 1
        if strategy_origin == "STRAT-B":
            self.stats["strat_b_signals"] += 1
        else:
            self.stats["strat_a_signals"] += 1

        # ── Lanzar GaleWatcher en background (solo para entradas iniciales) ──
        if stage not in ("martin",) and self._gale_watcher is not None:
            gale_info = GaleTradeInfo(
                asset=sym,
                direction=direction,
                amount=amount,
                entry_price=float(open_price or 0.0),
                opened_at=trade.opened_at,
                duration_sec=int(duration_sec),
                payout=int(payout),
                order_id=str(oid or ""),
                order_ref=int(order_ref or 0),
                account_type=self.account_type,
            )
            _gale_task = asyncio.create_task(
                self._gale_watcher.watch(gale_info),
                name=f"gale_watch:{sym}:{stage}",
            )
            self._gale_tasks.add(_gale_task)
            _gale_task.add_done_callback(self._gale_tasks.discard)

        if oid:
            log.info("  ✓ Orden aceptada  id=%s  open=%.5f  ref=%s", oid, open_price, order_ref)
        else:
            log.warning("  ⚠ Orden enviada pero broker NO devolvió id  open=%.5f  ref=%s", open_price, order_ref)
        try:
            bal = await self.client.get_balance()
            log.info("  💰 Balance: %.2f USD", bal)
        except asyncio.CancelledError:
            log.info("Interrupción durante lectura de balance; continuando cierre limpio.")
            return True
        except Exception:
            pass
        return True

    def log_stats(self) -> None:
        risk_txt = ""
        if self.session_start_balance and self.current_balance:
            dd = (self.session_start_balance - self.current_balance) / self.session_start_balance
            risk_txt = f"  Drawdown:{dd*100:.1f}%"
        cycle_txt = (
            f"  Ciclo#{self.cycle_id} {self.cycle_wins}W/{self.cycle_losses}L "
            f"ops:{self.cycle_ops}/{CYCLE_MAX_OPERATIONS}"
        )
        log.info(
            "📊 STATS | Scans:%d  Entradas:%d  Martingalas:%d  "
            "Zonas expiradas:%d  Sin señal:%d  Sensor filtradas:%d%s%s  [A]:%dW/%dL  [B]:%dW/%dL",
            self.stats["scans"], self.stats["entries"], self.stats["martins"],
            self.stats["expired_zones"], self.stats["skipped"], self.stats["filtered_sensor"],
            risk_txt,
            cycle_txt,
            self.stats["strat_a_wins"], self.stats["strat_a_losses"],
            self.stats["strat_b_wins"], self.stats["strat_b_losses"],
        )
        log.info(
            "📊 MARTIN | Sesión:%d/%d  Wins:%d  Losses:%d",
            self.stats.get("martin_attempts_session", 0),
            self._current_martin_attempt_limit(),
            self.stats.get("martin_wins", 0),
            self.stats.get("martin_losses", 0),
        )
        rej_age   = self.stats.get("score_rejected_age", 0)
        rej_score = self.stats.get("score_rejected_score", 0)
        rej_young = self.stats.get("rejected_young_zone", 0)
        if rej_age or rej_score or rej_young:
            log.info(
                "📊 RECHAZOS | Por antigüedad zona (>120min):%d  Por score<umbral:%d  Por zona joven (<%dmin):%d",
                rej_age,
                rej_score,
                ZONE_MIN_AGE_MIN,
                rej_young,
            )


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════════
async def sleep_with_inline_countdown(wait_seconds: float, label: str) -> None:
    """
    Espera mostrando un contador en la MISMA línea del terminal.
    Útil para no inundar el log con una línea nueva por segundo.
    """
    total = max(0.0, float(wait_seconds))
    if total <= 0.0:
        return

    end_at = time.monotonic() + total
    last_logged_sec: Optional[int] = None
    try:
        while True:
            remaining = max(0.0, end_at - time.monotonic())
            rem_sec = int(remaining + 0.999)
            if rem_sec >= 60:
                t_str = f"{rem_sec // 60}m{rem_sec % 60:02d}s"
            else:
                t_str = f"{rem_sec:>3d}s"
            sys.stdout.write(f"\r[INFO] {label} en {t_str}   ")
            sys.stdout.flush()

            # Fallback visible en logs: cada 10s y cuenta final 5..1.
            # En algunas consolas de Windows el \r inline no se aprecia estable.
            if rem_sec != last_logged_sec and (rem_sec % 10 == 0 or rem_sec <= 5):
                log.info("⏳ %s en %s", label, t_str.strip())
                last_logged_sec = rem_sec

            if remaining <= 0.0:
                break
            await asyncio.sleep(min(1.0, remaining))
    finally:
        # Limpiar la línea dinámica y dejar una línea nueva limpia para logs.
        sys.stdout.write("\r" + (" " * 100) + "\r\n")
        sys.stdout.flush()


def seconds_until_next_scan(now_ts: Optional[float] = None) -> float:
    """Calcula segundos hasta el próximo scan alineado a vela de 5m."""
    if LIVE_SCAN_MODE:
        return max(0.5, float(LIVE_SCAN_SLEEP_SEC))

    now = time.time() if now_ts is None else float(now_ts)
    if ALIGN_SCAN_TO_CANDLE:
        next_open = ((int(now) // TF_5M) + 1) * TF_5M
        target_scan = next_open - SCAN_LEAD_SEC
        if target_scan <= now:
            target_scan += TF_5M
        return max(1.0, target_scan - now)
    return max(5.0, SCAN_INTERVAL_SEC)


async def connect_with_retry(client: Quotex) -> Tuple[bool, str]:
    """Conecta con backoff especial para bloqueos transitorios 403/Cloudflare."""
    reason = ""
    for attempt in range(1, CONNECT_RETRIES + 1):
        ok, reason = await client.connect()
        if ok:
            return True, ""

        reason_txt = str(reason)
        if "403" in reason_txt or "cloudflare" in reason_txt.lower() or "cf-mitigated" in reason_txt.lower():
            log.warning(
                "☁️ Challenge 403 detectado (%d/%d). Esperando %.1fs antes de reintentar.",
                attempt,
                CONNECT_RETRIES,
                CF_403_BACKOFF_SEC,
            )
            _clear_quotex_session(client)
            await asyncio.sleep(CF_403_BACKOFF_SEC)
        else:
            await asyncio.sleep(1.5)
    return False, str(reason)


async def main(
    dry_run: bool,
    real_account: bool,
    loop_forever: bool,
    greylist_assets: Optional[set[str]] = None,
    on_cycle_end: Optional[Any] = None,
    on_bot_ready: Optional[Any] = None,
) -> Optional[ConsolidationBot]:
    if not EMAIL or not PASSWORD:
        print("ERROR: Falta QUOTEX_EMAIL / QUOTEX_PASSWORD en el .env")
        sys.exit(1)

    client = Quotex(email=EMAIL, password=PASSWORD)

    log.info("╔══════════════════════════════════════════════╗")
    log.info("║      CONSOLIDATION BOT — Quotex              ║")
    log.info("║  Cuenta  : %-34s║", "REAL ⚠️" if real_account else "DEMO ✅")
    log.info("║  Modo    : %-34s║", "LIVE" if not dry_run else "DRY-RUN")
    log.info("║  Velas   : %-2d min  Rango: %.1f%%  Timeout: %dmin ║",
             MIN_CONSOLIDATION_BARS, MAX_RANGE_PCT * 100, MAX_CONSOLIDATION_MIN)
    log.info("║  Montos  : base + MG externo independiente     ║")
    log.info("║  Payout  : %d%%  |  Vol filtro: %.1fx avg body ║",
             MIN_PAYOUT, VOLUME_MULTIPLIER)
    log.info("╚══════════════════════════════════════════════╝")

    # Conexión con reintentos + backoff especial para Cloudflare 403.
    check, reason = await connect_with_retry(client)
    
    if not check:
        log.critical("No se pudo conectar a Quotex: %s", reason)
        sys.exit(1)

    account_type = "REAL" if real_account else "PRACTICE"
    await client.change_account(account_type)

    start_balance: Optional[float] = None
    try:
        bal = await client.get_balance()
        start_balance = float(bal)
        log.info("✅ Conectado | Balance %s: %.2f USD", account_type, bal)
    except Exception as exc:
        log.warning("No se pudo leer balance: %s", exc)

    bot = ConsolidationBot(
        client=client,
        dry_run=dry_run,
        account_type=account_type,
        greylist_assets=greylist_assets,
    )
    if start_balance is not None:
        bot.set_session_start_balance(start_balance)

    # Notificar que el bot ya existe y tiene balance (antes del primer scan).
    if on_bot_ready is not None:
        try:
            result = on_bot_ready(bot)
            if asyncio.iscoroutine(result):
                await result
        except Exception:
            pass

    # Reconciliar pendientes históricos al arrancar para limpiar métricas.
    await bot.reconcile_pending_candidates()

    try:
        # Alinear también el PRIMER escaneo al reloj de vela para evitar señales
        # fuera de ventana al iniciar el bot en un segundo arbitrario.
        if loop_forever and ALIGN_SCAN_TO_CANDLE and not LIVE_SCAN_MODE:
            first_wait = seconds_until_next_scan(time.time())
            await sleep_with_inline_countdown(first_wait, "Sincronizando primer escaneo")
            log.info("Sincronización completada. Iniciando escaneo.")

        while True:
            cycle_start = time.time()
            broker_now = datetime.fromtimestamp(time.time(), tz=BROKER_TZ)
            log.info("── %s %s ──", broker_now.strftime("%H:%M:%S"), BROKER_TZ_LABEL)

            try:
                if loop_forever and not await bot.ensure_connection():
                    log.warning("⚠ Sin conexión estable, reintentando en 5s...")
                    await asyncio.sleep(5.0)
                    continue
                await bot.scan_all()
                await bot.reconcile_pending_candidates(max_age_minutes=PENDING_RECONCILE_AGE_MIN)
                if bot.session_stop_hit:
                    log.error("🛑 Bot detenido por stop-loss de sesión.")
                    break
            except asyncio.CancelledError:
                log.info("Ciclo cancelado por interrupción del usuario.")
                break
            except Exception as exc:
                log.error("Error en ciclo: %s", exc, exc_info=True)
                if looks_like_connection_issue(str(exc)):
                    log.warning("⚠ Error de conexión en ciclo; intentando reconectar inmediatamente...")
                    if not await bot.ensure_connection():
                        log.warning("⚠ Reconexión inmediata fallida; se reintentará en el siguiente ciclo.")

            bot.log_stats()

            if on_cycle_end is not None:
                try:
                    callback_result = on_cycle_end(bot)
                    if asyncio.iscoroutine(callback_result):
                        await callback_result
                except Exception as exc:
                    log.debug("HUB callback error: %s", exc)

            if not loop_forever:
                log.info("Ciclo único completado. Agrega --loop para modo 24/7.")
                break

            if LIVE_SCAN_MODE:
                sleep_for = max(0.5, float(LIVE_SCAN_SLEEP_SEC))
            elif ALIGN_SCAN_TO_CANDLE:
                sleep_for = seconds_until_next_scan(time.time())
            else:
                elapsed = time.time() - cycle_start
                sleep_for = max(5.0, SCAN_INTERVAL_SEC - elapsed)

            try:
                if LIVE_SCAN_MODE:
                    await asyncio.sleep(sleep_for)
                else:
                    await sleep_with_inline_countdown(sleep_for, "Próximo escaneo")
            except asyncio.CancelledError:
                log.info("Loop cancelado por interrupción del usuario.")
                break

    except KeyboardInterrupt:
        log.info("Detenido por el usuario (Ctrl+C).")
    finally:
        try:
            await asyncio.wait_for(bot.shutdown_background_tasks(), timeout=3.0)
        except Exception:
            pass
        try:
            await asyncio.wait_for(client.close(), timeout=3.0)
        except Exception:
            pass
        log.info("Bot detenido.")
        return bot


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Consolidation Bot — rango + martingala Quotex",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--live", action="store_true",
                   help="Enviar órdenes reales (sin esto: dry-run)")
    p.add_argument("--real", action="store_true",
                   help="⚠️ Operar en cuenta REAL (por defecto: DEMO)")
    p.add_argument("--loop", action="store_true",
                   help="Modo 24/7 (sin esto: un solo ciclo de análisis)")
    p.add_argument(
        "--greylist",
        type=str,
        default=",".join(sorted(GREYLIST_ASSETS)),
        help="Activos OTC separados por coma para omitir en scan_all",
    )
    p.add_argument(
        "--pattern-put-blacklist",
        type=str,
        default=",".join(sorted(PATTERN_PUT_BLACKLIST)),
        help="Patrones 1m separados por coma bloqueados como disparador de orden PUT",
    )
    p.add_argument(
        "--scan-top-n",
        type=int,
        default=SCAN_MAX_ASSETS_PER_CYCLE,
        help="Cantidad máxima de activos por ciclo, manteniendo orden por payout descendente",
    )
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    parsed_greylist = {
        token.strip()
        for token in (args.greylist or "").split(",")
        if token.strip()
    }
    parsed_pattern_put_blacklist = {
        token.strip()
        for token in (args.pattern_put_blacklist or "").split(",")
        if token.strip()
    }
    SCAN_MAX_ASSETS_PER_CYCLE = max(0, int(args.scan_top_n))
    PATTERN_PUT_BLACKLIST = parsed_pattern_put_blacklist
    try:
        asyncio.run(main(
            dry_run      = not args.live,
            real_account = args.real,
            loop_forever = args.loop,
            greylist_assets=parsed_greylist,
        ))
    except KeyboardInterrupt:
        # Evita traceback al interrumpir con Ctrl+C.
        raise SystemExit(0)
