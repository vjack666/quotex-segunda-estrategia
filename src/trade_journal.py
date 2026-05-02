"""
trade_journal.py — Módulo de aprendizaje y registro histórico de trades
=========================================================================
Registra en SQLite CADA candidato evaluado por el bot:

  · Los que se ACEPTARON (y el resultado: WIN / LOSS / PENDIENTE)
  · Los que se RECHAZARON (y por qué: score bajo, límite concurrente, cooldown…)
  · Las velas usadas para el análisis (últimas 20 guardadas en JSON)
  · El desglose completo del score (compression, bounce, trend, payout)

Base de datos: trade_journal.db  (en la raíz del proyecto)

TABLAS
──────
  candidates  — cada señal evaluada (aceptada o rechazada)
  outcomes    — resultado de cada orden colocada (se actualiza post-trade)

USO RÁPIDO
──────────
  from trade_journal import Journal

  journal = Journal()                       # abre / crea la BD

  # Registrar candidato rechazado
  cid = journal.log_candidate(entry, decision="REJECTED_SCORE",
                               reject_reason="score=58.3 < umbral 70")

  # Registrar candidato aceptado
  cid = journal.log_candidate(entry, decision="ACCEPTED",
                               order_id="abc123", amount=1.0)

  # Actualizar resultado cuando el broker lo confirma
  journal.update_outcome(order_id="abc123", outcome="WIN", profit=0.85)

  # Reporte de rendimiento
  journal.print_report()

REPORTE POR CONSOLA
───────────────────
  python -m trade_journal          ← reporte completo
  python -m trade_journal 7        ← últimos 7 días
"""
from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from entry_scorer import CandidateEntry


# ── Ruta a la BD ──────────────────────────────────────────────────────────────
_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
_DB_DIR = _ROOT / "data" / "db"
_DB_DIR.mkdir(parents=True, exist_ok=True)
_DB_DATE = datetime.now().strftime("%Y-%m-%d")
DB_PATH = _DB_DIR / f"trade_journal-{_DB_DATE}.db"
BROKER_TZ = timezone(timedelta(hours=-3))


# ─────────────────────────────────────────────────────────────────────────────
#  DDL — creación de tablas
# ─────────────────────────────────────────────────────────────────────────────
_DDL = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS candidates (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    scanned_at       TEXT NOT NULL,          -- ISO UTC del momento del escaneo
    asset            TEXT NOT NULL,
    direction        TEXT NOT NULL,          -- call | put
    payout           INTEGER,
    amount           REAL,
    stage            TEXT,                   -- initial | martin_break | martin

    -- Score global y componentes
    score            REAL,
    score_compression REAL,
    score_bounce     REAL,
    score_trend      REAL,
    score_payout     REAL,
    reversal_pattern TEXT DEFAULT 'none',
    reversal_strength REAL DEFAULT 0.0,

    -- Zona de consolidación
    zone_ceiling     REAL,
    zone_floor       REAL,
    zone_range_pct   REAL,
    zone_bars_inside INTEGER,
    zone_age_min     REAL,

    -- Decisión
    decision         TEXT NOT NULL,          -- ACCEPTED | REJECTED_SCORE |
                                             -- REJECTED_LIMIT | REJECTED_COOLDOWN
    reject_reason    TEXT,                   -- detalle si fue rechazado

    -- Orden (si fue aceptado)
    order_id         TEXT,
    outcome          TEXT DEFAULT 'PENDING', -- WIN | LOSS | PENDING | DRY_RUN
    profit           REAL DEFAULT 0.0,
    closed_at        TEXT,
    order_ref        INTEGER DEFAULT 0,
    strategy_origin  TEXT DEFAULT 'STRAT-A',
    ticket_open_price REAL,
    ticket_close_price REAL,
    ticket_opened_at TEXT,
    ticket_closed_at TEXT,
    ticket_duration_sec INTEGER,
    ticket_price_diff REAL,
    pre_objectives_json TEXT,
    pre_objectives_ok INTEGER,
    pre_objectives_note TEXT,

    -- Velas (JSON) para reproducir el análisis después
    candles_json     TEXT,

    -- Snapshot de estrategia para auditoría/replay
    strategy_json    TEXT,

    -- Auditoría dinámica de timing de entrada (caja negra)
    entry_time_since_open REAL,
    entry_secs_to_close REAL,
    entry_duration_sec INTEGER,
    entry_timing_decision TEXT
);

CREATE TABLE IF NOT EXISTS scan_sessions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at    TEXT NOT NULL,
    ended_at      TEXT,
    total_assets  INTEGER DEFAULT 0,
    total_candidates INTEGER DEFAULT 0,
    total_accepted   INTEGER DEFAULT 0,
    dry_run       INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_candidates_asset    ON candidates(asset);
CREATE INDEX IF NOT EXISTS idx_candidates_decision ON candidates(decision);
CREATE INDEX IF NOT EXISTS idx_candidates_order_id ON candidates(order_id);
CREATE INDEX IF NOT EXISTS idx_candidates_scanned  ON candidates(scanned_at);

CREATE TABLE IF NOT EXISTS expired_zones (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    expired_at      TEXT NOT NULL,       -- ISO hora de expiración (UTC-3)
    asset           TEXT NOT NULL,
    expiry_reason   TEXT NOT NULL,       -- TIME_LIMIT | BROKEN_ABOVE | BROKEN_BELOW
    ceiling         REAL NOT NULL,
    floor           REAL NOT NULL,
    range_pct       REAL,
    bars_inside     INTEGER,
    age_min         REAL,               -- minutos que vivió la zona
    last_close      REAL,               -- precio de cierre al expirar
    break_body      REAL DEFAULT NULL,  -- tamaño cuerpo vela ruptura (si aplica)
    payout          INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_expired_zones_asset  ON expired_zones(asset);
CREATE INDEX IF NOT EXISTS idx_expired_zones_reason ON expired_zones(expiry_reason);
"""


# ─────────────────────────────────────────────────────────────────────────────
#  Journal
# ─────────────────────────────────────────────────────────────────────────────
class Journal:
    """Interfaz principal del módulo de aprendizaje."""

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        self._open()

    # ── Conexión ──────────────────────────────────────────────────────────────
    def _open(self) -> None:
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_DDL)
        self._ensure_schema_upgrades()
        self._conn.commit()

    def _ensure_schema_upgrades(self) -> None:
        """Aplica migraciones suaves para bases existentes."""
        rows = self._conn.execute("PRAGMA table_info(candidates)").fetchall()
        cols = {r[1] for r in rows}
        if "strategy_json" not in cols:
            self._conn.execute("ALTER TABLE candidates ADD COLUMN strategy_json TEXT")
        if "reversal_pattern" not in cols:
            self._conn.execute("ALTER TABLE candidates ADD COLUMN reversal_pattern TEXT DEFAULT 'none'")
        if "reversal_strength" not in cols:
            self._conn.execute("ALTER TABLE candidates ADD COLUMN reversal_strength REAL DEFAULT 0.0")
        if "entry_time_since_open" not in cols:
            self._conn.execute("ALTER TABLE candidates ADD COLUMN entry_time_since_open REAL")
        if "entry_secs_to_close" not in cols:
            self._conn.execute("ALTER TABLE candidates ADD COLUMN entry_secs_to_close REAL")
        if "entry_duration_sec" not in cols:
            self._conn.execute("ALTER TABLE candidates ADD COLUMN entry_duration_sec INTEGER")
        if "entry_timing_decision" not in cols:
            self._conn.execute("ALTER TABLE candidates ADD COLUMN entry_timing_decision TEXT")
        if "order_ref" not in cols:
            self._conn.execute("ALTER TABLE candidates ADD COLUMN order_ref INTEGER DEFAULT 0")
        if "strategy_origin" not in cols:
            self._conn.execute("ALTER TABLE candidates ADD COLUMN strategy_origin TEXT DEFAULT 'STRAT-A'")
        if "ticket_open_price" not in cols:
            self._conn.execute("ALTER TABLE candidates ADD COLUMN ticket_open_price REAL")
        if "ticket_close_price" not in cols:
            self._conn.execute("ALTER TABLE candidates ADD COLUMN ticket_close_price REAL")
        if "ticket_opened_at" not in cols:
            self._conn.execute("ALTER TABLE candidates ADD COLUMN ticket_opened_at TEXT")
        if "ticket_closed_at" not in cols:
            self._conn.execute("ALTER TABLE candidates ADD COLUMN ticket_closed_at TEXT")
        if "ticket_duration_sec" not in cols:
            self._conn.execute("ALTER TABLE candidates ADD COLUMN ticket_duration_sec INTEGER")
        if "ticket_price_diff" not in cols:
            self._conn.execute("ALTER TABLE candidates ADD COLUMN ticket_price_diff REAL")
        if "pre_objectives_json" not in cols:
            self._conn.execute("ALTER TABLE candidates ADD COLUMN pre_objectives_json TEXT")
        if "pre_objectives_ok" not in cols:
            self._conn.execute("ALTER TABLE candidates ADD COLUMN pre_objectives_ok INTEGER")
        if "pre_objectives_note" not in cols:
            self._conn.execute("ALTER TABLE candidates ADD COLUMN pre_objectives_note TEXT")
        # Migración: tabla expired_zones (bases anteriores sin ella)
        self._conn.executescript(
            "CREATE TABLE IF NOT EXISTS expired_zones ("
            "    id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "    expired_at TEXT NOT NULL,"
            "    asset TEXT NOT NULL,"
            "    expiry_reason TEXT NOT NULL,"
            "    ceiling REAL NOT NULL,"
            "    floor REAL NOT NULL,"
            "    range_pct REAL,"
            "    bars_inside INTEGER,"
            "    age_min REAL,"
            "    last_close REAL,"
            "    break_body REAL DEFAULT NULL,"
            "    payout INTEGER DEFAULT 0"
            ");"
            "CREATE INDEX IF NOT EXISTS idx_expired_zones_asset  ON expired_zones(asset);"
            "CREATE INDEX IF NOT EXISTS idx_expired_zones_reason ON expired_zones(expiry_reason);"
        )

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    # ── Sesión de escaneo ─────────────────────────────────────────────────────
    def start_session(self, dry_run: bool = False) -> int:
        """Crea un registro de sesión y devuelve su id."""
        now = _now()
        cur = self._conn.execute(
            "INSERT INTO scan_sessions (started_at, dry_run) VALUES (?, ?)",
            (now, int(dry_run)),
        )
        self._conn.commit()
        return cur.lastrowid

    def log_entry_timing(
        self,
        candidate_id: int,
        time_since_open: float,
        secs_to_close: float,
        duration_sec: int,
        timing_decision: str,
    ) -> None:
        """Actualiza auditoría de timing para un candidato ya registrado."""
        self._conn.execute(
            """UPDATE candidates
               SET entry_time_since_open=?,
                   entry_secs_to_close=?,
                   entry_duration_sec=?,
                   entry_timing_decision=?
               WHERE id=?""",
            (
                float(time_since_open),
                float(secs_to_close),
                int(duration_sec),
                timing_decision,
                int(candidate_id),
            ),
        )
        self._conn.commit()

    def end_session(self, session_id: int, total_assets: int,
                    total_candidates: int, total_accepted: int) -> None:
        self._conn.execute(
            """UPDATE scan_sessions
               SET ended_at=?, total_assets=?, total_candidates=?, total_accepted=?
               WHERE id=?""",
            (_now(), total_assets, total_candidates, total_accepted, session_id),
        )
        self._conn.commit()

    # ── Registro de candidatos ────────────────────────────────────────────────
    def log_candidate(
        self,
        entry: "CandidateEntry",
        decision: str,
        reject_reason: str = "",
        order_id: str = "",
        amount: float = 0.0,
        stage: str = "initial",
        outcome: str = "PENDING",
        strategy: Optional[dict] = None,
    ) -> int:
        """
        Registra un candidato evaluado.

        decision debe ser uno de:
          ACCEPTED          — se envió orden
          REJECTED_SCORE    — score por debajo del umbral
          REJECTED_LIMIT    — límite de operaciones concurrentes alcanzado
          REJECTED_COOLDOWN — en período de cooldown
          REJECTED_NO_SIGNAL— sin señal válida (no era techo/piso)
        """
        bd = entry.score_breakdown
        strategy_payload = dict(strategy or {})
        strategy_payload["pattern_snapshot"] = {
            "stage": stage,
            "entry_mode": str(getattr(entry, "_entry_mode", "") or ""),
            "force_execute": bool(getattr(entry, "_force_execute", False)),
            "reversal_pattern": getattr(entry, "_reversal_pattern", getattr(entry, "reversal_pattern", "none")),
            "reversal_strength": float(getattr(entry, "_reversal_strength", getattr(entry, "reversal_strength", 0.0)) or 0.0),
            "reversal_confirms": bool(getattr(entry, "_reversal_confirms", getattr(entry, "reversal_confirms", False))),
            "signal_ts_1m": getattr(entry, "_signal_ts_1m", None),
            "order_block_info": str(getattr(entry, "_ob_info", "") or ""),
            "ma_info": str(getattr(entry, "_ma_info", "") or ""),
            "score_breakdown": dict(bd),
        }

        # Serializar velas (últimas 20 para no inflar la BD)
        candles_data = []
        for c in entry.candles[-20:]:
            candles_data.append({
                "ts": c.ts,
                "open": c.open,
                "high": c.high,
                "low": c.low,
                "close": c.close,
            })

        cur = self._conn.execute(
            """INSERT INTO candidates (
                scanned_at, asset, direction, payout, amount, stage,
                score, score_compression, score_bounce, score_trend, score_payout,
                reversal_pattern, reversal_strength,
                zone_ceiling, zone_floor, zone_range_pct, zone_bars_inside, zone_age_min,
                decision, reject_reason, order_id, outcome, candles_json, strategy_json
            ) VALUES (
                ?,?,?,?,?,?,
                ?,?,?,?,?,
                ?,?,
                ?,?,?,?,?,
                ?,?,?,?,?,?
            )""",
            (
                _now(),
                entry.asset, entry.direction, entry.payout, amount, stage,
                entry.score,
                bd.get("compression", 0.0),
                bd.get("bounce", 0.0),
                bd.get("trend", 0.0),
                bd.get("payout", 0.0),
                getattr(entry, "_reversal_pattern", getattr(entry, "reversal_pattern", "none")),
                float(getattr(entry, "_reversal_strength", getattr(entry, "reversal_strength", 0.0)) or 0.0),
                entry.zone.ceiling, entry.zone.floor,
                entry.zone.range_pct, entry.zone.bars_inside,
                entry.zone.age_minutes,
                decision, reject_reason, order_id, outcome,
                json.dumps(candles_data),
                json.dumps(strategy_payload, ensure_ascii=False),
            ),
        )
        self._conn.commit()
        return cur.lastrowid

    # ── Actualizar resultado ──────────────────────────────────────────────────
    # ── Registro de zonas expiradas ──────────────────────────────────────────
    def log_expired_zone(
        self,
        asset: str,
        expiry_reason: str,
        ceiling: float,
        floor: float,
        range_pct: float,
        bars_inside: int,
        age_min: float,
        last_close: float,
        break_body: Optional[float] = None,
        payout: int = 0,
    ) -> int:
        """
        Registra una zona que fue descartada.

        expiry_reason: TIME_LIMIT | BROKEN_ABOVE | BROKEN_BELOW
        """
        cur = self._conn.execute(
            """INSERT INTO expired_zones (
                expired_at, asset, expiry_reason,
                ceiling, floor, range_pct, bars_inside,
                age_min, last_close, break_body, payout
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                datetime.now(tz=BROKER_TZ).isoformat(),
                asset, expiry_reason,
                ceiling, floor, range_pct, bars_inside,
                age_min, last_close, break_body, payout,
            ),
        )
        self._conn.commit()
        return cur.lastrowid

    # ── Reporte de zonas expiradas ────────────────────────────────────────────
    def print_expired_zones(self, n: int = 40) -> None:
        """Muestra las últimas N zonas expiradas con diagnóstico."""
        rows = self._conn.execute(
            """SELECT expired_at, asset, expiry_reason,
                      ceiling, floor, range_pct, bars_inside,
                      age_min, last_close, break_body, payout
               FROM expired_zones
               ORDER BY id DESC LIMIT ?""",
            (n,),
        ).fetchall()

        print(f"\n{'═'*75}")
        print(f"  ZONAS EXPIRADAS — últimas {n}")
        print(f"{'═'*75}")
        if not rows:
            print("  Sin zonas registradas aún.")
            print(f"{'═'*75}\n")
            return

        reason_icon = {
            "TIME_LIMIT":     "⏱ ",
            "BROKEN_ABOVE":   "🔴",
            "BROKEN_BELOW":   "🟢",
        }
        print(f"  {'Hora':<19}  {'Activo':<22}  {'Razón':<15}  "
              f"{'Edad':>5}m  {'Rango':>6}%  {'Barras':>6}  {'Precio':>9}")
        print(f"  {'─'*70}")
        for r in rows:
            icon = reason_icon.get(r["expiry_reason"], "?  ")
            rng = (r["range_pct"] or 0.0) * 100
            extra = ""
            if r["expiry_reason"] in ("BROKEN_ABOVE", "BROKEN_BELOW") and r["break_body"]:
                extra = f"  cuerpo_ruptura={r['break_body']:.5f}"
            print(
                f"  {r['expired_at'][:19]}  {r['asset']:<22}  "
                f"{icon}{r['expiry_reason']:<13}  "
                f"{(r['age_min'] or 0):>5.1f}m  {rng:>6.3f}%  "
                f"{(r['bars_inside'] or 0):>6}  "
                f"{(r['last_close'] or 0):>9.5f}"
                f"{extra}"
            )

        # Resumen por razón
        summary = self._conn.execute(
            "SELECT expiry_reason, COUNT(*) AS n "
            "FROM expired_zones GROUP BY expiry_reason ORDER BY n DESC"
        ).fetchall()
        print(f"\n  {'RESUMEN POR CAUSA':─<45}")
        for s in summary:
            icon = reason_icon.get(s["expiry_reason"], "?  ")
            print(f"  {icon} {s['expiry_reason']:<15}  {s['n']:>4}x")
        print(f"{'═'*75}\n")

    def update_outcome(self, order_id: str, outcome: str, profit: float = 0.0) -> None:
        """
        Actualiza el resultado de una orden ya registrada.

        outcome: "WIN" | "LOSS" | "DRAW" | "EXPIRED"
        profit:  ganancia neta (positivo = ganó, negativo = perdió)
        """
        self._conn.execute(
            """UPDATE candidates
               SET outcome=?, profit=?, closed_at=?
               WHERE order_id=? AND outcome='PENDING'""",
            (outcome, profit, _now(), order_id),
        )
        self._conn.commit()

    def update_outcome_by_id(self, row_id: int, outcome: str, profit: float = 0.0) -> None:
        """
        Igual que update_outcome pero usando la clave primaria (id) de la fila.
        Útil cuando el broker devuelve order_id vacío pero tenemos el id interno.
        """
        self._conn.execute(
            """UPDATE candidates
               SET outcome=?, profit=?, closed_at=?
               WHERE id=? AND outcome='PENDING'""",
            (outcome, profit, _now(), row_id),
        )
        self._conn.commit()

    def update_ticket_details(
        self,
        *,
        row_id: Optional[int] = None,
        order_id: str = "",
        order_ref: int = 0,
        strategy_origin: str = "",
        open_price: Optional[float] = None,
        close_price: Optional[float] = None,
        opened_at: str = "",
        closed_at: str = "",
        duration_sec: Optional[int] = None,
        price_diff: Optional[float] = None,
        pre_objectives: Optional[dict] = None,
        pre_objectives_ok: Optional[bool] = None,
        pre_objectives_note: str = "",
    ) -> None:
        """Actualiza trazabilidad de ticket para una fila de candidato."""
        if row_id is None and not order_id:
            return

        payload_json = json.dumps(pre_objectives or {}, ensure_ascii=False) if pre_objectives is not None else None
        ok_val = None if pre_objectives_ok is None else int(bool(pre_objectives_ok))

        if row_id is not None:
            self._conn.execute(
                """UPDATE candidates
                   SET order_ref=COALESCE(NULLIF(?, 0), order_ref),
                       strategy_origin=COALESCE(NULLIF(?, ''), strategy_origin),
                       ticket_open_price=COALESCE(?, ticket_open_price),
                       ticket_close_price=COALESCE(?, ticket_close_price),
                       ticket_opened_at=COALESCE(NULLIF(?, ''), ticket_opened_at),
                       ticket_closed_at=COALESCE(NULLIF(?, ''), ticket_closed_at),
                       ticket_duration_sec=COALESCE(?, ticket_duration_sec),
                       ticket_price_diff=COALESCE(?, ticket_price_diff),
                       pre_objectives_json=COALESCE(?, pre_objectives_json),
                       pre_objectives_ok=COALESCE(?, pre_objectives_ok),
                       pre_objectives_note=COALESCE(NULLIF(?, ''), pre_objectives_note)
                   WHERE id=?""",
                (
                    int(order_ref),
                    strategy_origin,
                    open_price,
                    close_price,
                    opened_at,
                    closed_at,
                    int(duration_sec) if duration_sec is not None else None,
                    price_diff,
                    payload_json,
                    ok_val,
                    pre_objectives_note,
                    int(row_id),
                ),
            )
        else:
            self._conn.execute(
                """UPDATE candidates
                   SET order_ref=COALESCE(NULLIF(?, 0), order_ref),
                       strategy_origin=COALESCE(NULLIF(?, ''), strategy_origin),
                       ticket_open_price=COALESCE(?, ticket_open_price),
                       ticket_close_price=COALESCE(?, ticket_close_price),
                       ticket_opened_at=COALESCE(NULLIF(?, ''), ticket_opened_at),
                       ticket_closed_at=COALESCE(NULLIF(?, ''), ticket_closed_at),
                       ticket_duration_sec=COALESCE(?, ticket_duration_sec),
                       ticket_price_diff=COALESCE(?, ticket_price_diff),
                       pre_objectives_json=COALESCE(?, pre_objectives_json),
                       pre_objectives_ok=COALESCE(?, pre_objectives_ok),
                       pre_objectives_note=COALESCE(NULLIF(?, ''), pre_objectives_note)
                   WHERE order_id=?""",
                (
                    int(order_ref),
                    strategy_origin,
                    open_price,
                    close_price,
                    opened_at,
                    closed_at,
                    int(duration_sec) if duration_sec is not None else None,
                    price_diff,
                    payload_json,
                    ok_val,
                    pre_objectives_note,
                    order_id,
                ),
            )
        self._conn.commit()

    def print_ticket_audit(self, ticket_id: str) -> None:
        """Muestra detalle de ticket y comparación pre-ejecución."""
        def _fetch_row(conn: sqlite3.Connection):
            return conn.execute(
            """SELECT id, order_id, order_ref, asset, payout, direction, amount, stage,
                      strategy_origin, score, decision, outcome, profit,
                      ticket_open_price, ticket_close_price, ticket_opened_at,
                      ticket_closed_at, ticket_duration_sec, ticket_price_diff,
                      pre_objectives_ok, pre_objectives_note, pre_objectives_json,
                      strategy_json
               FROM candidates
               WHERE order_id=? OR id=?
               ORDER BY id DESC LIMIT 1""",
                (ticket_id, int(ticket_id) if ticket_id.isdigit() else -1),
            ).fetchone()

        row = _fetch_row(self._conn)
        db_used = str(self.db_path)

        if not row:
            for db_file in sorted(_DB_DIR.glob("trade_journal-*.db")):
                if str(db_file) == str(self.db_path):
                    continue
                try:
                    conn = sqlite3.connect(str(db_file), check_same_thread=False)
                    conn.row_factory = sqlite3.Row
                    found = _fetch_row(conn)
                    conn.close()
                    if found:
                        row = found
                        db_used = str(db_file)
                        break
                except Exception:
                    continue
            if not row:
                print(f"No se encontró ticket: {ticket_id}")
                return

        print(f"\n{'═'*78}")
        print("  AUDITORIA DE TICKET")
        print(f"{'═'*78}")
        print(f"  DB origen       : {db_used}")
        print(f"  DB id           : {row['id']}")
        print(f"  Ticket id       : {row['order_id']}")
        print(f"  Ticket ref      : {row['order_ref']}")
        print(f"  Activo          : {row['asset']}  ({row['payout']}%)")
        print(f"  Operación       : {str(row['direction']).upper()}  stage={row['stage']}  estrategia={row['strategy_origin']}")
        print(f"  Resultado       : {row['outcome']}  profit={float(row['profit'] or 0):.2f}")
        print(f"  Precio apertura : {row['ticket_open_price']}")
        print(f"  Precio cierre   : {row['ticket_close_price']}")
        print(f"  Hora apertura   : {row['ticket_opened_at']}")
        print(f"  Hora cierre     : {row['ticket_closed_at']}")
        print(f"  Duración (seg)  : {row['ticket_duration_sec']}")
        print(f"  Diferencia      : {row['ticket_price_diff']}")

        pre_ok = row["pre_objectives_ok"]
        pre_label = "N/A" if pre_ok is None else ("OK" if int(pre_ok) == 1 else "NO")
        print(f"  Objetivos pre   : {pre_label}")
        if row["pre_objectives_note"]:
            print(f"  Nota objetivos  : {row['pre_objectives_note']}")
        if row["pre_objectives_json"]:
            print(f"  Detalle pre     : {row['pre_objectives_json']}")
        print(f"{'═'*78}\n")

    # ── Reporte de rendimiento ────────────────────────────────────────────────
    def print_report(self, days: int = 30) -> None:
        since = (datetime.now(tz=BROKER_TZ) - timedelta(days=days)).isoformat()
        print(f"\n{'═'*65}")
        print(f"  TRADE JOURNAL — últimos {days} días")
        print(f"{'═'*65}")

        # ── Resumen general ─────────────────────────────────────────────────
        row = self._conn.execute(
            """SELECT
                COUNT(*) AS total,
                SUM(decision='ACCEPTED') AS accepted,
                SUM(decision LIKE 'REJECTED%') AS rejected,
                SUM(outcome='WIN') AS wins,
                SUM(outcome='LOSS') AS losses,
                SUM(outcome='PENDING') AS pending,
                ROUND(SUM(profit),2) AS net_profit,
                ROUND(AVG(CASE WHEN decision='ACCEPTED' THEN score END),1) AS avg_score_accepted,
                ROUND(AVG(CASE WHEN decision LIKE 'REJECTED%' THEN score END),1) AS avg_score_rejected
               FROM candidates
               WHERE scanned_at >= ?""",
            (since,),
        ).fetchone()

        if not row or row["total"] == 0:
            print("  Sin datos en el período seleccionado.")
            print(f"{'═'*65}\n")
            return

        wins   = row["wins"] or 0
        losses = row["losses"] or 0
        wr     = wins / (wins + losses) * 100 if (wins + losses) > 0 else 0.0

        print(f"  Total evaluados : {row['total']}")
        print(f"  Aceptados       : {row['accepted']}   Rechazados: {row['rejected']}")
        print(f"  Resultados      : WIN={wins}  LOSS={losses}  "
              f"PENDIENTES={row['pending'] or 0}")
        print(f"  Win Rate        : {wr:.1f}%")
        print(f"  Profit neto     : ${row['net_profit'] or 0:.2f}")
        print(f"  Score avg       : aceptados={row['avg_score_accepted'] or 0:.1f}  "
              f"rechazados={row['avg_score_rejected'] or 0:.1f}")

        # ── Win rate por bucket de score ────────────────────────────────────
        print(f"\n  {'WIN RATE POR BUCKET DE SCORE':─<45}")
        buckets = self._conn.execute(
            """SELECT
                CASE
                  WHEN score < 60 THEN '< 60'
                  WHEN score < 70 THEN '60-69'
                  WHEN score < 80 THEN '70-79'
                  WHEN score < 90 THEN '80-89'
                  ELSE '90+'
                END AS bucket,
                COUNT(*) AS total,
                SUM(outcome='WIN') AS wins,
                SUM(outcome='LOSS') AS losses
               FROM candidates
               WHERE scanned_at >= ? AND decision='ACCEPTED'
               GROUP BY bucket
               ORDER BY bucket""",
            (since,),
        ).fetchall()

        if buckets:
            print(f"  {'Score':>8}  {'Trades':>6}  {'Wins':>5}  {'Losses':>6}  {'WR%':>6}")
            for b in buckets:
                w = b["wins"] or 0
                l = b["losses"] or 0
                wr_b = w / (w + l) * 100 if (w + l) > 0 else 0.0
                print(f"  {b['bucket']:>8}  {b['total']:>6}  {w:>5}  {l:>6}  {wr_b:>5.1f}%")
        else:
            print("  Sin trades completados aún.")

        # ── Top activos por win rate ─────────────────────────────────────────
        print(f"\n  {'TOP ACTIVOS (mín. 3 trades)':─<45}")
        top_assets = self._conn.execute(
            """SELECT asset,
                COUNT(*) AS trades,
                SUM(outcome='WIN') AS wins,
                SUM(outcome='LOSS') AS losses,
                ROUND(SUM(profit),2) AS profit,
                ROUND(AVG(score),1) AS avg_score
               FROM candidates
               WHERE scanned_at >= ? AND decision='ACCEPTED'
               GROUP BY asset
               HAVING trades >= 3
               ORDER BY profit DESC
               LIMIT 10""",
            (since,),
        ).fetchall()

        if top_assets:
            print(f"  {'Activo':<22}  {'Trades':>6}  {'Wins':>5}  {'Losses':>6}  "
                  f"{'Profit':>8}  {'AvgScore':>8}")
            for a in top_assets:
                w = a["wins"] or 0
                l = a["losses"] or 0
                wr_a = w / (w + l) * 100 if (w + l) > 0 else 0.0
                print(f"  {a['asset']:<22}  {a['trades']:>6}  {w:>5}  {l:>6}  "
                      f"${a['profit'] or 0:>7.2f}  {a['avg_score'] or 0:>7.1f}  WR={wr_a:.0f}%")
        else:
            print("  Aún no hay suficientes datos por activo.")

        # ── Razones de rechazo más frecuentes ───────────────────────────────
        print(f"\n  {'RAZONES DE RECHAZO':─<45}")
        reasons = self._conn.execute(
            """SELECT decision, COUNT(*) AS n
               FROM candidates
               WHERE scanned_at >= ? AND decision LIKE 'REJECTED%'
               GROUP BY decision
               ORDER BY n DESC""",
            (since,),
        ).fetchall()

        for r in reasons:
            print(f"  {r['decision']:<35} {r['n']:>5}x")

        # ── Componente de score que más penaliza ────────────────────────────
        print(f"\n  {'PROMEDIO DE SCORES POR COMPONENTE (todos los candidatos)':─<45}")
        avgs = self._conn.execute(
            """SELECT
                ROUND(AVG(score_compression),2) AS compression,
                ROUND(AVG(score_bounce),2) AS bounce,
                ROUND(AVG(score_trend),2) AS trend,
                ROUND(AVG(score_payout),2) AS payout
               FROM candidates
               WHERE scanned_at >= ?""",
            (since,),
        ).fetchone()
        if avgs:
            print(f"  compression={avgs['compression'] or 0:.2f}/25  "
                  f"bounce={avgs['bounce'] or 0:.2f}/30  "
                  f"trend={avgs['trend'] or 0:.2f}/25  "
                  f"payout={avgs['payout'] or 0:.2f}/20")

        print(f"{'═'*65}\n")

    # ── Último N candidatos rechazados con detalle ────────────────────────────
    def print_rejected(self, n: int = 20) -> None:
        """Muestra los últimos N candidatos rechazados con detalle."""
        rows = self._conn.execute(
            """SELECT scanned_at, asset, direction, score, decision, reject_reason
               FROM candidates
               WHERE decision LIKE 'REJECTED%'
               ORDER BY id DESC LIMIT ?""",
            (n,),
        ).fetchall()
        print(f"\n{'─'*65}")
        print(f"  Últimos {n} candidatos rechazados")
        print(f"{'─'*65}")
        for r in rows:
            print(f"  {r['scanned_at'][:19]}  {r['asset']:<22}  "
                  f"{r['direction'].upper():4}  score={r['score'] or 0:>5.1f}  "
                  f"{r['decision']}")
            if r["reject_reason"]:
                print(f"    ↳ {r['reject_reason']}")
        print()

    # ── Exportar CSV ─────────────────────────────────────────────────────────
    def export_csv(self, path: Optional[Path] = None, days: int = 90) -> Path:
        """Exporta la tabla candidates a CSV para análisis externo."""
        import csv
        if path is None:
            path = _ROOT / "trade_journal_export.csv"
        since = (datetime.now(tz=BROKER_TZ) - timedelta(days=days)).isoformat()
        rows = self._conn.execute(
            "SELECT * FROM candidates WHERE scanned_at >= ? ORDER BY id",
            (since,),
        ).fetchall()
        if not rows:
            print("Sin datos para exportar.")
            return path
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([d[0] for d in self._conn.execute(
                "SELECT * FROM candidates LIMIT 0"
            ).description])
            for r in rows:
                writer.writerow(list(r))
        print(f"✅ Exportado {len(rows)} registros → {path}")
        return path


# ─────────────────────────────────────────────────────────────────────────────
#  Singleton (uso desde consolidation_bot)
# ─────────────────────────────────────────────────────────────────────────────
_journal: Optional[Journal] = None


def get_journal() -> Journal:
    global _journal
    if _journal is None:
        _journal = Journal()
    return _journal


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers internos
# ─────────────────────────────────────────────────────────────────────────────
def _now() -> str:
    return datetime.now(tz=BROKER_TZ).isoformat(timespec="seconds")


# ─────────────────────────────────────────────────────────────────────────────
#  CLI — python -m trade_journal  ó  python trade_journal.py [días]
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys as _sys

    j = Journal()
    if len(_sys.argv) > 2 and _sys.argv[1] == "--ticket":
        j.print_ticket_audit(_sys.argv[2])
    else:
        days_arg = int(_sys.argv[1]) if len(_sys.argv) > 1 else 30
        j.print_report(days=days_arg)
        j.print_rejected(n=15)

        if len(_sys.argv) > 2 and _sys.argv[2] == "--csv":
            j.export_csv()
