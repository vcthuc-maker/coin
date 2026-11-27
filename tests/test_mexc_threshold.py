import unittest
from mexc_threshold import detect_crossings, merge_events, recent_events


def h(t, ticker=3, px=1, symbol="BULLA_USDT"):
    return {"ts":t, "markets": {symbol:[px, 600000, ticker]}}


class ThresholdAlertsTest(unittest.TestCase):
    def test_first_5pct_crossing_is_emitted(self):
        t=1_700_000_000//300*300
        a=detect_crossings([h(t,4.8,1),h(t+300,5.6,1.01)],t+300)
        self.assertEqual(len(a),1)
        self.assertEqual(a[0]["mốc"],5)
        self.assertEqual(a[0]["coin"],"BULLA/USDT")

    def test_first_10pct_crossing_is_emitted(self):
        t=1_700_000_000//300*300
        a=detect_crossings([h(t,9.7,1),h(t+300,10.4,1.006)],t+300)
        self.assertEqual([x["mốc"] for x in a],[10])

    def test_no_backfill_when_already_55pct(self):
        t=1_700_000_000//300*300
        a=detect_crossings([h(t,54.9,1),h(t+300,55.35,1.006)],t+300)
        self.assertEqual(a,[])

    def test_missing_previous_snapshot_does_not_emit(self):
        t=1_700_000_000//300*300
        self.assertEqual(detect_crossings([h(t,5.4,1.01)],t),[])

    def test_cannot_replay_gap_over_ten_minutes(self):
        t=1_700_000_000//300*300
        self.assertEqual(detect_crossings([h(t,4,1),h(t+900,6,1.02)],t+900),[])

    def test_no_alert_when_price_drops_even_if_24h_pct_crosses(self):
        t=1_700_000_000//300*300
        self.assertEqual(detect_crossings([h(t,4.8,1),h(t+300,5.5,.99)],t+300),[])

    def test_no_alert_if_jump_too_far_beyond_threshold(self):
        t=1_700_000_000//300*300
        self.assertEqual(detect_crossings([h(t,4,1),h(t+300,22,1.2)],t+300),[])

    def test_cooldown_per_coin_and_per_milestone(self):
        t=1_700_000_000//300*300
        one=detect_crossings([h(t,4,1),h(t+300,5.3,1.01)],t+300)[0]
        events, new=merge_events([], [one],t+300)
        self.assertEqual(len(new),1)
        events, new=merge_events(events,[one],t+600)
        self.assertEqual(new,[])
        higher=dict(one,mốc=10,ts=t+600)
        events, new=merge_events(events,[higher],t+600)
        self.assertEqual(len(new),1)

    def test_recent_alerts_expire(self):
        t=1_700_000_000//300*300
        event=detect_crossings([h(t,4,1),h(t+300,5.3,1.01)],t+300)[0]
        self.assertEqual(len(recent_events([event],t+900)),1)
        self.assertEqual(recent_events([event],t+3901),[])


if __name__ == "__main__":
    unittest.main()
