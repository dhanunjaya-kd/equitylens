"""Run the long backtests from the app: one click, in the background, with progress.

The tools in backend/tools are started as a separate Python process (no console window), writing
to a log in the data folder; the page polls the status. Only one run of each tool at a time.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from . import config, store

BACKEND = Path(__file__).resolve().parents[1]
JOBS = {
    "levels": {"script": "tools/levels_backtest.py", "label": "Level test (Price map)", "result": "LEVELS_TRACK::IN"},
    "entry": {"script": "tools/entry_backtest.py", "label": "Entry backtest (entry card and value record)", "result": "ENTRY_TRACK::IN"},
}
_procs: dict[str, subprocess.Popen] = {}
_PROGRESS = re.compile(r"(\d+)/(\d+) stocks")
QUIET_LIMIT = 15 * 60       # no handle (the app restarted) and no log line for 15 minutes = not running


def _log(name: str) -> Path:
    return config.DATA_DIR / f"job_{name}.log"


def start(name: str) -> dict:
    if name not in JOBS:
        raise KeyError(name)
    st = status(name)
    if st["running"]:
        return st
    log = open(_log(name), "w", encoding="utf-8")
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    _procs[name] = subprocess.Popen([sys.executable, "-u", str(BACKEND / JOBS[name]["script"])], cwd=str(BACKEND),
                                    stdout=log, stderr=subprocess.STDOUT, env=env, creationflags=flags)
    log.close()
    store.put_company(f"JOB::{name}", {"started": time.time(), "pid": _procs[name].pid})
    return status(name)


def status(name: str) -> dict:
    if name not in JOBS:
        raise KeyError(name)
    p = _procs.get(name)
    log = _log(name)
    lines = log.read_text(encoding="utf-8", errors="replace").splitlines() if log.exists() else []
    finished = any(x.startswith("Done in") for x in lines)
    if p is not None:
        running = p.poll() is None
        code: Optional[int] = p.poll()
    else:   # the app restarted while a run was going: judge by the log
        running = bool(lines) and not finished and time.time() - log.stat().st_mtime < QUIET_LIMIT
        code = None
    prog = None
    for x in reversed(lines):
        m = _PROGRESS.search(x)
        if m:
            prog = {"done": int(m.group(1)), "total": int(m.group(2))}
            break
    if prog is None:
        m = re.match(r"(\d+) stocks", lines[0]) if lines else None
        if m:
            prog = {"done": 0, "total": int(m.group(1))}
    job = store.get_company(f"JOB::{name}")
    res = store.get_company(JOBS[name]["result"])
    failed = (not running) and bool(lines) and not finished
    return {"name": name, "label": JOBS[name]["label"], "running": running, "finished": finished, "failed": failed,
            "exit_code": code, "progress": prog, "started": job[1]["started"] if job else None,
            "last_lines": lines[-12:], "result_built": res[1].get("built") if res else None}


# ------------------------------------------------------------------ automatic runs
# The data checks are built on month ends, so their result can only change after a month ends (or when their
# rules change). Each check runs by itself once that has happened, outside market hours, one at a time; a failed
# attempt is not retried the same day.
AUTO_KEY = "AUTO::checks"
CHECK_EVERY = 10 * 60
_auto = {"started": False}


def _rules_version(name: str):
    if name == "levels":
        from . import pricemap
        return pricemap.LEVEL_RULES_VERSION
    from . import entry
    return entry.RULES_VERSION


def auto_settings() -> dict:
    hit = store.get_company(AUTO_KEY)
    s = hit[1] if hit else {}
    return {"enabled": {n: s.get("enabled", {}).get(n, True) for n in JOBS}, "last_try": s.get("last_try", {})}


def set_auto(name: str, on: bool) -> dict:
    if name not in JOBS:
        raise KeyError(name)
    s = auto_settings()
    s["enabled"][name] = bool(on)
    store.put_company(AUTO_KEY, s)
    return auto_status()


def _market_hours(now) -> bool:
    return now.weekday() < 5 and (9, 0) <= (now.hour, now.minute) <= (15, 45)


def due(name: str, now) -> tuple[bool, str]:
    """(due?, why) for one check at time `now` (IST)."""
    res = store.get_company(JOBS[name]["result"])
    if not res:
        return True, "never run"
    r = res[1]
    if r.get("rules_version") is not None and r.get("rules_version") != _rules_version(name):
        return True, "rules changed since the last run"
    built = str(r.get("built") or "")
    month_start = now.date().replace(day=1).isoformat()
    if built < month_start and now.day >= 2:     # a month has ended since (its last session is in the prices from day 2)
        return True, "a month has ended since the last run"
    return False, f"up to date (last run {built})"


def next_month_run(now) -> str:
    y, m = (now.year + (now.month == 12), now.month % 12 + 1)
    return f"{y}-{m:02d}-02 after market hours"


def auto_status() -> dict:
    from . import calendars
    from datetime import datetime
    now = datetime.now(calendars.IST)
    s = auto_settings()
    out = {}
    for n in JOBS:
        d, why = due(n, now)
        out[n] = {"enabled": s["enabled"][n], "due": d, "why": why, "last_try": s["last_try"].get(n),
                  "next": ("now (outside market hours)" if not _market_hours(now) else "after 15:45 today") if d else next_month_run(now)}
    return {"checks": out, "market_hours": _market_hours(now)}


def auto_tick(now=None) -> Optional[str]:
    """Start at most one due check. Returns the name started (or None)."""
    from . import calendars
    from datetime import datetime
    now = now or datetime.now(calendars.IST)
    if config.DEMO or _market_hours(now) or any(status(n)["running"] for n in JOBS):
        return None
    s = auto_settings()
    today = now.date().isoformat()
    for n in JOBS:
        if not s["enabled"][n] or s["last_try"].get(n, "") >= today:
            continue
        if n == "entry":
            from . import service
            if service.SCAN["running"]:          # both use screener.in: wait for the Top Picks scan to finish
                continue
        d, _ = due(n, now)
        if d:
            s["last_try"][n] = today
            store.put_company(AUTO_KEY, s)
            start(n)
            return n
    return None


def _auto_loop() -> None:
    time.sleep(120)                     # let the app finish starting
    while True:
        try:
            auto_tick()
        except Exception:  # noqa: BLE001 - never stop the loop
            pass
        time.sleep(CHECK_EVERY)


def start_background() -> None:
    """The data checks are now started by Settings -> Scans (automation.py), with every other scan."""
    return


def _old_start_background() -> None:
    import threading
    if config.DEMO or _auto["started"]:
        return
    _auto["started"] = True
    threading.Thread(target=_auto_loop, name="auto-checks", daemon=True).start()
