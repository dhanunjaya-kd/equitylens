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
