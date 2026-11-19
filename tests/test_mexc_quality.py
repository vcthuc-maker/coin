import unittest
import numpy as np
import pandas as pd

from mexc_quality import analyze, PREP, HOLD, REJECT
from mexc_outcomes import update_events, simple_summary, outcomes_table


def sample():
    n = 90
    t = np.arange(n)*300+1_700_000_000
    price = np.ones(n)
    hi = np.full(n, 1.02)
    lo = np.full(n, .98)
    vol = np.full(n, 18000.)
    # Last hour prior to candidate candle: quiet narrow base.
    hi[-15:-3] = 1.001
    lo[-15:-3] = .999
    vol[-15:-3] = 5000.
    hi[-3:] = 1.001
    lo[-3:] = .999
    vol[-3:] = 7500.
    return pd.DataFrame({
        "t": t, "open": price.copy(), "close": price.copy(),
        "high": hi, "low": lo, "amount": vol
    })


class QualityScannerTests(unittest.TestCase):
    def market(self, ch24=1):
        return {"coin":"TEST/USDT", "change24":ch24}

    def test_quiet_base_preparation(self):
        result = analyze(self.market(), sample())
        self.assertIsNotNone(result)
        self.assertEqual(result["trạng thái"], PREP)

    def test_single_volume_burst_is_not_confirmation(self):
        candles = sample()
        candles.loc[89, "amount"] = 250_000.
        result = analyze(self.market(), candles)
        self.assertTrue(result is None or result["trạng thái"] != HOLD)

    def test_breakout_needs_two_closed_holding_candles(self):
        candles = sample()
        for i in (88, 89):
            candles.loc[i, ["open", "close", "high", "low", "amount"]] = [
                1.001, 1.006, 1.007, 1.000, 12000
            ]
        result = analyze(self.market(), candles)
        self.assertIsNotNone(result)
        self.assertEqual(result["trạng thái"], HOLD)

    def test_giant_upper_wick_is_rejected(self):
        candles = sample()
        candles.loc[89, ["open", "close", "high", "low", "amount"]] = [
            1.0, 1.0003, 1.04, .999, 100000
        ]
        result = analyze(self.market(), candles)
        self.assertEqual(result["trạng thái"], REJECT)

    def test_overheated_24h_is_not_pre_pump(self):
        self.assertEqual(analyze(self.market(ch24=38), sample())["trạng thái"], REJECT)

    def test_missing_candle_blocks_all(self):
        data = sample().drop(index=75)
        self.assertIsNone(analyze(self.market(), data))

    def test_stale_candle_blocks_all(self):
        candles = sample()
        now = int(candles["t"].iloc[-1] + 300+500)
        self.assertIsNone(analyze(self.market(), candles, now=now))

    def test_no_future_price_used(self):
        candles = sample()
        prior = analyze(self.market(), candles)
        appended = pd.concat([candles, pd.DataFrame([{
            "t": candles["t"].iloc[-1]+300,
            "open":1., "close":1.5, "high":1.6, "low":.5, "amount":1e10,
        }])], ignore_index=True)
        now = int(candles["t"].iloc[-1]+300)
        self.assertIsNone(analyze(self.market(), appended, now=now))
        self.assertEqual(prior["trạng thái"], PREP)


class ForwardTrackingTests(unittest.TestCase):
    def test_future_outcome_waits_for_real_snapshot(self):
        t = 1_700_000_000
        signals = [{"coin":"TEST/USDT","trạng thái":PREP,"giá":1.}]
        entries = update_events([], signals, t, {"TEST_USDT":[1., 500000, 1.]})
        self.assertEqual(len(entries), 1)
        self.assertIsNone(entries[0]["metrics"]["15"])
        later = update_events(entries, signals, t+900,
                              {"TEST_USDT":[.92, 500000, -8.]})
        self.assertEqual(later[0]["metrics"]["15"], -8.)
        self.assertEqual(simple_summary(later)["positive_15_pct"], 0.)

    def test_missing_future_is_censored(self):
        t = 1_700_000_000
        rows = [{"coin":"TEST/USDT","trạng thái":PREP,"giá":1.}]
        events = update_events([], rows, t, {"TEST_USDT":[1., 500000, 0.]})
        events = update_events(events, [], t+1800, {})
        self.assertEqual(events[0]["metrics"]["15"], {"missing": True})
        self.assertEqual(simple_summary(events)["evaluated_15"], 0)

    def test_cooldown_prevents_repeated_flags(self):
        t = 1_700_000_000
        rows = [{"coin":"TEST/USDT","trạng thái":PREP,"giá":1.}]
        e = update_events([], rows, t, {"TEST_USDT":[1., 500000, 0.]})
        e = update_events(e, rows, t+300, {"TEST_USDT":[1.01, 500000, 1.]})
        self.assertEqual(len(e), 1)


if __name__ == "__main__":
    unittest.main()
