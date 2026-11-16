"""Capture the SAME rules used by the dashboard from closed hourly candles.

No new probability model; no look-ahead; only public OKX/MEXC data.
"""
import time

import pandas as pd
from signal_core import signal as score_signal


def closed_hourly_candles(client, get, ex, base):
    if ex == "okx":
        pair = base + "-USDT-SWAP"
        x = get(client, "https://www.okx.com/api/v5/market/history-candles",
                {"instId": pair, "bar": "1H", "limit": "100"}).get("data", [])
        out = [[int(v[0]), *map(float, [v[1], v[2], v[3], v[4], v[7]])]
               for v in x if len(v) > 8 and str(v[8]) == "1"]
    elif ex == "mexc":
        pair = base + "_USDT"
        obj = get(client, "https://contract.mexc.com/api/v1/contract/kline/" + pair,
                  {"interval": "Min60",
                   "start": int(time.time())-120*3600,
                   "end": int(time.time())})["data"]
        out = [[int(t)*1000, *[float(obj[k][i]) for k in
               ("open", "high", "low", "close", "amount")]]
               for i, t in enumerate(obj["time"])]
    else:
        raise ValueError("Only okx/mexc archive currently supported")
    df = pd.DataFrame(out, columns=["t", "open", "high", "low", "close", "turnover"])
    if df.empty:
        return df
    cutoff = int(time.time() // 3600 * 3600000)
    return df[df["t"] < cutoff].sort_values("t").drop_duplicates("t").tail(110).reset_index(drop=True)


def capture(client, get, exchange, coin, snapshot):
    candles = closed_hourly_candles(client, get, exchange, coin)
    if len(candles) < 75:
        raise RuntimeError("Insufficient closed hourly candles")
    # Correct source pair identifier is not needed because candles are provided.
    native = coin + ("-USDT-SWAP" if exchange == "okx" else "_USDT")
    prediction = score_signal(exchange, coin, native,
                              float(candles["close"].iloc[-1]),
                              0.0, candles=candles)
    if prediction is None:
        raise RuntimeError("Signal unavailable")
    return {
        "phase": prediction["trạng thái 4H"],
        "score": int(prediction["điểm 4H /100"]),
        "compression_hours": int(prediction["thời gian nén liên tục (giờ)"]),
        "breakout_age_hours": prediction["breakout cách đây (giờ)"],
        "signal_price_closed_1h": float(candles["close"].iloc[-1]),
        "signal_candle_start_ms": int(candles["t"].iloc[-1]),
        "reason": prediction["lý do"],
        "snapshot_price_usdt": snapshot["price_usdt"],
    }
