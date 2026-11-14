"""Index card: Yahoo chart format, change maths, VIX bands (offline):  python tests/test_indices.py"""
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ["EQL_DEMO"] = "1"
os.environ.setdefault("EQL_DATA_DIR", tempfile.mkdtemp())
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import indices  # noqa: E402

NOW = int(time.time())
RAW = {"chart": {"result": [{"meta": {"currency": "INR", "symbol": "^NSEI", "regularMarketPrice": 25100.5, "chartPreviousClose": 24900.0,
                                      "regularMarketDayHigh": 25150.0, "regularMarketDayLow": 24880.0, "fiftyTwoWeekHigh": 26277.35,
                                      "fiftyTwoWeekLow": 21743.65, "regularMarketTime": NOW,
                                      "currentTradingPeriod": {"regular": {"start": NOW - 3600, "end": NOW + 3600}}},
                             "timestamp": [NOW - 600, NOW - 300, NOW], "indicators": {"quote": [{"close": [24950.0, None, 25100.5]}]}}], "error": None}}


def test_parse_yahoo_chart():
    r = indices.parse(RAW, "^NSEI", "NIFTY 50", "index", "IN")
    assert r["price"] == 25100.5 and r["change"] == 200.5 and r["change_pct"] == 0.81
    assert r["open"] is True and r["spark"] == [24950.0, 25100.5] and r["hi52"] == 26277.35 and r["mood"] is None


def test_closed_market_and_missing():
    raw = {"chart": {"result": [{**RAW["chart"]["result"][0], "meta": {**RAW["chart"]["result"][0]["meta"],
           "currentTradingPeriod": {"regular": {"start": NOW - 7200, "end": NOW - 3600}}}}]}}
    assert indices.parse(raw, "^NSEI", "NIFTY 50", "index", "IN")["open"] is False
    try:
        indices.parse({"chart": {"result": []}}, "^X", "X", "index", "IN")
        raise AssertionError("should fail")
    except ValueError:
        pass


def test_vix_bands():
    assert indices.vix_mood(11, "IN")["label"] == "Calm" and indices.vix_mood(14, "IN")["label"] == "Normal"
    assert indices.vix_mood(19, "IN")["label"] == "Nervous" and indices.vix_mood(28, "IN")["label"] == "Fear"
    assert indices.vix_mood(14, "US")["label"] == "Normal" and indices.vix_mood(35, "US")["label"] == "Fear"


def test_both_markets_lists():
    i = [x["name"] for x in indices.get("IN")["items"]]
    u = [x["name"] for x in indices.get("US")["items"]]
    assert i == ["NIFTY 50", "BANK NIFTY", "SENSEX", "INDIA VIX"]
    assert u == ["S&P 500", "NASDAQ", "DOW JONES", "RUSSELL 2000", "VIX"]
    assert indices.get("US")["items"][-1]["mood"]


if __name__ == "__main__":
    bad = 0
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            try:
                f(); print("PASS", n)
            except Exception as e:  # noqa: BLE001
                bad += 1; print("FAIL", n, repr(e))
    sys.exit(1 if bad else 0)
