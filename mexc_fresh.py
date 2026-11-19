"""MEXC 48-hour anti-chase context and fresh-first-breakout gate.

Only historical, CLOSED hourly and 5-minute candles; no future pivots.
Scores/states are research observations and do not predict artificial pumps.
"""
import math
import pandas as pd

FRESH = "0. MỚI PHÁ NỀN — QUAN SÁT"
LATE48 = "3. ĐÃ TĂNG XA TRONG 48H — LOẠI"
NO_HISTORY = "KHÔNG ĐỦ DỮ LIỆU 48H — KHÔNG XÁC NHẬN"


def hourly_context(hourly, price, *, now=None):
    if hourly is None or hourly.empty or len(hourly) < 48:
        return None
    h = hourly.sort_values("t").drop_duplicates("t").tail(55).reset_index(drop=True)
    if len(h) < 48 or (h["t"].diff().iloc[-47:] != 3600).any():
        return None
    if now is not None and (int(h["t"].iloc[-1]) + 3600 > now or
                            now - int(h["t"].iloc[-1]) - 3600 > 7200):
        return None
    if any(not h[key].map(lambda x: math.isfinite(float(x))).all()
           for key in ("high", "low", "close")):
        return None
    segment = h.tail(48)
    low = float(segment["low"].min())
    if low <= 0 or float(segment["close"].iloc[0]) <= 0:
        return None
    change48 = (price / float(segment["close"].iloc[0]) - 1) * 100
    from_low = (price / low - 1) * 100
    change24 = (price / float(h["close"].iloc[-25]) - 1) * 100
    return {
        "48H %": round(change48, 2),
        "tăng từ đáy 48H %": round(from_low, 2),
        "24H nến %": round(change24, 2),
        "late": change48 >= 10 or from_low >= 15 or change24 >= 9
    }


def fresh_breakout(market, five, *, now=None):
    """One completed 5m breakout candle over the preceding 60m high.

    Previous 12 candles (prior to breakout) form the compressed base.
    The latest candle is THE FIRST to close above the earlier high.
    """
    if five is None or len(five) < 65:
        return None
    c = five.sort_values("t").drop_duplicates("t").tail(100).reset_index(drop=True)
    if (c["t"].diff().iloc[-64:] != 300).any():
        return None
    if now is not None and (int(c["t"].iloc[-1]) + 300 > now or
                            now - int(c["t"].iloc[-1]) - 300 > 450):
        return None
    base = c.iloc[-13:-1]
    low = float(base["low"].min())
    high = float(base["high"].max())
    close = float(c["close"].iloc[-1])
    prior = float(c["close"].iloc[-2])
    if low <= 0 or high <= 0 or close <= 0 or prior <= 0:
        return None
    if not all(c[k].iloc[-65:].map(lambda x: math.isfinite(float(x))).all()
               for k in ("open", "high", "low", "close", "amount")):
        return None
    width = (high / low - 1)*100
    past_range = c.iloc[-61:-13]
    median_range = []
    for j in range(0, len(past_range)-11, 6):
        block = past_range.iloc[j:j+12]
        if float(block["low"].min()) <= 0:
            return None
        median_range.append((float(block["high"].max()) /
                             float(block["low"].min()) - 1)*100)
    typical = float(pd.Series(median_range).median()) if median_range else width
    dry = float(base["amount"].mean()) <= float(past_range["amount"].mean()) * .95
    if not (width <= min(3.0, max(.7, typical * .85)) and dry):
        return None
    level_gap = (close/high-1)*100
    candle_move = (close/prior-1)*100
    volbase = float(base["amount"].mean())
    rvol = float(c["amount"].iloc[-1])/volbase if volbase > 0 else 0
    last = c.iloc[-1]
    height = max(float(last["high"])-float(last["low"]), close * 1e-9)
    wick = (float(last["high"])-max(close, float(last["open"])))/height * 100
    # Prior close must be under base resistance: late 2nd/3rd candles won't qualify.
    if not (prior <= high and .08 <= level_gap <= 1.2
            and .15 <= candle_move <= 1.8 and 1.2 <= rvol <= 3.5
            and wick <= 35 and float(last["close"]) >= float(last["open"])):
        return None
    return {
        "coin": market["coin"], "trạng thái": FRESH,
        "giá": round(close, 12), "nén (phút)": 60,
        "biên nén %": round(width, 2), "RVOL 5m": round(rvol, 2),
        "đến đỉnh nền %": round((high/close-1)*100,2),
        "tăng từ đáy 1H %": round((close/low-1)*100,2),
        "giá so EMA20 %": None, "râu trên %": round(wick,1),
        "số nến giữ nền": 1, "24H %": round(float(market.get("change24",0)),2),
        "lý do": "Nến 5M đầu đóng vượt nền nén 60 phút; chưa xác nhận tiếp diễn",
        "nến cuối UTC": pd.to_datetime(int(last["t"]),unit="s",utc=True).strftime("%Y-%m-%d %H:%M"),
    }


def apply_48h_guard(row, context):
    """Fail closed on missing hourly history, preserving diagnostic warnings."""
    if row is None:
        return None
    if context is None:
        return None  # no 48H claims without actual valid 48H candles
    row = dict(row)
    row.update({k:v for k,v in context.items() if k != "late"})
    if context["late"]:
        row["trạng thái"] = LATE48
        row["lý do"] = "Đã tăng mạnh 24–48H hoặc quá xa đáy 48H; không gọi là sắp pump"
    return row
