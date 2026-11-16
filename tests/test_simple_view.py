import unittest
import pandas as pd
from simple_view import three_state_view, DOWN, RECOVER, BREAK


def scan(phases, risks=None):
    risks = risks or ["", ""]
    return pd.DataFrame([
        {"coin": "DOGE/USDT", "sàn": ex, "trạng thái 4H": phases[i],
         "điểm 4H /100": 80, "thời gian nén liên tục (giờ)": 12,
         "rủi ro xu hướng": risks[i]}
        for i, ex in enumerate(("okx", "mexc"))
    ])


class SimpleViewTests(unittest.TestCase):
    def test_downtrend_takes_priority(self):
        risk = "DƯỚI EMA50, EMA50 ĐANG GIẢM"
        frame = scan(["ĐANG TÍCH LŨY", "ĐANG TÍCH LŨY"], [risk, ""])
        out = three_state_view(frame, pd.DataFrame(), min_score=50)
        self.assertEqual(out.iloc[0]["trạng thái"], DOWN)

    def test_technical_accumulation_is_only_watch(self):
        frame = scan(["ĐANG TÍCH LŨY", "ĐANG TÍCH LŨY"])
        out = three_state_view(frame, pd.DataFrame(), min_score=50, min_compression=6)
        self.assertEqual(out.iloc[0]["trạng thái"], RECOVER)
        self.assertEqual(out.iloc[0]["xác nhận OI + Spot"], "Chưa")

    def test_breakout_without_flow_not_confirmed(self):
        frame = scan(["VỪA BREAKOUT — CÓ THỂ TIẾP DIỄN", "ĐANG TÍCH LŨY"])
        out = three_state_view(frame, pd.DataFrame(), min_score=50)
        self.assertEqual(out.iloc[0]["trạng thái"], RECOVER)

    def test_score_filter(self):
        out = three_state_view(scan(["ĐANG TÍCH LŨY"]*2),
                               pd.DataFrame(), min_score=85)
        self.assertTrue(out.empty)


if __name__ == "__main__":
    unittest.main()
