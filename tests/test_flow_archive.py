import tempfile
import unittest
from pathlib import Path
import pandas as pd

from flow_collector import dedupe_append, spot_sample
from flow_history import summarize_flow
from signal_archive import tracking_table


class ArchiveTests(unittest.TestCase):
    def test_idempotent_hour(self):
        row = {"hour_utc": "2026-11-16T01:00:00Z",
               "exchange": "okx", "coin": "SOL",
               "collected_at_utc": "2026-11-16T01:13:00Z"}
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "flow.jsonl"
            self.assertEqual(dedupe_append(p, [row]), 1)
            self.assertEqual(dedupe_append(p, [row]), 0)
            self.assertEqual(len(p.read_text().splitlines()), 1)

    def test_spot_sample_has_duration(self):
        r = spot_sample([("buy", 200., 100000), ("sell", 100., 160000)])
        self.assertAlmostEqual(r["spot_sample_imbalance_pct"], 33.333, places=3)
        self.assertEqual(r["spot_sample_minutes"], 1.0)
        self.assertEqual(r["spot_sample_count"], 2)

    def test_oi_4h_only_when_sufficient_snapshots(self):
        frame = pd.DataFrame([
            {"exchange": "okx", "coin": "SOL", "collected_at_utc": "2026-11-16T00:12:00Z",
             "oi_unit": "USD", "oi_value": 100., "price_usdt": 20.,
             "spot_sample_count": 10, "spot_sample_minutes": 1,
             "spot_sample_imbalance_pct": 10.},
            {"exchange": "okx", "coin": "SOL", "collected_at_utc": "2026-11-16T04:12:00Z",
             "oi_unit": "USD", "oi_value": 110., "price_usdt": 21.,
             "spot_sample_count": 10, "spot_sample_minutes": 1,
             "spot_sample_imbalance_pct": -5.},
        ])
        frame["time"] = pd.to_datetime(frame["collected_at_utc"], utc=True)
        result = summarize_flow(frame, now="2026-11-16T05:00:00Z")
        self.assertEqual(float(result["OI 4H % (ước tính)"].iloc[0]), 10.)
        self.assertEqual(float(result["số giờ so sánh"].iloc[0]), 4.)

    def test_snapshot_followup_not_before_four_hours(self):
        archive = pd.DataFrame([{
            "exchange": "okx", "coin": "DOGE",
            "time": pd.Timestamp("2026-11-16T01:13:00Z"),
            "snapshot_price_usdt": .1, "phase": "ĐANG TÍCH LŨY",
            "score": 60, "compression_hours": 12
        }])
        prices = pd.DataFrame([{
            "exchange": "okx", "coin": "DOGE",
            "time": pd.Timestamp("2026-11-16T05:13:00Z"), "price_usdt": .105
        }])
        result = tracking_table(archive, prices)
        self.assertAlmostEqual(result["biến động ~4H %"].iloc[0], 5.)
        self.assertEqual(result["khoảng cách giờ"].iloc[0], 4.)


if __name__ == "__main__":
    unittest.main()
