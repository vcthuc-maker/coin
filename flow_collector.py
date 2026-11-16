"""Hourly public-data collector for GitHub Actions.

Append-only UTC hourly observations, idempotent by (hour, exchange, coin).
This is *not* uninterrupted tick-by-tick Spot CVD. Recent-trade buy/sell
imbalance is a snapshot sample of varying time span.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import os
from pathlib import Path
import time
import httpx

BASES = ("BTC", "ETH", "SOL", "DOGE", "SUI", "LINK", "TAO", "WLD",
         "NEAR", "INJ", "AVAX", "XRP", "ADA", "BNB", "PEPE")
EXCHANGES = ("okx", "mexc")
ROOT = Path(__file__).resolve().parent / "data" / "flow"
HTTP_TIMEOUT = 10.0


def num(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (ValueError, TypeError):
        return None


def get(client, url, params=None):
    res = client.get(url, params=params, timeout=HTTP_TIMEOUT)
    if res.status_code in (403, 451):
        raise RuntimeError("exchange denied hosting IP (HTTP %s)" % res.status_code)
    res.raise_for_status()
    body = res.json()
    if isinstance(body, dict) and body.get("success") is False:
        raise RuntimeError("API code %s" % body.get("code"))
    if isinstance(body, dict) and "code" in body and str(body["code"]) not in ("0", "200"):
        raise RuntimeError("API code %s" % body["code"])
    return body


def spot_sample(trades):
    buy = 0.0
    sell = 0.0
    timestamps = []
    for side, qty, stamp in trades:
        if qty is None or qty <= 0:
            continue
        if side == "buy":
            buy += qty
        elif side == "sell":
            sell += qty
        else:
            continue
        timestamps.append(stamp)
    total = buy + sell
    return {
        "spot_sample_count": len(timestamps),
        "spot_sample_minutes": round((max(timestamps) - min(timestamps)) / 60000, 3) if len(timestamps) >= 2 else None,
        "spot_sample_buy_usdt": round(buy, 3),
        "spot_sample_sell_usdt": round(sell, 3),
        "spot_sample_imbalance_pct": round((buy-sell) / total * 100, 3) if total > 0 else None,
    }


def collect_okx(client, base):
    pair = f"{base}-USDT-SWAP"
    spot = f"{base}-USDT"
    oi = get(client, "https://www.okx.com/api/v5/public/open-interest",
             {"instType": "SWAP", "instId": pair}).get("data", [])
    if not oi or num(oi[0].get("oiUsd")) is None:
        raise RuntimeError("OKX missing OI USD; do not guess notional")
    spot_rows = get(client, "https://www.okx.com/api/v5/market/trades",
                    {"instId": spot, "limit": "100"}).get("data", [])
    trades = []
    for trade in spot_rows:
        px, sz = num(trade.get("px")), num(trade.get("sz"))
        if px is not None and sz is not None:
            trades.append((trade.get("side"), px * sz, int(trade.get("ts", 0))))
    ticker = get(client, "https://www.okx.com/api/v5/market/ticker",
                 {"instId": pair}).get("data", [])
    if not ticker:
        raise RuntimeError("OKX ticker unavailable")
    price = num(ticker[0].get("last"))
    if price is None:
        raise RuntimeError("OKX invalid last price")
    result = spot_sample(trades)
    result.update({
        "oi_value": num(oi[0]["oiUsd"]), "oi_unit": "USD",
        "price_usdt": price, "funding_rate": None,
    })
    return result


def collect_mexc(client, base):
    native = f"{base}_USDT"
    info = get(client, "https://contract.mexc.com/api/v1/contract/detail",
               {"symbol": native}).get("data")
    if isinstance(info, list):
        info = next((r for r in info if r.get("symbol") == native), None)
    if not isinstance(info, dict) or info.get("state") != 0:
        raise RuntimeError("MEXC contract not active or missing")
    size = num(info.get("contractSize"))
    if size is None or size <= 0:
        raise RuntimeError("MEXC missing contractSize")
    raw = get(client, "https://contract.mexc.com/api/v1/contract/ticker",
              {"symbol": native}).get("data")
    if isinstance(raw, list):
        raw = next((r for r in raw if r.get("symbol") == native), None)
    if not isinstance(raw, dict):
        raise RuntimeError("MEXC ticker missing")
    price = num(raw.get("lastPrice"))
    oi_contracts = num(raw.get("holdVol"))
    if price is None or oi_contracts is None:
        raise RuntimeError("MEXC missing OI or price")
    # MEXC holdVol is contracts, contractSize base units per contract.
    oi_usd = oi_contracts * size * price
    spot = get(client, "https://api.mexc.com/api/v3/trades",
               {"symbol": base+"USDT", "limit": 500})
    if not isinstance(spot, list):
        raise RuntimeError("MEXC spot sample not available")
    trades = []
    for t in spot:
        px, qty = num(t.get("price")), num(t.get("qty"))
        if px is not None and qty is not None:
            trades.append(("sell" if t.get("isBuyerMaker") else "buy",
                           px * qty, int(t.get("time", 0))))
    result = spot_sample(trades)
    result.update({
        "oi_value": round(oi_usd, 3), "oi_unit": "USD_estimate_contract_size",
        "oi_contracts": oi_contracts, "contract_size": size,
        "price_usdt": price, "funding_rate": None,
    })
    return result


def dedupe_append(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                existing.append(json.loads(line))
    keys = {(x.get("hour_utc"), x.get("exchange"), x.get("coin")) for x in existing}
    written = 0
    for row in rows:
        key = (row["hour_utc"], row["exchange"], row["coin"])
        if key not in keys:
            existing.append(row)
            keys.add(key)
            written += 1
    existing.sort(key=lambda x: (x.get("hour_utc", ""), x.get("exchange", ""), x.get("coin", "")))
    temp = path.with_suffix(".tmp")
    temp.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in existing), encoding="utf-8")
    os.replace(temp, path)
    return written


def run():
    now = dt.datetime.now(dt.timezone.utc)
    hour = now.strftime("%Y-%m-%dT%H:00:00Z")
    month = now.strftime("%Y-%m")
    rows = []
    errors = []
    with httpx.Client(headers={"User-Agent": "PrePumpScanner-Public-Research/3.1"}) as client:
        for exchange in EXCHANGES:
            for coin in BASES:
                try:
                    data = collect_okx(client, coin) if exchange == "okx" else collect_mexc(client, coin)
                    rows.append({"hour_utc": hour, "collected_at_utc": now.isoformat(),
                                 "exchange": exchange, "coin": coin, **data})
                except Exception as err:
                    errors.append(f"{exchange} {coin}: {str(err)[:120]}")
                time.sleep(0.08)
    path = ROOT / f"{month}.jsonl"
    written = dedupe_append(path, rows)
    # Failure logs are emitted to the Actions job, not invented as zeros.
    print(f"hour={hour}; collected={len(rows)}; new_rows={written}; errors={len(errors)}; file={path}")
    for err in errors:
        print("WARN", err)
    if not rows:
        raise SystemExit("No public-market observations acquired; check hosting access.")


if __name__ == "__main__":
    run()
