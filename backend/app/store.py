"""Small SQLite store: cached company data + latest scan results."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from typing import Optional

from . import config

_lock = threading.Lock()


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(config.DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    return c


def init() -> None:
    with _lock, _conn() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS company (
            symbol TEXT PRIMARY KEY, fetched_at REAL, payload TEXT)""")
        c.execute("""CREATE TABLE IF NOT EXISTS ranking (
            symbol TEXT PRIMARY KEY, updated_at REAL, row TEXT)""")


def get_company(symbol: str) -> Optional[tuple[float, dict]]:
    with _conn() as c:
        r = c.execute("SELECT fetched_at, payload FROM company WHERE symbol=?", (symbol,)).fetchone()
    return (r["fetched_at"], json.loads(r["payload"])) if r else None


def put_company(symbol: str, payload: dict) -> None:
    with _lock, _conn() as c:
        c.execute("INSERT OR REPLACE INTO company(symbol, fetched_at, payload) VALUES (?,?,?)",
                  (symbol, time.time(), json.dumps(payload)))


def put_ranking(symbol: str, row: dict) -> None:
    with _lock, _conn() as c:
        c.execute("INSERT OR REPLACE INTO ranking(symbol, updated_at, row) VALUES (?,?,?)",
                  (symbol, time.time(), json.dumps(row)))


def all_rankings() -> list[dict]:
    with _conn() as c:
        rows = c.execute("SELECT updated_at, row FROM ranking").fetchall()
    out = []
    for r in rows:
        d = json.loads(r["row"])
        d["updated_at"] = r["updated_at"]
        out.append(d)
    return out


def count_companies() -> int:
    with _conn() as c:
        return c.execute("SELECT COUNT(*) FROM company").fetchone()[0]
