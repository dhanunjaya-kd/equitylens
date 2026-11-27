import unittest
from datetime import datetime

from app import terminal


def candle(stamp, high=110, low=90, close=100, volume=1):
    ts = int(datetime.fromisoformat(stamp).replace(tzinfo=terminal.IST).timestamp())
    return dict(t=ts, o=close, h=high, l=low, c=close, v=volume)


class IntradayPivots(unittest.TestCase):
    def test_completed_session_including_weekend(self):
        friday = candle("2026-11-27T09:15")
        monday = candle("2026-11-30T09:15", 170, 140, 155)
        result = terminal.session_pivots([monday], [friday, monday], [friday, monday])
        self.assertEqual(result["basis"], "2026-11-27")
        self.assertEqual(result["levels"], dict(PP=100, R1=110, R2=120, R3=140,
                                                S1=90, S2=80, S3=60))
        self.assertIsNone(terminal.session_pivots([monday], [monday], [friday, monday]))
        self.assertIsNone(terminal.session_pivots([monday], [friday], [friday]))

    def test_three_minute_clock_buckets(self):
        bars = [candle("2026-11-27T09:15"), candle("2026-11-27T09:17", 115, 95, 108),
                candle("2026-11-27T09:19"), candle("2026-11-30T09:15")]
        out = terminal.three_minutes(dict(bars=bars, offset=19800, vwap=[100, 104, 103, 100]))
        self.assertEqual(out["bars"][0], dict(bars[0], h=115, c=108, v=2))
        self.assertEqual(out["bars"][1]["t"], bars[2]["t"] - 60)
        self.assertEqual(len(out["bars"]), 3)
        self.assertEqual(out["vwap"], [104, 103, 100])
