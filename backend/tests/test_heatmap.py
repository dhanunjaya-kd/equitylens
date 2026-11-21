"""Heatmap data (offline):  python tests/test_heatmap.py"""
import os
import sys
import tempfile
from pathlib import Path

os.environ["EQL_DEMO"] = "1"
os.environ.setdefault("EQL_DATA_DIR", tempfile.mkdtemp())
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import heatmap, movers, sectors, store, technicals, usshares  # noqa: E402

store.init()
movers.refresh("IN", block=True)


def test_rows_are_slim_and_honest_about_market_cap():
    d = heatmap.get("IN", "1W")
    assert d["tf"] == "1W" and d["count"] == len(d["rows"]) > 0
    r = d["rows"][0]
    assert set(r["ret"]) == set(movers.TF) and "spark" not in r
    assert d["no_mcap"] == sum(1 for x in d["rows"] if not x["mcap"])      # nothing scanned in demo: all counted
    assert all(x["mcap"] is None for x in d["rows"])                         # never a guessed market cap


def test_sector_totals_add_up():
    d = heatmap.get("IN", "1D")
    assert sum(s["count"] for s in d["sectors"]) == d["count"]
    for s in d["sectors"]:
        rs = [r for r in d["rows"] if r["sector"] == s["sector"]]
        vals = [r["ret"]["1D"] for r in rs if r["ret"]["1D"] is not None]
        assert s["up"] == sum(1 for v in vals if v > 0) and s["down"] == sum(1 for v in vals if v < 0)
        assert abs(s["avg"] - sum(vals) / len(vals)) < 0.01


def test_sector_index_mapping():
    assert heatmap.sector_index("IN", "Information Technology")["index"]["ticker"] == "^CNXIT"
    assert heatmap.sector_index("IN", "Financial Services")["index"]["ticker"] == "NIFTY_FIN_SERVICE.NS"
    assert heatmap.sector_index("IN", "Chemicals")["index"] is None                      # no index: says so
    assert heatmap.sector_index("US", "Information Technology")["index"]["ticker"] == "XLK"
    assert heatmap.sector_index("US", "Unknown")["index"] is None
    ix = heatmap.sector_index("IN", "Information Technology")["index"]
    assert ix["fall_pct"] >= 0 and set(ix["ret"]) == set(movers.TF)


def test_nse_quote_gives_sector_and_shares():
    q = '{"industryInfo": {"macro": "Financial Services", "sector": "Financial Services", "industry": "Banks"}, "securityInfo": {"issuedSize": 7651780468}}'
    assert sectors.parse_quote(q) == ("Financial Services", 7651780468.0)
    assert sectors.parse_quote('{"industryInfo": {"sector": "NA"}, "securityInfo": {"issuedSize": 0}}') == (None, None)
    assert sectors.parse_quote("<html>blocked</html>") == (None, None)


def test_market_cap_from_nse_shares_only_when_no_scan():
    r = {"symbol": "ABC", "name": "Abc", "sector": "Power", "price": 250.0, "ret": {}, "turnover": {"1D": 5.0}}
    assert heatmap.slim(r, "1D", {"ABC": 4e8})["mcap"] == 10000.0            # 40 cr shares x Rs 250 = Rs 10,000 Cr
    assert heatmap.slim(r, "1D", {"ABC": 4e8})["mcap_src"] == "nse_shares"
    assert heatmap.slim(r, "1D", {})["mcap"] is None                          # no shares, no scan: no market cap
    scanned = dict(r, fund={"market_cap": 12345})
    assert heatmap.slim(scanned, "1D", {"ABC": 4e8})["mcap"] == 12345          # the scan wins


def test_which_stocks_still_need_a_lookup():
    import time
    store.put_company(sectors.KEY, {"sectors": {"AAA": "Power"}, "asked": {"CCC": time.time()},
                                    "shares": {"AAA": {"n": 1e8, "t": time.time()}, "BBB": {"n": 1e8, "t": 0}}})
    need = sectors.missing(["AAA", "BBB", "CCC", "DDD"])
    assert "AAA" not in need                    # sector and fresh shares known
    assert "BBB" in need and "DDD" in need      # no sector / stale shares; never asked
    assert "CCC" not in need                    # asked recently and NSE had nothing: not asked again for a month
    assert sectors.sector_map()["AAA"] == "Power"


def test_us_close_is_dated_on_new_york_time():
    import datetime as dt
    fri_close = int(dt.datetime(2026, 11, 20, 21, 0, tzinfo=dt.timezone.utc).timestamp())    # 4 pm New York, Friday
    assert technicals._day(fri_close, technicals._offset({"gmtoffset": -18000})) == "2026-11-20"
    assert technicals._day(fri_close, technicals._offset({})) == "2026-11-21"               # the old India-clock bug
    bars = [{"t": "2026-11-20", "o": 10, "h": 11, "l": 9, "c": 10.5, "v": 1}]
    meta = {"regularMarketPrice": 10.5, "regularMarketTime": fri_close, "gmtoffset": -18000}
    assert technicals.apply_meta(bars, meta) == bars                                         # no fake "Saturday" bar
    nse_close = int(dt.datetime(2026, 11, 20, 10, 0, tzinfo=dt.timezone.utc).timestamp())   # 3:30 pm India
    assert technicals._day(nse_close, technicals._offset({"gmtoffset": 19800})) == "2026-11-20"


def test_us_shares_from_sec_frames():
    import datetime as dt
    assert usshares.quarters(dt.date(2026, 1, 5), 3) == [(2026, 1), (2025, 4), (2025, 3)]
    best = usshares.parse_frames([{"data": [{"cik": 1, "val": 100, "end": "2026-04-01"}, {"cik": 2, "val": "x"}]},
                                  {"data": [{"cik": 1, "val": 120, "end": "2026-10-01"}]}])
    assert best == {1: {"n": 120.0, "end": "2026-10-01"}}
    r = {"symbol": "US:ABC", "name": "Abc", "sector": "Energy", "price": 50.0, "ret": {}, "turnover": {}}
    got = heatmap.slim(r, "1D", {"US:ABC": 2e8})
    assert got["mcap"] == 10000.0 and got["mcap_src"] == "sec_shares"                       # $10,000 M = $10 B


if __name__ == "__main__":
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f()
            print("PASS", k)
