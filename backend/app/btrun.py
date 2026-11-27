"""Shared engine for the long data checks (tools/levels_backtest.py, tools/entry_backtest.py).

Three things make a repeat run fast without changing what it measures:

1. A price archive with a FIXED first day. Yahoo's 10-year window slides forward every day, which quietly changed
   the oldest months of every run. The archive keeps the history it already has and adds new days. If the
   overlapping days disagree by more than 1% (a split or other price revision), that stock's archive starts again.
2. A saved result per stock for every month whose outcome can no longer change (its forward window has closed).
   It is reused only when the rules are the same and the prices (and P/E, NIFTY) the result depended on are
   byte-for-byte the same (a fingerprint); otherwise that stock is worked out again from scratch.
3. Parallel work: prices are downloaded 4 at a time, and stocks are worked out on all CPU cores but one.
   screener.in is still asked one stock at a time with the same pause, so it is not hammered.

The results are the same as a full one-by-one run on the same prices (tests/test_btrun.py checks this).
"""
from __future__ import annotations

import hashlib
import json
import multiprocessing as mp
import os
import sys
import time
from concurrent.futures import Future, ProcessPoolExecutor, ThreadPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path
from typing import Callable, Optional

from . import config, store

MIN_TRADED_VALUE = 1e7   # Rs 1 crore median daily traded value over the previous 3 months
LIQ_DAYS = 63
REVISION_TOLERANCE = 0.01


def liquid(bars, i):
    vals = sorted(b["c"] * (b.get("v") or 0) for b in bars[max(0, i - LIQ_DAYS + 1):i + 1])
    return vals[len(vals) // 2] >= MIN_TRADED_VALUE


# ------------------------------------------------------------------ fixed-start price archive
def merge_archive(old: Optional[list], fresh: list) -> tuple[list, bool]:
    """(merged bars, archive restarted?). Keeps the archive's days before the fresh download starts; the fresh
    download wins for every day it has. Restarts (fresh only) when any common day's close differs by >1%."""
    if not old:
        return list(fresh), False
    if not fresh:
        return list(old), False
    by = {b["t"]: b["c"] for b in old}
    for b in fresh:
        c0 = by.get(b["t"])
        if c0 and b["c"] and abs(b["c"] / c0 - 1) > REVISION_TOLERANCE:
            return list(fresh), True
    start = fresh[0]["t"]
    return [b for b in old if b["t"] < start] + list(fresh), False


def archived(key: str, fresh: list) -> tuple[list, bool]:
    hit = store.get_company(f"BTBARS::{key}")
    bars, restarted = merge_archive(hit[1]["bars"] if hit else None, fresh)
    store.put_company(f"BTBARS::{key}", {"bars": bars})
    return bars, restarted


def fingerprint(rows: list, fields=("t", "o", "h", "l", "c", "v")) -> str:
    """Stable hash of price bars (rounded so tiny float noise from the feed doesn't count as a change)."""
    h = hashlib.sha1()
    for b in rows:
        if isinstance(b, dict):
            h.update("|".join(f"{b.get(f):.4f}" if isinstance(b.get(f), float) else str(b.get(f)) for f in fields).encode())
        else:
            h.update(json.dumps(b).encode())
        h.update(b"\n")
    return h.hexdigest()


# ------------------------------------------------------------------ parallel runner
def default_workers() -> int:
    env = os.getenv("EQL_WORKERS")
    if env and env.isdigit():
        return max(1, int(env))
    return max(1, min((os.cpu_count() or 2) - 1, 8))


def _pool(workers: int):
    ctx = mp.get_context("spawn")
    if os.name == "nt":                       # no console window flashing up for each worker on Windows
        w = Path(sys.executable).with_name("pythonw.exe")
        if w.exists():
            ctx.set_executable(str(w))
    return ProcessPoolExecutor(max_workers=workers, mp_context=ctx)


def run(syms: list[str], fetch: Callable, compute: Callable, on_result: Callable,
        workers: Optional[int] = None, threads: int = 4, progress: Optional[Callable] = None) -> None:
    """fetch(sym) -> (args tuple for compute | None, skip reason) runs in `threads` download threads;
    compute(*args) runs on `workers` processes (in this process when workers == 1); on_result(sym, result, error)
    is called here, in order of completion. Downloads of the next batch overlap the work on the current one."""
    workers = workers or default_workers()
    total, done, t0 = len(syms), 0, time.time()
    chunk = max(8, workers * 3)
    parts = [syms[i:i + chunk] for i in range(0, total, chunk)]

    def safe_fetch(sym):
        try:
            args, why = fetch(sym)
            return sym, args, why
        except Exception as e:  # noqa: BLE001 - one stock must not stop the run
            return sym, None, f"fetch failed: {type(e).__name__}"

    def tick():
        nonlocal done
        done += 1
        if done % 10 == 0 or done == total:
            line = progress() if progress else ""
            print(f"  {done}/{total} stocks{' · ' + line if line else ''} · {(time.time() - t0) / 60:.1f} min", flush=True)

    pool = _pool(workers) if workers > 1 else None
    try:
        with ThreadPoolExecutor(threads) as tp:
            fetched = list(tp.map(safe_fetch, parts[0])) if parts else []
            for k in range(len(parts)):
                jobs, args_of = [], {}
                for sym, args, why in fetched:
                    args_of[sym] = args
                    if args is None:
                        on_result(sym, None, why)
                        tick()
                    elif pool:
                        try:
                            jobs.append((sym, pool.submit(compute, *args)))
                        except BrokenProcessPool:
                            jobs.append((sym, args))
                    else:
                        jobs.append((sym, args))
                nxt = tp.map(safe_fetch, parts[k + 1]) if k + 1 < len(parts) else iter(())
                for sym, job in jobs:
                    try:
                        res = job.result() if isinstance(job, Future) else compute(*job)
                        on_result(sym, res, None)
                    except BrokenProcessPool:
                        # the worker processes could not start or died: carry on in this process instead
                        if pool:
                            print("  CPU workers stopped; continuing one stock at a time", flush=True)
                            pool.shutdown(cancel_futures=True)
                            pool = None
                        try:
                            on_result(sym, compute(*args_of[sym]), None)
                        except Exception as e:  # noqa: BLE001
                            on_result(sym, None, f"error: {type(e).__name__}")
                    except Exception as e:  # noqa: BLE001
                        on_result(sym, None, f"error: {type(e).__name__}")
                    tick()
                fetched = list(nxt)
    finally:
        if pool:
            pool.shutdown(cancel_futures=True)


# ------------------------------------------------------------------ level test: one stock
def level_stock(bars: list[dict], cache: Optional[dict]) -> tuple[list, dict]:
    """All level-test rows for one stock + the cache for its closed months. A month end is closed when its whole
    forward window (LOOK sessions) is in the past: nothing after it can change its rows."""
    from . import pricemap
    t = [b["t"] for b in bars]
    n = len(bars)
    closed = [i for i in pricemap.month_ends(bars) if i + 1 + pricemap.LOOK < n]
    ver = f"{pricemap.LEVEL_RULES_VERSION}|{pricemap.TEST_VERSION}"
    old_rows, seen, after = [], set(), None
    if cache and cache.get("ver") == ver:
        ci = cache.get("cut_i")
        if ci is not None and ci < n and t[ci] == cache.get("cut") and \
                ci + pricemap.LOOK + 1 <= n and fingerprint(bars[:ci + pricemap.LOOK + 1]) == cache.get("hash"):
            old_rows, seen, after = cache["rows"], {tuple(k) for k in cache["seen"]}, cache["cut"]
    new_rows = pricemap.level_samples(bars, liquid, after=after, seen=seen)
    rows = old_rows + new_rows
    new_cache = None
    if closed:
        ci = closed[-1]
        cut = t[ci]
        keep = [r for r in rows if (r["date"] if r.get("skip") else r["seen"]) <= cut]
        new_cache = {"ver": ver, "cut": cut, "cut_i": ci, "hash": fingerprint(bars[:ci + pricemap.LOOK + 1]), "rows": keep,
                     "seen": sorted({(r["side"], r["source"], r["date"]) for r in keep if not r.get("skip")})}
    return rows, new_cache


# ------------------------------------------------------------------ entry backtest: one stock
ENTRY_FWD = 756          # 36 months: the longest forward window in the entry test


def entry_month(bars, c, sma200, i, pes, pe_dates, nifty_t, nifty_c, min_pe):
    """One month end -> ('row', row) | ('illiquid', None) | ('bad', None) | (None, None)."""
    import bisect
    from . import entry
    d = bars[i]["t"]
    k = bisect.bisect_right(pe_dates, d)
    if k < min_pe:
        return None, None
    if not liquid(bars, i):
        return "illiquid", None
    hist = [v for _, v in pes[:k]]
    try:
        v = entry.decide(bars, i, pe_hist=hist, pe_now=hist[-1])
    except Exception:  # noqa: BLE001
        return "bad", None
    if v["verdict"] == "NA":
        return None, None
    fwd = lambda n: c[i + n] / c[i] - 1 if i + n < len(c) else None   # noqa: E731
    a = bisect.bisect_right(nifty_t, d) - 1
    b12 = nifty_c[a + 252] / nifty_c[a] - 1 if a >= 0 and a + 252 < len(nifty_c) else None
    r12 = fwd(252)
    row = {"date": d, "verdict": v["verdict"], "rule": v["rule"], "state": v["checks"]["value"]["state"],
           "r6": fwd(126), "r12": r12, "r24": fwd(504), "r36": fwd(756),
           "x12": (r12 - b12) if r12 is not None and b12 is not None else None}
    if v["rule"] == "avoid_falling" and r12 is not None:
        j = next((j for j in range(i + 1, i + 253) if c[j] > sma200(j)), None)
        row["turned"] = j is not None
        row["r12_wait"] = c[i + 252] / c[j] - 1 if j is not None else 0.0
    return "row", row


def entry_stock(bars: list[dict], pes: list, nifty: list[dict], cache: Optional[dict]) -> tuple[list, dict, dict]:
    """(rows, counts {'illiquid', 'bad'}, cache) for one stock. A month end is closed when its 36-month window,
    the P/E history up to it and NIFTY up to its 12-month mark are all in the past and unchanged."""
    from . import entry, pricemap
    c = [b["c"] for b in bars]
    t = [b["t"] for b in bars]
    n = len(c)
    cum = [0.0]
    for x in c:
        cum.append(cum[-1] + x)
    sma200 = lambda j: (cum[j + 1] - cum[j - 199]) / 200 if j >= 199 else None   # noqa: E731
    pe_dates = [d for d, _ in pes]
    nifty_t, nifty_c = [b["t"] for b in nifty], [b["c"] for b in nifty]
    mes = pricemap.month_ends(bars)
    closed = [i for i in mes if i + ENTRY_FWD < n]
    ver = str(entry.RULES_VERSION)

    def fp(ci):
        end = t[ci + ENTRY_FWD]
        return fingerprint(bars[:ci + ENTRY_FWD + 1]) + fingerprint([p for p in pes if p[0] <= t[ci]]) + \
            fingerprint([b for b in nifty if b["t"] <= end], ("t", "c"))

    rows, counts, start_after = [], {"illiquid": 0, "bad": 0}, None
    if cache and cache.get("ver") == ver:
        ci = cache.get("cut_i")
        if ci is not None and ci + ENTRY_FWD < n and t[ci] == cache.get("cut") and fp(ci) == cache.get("hash"):
            rows, counts, start_after = list(cache["rows"]), dict(cache["counts"]), cache["cut"]
    new_cache = None
    cut_i = closed[-1] if closed else None
    for i in mes:
        if start_after and t[i] <= start_after:
            continue
        kind, row = entry_month(bars, c, sma200, i, pes, pe_dates, nifty_t, nifty_c, entry.MIN_PE_POINTS)
        if kind == "row":
            rows.append(row)
        elif kind in ("illiquid", "bad"):
            counts[kind] += 1
        if cut_i is not None and i == cut_i:
            new_cache = {"ver": ver, "cut": t[i], "cut_i": i, "hash": fp(i), "rows": list(rows), "counts": dict(counts)}
    if new_cache is None and cut_i is not None and start_after and t[cut_i] == start_after:
        new_cache = dict(cache)              # nothing new closed since the last run
    return rows, counts, new_cache
