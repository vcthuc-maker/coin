"""All-market MEXC Futures momentum radar (observation, not pump prediction).

Runs in GitHub Actions --once, or on a user's always-on machine with --loop.
GitHub's schedule is NOT real time. First observed 5m acceleration uses
actual ticker samples; missing/gapped history cannot create an early alert.
"""
from __future__ import annotations
import argparse
import json
import math
import os
from pathlib import Path
import time
from datetime import datetime, timezone

from mexc_fast import get_json
from mexc_velocity import parse_tickers

ROOT = Path(__file__).resolve().parent / "data" / "mexc_radar"
HISTORY = ROOT / "history.json"
EVENTS = ROOT / "events.json"
LATEST = ROOT / "latest.json"
MAX_SNAPSHOTS = 32
MAX_EVENTS = 1200
MIN_TURNOVER = 100_000
COOLDOWN = 45 * 60

def _atomic_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    temp.replace(path)

def _load_json(path, fallback):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return fallback

def _suitable(history, symbol, now, minutes, tolerance):
    """Choose a real sample around the requested lookback, not a synthetic price."""
    choices = []
    for row in history:
        age = now - int(row["ts"])
        if age <= 0 or abs(age - minutes * 60) > tolerance:
            continue
        sample = row["markets"].get(symbol)
        if sample and sample[0] > 0:
            choices.append((abs(age-minutes*60), sample, age))
    return min(choices, key=lambda v: v[0])[1:] if choices else (None, None)

def detect_radar(history, events, now):
    """Only signal if there is an observed prior price and a short observation gap.

    24h percentage is rolling exchange ticker change, not gain from local low.
    """
    if len(history) < 2:
        return [], []
    previous, latest = history[-2:]
    if not (0 < now - latest["ts"] < 180):
        return [], []
    gap = latest["ts"] - previous["ts"]
    # Late GitHub runs may skip crossing; never claim timing precision.
    if gap <= 0 or gap > 660:
        return [], []
    new_events = []
    warnings = []
    for symbol, (price, turnover, ch24) in latest["markets"].items():
        earlier = previous["markets"].get(symbol)
        if not earlier or turnover < MIN_TURNOVER or price <= 0:
            continue
        p_before, _, ch_before = earlier
        if p_before <= 0:
            continue
        delta = 100 * (price / p_before - 1)
        ref5, age5 = _suitable(history, symbol, latest["ts"], 5, 180)
        change5 = 100 * (price / ref5[0] - 1) if ref5 else None
        base = {
            "coin": symbol[:-5] + "/USDT", "symbol": symbol,
            "price": round(price, 12), "change24_pct": round(ch24, 2),
            "change_prev_pct": round(delta, 2), "change5_pct": round(change5, 2) if change5 is not None else None,
            "turnover24_usdt": int(turnover),
            "ts": int(latest["ts"]),
            "utc": datetime.fromtimestamp(int(latest["ts"]), timezone.utc).isoformat(),
        }
        signals = []
        # Early acceleration is only eligible when already-not-pumped (24h <10).
        # Volume acceleration is not inferred from 24h turnover; price-only research flag.
        if change5 is not None and 1.0 <= change5 <= 3.0 and -5 <= ch_before < 10 and ch24 < 12 and delta > 0:
            signals.append(("EARLY", "MỚI TĂNG 1–3% (5M) — THEO DÕI"))
        for threshold in (5, 10):
            if ch_before < threshold <= ch24 and delta > 0:
                if ch24 <= threshold + 3.5 and delta <= 5:
                    signals.append((f"M{threshold}", f"VỪA VƯỢT +{threshold}% (24H) — THEO DÕI"))
                else:
                    warnings.append({
                        **base, "status": f"VƯỢT +{threshold}% NHƯNG BÁO TRỄ — KHÔNG ĐUỔI"
                    })
        if not signals:
            continue
        for key, status in signals:
            if any(e["symbol"] == symbol and e["kind"] == key
                   and 0 <= now-int(e["ts"]) < COOLDOWN for e in events+new_events):
                continue
            new_events.append({**base, "kind": key, "status": status})
    return new_events, warnings

def once(*, now=None):
    now = int(time.time()) if now is None else int(now)
    markets = parse_tickers(get_json("/api/v1/contract/detail"),
                            get_json("/api/v1/contract/ticker"),
                            min_turnover=MIN_TURNOVER)
    if not markets:
        raise RuntimeError("No MEXC markets returned; keep previous snapshot")
    old = _load_json(HISTORY, {"snapshots":[]})
    snapshots = old.get("snapshots", []) if isinstance(old, dict) else []
    # Avoid duplicate snapshots created during the same second.
    snapshots = [s for s in snapshots
                 if 0 < now-int(s.get("ts", now)) <= 7200]
    snapshots.append({"ts":now, "markets":markets})
    snapshots = snapshots[-MAX_SNAPSHOTS:]
    events = _load_json(EVENTS, [])
    if not isinstance(events, list):
        events = []
    new, missed = detect_radar(snapshots, events, now)
    events = (events + new)[-MAX_EVENTS:]
    _atomic_json(HISTORY, {"snapshots":snapshots})
    _atomic_json(EVENTS, events)
    _atomic_json(LATEST, {
        "collected_at_utc":datetime.fromtimestamp(now, timezone.utc).isoformat(),
        "ts":now, "universe":len(markets), "snapshots":len(snapshots),
        "new":new[:70], "late_crossings":missed[:40],
        "recent": sorted([e for e in events if now-int(e["ts"]) <= 3600],
                         key=lambda e:e["ts"], reverse=True)[:100],
        "source":"MEXC Futures all-market ticker; REST snapshot observations",
        "warning":"Lịch GitHub Actions không bảo đảm 5 phút. Cảnh báo không phải khuyến nghị mua.",
    })
    # Optional push only for genuinely new, deduplicated observations.
    from mexc_threshold import notify_telegram
    telegram = [{
        "coin":e["coin"], "mốc": ("1–3" if e["kind"] == "EARLY" else e["kind"][1:]),
        "giá lần đầu":e["price"], "tăng 24H %":e["change24_pct"],
        "tăng từ snapshot trước %":e["change_prev_pct"],"lúc UTC":e["utc"]
    } for e in new]
    print(notify_telegram(telegram))
    print(f"radar markets={len(markets)} snapshots={len(snapshots)} new={len(new)} delayed={len(missed)}")
    return new

def main():
    parser = argparse.ArgumentParser(description="MEXC all-market radar. Does not place orders.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", help="one REST snapshot (for GitHub Actions)")
    mode.add_argument("--loop", action="store_true", help="run continuously on always-on host")
    parser.add_argument("--interval", type=int, default=30, help="seconds between REST polls, default 30")
    args = parser.parse_args()
    if not args.loop:
        once()
        return
    if args.interval < 20:
        parser.error("interval must be at least 20 seconds")
    print("MEXC continuous radar: running REST polling; Ctrl+C to stop")
    while True:
        begin = time.monotonic()
        try:
            once()
        except Exception as exc:
            print(f"Radar collection failed: {type(exc).__name__}: {str(exc)[:200]}", flush=True)
        time.sleep(max(0.0, args.interval-(time.monotonic()-begin)))

if __name__ == "__main__":
    main()
