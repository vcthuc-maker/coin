"""Forward-only outcomes for experimental MEXC watch signals.

Uses only FUTURE ticker snapshots to measure post-alert close-to-close returns.
Not exact candle high/low, TP-first, or a tradable fill. Missing snapshots
are censored, never counted as wins/losses.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

STORE = Path(__file__).resolve().parent / "data" / "mexc_quality" / "signals.jsonl"
WINDOWS = {15: (12, 22), 30: (25, 40), 60: (52, 73)}
EVENT_COOLDOWN = 3600
MAX_EVENTS = 4500


def read_events(path=STORE):
    if not path.exists():
        return []
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                events.append(json.loads(line))
            except (ValueError, TypeError):
                continue
    return events[-MAX_EVENTS:]


def update_events(events, rows, timestamp, markets, *, min_age=EVENT_COOLDOWN):
    """Timestamp is the UTC observation time (seconds); never use later observations.

    Rows from candle classifier are research flags, not trade recommendations.
    """
    now = int(timestamp)
    current = list(events)
    for row in rows:
        if row.get("trạng thái", "").startswith("3."):
            continue  # rejection is a risk warning, not an entry candidate
        symbol = row["coin"].replace("/USDT", "_USDT")
        # Use actual ticker observed at collection time for forward comparison.
        observed = markets.get(symbol)
        if observed is None or observed[0] <= 0:
            continue
        if any(e["coin"] == row["coin"] and e["trạng thái"] == row["trạng thái"]
               and 0 <= now - int(e["ts"]) < min_age for e in current):
            continue
        current.append({
            "ts": now, "coin": row["coin"], "trạng thái": row["trạng thái"],
            "signal_close_5m": row["giá"],
            "entry_snapshot_price": float(observed[0]),
            "metrics": {str(k): None for k in WINDOWS},
            "stale": False,
        })
    # Evaluate outcomes against only observed snapshot from THIS run.
    for e in current:
        age_minutes = (now - int(e["ts"])) / 60
        if age_minutes <= 0:
            continue
        symbol = e["coin"].replace("/USDT", "_USDT")
        observed = markets.get(symbol)
        for minutes, (low, high) in WINDOWS.items():
            key = str(minutes)
            if e["metrics"].get(key) is not None:
                continue
            if low <= age_minutes <= high and observed and observed[0] > 0:
                e["metrics"][key] = round(
                    (float(observed[0])/float(e["entry_snapshot_price"])-1)*100, 4)
            elif age_minutes > high:
                e["metrics"][key] = {"missing": True}
    return current[-MAX_EVENTS:]


def write_events(events, path=STORE):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text("".join(json.dumps(e, ensure_ascii=False)+"\n" for e in events),
                    encoding="utf-8")
    temp.replace(path)


def outcomes_table(events, last=100):
    rows = []
    for e in sorted(events, key=lambda e:int(e["ts"]), reverse=True)[:last]:
        metrics = e.get("metrics", {})
        def number(key):
            val = metrics.get(key)
            return float(val) if isinstance(val, (float, int)) else None
        rows.append({
            "coin": e["coin"], "trạng thái": e["trạng thái"],
            "lúc UTC": pd.to_datetime(int(e["ts"]), unit="s", utc=True),
            "giá quan sát": float(e["entry_snapshot_price"]),
            "15 phút %": number("15"), "30 phút %": number("30"),
            "60 phút %": number("60"),
        })
    return pd.DataFrame(rows)


def simple_summary(events):
    data = outcomes_table(events, last=MAX_EVENTS)
    if data.empty:
        return {"evaluated_15":0, "positive_15_pct":None, "avg_15_pct":None,
                "dump_15_pct":None, "by_state":[] }
    valid = data["15 phút %"].dropna()
    groups = []
    for state, part in data.groupby("trạng thái"):
        observed = part["15 phút %"].dropna()
        if len(observed):
            groups.append({
                "trạng thái": state,
                "số tín hiệu có kết quả 15m": int(len(observed)),
                "tăng sau 15m %": round(100 * float((observed > 0).mean()), 2),
                "giảm sâu <=-2% sau 15m": round(100 * float((observed <= -2).mean()), 2),
                "lợi nhuận TB 15m % (chưa phí)": round(float(observed.mean()), 3),
            })
    return {
        "evaluated_15": len(valid),
        "positive_15_pct": round(100*float((valid > 0).mean()),2) if len(valid) else None,
        "avg_15_pct": round(float(valid.mean()),3) if len(valid) else None,
        "dump_15_pct": round(100*float((valid <= -2).mean()),2) if len(valid) else None,
        "by_state": groups,
    }
