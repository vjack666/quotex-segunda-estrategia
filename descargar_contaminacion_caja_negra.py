from __future__ import annotations

import argparse
import asyncio
import csv
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).resolve().parent
SRC_DIR = ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from pyquotex.stable_api import Quotex  # type: ignore


BROKER_TZ = timezone(timedelta(hours=-3))
OUTPUT_DIR = ROOT / "data" / "price_contamination"
TIMEFRAMES: list[tuple[str, int, int]] = [
    ("1m", 60, 2 * 24 * 60),
    ("5m", 5 * 60, 2 * 24 * 12),
    ("15m", 15 * 60, 2 * 24 * 4),
    ("4h", 4 * 60 * 60, 12),
]


@dataclass
class Candle:
    ts: int
    open: float
    high: float
    low: float
    close: float

    @property
    def body(self) -> float:
        return abs(self.close - self.open)

    @property
    def range(self) -> float:
        return self.high - self.low


@dataclass
class ContaminationEvent:
    log_ts: str
    asset: str
    contaminated_price: float
    reason: str
    range_low: Optional[float] = None
    range_high: Optional[float] = None
    last_valid_price: Optional[float] = None
    delta_pct: Optional[float] = None
    log_source: str = ""

    @property
    def safe_stamp(self) -> str:
        return self.log_ts.replace(":", "").replace(" ", "_")


def load_env() -> None:
    for candidate in (ROOT / ".env", ROOT.parent / ".env"):
        if not candidate.exists():
            continue
        for line in candidate.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())
        break


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


async def fetch_candles(client: Quotex, asset: str, tf_sec: int, count: int) -> list[Candle]:
    end_time = time.time()
    offset = count * tf_sec
    try:
        raw_list = await client.get_candles(asset, end_time, offset, tf_sec)
    except Exception:
        return []
    candles = [raw_to_candle(item) for item in raw_list or [] if isinstance(item, dict)]
    valid = [c for c in candles if c and c.high > 0]
    return sorted(valid, key=lambda item: item.ts)


async def fetch_candles_with_retry(
    client: Quotex,
    asset: str,
    tf_sec: int,
    count: int,
    retries: int = 2,
    timeout_sec: float = 15.0,
) -> list[Candle]:
    attempts = max(1, int(retries))
    for attempt in range(1, attempts + 1):
        try:
            candles = await asyncio.wait_for(fetch_candles(client, asset, tf_sec, count), timeout=timeout_sec)
            if candles:
                return candles
        except Exception:
            pass
        if attempt < attempts:
            await asyncio.sleep(0.5 * attempt)
    return []


def select_log_files(target_date: Optional[str]) -> list[Path]:
    files: list[Path] = []
    if target_date:
        dated_log = ROOT / f"log-{target_date}.txt"
        if dated_log.exists():
            files.append(dated_log)
    consolidation_log = ROOT / "consolidation_bot.log"
    if consolidation_log.exists():
        files.append(consolidation_log)
    if files:
        return files
    dated_logs = sorted(ROOT.glob("log-*.txt"))
    return dated_logs[-1:] if dated_logs else []


def extract_contamination_events(log_files: list[Path]) -> list[ContaminationEvent]:
    events: list[ContaminationEvent] = []
    pattern_outside = re.compile(
        r"^(?P<ts>\d{2}:\d{2}:\d{2}).*?⚠\s+(?P<asset>[A-Z0-9_]+_otc):\s+precio\s+"
        r"(?P<price>-?\d+(?:\.\d+)?)\s+(?:contaminado\s+—\s+)?fuera\s+de\s+(?:zona|rango\s+de\s+zona)\s+"
        r"\[(?P<low>-?\d+(?:\.\d+)?),\s*(?P<high>-?\d+(?:\.\d+)?)\]"
        r"(?:\s+\(último\s+válido:\s+(?P<last>-?\d+(?:\.\d+)?)\))?",
        flags=re.IGNORECASE,
    )
    pattern_delta = re.compile(
        r"^(?P<ts>\d{2}:\d{2}:\d{2}).*?⚠\s+(?P<asset>[A-Z0-9_]+_otc):\s+precio\s+"
        r"(?P<price>-?\d+(?:\.\d+)?)\s+contaminado\s+—\s+cambio\s+de\s+"
        r"(?P<delta>-?\d+(?:\.\d+)?)%\s+vs\s+último\s+válido\s+(?P<last>-?\d+(?:\.\d+)?)",
        flags=re.IGNORECASE,
    )

    for log_file in log_files:
        try:
            lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            continue
        for line in lines:
            match_outside = pattern_outside.search(line)
            if match_outside:
                events.append(
                    ContaminationEvent(
                        log_ts=match_outside.group("ts"),
                        asset=match_outside.group("asset"),
                        contaminated_price=float(match_outside.group("price")),
                        reason="fuera_de_zona",
                        range_low=float(match_outside.group("low")),
                        range_high=float(match_outside.group("high")),
                        last_valid_price=float(match_outside.group("last")) if match_outside.group("last") else None,
                        log_source=log_file.name,
                    )
                )
                continue
            match_delta = pattern_delta.search(line)
            if match_delta:
                events.append(
                    ContaminationEvent(
                        log_ts=match_delta.group("ts"),
                        asset=match_delta.group("asset"),
                        contaminated_price=float(match_delta.group("price")),
                        reason="delta_vs_ultimo_valido",
                        last_valid_price=float(match_delta.group("last")),
                        delta_pct=float(match_delta.group("delta")),
                        log_source=log_file.name,
                    )
                )
    return events


def filter_events(
    events: list[ContaminationEvent],
    asset: Optional[str],
    limit: int,
    export_all: bool,
) -> list[ContaminationEvent]:
    filtered = events
    if asset:
        asset_upper = asset.strip().upper()
        filtered = [event for event in filtered if event.asset.upper() == asset_upper]
    filtered = sorted(filtered, key=lambda event: (event.log_source, event.log_ts), reverse=True)
    if export_all:
        return filtered
    return filtered[: max(1, limit)]


def write_report(folder: Path, event: ContaminationEvent, counts: dict[str, int], csv_name: str) -> None:
    lines = [
        "REPORTE DE CONTAMINACION DESDE CAJA NEGRA",
        "=" * 72,
        f"Activo: {event.asset}",
        f"Hora en log: {event.log_ts}",
        f"Archivo fuente: {event.log_source}",
        f"Motivo: {event.reason}",
        f"Precio contaminado: {event.contaminated_price:.5f}",
        f"Ultimo precio valido: {event.last_valid_price:.5f}" if event.last_valid_price is not None else "Ultimo precio valido: N/D",
    ]
    if event.range_low is not None and event.range_high is not None:
        lines.extend(
            [
                f"Rango de zona reportado: [{event.range_low:.5f}, {event.range_high:.5f}]",
                f"Desviacion contra limite superior: {((event.contaminated_price - event.range_high) / event.range_high * 100):.2f}%" if event.range_high else "Desviacion contra limite superior: N/D",
            ]
        )
    if event.delta_pct is not None:
        lines.append(f"Delta reportado en log: {event.delta_pct:.2f}%")

    lines.extend(
        [
            "",
            "Interpretacion:",
            "- El evento fue tomado desde la misma fuente de logs que revisa la caja negra.",
            "- La descarga se hace aparte para analizar el activo con una IA externa sin tocar el bot.",
            "- El CSV mezcla timeframes 1m, 5m, 15m y 4h en un solo archivo, identificados por columna.",
            "",
            f"Archivo CSV generado: {csv_name}",
            "Velas descargadas:",
        ]
    )
    for label in ["1m", "5m", "15m", "4h"]:
        lines.append(f"- {label}: {counts.get(label, 0)}")
    (folder / "reporte_contaminacion.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_csv(folder: Path, event: ContaminationEvent, exported: dict[str, list[Candle]]) -> Path:
    csv_path = folder / "velas_multiframe_2dias.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "asset",
                "event_log_ts",
                "event_reason",
                "timeframe",
                "timeframe_sec",
                "ts",
                "iso_broker",
                "open",
                "high",
                "low",
                "close",
                "body",
                "range",
            ]
        )
        timeframe_sec_map = {label: tf_sec for label, tf_sec, _ in TIMEFRAMES}
        for label, _, _ in TIMEFRAMES:
            for candle in exported.get(label, []):
                writer.writerow(
                    [
                        event.asset,
                        event.log_ts,
                        event.reason,
                        label,
                        timeframe_sec_map[label],
                        candle.ts,
                        datetime.fromtimestamp(candle.ts, tz=BROKER_TZ).isoformat(),
                        f"{candle.open:.10f}",
                        f"{candle.high:.10f}",
                        f"{candle.low:.10f}",
                        f"{candle.close:.10f}",
                        f"{candle.body:.10f}",
                        f"{candle.range:.10f}",
                    ]
                )
    return csv_path


async def export_event(client: Quotex, event: ContaminationEvent) -> Path:
    safe_asset = "".join(ch if (ch.isalnum() or ch in ("_", "-")) else "_" for ch in event.asset)
    folder = OUTPUT_DIR / f"{event.safe_stamp}_{safe_asset}_{event.reason}"
    folder.mkdir(parents=True, exist_ok=True)

    exported: dict[str, list[Candle]] = {}
    counts: dict[str, int] = {}
    for label, tf_sec, count in TIMEFRAMES:
        candles = await fetch_candles_with_retry(client, event.asset, tf_sec, count)
        exported[label] = candles
        counts[label] = len(candles)

    csv_path = write_csv(folder, event, exported)
    write_report(folder, event, counts, csv_path.name)
    return folder


async def main_async(args: argparse.Namespace) -> None:
    load_env()
    email = os.environ.get("QUOTEX_EMAIL", "").strip()
    password = os.environ.get("QUOTEX_PASSWORD", "").strip()
    if not email or not password:
        raise SystemExit("Faltan QUOTEX_EMAIL / QUOTEX_PASSWORD en .env")

    log_files = select_log_files(args.date)
    if not log_files:
        raise SystemExit("No se encontraron logs para la caja negra.")

    events = extract_contamination_events(log_files)
    selected = filter_events(events, args.asset, args.limit, args.all)
    if not selected:
        raise SystemExit("No se encontraron eventos contaminados con esos filtros.")

    print(f"Eventos encontrados en caja negra: {len(events)}")
    print(f"Eventos a exportar: {len(selected)}")
    for event in selected:
        print(f"- {event.log_ts} | {event.asset} | {event.reason} | fuente={event.log_source}")

    client = Quotex(email=email, password=password)
    connected, reason = await client.connect()
    if not connected:
        raise SystemExit(f"No se pudo conectar a Quotex: {reason}")

    try:
        await client.change_account("PRACTICE")
        for event in selected:
            folder = await export_event(client, event)
            print(f"Exportado: {folder}")
    finally:
        try:
            await client.close()
        except Exception:
            pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Descarga velas multi-timeframe para eventos contaminados detectados en la caja negra.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--date", type=str, default=None, help="Fecha del log en formato YYYY-MM-DD")
    parser.add_argument("--asset", type=str, default=None, help="Filtrar por activo exacto, por ejemplo LINUSD_otc")
    parser.add_argument("--limit", type=int, default=1, help="Cantidad de eventos a exportar si no usas --all")
    parser.add_argument("--all", action="store_true", help="Exportar todos los eventos encontrados")
    return parser


if __name__ == "__main__":
    parser = build_parser()
    try:
        asyncio.run(main_async(parser.parse_args()))
    except KeyboardInterrupt:
        raise SystemExit(0)