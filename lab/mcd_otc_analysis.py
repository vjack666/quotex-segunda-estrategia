"""
Análisis forense de MCD_OTC PUT - 2026-05-04 13:00:57
Operación ID 31 - LOSS -$2.44
"""
import json
from datetime import datetime, timezone, timedelta

TZ = timezone(timedelta(hours=-3))

# ══════════════════════════════════════════════════════════════
# DATOS DE LA OPERACIÓN (extraídos de la caja negra)
# ══════════════════════════════════════════════════════════════
TRADE = {
    "id": 31,
    "scanned_at": "2026-05-04T13:00:46-03:00",
    "asset": "MCD_otc",
    "direction": "PUT",
    "payout": 82,
    "amount": 2.44,
    "stage": "breakout",
    "score": 56.0,
    "score_threshold": 65,
    "score_breakdown": {
        "compression": 17.04,
        "bounce": 7.0,
        "trend": 24.25,
        "payout": 2.67,
        "age_adjustment": -12.0,
        "hist_level": 18.0,
        "weak_confirmation": -10.0,
        "breakout_bonus": 6.0,
        "order_block": 3.0,
    },
    "entry_mode": "breakout_below",
    "force_execute": True,
    "zone_ceiling": 255.35,
    "zone_floor": 254.969,
    "zone_range_pct": 0.001493,
    "zone_age_min": 6.43,
    "reversal_pattern": "none",
    "ticket_open_price": 254.629,
    "ticket_close_price": 254.682,
    "ticket_opened_at": "2026-05-04T13:00:57-03:00",
    "ticket_closed_at": "2026-05-04T13:06:03-03:00",
    "entry_time_since_open": 46.1,   # segundos desde apertura de vela 1m
    "entry_secs_to_close": 13.9,     # segundos hasta cierre de vela 1m
    "outcome": "LOSS",
    "profit": -2.44,
    "pre_objectives_ok": False,
    "pre_objectives_note": "fallaron: score_ok, timing_ok",
    "order_block_info": "tf=3m | +3 PUT alineado con BEAR OB (fuera de zona) | BEAR @ 254.993–255.112 | mitigado | 3 velas",
    "ma_info": "trend=FLAT cross=NONE ma35=255.227 ma50=255.254 px<MA50",
}

CANDLES_5M_RAW = [
    {"ts": 1777904400, "open": 255.529, "high": 255.644, "low": 255.529, "close": 255.638},
    {"ts": 1777904700, "open": 255.638, "high": 255.730, "low": 255.596, "close": 255.623},
    {"ts": 1777905000, "open": 255.627, "high": 255.680, "low": 255.451, "close": 255.514},
    {"ts": 1777905300, "open": 255.514, "high": 255.603, "low": 255.452, "close": 255.581},
    {"ts": 1777905600, "open": 255.581, "high": 255.650, "low": 255.504, "close": 255.504},
    {"ts": 1777905900, "open": 255.504, "high": 255.573, "low": 255.442, "close": 255.508},
    {"ts": 1777906200, "open": 255.506, "high": 255.585, "low": 255.459, "close": 255.515},
    {"ts": 1777906500, "open": 255.515, "high": 255.533, "low": 255.314, "close": 255.327},
    {"ts": 1777906800, "open": 255.327, "high": 255.331, "low": 255.147, "close": 255.169},
    {"ts": 1777907100, "open": 255.169, "high": 255.177, "low": 255.000, "close": 255.177},
    {"ts": 1777907400, "open": 255.180, "high": 255.227, "low": 255.072, "close": 255.143},
    {"ts": 1777907700, "open": 255.143, "high": 255.236, "low": 255.105, "close": 255.122},
    {"ts": 1777908000, "open": 255.122, "high": 255.174, "low": 255.006, "close": 255.146},
    {"ts": 1777908300, "open": 255.150, "high": 255.232, "low": 255.132, "close": 255.149},
    {"ts": 1777908600, "open": 255.149, "high": 255.240, "low": 255.072, "close": 255.106},
    {"ts": 1777908900, "open": 255.118, "high": 255.138, "low": 254.985, "close": 254.985},  # TOCA PISO
    {"ts": 1777909200, "open": 254.985, "high": 255.024, "low": 254.910, "close": 255.020},
    {"ts": 1777909500, "open": 255.020, "high": 255.101, "low": 254.993, "close": 255.064},
    {"ts": 1777909800, "open": 255.042, "high": 255.125, "low": 254.853, "close": 254.866},  # PRIMERA ROTURA (cierre < 254.969)
    {"ts": 1777910100, "open": 254.866, "high": 254.866, "low": 254.650, "close": 254.653},  # SEÑAL → ENTRY en esta vela
]

# ══════════════════════════════════════════════════════════════
# ANÁLISIS
# ══════════════════════════════════════════════════════════════
ZONE_FLOOR = 254.969
ZONE_CEILING = 255.35
ENTRY_PRICE = 254.629
CLOSE_PRICE = 254.682

entry_distance_below_floor = ZONE_FLOOR - ENTRY_PRICE
entry_distance_pct = entry_distance_below_floor / ZONE_FLOOR * 100

first_break_candle = CANDLES_5M_RAW[-2]  # ts=1777909800
signal_candle = CANDLES_5M_RAW[-1]       # ts=1777910100

momentum_1st_break = first_break_candle['open'] - first_break_candle['close']  # caída en vela de rotura
momentum_signal = signal_candle['open'] - signal_candle['close']               # caída en vela de señal

print("=" * 70)
print(f"ANÁLISIS FORENSE: MCD_OTC PUT — 2026-05-04 13:00:57")
print("=" * 70)

print("\n📍 ZONA DE CONSOLIDACIÓN")
print(f"   Piso:    {ZONE_FLOOR}")
print(f"   Techo:   {ZONE_CEILING}")
print(f"   Rango:   {(ZONE_CEILING-ZONE_FLOOR):.3f}  ({TRADE['zone_range_pct']*100:.2f}%)")
print(f"   Edad:    {TRADE['zone_age_min']:.1f} min al momento de entrada")

print("\n📊 SCORE BREAKDOWN")
print(f"   Score total:   {TRADE['score']}/100  (umbral={TRADE['score_threshold']})")
print(f"   ⚠ BAJO UMBRAL: {TRADE['score'] < TRADE['score_threshold']}")
print(f"   Compresión:    +{TRADE['score_breakdown']['compression']}")
print(f"   Bounce:        +{TRADE['score_breakdown']['bounce']}  ← SIN reversal (none)")
print(f"   Trend:         +{TRADE['score_breakdown']['trend']}")
print(f"   Payout:        +{TRADE['score_breakdown']['payout']}  ← MUY BAJO (82% payout)")
print(f"   Age adj:       {TRADE['score_breakdown']['age_adjustment']}  ← PENALIZACIÓN zona joven")
print(f"   Hist level:    +{TRADE['score_breakdown']['hist_level']}")
print(f"   Weak confirm:  {TRADE['score_breakdown']['weak_confirmation']}  ← PENALIZACIÓN sin reversal")
print(f"   Breakout:      +{TRADE['score_breakdown']['breakout_bonus']}")
print(f"   Order block:   +{TRADE['score_breakdown']['order_block']}")

print("\n⏱ TIMING DE ENTRADA")
print(f"   Apertura vela 1m: 13:00:00")
print(f"   Entrada real:     13:00:57  (+{TRADE['entry_time_since_open']:.0f}s en vela)")
print(f"   Cierre vela 1m:   13:01:00  (solo {TRADE['entry_secs_to_close']:.0f}s restantes)")
print(f"   ⚠ ENTRADA MUY TARDÍA: 46s en una vela de 60s (77% del tiempo consumido)")

print("\n📉 DISTANCIA PRECIO vs ZONA")
print(f"   Piso zona:         {ZONE_FLOOR}")
print(f"   Precio de entrada: {ENTRY_PRICE}")
print(f"   Distancia bajo piso: -{entry_distance_below_floor:.3f}  (-{entry_distance_pct:.3f}%)")
print(f"   ⚠ ENTRADA SOBREPASADA: el precio ya cayó {entry_distance_pct:.2f}% bajo el piso")

print("\n🕯 ANÁLISIS DE VELAS CLAVE")
print(f"   Vela de rotura (#19, ts=1777909800):")
print(f"     open={first_break_candle['open']}  close={first_break_candle['close']}")
print(f"     Caída: {momentum_1st_break:.3f} pts  (rotura del piso {ZONE_FLOOR})")
print(f"   Vela de señal (#20, ts=1777910100) — entrada aquí:")
print(f"     open={signal_candle['open']}  close={signal_candle['close']}")
print(f"     Caída adicional: {momentum_signal:.3f} pts")
print(f"   Caída acumulada desde piso al entrar: {entry_distance_below_floor:.3f} pts")
print(f"   Ticket cerró en: {CLOSE_PRICE} (+{CLOSE_PRICE - ENTRY_PRICE:.3f} vs entry = PÉRDIDA PUT)")

print("\n🔍 DIAGNÓSTICO DE CAUSAS (4 problemas)")
print()
print("  1. SCORE BAJO UMBRAL pero force_execute=True lo ignoró")
print(f"     Score: {TRADE['score']}/100 < umbral {TRADE['score_threshold']}/100")
print()
print("  2. TIMING TARDÍO — entrada en el último 23% de la vela")
print(f"     +46s en vela de 60s → pre_objectives falló timing_ok")
print()
print("  3. ENTRADA SOBREEXTENDIDA — precio ya bajó demasiado")
print(f"     -{entry_distance_pct:.2f}% bajo piso al entrar → momentum agotado")
print()
print("  4. ORDEN BLOCK MITIGADO → señal débil")
print(f"     BEAR OB ya mitigado (3 velas) → soporte menos confiable")

print()
print("=" * 70)
print("🔴 VEREDICTO: Entrada que NO debió ejecutarse")
print("   El bot entró en un breakout ya consumido, con score bajo, timing")
print("   tardío, y sin patrón de reversión confirmado.")
print("=" * 70)

# ══════════════════════════════════════════════════════════════
# FILTROS RECOMENDADOS
# ══════════════════════════════════════════════════════════════
print()
print("═" * 70)
print("🛡 FILTROS PROPUESTOS PARA breakout_below / breakout_above")
print("═" * 70)
print()
print("FILTRO 1 — Score estricto en breakout sin reversal")
print("  Condición: si reversal_pattern=='none' Y stage=='breakout'")
print("  Regla:     score >= score_threshold  (NO force_execute sin reversal)")
print("  Esta entrada: score=56 < 65 → RECHAZAR")
print()
print("FILTRO 2 — Distancia máxima de sobreextensión")
print("  Condición: breakout_below")
print("  Regla:     (zone_floor - entry_price) / zone_floor <= 0.0012  (0.12%)")
print(f"  Esta entrada: {entry_distance_pct:.3f}% → RECHAZAR (supera 0.12%)")
print()
print("FILTRO 3 — Timing de entrada")
print("  Condición: entry_time_since_open > 40s Y entry_secs_to_close < 20s")
print("  Regla:     RECHAZAR entrada tardía en breakout sin reversal")
print(f"  Esta entrada: +46s en vela → RECHAZAR")
print()
print("FILTRO 4 — Order Block mitigado + sin reversal = reducir peso")
print("  Condición: order_block mitigado Y reversal_pattern='none'")
print("  Regla:     NO sumar order_block score si ya está mitigado")
print("  Esta entrada: BEAR OB mitigado sumó +3 → habría sido 53/100")
print()
print("FILTRO 5 — Segunda rotura de la misma zona (re-entry check)")
print("  La zona 254.969-255.35 ya había roto a las 12:56 (expired_zone id=50)")
print("  y volvió a romper 4 min después. Segunda rotura = momentum débil.")
print("  Regla: si la zona ya expiró (BROKEN_BELOW) hace < 10 min → reducir score -15")
print()
print("RESUMEN FILTROS — si aplica 3 o más → RECHAZAR:")
print(f"  ✗ F1: score {TRADE['score']} < {TRADE['score_threshold']} (sin reversal) → RECHAZAR")
print(f"  ✗ F2: sobreextensión {entry_distance_pct:.3f}% > 0.12% → RECHAZAR")
print(f"  ✗ F3: timing tardío 46s > 40s → RECHAZAR")
print(f"  ✓ F4: OB mitigado (aplicable)")
print(f"  ✗ F5: segunda rotura misma zona → RECHAZAR")
print()
print("Con estos 5 filtros, esta operación sería RECHAZADA por F1, F2, F3 y F5.")
