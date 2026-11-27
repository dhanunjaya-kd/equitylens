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


if __name__ == "__main__":
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f()
            print("PASS", k)
