"""Automation: every background task in one place (Settings -> Automation), plus the ones added here:

  * Top Picks scan, India: every weekday evening from 19:30 IST (after the day's prices and filings are out)
  * Top Picks scan, US:    Tuesday-Saturday from 07:00 IST (after the US close); on by default since settings v2
                           (it was off before, which left the US Top Picks list nearly empty)
  * IPO lists:             every 15 minutes, weekdays 09:00-17:30 IST, so the Home page and the IPO page open instantly

A scan reuses a company's saved financials when they are under SCAN_REUSE_HOURS old, so each nightly scan only
downloads what is stale (screener.in is still asked one company at a time with the usual pause).
Nothing here runs in demo mode. The scans never start while an entry backtest is running (both use screener.in).
"""
from __future__ import annotations

import threading
import time
from datetime import datetime
from typing import Optional

from . import calendars, config, store

IST = calendars.IST
KEY = "AUTO::tasks"
TOGGLES = {"scan_in": True, "scan_us": True, "ipo": True}
VERSION = 2
LOOP_S = 5 * 60
_started = [False]


def settings() -> dict:
    hit = store.get_company(KEY)
    s = hit[1] if hit else {}
    out = {"v": VERSION, "enabled": {k: s.get("enabled", {}).get(k, v) for k, v in TOGGLES.items()}, "last": s.get("last", {})}
    if hit and s.get("v", 1) < 2:          # v1 saved the old default (US scan off) as if it were a choice: turn it on once
        out["enabled"]["scan_us"] = True
        _save(out)
    return out


def _save(s: dict) -> None:
    store.put_company(KEY, s)


def set_enabled(task: str, on: bool) -> dict:
    from . import jobs
    if task in jobs.JOBS:
        jobs.set_auto(task, on)
        return status()
    if task not in TOGGLES:
        raise KeyError(task)
    s = settings()
    s["enabled"][task] = bool(on)
    _save(s)
    return status()


# ------------------------------------------------------------------ when each task is due
def scan_due(market: str, now: datetime, last_day: Optional[str]) -> bool:
    day = now.date().isoformat()
    if last_day == day:
        return False
    if market == "IN":
        return now.weekday() < 5 and (now.hour, now.minute) >= (19, 30)
    return now.weekday() in (1, 2, 3, 4, 5) and 7 <= now.hour < 12      # Tue-Sat morning, after the US close


def ipo_due(now: datetime, last_ts: float, ts: float) -> bool:
    return now.weekday() < 5 and (9, 0) <= (now.hour, now.minute) <= (17, 30) and ts - (last_ts or 0) >= 15 * 60


def tick(now: Optional[datetime] = None, ts: Optional[float] = None) -> list[str]:
    """Start whatever is due. Returns what was started (for the tests)."""
    from . import jobs, service
    now = now or datetime.now(IST)
    ts = ts or time.time()
    if config.DEMO:
        return []
    s = settings()
    started = []
    if s["enabled"]["ipo"] and ipo_due(now, s["last"].get("ipo_ts", 0), ts):
        s["last"]["ipo_ts"] = ts
        _save(s)
        threading.Thread(target=_ipo_refresh, daemon=True).start()
        started.append("ipo")
    if not service.SCAN["running"] and not jobs.status("entry")["running"]:
        for task, market in (("scan_in", "IN"), ("scan_us", "US")):
            if s["enabled"][task] and scan_due(market, now, s["last"].get(task)):
                s["last"][task] = now.date().isoformat()
                s["last"][task + "_started"] = ts
                _save(s)
                service.start_scan(market=market, which="N500" if market == "IN" else "SP500")
                started.append(task)
                break                                   # one scan at a time
    return started


def _ipo_refresh() -> None:
    from . import ipo
    for fn in (lambda: ipo.india(refresh=True), lambda: ipo.us(),   # US months keep their own 30-min / 6-hour cache
               lambda: ipo.history("IN"), lambda: ipo.history("US")):  # 2-year lists rebuild in the background after 12 h
        try:
            fn()
        except Exception:  # noqa: BLE001
            pass


def _loop() -> None:
    time.sleep(90)
    while True:
        try:
            tick()
        except Exception:  # noqa: BLE001 - never stop the loop
            pass
        time.sleep(LOOP_S)


def start_background() -> None:
    if config.DEMO or _started[0]:
        return
    _started[0] = True
    threading.Thread(target=_loop, name="automation", daemon=True).start()


# ------------------------------------------------------------------ one list of everything that runs by itself
def _ts(key: str) -> Optional[float]:
    hit = store.get_company(key)
    return hit[0] if hit else None


def status() -> dict:
    from . import jobs, service
    now = datetime.now(IST)
    s = settings()
    a = jobs.auto_status()["checks"]
    scan = service.scan_status()
    pm_keys = sorted(store.keys_like("PREMARKET::CALL::IN::%"), reverse=True)
    rows = [
        {"id": "news", "name": "News and breaking", "schedule": "every 5 minutes, all day", "enabled": None,
         "last": _ts("NEWS::ITEMS")},
        {"id": "premarket", "name": "Pre-market board and NIFTY opening call", "schedule": "weekdays 08:20–09:15, every 9 minutes",
         "enabled": None, "last": _ts(pm_keys[0]) if pm_keys else None},
        {"id": "fiidii", "name": "FII / DII figures", "schedule": "weekdays from 18:00, every 30 minutes", "enabled": None,
         "last": _ts("FIIDII::CASH")},
        {"id": "ipo", "name": "IPO lists (NSE, SEBI, Nasdaq)", "schedule": "every 15 minutes, weekdays 09:00–17:30", "enabled": s["enabled"]["ipo"],
         "last": _ts("IPO::current::v2")},
        {"id": "scan_in", "name": "Top Picks scan · NIFTY 500", "schedule": "weekday evenings from 19:30 (financials older than "
         f"{config.SCAN_REUSE_HOURS:g} hours are downloaded again)", "enabled": s["enabled"]["scan_in"],
         "last": s["last"].get("scan_in_started"), "running": scan["running"] and scan.get("market") == "IN"},
        {"id": "scan_us", "name": "Top Picks scan · S&P 500", "schedule": "Tuesday–Saturday from 07:00 (after the US close)",
         "enabled": s["enabled"]["scan_us"], "last": s["last"].get("scan_us_started"),
         "running": scan["running"] and scan.get("market") == "US"},
    ]
    for n, label in (("levels", "Data check · support and resistance zones"), ("entry", "Data check · entry decision record")):
        st = jobs.status(n)
        rows.append({"id": n, "name": label, "schedule": "after each month end, outside market hours", "enabled": a[n]["enabled"],
                     "last_date": st.get("result_built"), "running": st.get("running", False), "failed": st.get("failed", False),
                     "next": a[n]["next"] if a[n]["enabled"] else None, "why": a[n]["why"]})
    for r in rows:
        r.setdefault("running", False)
    if scan["running"]:
        for r in rows:
            if r["running"] and r["id"].startswith("scan"):
                r["progress"] = {"done": scan.get("done"), "total": scan.get("total")}
    return {"tasks": rows, "now": now.isoformat(timespec="minutes")}
