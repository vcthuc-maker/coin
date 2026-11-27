"""Observed MEXC Futures 24h gain threshold crossings (5% and 10%).

Not a forecast or a trade signal. A threshold event is emitted only when
consecutive, recent all-market ticker snapshots prove the crossing. Never
backfill an event from a first observation already above the threshold.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path

THRESHOLDS = (5, 10)
EVENTS_PATH = Path(__file__).resolve().parent / "data" / "mexc_velocity" / "threshold_events.json"
COOLDOWN_SECONDS = 24 * 3600
RECENT_SECONDS = 60 * 60
MAX_EVENTS = 1600


def detect_crossings(history, now, *, thresholds=THRESHOLDS):
    """Compare only the last two consecutive snapshots, time must be <=10min apart.

    Percent changes refer to MEXC's moving 24H ticker figure, not returns
    since the trader's first signal or a known past local low.
    """
    if len(history) < 2:
        return []
    before, current = history[-2:]
    gap = int(current["ts"]) - int(before["ts"])
    if gap < 240 or gap > 660 or now - int(current["ts"]) > 330:
        return []
    found = []
    for symbol, values in current["markets"].items():
        prev = before["markets"].get(symbol)
        if prev is None:
            continue
        price, turnover, pct = values
        old_price, _, old_pct = prev
        if not (price > 0 and old_price > 0 and turnover >= 100_000):
            continue
        change5 = (price / old_price - 1) * 100
        for threshold in thresholds:
            # Do not call +30% "newly crossed 5%" due to a gap.
            max_band = 8.5 if threshold == 5 else 13.5
            if not (old_pct < threshold <= pct <= max_band):
                continue
            # Exclude snapshot declines and candle-sized wick reversals.
            # This cannot guarantee the absence of manipulation or a 48h rally.
            if change5 < 0.15 or change5 > 5:
                continue
            found.append({
                "coin": symbol[:-5] + "/USDT",
                "symbol": symbol,
                "mốc": threshold,
                "giá lần đầu": round(float(price), 12),
                "tăng 24H %": round(float(pct), 2),
                "tăng từ snapshot trước %": round(change5, 2),
                "turnover 24H USDT": round(float(turnover)),
                "lúc UTC": datetime.fromtimestamp(int(now), timezone.utc).isoformat(),
                "ts": int(now),
                "trạng thái": "VỪA VƯỢT MỐC — CẦN KIỂM TRA GIỮ GIÁ",
            })
    return sorted(found, key=lambda x: (x["mốc"], x["tăng từ snapshot trước %"]))


def merge_events(existing, fresh, now, *, cooldown=COOLDOWN_SECONDS):
    """Deduplicate each coin/threshold for 24h. Persist new events only once."""
    events = list(existing)
    added = []
    for event in fresh:
        if any(item.get("symbol") == event["symbol"]
               and int(item.get("mốc", 0)) == event["mốc"]
               and 0 <= int(now) - int(item["ts"]) < cooldown for item in events):
            continue
        events.append(event)
        added.append(event)
    return events[-MAX_EVENTS:], added


def read_events(path=EVENTS_PATH):
    if not path.exists():
        return []
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
        return result if isinstance(result, list) else []
    except (OSError, ValueError):
        return []


def write_events(events, path=EVENTS_PATH):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(events[-MAX_EVENTS:], ensure_ascii=False, indent=2),
                         encoding="utf-8")
    temporary.replace(path)


def recent_events(events, now, *, lookback=RECENT_SECONDS):
    return sorted([e for e in events if 0 <= now-int(e["ts"]) <= lookback],
                  key=lambda e: int(e["ts"]), reverse=True)

def notify_telegram(new_events):
    """Optional notification; requires TWO repository GitHub Actions secrets.

    Only first crossings pass here. Secrets never appear in output or files.
    Returns a non-secret status for workflow logs.
    """
    if not new_events:
        return "No new milestones"
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        return "Telegram not configured; website events still saved"
    import httpx
    sent = 0
    for e in new_events:
        message = (
            f"🔔 MEXC Futures {e['coin']} vừa được ghi nhận vượt "
            f"+{e['mốc']}% trong 24H\\n"
            f"Giá lúc quét: {e['giá lần đầu']} USDT\\n"
            f"Tăng 24H: {e['tăng 24H %']}% | "
            f"Tăng từ snapshot trước: {e['tăng từ snapshot trước %']}%\\n"
            f"UTC: {e['lúc UTC']}\\n"
            "Chỉ là mốc quan sát, KHÔNG phải lệnh mua hay dự báo tăng tiếp."
        )
        try:
            resp = httpx.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                data={"chat_id": chat_id, "text": message},
                timeout=8,
            )
            resp.raise_for_status()
            if not resp.json().get("ok", False):
                raise RuntimeError("Telegram returned not ok")
            sent += 1
        except Exception as exc:
            # Never include request URL in exception: it embeds the bot token.
            return f"Telegram delivery not confirmed ({type(exc).__name__}); sent={sent}"
    return f"Telegram notifications delivered: {sent}"
