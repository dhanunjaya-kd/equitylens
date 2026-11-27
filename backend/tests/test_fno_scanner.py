import unittest
from datetime import date, datetime, time, timedelta
from unittest.mock import patch

from app import fno_scanner as scan


class ScannerTests(unittest.TestCase):
    def bars(self, up):
        rows = []
        for i in range(50):
            close = 101 + i if up else 199 - i
            rows.append(dict(t=(date(2026, 1, 1) + timedelta(days=i)).isoformat(),
                             h=close + 1, l=close - 1, c=close, v=125 if i == 49 else 100))
        return rows

    def test_two_sides_completed_session_only(self):
        for up, side in [(True, "CE"), (False, "PE")]:
            rows = self.bars(up)
            day = rows[-1]["t"]
            result = scan.setup(rows + [dict(rows[-1], t="2027-01-01", h=900)], day)
            self.assertEqual(result["side"], side)
            self.assertEqual(result["level"], 151 if up else 149)
            rows[-1]["v"] = 124
            self.assertIsNone(scan.setup(rows, day))
            with self.assertRaises(ValueError):
                scan.setup(rows[:-1], day)

    def test_opening_confirmation(self):
        day = date(2026, 11, 27)
        start = int(datetime.combine(day, time(9, 15), scan.calendars.IST).timestamp())
        for side, sign in [("CE", 1), ("PE", -1)]:
            bars = [dict(t=start + i*300, h=101+i*.3*sign, l=99+i*.3*sign,
                         c=100+i*.3*sign, v=100) for i in range(3)]
            row = dict(side=side, level=100)
            self.assertIsNone(scan.opening_trigger(bars, row, day))
            self.assertIsNotNone(scan.opening_trigger(bars[1:], row, day))
            row["level"] = 103 if sign > 0 else 97
            self.assertIsNotNone(scan.opening_trigger(bars, row, day))

    def test_ban_unavailable(self):
        with patch.object(scan.flows, "_nse_text", return_value=None):
            with self.assertRaises(ValueError):
                scan.banned(date.today())

    def test_full_scan_with_mocked_market_data(self):
        rows = self.bars(False)
        writes = {}
        with patch.object(scan.config, "DEMO", False), patch.object(scan.technicals, "_yahoo", return_value=rows), \
             patch.object(scan.flows, "_nse_text", return_value="Name,Symbol,Lot\nTest,TEST,100"), \
             patch.object(scan.store, "put_company", side_effect=writes.__setitem__), patch.object(scan, "datetime", wraps=datetime) as clock:
            clock.now.return_value = datetime.fromisoformat(rows[-1]["t"] + "T16:00:00+05:30")
            scan.run()
        self.assertEqual(writes[scan.KEY]["rows"][0]["side"], "PE")
        self.assertEqual(writes[scan.KEY]["total"], 1)

    def test_contract_depth_freshness_and_spread(self):
        now = datetime(2026, 11, 27, 9, 32, tzinfo=scan.calendars.IST)
        quote = {"buyPrice1": 10, "sellPrice1": 10.1, "sellQuantity1": 100}
        rec = {"timestamp": "27-Nov-2026 09:31:59", "underlyingValue": 150,
               "expiryDates": ["29-Dec-2026"], "data": [
                   {"strikePrice": 150, "expiryDates": "29-Dec-2026", "PE": quote}]}
        row = dict(symbol="TEST", side="PE", lot=100)
        with patch.object(scan.terminal, "_expiries", return_value=rec["expiryDates"]), \
             patch.object(scan.terminal, "_chain_raw", return_value={"records": rec}), \
             patch.object(scan, "datetime", wraps=datetime) as clock:
            clock.now.return_value = now
            self.assertIn("Paper trigger", scan.contract(row, now))
            quote["sellQuantity1"] = 99
            self.assertIn("depth", scan.contract(row, now))
            quote.update(sellQuantity1=100, sellPrice1=11)
            self.assertIn("Spread", scan.contract(row, now))
            rec["timestamp"] = "27-Nov-2026 09:20:00"
            self.assertIn("stale", scan.contract(row, now))
