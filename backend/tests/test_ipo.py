"""IPO research (offline):  python tests/test_ipo.py

The rows below are written in the shapes the readers accept. Once the app has saved NSE's and SEBI's real
answers on a live run (data/ipo_raw/), those saved copies become fixtures here, as for every other source.
"""
from datetime import date
import os
import sys
import tempfile
from pathlib import Path

os.environ["EQL_DEMO"] = "1"
os.environ.setdefault("EQL_DATA_DIR", tempfile.mkdtemp())
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import ipo, store  # noqa: E402

store.init()


def test_price_band():
    assert ipo.price_band("Rs.95 to Rs.100") == (95.0, 100.0)
    assert ipo.price_band("Rs 1,050 - 1,108") == (1050.0, 1108.0)
    assert ipo.price_band("₹ 250 per equity share") == (250.0, 250.0)
    assert ipo.price_band(312) == (312.0, 312.0)
    assert ipo.price_band("100 to 90") == (None, None)            # backwards range: not trusted
    assert ipo.price_band("TBA") == (None, None)
    assert ipo.price_band(None) == (None, None)


def test_times_check():
    assert ipo.check_times(1000, 2500, 2.5) == (2.5, "NSE figure, agrees with bids ÷ shares offered")
    assert ipo.check_times(1000, 2500, None)[0] == 2.5                # worked out from NSE's two figures
    t, how = ipo.check_times(1000, 2500, 9.0)                        # disagreement -> left out, with the reason
    assert t is None and "left out" in how and "2.50x" in how
    assert ipo.check_times(None, None, 3.0)[0] is None                # nothing to check it against -> not shown
    assert ipo.check_times(None, None, None) == (None, "not published yet")


def test_issue_row_any_field_names():
    a = ipo.issue({"symbol": "abc", "companyName": "ABC Limited", "series": "EQ", "issueStartDate": "24-Nov-2026",
                   "issueEndDate": "26-Nov-2026", "issuePrice": "Rs.95 to Rs.100", "issueSize": "12500000",
                   "noOfSharesOffered": "1,00,000", "noOfsharesBid": "350000", "noOfTime": "3.50"})
    assert a["symbol"] == "ABC" and a["start"] == "2026-11-24" and a["end"] == "2026-11-26"
    assert (a["band_low"], a["band_high"], a["final_price"]) == (95.0, 100.0, None)
    assert a["times"] == 3.5 and a["size_text"] == "12500000" and not a["sme"]
    b = ipo.issue({"Symbol": "XYZ", "company": "XYZ &amp; Sons Ltd", "Series": "SM", "issue_price": None, "priceRange": "120"})
    assert b["company"] == "XYZ & Sons Ltd" and b["sme"] and b["final_price"] == 120.0 and b["times"] is None
    assert ipo.issue({"symbol": "NONAME"}) is None                    # no company name -> row dropped
    c = ipo.issue({"companyName": "Small Co", "securityType": "SME IPO"})
    assert c["sme"] and c["symbol"] is None


def test_rows_and_field_report():
    assert len(ipo.rows_of({"data": [{"a": 1}, "x"]})) == 1 and ipo.rows_of("x") == []
    rows = [{"symbol": "A", "companyName": "A Ltd"}, {"symbol": "B", "companyName": "B Ltd", "issueStartDate": "1-Dec-2026"}]
    rep = ipo.field_report(rows, ["symbol", "company", "start", "price"])
    assert rep["found"] == ["symbol", "company", "start"] and rep["missing"] == ["price"]
    assert ipo.field_report([], ["symbol"])["missing"] == []          # an empty list is not a format change


def test_categories_and_facts():
    js = {"dataList": [
        {"srNo": "1", "category": "Qualified Institutional Buyers(QIBs)", "noOfShareOffered": "200000", "noOfSharesBid": "5000000", "noOfTotalMeant": "25.00"},
        {"srNo": "2", "category": "Retail Individual Investors(RIIs)", "noOfShareOffered": "350000", "noOfSharesBid": "700000", "noOfTotalMeant": "9.99"},
        {"srNo": "3", "category": "Total", "noOfShareOffered": "550000", "noOfSharesBid": "5700000", "noOfTotalMeant": "10.36"}],
        "updateTime": "26-Nov-2026 17:00:00"}
    rows = ipo.categories(js)
    assert rows[0]["times"] == 25.0
    assert rows[1]["times"] is None and "left out" in rows[1]["check"]    # 700000/350000 = 2.00x, not 9.99x
    assert rows[2]["total"] and rows[2]["times"] == 10.36
    pairs, docs = ipo.facts({"issueInfo": {"dataList": [{"title": "Lot Size", "value": "150"},
                                                         {"title": "Lot Size", "value": "150"},
                                                         {"title": "RHP", "value": "https://x.nseindia.com/abc_RHP.pdf"}]},
                             "other": {"fileName": "https://x.nseindia.com/abc_anchor.pdf"}})
    assert pairs == [{"k": "Lot Size", "v": "150"}]
    assert {d["url"] for d in docs} == {"https://x.nseindia.com/abc_RHP.pdf", "https://x.nseindia.com/abc_anchor.pdf"}


def test_sebi_drhp_table():
    page = """<table><tr><th>Date</th><th>Title</th></tr>
    <tr><td>Nov 25, 2026</td><td><a href="https://www.sebi.gov.in/filings/public-issues/nov-2026/abc-limited_1.html" title="x">ABC Limited - DRHP</a></td></tr>
    <tr><td>Nov 24, 2026</td><td><a href="/filings/public-issues/nov-2026/xyz_2.html">XYZ Foods Limited - SME Draft Red Herring Prospectus</a></td></tr>
    <tr><td>not a date</td><td><a href="/q">Junk</a></td></tr></table>"""
    rows = ipo.parse_sebi_drhp(page)
    assert [r["company"] for r in rows] == ["ABC Limited", "XYZ Foods Limited"]
    assert rows[1]["url"].startswith("https://www.sebi.gov.in/") and rows[1]["sme"] and not rows[0]["sme"]


def test_listing_move_measured_only():
    bars = [{"t": "2026-11-10", "o": 120.0, "c": 130.0}, {"t": "2026-11-11", "o": 131.0, "c": 125.0}]
    m = ipo.listing_move(bars, "2026-11-10", 100.0)
    assert (m["open_vs_issue"], m["close_vs_issue"], m["now_vs_issue"], m["sessions"]) == (20.0, 30.0, 25.0, 2)
    assert ipo.listing_move(bars, "2026-11-01", 100.0) is None          # first bar 9 days after listing: not this listing
    assert ipo.listing_move([], "2026-11-10", 100.0) is None


def test_recently_listed_needs_final_price():
    past = [{"symbol": "AAA", "listing": "2026-11-20", "final_price": None},
            {"symbol": None, "listing": "2026-11-19", "final_price": 50.0},
            {"symbol": "OLD", "listing": "2025-01-01", "final_price": 10.0}]
    out = ipo.recently_listed(past, today=date(2026, 11, 27))
    assert [x["symbol"] for x in out] == ["AAA", None]                  # OLD is outside the 120-day window
    assert "price range" in out[0]["perf_note"] and out[1]["perf_note"] == "no NSE symbol"
    assert all(x["perf"] is None for x in out)


def test_demo_page_is_empty_not_invented():
    page = ipo.india()
    assert page["demo"] and page["open"] == [] and page["listed"] == []


if __name__ == "__main__":
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f()
            print("PASS", k)
