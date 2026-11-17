"""Early MEXC Futures 1-minute / 3-minute momentum observation.

Uses *closed* Min1 candles. No future candles, no prediction or execution.
The scheduler is only every five minutes, so one-minute impulses can be missed.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import math
import time

import pandas as pd

from mexc_fast import get_json

EARLY = "MỚI BẬT LÊN — 1–2 NẾN"
WATCH = "DÒNG TIỀN NHÍCH LÊN — THEO DÕI"
LATE = "ĐÃ CHẠY XA — KHÔNG MUA ĐUỔI"
MIN_1M_HISTORY = 40


def select_candidates(markets, history, limit=24):
    """Sample liquid, mildly moving and fresh accelerators; no claim of full coverage.

    Uses the most recent snapshots only; does not select based on future outcomes.
    """
    if not markets:
        return []
    from mexc_velocity import _reference
    now = int(history[-1]["ts"]) if history else int(time.time())
    candidates = []
    for symbol, (price, turnover, ch24) in markets.items():
        if ch24 >= 30 or ch24 < -20 or turnover < 100_000:
            continue
        ref = _reference(history, symbol, now, 5/60, 3*60) if history else None
        change5 = 100 * (price/ref - 1) if ref else None
        candidates.append({
            "native": symbol, "coin": symbol[:-5] + "/USDT",
            "change24": ch24, "turnover24": turnover,
            "change5_snapshot": change5,
        })
    if not candidates:
        return []
    # Fixed shares to retain small but active names without scanning every symbol.
    warming = sorted(
        [x for x in candidates if x["change5_snapshot"] is not None
         and .05 <= x["change5_snapshot"] <= 3],
        key=lambda x: x["change5_snapshot"], reverse=True,
    )[:max(1, limit // 2)]
    liquid = sorted(candidates, key=lambda x: x["turnover24"], reverse=True)[:max(1, limit // 4)]
    moderate = sorted(
        [x for x in candidates if -2 <= x["change24"] <= 10],
        key=lambda x: x["change24"], reverse=True,
    )[:limit]
    pooled = {}
    for item in warming + liquid + moderate:
        pooled.setdefault(item["native"], item)
    return list(pooled.values())[:limit]


def fetch_closed_1m(native, *, now=None):
    now = int(time.time()) if now is None else int(now)
    raw = get_json(f"/api/v1/contract/kline/{native}", {
        "interval": "Min1", "start": now - 85 * 60, "end": now
    })
    ts = raw.get("time") or []
    entries = []
    for i, t in enumerate(ts):
        entries.append({
            "t": int(t), "open": float(raw["open"][i]),
            "high": float(raw["high"][i]), "low": float(raw["low"][i]),
            "close": float(raw["close"][i]), "amount": float(raw["amount"][i]),
        })
    df = pd.DataFrame(entries, columns=["t", "open", "high", "low", "close", "amount"])
    if df.empty:
        return df
    # Exclude current unfinished minute; prevent stale/irregular candles from firing.
    df = df[df["t"] + 60 <= now].sort_values("t").drop_duplicates("t").tail(70)
    return df.reset_index(drop=True)


def classify_early(market, candles, *, now=None):
    now = int(time.time()) if now is None else int(now)
    if len(candles) < MIN_1M_HISTORY:
        return None
    c = candles.sort_values("t").reset_index(drop=True)
    if now - (int(c["t"].iloc[-1]) + 60) > 150:
        return None
    if (c["t"].diff().iloc[-35:] != 60).any():
        return None
    cols = ["open", "high", "low", "close", "amount"]
    if not all(pd.api.types.is_numeric_dtype(c[k]) for k in cols):
        return None
    if not all(c[k].map(math.isfinite).all() for k in cols):
        return None
    if (c[["open", "high", "low", "close"]] <= 0).any().any() or (c["amount"] < 0).any():
        return None
    price = float(c["close"].iloc[-1])
    close1 = float(c["close"].iloc[-2])
    close3 = float(c["close"].iloc[-4])
    close15 = float(c["close"].iloc[-16])
    change1 = (price / close1 - 1) * 100
    change3 = (price / close3 - 1) * 100
    change15 = (price / close15 - 1) * 100
    # Confirm price is close to *previous* resistance; never use current candle
    # or a retrospectively chosen future pivot.
    past = c.iloc[-33:-3]
    resistance = float(past["high"].max())
    low30 = float(c["low"].iloc[-31:].min())
    rise_from_low = (price / low30 - 1) * 100
    breakout_distance = (price / resistance - 1) * 100
    baseline = float(c["amount"].iloc[-33:-3].mean())
    recent_vol = float(c["amount"].iloc[-2:].mean())
    rvol = recent_vol / baseline if baseline > 0 else 0
    recent_turnover = float(c["amount"].iloc[-3:].sum())
    green = 0
    for i in range(1, 7):
        if float(c["close"].iloc[-i]) > float(c["open"].iloc[-i]):
            green += 1
        else:
            break
    # Allow a 1m dip if the 3m combined impulse still meets the watch threshold;
    # a strong early alert requires first or second positive candle.
    activity = rvol >= 1.5 and recent_turnover >= 3_000
    late = (rise_from_low >= 5 or change15 >= 6 or
            change3 >= 3 or market["change24"] >= 25 or
            (green >= 4 and rise_from_low >= 2.0))
    early = (
        activity and 1 <= green <= 2
        and .2 <= change1 <= 1.5 and .3 <= change3 <= 2.
        and -1.0 <= breakout_distance <= 1.8
        and rise_from_low <= 2.5 and change15 <= 3.
        and market["change24"] < 15
    )
    watch = activity and change3 >= .2 and rise_from_low < 4 and change15 < 5
    if late:
        status, priority = LATE, 2
    elif early:
        status, priority = EARLY, 0
    elif watch:
        status, priority = WATCH, 1
    else:
        return None
    return {
        "coin": market["coin"], "trạng thái": status,
        "giá": round(price, 12),
        "nến xanh liên tiếp": green,
        "1m %": round(change1, 3), "3m %": round(change3, 3),
        "15m %": round(change15, 3), "RVOL 1m": round(rvol, 2),
        "tăng từ đáy 30m %": round(rise_from_low, 2),
        "so với đỉnh trước %": round(breakout_distance, 2),
        "turnover 3m USDT": round(recent_turnover, 2),
        "24h %": round(market["change24"], 2),
        "nến cuối UTC": pd.to_datetime(int(c["t"].iloc[-1]), unit="s", utc=True).strftime("%Y-%m-%d %H:%M"),
        "_priority": priority,
    }


def scan_early(markets, history, *, limit=24, now=None):
    now = int(time.time()) if now is None else int(now)
    candidates = select_candidates(markets, history, limit=limit)
    results, errors = [], []
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = {pool.submit(fetch_closed_1m, item["native"], now=now): item for item in candidates}
        for future in as_completed(jobs):
            candidate = jobs[future]
            try:
                score = classify_early(candidate, future.result(), now=now)
                if score is not None:
                    results.append(score)
            except Exception as exc:
                errors.append(f"{candidate['native']}: {str(exc)[:120]}")
    results.sort(key=lambda x: (x["_priority"], -x["RVOL 1m"]))
    return [{k: v for k, v in x.items() if k != "_priority"} for x in results], errors, len(candidates)
