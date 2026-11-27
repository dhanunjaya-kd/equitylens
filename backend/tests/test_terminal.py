"""Live terminal readers (offline):  python tests/test_terminal.py

The NSE rows here are in the shapes the readers accept; after the first live run on the laptop the app's saved
answers (data/term_raw/) replace them as fixtures, as was done for the IPO page.
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ["EQL_DEMO"] = "1"
os.environ.setdefault("EQL_DATA_DIR", tempfile.mkdtemp())
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import terminal as T  # noqa: E402


def test_quote_change_is_checked():
    q = T.parse_quote({"info": {"symbol": "ABC", "companyName": "ABC Ltd", "isFNOSec": True},
                       "priceInfo": {"lastPrice": 105.0, "previousClose": 100.0, "change": 5.0, "pChange": 5.0,
                                     "intraDayHighLow": {"min": 99.0, "max": 106.0}, "upperCP": "110.00", "lowerCP": "90.00", "vwap": 103.2},
                       "metadata": {"lastUpdateTime": "27-Nov-2026 15:30:00"}})
    assert (q["ltp"], q["change"], q["high"], q["low"], q["upper_circuit"], q["fno"]) == (105.0, 5.0, 106.0, 99.0, 110.0, True)
    assert q["change_check"] is None
    bad = T.parse_quote({"priceInfo": {"lastPrice": 105.0, "previousClose": 100.0, "change": 9.0, "pChange": 9.0}})
    assert bad["change"] == 5.0 and bad["pchange"] == 5.0 and "does not equal" in bad["change_check"]


def test_depth_order_is_checked():
    good = T.parse_trade({"marketDeptOrderBook": {"bid": [{"price": 100.0, "quantity": 5}, {"price": 99.9, "quantity": 8}],
                                                  "ask": [{"price": 100.1, "quantity": 3}, {"price": 100.2, "quantity": 9}],
                                                  "totalBuyQuantity": 1000, "totalSellQuantity": 800,
                                                  "tradeInfo": {"totalTradedVolume": 12345, "totalTradedValue": 1.23}},
                          "securityWiseDP": {"deliveryToTradedQuantity": 45.6}})
    assert good["depth"]["ok"] and good["depth"]["total_buy"] == 1000 and good["delivery_pct"] == 45.6
    crossed = T.parse_trade({"marketDeptOrderBook": {"bid": [{"price": 101.0, "quantity": 5}], "ask": [{"price": 100.0, "quantity": 5}]}})
    assert crossed["depth"]["ok"] is False and "below best ask" in crossed["depth"]["why"]
    assert T.parse_trade({})["depth"] is None


def test_chain_pcr_max_pain_and_expiry():
    js = {"records": {"expiryDates": ["02-Dec-2026", "09-Dec-2026"], "underlyingValue": 25910.0, "timestamp": "27-Nov-2026 15:30:00",
                      "data": [{"strikePrice": s, "expiryDate": e,
                                "CE": {"openInterest": ce, "changeinOpenInterest": 1, "impliedVolatility": 12.5, "lastPrice": 10},
                                "PE": {"openInterest": pe, "lastPrice": 20}}
                               for e in ("02-Dec-2026", "09-Dec-2026")
                               for s, ce, pe in ((25800, 100, 900), (25900, 400, 500), (26000, 900, 100))]}}
    c = T.parse_chain(js)
    assert c["expiry"] == "02-Dec-2026" and len(c["rows"]) == 3 and c["atm"] == 25900 and c["ok"]
    assert c["pcr"] == round(1500 / 1400, 2)
    # payout at 25900: calls 100*100 = 10000, puts 100*100 = 10000 -> 20000; 25800: puts 500*100+100*200=70000; 26000: calls 100*200+400*100=60000
    assert c["max_pain"] == 25900
    assert T.parse_chain(js, "09-Dec-2026")["expiry"] == "09-Dec-2026"


def test_futures_basis_is_arithmetic():
    d = T.parse_deriv({"underlyingValue": 1000.0, "stocks": [
        {"metadata": {"instrumentType": "Stock Futures", "expiryDate": "29-Dec-2026", "lastPrice": 1012.5},
         "marketDeptOrderBook": {"tradeInfo": {"openInterest": 5000, "changeinOpenInterest": -200}}},
        {"metadata": {"instrumentType": "Stock Futures", "expiryDate": "26-Jan-2027", "lastPrice": 1020.0}},
        {"metadata": {"instrumentType": "Stock Options", "expiryDate": "29-Dec-2026", "lastPrice": 12.0}}]})
    assert [f["expiry"] for f in d["futures"]] == ["29-Dec-2026", "26-Jan-2027"]
    assert d["futures"][0]["basis"] == 12.5 and d["futures"][0]["oi"] == 5000


def test_yahoo_candles_and_vwap():
    res = {"meta": {"regularMarketPrice": 102.0, "chartPreviousClose": 100.0, "gmtoffset": 19800, "currency": "INR"},
           "timestamp": [1795700000, 1795700300, 1795700600],
           "indicators": {"quote": [{"open": [100, 101, None], "high": [101, 102, 103], "low": [99, 100, 101],
                                     "close": [100.5, 101.5, 102], "volume": [10, 30, 5]}]}}
    y = T.parse_yahoo(res)
    assert len(y["bars"]) == 2 and y["change"] == 2.0 and y["pchange"] == 2.0
    tp1, tp2 = (101 + 99 + 100.5) / 3, (102 + 100 + 101.5) / 3
    assert y["vwap"] == [round(tp1, 2), round((tp1 * 10 + tp2 * 30) / 40, 2)]
    assert T.yahoo_symbol("reliance") == "RELIANCE.NS" and T.yahoo_symbol("US:AAPL") == "AAPL" and T.yahoo_symbol("NIFTY") == "^NSEI"
    assert T.yahoo_symbol("US:SPX") == "^GSPC" and T.yahoo_symbol("US:NASDAQ") == "^IXIC" and T.yahoo_symbol("US:MSFT") == "MSFT"


def test_real_nse_option_chain_v3():
    import json
    js = json.loads((Path(__file__).parent / "fixtures" / "term" / "nse_chain_v3.json").read_text(encoding="utf-8"))
    c = T.parse_chain(js)                                    # NIFTY, saved by the app on 27 Nov 2026 09:29
    assert (c["expiry"], c["spot"], c["time"], c["atm"]) == ("01-Dec-2026", 25820.3, "27-Nov-2026 09:29:00", 25800.0)
    assert len(c["rows"]) == 149 and c["ok"] and c["pcr"] == 0.97 and c["max_pain"] == 25800.0
    atm = next(r for r in c["rows"] if r["strike"] == 25800.0)
    assert (atm["ce_ltp"], atm["pe_ltp"], atm["ce_oi"], atm["pe_oi"], atm["ce_iv"]) == (181.55, 166.8, 103873.0, 156127.0, 15.8)
    assert len(c["expiries"]) == 18 and c["expiries"][0] == "01-Dec-2026"


def test_four_hour_candles_from_hourly():
    from datetime import datetime, timezone
    t0 = int(datetime(2026, 11, 27, 3, 45, tzinfo=timezone.utc).timestamp())     # 09:15 IST
    day1 = [{"t": t0 + i * 3600, "o": 10 + i, "h": 11 + i, "l": 9 + i, "c": 10.5 + i, "v": 100} for i in range(7)]
    out = T.group_hours(day1, 19800)
    assert len(out) == 2 and out[0]["o"] == 10 and out[0]["c"] == 13.5 and out[0]["h"] == 14 and out[0]["v"] == 400
    assert out[1]["o"] == 14 and out[1]["v"] == 300


def test_real_nse_quote_and_order_book():
    import json
    js = json.loads((Path(__file__).parent / "fixtures" / "term" / "nse_quote_next.json").read_text(encoding="utf-8"))
    q = T.parse_quote(js)                                    # HDFCBANK, saved by the app on 27 Nov 2026 09:40
    assert (q["symbol"], q["ltp"], q["prev"], q["change"], q["pchange"]) == ("HDFCBANK", 860.5, 862.0, -1.5, -0.17)
    assert (q["open"], q["high"], q["low"], q["vwap"]) == (857.9, 864.7, 857.9, 861.35) and q["change_check"] is None
    assert (q["lower_circuit"], q["upper_circuit"], q["wk_high"], q["wk_low"], q["pe"]) == (775.8, 948.2, 1017.5, 669.2, 16.61)
    t = T.parse_trade(js)
    assert t["depth"]["ok"] and [b["price"] for b in t["depth"]["bids"]] == [860.35, 860.3, 860.25, 860.2, 860.15]
    assert t["depth"]["asks"][0] == {"price": 860.5, "qty": 756.0} and t["depth"]["total_sell"] == 1456374
    assert t["value_cr"] == 445.33 and t["delivery_pct"] == 63.82 and t["volume"] == 5170099


def test_real_nse_futures():
    import json
    js = json.loads((Path(__file__).parent / "fixtures" / "term" / "nse_deriv_next.json").read_text(encoding="utf-8"))
    d = T.parse_deriv(js)                                    # BANKNIFTY, 27 Nov 2026 09:41
    assert d["spot"] == 63833.45 and d["time"] == "27-Nov-2026 09:41:08"
    assert [f["expiry"] for f in d["futures"]] == ["29-Dec-2026", "25-Jan-2027", "23-Feb-2027"]
    assert d["futures"][0]["ltp"] == 63998 and d["futures"][0]["basis"] == 164.55 and d["futures"][0]["oi"] == 49331


if __name__ == "__main__":
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f()
            print("PASS", k)
