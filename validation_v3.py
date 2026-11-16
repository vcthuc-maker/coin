"""Pre-Pump V3.0: chronological, multi-horizon retrospective evaluation.

Important: Not a live win rate or validated AI model. Public OHLCV only.
The scoring callback sees data strictly BEFORE the entry candle.
All outcomes assume next OPEN entry and conservative stop-first on intrabar ties.
"""
from __future__ import annotations

import math
import pandas as pd

PHASE_GROUPS = {
    "NÉN LÂU — ƯU TIÊN 4H": "Nén lâu ưu tiên",
    "ĐANG TÍCH LŨY": "Tích lũy theo dõi",
    "VỪA BREAKOUT — CÓ THỂ TIẾP DIỄN": "Breakout tiếp diễn",
    "BREAKOUT CẦN XÁC NHẬN": "Breakout chưa xác nhận",
}
HORIZONS = {4: (1., 2., 3., 4.), 8: (2., 4., 6.), 24: (4., 6., 10.)}


def valid_frame(frame):
    if frame is None or len(frame) < 135:
        return False
    return all(k in frame.columns for k in ("t", "open", "high", "low", "close"))


def collect_events(candles, signal_func, exchange, pair, native, turnover,
                   stride=24, min_history=105):
    """Non-overlapping 24h event windows PER exchange/pair.
    Baseline = all sampled windows, with identical universe and dates.
    """
    if stride < 24:
        raise ValueError("stride must be at least 24 for independent 24h windows")
    if not valid_frame(candles):
        return []
    base = pair.rsplit("/", 1)[0]
    events = []
    for end in range(min_history, len(candles) - 24, stride):
        known = candles.iloc[:end]
        try:
            sig = signal_func(exchange, base, native,
                              float(known["close"].iloc[-1]),
                              turnover, candles=known)
        except (ValueError, IndexError, ZeroDivisionError, TypeError, KeyError):
            sig = None
        phase = sig.get("trạng thái 4H") if sig else None
        grade = int(sig.get("điểm 4H /100", 0)) if sig else 0
        future = candles.iloc[end:end+24]
        entry = float(future["open"].iloc[0])
        if not math.isfinite(entry) or entry <= 0:
            continue
        if not all(math.isfinite(float(v)) for v in
                   future[["high", "low", "close"]].to_numpy().ravel()):
            continue
        # Entry bar is next 1H candle; future is never passed to signal_func.
        events.append({
            "sàn": exchange, "coin": pair, "nhóm": PHASE_GROUPS.get(phase),
            "điểm": grade, "giá vào": entry, "giờ vào UTC": int(future["t"].iloc[0]),
            "future": future[["high", "low", "close"]].to_numpy(dtype=float),
        })
    return events


def resolve_outcome(event, horizon, target_pct, stop_pct=2., cost_pct=.25):
    """Simulate first touch of TP or SL within horizon. On both, SL first."""
    p0 = event["giá vào"]
    take = p0 * (1 + target_pct / 100)
    stop = p0 * (1 - stop_pct / 100)
    future = event["future"][:horizon]
    high_max = float(future[:, 0].max())
    low_min = float(future[:, 1].min())
    mfe = (high_max / p0 - 1) * 100
    mae = (low_min / p0 - 1) * 100
    exit_price = float(future[-1, 2])
    outcome = "HẾT HẠN"
    for hi, lo, _ in future:
        if lo <= stop:
            exit_price, outcome = stop, "STOP"
            break
        if hi >= take:
            exit_price, outcome = take, "TARGET"
            break
    pnl = (exit_price / p0 - 1) * 100 - cost_pct
    return {
        "kết quả": outcome, "lãi/lỗ ròng %": round(pnl, 4),
        "đạt mục tiêu": int(outcome == "TARGET"),
        "MFE %": round(mfe, 4), "MAE %": round(mae, 4),
    }


def evaluate(all_events, horizon=4, target_pct=4., stop_pct=2., cost_pct=.25):
    rows = []
    for ev in all_events:
        result = resolve_outcome(ev, horizon, target_pct, stop_pct, cost_pct)
        rows.append({
            "sàn": ev["sàn"], "coin": ev["coin"],
            "giờ vào UTC": pd.to_datetime(ev["giờ vào UTC"], unit="ms", utc=True),
            "nhóm": ev["nhóm"] if ev["nhóm"] else "BASELINE MỌI THỜI ĐIỂM",
            "điểm": ev["điểm"], "khung giờ": horizon,
            "mục tiêu %": target_pct, **result,
        })
    return pd.DataFrame(rows)


def summarize(trades):
    if trades.empty:
        return {"số tín hiệu": 0, "số coin": 0,
                "đạt mục tiêu %": None, "lãi/lỗ TB ròng %": None,
                "profit factor": None, "MFE TB %": None, "MAE TB %": None}
    pnl = trades["lãi/lỗ ròng %"]
    gains = pnl[pnl > 0].sum()
    losses = -pnl[pnl < 0].sum()
    return {
        "số tín hiệu": len(trades),
        "số coin": trades["coin"].nunique(),
        "đạt mục tiêu %": round(100 * float(trades["đạt mục tiêu"].mean()), 2),
        "lãi/lỗ TB ròng %": round(float(pnl.mean()), 4),
        "profit factor": round(float(gains / losses), 3) if losses > 0 else None,
        "MFE TB %": round(float(trades["MFE %"].mean()), 3),
        "MAE TB %": round(float(trades["MAE %"].mean()), 3),
    }


def temporal_split(all_events, holdout_fraction=.30, embargo_hours=24):
    """Global UTC split; exclusion band protects independence around boundary.

    Backtest parameters may already be informed by previous observations:
    a time split here is NOT a pristine untouched out-of-sample test.
    """
    if not all_events:
        return [], [], None
    stamps = sorted(set(ev["giờ vào UTC"] for ev in all_events))
    split_idx = min(len(stamps)-1, max(0, int(len(stamps)*(1-holdout_fraction))))
    boundary = stamps[split_idx]
    gap_ms = embargo_hours * 3600 * 1000
    develop = [e for e in all_events if e["giờ vào UTC"] + gap_ms < boundary]
    holdout = [e for e in all_events if e["giờ vào UTC"] >= boundary]
    return develop, holdout, pd.to_datetime(boundary, unit="ms", utc=True)


def report_rows(events, label, stop_pct=2., cost_pct=.25):
    """Every target is shown; no search for a best setting and no cherry-picking."""
    rows = []
    selected = [ev for ev in events if ev["nhóm"] is not None]
    baseline = events  # all eligible intervals; not randomly fabricated controls
    for horizon, goals in HORIZONS.items():
        for goal in goals:
            for group_label, subset in (("Scanner", selected), ("Baseline định kỳ", baseline)):
                frame = evaluate(subset, horizon, goal, stop_pct, cost_pct)
                rows.append({
                    "tập dữ liệu": label, "loại": group_label,
                    "khung giờ": horizon, "mục tiêu %": goal,
                    **summarize(frame),
                })
    return pd.DataFrame(rows)


def report_groups(holdout_events, stop_pct=2., cost_pct=.25, horizon=4, goal=4.):
    active = [e for e in holdout_events if e["nhóm"] is not None]
    rows = []
    for group in sorted({e["nhóm"] for e in active}):
        trades = evaluate([e for e in active if e["nhóm"] == group],
                          horizon, goal, stop_pct, cost_pct)
        rows.append({"nhóm": group, **summarize(trades)})
    return pd.DataFrame(rows)
