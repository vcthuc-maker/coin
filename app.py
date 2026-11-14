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
# Block obvious traditional-asset derivatives; this is NOT a verified crypto-only registry.
EXCLUDE = ("XAU", "XAG", "OIL", "GOLD", "SILVER", "EUR", "GBP", "JPY",
           "USOIL", "UKOIL", "SOXS", "QQQ", "SPY", "SHELL", "STOCK")
EXACT_EXCLUDE = {"CL", "GC", "SI", "NG", "ES", "NQ", "YM", "DXY", "SPX",
                 "NVDA", "NVIDIA", "MU", "TSLA", "AAPL", "MSFT", "GOOGL",
                 "GOOG", "AMZN", "META", "NFLX", "AMD", "INTC", "COIN",
                 "MSTR", "QQQ", "SPY", "SHELL", "SOXS", "SOXL", "SKHYNIX",
                 "BABA", "PLTR", "HOOD", "XOM", "USO", "SLV", "GLD"}
# Symbol exclusions are only a temporary safeguard; a verified asset-type
# catalog is needed before labeling the universe as strictly crypto.

def number(value, default=np.nan):
    try:
        x = float(value)
        return x if math.isfinite(x) else default
    except (TypeError, ValueError):
        return default

def api(ex, path, params=None):
    r = httpx.get(BASE[ex] + path, params=params, timeout=13.0,
                  headers={"User-Agent": "PrePumpScanner/1.1"})
    if r.status_code in (403, 451):
        msg = ("Giới hạn khu vực/IP theo chính sách sàn (HTTP "
               + str(r.status_code) + "). Không thể truy cập từ hosting hiện tại.")
        raise RuntimeError(msg)
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
        # MEXC ticker can include delisted, paused or non-kline-enabled contracts.
        # Fetch contract metadata ONCE per scan, not once per symbol.
        metadata = api(ex, "/api/v1/contract/detail")["data"]
        allowed = {m.get("symbol") for m in metadata
                   if m.get("state") == 0 and m.get("quoteCoin") == "USDT"
                   and m.get("futureType", 1) == 1}
        raw = api(ex, "/api/v1/contract/ticker")["data"]
        for r in raw if isinstance(raw, list) else [raw]:
            sym = r.get("symbol", "")
            if sym.endswith("_USDT") and sym in allowed:
                rows.append((sym[:-5], sym, number(r.get("lastPrice")), number(r.get("amount24"))))
    return [r for r in rows if r[0] and r[0].upper() not in EXACT_EXCLUDE
            and not any(x in r[0].upper() for x in EXCLUDE)
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
    # Pre-4H breakout setup: accumulation is only a proxy from OHLCV,
    # NOT proof of whale buying. All measurements use closed 1H candles.
    price24 = (close.iloc[-1] / close.iloc[-25] - 1) * 100
    recent_range = (high.iloc[-8:].max() / df["low"].iloc[-8:].min() - 1) * 100
    # Compare last 2 complete hours against preceding 6 hours.
    vol_accel = float(vol.iloc[-2:].mean() / max(vol.iloc[-8:-2].mean(), 1e-9))
    price_vs_ema = (close.iloc[-1] / ema20.iloc[-1] - 1) * 100
    # Breakout must not already be far above previous 24h resistance.
    near_resistance = -0.5 <= distance <= 3
    compressed = bb_pct <= 35 and recent_range <= 6
    controlled_price = -2 <= change4h <= 3 and -5 <= price24 <= 8
    demand_warming = rvol >= 0.8 and vol_accel >= 1.15
    trend_ready = 45 <= rsi <= 67 and -1 <= price_vs_ema <= 3
    overheated = (change4h > 5 or price24 > 12 or rsi > 72
                  or distance < -2 or rvol > 8)
    score = 0
    reasons = []
    if bb_pct <= 25:
        score += 20
        reasons.append("BB nén mạnh")
    elif bb_pct <= 35:
        score += 13
        reasons.append("BB đang nén")
    if recent_range <= 4:
        score += 10
        reasons.append("Biên 8H hẹp")
    elif recent_range <= 6:
        score += 6
    if -2 <= change4h <= 2 and -4 <= price24 <= 6:
        score += 15
        reasons.append("Giá chưa tăng nóng")
    elif controlled_price:
        score += 8
    if 0.8 <= rvol <= 3.5 and vol_accel >= 1.15:
        score += 20
        reasons.append("Volume đang tăng")
    elif 1.2 <= rvol <= 5:
        score += 10
    if near_resistance:
        score += 15
        reasons.append("Sát kháng cự")
    if trend_ready:
        score += 15
        reasons.append("Động lượng phù hợp")
    elif close.iloc[-1] > ema20.iloc[-1] and rsi < 70:
        score += 7
    if -1 <= price_vs_ema <= 2:
        score += 5

    # Hard guards: no strong early-pump label without BOTH price compression
    # and rising turnover; avoid chasing already extended candles.
    if not compressed:
        score = min(score, 64)
    if not controlled_price:
        score = min(score, 55)
    if rvol < 0.8 or vol_accel < 1.15:
        score = min(score, 59)
        reasons.append("Chưa có xác nhận volume")
    if overheated:
        score = min(score, 39)
        reasons.append("Cảnh báo tăng nóng / mua đuổi")
    score = min(score, 100)
    if overheated:
        phase = "ĐÃ TĂNG NÓNG"
    elif score >= 75 and compressed and controlled_price and demand_warming and near_resistance:
        phase = "ƯU TIÊN 4H"
    elif score >= 55 and compressed and controlled_price:
        phase = "THEO DÕI TÍCH LŨY"
    else:
        phase = "CHƯA XÁC NHẬN"

    return {"sàn": ex, "coin": f"{base}/USDT", "trạng thái 4H": phase,
            "Tích lũy 4H /100": int(score),
            "giá": price, "turnover 24h USDT": round(turnover, 2),
            "RVOL 1H": round(rvol, 2),
            "volume tăng tốc": round(vol_accel, 2),
            "RSI 1H": round(rsi, 1), "BB percentile": round(bb_pct, 1),
            "biên 8H %": round(recent_range, 2),
            "cách kháng cự %": round(distance, 2),
            "giá 4H %": round(change4h, 2),
            "giá 24H %": round(price24, 2),
            "lý do": ", ".join(reasons)}

def scan(selected, top, min_turnover):
    jobs, errors = [], []
    status = {ex: "Chưa quét" for ex in selected}
    for ex in selected:
        try:
            choices = sorted((m for m in find_markets(ex) if m[3] >= min_turnover),
                             key=lambda r: r[3], reverse=True)[:top]
            jobs.extend((ex, *m) for m in choices)
            status[ex] = f"Đã lấy danh sách ({len(choices)} hợp đồng)"
        except Exception as exc:
            status[ex] = "KHÔNG truy cập được dữ liệu"
            errors.append(f"{ex}: không lấy được danh sách — {exc}")
    results = []
    skipped = {ex: 0 for ex in selected}
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(signal, *j): j for j in jobs}
        for fut in concurrent.futures.as_completed(futures):
            try:
                v = fut.result()
                if v is not None:
                    results.append(v)
            except Exception as exc:
                j = futures[fut]
                # Many MEXC symbols return 510 despite appearing in its ticker.
                # Count as unavailable rather than treating them as trading signals.
                skipped[j[0]] += 1
                if len([e for e in errors if e.startswith(j[0] + " ")]) < 5:
                    errors.append(f"{j[0]} {j[1]}: {str(exc)[:150]}")
    for ex in selected:
        if status[ex].startswith("Đã lấy"):
            success = sum(x["sàn"] == ex for x in results)
            status[ex] = f"{success} có dữ liệu; {skipped[ex]} lỗi/không hỗ trợ"
    results.sort(key=lambda x: (x["Tích lũy 4H /100"], x["volume tăng tốc"]), reverse=True)
    return pd.DataFrame(results), errors, status

with st.sidebar:
    st.header("Cấu hình quét")
    selected = st.multiselect("Sàn", list(BASE), default=list(BASE))
    top = st.slider("Hợp đồng mỗi sàn", 5, 60, 15, 5)
    minimum = st.number_input("Turnover 24h tối thiểu (USDT)", min_value=0,
                              value=10_000_000, step=1_000_000)
    threshold = st.slider("Điểm tối thiểu tích lũy (/100)", 0, 100, 50, 5)
    only_setups = st.checkbox("Chỉ hiển thị ứng viên tích lũy", value=False)

st.info("Bộ lọc tích lũy và chuẩn bị breakout trong 4 giờ: dùng nến 1H đã đóng, "
        "Bollinger squeeze, biên giá, tăng tốc volume, RSI và khoảng cách kháng cự. "
        "Đây là HEURISTIC chưa backtest, KHÔNG phải xác suất pump, không đo Spot CVD/OI.")
st.caption("ƯU TIÊN 4H = setup kỹ thuật phù hợp, không đảm bảo giá tăng. "
           "Bộ lọc tài sản truyền thống theo ticker hiện chưa đầy đủ, không phải xác minh loại tài sản.")
if st.button("🔄 QUÉT NGAY", type="primary"):
    if not selected:
        st.warning("Hãy chọn ít nhất một sàn.")
    else:
        with st.spinner("Đang lấy dữ liệu các sàn và tính chỉ báo 1H..."):
            frame, errors, status = scan(selected, top, minimum)
        st.session_state["frame"] = frame
        st.session_state["errors"] = errors
        st.session_state["status"] = status
        st.session_state["scan_time"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")

if "frame" in st.session_state:
    frame = st.session_state["frame"]
    st.caption("Quét gần nhất (UTC): " + st.session_state["scan_time"])
    st.subheader("Trạng thái kết nối 4 sàn")
    for ex, info in st.session_state.get("status", {}).items():
        if "KHÔNG" in info:
            st.error(f"{ex.upper()}: {info}")
        else:
            st.caption(f"{ex.upper()}: {info}")
    a, b, c = st.columns(3)
    a.metric("Quan sát", len(frame))
    b.metric("Coin riêng biệt", frame["coin"].nunique() if not frame.empty else 0)
    c.metric("Điểm tích lũy cao nhất (/100)", int(frame["Tích lũy 4H /100"].max()) if not frame.empty else 0)
    filtered = frame[frame["Tích lũy 4H /100"] >= threshold] if not frame.empty else frame
    if only_setups and not filtered.empty:
        filtered = filtered[filtered["trạng thái 4H"].isin(["ƯU TIÊN 4H", "THEO DÕI TÍCH LŨY"])]
    st.subheader("Ứng viên có khả năng chuẩn bị breakout 4 giờ")
    st.caption("Bảng chỉ hiện khi đủ cả cấu trúc tích lũy, volume tăng, giá chưa tăng nóng và gần kháng cự.")
    if frame.empty:
        st.warning("Không thu được dữ liệu. Xem trạng thái API ở trên.")
    else:
        preferred = frame[frame["trạng thái 4H"] == "ƯU TIÊN 4H"]
        st.metric("Setup ưu tiên 4H", len(preferred))
        st.dataframe(preferred, use_container_width=True, hide_index=True)
        if preferred.empty:
            st.caption("Chưa có ứng viên vượt đầy đủ điều kiện. Không ép tạo tín hiệu mua.")
        st.subheader("Ứng viên tích lũy cần quan sát thêm")
        watchlist = filtered[filtered["trạng thái 4H"] == "THEO DÕI TÍCH LŨY"]
        if not watchlist.empty:
            st.dataframe(watchlist, use_container_width=True, hide_index=True)
        else:
            st.caption("Chưa có coin đang tích lũy đủ điểm theo dõi.")
        st.subheader("Toàn bộ kết quả đã lọc")
        st.dataframe(filtered, use_container_width=True, hide_index=True)
        st.caption("Cùng một coin trên hai sàn được ghi thành hai quan sát, chưa xác nhận Spot CVD hay OI.")
    if not frame.empty:
        st.download_button("📥 Tải CSV", filtered.to_csv(index=False).encode("utf-8-sig"),
                           file_name="prepump_scanner.csv", mime="text/csv")
    errors = st.session_state.get("errors", [])
    if errors:
        with st.expander(f"Ví dụ lỗi API / thiếu dữ liệu ({len(errors)} thông báo; xem số lượng theo sàn ở trên)"):
            st.code("\n".join(errors[:60]))
else:
    st.write("Chọn cấu hình và nhấn **QUÉT NGAY** để lấy dữ liệu thực từ bốn sàn.")
