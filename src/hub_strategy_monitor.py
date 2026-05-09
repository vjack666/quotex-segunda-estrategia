import argparse
import json
import os
import sys
import time
from pathlib import Path

from entry_scorer import CandidateEntry
from models import Candle, ConsolidationZone

_ROOT = Path(__file__).resolve().parent.parent
_SRC = Path(__file__).resolve().parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_GREEN = "\033[32m"
_RED = "\033[31m"
_YELLOW = "\033[33m"
_CYAN = "\033[36m"
_MAGENTA = "\033[35m"
_WHITE = "\033[37m"

# ── Caché local de pares STRAT-A (persiste entre ciclos dentro del proceso) ──
_strat_a_cache: dict[str, dict] = {}
_MAX_ABSENT_CYCLES = 4   # ciclos sin aparecer antes de invalidar
_MIN_SCORE_KEEP = 20.0   # score mínimo para mantener el par (ajustado a condiciones actuales)
_SCORE_THRESHOLD = 50.0  # score para considerar el bloque aprobado (sync con threshold base STRAT-A)

# Archivo de cola para invalidaciones (lo consume el bot central)
_INVALIDATION_QUEUE = _ROOT / "data" / "hub_invalidations_queue.jsonl"


def _enable_ansi_windows() -> bool:
    """Intenta habilitar ANSI en consola Windows. Retorna True si queda activo."""
    if os.name != "nt":
        return True
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)
            return True
    except Exception:
        pass
    return False


# Detectar soporte ANSI al inicio del proceso (antes de cualquier escritura).
_ANSI_OK: bool = _enable_ansi_windows()


def _ok(flag: bool) -> str:
    return f"{_GREEN}[x]{_RESET}" if flag else f"{_RED}[ ]{_RESET}"


def _load_state(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


# ─────────────────────────────────────────────────────────────────────────────
#  LÓGICA DE CACHÉ Y PERSISTENCIA (solo STRAT-A)
# ─────────────────────────────────────────────────────────────────────────────

def _checklist_blocks_for(c: dict) -> list[tuple[str, bool]]:
    """7 bloques del checklist STRAT-A derivados de los campos del candidato."""
    score = float(c.get("score", 0.0) or 0.0)
    payout = int(c.get("payout", 0) or 0)
    zone_ceiling = float(c.get("zone_ceiling", 0.0) or 0.0)
    zone_floor = float(c.get("zone_floor", 0.0) or 0.0)
    entry_mode = str(c.get("entry_mode", "") or "")
    pattern = str(c.get("pattern", "") or "")
    pattern_strength = float(c.get("pattern_strength", 0.0) or 0.0)
    direction = str(c.get("direction", "") or "").lower()
    dist_pct = c.get("dist_pct", None)
    signal_type = str(c.get("signal_type", "") or "")
    pipeline_stage = str(c.get("raw_reason", "") or "preview").strip().lower()
    execution_ready = pipeline_stage in ("selected_near_trigger", "accepted", "entered")

    return [
        ("Mercado y datos",      bool(c.get("asset", ""))),
        ("Zona detectada",       zone_ceiling > 0 and zone_floor > 0),
        ("Condicion entrada",    bool(entry_mode)),
        ("Vela 1m valida",       pattern_strength > 0.0 or bool(signal_type)),
        ("Patron + filtros H1",  bool(pattern)),
        (f"Score >= {_SCORE_THRESHOLD:.0f}", score >= _SCORE_THRESHOLD),
        (
            "Riesgo OK (payout/dist)",
            payout >= 80 and dist_pct is not None and direction in ("call", "put") and execution_ready,
        ),
    ]


def _invalidation_reason(c: dict, absent_cycles: int) -> str | None:
    """Devuelve el motivo de invalidación o None si el par sigue válido."""
    score = float(c.get("score", 0.0) or 0.0)
    if absent_cycles >= _MAX_ABSENT_CYCLES:
        return f"ausente {absent_cycles} ciclos consecutivos"
    if score < _MIN_SCORE_KEEP and score > 0:
        return f"score demasiado bajo ({score:.1f} < {_MIN_SCORE_KEEP})"
    return None


def _log_invalidation(asset: str, reason: str, c: dict) -> None:
    """Escribe la invalidación a la cola JSONL y opcionalmente al journal SQLite."""
    entry = {
        "ts": time.time(),
        "strategy": "A",
        "asset": asset,
        "reason": reason,
        "score": float(c.get("score", 0.0) or 0.0),
        "direction": str(c.get("direction", "") or ""),
        "entry_mode": str(c.get("entry_mode", "") or ""),
        "payout": int(c.get("payout", 0) or 0),
    }
    # 1) Cola JSONL (sin riesgos de lock)
    try:
        _INVALIDATION_QUEUE.parent.mkdir(parents=True, exist_ok=True)
        with _INVALIDATION_QUEUE.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass
    # 2) Intento directo al journal SQLite (proceso separado → puede fallar, no pasa nada)
    try:
        from trade_journal import get_journal

        direction = str(entry["direction"] or "").lower()
        if direction not in ("call", "put"):
            direction = "call"

        zone_floor = float(c.get("zone_floor", 0.0) or 0.0)
        zone_ceiling = float(c.get("zone_ceiling", 0.0) or 0.0)
        if zone_ceiling <= zone_floor:
            # Fallback mínimo para evitar zona inválida al persistir en journal.
            zone_floor = max(0.0, zone_floor)
            zone_ceiling = zone_floor + 1e-6

        zone = ConsolidationZone(
            asset=asset,
            ceiling=zone_ceiling,
            floor=zone_floor,
            bars_inside=0,
            detected_at=time.time(),
            range_pct=0.0,
        )
        px = zone_floor if direction == "call" else zone_ceiling
        candles = [Candle(ts=int(time.time()), open=px, high=px, low=px, close=px)]

        journal_entry = CandidateEntry(
            asset=asset,
            payout=int(entry["payout"]),
            zone=zone,
            direction=direction,
            candles=candles,
        )
        journal_entry.score = float(entry["score"])
        setattr(journal_entry, "_entry_mode", str(entry.get("entry_mode", "") or ""))

        get_journal().log_candidate(
            entry=journal_entry,
            decision="REJECTED_SCORE",
            reject_reason=f"INVALIDATED_MONITOR: {reason}",
            stage="monitor_invalidation",
            strategy={
                "source": "hub_strategy_monitor",
                "strategy": "STRAT-A",
                "event": "INVALIDATED",
            },
        )
    except Exception:
        pass


def _update_strat_a_cache(live_candidates: list[dict]) -> None:
    """Actualiza la caché local con los candidatos del ciclo actual."""
    global _strat_a_cache
    live_assets = {str(c.get("asset", "") or "") for c in live_candidates if c.get("asset")}

    # Actualizar / agregar pares presentes en este ciclo
    for c in live_candidates:
        asset = str(c.get("asset", "") or "")
        if not asset:
            continue
        if asset not in _strat_a_cache:
            _strat_a_cache[asset] = {
                "candidate": c,
                "first_seen": time.time(),
                "last_seen": time.time(),
                "cycles_absent": 0,
                "status": "building",  # building | complete | invalidated
                "invalidation_reason": "",
            }
        else:
            entry = _strat_a_cache[asset]
            entry["candidate"] = c
            entry["last_seen"] = time.time()
            entry["cycles_absent"] = 0
            stage = str(c.get("raw_reason", "") or "preview").strip().lower()
            if stage == "entered":
                entry["status"] = "complete"
            elif stage in ("selected_near_trigger", "accepted"):
                entry["status"] = "ready"
            elif stage.startswith("rejected_") or stage in ("watched_limit", "enter_failed"):
                entry["status"] = "blocked"
            else:
                entry["status"] = "building"

    # Incrementar ausencias y verificar invalidaciones
    to_remove = []
    for asset, entry in _strat_a_cache.items():
        if asset not in live_assets:
            entry["cycles_absent"] += 1
        reason = None
        if entry["status"] != "complete":
            reason = _invalidation_reason(entry["candidate"], entry["cycles_absent"])
        if reason and entry["status"] not in ("invalidated",):
            entry["status"] = "invalidated"
            entry["invalidation_reason"] = reason
            _log_invalidation(asset, reason, entry["candidate"])
            # Dejar el par en pantalla 2 ciclos más para que se vea el motivo
            entry["cycles_absent"] = _MAX_ABSENT_CYCLES - 2

    # Eliminar invalidados que ya mostraron su mensaje suficiente tiempo
    for asset, entry in list(_strat_a_cache.items()):
        if entry["status"] == "invalidated" and entry["cycles_absent"] >= _MAX_ABSENT_CYCLES:
            to_remove.append(asset)
    for asset in to_remove:
        del _strat_a_cache[asset]


# ─────────────────────────────────────────────────────────────────────────────
#  RENDER STRAT-A  (2 columnas, checklist 7 bloques, pares persistentes)
# ─────────────────────────────────────────────────────────────────────────────

_W = 80          # ancho total
_COL_L = 34      # ancho columna izquierda (info del par)
_COL_R = 44      # ancho columna derecha (checklist)


def _pad(text: str, width: int) -> str:
    """Trunca o rellena con espacios hasta `width` (ignorando escapes ANSI para el cálculo)."""
    # Contar solo caracteres visibles (ignorar secuencias ANSI)
    import re
    visible = re.sub(r'\033\[[0-9;]*m', '', text)
    visible_len = len(visible)
    if visible_len >= width:
        return text  # ya cabe (no truncar texto con colores)
    return text + " " * (width - visible_len)


def _render_strat_a(state: dict) -> str:
    scans = int(state.get("total_scans", 0) or 0)
    balance = float(state.get("balance", 0.0) or 0.0)
    wins = int(state.get("wins", 0) or 0)
    losses = int(state.get("losses", 0) or 0)
    gale = dict(state.get("gale", {}) or {})

    sep = f"{_DIM}{'─' * _W}{_RESET}"
    lines: list[str] = []

    # ── Header ──
    lines.append(f"{_BOLD}{_CYAN}{'═' * _W}{_RESET}")
    lines.append(f"{_BOLD}{_CYAN}  MONITOR A  ·  STRAT-A  Consolidacion / Rebote{_RESET}")
    lines.append(f"  Scans:{scans}  Balance:${balance:.2f}  W/L:{wins}/{losses}")
    lines.append(sep)

    # ── Gale (si activo) ──
    if bool(gale.get("active", False)):
        g_asset = str(gale.get("asset", "") or "")
        g_dir   = str(gale.get("direction", "") or "").upper()
        g_secs  = float(gale.get("secs_remaining", 0.0) or 0.0)
        lines.append(
            f"  {_YELLOW}{_BOLD}GALE ACTIVO{_RESET}  "
            f"{g_asset} {g_dir}  {g_secs:.0f}s restantes"
        )
        lines.append(sep)

    # ── Pares en caché ──
    if not _strat_a_cache:
        lines.append(f"  {_DIM}Sin pares detectados aun. Esperando proxima exploracion...{_RESET}")
    else:
        # Ordenar: ready/completo arriba, luego building, blocked e invalidated
        order = {"ready": 0, "complete": 1, "building": 2, "blocked": 3, "invalidated": 4}
        sorted_entries = sorted(
            _strat_a_cache.items(),
            key=lambda kv: (order.get(kv[1]["status"], 3), -float(kv[1]["candidate"].get("score", 0) or 0)),
        )

        for asset, entry in sorted_entries:
            c = entry["candidate"]
            status = entry["status"]
            absent = entry["cycles_absent"]
            cycles_building = max(1, round((time.time() - entry["first_seen"]) / 60))

            direction = str(c.get("direction", "") or "").upper()
            score     = float(c.get("score", 0.0) or 0.0)
            payout    = int(c.get("payout", 0) or 0)
            zone_ceil = float(c.get("zone_ceiling", 0.0) or 0.0)
            zone_flr  = float(c.get("zone_floor", 0.0) or 0.0)
            entry_mode = str(c.get("entry_mode", "") or "--")
            dist_pct   = c.get("dist_pct", None)
            dist_txt   = "--" if dist_pct is None else f"{float(dist_pct) * 100:.2f}%"
            pipeline_stage = str(c.get("raw_reason", "") or "preview").strip().lower()

            # Color / etiqueta de estado
            if status == "building":
                status_col = _YELLOW
                status_lbl = f"EN CONSTRUCCION  (visto hace {cycles_building} min)"
            elif status == "ready":
                status_col = _CYAN
                status_lbl = "LISTO PARA ORDEN"
            elif status == "complete":
                status_col = _GREEN
                status_lbl = "ORDEN ENVIADA ✓"
            elif status == "blocked":
                status_col = _YELLOW
                status_lbl = "BLOQUEADO MOTOR"
            else:
                status_col = _RED
                status_lbl = "INVALIDADO"

            # ── Línea de cabecera del par ──
            dir_col = _GREEN if direction == "CALL" else _RED
            lines.append(
                f"  {_BOLD}{asset:<16}{_RESET}"
                f"  {_BOLD}{dir_col}{direction:<5}{_RESET}"
                f"  Score:{_BOLD}{score:>5.1f}{_RESET}"
                f"  P:{payout}%"
                f"  [{status_col}{_BOLD}{status_lbl}{_RESET}]"
            )

            if status == "invalidated":
                reason = entry.get("invalidation_reason", "desconocido")
                lines.append(f"    {_DIM}✗ Motivo: {reason}{_RESET}")
                lines.append(sep)
                continue

            # ── Datos clave (línea compacta) ──
            lines.append(
                f"    Zona: {zone_flr:.5f} — {zone_ceil:.5f}"
                f"  Dist: {dist_txt}"
                f"  Modo: {entry_mode}"
                f"  Etapa: {pipeline_stage}"
            )

            # ── Checklist (columna única, clara) ──
            blocks = _checklist_blocks_for(c)
            approved = sum(1 for _, done in blocks if done)
            lines.append(f"    Checklist {approved}/{len(blocks)}:")
            for i, (label, done) in enumerate(blocks, 1):
                lines.append(f"      {_ok(done)} {i}. {label}")

            lines.append(sep)

    lines.append("")
    lines.append(f"{_DIM}[ORDEN ENVIADA] = pipeline_stage 'entered' confirmado por el motor.{_RESET}")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
#  RENDER genérico STRAT-B / STRAT-C
# ─────────────────────────────────────────────────────────────────────────────

def _checklist_generic(strategy: str, candidates: list[dict]) -> list[tuple[str, bool]]:
    top = candidates[0] if candidates else {}
    score   = float(top.get("score", 0.0) or 0.0)
    payout  = int(top.get("payout", 0) or 0)
    direction = str(top.get("direction", "") or "").lower()
    has_dist  = top.get("dist_pct", None) is not None
    confidence = float(top.get("confidence", 0.0) or 0.0)

    req_score   = {"B": 48.0, "C": 41.0}.get(strategy, 50.0)  # C: 7/17*100=41.2 sync MIN_SCORE
    req_payout  = 80
    req_conf    = 0.70 if strategy == "B" else 0.0

    items = [
        ("Activo detectado en scan",       len(candidates) > 0),
        ("Direccion valida (CALL/PUT)",     direction in ("call", "put")),
        (f"Payout >= {req_payout}%",        payout >= req_payout),
        (f"Score >= {req_score:.0f}",       score >= req_score),
        ("Distancia al trigger disponible", has_dist),
    ]
    if strategy == "B":
        items.append((f"Confianza >= {req_conf:.0%}", confidence >= req_conf))
    return items


def _stage_tag_b(stage: str) -> str:
    s = str(stage or "").strip().lower()
    if s == "entered":
        return f"{_GREEN}[ORDEN ENVIADA ✓]{_RESET}"
    if s == "accepted":
        return f"{_CYAN}[LISTO PARA ORDEN]{_RESET}"
    if s in ("rejected_limit", "blocked_readonly", "enter_failed"):
        return f"{_YELLOW}[BLOQUEADO MOTOR]{_RESET}"
    if s in ("rejected_conf", "rejected_no_signal"):
        return f"{_YELLOW}[FILTRADO]{_RESET}"
    return f"{_YELLOW}[EN CONSTRUCCION]{_RESET}"


def _pipeline_steps_b(c: dict) -> list[tuple[str, bool]]:
    stage = str(c.get("raw_reason", "") or "preview").strip().lower()
    signal_type = str(c.get("signal_type", "") or "")
    conf = float(c.get("confidence", 0.0) or 0.0)
    direction = str(c.get("direction", "") or "").lower()
    payout = int(c.get("payout", 0) or 0)
    dist = c.get("dist_pct", None)
    is_early = signal_type.startswith("wyckoff_early")
    req_conf = 0.62 if is_early else 0.70

    signal_ok = stage not in ("rejected_no_signal",) and bool(signal_type)
    conf_ok = conf >= req_conf and stage not in ("rejected_conf",)
    engine_enabled = stage not in ("blocked_readonly",)
    limits_ok = stage not in ("rejected_limit",)
    accepted = stage in ("accepted", "entered")
    entered = stage == "entered"

    return [
        ("Datos 1m recolectados", bool(c.get("asset", ""))),
        ("Patron Wyckoff detectado", signal_ok),
        (f"Confianza >= {req_conf:.0%}", conf_ok),
        ("Motor habilitado para operar", engine_enabled),
        ("Limites/cooldown permitidos", limits_ok),
        ("Candidato aceptado por motor", accepted),
        ("Orden enviada al broker", entered),
        ("Payout/distancia validos", payout >= 80 and dist is not None and direction in ("call", "put")),
    ]


def _render_strat_b(state: dict) -> str:
    scans = int(state.get("total_scans", 0) or 0)
    balance = float(state.get("balance", 0.0) or 0.0)
    wins = int(state.get("wins", 0) or 0)
    losses = int(state.get("losses", 0) or 0)
    candidates = list(state.get("strat_b", []) or [])
    gale = dict(state.get("gale", {}) or {})

    sep = f"{_DIM}{'─' * _W}{_RESET}"
    lines = [
        f"{_BOLD}{_CYAN}{'═' * _W}{_RESET}",
        f"{_BOLD}{_CYAN}  MONITOR B  ·  STRAT-B  Spring / Sweep{_RESET}",
        f"  Scans:{scans}  Balance:${balance:.2f}  W/L:{wins}/{losses}",
        sep,
    ]

    if not candidates:
        lines.append(f"  {_DIM}Sin candidatos STRAT-B en este ciclo.{_RESET}")
    else:
        for i, c in enumerate(candidates[:5], 1):
            asset = str(c.get("asset", "") or "")
            direction = str(c.get("direction", "") or "").upper()
            score = float(c.get("score", 0.0) or 0.0)
            payout = int(c.get("payout", 0) or 0)
            conf = float(c.get("confidence", 0.0) or 0.0)
            signal_type = str(c.get("signal_type", "") or "none")
            stage = str(c.get("raw_reason", "") or "preview").strip().lower()
            note = str(c.get("raw_note", "") or "")
            dist = c.get("dist_pct", None)
            dist_txt = "--" if dist is None else f"{float(dist) * 100:.2f}%"

            lines.append(
                f"  {_BOLD}{i}. {asset:<12}{_RESET} {direction:<4} "
                f"S:{score:>5.1f} Conf:{conf*100:>5.1f}% P:{payout:>2}%  {_stage_tag_b(stage)}"
            )
            lines.append(f"  {_DIM}Patron: {signal_type} | Dist:{dist_txt} | Etapa:{stage}{_RESET}")
            if note:
                lines.append(f"  {_DIM}Motivo motor: {note}{_RESET}")

            steps = _pipeline_steps_b(c)
            lines.append(f"  {_BOLD}Pipeline{_RESET}")
            for label, done in steps:
                lines.append(f"    {_ok(done)} {label}")
            lines.append(sep)

    lines.append(f"{_BOLD}Gale watcher{_RESET}")
    if bool(gale.get("active", False)):
        lines.append(
            f"  Activo: {gale.get('asset', '')} {str(gale.get('direction', '')).upper()} "
            f"{float(gale.get('secs_remaining', 0.0) or 0.0):.0f}s"
        )
    else:
        lines.append(f"  {_DIM}Sin gale activo{_RESET}")

    lines.append("")
    lines.append(f"{_DIM}La etapa mostrada viene del pipeline real del motor STRAT-B.{_RESET}")
    lines.append(f"{_DIM}Auto-cierre si se detiene el monitor central (sin heartbeat).{_RESET}")
    return "\n".join(lines)


def _pipeline_steps_c(c: dict) -> list[tuple[str, bool]]:
    """Pipeline de 8 etapas para STRAT-C — muestra exactamente qué bloqueó la orden."""
    score    = float(c.get("score", 0.0) or 0.0)    # normalizado 0-100
    raw_score = score * 17.0 / 100.0                  # devolver a 0-17
    payout   = int(c.get("payout", 0) or 0)
    direction = str(c.get("direction", "") or "").lower()
    dist      = c.get("dist_pct", None)
    stage     = str(c.get("raw_reason", "") or "scan").strip().lower()
    conf      = float(c.get("confidence", 0.0) or 0.0)

    # Umbrales STRAT-C
    MIN_SCORE_RAW  = 7.0   # MIN_SCORE del detector (0-17) — sync con main.py --strat-c-min-score=7
    MIN_SCORE_NORM = MIN_SCORE_RAW / 17.0 * 100.0   # ~41.2 normalizado
    MIN_PAYOUT_C   = 80

    has_data  = bool(c.get("asset", ""))
    dir_ok    = direction in ("call", "put")
    payout_ok = payout >= MIN_PAYOUT_C
    score_ok  = score >= MIN_SCORE_NORM
    # "in_window" indica si la señal se generó en segundo 30-41 (campo agregado en bot)
    in_window = bool(c.get("signal_type", None) is not None) or score > 0
    zone_ok   = dist is not None          # zona S/R activa implícita si hay dist
    motor_on  = stage not in ("blocked_readonly",)
    entered   = stage in ("entered",)

    return [
        ("Datos 1m recolectados",            has_data),
        ("Direccion valida (CALL/PUT)",       dir_ok),
        (f"Payout >= {MIN_PAYOUT_C}%",        payout_ok),
        (f"Score >= {MIN_SCORE_RAW:.0f}/17 (>={MIN_SCORE_NORM:.0f}/100)", score_ok),
        ("Zona S/R activa (dist disponible)", zone_ok),
        ("Motor habilitado (--strat-c-enabled)", motor_on),
        ("Candidato en ciclo aceptado",       entered or score_ok),
        ("Orden enviada al broker",           entered),
    ]


def _render_strat_c(state: dict) -> str:
    """Render especializado para STRAT-C con pipeline de 8 etapas."""
    import time as _t
    scans   = int(state.get("total_scans", 0) or 0)
    balance = float(state.get("balance", 0.0) or 0.0)
    wins    = int(state.get("wins", 0) or 0)
    losses  = int(state.get("losses", 0) or 0)
    candidates = list(state.get("strat_c", []) or [])
    gale    = dict(state.get("gale", {}) or {})

    # Segundo actual del reloj local (proxy del broker mientras no hay campo explícito)
    _now_sec = int(_t.time()) % 60
    _in_window = 30 <= _now_sec <= 41

    sep  = f"{_DIM}{'─' * _W}{_RESET}"
    win_color = _GREEN if _in_window else _DIM
    win_label = f"s={_now_sec:02d} {'✅ EN VENTANA' if _in_window else '⏳ fuera s30-41'}"

    lines = [
        f"{_BOLD}{_CYAN}{'═' * _W}{_RESET}",
        f"{_BOLD}{_CYAN}  MONITOR C  ·  STRAT-C  Rechazo M1 (ventana s30-41, exp 60s){_RESET}",
        f"  Scans:{scans}  Balance:${balance:.2f}  W/L:{wins}/{losses}  {win_color}{win_label}{_RESET}",
        sep,
    ]

    if not candidates:
        lines.append(f"  {_DIM}Sin candidatos STRAT-C en este ciclo.{_RESET}")
        lines.append(f"  {_DIM}Esperando deteccion de wick en zona S/R...{_RESET}")
    else:
        top = candidates[0]
        asset     = str(top.get("asset", "") or "")
        direction = str(top.get("direction", "") or "").upper()
        score     = float(top.get("score", 0.0) or 0.0)
        raw_score = score * 17.0 / 100.0
        payout    = int(top.get("payout", 0) or 0)
        dist      = top.get("dist_pct", None)
        dist_txt  = "--" if dist is None else f"{float(dist)*100:.2f}%"

        lines.append(
            f"  {_BOLD}Top señal:{_RESET} {asset:<12} {direction:<4} "
            f"S:{raw_score:.1f}/17 ({score:.0f}/100) P:{payout}% Dist:{dist_txt}"
        )
        lines.append(sep)
        lines.append(f"{_BOLD}Pipeline STRAT-C{_RESET}")
        for label, done in _pipeline_steps_c(top):
            lines.append(f"  {_ok(done)} {label}")
        lines.append(sep)

        if len(candidates) > 1:
            lines.append(f"{_BOLD}Otros candidatos{_RESET}")
            for i, c in enumerate(candidates[1:5], 2):
                d  = str(c.get("direction", "")).upper()
                s  = float(c.get("score", 0.0) or 0.0)
                r  = s * 17.0 / 100.0
                px = int(c.get("payout", 0) or 0)
                di = c.get("dist_pct", None)
                di_txt = "--" if di is None else f"{float(di)*100:.2f}%"
                lines.append(
                    f"  {i}. {str(c.get('asset','')):<12} {d:<4} "
                    f"S:{r:.1f}/17 P:{px}% Dist:{di_txt}"
                )
            lines.append(sep)

    lines.append(f"{_BOLD}Ventana de entrada{_RESET}")
    lines.append(
        f"  {win_color}Segundo actual: {_now_sec:02d}  "
        f"Ventana activa: s30-s41  "
        f"{'✅ DENTRO' if _in_window else '⏳ FUERA'}{_RESET}"
    )
    lines.append(sep)
    lines.append(f"{_BOLD}Gale watcher{_RESET}")
    if bool(gale.get("active", False)):
        lines.append(
            f"  Activo: {gale.get('asset','')} {str(gale.get('direction','')).upper()} "
            f"{float(gale.get('secs_remaining', 0.0) or 0.0):.0f}s"
        )
    else:
        lines.append(f"  {_DIM}Sin gale activo{_RESET}")

    lines.append("")
    lines.append(f"{_DIM}STRAT-C usa su propio cooldown (70s) independiente de A/B.{_RESET}")
    lines.append(f"{_DIM}Auto-cierre si se detiene el monitor central (sin heartbeat).{_RESET}")
    return "\n".join(lines)


def _render_generic(strategy: str, state: dict) -> str:
    scans   = int(state.get("total_scans", 0) or 0)
    balance = float(state.get("balance", 0.0) or 0.0)
    wins    = int(state.get("wins", 0) or 0)
    losses  = int(state.get("losses", 0) or 0)
    key     = {"B": "strat_b", "C": "strat_c"}.get(strategy, "strat_b")
    candidates = list(state.get(key, []) or [])
    gale    = dict(state.get("gale", {}) or {})

    strategy_name = {"B": "Spring / Sweep", "C": "Rechazo M1 (ventana s30-41, exp 60s)"}.get(strategy, "")
    sep = f"{_DIM}{'─' * _W}{_RESET}"

    lines = [
        f"{_BOLD}{_CYAN}{'═' * _W}{_RESET}",
        f"{_BOLD}{_CYAN}  MONITOR {strategy}  ·  STRAT-{strategy}  {strategy_name}{_RESET}",
        f"  Scans:{scans}  Balance:${balance:.2f}  W/L:{wins}/{losses}",
        sep,
        f"{_BOLD}Checklist{_RESET}",
    ]
    for label, done in _checklist_generic(strategy, candidates):
        lines.append(f"  {_ok(done)} {label}")

    lines.append(sep)
    lines.append(f"{_BOLD}Top candidatos{_RESET}")
    if not candidates:
        lines.append(f"  {_DIM}Sin candidatos en este ciclo{_RESET}")
    else:
        for i, c in enumerate(candidates[:5], 1):
            direction = str(c.get("direction", "")).upper()
            score     = float(c.get("score", 0.0) or 0.0)
            payout    = int(c.get("payout", 0) or 0)
            dist      = c.get("dist_pct", None)
            dist_txt  = "--" if dist is None else f"{float(dist)*100:.2f}%"
            lines.append(
                f"  {i}. {str(c.get('asset','')):<12} {direction:<4} "
                f"S:{score:>5.1f} P:{payout:>2}% Dist:{dist_txt}"
            )

    lines.append(sep)
    lines.append(f"{_BOLD}Gale watcher{_RESET}")
    if bool(gale.get("active", False)):
        lines.append(
            f"  Activo: {gale.get('asset','')} {str(gale.get('direction','')).upper()} "
            f"{float(gale.get('secs_remaining', 0.0) or 0.0):.0f}s"
        )
    else:
        lines.append(f"  {_DIM}Sin gale activo{_RESET}")

    lines.append("")
    lines.append(f"{_DIM}Auto-cierre si se detiene el monitor central (sin heartbeat).{_RESET}")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
#  MAIN LOOP
# ─────────────────────────────────────────────────────────────────────────────

def _main() -> int:
    parser = argparse.ArgumentParser(description="Monitor checklist por estrategia")
    parser.add_argument("--strategy", choices=("A", "B", "C"), required=True)
    parser.add_argument("--state-file", required=True)
    parser.add_argument("--interval", type=float, default=0.8)
    parser.add_argument("--stale-sec", type=float, default=8.0)
    args = parser.parse_args()

    state_path = Path(args.state_file)
    strategy   = str(args.strategy)
    # _ANSI_OK ya fue detectado al importar el módulo; no hace falta volver a llamar.
    # En consolas sin ANSI (Windows legacy) usamos cls para evitar acumulación de frames.
    ansi_ok = _ANSI_OK

    def _clear_screen() -> None:
        if ansi_ok:
            sys.stdout.write("\033[H\033[J")
        else:
            os.system("cls" if os.name == "nt" else "clear")

    last_frame = ""

    while True:
        if not state_path.exists():
            msg = "Esperando monitor central..."
            if msg != last_frame:
                _clear_screen()
                sys.stdout.write(msg + "\n")
                sys.stdout.flush()
                last_frame = msg
            time.sleep(max(0.2, args.interval))
            continue

        state = _load_state(state_path)
        heartbeat = float(state.get("generated_at", 0.0) or 0.0)
        age = time.time() - heartbeat if heartbeat > 0 else 9999.0
        if age > float(args.stale_sec):
            _clear_screen()
            sys.stdout.write("Monitor central detenido. Cerrando esta ventana...\n")
            sys.stdout.flush()
            return 0

        # Actualizar caché de pares STRAT-A (solo en ventana A)
        if strategy == "A":
            live_a = list(state.get("strat_a", []) or [])
            _update_strat_a_cache(live_a)
            frame = _render_strat_a(state)
        elif strategy == "B":
            frame = _render_strat_b(state)
        elif strategy == "C":
            frame = _render_strat_c(state)
        else:
            frame = _render_generic(strategy, state)

        if frame != last_frame:
            _clear_screen()
            sys.stdout.write(frame)
            sys.stdout.write("\n")
            sys.stdout.flush()
            last_frame = frame

        time.sleep(max(0.2, args.interval))


if __name__ == "__main__":
    raise SystemExit(_main())
