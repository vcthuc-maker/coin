"""Read and analyze hourly archived public market snapshots.

OI change uses same exchange/coin/unit and requires observations 3–5 hours
apart. Spot trades are only point-in-time samples, NOT 4h CVD.
"""
import json
from pathlib import Path

import pandas as pd

STORE = Path(__file__).resolve().parent / "data" / "flow"


def read_archive(limit_months=3):
    paths = sorted(STORE.glob("????-??.jsonl"))[-limit_months:]
    rows = []
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    if not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(rows)
    frame["time"] = pd.to_datetime(frame["collected_at_utc"], utc=True, errors="coerce")
    for key in ("oi_value", "price_usdt", "spot_sample_imbalance_pct",
                "spot_sample_minutes", "spot_sample_count"):
        if key not in frame:
            frame[key] = None
        frame[key] = pd.to_numeric(frame[key], errors="coerce")
    frame = frame.dropna(subset=["time"]).sort_values("time")
    return frame.drop_duplicates(["hour_utc", "exchange", "coin"], keep="last")


def summarize_flow(frame, now=None):
    fields = ["coin", "sàn", "cập nhật UTC", "độ trễ (giờ)",
              "OI đơn vị", "OI hiện tại", "OI 4H % (ước tính)",
              "số giờ so sánh", "Spot imbalance % (mẫu)",
              "thời lượng Spot mẫu (phút)", "số trades mẫu"]
    if frame.empty:
        return pd.DataFrame(columns=fields)
    now = pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now)
    if now.tzinfo is None:
        now = now.tz_localize("UTC")
    output = []
    for (ex, coin), group in frame.groupby(["exchange", "coin"]):
        group = group.sort_values("time")
        recent = group.iloc[-1]
        age_h = (now - recent["time"]).total_seconds() / 3600
        oi_change = None
        delta_h = None
        # Choose closest to four hours earlier; don't extrapolate or use a wrong unit.
        eligible = group.iloc[:-1].copy()
        if not eligible.empty:
            eligible["delta_h"] = (recent["time"] - eligible["time"]).dt.total_seconds() / 3600
            eligible = eligible[(eligible["delta_h"] >= 3) & (eligible["delta_h"] <= 5) &
                                (eligible["oi_unit"] == recent["oi_unit"]) &
                                (eligible["oi_value"] > 0)]
            if not eligible.empty and pd.notna(recent["oi_value"]):
                ref = eligible.iloc[(eligible["delta_h"] - 4).abs().argsort().iloc[0]]
                oi_change = round((recent["oi_value"] / ref["oi_value"] - 1) * 100, 3)
                delta_h = round(float(ref["delta_h"]), 2)
        output.append({
            "coin": coin, "sàn": ex, "cập nhật UTC": recent["time"],
            "độ trễ (giờ)": round(age_h, 2), "OI đơn vị": recent["oi_unit"],
            "OI hiện tại": recent["oi_value"],
            "OI 4H % (ước tính)": oi_change, "số giờ so sánh": delta_h,
            "Spot imbalance % (mẫu)": recent["spot_sample_imbalance_pct"],
            "thời lượng Spot mẫu (phút)": recent["spot_sample_minutes"],
            "số trades mẫu": recent["spot_sample_count"],
        })
    result = pd.DataFrame(output, columns=fields)
    return result.sort_values(["độ trễ (giờ)", "coin", "sàn"])


def historic_coverage(frame):
    if frame.empty:
        return {"rows": 0, "coins": 0, "last": None}
    return {
        "rows": len(frame), "coins": frame["coin"].nunique(),
        "last": frame["time"].max(),
    }
