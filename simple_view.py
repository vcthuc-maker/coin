"""Compact research-only watchlist: three user-facing states.

The 3rd state requires archived, fresh two-exchange flow agreement.
No probability of pump and no automatic execution.
"""
import pandas as pd

from confirmation import confirmation_table

DOWN = "1. NÉN TRONG XU HƯỚNG GIẢM"
RECOVER = "2. TÍCH LŨY — THEO DÕI ĐẢO CHIỀU"
BREAK = "3. BREAKOUT — DÒNG TIỀN XÁC NHẬN"
TECH_PHASES = {"NÉN LÂU — ƯU TIÊN 4H", "ĐANG TÍCH LŨY",
               "VỪA BREAKOUT — CÓ THỂ TIẾP DIỄN", "BREAKOUT CẦN XÁC NHẬN"}
COLUMNS = ["coin", "trạng thái", "điểm kỹ thuật cao nhất /100",
           "nén lâu nhất (giờ)", "sàn", "xác nhận OI + Spot",
           "ghi chú"]


def three_state_view(frame, archive, now=None, min_score=0, min_compression=0):
    if frame is None or frame.empty:
        return pd.DataFrame(columns=COLUMNS)
    confirmed = confirmation_table(frame, archive, now=now)
    is_confirmed = dict(zip(confirmed["coin"], confirmed["xác nhận sơ bộ"].str.startswith("ĐỒNG THUẬN")))
    confirms = dict(zip(confirmed["coin"], confirmed["sàn có OI + Spot"]))
    rows = []
    for coin, group in frame.groupby("coin"):
        phases = set(group["trạng thái 4H"])
        down = group["rủi ro xu hướng"].fillna("").str.startswith("DƯỚI EMA50").any()
        breakout = "VỪA BREAKOUT — CÓ THỂ TIẾP DIỄN" in phases
        eligible = bool(phases.intersection(TECH_PHASES))
        score = int(group["điểm 4H /100"].max())
        hours = int(group["thời gian nén liên tục (giờ)"].max())
        if score < min_score:
            continue

        # Strict priority: never label a downtrend as confirmed breakout.
        if down and eligible and hours >= min_compression:
            label = DOWN
            note = "EMA50 đang giảm; nén giá chưa chứng minh lực mua tích lũy"
        elif breakout and is_confirmed.get(coin, False):
            label = BREAK
            note = "Breakout kỹ thuật và OI/Spot mẫu đồng thuận tối thiểu 2 sàn"
        elif not down and eligible and hours >= min_compression:
            label = RECOVER
            note = "Theo dõi; thiếu xác nhận đầy đủ hoặc chưa breakout"
        else:
            continue
        rows.append({
            "coin": coin, "trạng thái": label,
            "điểm kỹ thuật cao nhất /100": score,
            "nén lâu nhất (giờ)": hours,
            "sàn": ", ".join(sorted(group["sàn"].unique())),
            "xác nhận OI + Spot": confirms.get(coin, "—") if label == BREAK else "Chưa",
            "ghi chú": note,
        })
    if not rows:
        return pd.DataFrame(columns=COLUMNS)
    result = pd.DataFrame(rows, columns=COLUMNS)
    order = {BREAK: 0, RECOVER: 1, DOWN: 2}
    result["_priority"] = result["trạng thái"].map(order)
    return (result.sort_values(["_priority", "điểm kỹ thuật cao nhất /100"],
                               ascending=[True, False])
                  .drop(columns="_priority").reset_index(drop=True))
