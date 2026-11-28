import unittest
from mexc_radar import detect_radar, _suitable

T = 1800000000

def snapshot(ts, pct, price=1, symbol="BULLA_USDT"):
    return {"ts":ts, "markets":{symbol:[price, 500000, pct]}}

class MarketRadarTests(unittest.TestCase):
    def test_early_five_minute_impulse_without_full_candle_scan(self):
        h = [snapshot(T, 2, 1.0), snapshot(T+300, 3.6, 1.018)]
        new, missed = detect_radar(h, [], T+300)
        self.assertEqual([e["kind"] for e in new], ["EARLY"])
        self.assertFalse(missed)

    def test_5percent_crossing(self):
        h = [snapshot(T, 4.8, 1), snapshot(T+300, 5.6, 1.008)]
        new, _ = detect_radar(h, [], T+300)
        self.assertEqual([e["kind"] for e in new], ["M5"])

    def test_10percent_crossing(self):
        h = [snapshot(T, 9.5, 1), snapshot(T+300, 10.5, 1.01)]
        new, _ = detect_radar(h, [], T+300)
        self.assertEqual([e["kind"] for e in new], ["M10"])

    def test_already_55_is_not_reported_as_first_5(self):
        h = [snapshot(T, 54, 1), snapshot(T+300, 55, 1.01)]
        new, missed = detect_radar(h, [], T+300)
        self.assertEqual(new, [])
        self.assertEqual(missed, [])

    def test_big_gap_is_reported_late_not_early(self):
        h = [snapshot(T, 4, 1), snapshot(T+300, 15, 1.12)]
        new, missed = detect_radar(h, [], T+300)
        self.assertEqual(new, [])
        self.assertEqual(len(missed), 2)

    def test_missing_snapshots_does_not_guess(self):
        self.assertEqual(detect_radar([snapshot(T+300,5.7)],[],T+300), ([],[]))
        self.assertEqual(detect_radar([snapshot(T,3),snapshot(T+3600,6)],[],T+3600), ([],[]))

    def test_cooldown_prevents_repeating_early(self):
        h = [snapshot(T, 2, 1), snapshot(T+300, 3.6, 1.018)]
        new, _ = detect_radar(h, [], T+300)
        again, _ = detect_radar(h, new, T+300)
        self.assertEqual(again, [])

    def test_early_does_not_fire_when_24hour_already_pumped(self):
        h = [snapshot(T, 15, 1),snapshot(T+300,16.2,1.015)]
        new, _ = detect_radar(h,[],T+300)
        self.assertEqual(new, [])

    def test_ref_needs_real_historical_price(self):
        self.assertEqual(_suitable([snapshot(T, 1)],"WRONG_USDT",T+300,5,180),(None,None))


if __name__ == "__main__":
    unittest.main()
