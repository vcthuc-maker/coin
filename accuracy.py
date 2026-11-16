"""Retrospective, exploratory replay for Pre-Pump Scanner.
Not a prospective accuracy estimate. Uses only CLOSED 1H candles.
Entry = next candle's open; evaluates next 4 closed candles.
"""
import math
import pandas as pd

TRADE_PHASES = {
    "NÉN LÂU — ƯU TIÊN 4H": "Nén lâu ưu tiên",
    "ĐANG TÍCH LŨY": "Tích lũy theo dõi",
    "VỪA BREAKOUT — CÓ THỂ TIẾP DIỄN": "Breakout tiếp diễn",
    "BREAKOUT CẦN XÁC NHẬN": "Breakout cần xác nhận",
}

def replay(df, score_signal, exchange, symbol, turnover=0, take_pct=4.0,
           stop_pct=2.0, roundtrip_cost_pct=0.25, stride=4):
    """Returns independent nonoverlapping 4H evaluations for one exchange/pair.
    The signal function receives only historical candles through the cutoff.
    In an intrabar TP+SL tie, count SL first (conservative).
    """
    if not 0 < stop_pct < 100 or not 0 < take_pct < 100:
        raise ValueError("Take/stop phải trong khoảng (0, 100)")
    if not 0 <= roundtrip_cost_pct < 10:
        raise ValueError("Chi phí không hợp lệ")
    if stride < 4:
        raise ValueError("Bước tín hiệu cần >= 4 để tránh chồng thời gian.")
    entries = []
    if len(df) < 80:
        return pd.DataFrame()
    for end in range(75, len(df) - 4, stride):
        past = df.iloc[:end].copy()
        try:
            prediction = score_signal(
                exchange, symbol.split("/")[0], symbol, float(past["close"].iloc[-1]),
                turnover, candles=past)
        except (ValueError, ZeroDivisionError, IndexError, KeyError, TypeError):
            continue
        if not prediction:
            continue
        phase = prediction["trạng thái 4H"]
        if phase not in TRADE_PHASES:
            continue
        next_four = df.iloc[end:end + 4]
        if len(next_four) < 4:
            continue
        entry_price = float(next_four["open"].iloc[0])
        if not math.isfinite(entry_price) or entry_price <= 0:
            continue
        take = entry_price * (1 + take_pct / 100)
        stop = entry_price * (1 - stop_pct / 100)
        outcome = "HẾT 4H"
        exit_price = float(next_four["close"].iloc[-1])
        for _, candle in next_four.iterrows():
            hit_stop = float(candle["low"]) <= stop
            hit_take = float(candle["high"]) >= take
            if hit_stop:
                exit_price, outcome = stop, "CẮT LỖ"
                break
            if hit_take:
                exit_price, outcome = take, "ĐẠT MỤC TIÊU"
                break
        gross = (exit_price / entry_price - 1) * 100
        net = gross - roundtrip_cost_pct
        entries.append({
            "sàn": exchange, "coin": symbol, "nhóm": TRADE_PHASES[phase],
            "điểm": int(prediction["điểm 4H /100"]),
            "thời điểm tín hiệu UTC": pd.to_datetime(int(past["t"].iloc[-1]), unit="ms", utc=True),
            "giá vào (nến tiếp)": entry_price,
            "giá thoát": exit_price, "kết quả": outcome,
            "lãi/lỗ sau chi phí %": round(net, 3),
            "đạt mục tiêu": int(outcome == "ĐẠT MỤC TIÊU"),
        })
    return pd.DataFrame(entries)

def metrics(trades):
    if trades.empty:
        return {
            "số tín hiệu": 0, "tỷ lệ đạt mục tiêu %": None,
            "lợi nhuận TB sau chi phí %": None, "profit factor": None,
            "tỷ lệ lãi sau chi phí %": None
        }
    vals = trades["lãi/lỗ sau chi phí %"]
    gains = float(vals[vals > 0].sum())
    losses = float(-vals[vals < 0].sum())
    pf = round(gains / losses, 2) if losses > 0 else None
    return {
        "số tín hiệu": len(trades),
        "tỷ lệ đạt mục tiêu %": round(float(trades["đạt mục tiêu"].mean() * 100), 1),
        "lợi nhuận TB sau chi phí %": round(float(vals.mean()), 3),
        "profit factor": pf,
        "tỷ lệ lãi sau chi phí %": round(float((vals > 0).mean() * 100), 1),
    }

def breakdown(trades):
    if trades.empty:
        return pd.DataFrame()
    rows = []
    for phase, group in trades.groupby("nhóm"):
        rows.append({"nhóm": phase, **metrics(group)})
    rows.append({"nhóm": "TẤT CẢ", **metrics(trades)})
    return pd.DataFrame(rows)
