"""IPO research (offline):  python tests/test_ipo.py

fixtures/ipo/ holds NSE's and SEBI's real answers saved by the app on 27 Nov 2026 (open, upcoming and past issues,
one SME issue's details, SEBI's draft offer documents page).
"""
from datetime import date
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ["EQL_DEMO"] = "1"
os.environ.setdefault("EQL_DATA_DIR", tempfile.mkdtemp())
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import ipo, store  # noqa: E402

store.init()
FX = Path(__file__).parent / "fixtures" / "ipo"
J = lambda name: json.loads((FX / name).read_text(encoding="utf-8"))   # noqa: E731
NO_PRICES = lambda sym: (_ for _ in ()).throw(RuntimeError("offline"))   # noqa: E731


def test_price_band():
    assert ipo.price_band("Rs.95 to Rs.100") == (95.0, 100.0)
    assert ipo.price_band("Rs 1,050 - 1,108") == (1050.0, 1108.0)
    assert ipo.price_band("Rs. 130 to Rs. 142 per equity share") == (130.0, 142.0)
    assert ipo.price_band("   136") == (136.0, 136.0)
    assert ipo.price_band("100 to 90") == (None, None)            # backwards range: not trusted
    assert ipo.price_band("TBA") == (None, None) and ipo.price_band(None) == (None, None)


def test_times_check():
    assert ipo.check_times(1000, 2500, 2.5) == (2.5, "NSE figure, agrees with bids ÷ shares offered")
    assert ipo.check_times(1000, 2500, None)[0] == 2.5
    t, how = ipo.check_times(1000, 2500, 9.0)
    assert t is None and "left out" in how and "2.50x" in how
    assert ipo.check_times(0, 282000, 0.0) == (None, "NSE does not publish the shares reserved for this category")
    assert ipo.check_times(None, None, 3.0)[0] is None


def test_real_open_issues():
    rows = [ipo.issue(r) for r in ipo.rows_of(J("nse_current.json"))]
    by = {x["symbol"]: x for x in rows}
    s = by["SHREESIDHI"]
    assert s["sme"] and (s["band_low"], s["band_high"]) == (130.0, 142.0) and s["times"] == 1.24
    assert s["size_cr"] == 93.66                                   # 65,96,000 shares (= shares offered) × ₹142
    f = by["FOODLINK"]                                              # mainboard, NSE writes 1.0474048E7
    assert not f["sme"] and f["times"] == 0.87 and f["size_cr"] == 200.05
    a = by["AIRPRO"]                                                # fixed price, no bids yet
    assert a["sme"] and a["final_price"] == 99.0 and a["times"] is None and a["times_check"] == "not published yet"
    rep = ipo.field_report(ipo.rows_of(J("nse_current.json")), ipo.SOURCES["current"][3])
    assert rep["missing"] == []


def test_real_upcoming_and_past():
    up = {x["symbol"]: x for x in (ipo.issue(r) for r in J("nse_upcoming.json"))}
    assert not up["MATANGI"]["sme"] and up["AJPACK"]["sme"] and up["MONOMARK"]["start"] == "2026-12-02"
    assert up["MATANGI"]["size_cr"] is None                         # no shares-offered figure to confirm the unit
    past_rows = J("nse_past.json")
    past = [x for x in (ipo.issue(r) for r in past_rows) if x]
    assert len(past) < len(past_rows)                               # bonds, InvITs and REITs dropped
    m = next(x for x in past if x["symbol"] == "MAHACOAL")
    assert (m["band_low"], m["band_high"], m["final_price"], m["listing"]) == (129.0, 136.0, 136.0, "2026-11-27")
    r = next(x for x in past if x["symbol"] == "RUNWALENTR")       # NSE's 'issue price' outside its own range
    assert r["final_price"] is None and "outside" in r["final_note"]
    listed = ipo.recently_listed(past, date(2026, 11, 27), prices=NO_PRICES)
    syms = {x["symbol"] for x in listed}
    assert "MAHACOAL" in syms and "11MGEL29" not in syms           # 2019 issue re-listed in 2026: not an IPO listing
    assert all(x["perf"] is None for x in listed)
    assert next(x for x in listed if x["symbol"] == "MAHACOAL")["perf_note"] == "daily prices not available for this symbol"


def test_real_issue_detail():
    d = ipo.parse_detail(J("nse_detail_SHREESIDHI.json"))
    assert (d["band_low"], d["band_high"], d["lot"], d["lot_value"]) == (130.0, 142.0, 1000.0, 142000)
    assert d["issue_shares"] == 6596000 and d["size_cr"] == 93.66
    c = d["composition"]
    assert c["ok"] and c["fresh_pct"] == 100.0 and c["market_maker"] == 330000 and c["ofs"] is None
    assert d["times"] == 1.24 and d["total_bids"] == 8198000 and d["applications"] == 2730
    cats = d["categories"]
    assert cats["adds_up"]                                          # 2.82 L + 29 L + 50.16 L = 81.98 L
    main = [r for r in cats["rows"] if r["level"] == 0 and not r["total"]]
    assert [r["sr"] for r in main] == ["1", "2", "3"] and main[2]["applications"] == 2508
    assert all(r["times"] is None for r in cats["rows"])            # NSE reserves 0 shares per category for this SME issue
    assert not any(r["category"] == "Category" for r in cats["rows"])   # header row skipped
    dm = d["demand"]
    assert dm["ok"] and dm["top_price"] == 142 and dm["at_top"] == 80.6 and len(dm["levels"]) == 8
    assert {x["title"] for x in d["docs"]} >= {"Red Herring Prospectus", "Ratios / Basis of Issue Price"}
    keys = {f["k"] for f in d["facts"]}
    assert "Lot Size" in keys and "Book Running Lead Managers" in keys and None not in keys


def test_checks_reject_bad_numbers():
    c = ipo.composition("fresh issue of 10,00,000 Equity Shares and an offer for sale of 5,00,000 Equity Shares", 15_00_000)
    assert c["ok"] and c["fresh_pct"] == 66.7 and c["ofs"] == 500000
    bad = ipo.composition("fresh issue of 10,00,000 Equity Shares and an offer for sale of 5,00,000 Equity Shares", 20_00_000)
    assert not bad["ok"] and "does not match" in bad["note"]
    g = {"graphData": [{"type": "100", "value": "1"}, {"type": "105", "value": "1"}], "TOTAL_BIDS": "500000"}
    assert ipo.demand(g)["ok"] is False                             # 2 lakh at prices vs 5 lakh total
    cats = ipo.categories([], [{"srNo": "1", "category": "QIB", "noOfshareBid": "100"},
                               {"srNo": "2", "category": "Retail", "noOfshareBid": "100"},
                               {"srNo": None, "category": "Total", "noOfshareBid": "300"}])
    assert not cats["adds_up"] and "300" in cats["check"]


def test_real_sebi_drhp():
    rows = ipo.parse_sebi_drhp((FX / "sebi_drhp.html").read_text(encoding="utf-8"))
    assert len(rows) == 25
    first = rows[0]
    assert first["company"] == "NLC India Renewables Limited" and first["kind"] == "DRHP" and first["date"] == "2026-11-25"
    assert first["abridged"].endswith("Prospectus_p.pdf") and " " not in first["abridged"]
    assert rows[2]["company"] == "Chartered Speed Limited" and rows[2]["kind"] == "Addendum"


def test_listing_move_measured_only():
    bars = [{"t": "2026-11-10", "o": 120.0, "h": 135.0, "l": 118.0, "c": 130.0}, {"t": "2026-11-11", "o": 131.0, "h": 132.0, "l": 110.0, "c": 125.0}]
    m = ipo.listing_move(bars, "2026-11-10", 100.0)
    assert (m["open_vs_issue"], m["close_vs_issue"], m["now_vs_issue"], m["high_vs_issue"], m["low_vs_issue"], m["sessions"]) == (20.0, 30.0, 25.0, 35.0, 10.0, 2)
    assert ipo.listing_move(bars, "2026-11-01", 100.0) is None     # first bar 9 days after listing: not this listing
    st = ipo.listed_stats([{"sme": False, "perf": m}, {"sme": False, "perf": dict(m, close_vs_issue=-5.0, now_vs_issue=-1.0)},
                           {"sme": True, "perf": None}])
    assert st["main"] == {"n": 2, "above_listing": 1, "median_listing": 12.5, "above_now": 1, "median_now": 12.0}
    assert st["sme"] == {"n": 0}


def test_demo_page_is_empty_not_invented():
    page = ipo.india()
    assert page["demo"] and page["open"] == [] and page["listed"] == []


# Nasdaq IPO calendar: shape as documented by its public JSON (data.priced / upcoming.upcomingTable / filed / withdrawn).
# Replace with a saved real answer (data/ipo_raw/nasdaq_ipo_YYYY-MM.json) once the app has fetched one.
NQ = {"data": {
    "priced": {"rows": [
        {"dealID": "1-1", "proposedTickerSymbol": "ABCD", "companyName": "Abcd Therapeutics, Inc.", "proposedExchange": "NASDAQ Global",
         "proposedSharePrice": "16.00", "sharesOffered": "10,000,000", "pricedDate": "11/20/2026", "dollarValueOfSharesOffered": "$160,000,000"},
        {"dealID": "1-2", "proposedTickerSymbol": "BADV", "companyName": "Bad Value Corp", "proposedExchange": "NYSE",
         "proposedSharePrice": "10.00", "sharesOffered": "1,000,000", "pricedDate": "11/18/2026", "dollarValueOfSharesOffered": "$99,000,000"}]},
    "upcoming": {"upcomingTable": {"rows": [
        {"dealID": "2-1", "proposedTickerSymbol": "NEWX", "companyName": "Newx Holdings", "proposedExchange": "NASDAQ Capital",
         "proposedSharePrice": "4.00-5.00", "sharesOffered": "2,500,000", "expectedPriceDate": "12/03/2026", "dollarValueOfSharesOffered": "$12,500,000"}]}},
    "filed": {"rows": [{"dealID": "3-1", "proposedTickerSymbol": "FILE", "companyName": "Filer &amp; Co", "filedDate": "11/25/2026",
                        "dollarValueOfSharesOffered": "$100,000,000"}]},
    "withdrawn": {"rows": [{"dealID": "4-1", "proposedTickerSymbol": "GONE", "companyName": "Gone Ltd", "proposedExchange": "NYSE",
                            "sharesOffered": "3,000,000", "filedDate": "06/01/2026", "withdrawDate": "11/10/2026"}]}}}


def test_us_calendar_parse():
    got = ipo.parse_us_month(NQ)
    a, b = got["priced"]
    assert a["symbol"] == "ABCD" and a["final_price"] == 16.0 and a["value_m"] == 160.0 and a["priced"] == "2026-11-20"
    assert b["value_m"] is None and "shares × IPO price" in b["value_note"]       # 1M × $10 ≠ $99M: left out
    u = got["upcoming"][0]
    assert (u["band_low"], u["band_high"], u["final_price"], u["expected"]) == (4.0, 5.0, None, "2026-12-03")
    assert got["filed"][0]["company"] == "Filer & Co" and got["filed"][0]["filed"] == "2026-11-25"
    assert got["withdrawn"][0]["withdrawn"] == "2026-11-10"
    assert ipo.parse_us_month({}) == {"priced": [], "upcoming": [], "filed": [], "withdrawn": []}


def test_us_listing_needs_fresh_series():
    bars = [{"t": "2026-11-21", "o": 18, "h": 20, "l": 17, "c": 19}, {"t": "2026-11-24", "o": 19, "h": 19, "l": 15, "c": 16}]
    m = ipo.us_listing_move(bars, "2026-11-20", 16.0)
    assert m["first_day"] == "2026-11-21" and m["open_vs_issue"] == 12.5 and m["now_vs_issue"] == 0.0
    old = [{"t": "2026-05-01", "o": 1, "h": 1, "l": 1, "c": 1}] + bars
    assert ipo.us_listing_move(old, "2026-11-20", 16.0) == "traded_before"


def test_us_months_window():
    assert ipo._us_months(date(2026, 1, 15)) == ["2025-09", "2025-10", "2025-11", "2025-12", "2026-01", "2026-02"]


if __name__ == "__main__":
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f()
            print("PASS", k)
