"""Optional LIVE-only contextual checks: NOT historical 4h OI/CVD evidence.

Spot net taker notional from recent public trades is a SHORT SAMPLE,
not a complete 4h CVD series. Current open interest is a SNAPSHOT.
Do not feed these data into retrospective scoring or validation.
"""
import math
import time

import httpx
import pandas as pd


def _get(url, params):
    r = httpx.get(url, params=params, timeout=10.0,
                  headers={"User-Agent": "PrePumpScanner/3.0"})
    if r.status_code in (403, 451):
        raise RuntimeError(f"API bị từ chối truy cập (HTTP {r.status_code})")
    r.raise_for_status()
    return r.json()


def _finite(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def _sample_stats(trades):
    if not trades:
        return None, None, None, 0
    buy = sum(t[1] for t in trades if t[0] == "buy")
    sell = sum(t[1] for t in trades if t[0] == "sell")
    total = buy + sell
    if total <= 0:
        return None, None, None, len(trades)
    return round(buy - sell, 2), round((buy - sell) / total * 100, 2), \
        round((max(t[2] for t in trades) - min(t[2] for t in trades)) / 60000, 1), len(trades)


def probe_okx(base):
    pair = base + "-USDT"
    derivatives = base + "-USDT-SWAP"
    oi_raw = _get("https://www.okx.com/api/v5/public/open-interest",
                  {"instType": "SWAP", "instId": derivatives})
    if oi_raw.get("code") != "0":
        raise RuntimeError("OI OKX: " + str(oi_raw.get("msg")))
    items = oi_raw.get("data") or []
    oi_usd = _finite(items[0].get("oiUsd")) if items else None
    if oi_usd is None and items:
        oi_usd = _finite(items[0].get("oiCcy"))
        oi_usd = None if oi_usd is None else oi_usd  # native units, NOT USD
    # CVD-like net of only the most recent public trades, not a 4h cumulative history.
    spot = _get("https://www.okx.com/api/v5/market/trades",
                {"instId": pair, "limit": "100"})
    if spot.get("code") != "0":
        raise RuntimeError("Spot OKX: " + str(spot.get("msg")))
    trades = []
    for t in spot.get("data", []):
        price, size = _finite(t.get("px")), _finite(t.get("sz"))
        if price is not None and size is not None and t.get("side") in ("buy", "sell"):
            trades.append((t["side"], price * size, int(t.get("ts", 0))))
    delta, imbalance, minutes, count = _sample_stats(trades)
    return {"oi_gốc": oi_usd, "đơn vị OI": "USD" if items and _finite(items[0].get("oiUsd")) is not None else "base coin",
            "Spot mua-bán ròng USDT (mẫu)": delta, "Spot imbalance % (mẫu)": imbalance,
            "khoảng mẫu phút": minutes, "số trades Spot": count}


def probe_mexc(base):
    native = base + "_USDT"
    raw = _get("https://contract.mexc.com/api/v1/contract/ticker",
               {"symbol": native})
    if not raw.get("success"):
        raise RuntimeError("Ticker MEXC: " + str(raw.get("code")))
    obj = raw.get("data") or {}
    if isinstance(obj, list):
        obj = next((v for v in obj if v.get("symbol") == native), {})
    oi_contracts = _finite(obj.get("holdVol"))
    if oi_contracts is None:
        raise RuntimeError("Không có OI hợp đồng MEXC")
    spot = _get("https://api.mexc.com/api/v3/trades",
                {"symbol": base + "USDT", "limit": 500})
    trades = []
    for t in spot if isinstance(spot, list) else []:
        px, qty = _finite(t.get("price")), _finite(t.get("qty"))
        if px is not None and qty is not None:
            side = "sell" if t.get("isBuyerMaker") else "buy"
            trades.append((side, px * qty, int(t.get("time", 0))))
    delta, imbalance, minutes, count = _sample_stats(trades)
    return {"oi_gốc": oi_contracts, "đơn vị OI": "contracts",
            "Spot mua-bán ròng USDT (mẫu)": delta, "Spot imbalance % (mẫu)": imbalance,
            "khoảng mẫu phút": minutes, "số trades Spot": count}


def probe(exchange, pair):
    base = pair.rsplit("/", 1)[0]
    if exchange == "okx":
        return probe_okx(base)
    if exchange == "mexc":
        return probe_mexc(base)
    raise RuntimeError("Sàn không hỗ trợ API từ hosting hoặc chưa có bộ thu thập")


def run_samples(frame, limit=8):
    output, errors = [], []
    if frame.empty:
        return pd.DataFrame(), errors
    # Prefer highest-scored candidates; each row remains exchange specific.
    rows = frame.sort_values("điểm 4H /100", ascending=False).head(limit)
    for _, row in rows.iterrows():
        ex, pair = row["sàn"], row["coin"]
        try:
            data = probe(ex, pair)
            output.append({"sàn": ex, "coin": pair,
                           "lấy lúc UTC": pd.Timestamp.now(tz="UTC"),
                           **data})
        except Exception as exc:
            errors.append(f"{ex} {pair}: {str(exc)[:180]}")
    return pd.DataFrame(output), errors
