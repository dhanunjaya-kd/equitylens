"""Earnings + economic calendars and logos, on the live sources' raw formats (offline):  python tests/test_calendar.py"""
import os
import sys
import tempfile
from datetime import date
from pathlib import Path

os.environ["EQL_DEMO"] = "1"
os.environ.setdefault("EQL_DATA_DIR", tempfile.mkdtemp())
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import calendars as cal, logos, store  # noqa: E402

store.init()
D = date(2026, 11, 18)


def test_nasdaq_earnings_format():
    j = {"data": {"asOf": "Wed, Nov 18, 2026", "headers": {}, "rows": [
        {"lastYearRptDt": "11/19/2025", "lastYearEPS": "$4.06", "time": "time-after-hours", "symbol": "NVDA", "name": "NVIDIA Corporation",
         "marketCap": "$4,512,000,000,000", "fiscalQuarterEnding": "Oct/2026", "epsForecast": "$1.25", "noOfEsts": "18"},
        {"lastYearRptDt": "N/A", "lastYearEPS": "($0.20)", "time": "time-pre-market", "symbol": "BRK.B", "name": "Loss Co",
         "marketCap": "N/A", "fiscalQuarterEnding": "Sep/2026", "epsForecast": "($0.59)", "noOfEsts": "1"},
        {"time": "time-not-supplied", "symbol": "XYZ", "name": "Reported Inc", "marketCap": "$1,000,000,000",
         "epsForecast": "$1.00", "eps": "$1.10", "surprise": "10.00", "noOfEsts": "3"}]}}
    r = cal.parse_nasdaq_earnings(j, D)
    assert r[0]["symbol"] == "US:NVDA" and r[0]["timing"] == "AMC" and r[0]["eps_estimate"] == 1.25 and r[0]["market_cap"] == 4512000.0
    assert r[1]["symbol"] == "US:BRK-B" and r[1]["eps_estimate"] == -0.59 and r[1]["eps_last_year"] == -0.2 and r[1]["market_cap"] is None
    assert r[1]["timing"] == "BMO" and r[2]["timing"] == "TBD" and r[2]["eps_actual"] == 1.1 and r[2]["surprise_pct"] == 10.0
    assert cal.parse_nasdaq_earnings({"data": {"rows": None}}, D) == [] and cal.parse_nasdaq_earnings({}, D) == []


def test_nse_event_format():
    rows = [{"symbol": "TCS", "company": "Tata Consultancy Services Limited", "purpose": "Financial Results/Dividend",
             "bm_desc": "To consider and approve the financial results for the period ended September 30, 2026 and dividend", "date": "09-Oct-2026"},
            {"symbol": "ITC", "company": "ITC Limited", "purpose": "Bonus", "bm_desc": "Bonus", "date": "20-Nov-2026"},
            {"symbol": "XYZ", "company": "X", "purpose": "Fund Raising", "bm_desc": "To consider raising funds via QIP", "date": "21-11-2026"},
            {"symbol": "", "company": "bad", "purpose": "Results", "date": "21-Nov-2026"},
            {"symbol": "ABC", "company": "bad date", "purpose": "Results", "date": "someday"}]
    r = cal.parse_nse_events(rows)
    assert [x["type"] for x in r] == ["Results", "Bonus", "Fund raising"]
    assert r[0]["date"] == "2026-10-09" and r[2]["date"] == "2026-11-21" and r[1]["detail"] is None


def test_nasdaq_econ_format():
    j = {"data": {"rows": [
        {"gmt": "13:30", "country": "United States", "eventName": "Core CPI (MoM)", "actual": "0.4%", "consensus": "0.3%", "previous": "0.3%",
         "description": "The Core CPI measures..."},
        {"gmt": "All Day", "country": "India", "eventName": "Bank Holiday", "actual": "&nbsp;", "consensus": "&nbsp;", "previous": "&nbsp;"}]}}
    r = cal.parse_nasdaq_econ(j, D)
    assert r[0]["at"] == "2026-11-18T13:30:00+00:00" and r[0]["actual"] == "0.4%" and cal.surprise(r[0]) == "above"
    assert r[1]["at"] is None and r[1]["actual"] is None and r[1]["forecast"] is None


def test_values_and_surprise():
    assert cal.money("($1.05)") == -1.05 and cal.money("$131,271,743,181") == 131271743181 and cal.money("N/A") is None
    assert cal.number("-60.30B") == -60.3 and cal.number("221K") == 221
    assert cal.surprise({"actual": "3.0%", "forecast": "3.0%"}) == "in line"
    assert cal.surprise({"actual": "2.8%", "forecast": "3.0%"}) == "below" and cal.surprise({"actual": None, "forecast": "1"}) is None


def test_official_schedules_and_times():
    ev = cal.official_events()
    cpi = [e for e in ev if e["country"] == "India" and "CPI" in e["event"]]
    assert all(date.fromisoformat(e["date"]).weekday() < 5 for e in cpi)
    dec = [e for e in cpi if e["date"].startswith("2026-12")][0]
    assert dec["date"] == "2026-12-14" and dec["at"] == "2026-12-14T10:30:00+00:00"          # 12 Dec is a Saturday; 4 PM IST
    fomc = {e["date"]: e["at"] for e in ev if "FOMC" in e["event"]}
    assert fomc["2026-12-09"] == "2026-12-09T19:00:00+00:00" and fomc["2027-03-17"] == "2027-03-17T18:00:00+00:00"  # EST vs EDT
    rbi = [e["date"] for e in ev if "RBI" in e["event"]]
    assert "2026-12-04" in rbi and "2027-02-05" in rbi
    assert any(e["date"] == "2026-11-30" and "GDP" in e["event"] for e in ev)
    assert any(e["date"] == "2026-11-16" and "WPI" in e["event"] for e in ev)


def test_guide_importance():
    assert cal.guide("Fed Interest Rate Decision")["importance"] == 3 and cal.guide("Nonfarm Payrolls")["topic"] == "jobs"
    assert cal.guide("CPI Inflation (YoY)")["importance"] == 3 and cal.guide("Something odd")["importance"] == 1


def test_economy_merges_official_without_duplicates():
    c = cal.economy("IN", date(2026, 11, 9), 14)
    names = [(e["date"], e["event"]) for e in c["events"]]
    assert ("2026-11-12", "CPI Inflation (YoY)") in names and ("2026-11-16", "WPI Inflation (YoY)") in names
    assert len(names) == len(set(names)) and all(e["country"] == "India" for e in c["events"])
    assert c["next_big"] and c["next_big"] == sorted(c["next_big"], key=lambda e: e["at"])


def test_earnings_both_markets():
    for mk in ("US", "IN"):
        e = cal.earnings(mk, date(2026, 11, 9), 7)
        assert e["rows"] and all("2026-11-09" <= r["date"] <= "2026-11-15" for r in e["rows"])
        assert all(r["market"] == mk for r in e["rows"]) and e["source"]
    us = cal.earnings("US", date(2026, 11, 9), 7)["rows"]
    assert any(r["symbol"] == "US:SMLL" and not r["in_index"] for r in us)


def test_logo_monogram():
    assert logos.initials("TCS", "Tata Consultancy Services Limited") == "TC"
    assert logos.initials("US:AAPL", "Apple Inc.") == "AP" and logos.initials("US:X", "") == "X"
    data, media = logos.get("US:AAPL", "Apple Inc.")
    assert media == "image/svg+xml" and b"<svg" in data and b"AP" in data


if __name__ == "__main__":
    bad = 0
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            try:
                f(); print("PASS", n)
            except Exception as e:  # noqa: BLE001
                bad += 1; print("FAIL", n, repr(e))
    sys.exit(1 if bad else 0)
