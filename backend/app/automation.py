"""Scans and background jobs: every scan EquityLens runs, in one list (Settings -> Scans), each with Auto / Manual.

Mode
  * Auto (default): when the app starts (after 20 s) and every minute while it runs, each scan that is switched on
    and out of date is started. Heavy scans run ONE AT A TIME in the order of JOBS (the rest wait in the queue);
    light ones run alongside.
  * Manual: nothing starts by itself - not even from opening a page. A scan runs only when "Run now" / "Run all"
    is pressed (those go through the same queue).
  Any single scan can also be switched off (it then runs only when asked).

When each scan is out of date
  * Market prices (India / US): Market Movers' own rule - a market close since the last load, 15 min old in market
    hours, older than 6 h, or saved before scanners existed.
  * NSE classification: stocks in the price list whose NSE classification / issued shares are missing or due.
  * IPO lists: every 15 minutes on weekdays 09:00-17:30 IST (and once if never loaded).
  * IPO 2-year history (India / US): older than 12 hours.
  * US stock list (Nasdaq): older than 4 hours.
  * Top Picks scan: India - the latest weekday 19:30 IST has passed since the last scan; US - the latest Tue-Sat
    07:00 IST (after a US close). So a laptop opened late catches up with the scan it missed.
    Never while an entry backtest runs (both use screener.in).
  * Data checks: after each month end, outside market hours (jobs.py).
Nothing runs in demo mode.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta
from typing import Optional

from . import calendars, config, store

IST = calendars.IST
KEY = "AUTO::tasks"
VERSION = 3
LOOP_S = 60
FIRST_S = 20
_started = [False]
_light = {"us_list": False, "ipo": False}

# id, name, what it fills, heavy (one at a time), on by default
JOBS = [
    ("prices_in", "Market prices · India", "Market Movers, Scanners, Heatmap, Money flow", True, True),
    ("classify_in", "NSE classification and shares", "Money flow groups, Heatmap box sizes", False, True),
    ("ipo", "IPO lists (NSE, SEBI, Nasdaq)", "IPO pages, Home", False, True),
    ("ipo_hist_in", "IPO 2-year history · India", "IPO › Last 2 years, Lock-in calendar", True, True),
    ("scan_in", "Top Picks scan · NIFTY 500", "Top Picks, Screener, company scores", True, True),
    ("prices_us", "Market prices · US", "US Market Movers, Scanners, Heatmap, Money flow", True, True),
    ("us_list", "US stock list (Nasdaq)", "All US view, US market caps", False, True),
    ("ipo_hist_us", "IPO 2-year history · US", "US IPO › Last 2 years", True, True),
    ("scan_us", "Top Picks scan · S&P 500", "US Top Picks, Screener, company scores", True, True),
    ("levels", "Data check · support and resistance zones", "Price map tested record", True, True),
    ("entry", "Data check · entry decision record", "Entry card tested record", True, True),
]
IDS = [j[0] for j in JOBS]
HEAVY = {j[0] for j in JOBS if j[3]}
TOGGLES = {j[0]: j[4] for j in JOBS if j[0] not in ("levels", "entry")}     # data checks keep their switch in jobs.py


# ------------------------------------------------------------------ settings
def settings() -> dict:
    hit = store.get_company(KEY)
    s = hit[1] if hit else {}
    en = s.get("enabled", {})
    out = {"v": VERSION, "mode": s.get("mode", "auto"), "enabled": {k: en.get(k, v) for k, v in TOGGLES.items()},
           "last": s.get("last", {}), "requested": list(s.get("requested", []))}
    if hit and s.get("v", 1) < 2:          # v1 saved the old default (US scan off) as if it were a choice: turn it on once
        out["enabled"]["scan_us"] = True
    if hit and s.get("v", 1) < VERSION:
        _save(out)
    return out


_status_memo: list = [0.0, None]


def _save(s: dict) -> None:
    store.put_company(KEY, s)
    _status_memo[1] = None            # the top-bar ring shows a change at once


def mode() -> str:
    return settings()["mode"]


def set_mode(m: str) -> dict:
    if m not in ("auto", "manual"):
        raise KeyError(m)
    s = settings()
    s["mode"] = m
    _save(s)
    return status()


def enabled(task: str) -> bool:
    if task in ("levels", "entry"):
        from . import jobs
        return jobs.auto_settings()["enabled"][task]
    return settings()["enabled"].get(task, True)


def allowed(task: str) -> bool:
    """May this scan start by itself (from a page visit or the loop)? Auto mode and the scan switched on."""
    return mode() == "auto" and enabled(task)


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


# ------------------------------------------------------------------ schedules
def _last_slot(market: str, now: datetime) -> Optional[str]:
    """Date of the latest scheduled Top Picks slot at or before `now` (IN: weekdays 19:30; US: Tue-Sat 07:00)."""
    for back in range(0, 8):
        d = now - timedelta(days=back)
        if market == "IN":
            ok = d.weekday() < 5 and (back > 0 or (now.hour, now.minute) >= (19, 30))
        else:
            ok = d.weekday() in (1, 2, 3, 4, 5) and (back > 0 or now.hour >= 7)
        if ok:
            return d.date().isoformat()
    return None


def scan_due(market: str, now: datetime, last_day: Optional[str]) -> bool:
    slot = _last_slot(market, now)
    return slot is not None and (last_day or "") < slot


def ipo_due(now: datetime, last_ts: float, ts: float) -> bool:
    if not last_ts:
        return True
    return now.weekday() < 5 and (9, 0) <= (now.hour, now.minute) <= (17, 30) and ts - last_ts >= 15 * 60


_sym_memo: dict = {}


def _price_symbols(market: str) -> list[str]:
    """Symbols in the saved price list, worked out once per save (the list is several MB)."""
    from . import movers
    key = movers._key(market)
    t = store.stamp(key)
    m = _sym_memo.get(key)
    if m and m[0] == t:
        return list(m[1])
    hit = store.get_company(key)
    syms = [r["symbol"] for r in (hit[1].get("rows", []) if hit else [])]
    _sym_memo[key] = (hit[0] if hit else None, syms)
    return list(syms)


def _ts(key: str) -> Optional[float]:
    return store.stamp(key)          # only the save time: never decode a big list for it


# ------------------------------------------------------------------ each scan: running / progress, due, start, last run
def _state(job: str) -> dict:
    """{"running", "done", "total", "started"} for one scan."""
    from . import ipo, jobs, movers, sectors, service
    if job.startswith("prices_"):
        st = movers.STATE[job[-2:].upper()]
        return {"running": st["running"], "done": st.get("done"), "total": st.get("total"), "started": st.get("started")}
    if job == "classify_in":
        st = sectors.STATE
        return {"running": st["running"], "done": st.get("done"), "total": st.get("total"), "started": st.get("started")}
    if job.startswith("ipo_hist_"):
        st = ipo.HIST_STATE[job[-2:].upper()]
        return {"running": st["running"], "done": st.get("done"), "total": st.get("total"), "started": st.get("started")}
    if job.startswith("scan_"):
        sc = service.SCAN
        run = sc["running"] and sc.get("market") == job[-2:].upper()
        return {"running": run, "done": sc.get("done") if run else None, "total": sc.get("total") if run else None,
                "started": sc.get("started_at") if run else None}
    if job in ("levels", "entry"):
        st = jobs.status(job)
        return {"running": st.get("running", False), "done": None, "total": None, "started": None}
    return {"running": _light.get(job, False), "done": None, "total": None, "started": None}


def _due(job: str, now: datetime, ts: float, s: dict) -> tuple[bool, str]:
    from . import ipo, jobs, movers, sectors, usuniverse
    if job.startswith("prices_"):
        return (True, "out of date") if movers.is_stale(job[-2:].upper()) else (False, "up to date")
    if job == "classify_in":
        syms = _price_symbols("IN")
        if not syms:
            return False, "waits for India market prices"
        n = len(sectors.missing(syms))
        return (n > 0, f"{n} stocks to look up" if n else "all looked up")
    if job == "ipo":
        return (True, "due") if ipo_due(now, s["last"].get("ipo_ts", 0), ts) else (False, "every 15 min, weekdays 09:00-17:30")
    if job.startswith("ipo_hist_"):
        t = _ts(f"IPO::HIST::{job[-2:].upper()}")
        return (True, "older than 12 hours" if t else "never built") if not t or ts - t > ipo.HIST_TTL else (False, "up to date")
    if job == "us_list":
        t = _ts("USUNIV::listed")
        return (True, "older than 4 hours" if t else "never loaded") if not t or ts - t > usuniverse.TTL_LISTED else (False, "up to date")
    if job.startswith("scan_"):
        if jobs.status("entry").get("running"):
            return False, "waits for the entry backtest (both use screener.in)"
        d = scan_due(job[-2:].upper(), now, s["last"].get(job))
        return (True, "a scheduled scan is due") if d else (False, "done for the latest schedule")
    if job in ("levels", "entry"):
        d, why = jobs.due(job, now)
        if d and jobs._market_hours(now):
            return False, "waits for market hours to end"
        return d, why
    return False, ""


def _start(job: str, now: datetime, ts: float, s: dict) -> None:
    from . import ipo, jobs, movers, sectors, service, usuniverse
    if job.startswith("prices_"):
        movers.refresh(job[-2:].upper())
    elif job == "classify_in":
        sectors.start_fill(_price_symbols("IN"))
    elif job == "ipo":
        s["last"]["ipo_ts"] = ts
        _light["ipo"] = True
        threading.Thread(target=_ipo_refresh, daemon=True).start()
    elif job.startswith("ipo_hist_"):
        ipo.history(job[-2:].upper(), refresh=True, force=True)
    elif job == "us_list":
        def run():
            try:
                usuniverse.listed(refresh=True)
                usuniverse.nasdaq100(refresh=True)
            finally:
                _light["us_list"] = False
        _light["us_list"] = True
        threading.Thread(target=run, daemon=True).start()
    elif job.startswith("scan_"):
        m = job[-2:].upper()
        s["last"][job] = now.date().isoformat()
        s["last"][job + "_started"] = ts
        service.start_scan(market=m, which="N500" if m == "IN" else "SP500")
    elif job in ("levels", "entry"):
        jobs.start(job)


def _ipo_refresh() -> None:
    from . import ipo
    try:
        for fn in (lambda: ipo.india(refresh=True), lambda: ipo.us()):     # US months keep their own 30-min / 6-hour cache
            try:
                fn()
            except Exception:  # noqa: BLE001
                pass
    finally:
        _light["ipo"] = False


# ------------------------------------------------------------------ the loop
def tick(now: Optional[datetime] = None, ts: Optional[float] = None) -> list[str]:
    """Start what is wanted: asked for (Run now / Run all), or in Auto mode switched on and out of date.
    Heavy scans one at a time, in JOBS order. Returns what was started."""
    now = now or datetime.now(IST)
    ts = ts or time.time()
    if config.DEMO:
        return []
    s = settings()
    auto = s["mode"] == "auto"
    started = []
    heavy_busy = any(_state(j)["running"] for j in HEAVY)
    for job in IDS:
        st = _state(job)
        if st["running"]:
            if job in s["requested"]:
                s["requested"].remove(job)
            continue
        asked = job in s["requested"]
        want = asked or (auto and enabled(job) and _due(job, now, ts, s)[0])
        if job.startswith("scan_") and asked and _state("entry")["running"]:
            want = False                               # stays queued until the entry backtest ends
        if not want:
            continue
        if job in HEAVY:
            if heavy_busy:
                continue                               # waits in the queue
            heavy_busy = True
        try:
            _start(job, now, ts, s)
            started.append(job)
        except Exception:  # noqa: BLE001 - one scan failing never stops the others
            pass
        if asked:
            s["requested"].remove(job)
    try:
        broker_reminder(now, s)
    except Exception:  # noqa: BLE001
        pass
    _save(s)
    return started


def broker_reminder(now: datetime, s: dict) -> Optional[str]:
    """Weekdays 08:45-10:00 IST, once a day: Telegram note for broker logins that have ended (when Telegram is set up)."""
    from . import alerts, brokers
    day = now.date().isoformat()
    if now.weekday() >= 5 or not ((8, 45) <= (now.hour, now.minute) <= (10, 0)) or s["last"].get("broker_remind") == day:
        return None
    ended = [b["name"] for b in brokers.status("") if b.get("token_time") and
             (b.get("error") or (b.get("valid_until") and b["valid_until"] < now.isoformat(timespec="minutes")))]
    s["last"]["broker_remind"] = day
    if not ended:
        return None
    try:
        alerts.send(f"🔗 <b>Broker login ended</b>: {', '.join(ended)}.\nOpen EquityLens → My Portfolio → Reconnect to keep holdings up to date.")
        return ", ".join(ended)
    except Exception:  # noqa: BLE001 - Telegram not set up: nothing to send
        return None


def run_now(job: str) -> dict:
    if job not in IDS:
        raise KeyError(job)
    s = settings()
    if job not in s["requested"]:
        s["requested"].append(job)
    _save(s)
    tick()
    return status()


def run_all() -> dict:
    s = settings()
    s["requested"] = [j for j in IDS if not _state(j)["running"]]
    _save(s)
    tick()
    return status()


def _loop() -> None:
    time.sleep(FIRST_S)
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


# ------------------------------------------------------------------ one list of everything
def status_cached(max_age: float = 3.0) -> dict:
    """status() shared for a few seconds: every open phone, tablet and tab asks for it."""
    if _status_memo[1] is not None and time.time() - _status_memo[0] < max_age:
        return _status_memo[1]
    st = status()
    _status_memo[0], _status_memo[1] = time.time(), st
    return st


def status() -> dict:
    now = datetime.now(IST)
    ts = time.time()
    s = settings()
    last_keys = {"prices_in": "MOVERS::v2::IN", "prices_us": "MOVERS::v2::US", "classify_in": "SECTORS::IN",
                 "ipo": "IPO::current::v2", "ipo_hist_in": "IPO::HIST::IN", "ipo_hist_us": "IPO::HIST::US", "us_list": "USUNIV::listed"}
    rows = []
    for job, name, fills, heavy, _ in JOBS:
        st = _state(job)
        try:
            due, why = _due(job, now, ts, s)
        except Exception as e:  # noqa: BLE001
            due, why = False, f"could not check: {e}"[:120]
        last = _ts(last_keys[job]) if job in last_keys else s["last"].get(job + "_started")
        if job in ("levels", "entry"):
            from . import jobs
            last = None
            last_date = jobs.status(job).get("result_built")
        else:
            last_date = None
        eta = None
        if st["running"] and st.get("done") and st.get("total") and st.get("started"):
            el = ts - st["started"]
            eta = round(el / st["done"] * (st["total"] - st["done"])) if st["done"] else None
        queued = (job in s["requested"]) and not st["running"]
        rows.append({"id": job, "name": name, "fills": fills, "heavy": heavy, "enabled": enabled(job),
                     "running": st["running"], "progress": {"done": st.get("done"), "total": st.get("total")} if st["running"] else None,
                     "eta_s": eta, "queued": queued, "due": due, "why": why, "last": last, "last_date": last_date})
    run = [r for r in rows if r["running"]]
    done = sum((r["progress"] or {}).get("done") or 0 for r in run)
    total = sum((r["progress"] or {}).get("total") or 0 for r in run)
    always = [{"id": "news", "name": "News and breaking", "schedule": "every 5 minutes, all day", "last": _ts("NEWS::ITEMS")},
              {"id": "premarket", "name": "Pre-market board and NIFTY opening call", "schedule": "weekdays 08:20-09:15, every 9 minutes"},
              {"id": "fiidii", "name": "FII / DII figures", "schedule": "weekdays from 18:00, every 30 minutes", "last": _ts("FIIDII::CASH")}]
    return {"mode": s["mode"], "now": now.isoformat(timespec="minutes"), "tasks": rows, "always": always,
            "overall": {"running": len(run), "queued": sum(1 for r in rows if r["queued"]), "due": sum(1 for r in rows if r["due"] and r["enabled"]),
                        "done": done, "total": total, "pct": round(done / total * 100) if total else None,
                        "names": [r["name"] for r in run]}}
