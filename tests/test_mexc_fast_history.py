import unittest
from unittest.mock import patch
import numpy as np
import pandas as pd

from mexc_fast import classify, apply_fast_history_guard, scan_fast


def hours(prices):
    prices = np.asarray(prices, dtype=float)
    return pd.DataFrame({
        "t": 1_700_000_000 + np.arange(len(prices)) * 3600,
        "high": prices * 1.003,
        "low": prices * .997,
        "close": prices,
    })


def fast_row():
    return {
        "coin": "ELSA/USDT", "trạng thái": "TĂNG TỐC SỚM — THEO DÕI",
        "điểm hoạt động /100": 77, "giá (USDT)": 1.01,
        "5m %": .2, "15m %": 1.7, "1h %": 2.0, "24h %": 4.0,
        "RVOL 15m": 3.1, "turnover 15m USDT": 40000,
        "vượt đỉnh gần đây %": .4,
        "nến cuối UTC": "2026-11-23 02:00",
    }


class HistoricalFilterTests(unittest.TestCase):
    def test_flat_history_preserves_early_status_and_original_score(self):
        row = apply_fast_history_guard(fast_row(), hours([1.0] * 55))
        self.assertEqual(row["trạng thái"], "MỚI TĂNG TỐC — THEO DÕI")
        self.assertEqual(row["điểm hoạt động /100"], 77)

    def test_two_day_rally_prevents_fresh_signal(self):
        row = apply_fast_history_guard(fast_row(), hours(np.linspace(.80, 1.0, 55)))
        self.assertEqual(row["trạng thái"], "ĐÃ TĂNG XA 24–48H — TRÁNH MUA ĐUỔI")
        self.assertGreater(row["tăng từ đáy 48H %"], 15)

    def test_missing_hourly_data_must_not_claim_early(self):
        row = apply_fast_history_guard(fast_row(), pd.DataFrame())
        self.assertEqual(row["trạng thái"], "CHƯA ĐỦ LỊCH SỬ 48H — KHÔNG XÁC NHẬN")
        self.assertIsNone(row["mức tăng 48H %"])

    def test_gap_in_hourly_data_fails_closed(self):
        h = hours([1.0] * 55)
        h.loc[35, "t"] += 30
        row = apply_fast_history_guard(fast_row(), h)
        self.assertIn("CHƯA ĐỦ LỊCH SỬ", row["trạng thái"])

    def test_existing_five_minute_classifier_not_retuned(self):
        prices = np.full(60, 1.0)
        prices[-13:] = np.linspace(1.005, 1.035, 13)
        vol = np.full(60, 10000.)
        vol[-3:] = 40000.
        frame = pd.DataFrame({
            "t": 1_700_000_000 + np.arange(60) * 300,
            "open": prices, "high": prices * 1.002,
            "low": prices * .998, "close": prices, "amount": vol,
        })
        original = classify({"coin": "ELSA/USDT", "change24": 3.0}, frame)
        self.assertEqual(original["trạng thái"], "TĂNG TỐC SỚM — THEO DÕI")
        after = apply_fast_history_guard(original, hours([1.] * 55))
        self.assertEqual(original["điểm hoạt động /100"], after["điểm hoạt động /100"])

    @patch("mexc_fast.universe")
    @patch("mexc_fast.closed_klines")
    @patch("mexc_fast.closed_hourly")
    def test_scan_is_still_same_single_table(self, mock_hourly, mock_five, mock_universe):
        mock_universe.return_value = [{"native":"ELSA_USDT","coin":"ELSA/USDT",
                                       "change24":3.0,"turnover24":1000000}]
        prices = np.full(60, 1.0)
        prices[-13:] = np.linspace(1.005, 1.035, 13)
        vol = np.full(60, 10000.)
        vol[-3:] = 40000.
        mock_five.return_value = pd.DataFrame({
            "t": 1_700_000_000 + np.arange(60)*300,
            "open": prices, "high": prices*1.002,
            "low": prices*.998, "close": prices, "amount": vol
        })
        mock_hourly.return_value = hours([1.]*55)
        df, errors, checked = scan_fast()
        self.assertEqual(checked, 1)
        self.assertEqual(len(errors), 0)
        self.assertEqual(len(df), 1)
        self.assertIn("tăng từ đáy 48H %", df.columns)


if __name__ == "__main__":
    unittest.main()
