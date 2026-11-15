"""Start EquityLens:  python run.py   then open http://localhost:8600

Logs always go to backend/data/logs/equitylens.log (2 MB x 4 files).
Started from EquityLens.vbs (pythonw, no window) there is no console at all,
so anything printed or any crash also lands in data/logs/console.log.
"""
import logging
import logging.config
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


if __name__ == "__main__":
    if WINDOWLESS:
        out = open(LOG_DIR / "console.log", "a", encoding="utf-8", buffering=1)  # noqa: SIM115
        sys.stdout = sys.stderr = out
    else:
        print(f"\n  EquityLens running ->  http://localhost:{config.PORT}\n  Logs: {LOG_FILE}\n")
    (config.DATA_DIR / "equitylens.pid").write_text(str(os.getpid()))     # used by "Stop EquityLens.vbs"
    logging.config.dictConfig(log_config(not WINDOWLESS))
    logging.getLogger("equitylens").info("starting on %s:%s (windowless=%s)", config.HOST, config.PORT, WINDOWLESS)
    uvicorn.run("app.main:app", host=config.HOST, port=config.PORT, reload=False, log_config=None)
