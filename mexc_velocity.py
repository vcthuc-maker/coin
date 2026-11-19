"""MEXC market-wide price-velocity watch. No trading or predictive probability.

One all-market ticker request per collection; *observed* 5/15/60-minute
changes from archived ticker snapshots. Rolling snapshots are replaceable;
no synthetic historical values or extrapolated values.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
import time

from mexc_fast import EXCLUDE, get_json

ROOT = Path(__file__).resolve().parent / "data" / "mexc_velocity"
HISTORY = ROOT / "history.json"
LATEST = ROOT / "latest.json"
EARLY_LATEST = ROOT / "latest_early.json"
QUALITY_LATEST = ROOT / "latest_quality.json"
MAX_SNAPSHOTS = 28
MAX_LAG_SECONDS = 11 * 60


def _num(obj, key):
    try:
        n = float(obj.get(key))
        return n if 0 < n < float("inf") else None
    except (ValueError, TypeError):
        return None


def parse_tickers(metadata, tickers, min_turnover=100_000):
    allowed = {
        x.get("symbol") for x in metadata if
        str(x.get("state")) == "0" and x.get("quoteCoin") == "USDT"
        and str(x.get("futureType", 1)) == "1"
    }
    rows = {}
    for item in tickers if isinstance(tickers, list) else [tickers]:
        symbol = item.get("symbol", "")
        base = symbol[:-5].upper() if symbol.endswith("_USDT") else ""
        if not base or base in EXCLUDE or symbol not in allowed:
            continue
        px = _num(item, "lastPrice")
        turnover = _num(item, "amount24")
        if px is None or turnover is None or turnover < min_turnover:
            continue
        try:
            ch24 = float(item.get("riseFallRate", 0)) * 100
        except (ValueError, TypeError):
            ch24 = 0.
        if not -100 <= ch24 <= 100000:
            continue
        rows[symbol] = [round(px, 12), round(turnover), round(ch24, 3)]
    return rows


def _reference(history, symbol, now, hours, tolerance):
    candidates = []
    desired = hours * 3600
    for item in history:
        age = now - int(item["ts"])
        if age <= 0 or abs(age - desired) > tolerance:
            continue
        sample = item.get("markets", {}).get(symbol)
        if sample is not None and sample[0] > 0:
            candidates.append((abs(age - desired), sample[0]))
    return min(candidates, default=(None, None))[1]


def compute(history):
    if not history:
        return []
    recent = history[-1]
    now = int(recent["ts"])
    results = []
    for symbol, values in recent["markets"].items():
        px, turnover, ch24 = values
        r5 = _reference(history, symbol, now, 5 / 60, 3 * 60)
        r15 = _reference(history, symbol, now, .25, 4 * 60)
        r60 = _reference(history, symbol, now, 1, 8 * 60)
        change5 = round((px / r5 - 1) * 100, 2) if r5 else None
        change15 = round((px / r15 - 1) * 100, 2) if r15 else None
        change60 = round((px / r60 - 1) * 100, 2) if r60 else None
        if ch24 >= 25 or (change15 is not None and change15 > 7) or (
                change60 is not None and change60 >= 12):
            status = "ĐÃ TĂNG NÓNG — KHÔNG MUA ĐUỔI"
            priority = 2
        elif change5 is not None and change15 is not None and (
                change5 >= .35 and .7 <= change15 <= 4
                and (change60 is None or change60 <= 8)
                and ch24 < 18):
            status = "MỚI TĂNG TỐC — THEO DÕI"
            priority = 0
        elif change15 is not None and change15 >= .4 and ch24 < 18:
            status = "ĐANG NHÍCH LÊN — CHỜ XÁC NHẬN"
            priority = 1
        else:
            continue
        results.append({
            "coin": symbol[:-5] + "/USDT", "trạng thái": status,
            "giá": px, "5m %": change5, "15m %": change15,
            "1H %": change60, "24H %": ch24,
            "turnover 24H USDT": turnover, "_rank": priority
        })
    return sorted(results, key=lambda a: (a["_rank"], -(a["15m %"] or -999)))


def apply_snapshot(history, ts, markets):
    """Idempotent 5-minute bucket updates, robust to missed scheduler intervals."""
    bucket = int(ts) // 300 * 300
    previous = [row for row in history
                if int(row["ts"]) < bucket and bucket - int(row["ts"]) <= 2*3600 + 300]
    previous.append({"ts": bucket, "markets": markets})
    return previous[-MAX_SNAPSHOTS:]


def run():
    now = int(time.time())
    metadata = get_json("/api/v1/contract/detail")
    tickers = get_json("/api/v1/contract/ticker")
    markets = parse_tickers(metadata, tickers)
    if not markets:
        raise RuntimeError("No valid MEXC futures tickers; preserve previous data.")
    prior = []
    if HISTORY.exists():
        prior = json.loads(HISTORY.read_text(encoding="utf-8")).get("snapshots", [])
    history = apply_snapshot(prior, now, markets)
    alerts = compute(history)
    # Short-horizon detector only checks a bounded, diverse subset of markets.
    # Keep its failures separate: market-wide snapshot must not be lost.
    early_rows, early_errors, early_count = [], [], 0
    try:
        from mexc_early import scan_early
        early_rows, early_errors, early_count = scan_early(
            markets, history, limit=24, now=now)
    except Exception as exc:
        early_errors.append("1m scan: " + str(exc)[:180])
    quality_rows, quality_errors, quality_checked = [], [], 0
    try:
        from mexc_quality import scan_quality
        quality_rows, quality_errors, quality_checked = scan_quality(
            markets, history, now, limit=30)
    except Exception as exc:
        quality_errors.append("5m preparation scan: " + str(exc)[:180])
    quality_payload = {
        "collected_at_utc": datetime.fromtimestamp(now, timezone.utc).isoformat(),
        "universe_size": len(markets),
        "scanned_5m": quality_checked,
        "rows": quality_rows,
        "errors": quality_errors[:30],
        "note": "Watchlist nén trước breakout + breakout giữ nền; không phải xác suất pump."
    }
    try:
        from mexc_outcomes import read_events, update_events, write_events, simple_summary
        event_history = update_events(read_events(), quality_rows, now, markets)
        write_events(event_history)
        quality_payload["evaluation"] = simple_summary(event_history)
        quality_payload["saved_signals"] = len(event_history)
    except Exception as exc:
        quality_payload["evaluation_error"] = str(exc)[:160]
    payload_early = {
        "collected_at_utc": datetime.fromtimestamp(now, timezone.utc).isoformat(),
        "universe_size": len(markets),
        "scanned_1m": early_count,
        "rows": early_rows[:60],
        "errors": early_errors[:25],
        "notice": "Đọc nến 1 phút đã đóng; chạy lịch 5 phút có thể bỏ qua đợt pump xảy ra giữa các lần quét."
    }
    payload = {
        "collected_at_utc": datetime.fromtimestamp(now, timezone.utc).isoformat(),
        "universe_size": len(markets),
        "history_intervals": len(history),
        "rows": [{k: v for k, v in x.items() if k != "_rank"} for x in alerts[:100]],
        "coverage_notice": "5m/15m/1H values are snapshot-to-snapshot changes, not candle high/low."
    }
    ROOT.mkdir(parents=True, exist_ok=True)
    HISTORY.write_text(json.dumps({"snapshots": history}, ensure_ascii=False, separators=(",", ":")),
                       encoding="utf-8")
    LATEST.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    EARLY_LATEST.write_text(json.dumps(payload_early, ensure_ascii=False, indent=2), encoding="utf-8")
    QUALITY_LATEST.write_text(json.dumps(quality_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"mexc_velocity: markets={len(markets)} snapshots={len(history)} alerts={len(alerts)}")
    print(f"early={sum(x['_rank']==0 for x in alerts)} late={sum(x['_rank']==2 for x in alerts)}")
    print(f"1m_scanned={early_count} 1m_alerts={len(early_rows)} 1m_errors={len(early_errors)}")


def read_latest():
    if not LATEST.exists():
        return None
    try:
        data = json.loads(LATEST.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (ValueError, OSError):
        return None


if __name__ == "__main__":
    run()


def read_early_latest():
    if not EARLY_LATEST.exists():
        return None
    try:
        data = json.loads(EARLY_LATEST.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (ValueError, OSError):
        return None

def read_quality_latest():
    if not QUALITY_LATEST.exists():
        return None
    try:
        obj = json.loads(QUALITY_LATEST.read_text(encoding="utf-8"))
        return obj if isinstance(obj, dict) else None
    except (OSError, ValueError):
        return None
