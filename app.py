import concurrent.futures
import datetime as dt
import math
import time

import httpx
import numpy as np
import pandas as pd
import streamlit as st

from accuracy import replay, metrics, breakdown
from market_flow import run_samples
from flow_history import read_archive, summarize_flow, historic_coverage
from signal_core import signal as score_signal_core
from signal_archive import load_signals, tracking_table
from validation_v3 import (
    collect_events, temporal_split, report_rows, report_groups, evaluate, summarize,
)

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
                 "BABA", "PLTR", "HOOD", "XOM", "USO", "SLV", "GLD", "SNDK"}
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

def history(ex, native, lookback=120):
    """Fetch only closed 1H candles. Longer backtests need extended history."""
    lookback = int(max(90, min(lookback, 1200)))
    out = []
    if ex == "binance":
        cursor = None
        while len(out) < lookback:
            params = {"symbol": native, "interval": "1h", "limit": min(1000, lookback - len(out))}
            if cursor is not None:
                params["endTime"] = cursor
            x = api(ex, "/fapi/v1/klines", params)
            if not x:
                break
            out.extend([[int(v[0]), *map(float, [v[1], v[2], v[3], v[4], v[7]])] for v in x])
            cursor = int(x[0][0]) - 1
            if len(x) < params["limit"]:
                break
    elif ex == "bybit":
        cursor = None
        while len(out) < lookback:
            params = {"category": "linear", "symbol": native, "interval": "60",
                      "limit": str(min(1000, lookback - len(out)))}
            if cursor is not None:
                params["end"] = str(cursor)
            x = api(ex, "/v5/market/kline", params)["result"]["list"]
            if not x:
                break
            out.extend([[int(v[0]), *map(float, [v[1], v[2], v[3], v[4], v[6]])] for v in x])
            cursor = min(int(v[0]) for v in x) - 1
            if len(x) < int(params["limit"]):
                break
    elif ex == "okx":
        # History endpoint paginates backward with after=earliest timestamp in ms.
        cursor = None
        while len(out) < lookback:
            params = {"instId": native, "bar": "1H",
                      "limit": str(min(300, lookback - len(out)))}
            if cursor is not None:
                params["after"] = str(cursor)
            x = api(ex, "/api/v5/market/history-candles", params)["data"]
            if not x:
                break
            out.extend([[int(v[0]), *map(float, [v[1], v[2], v[3], v[4], v[7]])]
                        for v in x if len(v) > 8 and str(v[8]) == "1"])
            next_cursor = min(int(v[0]) for v in x)
            if cursor is not None and next_cursor >= cursor:
                break
            cursor = next_cursor
            if len(x) < int(params["limit"]):
                break
    else:
        # MEXC Kline supports start/end Unix seconds and up to 2000 rows.
        x = api(ex, f"/api/v1/contract/kline/{native}",
                {"interval": "Min60",
                 "start": int(time.time() - (lookback + 3) * 3600),
                 "end": int(time.time())})["data"]
        out = [[int(t) * 1000, *[float(x[k][i]) for k in
               ("open", "high", "low", "close", "amount")]]
               for i, t in enumerate(x["time"])]
    df = pd.DataFrame(out, columns=["t", "open", "high", "low", "close", "turnover"])
    if df.empty:
        return df
    df = df.drop_duplicates("t").sort_values("t")
    current_hour = int(time.time() // 3600 * 3600000)
    return df[df["t"] < current_hour].tail(lookback).reset_index(drop=True)

def signal(ex, base, native, price, turnover, candles=None):
    # One shared ruleset for live dashboard, retrospective replay and archive.
    df = history(ex, native) if candles is None else candles
    return score_signal_core(ex, base, native, price, turnover, candles=df)

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


def aggregate_coin_signals(frame):
    """One row per pair. Never sum scores across exchanges or call this a probability."""
    columns = ["coin", "mức ưu tiên", "điểm tổng hợp /100", "trạng thái tổng hợp",
               "sàn có dữ liệu", "số sàn", "đồng thuận", "nén dài nhất (giờ)",
               "breakout gần nhất (giờ)", "RVOL cao nhất", "giá 4H trung vị %",
               "chi tiết theo sàn"]
    if frame.empty:
        return pd.DataFrame(columns=columns)
    rows = []
    strongest = {"NÉN LÂU — ƯU TIÊN 4H", "VỪA BREAKOUT — CÓ THỂ TIẾP DIỄN"}
    watch = {"ĐANG TÍCH LŨY", "BREAKOUT CẦN XÁC NHẬN"}
    for coin, group in frame.groupby("coin", sort=False):
        statuses = set(group["trạng thái 4H"])
        qualifying = group[group["trạng thái 4H"].isin(strongest)]
        watching = group[group["trạng thái 4H"].isin(watch)]
        hot = bool("ĐÃ TĂNG NÓNG" in statuses)
        if not qualifying.empty:
            grade = 0
            status = "ỨNG VIÊN PRE-PUMP 4H"
            candidate = qualifying
        elif not watching.empty:
            grade = 1
            status = "THEO DÕI — CẦN XÁC NHẬN"
            candidate = watching
        else:
            grade = 2
            status = "CHƯA CÓ TÍN HIỆU"
            candidate = group
        # Score = best observed setup, NOT additive independent proof.
        raw_score = int(candidate["điểm 4H /100"].max())
        # A single exchange is unverified; cap confidence of the rank display.
        # Two exchanges may be discordant despite both having observations.
        modes = set()
        for label in statuses:
            if label in {"NÉN LÂU — ƯU TIÊN 4H", "ĐANG TÍCH LŨY"}:
                modes.add("nén")
            elif label in {"VỪA BREAKOUT — CÓ THỂ TIẾP DIỄN", "BREAKOUT CẦN XÁC NHẬN"}:
                modes.add("breakout")
            else:
                modes.add("khác")
        n = group["sàn"].nunique()
        if n == 1:
            consensus = "1 sàn — chưa xác nhận đa sàn"
            score = min(raw_score, 79)
        elif len(modes) == 1:
            consensus = "Cùng nhóm tín hiệu"
            score = raw_score
        else:
            consensus = "Không đồng thuận"
            score = min(raw_score, 69)
        if hot:
            consensus += " / có cảnh báo tăng nóng"
            score = min(score, 49)
            grade = max(grade, 1)
            status = "CẦN KIỂM TRA RỦI RO"
        details = " | ".join(
            f'{r["sàn"].upper()}: {r["trạng thái 4H"]} ({r["điểm 4H /100"]})'
            for _, r in group.sort_values("sàn").iterrows())
        recent = group["breakout cách đây (giờ)"].dropna()
        rows.append({
            "coin": coin, "mức ưu tiên": grade, "điểm tổng hợp /100": score,
            "trạng thái tổng hợp": status,
            "sàn có dữ liệu": ", ".join(sorted(group["sàn"].unique())),
            "số sàn": n, "đồng thuận": consensus,
            "nén dài nhất (giờ)": int(group["thời gian nén liên tục (giờ)"].max()),
            "breakout gần nhất (giờ)": int(recent.min()) if not recent.empty else None,
            "RVOL cao nhất": round(float(group["RVOL 1H"].max()), 2),
            "giá 4H trung vị %": round(float(group["giá 4H %"].median()), 2),
            "chi tiết theo sàn": details,
        })
    return pd.DataFrame(rows, columns=columns).sort_values(
        ["mức ưu tiên", "điểm tổng hợp /100", "số sàn"],
        ascending=[True, False, False]).reset_index(drop=True)

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
st.caption("V2.3: bảng đầu tiên xếp hạng theo coin, gộp quan sát đa sàn và đánh dấu bất đồng. "
           "Dữ liệu giới hạn 100–130 nến; chưa đo Spot CVD, OI hay xác suất 4H. "
           "Chưa bảo đảm lọc hết tài sản phi crypto.")
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
    st.subheader("🔥 TOP COIN CÓ TÍN HIỆU PRE-PUMP 4H")
    st.caption("Mỗi coin một dòng. Nhóm ưu tiên được đưa lên đầu; điểm tổng hợp là điểm kỹ thuật, KHÔNG phải xác suất pump. Dữ liệu khác sàn có thể chưa đồng thuận.")
    ranked = aggregate_coin_signals(frame)
    if ranked.empty:
        st.warning("Chưa có dữ liệu để xếp hạng.")
    else:
        candidates = ranked[ranked["mức ưu tiên"] <= 1].copy()
        if only_setups:
            candidates = candidates[candidates["mức ưu tiên"] == 0]
        candidates = candidates[candidates["điểm tổng hợp /100"] >= threshold]
        if candidates.empty:
            st.info("Chưa có coin đạt mức điểm và điều kiện ưu tiên hiện tại. Có thể hạ bộ lọc để xem nhóm theo dõi, nhưng không coi đó là lệnh mua.")
        else:
            st.dataframe(candidates.drop(columns=["mức ưu tiên"]), use_container_width=True,
                         hide_index=True)
        st.download_button("📥 Tải bảng Pre-Pump tổng hợp (CSV)",
                           ranked.drop(columns=["mức ưu tiên"]).to_csv(index=False).encode("utf-8-sig"),
                           file_name="prepump_4h_ranked.csv", mime="text/csv")
    st.divider()
    st.subheader("🕐 V3.1 — LỊCH SỬ DÒNG TIỀN (THU THẬP THEO GIỜ)")
    st.caption("Kho dữ liệu được GitHub Actions cố gắng cập nhật mỗi giờ. "
               "Tác vụ có thể trễ, thất bại hoặc bị tạm dừng; dữ liệu không liên tục "
               "không được coi là Spot CVD. Lịch sử mới chỉ bắt đầu khi tác vụ chạy thành công.")
    archived = read_archive()
    cov = historic_coverage(archived)
    if cov["rows"] == 0:
        st.info("Chưa có bản ghi trên repository. Xem tab Actions → Archive public market-flow snapshots; "
                "cần workflow chạy thành công và có quyền ghi nội dung.")
    else:
        col1, col2, col3 = st.columns(3)
        col1.metric("Số bản ghi OI/Spot mẫu", cov["rows"])
        col2.metric("Số coin được lưu", cov["coins"])
        col3.metric("Bản ghi cuối UTC", str(cov["last"])[:19])
        summary = summarize_flow(archived)
        fresh = summary[summary["độ trễ (giờ)"].between(0, 3)]
        if fresh.empty:
            st.error("Không có dữ liệu mới trong 3 giờ gần nhất. "
                     "Không dùng OI thay đổi 4H cũ để giao dịch.")
        else:
            st.dataframe(fresh, use_container_width=True, hide_index=True)
            st.caption("OI 4H chỉ xuất hiện khi đủ hai quan sát cùng sàn/coin/đơn vị cách nhau 3–5 giờ. "
                       "Spot imbalance là mẫu giao dịch gần nhất của từng lần chụp, "
                       "KHÔNG phải CVD 4 giờ.")
        with st.expander("Lịch sử dữ liệu được lưu"):
            st.dataframe(archived.tail(300), use_container_width=True, hide_index=True)
        st.download_button("📥 Tải dữ liệu quan sát gần đây", archived.to_csv(index=False).encode("utf-8-sig"),
                           file_name="market_flow_observations.csv", mime="text/csv")
    st.divider()
    st.subheader("📓 V3.1 — NHẬT KÝ TÍN HIỆU SAU KHI PHÁT")
    st.caption("Tín hiệu được tác vụ GitHub Actions ghi theo giờ khi chạy thành công. "
               "Kết quả ~4H là chênh lệch giữa hai giá snapshot cách nhau gần 4 giờ, "
               "KHÔNG phải backtest TP/SL hoặc tỷ lệ giao dịch khớp thật.")
    log = load_signals()
    if log.empty:
        st.info("Chưa có tín hiệu nào được lưu trên GitHub. Kiểm tra workflow theo giờ. "
                "Dữ liệu sẽ chỉ xuất hiện kể từ lần thu thập thành công đầu tiên.")
    else:
        st.metric("Số lần chụp tín hiệu được lưu", len(log))
        followed = tracking_table(log, archived)
        st.dataframe(followed, use_container_width=True, hide_index=True)
        st.download_button("📥 Xuất nhật ký tín hiệu", followed.to_csv(index=False).encode("utf-8-sig"),
                           file_name="prepump_31_live_signal_log.csv", mime="text/csv")
        st.caption("Chỉ những bản ghi có giá sau khoảng 4 giờ mới hiện biến động 4H; "
                   "dữ liệu chưa có được để trống. Không suy ra tỷ lệ pump từ các snapshot chưa đủ mẫu.")
    st.divider()
    st.subheader("🌊 DÒNG TIỀN HIỆN TẠI — OI và giao dịch Spot mẫu")
    st.caption("Dữ liệu này KHÔNG phải OI thay đổi 4H hoặc Spot CVD 4H. "
               "OI là snapshot hiện tại, Spot chỉ là mẫu giao dịch gần nhất. "
               "Không được sử dụng để tính tỷ lệ thành công lịch sử.")
    if st.button("🔍 Kiểm tra dòng tiền top 8 quan sát", key="flow_probe"):
        with st.spinner("Đang kiểm tra nguồn dữ liệu công khai OKX/MEXC..."):
            flow_frame, flow_errors = run_samples(frame, limit=8)
            st.session_state["flow_frame"] = flow_frame
            st.session_state["flow_errors"] = flow_errors
    if "flow_frame" in st.session_state:
        flow_frame = st.session_state["flow_frame"]
        if flow_frame.empty:
            st.warning("Không có dữ liệu flow hỗ trợ từ nguồn hiện tại.")
        else:
            st.dataframe(flow_frame, use_container_width=True, hide_index=True)
            st.caption("OI OKX có thể hiển thị theo USD hoặc base coin; MEXC theo hợp đồng. "
                       "KHÔNG so sánh/cộng trực tiếp OI giữa sàn. "
                       "Spot imbalance dương là mua chủ động trội trong tập trades được trả về, không phải tín hiệu mua.")
        if st.session_state.get("flow_errors"):
            with st.expander("Nguồn dữ liệu flow không khả dụng"):
                st.code("\n".join(st.session_state["flow_errors"]))
    st.divider()
    st.subheader("🧪 V3.0 — KIỂM ĐỊNH 4H / 8H / 24H, MFE / MAE")
    st.warning("Thử nghiệm theo thời gian, KHÔNG phải AI đã huấn luyện hoặc win rate đã xác nhận. "
               "Dùng bộ quy tắc vốn đã được điều chỉnh trên dữ liệu trước đây; "
               "phần kiểm định cuối kỳ chưa phải mẫu ngoài tập tuyệt đối. "
               "Chưa dùng Spot CVD, OI lịch sử hoặc funding trong thuật toán.")
    p1, p2, p3 = st.columns(3)
    with p1:
        v3_count = st.slider("V3: cặp sàn–coin", 5, 40, 20, 5, key="v3_pairs")
    with p2:
        v3_cost = st.number_input("V3: phí + trượt giá 2 chiều %", 0.0, 5.0,
                                  0.25, 0.05, key="v3_cost")
    with p3:
        v3_stop = st.number_input("V3: cắt lỗ %", 0.5, 20.0,
                                  2.0, 0.5, key="v3_stop")
    if st.button("🔬 CHẠY KIỂM ĐỊNH V3", key="v3_run"):
        chosen = (frame.sort_values("turnover 24h USDT", ascending=False)
                       .drop_duplicates(["sàn", "coin"]).head(v3_count))
        jobs = []
        for _, item in chosen.iterrows():
            ex = item["sàn"]
            base = item["coin"].removesuffix("/USDT")
            native = (base + "USDT" if ex in ("binance", "bybit") else
                      base + "-USDT-SWAP" if ex == "okx" else base + "_USDT")
            jobs.append((ex, item["coin"], native,
                         float(item["turnover 24h USDT"])))
        windows, cover, errors_v3 = [], [], []
        def run_one(job):
            ex, pair, native, turnover = job
            candles = history(ex, native, lookback=900)
            events = collect_events(candles, signal, ex, pair, native, turnover)
            return len(candles), events
        with st.spinner("Đang kiểm định 24 giờ không chồng lấn theo từng cặp..."):
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                pending = {pool.submit(run_one, job): job for job in jobs}
                for future in concurrent.futures.as_completed(pending):
                    job = pending[future]
                    try:
                        count, events = future.result()
                        windows.extend(events)
                        cover.append({"sàn": job[0], "coin": job[1],
                                      "nến lịch sử": count, "cửa sổ 24H": len(events),
                                      "sự kiện Scanner": sum(e["nhóm"] is not None for e in events)})
                    except Exception as exc:
                        errors_v3.append(f"{job[0]} {job[1]}: {str(exc)[:140]}")
        dev, hold, boundary = temporal_split(windows, .30, 24)
        st.session_state["v3_data"] = {
            "development": report_rows(dev, "Phát triển", v3_stop, v3_cost),
            "holdout": report_rows(hold, "Cuối kỳ", v3_stop, v3_cost),
            "groups": report_groups(hold, v3_stop, v3_cost),
            "boundary": boundary,
            "coverage": pd.DataFrame(cover),
            "errors": errors_v3,
            "dev_n": len(dev),
            "hold_n": len(hold),
            "dev_signals": sum(e["nhóm"] is not None for e in dev),
            "hold_signals": sum(e["nhóm"] is not None for e in hold),
            "hold_coins": len({e["coin"] for e in hold if e["nhóm"] is not None}),
            "stop": v3_stop,
            "cost": v3_cost,
        }
    if "v3_data" in st.session_state:
        data = st.session_state["v3_data"]
        st.caption(f"Cắt theo thời gian UTC tại: {data['boundary']}; "
                   f"loại 24H quanh ranh giới ở phần phát triển. "
                   "Mỗi cặp chỉ lấy một cửa sổ 24H để tránh tín hiệu chồng lấn trong cùng cặp.")
        n1, n2, n3 = st.columns(3)
        n1.metric("Tín hiệu phần phát triển", data["dev_signals"])
        n2.metric("Tín hiệu phần cuối kỳ", data["hold_signals"])
        n3.metric("Coin có tín hiệu cuối kỳ", data["hold_coins"])
        if data["hold_signals"] < 200 or data["hold_coins"] < 10:
            st.error("KHÔNG ĐỦ CƠ SỞ ĐÁNH GIÁ GIAO DỊCH THỰC: "
                     "cần thêm tín hiệu độc lập và nhiều coin trên giai đoạn chưa dùng chỉnh tham số.")
        st.markdown("**Đánh giá cuối kỳ (70/30 theo thời gian, có khoảng cách 24H)**")
        st.dataframe(data["holdout"], use_container_width=True, hide_index=True)
        st.markdown("**So sánh nhóm tín hiệu tại 4H / TP +4% / SL theo cấu hình**")
        if data["groups"].empty:
            st.info("Chưa có tín hiệu đủ điều kiện ở phần cuối kỳ.")
        else:
            st.dataframe(data["groups"], use_container_width=True, hide_index=True)
        with st.expander("Xem kết quả phần phát triển và độ phủ dữ liệu"):
            st.dataframe(data["development"], use_container_width=True, hide_index=True)
            st.dataframe(data["coverage"], use_container_width=True, hide_index=True)
        if data["errors"]:
            with st.expander(f"Lỗi dữ liệu kiểm định V3 ({len(data['errors'])})"):
                st.code("\n".join(data["errors"][:40]))
        if not data["holdout"].empty:
            st.download_button("📥 Tải báo cáo V3 (CSV)",
                               data["holdout"].to_csv(index=False).encode("utf-8-sig"),
                               file_name="pre_pump_v3_temporal_validation.csv",
                               mime="text/csv")
    st.divider()
    st.subheader("📊 PRE-PUMP ACCURACY TRACKER — Kiểm định lịch sử 4H")
    st.warning("KIỂM ĐỊNH HỒI TƯỞNG, CHƯA PHẢI WIN RATE THỰC TẾ. "
               "Chỉ dùng dữ liệu nến 1H gần đây và bộ quy tắc hiện tại. "
               "Kết quả có thể sai lệch do chọn mẫu, quá ít dữ liệu, phí ước tính "
               "và chưa tính funding. Không dùng như lời khuyên mua.")
    h1, h2, h3, h4 = st.columns(4)
    with h1:
        take_pct = st.number_input("Chốt lời (%)", min_value=0.5, max_value=30.0,
                                   value=4.0, step=0.5, key="bt_take")
    with h2:
        stop_pct = st.number_input("Cắt lỗ (%)", min_value=0.5, max_value=20.0,
                                   value=2.0, step=0.5, key="bt_stop")
    with h3:
        costs_pct = st.number_input("Phí + trượt giá hai chiều (%)",
                                    min_value=0.0, max_value=5.0,
                                    value=0.25, step=0.05, key="bt_cost")
    with h4:
        sample_count = st.slider("Số quan sát để thử", 5, 40, 20, 5, key="bt_symbols")
    if st.button("🧪 CHẠY KIỂM ĐỊNH 4H", type="secondary"):
        to_test = (frame.drop_duplicates(["sàn", "coin"])
                       .sort_values("turnover 24h USDT", ascending=False)
                       .head(sample_count))
        jobs = []
        for _, item in to_test.iterrows():
            ex = item["sàn"]
            base = item["coin"].removesuffix("/USDT")
            native = (base + "USDT" if ex in ("binance", "bybit")
                      else base + "-USDT-SWAP" if ex == "okx"
                      else base + "_USDT")
            jobs.append((ex, item["coin"], native, float(item["turnover 24h USDT"])))
        parts, errors_bt, coverage = [], [], []
        with st.spinner("Đang tải nến đóng, phát lại các tín hiệu lịch sử và kiểm tra 4H..."):
            def one_test(job):
                ex, pair, native, turnover = job
                candles = history(ex, native, lookback=600)
                out = replay(candles, signal, ex, pair, turnover,
                              take_pct=take_pct, stop_pct=stop_pct,
                              roundtrip_cost_pct=costs_pct, stride=4)
                return out, len(candles)
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                futures = {pool.submit(one_test, job): job for job in jobs}
                for future in concurrent.futures.as_completed(futures):
                    try:
                        result, candle_count = future.result()
                        coverage.append({"sàn": futures[future][0], "coin": futures[future][1],
                                         "nến 1H đóng": candle_count,
                                         "tín hiệu lịch sử": len(result)})
                        if not result.empty:
                            parts.append(result)
                    except Exception as err:
                        job = futures[future]
                        errors_bt.append(f"{job[0]} {job[1]}: {str(err)[:130]}")
        st.session_state["accuracy_trades"] = (
            pd.concat(parts, ignore_index=True) if parts else pd.DataFrame())
        st.session_state["accuracy_errors"] = errors_bt
        st.session_state["accuracy_coverage"] = pd.DataFrame(coverage)
        st.session_state["accuracy_params"] = (take_pct, stop_pct, costs_pct)
    if "accuracy_trades" in st.session_state:
        trades = st.session_state["accuracy_trades"]
        coverage = st.session_state.get("accuracy_coverage", pd.DataFrame())
        if not coverage.empty:
            st.caption(f"Đã tải {len(coverage)} cặp sàn-coin; "
                       f"trung vị {int(coverage['nến 1H đóng'].median())} nến 1H đóng mỗi cặp.")
            with st.expander("Kiểm tra độ phủ dữ liệu kiểm định"):
                st.dataframe(coverage, use_container_width=True, hide_index=True)
        if trades.empty:
            st.info("Không tìm được tín hiệu lịch sử đủ điều kiện theo bộ quy tắc hiện tại. "
                    "Không thể tính tỷ lệ dự đoán đúng.")
        else:
            distinct_assets = trades["coin"].nunique()
            distinct_exchange_pairs = trades[["sàn", "coin"]].drop_duplicates().shape[0]
            st.caption(f"Kiểm định gồm {distinct_assets} mã tài sản, "
                       f"{distinct_exchange_pairs} cặp sàn–mã, {len(trades)} tín hiệu.")
            if distinct_assets < 5:
                st.error("MẪU KHÔNG ĐẠI DIỆN: Quá ít mã tài sản. "
                         "Không dùng tỷ lệ thắng/Profit Factor này để suy luận về khả năng pump của thị trường crypto.")
            m = metrics(trades)
            a, b, c, d = st.columns(4)
            a.metric("Tín hiệu mẫu", str(m["số tín hiệu"]))
            b.metric("Đạt +4% trước -2%*" if st.session_state["accuracy_params"][:2] == (4.0, 2.0)
                     else "Đạt take-profit trước stop", f'{m["tỷ lệ đạt mục tiêu %"]:.1f}%')
            c.metric("Lợi nhuận TB sau phí*", f'{m["lợi nhuận TB sau chi phí %"]:.3f}%')
            d.metric("Profit factor", str(m["profit factor"]) if m["profit factor"] is not None else "N/A")
            if len(trades) < 200:
                st.warning(f"Chỉ {len(trades)} tín hiệu lịch sử: mẫu nhỏ, không đủ để kết luận hiệu quả dự báo.")
            st.caption("*Giả định: giá vào = mở cửa nến sau tín hiệu, kiểm tra tối đa 4 nến 1H đã đóng; "
                       "TP/SL theo cấu hình; nếu nến chạm cả TP và SL thì tính SL trước. "
                       "Các sự kiện không chồng lấn trong cùng hợp đồng, nhưng cùng coin đa sàn có tương quan. "
                       "Chưa tính funding; không có dữ liệu lệnh khớp thực.")
            st.dataframe(breakdown(trades), use_container_width=True, hide_index=True)
            with st.expander("Xem từng tín hiệu đã kiểm định"):
                st.dataframe(trades, use_container_width=True, hide_index=True)
            st.download_button("📥 Xuất CSV kiểm định 4H",
                               trades.to_csv(index=False).encode("utf-8-sig"),
                               file_name="accuracy_4h_exploratory.csv",
                               mime="text/csv")
        if st.session_state.get("accuracy_errors"):
            with st.expander("Lỗi lấy dữ liệu kiểm định"):
                st.code("\n".join(st.session_state["accuracy_errors"][:25]))
    st.divider()
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
