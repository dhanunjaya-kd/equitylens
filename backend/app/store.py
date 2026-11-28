"""SQLite store with WAL mode, thread-local connection pooling, and indexed rankings."""
from __future__ import annotations

import json
import marshal
import sqlite3
import threading
import time
from collections import OrderedDict
from typing import Optional

from . import config

_lock = threading.Lock()
_local = threading.local()
_rank_cache: dict[str, list[dict]] = {}


def _conn() -> sqlite3.Connection:
    db_key = str(config.DB_PATH)
    conns: dict[str, sqlite3.Connection] = getattr(_local, "conns", None)
    if conns is None:
        conns = {}
        _local.conns = conns
    c = conns.get(db_key)
    if c is not None:
        try:
            c.execute("SELECT 1")
            return c
        except sqlite3.Error:
            conns.pop(db_key, None)
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(config.DB_PATH, timeout=30, check_same_thread=False)
    c.row_factory = sqlite3.Row
    try:
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=NORMAL")
        c.execute("PRAGMA temp_store=MEMORY")
        c.execute("PRAGMA busy_timeout=30000")
    except sqlite3.Error:
        pass
    conns[db_key] = c
    return c


def init() -> None:
    with _lock, _conn() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS company (
            symbol TEXT PRIMARY KEY, fetched_at REAL, payload TEXT)""")
        c.execute("""CREATE TABLE IF NOT EXISTS ranking (
            symbol TEXT PRIMARY KEY, updated_at REAL, row TEXT,
            market TEXT, overall REAL, market_cap REAL, verdict TEXT)""")
        cols = {r["name"] for r in c.execute("PRAGMA table_info(ranking)").fetchall()}
        for col, typ in (("market", "TEXT"), ("overall", "REAL"), ("market_cap", "REAL"), ("verdict", "TEXT")):
            if col not in cols:
                c.execute(f"ALTER TABLE ranking ADD COLUMN {col} {typ}")
        c.execute("CREATE INDEX IF NOT EXISTS idx_ranking_market_overall ON ranking(market, overall DESC)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_ranking_verdict ON ranking(market, verdict)")
    _rank_cache.pop(str(config.DB_PATH), None)


# Big saved payloads (price lists with scans, the all-US list, IPO history...) are read many times a minute.
# Re-reading and JSON-decoding several MB each time made every page slow. Keep the decoded payload of big
# entries in memory as marshal bytes, keyed by its save time: a cheap time check, then marshal.loads hands
# every caller its own fresh copy (about 3x faster than json.loads, and safe to change).
BIG = 100_000                 # characters of JSON
_MEM_CAP = 300_000_000        # bytes kept in memory at most
_dec: "OrderedDict[tuple, tuple[float, bytes]]" = OrderedDict()
_dec_lock = threading.Lock()


def _remember(k: tuple, ts: float, payload) -> None:
    try:
        b = marshal.dumps(payload)
    except ValueError:
        return
    with _dec_lock:
        _dec[k] = (ts, b)
        _dec.move_to_end(k)
        total = sum(len(v[1]) for v in _dec.values())
        while total > _MEM_CAP and len(_dec) > 1:
            _, (_, old) = _dec.popitem(last=False)
            total -= len(old)


def _forget(symbol: str) -> None:
    with _dec_lock:
        _dec.pop((str(config.DB_PATH), symbol), None)


def get_company(symbol: str) -> Optional[tuple[float, dict]]:
    k = (str(config.DB_PATH), symbol)
    with _dec_lock:
        m = _dec.get(k)
    c = _conn()
    if m is not None:
        r = c.execute("SELECT fetched_at FROM company WHERE symbol=?", (symbol,)).fetchone()
        if r and r[0] == m[0]:
            return m[0], marshal.loads(m[1])
        _forget(symbol)
    r = c.execute("SELECT fetched_at, payload FROM company WHERE symbol=?", (symbol,)).fetchone()
    if not r:
        return None
    text = r["payload"]
    payload = json.loads(text)
    if len(text) >= BIG:
        _remember(k, r["fetched_at"], payload)
    return r["fetched_at"], payload


def stamp(symbol: str) -> Optional[float]:
    """When an entry was saved, without reading it."""
    r = _conn().execute("SELECT fetched_at FROM company WHERE symbol=?", (symbol,)).fetchone()
    return r[0] if r else None


def get_many(symbols: list[str]) -> dict[str, tuple[float, dict]]:
    """Several small entries in one query: {symbol: (fetched_at, payload)} for those that exist."""
    out: dict = {}
    c = _conn()
    syms = list(dict.fromkeys(s for s in symbols if s))
    for i in range(0, len(syms), 500):
        part = syms[i:i + 500]
        q = "SELECT symbol, fetched_at, payload FROM company WHERE symbol IN (%s)" % ",".join("?" * len(part))
        for r in c.execute(q, part).fetchall():
            out[r["symbol"]] = (r["fetched_at"], json.loads(r["payload"]))
    return out


def put_company(symbol: str, payload: dict) -> None:
    _forget(symbol)
    with _lock, _conn() as c:
        c.execute("INSERT OR REPLACE INTO company(symbol, fetched_at, payload) VALUES (?,?,?)",
                  (symbol, time.time(), json.dumps(payload)))
    _forget(symbol)


def put_ranking(symbol: str, row: dict) -> None:
    now = time.time()
    with _lock, _conn() as c:
        c.execute(
            """INSERT OR REPLACE INTO ranking(symbol, updated_at, row, market, overall, market_cap, verdict)
               VALUES (?,?,?,?,?,?,?)""",
            (symbol, now, json.dumps(row), row.get("market", "IN"), row.get("overall"), row.get("market_cap"), row.get("verdict")),
        )
    _rank_cache.pop(str(config.DB_PATH), None)


def all_rankings() -> list[dict]:
    db_key = str(config.DB_PATH)
    cached = _rank_cache.get(db_key)
    if cached is not None:
        return [dict(r) for r in cached]
    with _conn() as c:
        rows = c.execute("SELECT updated_at, row FROM ranking").fetchall()
    out = []
    for r in rows:
        d = json.loads(r["row"])
        d["updated_at"] = r["updated_at"]
        out.append(d)
    _rank_cache[db_key] = out
    return [dict(r) for r in out]


def count_companies() -> int:
    with _conn() as c:
        return c.execute("SELECT COUNT(*) FROM company").fetchone()[0]


def keys_like(pattern: str) -> list[str]:
    with _conn() as c:
        return [r["symbol"] for r in c.execute("SELECT symbol FROM company WHERE symbol LIKE ?", (pattern,)).fetchall()]
