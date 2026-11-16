"""Shared versioned Pre-Pump heuristic for dashboard and hourly observation archive.

Research only; score is NOT a probability of price increase.
""" 
import numpy as np
import pandas as pd

def signal(ex, base, native, price, turnover, candles):
    df = candles
    if len(df) < 75:
        return None
    close = df["close"]
    high = df["high"]
    low = df["low"]
    vol = df["turnover"]
    ema20 = close.ewm(span=20, adjust=False).mean()
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rsi = float((100 - 100 / (1 + gain / loss.replace(0, 1e-12))).iloc[-1])
    rvol = float(vol.iloc[-1] / max(vol.iloc[-49:-1].mean(), 1e-9))
    accel = float(vol.iloc[-2:].mean() / max(vol.iloc[-8:-2].mean(), 1e-9))
    avg = close.rolling(20).mean()
    bbw = (4 * close.rolling(20).std() / avg).replace([np.inf, -np.inf], np.nan)
    # History-relative threshold per bar, avoiding future observations.
    bbw_limit = bbw.shift(1).rolling(48, min_periods=24).quantile(0.35)
    rolling_range = high.rolling(8).max() / low.rolling(8).min() - 1
    compression = (bbw <= bbw_limit) & (rolling_range <= 0.06)
    compression = compression.fillna(False)
    bb_pct = float((bbw.dropna().tail(72) <= bbw.iloc[-1]).mean() * 100)
    change4 = float((close.iloc[-1] / close.iloc[-5] - 1) * 100)
    change24 = float((close.iloc[-1] / close.iloc[-25] - 1) * 100)
    distance = float((high.iloc[-25:-1].max() / close.iloc[-1] - 1) * 100)
    ema_gap = float((close.iloc[-1] / ema20.iloc[-1] - 1) * 100)

    def count_compressed(end_index):
        hours = 0
        for i in range(end_index, max(-1, end_index - 96), -1):
            if i < 0 or not bool(compression.iloc[i]):
                break
            hours += 1
        return hours

    compressed_hours = count_compressed(len(df) - 1)
    # Look for a *recent* 1H closed candle breaking a PREVIOUS 24H high,
    # accompanied by meaningful turnover, and preceded by >= 6 compressed hours.
    breakout = None
    for j in range(len(df) - 1, len(df) - 5, -1):
        if j < 50:
            break
        resistance_before = float(high.iloc[j-24:j].max())
        past_volume = float(vol.iloc[j-48:j].mean())
        bar_rvol = float(vol.iloc[j] / max(past_volume, 1e-9))
        preceding_hours = count_compressed(j - 1)
        # >= 0.2% above resistance avoids noise around the old top.
        if (close.iloc[j] >= resistance_before * 1.002 and
                bar_rvol >= 1.5 and preceding_hours >= 6):
            breakout = (j, resistance_before, bar_rvol, preceding_hours)
            break

    overheated = (rsi >= 76 or change4 >= 12 or change24 >= 22 or ema_gap >= 10)
    # Accumulation setup: strong compression over several completed hours
    # and some turnover improvement, without price already extending far.
    controlled = (-3 <= change4 <= 4 and -7 <= change24 <= 9 and
                  43 <= rsi <= 70 and -3 <= ema_gap <= 4)
    near_top = -0.7 <= distance <= 4.5
    volume_waking = rvol >= 0.75 and accel >= 1.1
    comp_score = min(compressed_hours / 24, 1) * 30
    width_score = 15 if bb_pct <= 20 else (10 if bb_pct <= 35 else 0)
    price_score = 15 if controlled else 0
    volume_score = 20 if volume_waking else (8 if rvol >= 1.2 else 0)
    resistance_score = 10 if near_top else 0
    trend_score = 10 if 48 <= rsi <= 68 and close.iloc[-1] >= ema20.iloc[-1] else 0
    pre_score = round(comp_score + width_score + price_score +
                      volume_score + resistance_score + trend_score)
    # Keep compression duration distinct from a single narrow BB sample.
    if compressed_hours < 6:
        pre_score = min(pre_score, 49)
    if not controlled or overheated:
        pre_score = min(pre_score, 39)
    if not volume_waking:
        pre_score = min(pre_score, 59)
    pre_score = int(min(100, pre_score))
    phase = "CHƯA XÁC NHẬN"
    reasons = []
    if compressed_hours >= 6:
        reasons.append(f"Nén liên tục {compressed_hours}H")
    if volume_waking:
        reasons.append("Volume bắt đầu tăng")
    if near_top:
        reasons.append("Gần kháng cự")
    if not controlled:
        reasons.append("Động lượng/giá chưa phù hợp")

    breakout_age = None
    breakout_volume = None
    prior_compression = None
    continuation_score = 0
    if breakout is not None:
        j, level, burst_rvol, prior_hours = breakout
        breakout_age = len(df) - 1 - j
        breakout_volume = round(burst_rvol, 2)
        prior_compression = prior_hours
        growth_since_level = float((close.iloc[-1] / level - 1) * 100)
        intact = close.iloc[-1] >= level * 0.995
        controlled_extension = -0.5 <= growth_since_level <= 8
        healthy_rsi = 52 <= rsi <= 75
        supporting_volume = rvol >= 0.65
        continuation_score = int(min(100,
            min(prior_hours, 24) / 24 * 25 +
            min(burst_rvol / 3, 1) * 25 +
            (20 if intact else 0) +
            (15 if healthy_rsi else 0) +
            (15 if supporting_volume else 0)))
        if not intact or not controlled_extension or overheated:
            continuation_score = min(continuation_score, 39)
        if intact and controlled_extension and healthy_rsi and supporting_volume and not overheated and continuation_score >= 65:
            phase = "VỪA BREAKOUT — CÓ THỂ TIẾP DIỄN"
            reasons.append(f"Breakout {breakout_age}H trước, vol {burst_rvol:.1f}x")
        else:
            phase = "BREAKOUT CẦN XÁC NHẬN"
            reasons.append("Đã breakout nhưng cần kiểm tra rủi ro")

    if phase == "CHƯA XÁC NHẬN":
        if overheated:
            phase = "ĐÃ TĂNG NÓNG"
        elif compressed_hours >= 12 and pre_score >= 70 and controlled and near_top and volume_waking:
            phase = "NÉN LÂU — ƯU TIÊN 4H"
        elif compressed_hours >= 6 and pre_score >= 50 and controlled:
            phase = "ĐANG TÍCH LŨY"

    score = continuation_score if phase.startswith(("VỪA BREAKOUT", "BREAKOUT")) else pre_score
    return {
        "sàn": ex, "coin": f"{base}/USDT", "trạng thái 4H": phase,
        "điểm 4H /100": score, "điểm nén /100": pre_score,
        "điểm tiếp diễn /100": continuation_score,
        "thời gian nén liên tục (giờ)": compressed_hours,
        "nén trước breakout (giờ)": prior_compression,
        "breakout cách đây (giờ)": breakout_age,
        "volume breakout / TB": breakout_volume,
        "giá": price, "turnover 24h USDT": round(turnover, 2),
        "RVOL 1H": round(rvol, 2), "volume tăng tốc": round(accel, 2),
        "RSI 1H": round(rsi, 1), "BB percentile": round(bb_pct, 1),
        "cách kháng cự %": round(distance, 2), "giá 4H %": round(change4, 2),
        "giá 24H %": round(change24, 2), "lý do": ", ".join(reasons)
    }

