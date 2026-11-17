"""Start EquityLens:  python run.py   then open http://localhost:8600

Logs always go to backend/data/logs/equitylens.log (2 MB x 4 files).
Started from EquityLens.vbs (pythonw, no window) there is no console at all,
so anything printed or any crash also lands in data/logs/console.log.
"""
import glob
import logging
import logging.config
import socket
import subprocess
import threading
import time
import logging.handlers  # noqa: F401
import os
import sys

import uvicorn

from app import config

LOG_DIR = config.DATA_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "equitylens.log"
WINDOWLESS = sys.stdout is None or sys.stderr is None      # pythonw.exe


class QuietDisconnects(logging.Filter):
    """Windows logs a scary traceback whenever a browser drops a connection early
    (WinError 10054). It is harmless, so keep it out of the log."""

    def filter(self, record: logging.LogRecord) -> bool:
        exc = record.exc_info[1] if record.exc_info else None
        if isinstance(exc, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
            return False
        return "_call_connection_lost" not in record.getMessage()


def log_config(console: bool) -> dict:
    handlers = {
        "file": {"class": "logging.handlers.RotatingFileHandler", "filename": str(LOG_FILE), "maxBytes": 2_000_000,
                 "backupCount": 3, "encoding": "utf-8", "formatter": "plain", "filters": ["quiet"]},
    }
    if console:
        handlers["console"] = {"class": "logging.StreamHandler", "stream": "ext://sys.stderr", "formatter": "plain", "filters": ["quiet"]}
    names = list(handlers)
    return {
        "version": 1, "disable_existing_loggers": False,
        "filters": {"quiet": {"()": QuietDisconnects}},
        "formatters": {"plain": {"format": "%(asctime)s %(levelname)-7s %(message)s", "datefmt": "%Y-%m-%d %H:%M:%S"}},
        "handlers": handlers,
        "root": {"level": "INFO", "handlers": names},
        "loggers": {
            "uvicorn": {"level": "INFO", "handlers": [], "propagate": True},
            "uvicorn.error": {"level": "INFO", "handlers": [], "propagate": True},
            "uvicorn.access": {"level": "WARNING", "handlers": [], "propagate": True},   # no line per request
        },
    }


HERE = os.path.dirname(os.path.abspath(__file__))
WATCH = [os.path.join(HERE, "app", "*.py"), os.path.join(HERE, "static", "index.html")]


def _stamp() -> dict:
    out = {}
    for pat in WATCH:
        for f in glob.glob(pat):
            try:
                out[f] = os.path.getmtime(f)
            except OSError:
                pass
    return out


def _requirements_changed() -> bool:
    """New packages need the launcher's install step, so don't restart into a crash."""
    try:
        with open(os.path.join(HERE, "requirements.txt"), encoding="utf-8") as a, \
             open(os.path.join(HERE, "venv", "eql_req.txt"), encoding="utf-8") as b:
            return a.read() != b.read()
    except OSError:
        return False


def watch_for_updates(log: logging.Logger, every: int = 15) -> None:
    """After a `git pull`, start a fresh server with the new code and exit this one,
    so the app never keeps running old code."""
    before = _stamp()
    while True:
        time.sleep(every)
        now = _stamp()
        if now != before:
            time.sleep(5)              # let git finish writing every file
            if _requirements_changed():
                log.warning("code changed but new packages are needed; restart with EquityLens.vbs")
                before = _stamp()
                continue
            log.info("code changed on disk - restarting with the new version")
            flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            subprocess.Popen([sys.executable, os.path.abspath(__file__), "--wait-port"], cwd=HERE,
                             creationflags=flags, close_fds=True)
            os._exit(0)


def wait_for_port(port: int, seconds: int = 30) -> None:
    """The previous server may still be letting go of the port."""
    end = time.time() + seconds
    while time.time() < end:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return
            except OSError:
                time.sleep(0.5)


if __name__ == "__main__":
    if "--wait-port" in sys.argv:
        wait_for_port(config.PORT)
    if WINDOWLESS:
        out = open(LOG_DIR / "console.log", "a", encoding="utf-8", buffering=1)  # noqa: SIM115
        sys.stdout = sys.stderr = out
    else:
        print(f"\n  EquityLens running ->  http://localhost:{config.PORT}\n  Logs: {LOG_FILE}\n")
    (config.DATA_DIR / "equitylens.pid").write_text(str(os.getpid()))     # used by "Stop EquityLens.vbs"
    logging.config.dictConfig(log_config(not WINDOWLESS))
    logging.getLogger("equitylens").info("starting on %s:%s (windowless=%s)", config.HOST, config.PORT, WINDOWLESS)
    if os.environ.get("EQL_AUTO_RESTART", "1") != "0":
        threading.Thread(target=watch_for_updates, args=(logging.getLogger("equitylens"),), daemon=True).start()
    uvicorn.run("app.main:app", host=config.HOST, port=config.PORT, reload=False, log_config=None)
