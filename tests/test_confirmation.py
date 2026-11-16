import unittest
import pandas as pd

from confirmation import confirmation_table


def technical(sites=("okx", "mexc")):
    return pd.DataFrame([
        {"coin": "SOL/USDT", "sàn": ex, "trạng thái 4H": "ĐANG TÍCH LŨY",
         "thời gian nén liên tục (giờ)": 15, "điểm 4H /100": 70}
        for ex in sites
    ])


def flow(now, missing=None, weak=None):
    rows = []
    for ex in ("okx", "mexc"):
        if ex == missing:
            continue
        for hours_ago, oi, spot in [(4, 100., 12.), (0, 105., 20.)]:
            rows.append({
                "exchange": ex, "coin": "SOL", "oi_unit": "USD",
                "collected_at_utc": (now - pd.Timedelta(hours=hours_ago)).isoformat(),
                "oi_value": oi if ex != weak else (102. if hours_ago == 0 else 100.),
                "spot_sample_imbalance_pct": spot,
                "spot_sample_count": 100, "spot_sample_minutes": 2.,
            })
    return pd.DataFrame(rows)


class ConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.now = pd.Timestamp("2026-11-16T10:00:00Z")

    def test_two_exchanges_qualified(self):
        result = confirmation_table(technical(), flow(self.now), now=self.now)
        self.assertIn("ĐỒNG THUẬN", result.iloc[0]["xác nhận sơ bộ"])
        self.assertEqual(result.iloc[0]["sàn có OI + Spot"], "mexc, okx")

    def test_only_one_exchange_never_confirmed(self):
        r = confirmation_table(technical(("okx",)), flow(self.now), now=self.now)
        self.assertEqual(r.iloc[0]["xác nhận sơ bộ"], "CHƯA XÁC NHẬN")

    def test_one_exchange_fails_oi_gate(self):
        r = confirmation_table(technical(), flow(self.now, weak="okx"), now=self.now)
        self.assertEqual(r.iloc[0]["xác nhận sơ bộ"], "CHƯA XÁC NHẬN")

    def test_one_exchange_missing(self):
        r = confirmation_table(technical(), flow(self.now, missing="mexc"), now=self.now)
        self.assertEqual(r.iloc[0]["xác nhận sơ bộ"], "CHƯA XÁC NHẬN")

    def test_stale_data_never_confirmed(self):
        old = flow(self.now - pd.Timedelta(hours=12))
        r = confirmation_table(technical(), old, now=self.now)
        self.assertEqual(r.iloc[0]["xác nhận sơ bộ"], "CHƯA XÁC NHẬN")

    def test_downtrend_warning_blocks_confirmation(self):
        tech = technical()
        tech["rủi ro xu hướng"] = [
            "DƯỚI EMA50, EMA50 ĐANG GIẢM — CHƯA XÁC NHẬN ĐẢO CHIỀU",
            "KHÔNG CÓ CẢNH BÁO GIẢM THEO EMA50",
        ]
        r = confirmation_table(tech, flow(self.now), now=self.now)
        self.assertEqual(r.iloc[0]["xác nhận sơ bộ"], "CHƯA XÁC NHẬN")
        self.assertIn("EMA50 giảm", r.iloc[0]["lý do chưa xác nhận"])

    def test_missing_archive_never_confirmed(self):
        r = confirmation_table(technical(), pd.DataFrame(), now=self.now)
        self.assertEqual(r.iloc[0]["xác nhận sơ bộ"], "CHƯA XÁC NHẬN")


if __name__ == "__main__":
    unittest.main()
