"""MEXC Futures Fast-Mover 5m scanner. Research-only, no order placement.

Use CLOSED Min5 candles only. Screening 24h ticker gain merely discovers markets;
it never means an asset is an early pump. Return explicit chasing warnings.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import time

import httpx
import numpy as np
import pandas as pd

BASE = "https://contract.mexc.com"
# Temporary symbol-based exclusions; not an authoritative crypto asset registry.
EXCLUDE = {"SNDK", "NVDA", "NVIDIA", "TSLA", "AAPL", "MSFT", "AMZN",
           "GOOGL", "META", "AMD", "INTC", "MU", "QQQ", "SPY", "SOXS",
           "SHELL", "CL", "USO", "XAU", "XAG", "OIL", "SKHYNIX"}


def get_json(path, params=None, timeout=12):
    with httpx.Client(headers={"User-Agent": "PrePumpScanner-FastMover/1.0"},
                      timeout=timeout) as client:
        resp = client.get(BASE + path, params=params)
        if resp.status_code in (403, 451, 429):
            raise RuntimeError(f"MEXC HTTP {resp.status_code}: không truy cập được API")
        resp.raise_for_status()
        obj = resp.json()
        if not isinstance(obj, dict) or not obj.get("success"):
            raise RuntimeError(f"MEXC API {obj.get('code') if isinstance(obj, dict) else 'invalid'}")
        return obj["data"]


def universe(min_turnover_usdt=250_000, max_candidates=45):
    metadata = get_json("/api/v1/contract/detail")
    tickers = get_json("/api/v1/contract/ticker")
    permitted = {x.get("symbol") for x in metadata if
                 str(x.get("state")) == "0" and x.get("quoteCoin") == "USDT"
                 and str(x.get("futureType", 1)) == "1"}
    rows = []
    for t in tickers if isinstance(tickers, list) else [tickers]:
        symbol = t.get("symbol", "")
        base = symbol[:-5].upper() if symbol.endswith("_USDT") else ""
        if not base or symbol not in permitted or base in EXCLUDE:
            continue
        turnover = pd.to_numeric(t.get("amount24"), errors="coerce")
        change = pd.to_numeric(t.get("riseFallRate"), errors="coerce")
        price = pd.to_numeric(t.get("lastPrice"), errors="coerce")
        if (not np.isfinite(turnover) or turnover < min_turnover_usdt
                or not np.isfinite(change) or not np.isfinite(price) or price <= 0):
            continue
        rows.append({"native": symbol, "coin": f"{base}/USDT",
                     "turnover24": float(turnover), "change24": float(change) * 100,
                     "price": float(price)})
    if not rows:
        return []
    df = pd.DataFrame(rows)
    # Diversify discovery: strong liquidity, early moderate movers,
    # plus some active gainers; do not inspect solely already-pumped coins.
    liquid = df.sort_values("turnover24", ascending=False).head(max_candidates // 2)
    warming = df[(df["change24"] >= -3) & (df["change24"] <= 12)]
    warming = warming.sort_values(["change24", "turnover24"], ascending=False).head(max_candidates)
    gainers = df[(df["change24"] > 12) & (df["change24"] <= 80)]
    gainers = gainers.sort_values("change24", ascending=False).head(max_candidates // 3)
    pool = pd.concat([liquid, warming, gainers]).drop_duplicates("native")
    return pool.head(max_candidates).to_dict("records")


def closed_klines(native, *, now=None):
    now = int(time.time()) if now is None else int(now)
    data = get_json(f"/api/v1/contract/kline/{native}",
                    {"interval": "Min5", "start": now - 70 * 300, "end": now})
    ts = data.get("time", [])
    rows = [
        [int(t), float(data["open"][i]), float(data["high"][i]),
         float(data["low"][i]), float(data["close"][i]), float(data["amount"][i])]
        for i, t in enumerate(ts)
    ]
    candles = pd.DataFrame(rows, columns=["t", "open", "high", "low", "close", "amount"])
    if candles.empty:
        return candles
    # Closed 5m candles only, time is opening timestamp in seconds.
    return (candles[candles["t"] + 300 <= now]
            .drop_duplicates("t").sort_values("t").tail(65).reset_index(drop=True))


def classify(market, candles):
    if len(candles) < 40:
        return None
    close = candles["close"]
    amount = candles["amount"]
    if (close.le(0).any() or amount.lt(0).any() or
            not np.isfinite(close).all() or not np.isfinite(amount).all()):
        return None
    price = float(close.iloc[-1])
    ch5 = (price / float(close.iloc[-2]) - 1) * 100
    ch15 = (price / float(close.iloc[-4]) - 1) * 100
    ch60 = (price / float(close.iloc[-13]) - 1) * 100
    base_volume = float(amount.iloc[-39:-3].mean())
    last_volume = float(amount.iloc[-3:].mean())
    rvol = last_volume / base_volume if base_volume > 0 else 0
    turnover_15 = float(amount.iloc[-3:].sum())
    high_prev = float(candles["high"].iloc[-28:-4].max())
    price_break = (price / high_prev - 1) * 100 if high_prev > 0 else -100.
    # Short-horizon momentum with exceptional activity, not just 24h % gain.
    activity = rvol >= 1.7 and turnover_15 >= 15_000
    early = (0.4 <= ch15 <= 4.0 and 0.6 <= ch60 <= 7.0
             and price_break >= -1.0 and market["change24"] < 18.0)
    surge = activity and early
    overheated = (ch15 > 6 or ch60 > 12 or market["change24"] >= 25
                  or ch5 >= 4)
    if overheated:
        phase = "ĐÃ PUMP — TRÁNH MUA ĐUỔI"
    elif surge:
        phase = "TĂNG TỐC SỚM — THEO DÕI"
    elif activity and (ch15 > 0.2 or ch60 > 0.4):
        phase = "VOLUME TĂNG — CHỜ PHÁ CẢN"
    else:
        return None
    # Rules-based ranking, NOT a calibrated probability.
    score = int(min(100, 20 * min(rvol / 3.5, 1) +
                    20 * min(max(ch15, 0) / 3, 1) +
                    15 * min(max(ch60, 0) / 5, 1) +
                    (20 if price_break >= 0 else (10 if price_break >= -1 else 0)) +
                    (15 if turnover_15 >= 50_000 else 0) +
                    (10 if market["change24"] < 10 else 0)))
    if overheated:
        score = min(score, 39)
    return {
        "coin": market["coin"], "trạng thái": phase, "điểm hoạt động /100": score,
        "giá (USDT)": price, "5m %": round(ch5, 2), "15m %": round(ch15, 2),
        "1h %": round(ch60, 2), "24h %": round(market["change24"], 2),
        "RVOL 15m": round(rvol, 2), "turnover 15m USDT": round(turnover_15),
        "vượt đỉnh gần đây %": round(price_break, 2),
        "nến cuối UTC": datetime.fromtimestamp(int(candles["t"].iloc[-1]), timezone.utc).strftime("%Y-%m-%d %H:%M"),
    }


def scan_fast(min_turnover_usdt=250_000, max_candidates=45):
    markets = universe(min_turnover_usdt=min_turnover_usdt,
                       max_candidates=max_candidates)
    results, errors = [], []
    def job(market):
        df = closed_klines(market["native"])
        return classify(market, df)
    # Small pool to avoid bursts of requests from Streamlit Cloud shared IP.
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {pool.submit(job, x): x["coin"] for x in markets}
        for future in as_completed(futures):
            try:
                result = future.result()
                if result is not None:
                    results.append(result)
            except Exception as exc:
                errors.append(f"{futures[future]}: {str(exc)[:110]}")
    df = pd.DataFrame(results)
    if not df.empty:
        priority = {"TĂNG TỐC SỚM — THEO DÕI": 0,
                    "VOLUME TĂNG — CHỜ PHÁ CẢN": 1,
                    "ĐÃ PUMP — TRÁNH MUA ĐUỔI": 2}
        df["_rank"] = df["trạng thái"].map(priority)
        df = df.sort_values(["_rank", "điểm hoạt động /100"],
                            ascending=[True, False]).drop(columns="_rank")
    return df, errors, len(markets)
