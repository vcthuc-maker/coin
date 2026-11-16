"""V3.2 experimental pre-pump confirmation from archived snapshots.

This is NOT a probability, a full Spot CVD, or evidence of market manipulation.
Missing/stale values always produce non-confirmation. No score inflation.
"""
from __future__ import annotations

import pandas as pd

TECHNICAL_PHASES = {
    "NÉN LÂU — ƯU TIÊN 4H",
    "ĐANG TÍCH LŨY",
    "VỪA BREAKOUT — CÓ THỂ TIẾP DIỄN",
}
COLUMNS = [
    "coin", "xác nhận sơ bộ", "sàn hợp lệ", "sàn có OI + Spot",
    "OI 4H nhỏ nhất %", "Spot imbalance nhỏ nhất % (mẫu)",
    "nén tối đa (giờ)", "điểm kỹ thuật cao nhất",
    "lý do chưa xác nhận",
]


def confirmation_table(scan_frame, archived, now=None, *, oi_min=3.0, spot_min=10.0,
                       freshness_hours=2.5, sample_min_trades=50,
                       sample_min_minutes=0.25):
    """One row per coin, conservative concordance across >=2 *eligible* exchanges.

    Eligibility: technical accumulation/early breakout, matching fresh archived
    exchange pair, OI change measured over ~4 hours in the same unit, minimum
    positive sampled Spot taker imbalance. All checks are causal only at the
    snapshot timestamp; the current scan may be slightly later.
    """
    if scan_frame is None or scan_frame.empty:
        return pd.DataFrame(columns=COLUMNS)
    now = pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now)
    if now.tzinfo is None:
        now = now.tz_localize("UTC")
    flow_groups = {}
    if archived is not None and not archived.empty:
        data = archived.copy()
        data["time"] = pd.to_datetime(data["collected_at_utc"], utc=True, errors="coerce")
        for col in ("oi_value", "spot_sample_imbalance_pct",
                    "spot_sample_minutes", "spot_sample_count"):
            data[col] = pd.to_numeric(data[col], errors="coerce")
        data = data.dropna(subset=["time"]).sort_values("time")
        for (exchange, coin), group in data.groupby(["exchange", "coin"]):
            flow_groups[(exchange, coin)] = group

    out = []
    for coin, g in scan_frame.groupby("coin", sort=True):
        base = str(coin).removesuffix("/USDT")
        detail = []
        eligible = set()
        oi_pass = set()
        spot_pass = set()
        both_pass = set()
        oi_rates, spots = [], []
        for _, technical in g.iterrows():
            ex = technical["sàn"]
            phase = technical["trạng thái 4H"]
            if str(technical.get("rủi ro xu hướng", "")).startswith("DƯỚI EMA50"):
                detail.append(f"{ex}: EMA50 giảm, chưa xác nhận đảo chiều")
                continue
            if phase not in TECHNICAL_PHASES:
                detail.append(f"{ex}: chưa có setup kỹ thuật")
                continue
            eligible.add(ex)
            obs = flow_groups.get((ex, base))
            if obs is None or len(obs) == 0:
                detail.append(f"{ex}: thiếu lịch sử OI/Spot")
                continue
            latest = obs.iloc[-1]
            age = (now - latest["time"]).total_seconds() / 3600
            if not (0 <= age <= freshness_hours):
                detail.append(f"{ex}: dữ liệu cũ ({age:.1f}H)")
                continue
            # Find a 4h reference within 3-5 hours; never interpolate or cross units.
            delta = (latest["time"] - obs["time"]).dt.total_seconds() / 3600
            prior = obs.loc[(delta >= 3) & (delta <= 5) &
                            (obs["oi_unit"] == latest["oi_unit"]) &
                            (obs["oi_value"] > 0)].copy()
            change = None
            if not prior.empty and pd.notna(latest["oi_value"]) and latest["oi_value"] > 0:
                prior["distance_to_4h"] = abs(delta.loc[prior.index] - 4)
                ref = prior.sort_values("distance_to_4h").iloc[0]
                change = (float(latest["oi_value"]) / float(ref["oi_value"]) - 1) * 100
                if change >= oi_min:
                    oi_pass.add(ex)
                    oi_rates.append(change)
                else:
                    detail.append(f"{ex}: OI 4H {change:+.2f}% chưa đạt")
            else:
                detail.append(f"{ex}: thiếu cặp OI cách 4H")
            spot = latest["spot_sample_imbalance_pct"]
            trades = latest["spot_sample_count"]
            minutes = latest["spot_sample_minutes"]
            if (pd.notna(spot) and pd.notna(trades) and pd.notna(minutes) and
                    trades >= sample_min_trades and minutes >= sample_min_minutes and
                    spot >= spot_min):
                spot_pass.add(ex)
                spots.append(float(spot))
            else:
                detail.append(f"{ex}: Spot mẫu thiếu hoặc chưa đủ mua chủ động")
            if ex in oi_pass and ex in spot_pass:
                both_pass.add(ex)

        # Only cross-exchange consensus; same coin observed on multiple exchanges
        # but inconsistent data must not be treated as independent confirmations.
        confirmed = len(both_pass) >= 2
        if len(eligible) < 2:
            detail.append("chưa có setup phù hợp ở 2 sàn")
        elif len(both_pass) < 2:
            detail.append("chưa đủ đồng thuận OI và Spot mẫu trên 2 sàn")
        out.append({
            "coin": coin,
            "xác nhận sơ bộ": "ĐỒNG THUẬN SƠ BỘ — CẦN KIỂM CHỨNG" if confirmed
                              else "CHƯA XÁC NHẬN",
            "sàn hợp lệ": ", ".join(sorted(eligible)) if eligible else "—",
            "sàn có OI + Spot": ", ".join(sorted(both_pass)) if both_pass else "—",
            "OI 4H nhỏ nhất %": round(min(oi_rates), 2) if oi_rates else None,
            "Spot imbalance nhỏ nhất % (mẫu)": round(min(spots), 2) if spots else None,
            "nén tối đa (giờ)": int(g["thời gian nén liên tục (giờ)"].max()),
            "điểm kỹ thuật cao nhất": int(g["điểm 4H /100"].max()),
            "lý do chưa xác nhận": "; ".join(dict.fromkeys(detail)) if not confirmed else
                                  "Hai sàn có OI tăng và mua chủ động trong mẫu ngắn; không phải CVD",
        })
    return (pd.DataFrame(out, columns=COLUMNS)
            .assign(_rank=lambda df: df["xác nhận sơ bộ"].str.startswith("ĐỒNG THUẬN").astype(int))
            .sort_values(["_rank", "điểm kỹ thuật cao nhất"], ascending=[False, False])
            .drop(columns=["_rank"]).reset_index(drop=True))
