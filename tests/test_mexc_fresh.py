import unittest
import numpy as np
import pandas as pd

from mexc_fresh import hourly_context, fresh_breakout, apply_48h_guard, FRESH, LATE48
from mexc_outcomes import update_events


def hours(closes):
    n = len(closes)
    return pd.DataFrame({
        "t": 1_700_000_000 + np.arange(n)*3600,
        "high": np.array(closes)*1.002,
        "low": np.array(closes)*.998,
        "close": closes,
    })


def minute5():
    n = 85
    c = np.ones(n)
    c[-1] = 1.007
    amount = np.full(n, 14000.)
    amount[-13:-1] = 8000.
    amount[-1] = 15000.
    high = np.full(n, 1.02)
    low = np.full(n, .98)
    high[-13:-1] = 1.002
    low[-13:-1] = .998
    high[-1] = 1.008
    low[-1] = .999
    return pd.DataFrame({
        "t": 1_700_000_000 + np.arange(n)*300,
        "open": np.ones(n), "high": high, "low": low,
        "close": c, "amount": amount
    })


class FirstAlertTests(unittest.TestCase):
    def test_new_breakout_first_candle(self):
        bars = minute5()
        now = int(bars["t"].iloc[-1]+300)
        r = fresh_breakout({"coin":"TEST/USDT","change24":1.}, bars, now=now)
        self.assertIsNotNone(r)
        self.assertEqual(r["trạng thái"], FRESH)
        self.assertEqual(r["số nến giữ nền"], 1)

    def test_second_breakout_does_not_claim_first(self):
        bars = minute5()
        bars.loc[83,"close"] = 1.006
        bars.loc[83,"high"] = 1.007
        now = int(bars["t"].iloc[-1]+300)
        r = fresh_breakout({"coin":"TEST/USDT","change24":1.}, bars, now=now)
        self.assertIsNone(r)

    def test_late_48h_coin_is_rejected_even_when_short_term_breaks(self):
        closes = np.linspace(1.,1.17,55)
        h = hours(closes)
        ctx = hourly_context(h,1.17,now=int(h["t"].iloc[-1]+3600))
        self.assertTrue(ctx["late"])
        row = {"coin":"TEST/USDT","trạng thái":FRESH}
        rejected = apply_48h_guard(row,ctx)
        self.assertEqual(rejected["trạng thái"], LATE48)

    def test_neutral_48h_does_not_block_first_alert(self):
        closes = np.full(55,1.)
        h = hours(closes)
        ctx = hourly_context(h,1.007,now=int(h["t"].iloc[-1]+3600))
        self.assertFalse(ctx["late"])
        row = {"coin":"TEST/USDT","trạng thái":FRESH}
        self.assertEqual(apply_48h_guard(row,ctx)["trạng thái"],FRESH)

    def test_missing_long_history_never_claims_early(self):
        self.assertIsNone(hourly_context(hours(np.ones(12)),1.))
        self.assertIsNone(apply_48h_guard({"trạng thái":FRESH},None))

    def test_48h_cooldown_blocks_repeat_alert(self):
        event = {"coin":"TEST/USDT","trạng thái":FRESH,"giá":1.}
        markets = {"TEST_USDT":[1.,500000,1.]}
        t = 1_700_000_000
        e = update_events([], [event], t, markets)
        e = update_events(e,[event],t+3600,markets)
        self.assertEqual(len(e),1)
        e = update_events(e,[event],t+49*3600,markets)
        self.assertEqual(len(e),2)


if __name__=="__main__":
    unittest.main()
