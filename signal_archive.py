"""Read archived scanner signal snapshots; do not claim prospective win rate.

The 4H comparison is a spot *snapshot price-to-price* change, not an executable
trade, not TP-before-SL, and not a complete future candle path.
"""
import json
from pathlib import Path
import pandas as pd

STORE = Path(__file__).resolve().parent / "data" / "signals"


def load_signals(limit_months=3):
    paths = sorted(STORE.glob("????-??.jsonl"))[-limit_months:]
    rows = []
    for p in paths:
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    if not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(rows)
    frame["time"] = pd.to_datetime(frame["collected_at_utc"], utc=True, errors="coerce")
    frame["score"] = pd.to_numeric(frame["score"], errors="coerce")
    frame["snapshot_price_usdt"] = pd.to_numeric(frame["snapshot_price_usdt"], errors="coerce")
    return (frame.dropna(subset=["time"])
            .sort_values("time")
            .drop_duplicates(["hour_utc", "exchange", "coin"], keep="last"))


def tracking_table(signals, market_flow):
    cols = ["sàn", "coin", "tín hiệu lúc UTC", "trạng thái", "điểm",
            "nén giờ", "giá chụp", "giá sau ~4H",
            "biến động ~4H %", "khoảng cách giờ"]
    if signals.empty:
        return pd.DataFrame(columns=cols)
    result = []
    for _, item in signals.sort_values("time", ascending=False).head(200).iterrows():
        later = pd.DataFrame()
        if not market_flow.empty:
            later = market_flow[
                (market_flow["exchange"] == item["exchange"]) &
                (market_flow["coin"] == item["coin"]) &
                ((market_flow["time"] - item["time"]).dt.total_seconds() / 3600).between(3.5, 4.5)]
        follow = later.iloc[(later["time"] - (item["time"] + pd.Timedelta(hours=4))).abs().argsort().iloc[0]] if not later.empty else None
        start = item["snapshot_price_usdt"]
        finish = float(follow["price_usdt"]) if follow is not None else None
        growth = (finish / start - 1) * 100 if finish is not None and start > 0 else None
        result.append({
            "sàn": item["exchange"], "coin": item["coin"],
            "tín hiệu lúc UTC": item["time"], "trạng thái": item["phase"],
            "điểm": item["score"], "nén giờ": item["compression_hours"],
            "giá chụp": start, "giá sau ~4H": finish,
            "biến động ~4H %": round(growth, 3) if growth is not None else None,
            "khoảng cách giờ": round((follow["time"] - item["time"]).total_seconds()/3600, 2)
                                 if follow is not None else None,
        })
    return pd.DataFrame(result, columns=cols)
