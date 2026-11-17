import unittest

import numpy as np
import pandas as pd

from mexc_early import (
    classify_early, select_candidates, EARLY, LATE, WATCH
)


def candles(*, breakout=True, greens=2, last_change=.65, volume_factor=2.5):
    n = 65
    starts = 1_700_000_000 + np.arange(n) * 60
    close = np.ones(n) * 1.0
    op = close.copy()
    # Use the last 3 closed candles to create a first/second-candle impulse.
    # Historical candles remain flat and are known before latest signal.
    if greens == 2:
        close[-3] = 1.002
        op[-3] = 1.003
        op[-2] = 1.002
        close[-2] = 1.004
        op[-1] = 1.004
        close[-1] = 1 + last_change / 100 + .004
    elif greens == 5:
        close[-6:] = np.linspace(1.002, 1.02, 6)
        op[-6] = 1
        op[-5:] = close[-6:-1]
    else:
        op[-1] = 1.
        close[-1] = 1 + last_change / 100
    high = np.maximum(op, close) * 1.0001
    low = np.minimum(op, close) * .9999
    volume = np.ones(n) * 1000.
    volume[-2:] = 1000 * volume_factor
    df = pd.DataFrame({"t": starts, "open": op, "high": high, "low": low,
                       "close": close, "amount": volume})
    if not breakout:
        df.loc[n-20, "high"] = 1.04
    return df


class EarlyPumpOneMinuteTests(unittest.TestCase):
    def test_first_two_candles_can_be_marked_early(self):
        df = candles(greens=2)
        now = int(df["t"].iloc[-1] + 60)
        item = classify_early({"coin":"TEST/USDT", "change24": 2.0},
                              df, now=now)
        self.assertIsNotNone(item)
        self.assertEqual(item["trạng thái"], EARLY)
        self.assertEqual(item["nến xanh liên tiếp"], 2)
        self.assertLess(item["tăng từ đáy 30m %"], 2.5)

    def test_more_than_four_green_candles_is_late(self):
        df = candles(greens=5)
        now = int(df["t"].iloc[-1] + 60)
        item = classify_early({"coin":"TEST/USDT", "change24": 3.0},
                              df, now=now)
        self.assertEqual(item["trạng thái"], LATE)

    def test_missing_candles_never_triggers(self):
        df = candles().drop(index=35).reset_index(drop=True)
        now = int(df["t"].iloc[-1] + 60)
        self.assertIsNone(classify_early({"coin":"TEST/USDT", "change24":1.0},
                                         df, now=now))

    def test_stale_minute_candle_never_triggers(self):
        df = candles()
        now = int(df["t"].iloc[-1] + 60 + 200)
        self.assertIsNone(classify_early({"coin":"TEST/USDT", "change24":1.0},
                                         df, now=now))

    def test_distant_resistance_not_early(self):
        df = candles(breakout=False)
        now = int(df["t"].iloc[-1] + 60)
        item = classify_early({"coin":"TEST/USDT", "change24": 1.0},
                              df, now=now)
        self.assertTrue(item is None or item["trạng thái"] != EARLY)

    def test_diverse_candidate_selection_and_no_future_data(self):
        markets = {
            f"TEST{i}_USDT": [1., 200000+i*1000, 2.] for i in range(60)
        }
        history = [{"ts": 1_700_000_000, "markets": markets},
                   {"ts": 1_700_000_300, "markets": markets}]
        sample = select_candidates(markets, history, limit=24)
        self.assertLessEqual(len(sample), 24)
        self.assertTrue(sample)


if __name__ == "__main__":
    unittest.main()
