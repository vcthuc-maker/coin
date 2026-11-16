import unittest
import numpy as np
import pandas as pd

from validation_v3 import (
    collect_events, resolve_outcome, temporal_split, evaluate, summarize,
    report_rows, HORIZONS,
)


def candles(count=280):
    idx = np.arange(count)
    close = 100 + 0.01 * idx
    return pd.DataFrame({
        "t": (idx + 2_000_000) * 3_600_000,
        "open": close, "high": close * 1.002,
        "low": close * .998, "close": close,
        "turnover": np.full(count, 100_000.),
    })


def dummy_signal(exchange, base, native, price, turnover, candles):
    return {"trạng thái 4H": "ĐANG TÍCH LŨY", "điểm 4H /100": 55}


class ValidationTests(unittest.TestCase):
    def test_no_future_candles_and_independent_entries(self):
        df = candles()
        seen = []
        def callback(ex, base, native, price, turnover, candles):
            seen.append(len(candles))
            return dummy_signal(ex, base, native, price, turnover, candles)
        events = collect_events(df, callback, "okx", "BTC/USDT",
                                "BTC-USDT-SWAP", 1e7)
        self.assertTrue(events)
        self.assertEqual(seen[0], 105)
        self.assertEqual(seen[1], 129)
        stamps = [e["giờ vào UTC"] for e in events]
        self.assertTrue(all(y-x >= 24*3600000 for x, y in zip(stamps, stamps[1:])))

    def test_stop_first_and_mfe_mae(self):
        ev = {"giá vào": 100.0,
              "future": np.array([[106., 97., 102.]] * 24)}
        result = resolve_outcome(ev, 4, 4., 2., .25)
        self.assertEqual(result["kết quả"], "STOP")
        self.assertAlmostEqual(result["lãi/lỗ ròng %"], -2.25)
        self.assertAlmostEqual(result["MFE %"], 6.)
        self.assertAlmostEqual(result["MAE %"], -3.)

    def test_temporal_split_gap(self):
        events = collect_events(candles(400), dummy_signal, "okx",
                                "BTC/USDT", "BTC-USDT-SWAP", 1e7)
        dev, hold, cutoff = temporal_split(events, .30, 24)
        self.assertTrue(dev and hold)
        self.assertTrue(all(a["giờ vào UTC"] + 24*3600000 <
                            hold[0]["giờ vào UTC"] for a in dev))
        self.assertGreater(len(hold), 0)

    def test_baseline_and_multiple_horizons(self):
        events = collect_events(candles(280), dummy_signal, "okx",
                                "BTC/USDT", "BTC-USDT-SWAP", 1e7)
        table = report_rows(events, "Kiểm tra")
        self.assertEqual(len(table), 2 * sum(len(v) for v in HORIZONS.values()))
        self.assertEqual(set(table["loại"]), {"Scanner", "Baseline định kỳ"})
        self.assertGreater(len(evaluate(events, 4, 1.)), 0)

    def test_empty_metrics(self):
        result = summarize(pd.DataFrame())
        self.assertEqual(result["số tín hiệu"], 0)
        self.assertIsNone(result["đạt mục tiêu %"])


if __name__ == "__main__":
    unittest.main()
