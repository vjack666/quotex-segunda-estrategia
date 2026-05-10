"""
BLACK BOX RECORDER - Captura completa de estrategias A, B, C
============================================================

Sistema exhaustivo que registra CADA escaneo, decisión y resultado:
- Todo lo que ve cada estrategia
- Todas las métricas calculadas
- Razones de aceptación/rechazo
- Snapshots de velas
- Histórico completo para análisis posterior

Almacenamiento: SQLite + JSON exports
"""

import json
import sqlite3
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Any, Optional
from dataclasses import dataclass

# ─────────────────────────────────────────────────────────────────────────────
#  CONFIGURACIÓN
# ─────────────────────────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DB_DIR = DATA_DIR / "db"
EXPORTS_DIR = DATA_DIR / "exports" / "black_box"
LOGS_DIR = DATA_DIR / "logs" / "black_box"

for d in [DB_DIR, EXPORTS_DIR, LOGS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

TODAY = datetime.now().strftime("%Y-%m-%d")
BLACK_BOX_DB = DB_DIR / f"black_box_strat_{TODAY}.db"
BLACK_BOX_LOG = LOGS_DIR / f"black_box_{TODAY}.jsonl"


# ─────────────────────────────────────────────────────────────────────────────
#  DDL - SCHEMA COMPLETO
# ─────────────────────────────────────────────────────────────────────────────

_DDL_SCANS = """
CREATE TABLE IF NOT EXISTS scans (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              REAL NOT NULL,
    ts_iso          TEXT NOT NULL,
    strategy        TEXT NOT NULL,          -- A | B | C
    scan_number     INTEGER,
    total_candidates INTEGER DEFAULT 0,
    
    -- Contexto de mercado
    market_state    TEXT,                   -- trending | consolidating | ranging
    volatility_atr  REAL,
    
    -- Resultado del escaneo
    found_count     INTEGER DEFAULT 0,      -- candidatos encontrados
    accepted_count  INTEGER DEFAULT 0,
    rejected_count  INTEGER DEFAULT 0,
    
    created_at      TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS scan_candidates (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id         INTEGER NOT NULL,
    ts              REAL NOT NULL,
    strategy        TEXT NOT NULL,          -- A | B | C
    
    -- Identificación
    asset           TEXT NOT NULL,
    direction       TEXT NOT NULL,          -- call | put
    
    -- Scores y métricas
    score           REAL,
    confidence      REAL,
    payout          INTEGER,
    
    -- Decisión
    decision        TEXT NOT NULL,          -- ACCEPTED | REJECTED_SCORE | etc
    decision_reason TEXT,
    reject_reason   TEXT,
    
    -- Detalles específicos por estrategia
    strategy_details TEXT,                  -- JSON con detalles específicos
    
    -- Velas snapshot (JSON)
    candles_1m      TEXT,                   -- últimas 5 velas 1m
    candles_5m      TEXT,                   -- últimas 3 velas 5m
    
    -- Resultado (si fue aceptado)
    order_id        TEXT,
    order_result    TEXT,                   -- WIN | LOSS | PENDING | EXPIRED
    profit          REAL,
    masaniello_snapshot TEXT,               -- JSON con estado Masaniello al cerrar
    
    created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at      TEXT DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY(scan_id) REFERENCES scans(id)
);

CREATE TABLE IF NOT EXISTS strategy_metrics (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              REAL NOT NULL,
    strategy        TEXT NOT NULL,          -- A | B | C
    
    -- Acumulado
    total_scans     INTEGER DEFAULT 0,
    total_candidates INTEGER DEFAULT 0,
    total_accepted  INTEGER DEFAULT 0,
    
    -- Performance
    wins            INTEGER DEFAULT 0,
    losses          INTEGER DEFAULT 0,
    pending         INTEGER DEFAULT 0,
    win_rate        REAL,
    pnl             REAL,
    
    -- Últimos valores
    last_decision   TEXT,
    last_asset      TEXT,
    
    created_at      TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS phase_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              REAL NOT NULL,
    ts_iso          TEXT NOT NULL,
    strategy        TEXT NOT NULL,
    asset           TEXT,
    
    phase           TEXT NOT NULL,          -- signal_detected | scored | filtered | accepted | rejected
    message         TEXT,
    
    created_at      TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS maintenance_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              REAL NOT NULL,
    ts_iso          TEXT NOT NULL,
    category        TEXT NOT NULL,          -- HTF_LIBRARY | VIP_LIBRARY | SPIKE_FILTER | etc
    subtype         TEXT NOT NULL,          -- REFRESH | ENTER | EXIT | PURGE | SUMMARY
    asset           TEXT,
    severity        TEXT DEFAULT 'INFO',
    payload_json    TEXT,
    created_at      TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


# ─────────────────────────────────────────────────────────────────────────────
#  BLACK BOX RECORDER CLASS
# ─────────────────────────────────────────────────────────────────────────────

class BlackBoxRecorder:
    """Registra TODA la actividad de las estrategias."""
    
    def __init__(self):
        self.db_path = BLACK_BOX_DB
        self.log_path = BLACK_BOX_LOG
        self._init_db()
    
    def _init_db(self) -> None:
        """Crea tablas si no existen."""
        try:
            con = sqlite3.connect(self.db_path)
            con.executescript(_DDL_SCANS)
            # Migración ligera para DBs existentes del día.
            cols = [
                str(row[1]).lower()
                for row in con.execute("PRAGMA table_info(scan_candidates)").fetchall()
            ]
            if "masaniello_snapshot" not in cols:
                con.execute("ALTER TABLE scan_candidates ADD COLUMN masaniello_snapshot TEXT")
            maintenance_cols = [
                str(row[1]).lower()
                for row in con.execute("PRAGMA table_info(maintenance_log)").fetchall()
            ]
            if not maintenance_cols:
                con.execute(
                    """
                    CREATE TABLE IF NOT EXISTS maintenance_log (
                        id              INTEGER PRIMARY KEY AUTOINCREMENT,
                        ts              REAL NOT NULL,
                        ts_iso          TEXT NOT NULL,
                        category        TEXT NOT NULL,
                        subtype         TEXT NOT NULL,
                        asset           TEXT,
                        severity        TEXT DEFAULT 'INFO',
                        payload_json    TEXT,
                        created_at      TEXT DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            con.commit()
            con.close()
        except Exception as e:
            print(f"❌ Error inicializando DB: {e}")
    
    def record_scan_start(self, strategy: str, scan_number: int, market_context: Dict[str, Any] = None) -> int:
        """Registra el inicio de un escaneo. Retorna scan_id."""
        ts = datetime.now(timezone.utc).timestamp()
        ts_iso = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
        
        market_state = market_context.get("market_state", "unknown") if market_context else "unknown"
        volatility = market_context.get("volatility_atr", 0.0) if market_context else 0.0
        
        con = sqlite3.connect(self.db_path)
        cur = con.cursor()
        cur.execute('''
            INSERT INTO scans (ts, ts_iso, strategy, scan_number, market_state, volatility_atr)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (ts, ts_iso, strategy, scan_number, market_state, volatility))
        con.commit()
        scan_id = cur.lastrowid
        con.close()
        
        # Log a JSONL
        self._log_jsonl({
            "event": "scan_start",
            "ts": ts,
            "ts_iso": ts_iso,
            "strategy": strategy,
            "scan_number": scan_number,
            "market_state": market_state,
            "volatility": volatility,
        })
        
        return scan_id
    
    def record_candidate(self, scan_id: int, strategy: str, data: Dict[str, Any]) -> int:
        """Registra un candidato escaneado y retorna su id."""
        ts = datetime.now(timezone.utc).timestamp()
        
        con = sqlite3.connect(self.db_path)
        cur = con.cursor()
        
        # Extraer campos
        asset = data.get("asset", "")
        direction = data.get("direction", "")
        score = data.get("score", 0.0)
        confidence = data.get("confidence", 0.0)
        payout = data.get("payout", 0)
        decision = data.get("decision", "")
        decision_reason = data.get("decision_reason", "")
        reject_reason = data.get("reject_reason", "")
        order_id = data.get("order_id", None)  # ← Use None instead of ""
        
        # Detalles específicos por estrategia (JSON)
        strategy_details = json.dumps(data.get("strategy_details", {}), ensure_ascii=False)
        
        # Velas (JSON)
        candles_1m = json.dumps(data.get("candles_1m", []), ensure_ascii=False) if data.get("candles_1m") else None
        candles_5m = json.dumps(data.get("candles_5m", []), ensure_ascii=False) if data.get("candles_5m") else None
        
        cur.execute('''
            INSERT INTO scan_candidates 
            (scan_id, ts, strategy, asset, direction, score, confidence, payout,
             decision, decision_reason, reject_reason, strategy_details, candles_1m, candles_5m, order_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            scan_id, ts, strategy, asset, direction, score, confidence, payout,
            decision, decision_reason, reject_reason, strategy_details, candles_1m, candles_5m, order_id
        ))
        candidate_id = int(cur.lastrowid or 0)
        con.commit()
        con.close()
        
        # Log a JSONL
        self._log_jsonl({
            "event": "candidate_recorded",
            "ts": ts,
            "strategy": strategy,
            "asset": asset,
            "direction": direction,
            "score": score,
            "confidence": confidence,
            "decision": decision,
        })
        return candidate_id

    def update_candidate(
        self,
        candidate_id: int,
        *,
        decision: Optional[str] = None,
        decision_reason: Optional[str] = None,
        reject_reason: Optional[str] = None,
        order_id: Optional[str] = None,
        order_result: Optional[str] = None,
        profit: Optional[float] = None,
        masaniello_snapshot: Optional[Dict[str, Any] | str] = None,
    ) -> None:
        """Actualiza un candidato existente con estado posterior al escaneo."""
        if candidate_id <= 0:
            return

        fields: list[str] = []
        values: list[Any] = []
        if decision is not None:
            fields.append("decision = ?")
            values.append(decision)
        if decision_reason is not None:
            fields.append("decision_reason = ?")
            values.append(decision_reason)
        if reject_reason is not None:
            fields.append("reject_reason = ?")
            values.append(reject_reason)
        if order_id is not None:
            fields.append("order_id = ?")
            values.append(order_id)
        if order_result is not None:
            fields.append("order_result = ?")
            values.append(order_result)
        if profit is not None:
            fields.append("profit = ?")
            values.append(profit)
        if masaniello_snapshot is not None:
            fields.append("masaniello_snapshot = ?")
            if isinstance(masaniello_snapshot, str):
                values.append(masaniello_snapshot)
            else:
                values.append(json.dumps(masaniello_snapshot, ensure_ascii=False))
        if not fields:
            return

        fields.append("updated_at = ?")
        values.append(datetime.now(timezone.utc).isoformat())
        values.append(candidate_id)

        con = sqlite3.connect(self.db_path)
        cur = con.cursor()
        cur.execute(
            f"UPDATE scan_candidates SET {', '.join(fields)} WHERE id = ?",
            values,
        )
        con.commit()
        con.close()
    
    def record_order_result(self, order_id: str, outcome: str, profit: float) -> None:
        """Actualiza resultado de una orden."""
        ts = datetime.now(timezone.utc).timestamp()
        ts_iso = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
        
        con = sqlite3.connect(self.db_path)
        cur = con.cursor()
        cur.execute('''
            UPDATE scan_candidates
            SET order_result = ?, profit = ?, updated_at = ?
            WHERE order_id = ?
        ''', (outcome, profit, ts_iso, order_id))
        con.commit()
        con.close()
        
        self._log_jsonl({
            "event": "order_result",
            "ts": ts,
            "order_id": order_id,
            "outcome": outcome,
            "profit": profit,
        })
    
    def record_phase(self, strategy: str, phase: str, message: str = "", asset: str = "") -> None:
        """Registra una fase de procesamiento."""
        ts = datetime.now(timezone.utc).timestamp()
        ts_iso = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
        
        con = sqlite3.connect(self.db_path)
        cur = con.cursor()

    def record_maintenance_event(
        self,
        category: str,
        subtype: str,
        *,
        asset: str = "",
        severity: str = "INFO",
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Registra eventos de mantenimiento / salud del sistema en la caja negra."""
        ts = datetime.now(timezone.utc).timestamp()
        ts_iso = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
        payload_json = json.dumps(payload or {}, ensure_ascii=False)

        con = sqlite3.connect(self.db_path)
        cur = con.cursor()
        cur.execute(
            '''
            INSERT INTO maintenance_log (ts, ts_iso, category, subtype, asset, severity, payload_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ''',
            (ts, ts_iso, str(category), str(subtype), str(asset or ""), str(severity or "INFO"), payload_json),
        )
        con.commit()
        con.close()

        self._log_jsonl({
            "event": "maintenance",
            "ts": ts,
            "ts_iso": ts_iso,
            "category": category,
            "subtype": subtype,
            "asset": asset,
            "severity": severity,
            "payload": payload or {},
        })
        cur.execute('''
            INSERT INTO phase_log (ts, ts_iso, strategy, asset, phase, message)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (ts, ts_iso, strategy, asset, phase, message))
        con.commit()
        con.close()
    
    def update_scan_results(self, scan_id: int, found: int, accepted: int, rejected: int) -> None:
        """Actualiza conteo final del escaneo."""
        con = sqlite3.connect(self.db_path)
        cur = con.cursor()
        cur.execute('''
            UPDATE scans
            SET found_count = ?, accepted_count = ?, rejected_count = ?
            WHERE id = ?
        ''', (found, accepted, rejected, scan_id))
        con.commit()
        con.close()
    
    def update_strategy_metrics(self, strategy: str, metrics: Dict[str, Any]) -> None:
        """Actualiza métricas agregadas de la estrategia."""
        ts = datetime.now(timezone.utc).timestamp()
        
        con = sqlite3.connect(self.db_path)
        cur = con.cursor()
        cur.execute('''
            INSERT INTO strategy_metrics 
            (ts, strategy, total_scans, total_candidates, total_accepted, wins, losses, pending, win_rate, pnl, last_decision, last_asset)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            ts, strategy,
            metrics.get("total_scans", 0),
            metrics.get("total_candidates", 0),
            metrics.get("total_accepted", 0),
            metrics.get("wins", 0),
            metrics.get("losses", 0),
            metrics.get("pending", 0),
            metrics.get("win_rate", 0.0),
            metrics.get("pnl", 0.0),
            metrics.get("last_decision", ""),
            metrics.get("last_asset", ""),
        ))
        con.commit()
        con.close()
    
    def _log_jsonl(self, record: Dict[str, Any]) -> None:
        """Escribe evento a JSONL."""
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as e:
            print(f"⚠️ Error escribiendo JSONL: {e}")
    
    def export_summary(self) -> Dict[str, Any]:
        """Genera resumen del día."""
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        
        # Scans por estrategia
        cur.execute('''
            SELECT strategy, COUNT(*) as count, SUM(found_count) as found, 
                   SUM(accepted_count) as accepted
            FROM scans
            GROUP BY strategy
        ''')
        scans = {row["strategy"]: dict(row) for row in cur.fetchall()}
        
        # Performance por estrategia
        cur.execute('''
            SELECT strategy, COUNT(*) as total_trades, 
                   SUM(CASE WHEN order_result = 'WIN' THEN 1 ELSE 0 END) as wins,
                   SUM(CASE WHEN order_result = 'LOSS' THEN 1 ELSE 0 END) as losses,
                   ROUND(SUM(profit), 2) as pnl
            FROM scan_candidates
            WHERE order_result IS NOT NULL
            GROUP BY strategy
        ''')
        performance = {row["strategy"]: dict(row) for row in cur.fetchall()}
        
        con.close()
        
        return {
            "date": TODAY,
            "scans_by_strategy": scans,
            "performance_by_strategy": performance,
        }


# ─────────────────────────────────────────────────────────────────────────────
#  SINGLETON INSTANCE
# ─────────────────────────────────────────────────────────────────────────────

_recorder = None

def get_black_box() -> BlackBoxRecorder:
    """Obtiene instancia singleton del recorder."""
    global _recorder
    if _recorder is None:
        _recorder = BlackBoxRecorder()
    return _recorder


# ─────────────────────────────────────────────────────────────────────────────
#  USO SIMPLE
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Ejemplo de uso
    recorder = get_black_box()
    
    # Registrar escaneo
    scan_id = recorder.record_scan_start("A", 1, {"market_state": "consolidating", "volatility_atr": 0.0015})
    
    # Registrar candidato
    recorder.record_candidate(scan_id, "A", {
        "asset": "EURUSD_OTC",
        "direction": "call",
        "score": 65.3,
        "confidence": 0.82,
        "payout": 82,
        "decision": "ACCEPTED",
        "decision_reason": "Strong rebound signal",
        "strategy_details": {"zone": [1.0950, 1.0980], "pattern": "spring"},
    })
    
    # Actualizar resultados
    recorder.update_scan_results(scan_id, found=5, accepted=1, rejected=4)
    
    # Exportar resumen
    summary = recorder.export_summary()
    print("\n📊 BLACK BOX SUMMARY")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    
    print(f"\n✅ Datos guardados en:")
    print(f"   DB:   {BLACK_BOX_DB}")
    print(f"   JSONL: {BLACK_BOX_LOG}")
