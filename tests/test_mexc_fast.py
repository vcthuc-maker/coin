import unittest
import numpy as np
import pandas as pd
from mexc_fast import classify


def candles(prices, amounts):
    n = len(prices)
    return pd.DataFrame({
        "t": np.arange(n) * 300 + 1_700_000_000,
        "open": prices, "high": np.array(prices) * 1.002,
        "low": np.array(prices) * .998,
        "close": prices, "amount": amounts,
    })


class FastMoverTests(unittest.TestCase):
    def test_early_momentum_discovered_without_24h_pump(self):
        prices = np.full(60, 1.0)
        prices[-13:] = np.linspace(1.005, 1.035, 13)
        amounts = np.full(60, 10000.)
        amounts[-3:] = 40000.
        result = classify({"coin": "TEST/USDT", "change24": 3.0},
                          candles(prices, amounts))
        self.assertIsNotNone(result)
        self.assertEqual(result["trạng thái"], "TĂNG TỐC SỚM — THEO DÕI")

    def test_24h_chase_warning_has_priority(self):
        prices = np.full(60, 1.)
        prices[-13:] = np.linspace(1.01, 1.03, 13)
        amounts = np.full(60, 20000.)
        amounts[-3:] = 60000.
        result = classify({"coin": "TEST/USDT", "change24": 45.},
                          candles(prices, amounts))
        self.assertIsNotNone(result)
        self.assertEqual(result["trạng thái"], "ĐÃ PUMP — TRÁNH MUA ĐUỔI")
        self.assertLessEqual(result["điểm hoạt động /100"], 39)

    def test_no_activity_is_not_false_early_alert(self):
        prices = np.full(60, 1.)
        amounts = np.full(60, 1000.)
        self.assertIsNone(classify({"coin": "TEST/USDT", "change24": 0.},
                                   candles(prices, amounts)))

    def test_insufficient_candles_is_no_signal(self):
        prices = np.full(15, 1.)
        amounts = np.full(15, 1000.)
        self.assertIsNone(classify({"coin": "TEST/USDT", "change24": 0.},
                                   candles(prices, amounts)))


if __name__ == "__main__":
    unittest.main()
