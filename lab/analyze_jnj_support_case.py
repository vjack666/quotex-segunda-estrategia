import csv
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

ENTRY_ISO = "2026-04-29T11:22:26-03:00"
CSV_PATH = Path("data/exports/20260429_112621_JNJ_otc_multiframe_2dias.csv")


def load_rows(path: Path):
    rows_1m = []
    rows_5m = []
    with path.open("r", encoding="utf-8", newline="") as f:
        r = csv.DictReader(f)
        for row in r:
            ts = datetime.fromisoformat(row["iso_broker"])
            row["_dt"] = ts
            row["low"] = float(row["low"])
            row["high"] = float(row["high"])
            row["close"] = float(row["close"])
            row["open"] = float(row["open"])
            if row["timeframe"] == "1m":
                rows_1m.append(row)
            elif row["timeframe"] == "5m":
                rows_5m.append(row)
    return rows_1m, rows_5m


def main():
    entry_dt = datetime.fromisoformat(ENTRY_ISO)
    rows_1m, rows_5m = load_rows(CSV_PATH)

    w_start = entry_dt - timedelta(minutes=50)
    w_end = entry_dt + timedelta(minutes=20)
    win_1m = [x for x in rows_1m if w_start <= x["_dt"] <= w_end]

    clusters = defaultdict(lambda: {"touches": 0, "last_touch": None, "min_low": 10**9, "max_low": -10**9})
    for x in win_1m:
        bucket = round(x["low"], 2)
        c = clusters[bucket]
        c["touches"] += 1
        c["last_touch"] = x["_dt"]
        c["min_low"] = min(c["min_low"], x["low"])
        c["max_low"] = max(c["max_low"], x["low"])

    rank = sorted(clusters.items(), key=lambda kv: (kv[1]["touches"], kv[1]["last_touch"]), reverse=True)

    w5_start = entry_dt - timedelta(hours=3)
    w5 = [x for x in rows_5m if w5_start <= x["_dt"] <= entry_dt]
    cl5 = defaultdict(int)
    for x in w5:
        cl5[round(x["low"], 2)] += 1
    rank5 = sorted(cl5.items(), key=lambda kv: kv[1], reverse=True)

    entry_price = None
    for x in rows_1m:
        if abs((x["_dt"] - entry_dt).total_seconds()) <= 60:
            entry_price = x["close"]
            break

    print("ENTRY_ISO", ENTRY_ISO)
    print("ENTRY_PRICE", f"{entry_price:.5f}" if entry_price is not None else "NA")
    print("WINDOW_1M_CANDLES", len(win_1m))
    print("TOP_SUPPORTS_1M")
    for level, d in rank[:8]:
        width = d["max_low"] - d["min_low"]
        print(f"  {level:.2f} touches={d['touches']} width={width:.5f} last={d['last_touch'].isoformat()}")

    print("TOP_SUPPORTS_5M")
    for level, touches in rank5[:8]:
        print(f"  {level:.2f} touches={touches}")

    if rank:
        best_level = rank[0][0]
        print("BEST_SUPPORT", f"{best_level:.2f}")
        print("ENTRY_ZONE", f"[{best_level + 0.03:.2f}, {best_level + 0.06:.2f}]")


if __name__ == "__main__":
    main()
