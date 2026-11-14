import concurrent.futures
import datetime as dt
import math
import time

import httpx
import numpy as np
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Pre-Pump Scanner | 4 Exchanges", layout="wide")
st.title("🔎 Pre-Pump Scanner — 4 sàn")
st.caption("Binance • Bybit • OKX • MEXC | Rule-based, không phải AI đã huấn luyện. Chỉ dữ liệu công khai, không đặt lệnh.")
BASE = {"binance": "https://fapi.binance.com", "bybit": "https://api.bybit.com",
        "okx": "https://www.okx.com", "mexc": "https://contract.mexc.com"}
EXCLUDE = ("XAU", "XAG", "OIL", "USOIL", "UKOIL", "GOLD", "SILVER", "EUR", "GBP", "JPY")

def number(value, default=np.nan):
    try:
        x = float(value)
        return x if math.isfinite(x) else default
    except (TypeError, ValueError):
        return default

def api(ex, path, params=None):
    r = httpx.get(BASE[ex] + path, params=params, timeout=13.0,
                  headers={"User-Agent": "PrePumpScanner/1.1"})
    r.raise_for_status()
    obj = r.json()
    if ex == "bybit" and obj.get("retCode", 0) != 0:
        raise ValueError(str(obj.get("retMsg")))
    if ex == "okx" and obj.get("code", "0") != "0":
        raise ValueError(str(obj.get("msg")))
    if ex == "mexc" and not obj.get("success", False):
        raise ValueError(str(obj.get("code")))
    return obj

def find_markets(ex):
    rows = []
    if ex == "binance":
        raw = api(ex, "/fapi/v1/ticker/24hr")
        for r in raw:
            sym = r.get("symbol", "")
            if sym.endswith("USDT") and "_" not in sym:
                rows.append((sym[:-4], sym, number(r.get("lastPrice")), number(r.get("quoteVolume"))))
    elif ex == "bybit":
        # Pagination: each page has up to 1000 symbols.
        cursor = None
        for _ in range(5):
            params = {"category": "linear", "limit": "1000"}
            if cursor:
                params["cursor"] = cursor
            data = api(ex, "/v5/market/tickers", params)["result"]
            for r in data.get("list", []):
                sym = r.get("symbol", "")
                if sym.endswith("USDT"):
                    rows.append((sym[:-4], sym, number(r.get("lastPrice")), number(r.get("turnover24h"))))
            nxt = data.get("nextPageCursor")
            if not nxt or nxt == cursor:
                break
            cursor = nxt
    elif ex == "okx":
        raw = api(ex, "/api/v5/market/tickers", {"instType": "SWAP"})["data"]
        for r in raw:
            sym = r.get("instId", "")
            if sym.endswith("-USDT-SWAP"):
                px = number(r.get("last"))
                rows.append((sym.split("-")[0], sym, px, number(r.get("volCcy24h")) * px))
    else:
        raw = api(ex, "/api/v1/contract/ticker")["data"]
        for r in raw if isinstance(raw, list) else [raw]:
            sym = r.get("symbol", "")
            if sym.endswith("_USDT"):
                rows.append((sym[:-5], sym, number(r.get("lastPrice")), number(r.get("amount24"))))
    return [r for r in rows if r[0] and not any(x in r[0].upper() for x in EXCLUDE)
            and np.isfinite(r[2]) and r[2] > 0 and np.isfinite(r[3])]

def history(ex, native):
    if ex == "binance":
        x = api(ex, "/fapi/v1/klines", {"symbol": native, "interval": "1h", "limit": 130})
        out = [[int(v[0]), *map(float, [v[1], v[2], v[3], v[4], v[7]])] for v in x]
    elif ex == "bybit":
        x = api(ex, "/v5/market/kline", {"category": "linear", "symbol": native,
                                         "interval": "60", "limit": "130"})["result"]["list"]
        out = [[int(v[0]), *map(float, [v[1], v[2], v[3], v[4], v[6]])] for v in x]
    elif ex == "okx":
        x = api(ex, "/api/v5/market/candles", {"instId": native, "bar": "1H", "limit": "100"})["data"]
        out = [[int(v[0]), *map(float, [v[1], v[2], v[3], v[4], v[7]])]
               for v in x if len(v) > 8 and str(v[8]) == "1"]
    else:
        x = api(ex, f"/api/v1/contract/kline/{native}", {"interval": "Min60"})["data"]
        out = [[int(t) * 1000, *[float(x[k][i]) for k in ("open", "high", "low", "close", "amount")]]
               for i, t in enumerate(x["time"])]
    df = pd.DataFrame(out, columns=["t", "open", "high", "low", "close", "turnover"])
    df = df.drop_duplicates("t").sort_values("t")
    # Exclude the current unclosed hour, whose volume would bias RVOL lower.
    current_hour = int(time.time() // 3600 * 3600000)
    return df[df["t"] < current_hour].tail(120).reset_index(drop=True)

def signal(ex, base, native, price, turnover):
    df = history(ex, native)
    if len(df) < 55:
        return None
    close = df["close"]
    high = df["high"]
    vol = df["turnover"]
    ema20 = close.ewm(span=20, adjust=False).mean()
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
    rsi = 100 - 100 / (1 + gain.iloc[-1] / max(loss.iloc[-1], 1e-12))
    rvol = float(vol.iloc[-1] / max(vol.iloc[-49:-1].mean(), 1e-9))
    avg = close.rolling(20).mean()
    std = close.rolling(20).std()
    bb_width = (4 * std / avg).replace([np.inf, -np.inf], np.nan)
    sample = bb_width.dropna().tail(72)
    bb_pct = float((sample <= bb_width.iloc[-1]).mean() * 100)
    # Resistance is strictly from completed candles before the current completed candle.
    resistance = float(high.iloc[-25:-1].max())
    distance = (resistance / close.iloc[-1] - 1) * 100
    change4h = (close.iloc[-1] / close.iloc[-5] - 1) * 100
    score = 0
    reasons = []
    if rvol >= 1.8:
        score += 25
        reasons.append("RVOL ≥1.8")
    elif rvol >= 1.2:
        score += 10
    if bb_pct <= 25:
        score += 20
        reasons.append("Bollinger squeeze")
    if close.iloc[-1] > ema20.iloc[-1]:
        score += 10
        reasons.append("Trên EMA20")
    if 48 <= rsi <= 68:
        score += 10
        reasons.append("RSI thuận lợi")
    if -0.5 <= distance <= 3:
        score += 15
        reasons.append("Gần kháng cự")
    if -2 <= change4h <= 3:
        score += 10
    # OI, spot CVD and funding are deliberately not scored until properly collected.
    return {"sàn": ex, "coin": f"{base}/USDT", "score /90": score,
            "giá": price, "turnover 24h USDT": turnover, "RVOL 1H": round(rvol, 2),
            "RSI 1H": round(rsi, 1), "BB percentile": round(bb_pct, 1),
            "cách kháng cự %": round(distance, 2), "giá 4H %": round(change4h, 2),
            "lý do": ", ".join(reasons)}

def scan(selected, top, min_turnover):
    jobs, errors = [], []
    for ex in selected:
        try:
            choices = sorted((m for m in find_markets(ex) if m[3] >= min_turnover),
                             key=lambda r: r[3], reverse=True)[:top]
            jobs.extend((ex, *m) for m in choices)
        except Exception as exc:
            errors.append(f"{ex}: không lấy được danh sách — {exc}")
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(signal, *j): j for j in jobs}
        for fut in concurrent.futures.as_completed(futures):
            try:
                v = fut.result()
                if v is not None:
                    results.append(v)
            except Exception as exc:
                j = futures[fut]
                errors.append(f"{j[0]} {j[1]}: {str(exc)[:150]}")
    results.sort(key=lambda x: (x["score /90"], x["RVOL 1H"]), reverse=True)
    return pd.DataFrame(results), errors

with st.sidebar:
    st.header("Cấu hình quét")
    selected = st.multiselect("Sàn", list(BASE), default=list(BASE))
    top = st.slider("Hợp đồng mỗi sàn", 5, 60, 15, 5)
    minimum = st.number_input("Turnover 24h tối thiểu (USDT)", min_value=0,
                              value=10_000_000, step=1_000_000)
    threshold = st.slider("Điểm tối thiểu (/90)", 0, 90, 30, 5)

st.info("Đây là bản quét thủ công theo yêu cầu, chưa dự báo xác suất pump bằng AI, "
        "chưa đo Spot CVD hay OI 4H. Không sử dụng điểm để tự động mua bán.")
if st.button("🔄 QUÉT NGAY", type="primary"):
    if not selected:
        st.warning("Hãy chọn ít nhất một sàn.")
    else:
        with st.spinner("Đang lấy dữ liệu các sàn và tính chỉ báo 1H..."):
            frame, errors = scan(selected, top, minimum)
        st.session_state["frame"] = frame
        st.session_state["errors"] = errors
        st.session_state["scan_time"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")

if "frame" in st.session_state:
    frame = st.session_state["frame"]
    st.caption("Quét gần nhất (UTC): " + st.session_state["scan_time"])
    a, b, c = st.columns(3)
    a.metric("Quan sát", len(frame))
    b.metric("Coin riêng biệt", frame["coin"].nunique() if not frame.empty else 0)
    c.metric("Điểm cao nhất (/90)", int(frame["score /90"].max()) if not frame.empty else 0)
    filtered = frame[frame["score /90"] >= threshold] if not frame.empty else frame
    st.dataframe(filtered, use_container_width=True, hide_index=True)
    if not frame.empty:
        st.download_button("📥 Tải CSV", filtered.to_csv(index=False).encode("utf-8-sig"),
                           file_name="prepump_scanner.csv", mime="text/csv")
    errors = st.session_state.get("errors", [])
    if errors:
        with st.expander(f"Lỗi API / thiếu dữ liệu: {len(errors)}"):
            st.code("\n".join(errors[:60]))
else:
    st.write("Chọn cấu hình và nhấn **QUÉT NGAY** để lấy dữ liệu thực từ bốn sàn.")
