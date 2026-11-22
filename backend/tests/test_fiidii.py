"""FII / DII and CFTC positions (offline):  python tests/test_fiidii.py"""
import json
import os
import random
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

os.environ["EQL_DEMO"] = "1"
os.environ.setdefault("EQL_DATA_DIR", tempfile.mkdtemp())
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import fiidii, store  # noqa: E402

store.init()


def test_parse_cash_reads_nse_rows():
    text = json.dumps([
        {"category": "DII **", "date": "20-Nov-2026", "buyValue": "11000.5", "sellValue": "9169.86", "netValue": "1830.64"},
        {"category": "FII/FPI *", "date": "20-Nov-2026", "buyValue": "12000", "sellValue": "12962.94", "netValue": "-962.94"},
    ])
    r = fiidii.parse_cash(text)
    assert r["date"] == "2026-11-20"
    assert r["fii"] == {"buy": 12000.0, "sell": 12962.94, "net": -962.94}
    assert r["dii"]["net"] == 1830.64
    assert fiidii.parse_cash("not json") is None and fiidii.parse_cash("[]") is None


PART = """"Participant wise Open Interest (no. of contracts) in Equity Derivatives as on Nov 20, 2026",,,,,,,,,,,,,,
Client Type,Future Index Long,Future Index Short,Future Stock Long,Future Stock Short,Option Index Call Long,Option Index Put Long,Option Index Call Short,Option Index Put Short,Option Stock Call Long,Option Stock Put Long,Option Stock Call Short,Option Stock Put Short,Total Long Contracts,Total Short Contracts
Client,"2,00,000",90000,3000000,1000000,500000,400000,600000,600000,100,100,100,100,0,0
DII,80000,12000,100000,2300000,0,10000,0,0,0,0,0,0,0,0
FII,102273,193782,2000000,300000,250000,300000,200000,100000,0,0,0,0,0,0
Pro,40000,90491,200000,100000,300000,200000,250000,210000,0,0,0,0,0,0
TOTAL,422273,386273,5300000,3700000,1050000,910000,1050000,910000,0,0,0,0,0,0
"""


def test_parse_participant_and_long_share():
    p = fiidii.parse_participant(PART)
    assert set(p) == {"Client", "DII", "FII", "Pro"}                    # the TOTAL row is not a participant
    assert p["Client"]["fut_idx_long"] == 200000.0                       # Indian-grouped commas read correctly
    d = fiidii.derived(p)
    assert d["FII"]["fut_idx_net"] == 102273 - 193782
    assert d["FII"]["fut_idx_share"] == round(100 * 102273 / (102273 + 193782), 1)
    assert d["FII"]["idx_put_net"] == 200000
    assert fiidii.parse_participant("no header here") == {}


def test_every_contract_has_two_sides():
    d = fiidii.derived(fiidii.parse_participant(PART))
    assert sum(v["idx_call_net"] for v in d.values()) == 0
    assert sum(v["idx_put_net"] for v in d.values()) == 0


COT = """Traders in Financial Futures - Futures Only Positions as of November 17, 2026
-----------------------------------------------------------------------------------------------
E-MINI S&P 500 - CHICAGO MERCANTILE EXCHANGE
CFTC Code #13874A                                            Open Interest is 2,000,000
Positions
   160,000    900,000     12,000    910,869    240,000     55,000    200,000    367,212     40,000    160,000    100,000     20,000    140,000    120,000
Changes from:       November 10, 2026
"""


def test_parse_cot_picks_the_right_columns():
    r = fiidii.parse_cot(COT)
    assert r["date"] == "2026-11-17"
    m = r["13874A"]
    assert m["oi"] == 2000000
    assert m["dealer"] == {"long": 160000, "short": 900000}           # spread columns (3rd, 6th, 9th) skipped
    assert m["asset_mgr"] == {"long": 910869, "short": 240000}
    assert m["lev_funds"] == {"long": 200000, "short": 367212}
    assert m["nonrep"] == {"long": 140000, "short": 120000}
    assert "209742" not in r                                            # Nasdaq block absent: nothing invented


def test_entry_waits_until_the_figures_are_public():
    days = [date(2026, 11, 16) + timedelta(days=k) for k in range(10)]
    pos = {d.isoformat(): i for i, d in enumerate(x for x in days if x.weekday() < 5)}
    i = lambda s: [k for k, v in pos.items() if v == s][0]
    assert i(fiidii.entry_index("2026-11-20", pos, 1)) == "2026-11-23"    # Friday evening figures -> Monday close
    assert i(fiidii.entry_index("2026-11-17", pos, 4)) == "2026-11-23"    # Tuesday COT, Friday release -> Monday
    assert i(fiidii.entry_index("2026-11-18", pos, 1)) == "2026-11-19"


def _series(n, seed=3):
    rnd = random.Random(seed)
    d0 = date(2020, 1, 6)
    days = [d0 + timedelta(days=k) for k in range(int(n * 1.5)) if (d0 + timedelta(days=k)).weekday() < 5][:n]
    closes, px = {}, 100.0
    for d in days:
        px *= 1 + rnd.gauss(0.0003, 0.01)
        closes[d.isoformat()] = px
    series = [(d.isoformat(), rnd.gauss(0, 1)) for d in days]
    return series, closes


def test_extreme_uses_only_earlier_readings():
    series, closes = _series(600)
    a = fiidii.extreme_test(series, closes, 250, (5,), start_shift=1)
    # changing readings after the last tested day cannot change any earlier decision
    cut = 450
    b = fiidii.extreme_test(series[:cut] + [(d, 99.0) for d, _ in series[cut:]], closes, 250, (5,), start_shift=1)
    c = fiidii.extreme_test(series[:cut], closes, 250, (5,), start_shift=1)
    assert a["5"]["base_n"] == b["5"]["base_n"]
    assert b["5"]["low"]["n"] == c["5"]["low"]["n"]                      # 99s are never "low"
    assert b["5"]["high"]["n"] >= c["5"]["high"]["n"]


def test_gap_keeps_events_apart_and_verdict_needs_ten():
    series, closes = _series(400)
    series = series[:250] + [(d, -50.0) for d, _ in series[250:262]] + series[262:]   # 12 extreme days in a row
    g5 = fiidii.extreme_test(series, closes, 250, (5,), start_shift=1, gap=5)
    g1 = fiidii.extreme_test(series, closes, 250, (5,), start_shift=1, gap=1)
    assert g1["5"]["low"]["n"] > g5["5"]["low"]["n"]
    assert g1["5"]["low"]["n"] - g5["5"]["low"]["n"] >= 12 - 3          # a 12-day run counts at most 3 times 5 apart
    few = g5["5"]["low"]
    if few["n"] < 10:
        assert few["verdict"] == "too_few" and "up_pct" not in few


def test_wilson_range():
    lo, hi = fiidii.wilson(22, 32)
    assert 0.54 < lo < 0.56 and 0.79 < hi < 0.81
    assert fiidii.wilson(0, 0) == (0.0, 1.0)


def test_payloads_in_demo():
    fiidii.demo_fill()
    d = fiidii.india(fetch=False)
    assert len(d["cash"]) == min(d["saved_days"], 260) and d["cash"][-1]["date"] == d["latest"]["date"]
    assert set(d["positions"]["now"]) == {"FII", "DII", "Pro", "Client"}
    u = fiidii.us()
    m = u["markets"]["13874A"]
    assert m["latest"]["asset_mgr"]["net"] == m["latest"]["asset_mgr"]["long"] - m["latest"]["asset_mgr"]["short"]
    assert all(1 <= v <= 100 for v in m["percentile_3y"].values())
    assert "not_included" in u


# ---------------------------------------------------------------- NSDL / CDSL / SEBI pages and holdings
FIX = Path(__file__).parent / "fixtures"


def test_nsdl_daily_reads_equity_and_checks_every_row():
    from app import fpi
    days, bad = fpi.parse_nsdl_daily((FIX / "nsdl_daily.html").read_text())
    assert set(days) == {"2024-12-02", "2024-12-03"}                       # 04-Dec fails 100 - 50 = 70 and is dropped
    assert bad == 1
    d = days["2024-12-02"]
    assert d["exch"] == {"buy": 16983.42, "sell": 19982.44, "net": -2999.02}  # brackets = negative
    assert d["primary"]["net"] == 2008.7 and d["sub"]["net"] == -990.32
    assert "2024-12-01" not in days                                         # derivative table's date not read as equity


def test_sector_report_columns_and_total_check():
    from app import fpi
    html = (FIX / "fpi_sectors.html").read_text()
    r = fpi.parse_sectors(html)
    assert r["end"] == "2025-07-31" and r["net_period"] == ["2025-07-16", "2025-07-31"] and r["prev_period"] == ["2025-07-01", "2025-07-15"]
    auto = r["sectors"][0]
    assert auto == {"name": "Automobile and Auto Components", "auc_start": 509003.0, "net_prev": -1159.0, "net": -2425.0, "auc": 501618.0}
    assert len(r["sectors"]) == 3 and r["total"]["net"] == -2425 - 300 + 2500
    broken = html.replace(">-2,425<", ">-9,425<", 1)                       # a sector no longer adds up to the Grand Total
    assert fpi.parse_sectors(broken) == {}


def test_sebi_mutual_funds_days_and_years():
    from app import fpi
    days, periods = fpi.parse_sebi_mf((FIX / "sebi_mf.html").read_text())
    assert days == {"2026-11-03": {"buy": 12500.4, "sell": 10200.1, "net": 2300.3}, "2026-11-04": {"buy": 9000.0, "sell": 9800.0, "net": -800.0}}
    assert [p["period"] for p in periods] == ["April 2005-Mar 2006", "April 2002-Mar 2003"]
    assert periods[1]["net"] == -2066.7


def test_numbers():
    from app import fpi
    assert fpi.num("5,09,003") == 509003 and fpi.num("(2,999.02)") == -2999.02 and fpi.num("-1,159") == -1159
    assert fpi.num("") is None and fpi.num("-") is None and fpi.num("abc") is None


def test_holding_change_from_shareholding_table():
    from app import instholdings
    c = {"tables": {"shareholding_quarterly": {"columns": ["Mar 2026", "Jun 2026", "Sep 2026"],
                                               "rows": {"Promoters": [50, 50, 50], "FIIs": [20.0, 21.5, 20.25], "DIIs": [10.0, None, 12.0]}}}}
    r = instholdings.stock_change(c)
    assert r["quarter"] == "Sep 2026" and r["prev_quarter"] == "Jun 2026"
    assert r["fii"] == 20.25 and r["fii_chg"] == -1.25
    assert r["dii_chg"] is None                                             # no previous figure: no change claimed
    assert instholdings.stock_change({"tables": {}}) is None


def test_fpi_payload_in_demo():
    from app import fpi
    fpi.demo_fill()
    p = fpi.payload()
    m = p["nsdl"]["months"][-1]
    assert m["exch"] == round(sum(r["net"] for r in p["nsdl"]["rows"] if r["date"][:7] == m["month"]), 2)
    s = p["sectors"]
    assert abs(sum(x["net"] for x in s["sectors"]) - s["total"]["net"]) < 1
    assert all(len(x["hist"]) == len(s["periods"]) for x in s["sectors"])


if __name__ == "__main__":
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f()
            print("PASS", k)
