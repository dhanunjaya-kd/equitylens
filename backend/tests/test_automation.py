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
    assert not automation.scan_due("IN", at(2026, 11, 27, 19, 0), "2026-11-26")  # before today's slot, Thursday's done
    assert automation.scan_due("IN", at(2026, 11, 27, 19, 0), "2026-11-25")      # Thursday's missed: catch up on opening
    assert not automation.scan_due("IN", at(2026, 11, 27, 21), "2026-11-27")    # once per slot
    assert not automation.scan_due("IN", at(2026, 11, 28, 20), "2026-11-27")    # Saturday: Friday's slot already done
    assert automation.scan_due("US", at(2026, 11, 28, 7, 5), "2026-11-27")      # Saturday morning after Friday's US close
    assert not automation.scan_due("US", at(2026, 11, 30, 7, 5), "2026-11-28")  # Monday: no US close since Saturday's run
    assert automation.ipo_due(at(2026, 11, 27, 10), 0, 1000.0)
    assert not automation.ipo_due(at(2026, 11, 27, 10), 1000.0, 1000.0 + 600)  # 10 minutes later: not yet
    assert not automation.ipo_due(at(2026, 11, 27, 20), 900.0, 1000.0 + 6000)  # after hours


def _fake(due_now: set, running: set, started: list):
    """Replace the real scans with stand-ins: which are due / running, and record starts."""
    real = (automation._due, automation._state, automation._start)
    automation._due = lambda job, now, ts, s: (job in due_now, "")
    automation._state = lambda job: {"running": job in running, "done": None, "total": None, "started": None}
    def start(job, now, ts, s):
        started.append(job)
        if job in automation.HEAVY:
            running.add(job)
    automation._start = start
    return real


def test_auto_runs_what_is_due_heavy_one_at_a_time():
    store.put_company(automation.KEY, {"v": 3, "mode": "auto", "enabled": {}, "last": {}, "requested": []})
    started, running = [], set()
    real = _fake({"prices_in", "classify_in", "ipo", "scan_in", "prices_us"}, running, started)
    demo, config.DEMO = config.DEMO, False
    try:
        assert automation.tick(at(2026, 11, 27, 20), 1.0) == ["prices_in", "classify_in", "ipo"]   # one heavy + the light ones
        assert automation.tick(at(2026, 11, 27, 20, 1), 2.0) == ["classify_in", "ipo"]             # heavy queue waits
        running.clear()
        assert automation.tick(at(2026, 11, 27, 20, 2), 3.0)[0] == "prices_in"                     # (stand-in stays due)
        automation.set_enabled("prices_in", False)
        running.clear()
        assert automation.tick(at(2026, 11, 27, 20, 3), 4.0)[0] == "classify_in" and "scan_in" in running
    finally:
        automation._due, automation._state, automation._start = real
        config.DEMO = demo
        automation.set_enabled("prices_in", True)


def test_manual_runs_only_what_is_asked():
    store.put_company(automation.KEY, {"v": 3, "mode": "manual", "enabled": {}, "last": {}, "requested": []})
    started, running = [], set()
    real = _fake(set(automation.IDS), running, started)
    demo, config.DEMO = config.DEMO, False
    try:
        assert automation.tick(at(2026, 11, 27, 20), 1.0) == []                 # everything due, nothing asked
        assert not automation.allowed("prices_in")                            # pages don't start loads either
        automation.run_now("ipo_hist_in")
        assert started == ["ipo_hist_in"]
        automation.run_all()                                                  # all asked: light ones start, heavy ones queue
        assert "ipo" in started and "us_list" in started and "prices_in" not in started
        q = [r["id"] for r in automation.status()["tasks"] if r["queued"]]
        assert "prices_in" in q and "scan_us" in q
        running.clear()
        automation.tick(at(2026, 11, 27, 21), 2.0)
        assert "prices_in" in started                                         # next in the queue
    finally:
        automation._due, automation._state, automation._start = real
        config.DEMO = demo
        automation.set_mode("auto")


def test_broker_reminder_once_a_weekday_morning_for_ended_logins():
    from app import alerts, brokers
    sent = []
    real = (alerts.send, brokers.status)
    alerts.send = lambda text, s=None: sent.append(text)
    brokers.status = lambda base: [{"name": "Zerodha", "token_time": 1.0, "valid_until": "2026-11-27T06:00+05:30", "error": None},
                                   {"name": "Fyers", "token_time": 1.0, "valid_until": None, "error": None}]
    try:
        s = {"last": {}}
        assert automation.broker_reminder(at(2026, 11, 27, 8, 0), s) is None        # too early
        assert automation.broker_reminder(at(2026, 11, 27, 9, 0), s) == "Zerodha"   # ended at 06:00; Fyers has no stated end
        assert automation.broker_reminder(at(2026, 11, 27, 9, 30), s) is None       # once a day
        assert automation.broker_reminder(at(2026, 11, 28, 9, 0), {"last": {}}) is None   # Saturday
        assert len(sent) == 1 and "Zerodha" in sent[0]
    finally:
        alerts.send, brokers.status = real


def test_old_settings_turn_the_us_scan_on_once():
    store.put_company(automation.KEY, {"enabled": {"scan_in": True, "scan_us": False, "ipo": True}, "last": {}})
    assert automation.settings()["enabled"]["scan_us"] is True                   # v1 default saved as a choice
    automation.set_enabled("scan_us", False)
    assert automation.settings()["enabled"]["scan_us"] is False                  # a real choice after that stays


def test_status_lists_every_task():
    st = automation.status()
    assert [r["id"] for r in st["tasks"]] == automation.IDS
    assert [r["id"] for r in st["always"]] == ["news", "premarket", "fiidii"]
    assert set(st["overall"]) >= {"running", "queued", "pct", "names"} and st["mode"] in ("auto", "manual")


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
    assert "premarket" not in page and "breaking" in page and "results" in page


def test_today_us_parts_from_saved_data():
    assert today._us_ipos("2026-11-27") is None and today._us_bigmoney() is None      # nothing saved: no tile
    store.put_company("IPO::US::2026-11", {"items": {
        "upcoming": [{"deal": "1", "symbol": "NEWX", "company": "Newx", "expected": "2026-12-02", "value_m": 12.5},
                     {"deal": "2", "symbol": "LATE", "company": "Late", "expected": "2026-12-20"},
                     {"deal": "3", "symbol": "OLD", "company": "Old", "expected": "2026-11-20"}],
        "priced": [{"deal": "4", "symbol": "ABCD", "company": "Abcd", "priced": "2026-11-20", "final_price": 16.0}]}})
    u = today._us_ipos("2026-11-27")
    assert u["this_week"] == 1 and u["upcoming"] == 2 and u["next"][0]["symbol"] == "NEWX" and u["last"][0]["price"] == 16.0
    from app import fiidii
    t = fiidii._tuesdays(2)
    for k, (al, as_) in zip(t[::-1], ((600, 400), (700, 300))):
        store.put_company(f"COT::{k.isoformat()}", {"w": {"date": k.isoformat(), "13874A": {"oi": 1000, "asset_mgr": {"long": al, "short": as_},
                          "lev_funds": {"long": 100, "short": 300}, "dealer": {"long": 0, "short": 0}, "other": {"long": 0, "short": 0}, "nonrep": {"long": 0, "short": 0}}}})
    b = today._us_bigmoney()
    assert b["asset_mgr"] == {"net_pct": 40.0, "change": 20.0} and b["lev_funds"]["net_pct"] == -20.0


if __name__ == "__main__":
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f()
            print("PASS", k)
