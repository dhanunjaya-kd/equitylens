"""US pipeline on SEC-format sample files (offline):  python tests/test_us.py"""
import os
import sys
import tempfile
from pathlib import Path

os.environ["EQL_DEMO"] = "1"
os.environ.setdefault("EQL_DATA_DIR", tempfile.mkdtemp())
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import analysis, money, us  # noqa: E402

info, FACTS, SUBS = us.fetch_raw("TSTUS")


def _c(price=180.0):
    return us.build_company("TSTUS", price, 207.0, 127.0, info, FACTS, SUBS)


def test_revenue_tag_switch_is_merged():
    s = _c()["tables"]["profit_loss"]["rows"]["Sales"]
    assert s[0] == 20000.0 and all(v is not None for v in s[:12])  # SalesRevenueNet (2014-17) + ASC 606 tag (2018+)


def test_ytd_ignored_and_q4_derived():
    q = _c()["tables"]["quarters"]
    sales = dict(zip(q["columns"], q["rows"]["Sales"]))
    fy25 = 20000 * 1.1 ** 11
    assert abs(sales["Sep 2025"] - round(fy25 * 0.26, 2)) < 1      # derived Q4
    assert abs(sales["Jun 2025"] - round(fy25 * 0.24, 2)) < 1      # 3-month value, not the 9-month YTD


def test_ttm_and_ratios():
    c = _c()
    pl = c["tables"]["profit_loss"]
    assert pl["columns"][-1] == "TTM"
    r = c["ratios"]
    assert r["market_cap"] == round(180 * 940e6 / 1e6) and r["pe"] == round(180 / pl["rows"]["EPS in Rs"][-1], 1)
    assert r["high"] == 207.0 and r["book_value"] > 0


def test_documents_point_to_sec():
    docs = _c()["documents"]
    assert docs[0]["items"][0]["url"].startswith("https://www.sec.gov/Archives/edgar/data/1234567/")


def test_engine_runs_in_dollars():
    money.set_market("US")
    c = _c()
    c.pop("annual_eps_points")
    a = analysis.analyse(c, 18.0)
    assert a["verdict"]["tone"] in ("good", "ok") and a["scores"]["ownership"] is None
    assert a["forensics"]["piotroski"]["available"] and "$" in a["forensics"]["piotroski"]["checks"][0]["detail"]
    assert not any("₹" in f["text"] for f in a["flags"])
    money.set_market("IN")


def test_search_and_unknown():
    assert us.search("tst")[0]["symbol"] == "US:TSTUS"
    try:
        us.fetch_raw("ZZZZ")
        raise AssertionError
    except us.USFetchError:
        pass


def test_pe_history():
    bars = [{"t": f"20{y}-{m:02d}-15", "c": 100.0} for y in range(16, 26) for m in range(1, 13)]
    pe = us.pe_history(bars, [("2015-09-30", 5.0), ("2020-09-30", 10.0)])
    assert pe["Price to Earning"][0][1] == 20.0 and pe["Price to Earning"][-1][1] == 10.0


# ---- foreign filer (20-F, IFRS, euros). Constructed in SEC's companyfacts layout; to be joined by a real saved
#      answer (data/us_raw/sec_facts_<TICKER>.json) once the app has fetched one.
def _ann(vals, unit="EUR", form="20-F"):
    return {"units": {unit: [{"start": f"{y - 1}-01-01", "end": f"{y - 1}-12-31", "val": v, "form": form, "filed": f"{y}-03-01"}
                             for y, v in vals]}}


def _inst(vals, unit="EUR"):
    return {"units": {unit: [{"end": f"{y - 1}-12-31", "val": v, "form": "20-F", "filed": f"{y}-03-01"} for y, v in vals]}}


IFRS = {"facts": {"dei": {}, "ifrs-full": {
    "Revenue": _ann([(2023, 1000e6), (2024, 1200e6), (2025, 1440e6)]),
    "ProfitLoss": _ann([(2023, 110e6), (2024, 130e6), (2025, 160e6)]),
    "ProfitLossAttributableToOwnersOfParent": _ann([(2023, 100e6), (2024, 120e6), (2025, 150e6)]),
    "BasicEarningsLossPerShare": {"units": {"EUR/shares": [{"start": "2024-01-01", "end": "2024-12-31", "val": 1.5, "form": "20-F", "filed": "2025-03-01"}]}},
    "Assets": _inst([(2024, 3000e6), (2025, 3300e6)]),
    "EquityAttributableToOwnersOfParent": _inst([(2024, 1500e6), (2025, 1650e6)]),
}}}
FX = {"rate": 1.10, "date": "2026-11-27", "source": "Yahoo EURUSD=X"}
EU = {"ticker": "EUCO", "cik": 999, "name": "Euro Co"}


def test_ifrs_filer_reads_ifrs_and_converts_at_one_stated_rate():
    F = us.Facts(IFRS)
    assert (F.ns, F.cur, F.annual_form()) == ("ifrs-full", "EUR", "20-F")
    c = us.build_company("EUCO", 50.0, 55.0, 40.0, EU, IFRS, {"name": "Euro Co"}, fx=FX, nasdaq_cap=11000.0)
    pl = c["tables"]["profit_loss"]["rows"]
    assert pl["Sales"] == [1100.0, 1320.0, 1584.0]                       # EUR m x 1.10
    assert pl["Net Profit"] == [110.0, 132.0, 165.0]                     # owners' share, not ProfitLoss incl. minorities
    # per US-traded share: Nasdaq cap 11,000 $M / $50 = 220 M traded shares -> EPS = 165 / 220
    assert pl["EPS in Rs"][-1] == 0.75 and c["ratios"]["market_cap"] == 11000 and c["ratios"]["pe"] == round(50 / 0.75, 1)
    assert c["reporting"]["currency"] == "EUR" and c["reporting"]["fx"]["rate"] == 1.10 and c["reporting"]["standard"] == "IFRS"
    assert "1 EUR = $1.1" in c["about"]


def test_foreign_filer_without_rate_or_cap_shows_nothing_invented():
    try:
        us.build_company("EUCO", 50.0, 55.0, 40.0, EU, IFRS, {}, fx=None)
        raise AssertionError("must refuse without an exchange rate")
    except us.USFetchError as e:
        assert "EUR" in str(e)
    c = us.build_company("EUCO", 50.0, 55.0, 40.0, EU, IFRS, {}, fx=FX, nasdaq_cap=None)
    assert "market_cap" not in c["ratios"] and "pe" not in c["ratios"] and c["tables"]["profit_loss"]["rows"]["EPS in Rs"][-1] is None


def test_new_listing_profile_from_what_exists():
    subs = {"name": "Anthropic, PBC", "sic": "7372", "sicDescription": "Services-Prepackaged Software", "exchanges": ["Nasdaq"],
            "filings": {"recent": {"form": ["424B4", "S-1/A", "S-1", "8-K"], "filingDate": ["2026-11-20", "2026-11-10", "2026-10-01", "2026-11-21"],
                                   "accessionNumber": ["0001-26-1", "0001-26-2", "0001-26-3", "0001-26-4"],
                                   "primaryDocument": ["p.htm", "a.htm", "s1.htm", "k.htm"], "reportDate": ["", "", "", ""]}}}
    ipo_row = {"priced": "2026-11-19", "final_price": 83.0, "range_text": "83.00", "shares": 980e6, "value_m": 81340.0, "symbol": "ANT"}
    bars = [{"t": "2026-11-20", "o": 100.0, "h": 110.0, "l": 95.0, "c": 104.0, "v": 1}, {"t": "2026-11-27", "o": 104, "h": 106, "l": 99, "c": 99.6, "v": 1}]
    p = us.profile({"ticker": "ANT", "cik": 1, "name": "Anthropic"}, {"facts": {}}, subs, bars, ipo_row,
                   {"market_cap": 120000.0, "sector": "Information Technology", "country": "United States"})
    assert p["kind"] == "new_listing" and p["ipo"]["final_price"] == 83.0 and p["price"] == 99.6
    assert p["listing_move"]["first_day"] == "2026-11-20" and p["listing_move"]["now_vs_issue"] == 20.0
    assert [x["form"] for x in p["prospectus"]] == ["424B4", "S-1/A", "S-1"] and p["quarters"] == {} and p["balance"] is None
    assert us.profile({"ticker": "SPCX", "cik": 2, "name": "x"}, {"facts": {}}, {"sic": "6770"}, [], None, None)["kind"] == "spac"



def test_nasdaq_screener_rows_are_checked():
    from app import movers, usuniverse
    js = {"data": {"headers": {}, "rows": [
        {"symbol": "AAPL", "name": "Apple Inc. Common Stock", "lastsale": "$255.46", "netchange": "-0.33", "pctchange": "-0.129%",
         "volume": "40000000", "marketCap": "3791234567890.00", "country": "United States", "ipoyear": "1980",
         "industry": "Computer Manufacturing", "sector": "Technology"},
        {"symbol": "BRK/B", "name": "Berkshire Hathaway Inc.", "lastsale": "$500.00", "netchange": "5.00", "pctchange": "9.0%",
         "volume": "1", "marketCap": "", "sector": "Finance"},                                  # % disagrees with change: dropped
        {"symbol": "ABR^D", "name": "Arbor Realty 6.375% Series D Preferred Stock", "lastsale": "$20"},
        {"symbol": "XYZW", "name": "XYZ Corp Warrants", "lastsale": "$0.10"}]}}
    rows = usuniverse.parse_screener(js, "nasdaq")
    assert [r["symbol"] for r in rows] == ["US:AAPL", "US:BRK-B"]
    a, b = rows
    assert (a["chg_pct"], a["market_cap"], a["sector"], a["exchange"], a["ipo_year"]) == (-0.129, 3791234.6, "Information Technology", "Nasdaq", 1980)
    assert b["chg_pct"] is None and b["market_cap"] is None and b["sector"] == "Financials"
    snap = movers.snapshot_row(a)
    assert snap["ret"]["1D"] == -0.129 and snap["ret"]["1W"] is None and snap["above200"] is None and snap["snapshot"]
    mood = movers._mood([snap], "1D")
    assert mood["above200"] is None and mood["with_history"] == 0 and "200-day" not in mood["read"]
    assert len(usuniverse.parse_ndx({"data": {"data": {"rows": [{"symbol": "AAPL", "companyName": "Apple"}]}}})) == 1


if __name__ == "__main__":
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f()
            print("PASS", k)
