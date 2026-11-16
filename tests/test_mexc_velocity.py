import unittest

from mexc_velocity import apply_snapshot, compute, parse_tickers


class MarketWideAccelerationTests(unittest.TestCase):
    def test_parser_covers_small_gainers_without_top_15_limit(self):
        metadata = [{"symbol": f"X{i}_USDT", "state": 0,
                     "quoteCoin": "USDT", "futureType": 1} for i in range(55)]
        tickers = [{"symbol": f"X{i}_USDT", "lastPrice": 1 + i/100,
                    "amount24": 200000, "riseFallRate": .01} for i in range(55)]
        market = parse_tickers(metadata, tickers, min_turnover=100000)
        self.assertEqual(len(market), 55)

    def test_collect_first_snapshot_never_claims_early_signal(self):
        history = apply_snapshot([], 1_700_001_000,
                                 {"TEST_USDT": [1.0, 500000, 1.0]})
        self.assertEqual(compute(history), [])

    def test_true_5_and_15minute_snapshot_momentum(self):
        t = 1_700_001_000 // 300 * 300
        hist = []
        prices = [1.0, 1.0, 1.0, 1.008]
        for j, p in enumerate(prices):
            hist = apply_snapshot(hist, t+j*300,
                                  {"TEST_USDT": [p, 750000, 2.0]})
        result = compute(hist)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["trạng thái"], "MỚI TĂNG TỐC — THEO DÕI")
        self.assertAlmostEqual(result[0]["15m %"], .8, places=2)

    def test_overheated_is_not_early(self):
        t = 1_700_001_000 // 300 * 300
        hist = []
        for j, p in enumerate([1., 1.01, 1.02, 1.08]):
            hist = apply_snapshot(hist, t+j*300,
                                  {"TEST_USDT": [p, 750000, 30.0]})
        result = compute(hist)
        self.assertEqual(result[0]["trạng thái"], "ĐÃ TĂNG NÓNG — KHÔNG MUA ĐUỔI")

    def test_missing_15minute_reference_is_not_early(self):
        t = 1_700_001_000 // 300 * 300
        history = apply_snapshot([], t, {"TEST_USDT": [1.0, 750000, 2.]})
        history = apply_snapshot(history, t+300,
                                 {"TEST_USDT": [1.01, 750000, 2.]})
        self.assertFalse(any(x["trạng thái"].startswith("MỚI TĂNG")
                             for x in compute(history)))

    def test_same_bucket_idempotent(self):
        h = apply_snapshot([], 1_700_001_005, {"TEST_USDT": [1., 200000, 1.]})
        h = apply_snapshot(h, 1_700_001_080, {"TEST_USDT": [1.01, 200000, 1.]})
        self.assertEqual(len(h), 1)


if __name__ == "__main__":
    unittest.main()
