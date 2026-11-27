"""Automation and the Home 'Today' strip (offline):  python tests/test_automation.py"""
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

os.environ["EQL_DEMO"] = "1"
os.environ.setdefault("EQL_DATA_DIR", tempfile.mkdtemp())
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import automation, calendars, config, jobs, service, store, today  # noqa: E402

store.init()
at = lambda *a: datetime(*a, tzinfo=calendars.IST)   # noqa: E731


def test_scan_and_ipo_schedule():
    assert automation.scan_due("IN", at(2026, 11, 27, 19, 30), None)            # Friday 19:30
    assert not automation.scan_due("IN", at(2026, 11, 27, 19, 0), None)        # too early
    assert not automation.scan_due("IN", at(2026, 11, 27, 21), "2026-11-27")   # once a day
    assert not automation.scan_due("IN", at(2026, 11, 28, 20), None)           # Saturday
    assert automation.scan_due("US", at(2026, 11, 28, 7, 5), None)             # Saturday morning after Friday's US close
    assert not automation.scan_due("US", at(2026, 11, 30, 7, 5), None)         # Monday: no US session closed since Saturday's run
    assert automation.ipo_due(at(2026, 11, 27, 10), 0, 1000.0)
    assert not automation.ipo_due(at(2026, 11, 27, 10), 1000.0, 1000.0 + 600)  # 10 minutes later: not yet
    assert not automation.ipo_due(at(2026, 11, 27, 20), 0, 1000.0)             # after hours


def test_tick_starts_one_scan_and_waits_for_the_entry_backtest():
    started = []
    real = (service.start_scan, jobs.status, automation._ipo_refresh)
    service.start_scan = lambda market="IN", which="N500", **k: started.append(market)
    automation._ipo_refresh = lambda: None
    demo, config.DEMO = config.DEMO, False
    try:
        jobs.status = lambda n: {"running": n == "entry"}
        assert automation.tick(at(2026, 11, 27, 20), 1.0) == []                 # entry backtest running: no scan
        jobs.status = lambda n: {"running": False}
        assert automation.tick(at(2026, 11, 27, 20), 2.0) == ["scan_in"] and started == ["IN"]
        assert automation.tick(at(2026, 11, 27, 21), 3.0) == []                 # done for today
        automation.set_enabled("scan_in", False)
        assert automation.tick(at(2026, 11, 30, 20), 4.0) == []
        assert automation.settings()["enabled"]["scan_in"] is False
        assert automation.tick(at(2026, 11, 30, 10), 5000.0) == ["ipo"]
    finally:
        service.start_scan, jobs.status, automation._ipo_refresh = real
        config.DEMO = demo


def test_status_lists_every_task():
    ids = [r["id"] for r in automation.status()["tasks"]]
    assert ids == ["news", "premarket", "fiidii", "ipo", "scan_in", "scan_us", "levels", "entry"]


def test_today_uses_saved_data_and_never_invents():
    store.put_company("PREMARKET::CALL::IN::2026-11-27", {"call": "up", "label": "Gap-up likely", "built": "08:58"})
    assert today._premarket("2026-11-27")["label"] == "Gap-up likely" and today._premarket("2026-11-26") is None
    store.put_company("FIIDII::CASH", {"2026-11-25": {"fii": {"net": -100.0}, "dii": {"net": 50.0}},
                                       "2026-11-26": {"fii": {"net": 1234.5}, "dii": {"net": -321.0}}})
    assert today._fiidii() == {"date": "2026-11-26", "fii": 1234.5, "dii": -321.0}
    store.put_company("IPO::current::v2", {"items": [{"symbol": "AAA", "company": "AAA Ltd", "end": "2026-11-27", "times": 1.2, "sme": True},
                                                     {"symbol": "BBB", "company": "BBB Ltd", "end": "2026-11-30", "sme": False}]})
    ip = today._ipos("2026-11-27")
    assert ip["open"] == 2 and ip["open_main"] == 1 and [x["symbol"] for x in ip["closing_today"]] == ["AAA"]
    assert ip["opening_next"] == []
    from app import movers
    rows = [{"symbol": f"S{i}", "date": "2026-11-27", "ret": {"1D": (i % 3) - 1.0}, "above200": i % 2 == 0, "above50": True,
             "new_high": i == 0, "new_low": False, "from_hi": -10, "from_lo": 20} for i in range(9)]
    store.put_company(movers._key("IN"), {"rows": rows})
    b = today._breadth("IN")
    assert (b["advances"], b["declines"], b["unchanged"], b["above200"], b["new_highs"], b["count"]) == (3, 3, 3, 56, 1, 9)
    page = today.get("US")
    assert "premarket" not in page and "breaking" in page


if __name__ == "__main__":
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f()
            print("PASS", k)
