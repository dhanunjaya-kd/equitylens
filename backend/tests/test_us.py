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


if __name__ == "__main__":
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f()
            print("PASS", k)
