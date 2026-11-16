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
    results.sort(key=lambda x: (x["điểm 4H /100"], x["thời gian nén liên tục (giờ)"]), reverse=True)
    return pd.DataFrame(results), errors, status

with st.sidebar:
    st.header("Cấu hình quét")
    selected = st.multiselect("Sàn", list(BASE), default=list(BASE))
    top = st.slider("Hợp đồng mỗi sàn", 5, 60, 15, 5)
    minimum = st.number_input("Turnover 24h tối thiểu (USDT)", min_value=0,
                              value=10_000_000, step=1_000_000)
    threshold = st.slider("Điểm tối thiểu (/100)", 0, 100, 50, 5)
    minimum_compression = st.slider("Số giờ nén liên tục tối thiểu (nhóm tích lũy)", 0, 48, 6, 2)
    only_setups = st.checkbox("Chỉ hiển thị tích lũy / breakout gần đây", value=False)

st.info("V2.2: Đo thời gian nén liên tục trên nến 1H và phát hiện breakout xảy ra trong 4 nến 1H đã đóng. "
        "Hai nhóm: tích lũy lâu chưa breakout và vừa breakout có điều kiện tiếp diễn. "
        "Đây là điểm quy tắc chưa backtest, KHÔNG phải xác suất pump hay lời khuyên mua bán.")
st.caption("Dữ liệu giới hạn khoảng 100–130 nến gần nhất; thời gian nén dài hơn lịch sử có thể bị đánh giá thấp. "
           "Chưa xác nhận dòng tiền Spot CVD hoặc OI; chưa bảo đảm lọc hết tài sản phi crypto.")
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
    c.metric("Điểm 4H cao nhất (/100)", int(frame["điểm 4H /100"].max()) if not frame.empty else 0)
    filtered = frame[frame["điểm 4H /100"] >= threshold] if not frame.empty else frame
    setup_names = ["NÉN LÂU — ƯU TIÊN 4H", "ĐANG TÍCH LŨY",
                   "VỪA BREAKOUT — CÓ THỂ TIẾP DIỄN", "BREAKOUT CẦN XÁC NHẬN"]
    if only_setups and not filtered.empty:
        filtered = filtered[filtered["trạng thái 4H"].isin(setup_names)]
    st.subheader("🕒 Nén lâu — chuẩn bị breakout trong 4 giờ")
    if frame.empty:
        st.warning("Không có dữ liệu từ các sàn. Kiểm tra API.")
    else:
        compressed = frame[
            frame["trạng thái 4H"].isin(["NÉN LÂU — ƯU TIÊN 4H", "ĐANG TÍCH LŨY"]) &
            (frame["thời gian nén liên tục (giờ)"] >= minimum_compression)
        ]
        priority = compressed[compressed["trạng thái 4H"] == "NÉN LÂU — ƯU TIÊN 4H"]
        st.metric("Ứng viên nén lâu ưu tiên", len(priority))
        st.dataframe(compressed, use_container_width=True, hide_index=True)
        if compressed.empty:
            st.caption("Chưa có setup nén lâu đạt điều kiện. Không tự tạo tín hiệu.")
        st.subheader("🚀 Vừa breakout — kiểm tra khả năng tiếp diễn")
        continuation = frame[frame["trạng thái 4H"].isin(
            ["VỪA BREAKOUT — CÓ THỂ TIẾP DIỄN", "BREAKOUT CẦN XÁC NHẬN"])]
        st.metric("Breakout trong 4 nến 1H gần nhất", len(continuation))
        st.dataframe(continuation, use_container_width=True, hide_index=True)
        if continuation.empty:
            st.caption("Chưa phát hiện breakout đạt định nghĩa kiểm thử.")
        st.subheader("Toàn bộ kết quả đã lọc")
        st.dataframe(filtered, use_container_width=True, hide_index=True)
        st.caption("Thời gian tính từ các nến đóng; không phải bằng chứng cá voi tích trữ. "
                   "Hai sàn có thể ghi nhận cùng một coin dưới hai dòng khác nhau.")
    if not frame.empty:
        st.download_button("📥 Tải CSV", filtered.to_csv(index=False).encode("utf-8-sig"),
                           file_name="prepump_scanner.csv", mime="text/csv")
    errors = st.session_state.get("errors", [])
    if errors:
        with st.expander(f"Ví dụ lỗi API / thiếu dữ liệu ({len(errors)} thông báo; xem số lượng theo sàn ở trên)"):
            st.code("\n".join(errors[:60]))
else:
    st.write("Chọn cấu hình và nhấn **QUÉT NGAY** để lấy dữ liệu thực từ bốn sàn.")
