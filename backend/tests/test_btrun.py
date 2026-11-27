"""Fast data checks (offline):  python tests/test_btrun.py

The point of these tests: a run that reuses saved months gives EXACTLY the same rows as working everything out
again, the parallel runner gives the same results as one-by-one, and the price archive keeps its first day.
"""
import json
import math
import os
import random
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

os.environ["EQL_DEMO"] = "1"
os.environ.setdefault("EQL_DATA_DIR", tempfile.mkdtemp())
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import btrun, entry, pricemap, store  # noqa: E402

store.init()


def _bars(n, seed=5, sd=0.018, start=date(2014, 1, 1), vol=2_000_000):
    rnd, c = random.Random(seed), 100.0
    days = [d for d in (start + timedelta(days=i) for i in range(n * 2)) if d.weekday() < 5][:n]
    out = []
    for d in days:
        o = c
        c *= 1 + rnd.gauss(0.0003, sd)
        out.append({"t": d.isoformat(), "o": o, "h": max(o, c) * 1.004, "l": min(o, c) * 0.996, "c": c, "v": vol})
    return out


def _pes(bars):
    return [(b["t"], 18 + 6 * math.sin(k / 40)) for k, b in enumerate(bars) if k % 7 == 0]


def _counting(mod, name):
    calls = [0]
    orig = getattr(mod, name)

    def wrapped(*a, **k):
        calls[0] += 1
        return orig(*a, **k)
    setattr(mod, name, wrapped)
    return calls, lambda: setattr(mod, name, orig)


def _same(a, b):
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_archive_keeps_first_day_and_restarts_on_revision():
    old = _bars(300)
    fresh = [dict(b) for b in old[50:]] + _bars(330, seed=5)[300:]        # window moved 50 days, 30 new days
    merged, restarted = btrun.merge_archive(old, fresh)
    assert not restarted and merged[0]["t"] == old[0]["t"] and merged[-1]["t"] == fresh[-1]["t"]
    assert len(merged) == 330 and len({b["t"] for b in merged}) == 330
    split = [dict(b, c=b["c"] / 2) if b["t"] < old[200]["t"] else b for b in fresh]   # a 1:2 split rescaled history
    merged2, restarted2 = btrun.merge_archive(old, split)
    assert restarted2 and merged2 == split
    assert btrun.merge_archive(None, fresh) == (fresh, False)


def test_fingerprint_ignores_float_noise_not_changes():
    a = _bars(50)
    b = [dict(x, c=x["c"] + 1e-9) for x in a]
    c = [dict(x, c=x["c"] * 1.001) if i == 10 else x for i, x in enumerate(a)]
    assert btrun.fingerprint(a) == btrun.fingerprint(b) != btrun.fingerprint(c)


def test_level_rows_reused_months_equal_full_run():
    bars = _bars(2300, seed=11, sd=0.02)
    rows1, cache = btrun.level_stock(bars, None)
    assert cache and cache["rows"] and rows1
    later = _bars(2345, seed=11, sd=0.02)                 # two more months of the same stock
    assert later[:2300] == bars
    calls, undo = _counting(pricemap, "level_ladder")
    full, _ = btrun.level_stock(later, None)
    n_full = calls[0]
    inc, cache2 = btrun.level_stock(later, cache)
    n_inc = calls[0] - n_full
    undo()
    assert _same(full, inc) and cache2["cut"] >= cache["cut"]
    assert n_inc * 4 < n_full                              # saved months really reused (only the open year redone)
    revised = [dict(b, c=b["c"] * 1.05) if i == 900 else b for i, b in enumerate(later)]   # an old price changed
    full_r, _ = btrun.level_stock(revised, None)
    inc_r, _ = btrun.level_stock(revised, cache)          # the saved months must be thrown away, not reused
    assert _same(full_r, inc_r)


def test_entry_rows_reused_months_equal_full_run():
    bars = _bars(3100, seed=21)
    nifty = _bars(3150, seed=99, sd=0.01)
    pes = _pes(bars)
    rows1, counts1, cache = btrun.entry_stock(bars, pes, nifty[:3100], None)
    assert cache and rows1 and counts1["illiquid"] == 0
    later = _bars(3160, seed=21)
    pes2 = _pes(later)
    calls, undo = _counting(entry, "decide")
    full = btrun.entry_stock(later, pes2, nifty, None)
    n_full = calls[0]
    inc = btrun.entry_stock(later, pes2, nifty, cache)
    n_inc = calls[0] - n_full
    undo()
    assert _same(full[0], inc[0]) and full[1] == inc[1]
    assert n_inc * 2 < n_full                              # only the last 36 months worked out again
    pes_rev = [(d, v * 1.2) if i == 30 else (d, v) for i, (d, v) in enumerate(pes2)]   # an old P/E point revised
    assert _same(btrun.entry_stock(later, pes_rev, nifty, None)[0], btrun.entry_stock(later, pes_rev, nifty, cache)[0])
    ver = dict(cache, ver="old rules")                      # rules changed: nothing reused
    assert _same(btrun.entry_stock(later, pes2, nifty, ver)[0], full[0])


def test_entry_month_matches_the_rule_engine():
    bars = _bars(1500, seed=4)
    c = [b["c"] for b in bars]
    pes = _pes(bars)
    i = 1200
    hist = [v for d, v in pes if d <= bars[i]["t"]]
    v = entry.decide(bars, i, pe_hist=hist, pe_now=hist[-1])
    kind, row = btrun.entry_month(bars, c, lambda j: sum(c[j - 199:j + 1]) / 200, i, pes, [d for d, _ in pes],
                                  [b["t"] for b in bars], c, entry.MIN_PE_POINTS)
    if v["verdict"] == "NA":
        assert kind is None
    else:
        assert kind == "row" and row["verdict"] == v["verdict"] and row["x12"] == 0.0     # vs itself as the benchmark


def test_parallel_runner_equals_one_by_one():
    syms = [f"S{k}" for k in range(6)] + ["BAD"]
    data = {s: _bars(2300 + 40 * k, seed=k) for k, s in enumerate(syms[:-1])}
    nifty = _bars(2600, seed=99, sd=0.01)

    def fetch(s):
        if s == "BAD":
            return None, "no volume data"
        return (data[s], _pes(data[s]), nifty, None), None

    def go(workers):
        got = {}
        btrun.run(syms, fetch, btrun.entry_stock, lambda s, r, why: got.__setitem__(s, r[0] if r else why), workers=workers)
        return got
    one, many = go(1), go(2)
    assert one["BAD"] == "no volume data" and set(one) == set(syms)
    assert _same(one, many)


def test_checks_run_by_themselves_after_a_month_end_outside_market_hours():
    from datetime import datetime
    from app import calendars, config, jobs, pricemap
    started = []
    real_start, real_status = jobs.start, jobs.status
    jobs.start = lambda n: started.append(n)
    jobs.status = lambda n: {"running": False}
    demo, config.DEMO = config.DEMO, False
    try:
        at = lambda *a: datetime(*a, tzinfo=calendars.IST)                     # noqa: E731
        store.put_company("LEVELS_TRACK::IN", {"built": "2026-11-25", "rules_version": pricemap.LEVEL_RULES_VERSION})
        store.put_company("ENTRY_TRACK::IN", {"built": "2026-11-25", "rules_version": entry.RULES_VERSION})
        assert jobs.due("levels", at(2026, 11, 28, 21))[0] is False            # same month: nothing new
        assert jobs.due("levels", at(2026, 12, 1, 21))[0] is False             # day 1: the month-end is not in the prices yet
        assert jobs.due("levels", at(2026, 12, 2, 21)) == (True, "a month has ended since the last run")
        assert jobs.auto_tick(at(2026, 12, 2, 11)) is None and not started     # Wednesday 11:00: market hours
        assert jobs.auto_tick(at(2026, 12, 2, 21)) == "levels"                 # evening: one check at a time
        assert jobs.auto_tick(at(2026, 12, 2, 22)) == "entry"
        assert jobs.auto_tick(at(2026, 12, 2, 23)) is None                     # each tried once a day
        jobs.set_auto("entry", False)
        assert jobs.auto_tick(at(2026, 12, 3, 21)) == "levels" and jobs.auto_tick(at(2026, 12, 3, 22)) is None
        store.put_company("ENTRY_TRACK::IN", {"built": "2026-12-03", "rules_version": -1})
        assert jobs.due("entry", at(2026, 12, 4, 21)) == (True, "rules changed since the last run")
        assert jobs.auto_status()["checks"]["entry"]["enabled"] is False
    finally:
        jobs.start, jobs.status, config.DEMO = real_start, real_status, demo


if __name__ == "__main__":
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f()
            print("PASS", k)
