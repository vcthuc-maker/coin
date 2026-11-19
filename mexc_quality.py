"""MEXC pre-breakout *research watchlist* using only closed 5m Futures candles.

IMPORTANT: cannot predict artificial pumps. Two-stage labels separate
preparation from persistence. A single RVOL spike is never enough.
All indicators are calculated from candles available AT the signal.
"""
from __future__ import annotations

import math
import pandas as pd

PREP = "1. NÉN GIÁ — CHỜ DÒNG TIỀN"
HOLD = "2. BREAKOUT GIỮ GIÁ — CHƯA ĐUỔI"
REJECT = "3. XẢ / TĂNG NÓNG — LOẠI"
MIN_BARS = 70
OUTPUT_COLUMNS = [
    "coin", "trạng thái", "giá", "nén (phút)", "biên nén %",
    "RVOL 5m", "đến đỉnh nền %", "tăng từ đáy 1H %",
    "giá so EMA20 %", "râu trên %", "số nến giữ nền",
    "24H %", "lý do", "nến cuối UTC",
]


def analyze(market, candles, now=None):
    """Rows are real closed 5m Futures candles with columns t/open/high/low/close/amount.

    Compression uses PRIOR 60m range, excluding the breakout bars.
    Return a record only if an actionable *research condition* or dump risk exists.
    """
    if len(candles) < MIN_BARS:
        return None
    c = candles.sort_values("t").drop_duplicates("t").tail(100).reset_index(drop=True)
    if len(c) < MIN_BARS or (c["t"].diff().iloc[-MIN_BARS+1:] != 300).any():
        return None
    if now is not None and (int(c["t"].iloc[-1]) + 300 > now or
                           now - int(c["t"].iloc[-1]) - 300 > 450):
        return None
    fields = ("open", "high", "low", "close", "amount")
    try:
        if not all(c[k].map(lambda x: math.isfinite(float(x))).all() for k in fields):
            return None
        if (c[["open", "high", "low", "close"]] <= 0).any().any() or (c["amount"] < 0).any():
            return None
    except (ValueError, TypeError):
        return None
    price = float(c["close"].iloc[-1])
    prev = c.iloc[-15:-3]  # 12 x 5m = 60 minutes, before recent 3 bars
    high_base = float(prev["high"].max())
    low_base = float(prev["low"].min())
    width = (high_base / low_base - 1) * 100
    # Relative range to prior regime, avoids hardcoded 2% rule for every alt.
    history_ranges = []
    for k in range(18, 60, 4):
        w = c.iloc[-k-12:-k]
        if len(w) == 12:
            history_ranges.append((float(w["high"].max()) /
                                   float(w["low"].min()) - 1) * 100)
    baseline_width = float(pd.Series(history_ranges).median()) if history_ranges else width
    is_compressed = width <= min(3.2, max(1.0, baseline_width * .80))
    # Volume drying during base is stronger evidence than current abnormal volume alone.
    base_turnover = float(prev["amount"].mean())
    prior_turnover = float(c["amount"].iloc[-39:-15].mean())
    drying = base_turnover <= prior_turnover * .88 if prior_turnover > 0 else False
    last_turnover = float(c["amount"].iloc[-1])
    rvol = last_turnover / base_turnover if base_turnover > 0 else 0
    trend = c["close"].ewm(span=20, adjust=False).mean()
    ema_gap = (price / float(trend.iloc[-1]) - 1) * 100
    trend_slope = float(trend.iloc[-1] / trend.iloc[-7] - 1) * 100
    recent_low = float(c["low"].iloc[-13:].min())
    extended = (price / recent_low - 1) * 100
    distance_to_base = (high_base / price - 1) * 100
    wick = max(0.0, float(c["high"].iloc[-1]) -
               max(float(c["open"].iloc[-1]), price))
    candle_height = max(float(c["high"].iloc[-1]) - float(c["low"].iloc[-1]), price * 1e-9)
    upper_wick = wick / candle_height * 100
    closes = c["close"]
    recent_3 = closes.iloc[-3:]
    # A breakout is only labelled when 2 closed 5m candles hold the *old* base
    held = int((recent_3 >= high_base * .997).sum())
    closes_above = int((recent_3 >= high_base * 1.001).sum())
    change15 = (price / float(closes.iloc[-4]) - 1) * 100
    change5 = (price / float(closes.iloc[-2]) - 1) * 100
    ch24 = float(market.get("change24", 0))
    negative = (upper_wick >= 55 or
                (rvol >= 2.5 and change5 <= -.4) or
                (change15 >= 3.5 and price < high_base) or
                extended >= 5.0 or ch24 >= 25)
    flag_prep = (is_compressed and drying and
                 -.8 <= distance_to_base <= 2.0 and
                 -.8 <= ema_gap <= 1.8 and trend_slope >= -.3 and
                 extended <= 2.5 and ch24 < 12 and
                 upper_wick < 45 and rvol < 3.0)
    flag_hold = (is_compressed and closes_above >= 2 and held >= 2 and
                 1.2 <= rvol <= 3.8 and
                 0 <= (price / high_base - 1) * 100 <= 2.0 and
                 change15 <= 2.5 and extended <= 3.5 and
                 upper_wick < 40 and ch24 < 15 and trend_slope >= -.2)
    if negative:
        status = REJECT
        reason = "Râu trên lớn, giá xả hoặc đà tăng quá xa; không dùng làm tín hiệu mua"
    elif flag_hold:
        status = HOLD
        reason = "Nén trước đó; đã đóng >=2 nến trên đỉnh nền; giá chưa kéo quá xa"
    elif flag_prep:
        status = PREP
        reason = "Nền nén, volume nền suy giảm và giá còn gần đỉnh nền"
    else:
        return None
    return {
        "coin": market["coin"], "trạng thái": status,
        "giá": round(price, 12), "nén (phút)": 60,
        "biên nén %": round(width, 2),
        "RVOL 5m": round(rvol, 2), "đến đỉnh nền %": round(distance_to_base, 2),
        "tăng từ đáy 1H %": round(extended, 2),
        "giá so EMA20 %": round(ema_gap, 2), "râu trên %": round(upper_wick, 1),
        "số nến giữ nền": held, "24H %": round(ch24, 2),
        "lý do": reason,
        "nến cuối UTC": pd.to_datetime(int(c["t"].iloc[-1]), unit="s", utc=True).strftime("%Y-%m-%d %H:%M"),
    }


def scan_quality(markets, history, now, *, limit=30):
    """Sample diverse candidates to control API load. Not full-market verification."""
    from mexc_early import select_candidates
    from mexc_fast import get_json
    from concurrent.futures import ThreadPoolExecutor, as_completed

    # Detect compressed / quiet names as well as mild accelerators.
    picks = select_candidates(markets, history, limit=limit)
    quiet = sorted(
        [{"native": symbol, "coin": symbol[:-5]+"/USDT",
          "change24": values[2], "turnover24": values[1]}
         for symbol, values in markets.items()
         if -5 <= values[2] <= 5 and values[1] >= 100000],
        key=lambda x: x["turnover24"], reverse=True,
    )[:max(5, limit//3)]
    pick_by_sym = {x["native"]: x for x in quiet}
    for x in picks:
        pick_by_sym.setdefault(x["native"], x)
    chosen = list(pick_by_sym.values())[:limit]
    errors, rows = [], []
    def fetch(item):
        raw = get_json("/api/v1/contract/kline/"+item["native"],
                       {"interval":"Min5", "start": now-110*300, "end": now})
        ts = raw.get("time", [])
        frame = pd.DataFrame([{
            "t": int(t), "open": float(raw["open"][i]), "high": float(raw["high"][i]),
            "low": float(raw["low"][i]), "close": float(raw["close"][i]),
            "amount": float(raw["amount"][i])} for i,t in enumerate(ts)])
        if frame.empty:
            return None
        frame = frame[frame["t"] + 300 <= now]
        return analyze(item, frame, now=now)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {pool.submit(fetch, item): item for item in chosen}
        for future in as_completed(futures):
            try:
                outcome = future.result()
                if outcome:
                    rows.append(outcome)
            except Exception as err:
                errors.append(f"{futures[future]['native']}: {str(err)[:130]}")
    rank = {PREP:0, HOLD:1, REJECT:2}
    return sorted(rows, key=lambda x:(rank[x["trạng thái"]], x["biên nén %"])), errors, len(chosen)
