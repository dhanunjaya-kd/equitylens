"""Do support/resistance levels that held before hold again? Tests the Price map's levels on NSE stocks.

    Normally started from the app: Price map tab -> "Run the test". From a terminal:
    python tools\\levels_backtest.py

The rules were fixed before any run (21 Nov 2026) and are in app/pricemap.py (LEVEL_* constants):
  - At every month end, the nearest support and resistance ZONE are built exactly like the Price map (rules v2),
    from prices up to that day only. Their record so far puts them in a bucket:
    untested · 1-2 tests · 3+ tests held under 50% · 3+ tests held 50-74% · 3+ tests held 75%+.
  - The outcome is the NEXT test of that zone after that day: held (a 2 ATR move away before a close 0.5 ATR
    through, within 20 sessions) or broken. Untested within 252 sessions, or unresolved, is not counted.
    Each test is counted once.
  - PASS (per side): "3+ tests, held 75%+" held again 10+ points more often than "3+ tests, held under 50%"
    and 5+ points more often than all levels, in both halves (tests before 2021 / from 2021), with 100+ tests
    in each of those two buckets in each half.
  - Chance test: next to every real zone, a random-price zone (same side and width, random distance, not
    overlapping a real zone) is tested with the same rules. Compared inside the same distance bands, real zones
    pass if they held 5+ points more often, in both halves, with 100+ tests of each.
  - A month end is skipped when the stock was illiquid (median daily traded value over the previous 3 months
    under Rs 1 crore), same as the entry backtest.

Runs on app/btrun.py: a fixed-start price archive, saved results for months whose forward window has closed,
prices downloaded 4 at a time and stocks worked out on all CPU cores (--workers N to change). The app also starts
it by itself after each month end (app/jobs.py).

Saves the result to the app (it appears on every Price map) and to data/levels_track.json.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import btrun, config, pricemap, store, technicals, universe  # noqa: E402

UNIVERSES = {"ALL": "All NSE stocks", "N500": "NIFTY 500 stocks"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--universe", choices=list(UNIVERSES), default="ALL")
    ap.add_argument("--workers", type=int, default=0, help="CPU workers (default: all cores but one)")
    a = ap.parse_args()
    if config.DEMO:
        sys.exit("Turn demo mode off first.")
    store.init()
    n500 = {u["symbol"] for u in universe.index_list("N500")}
    syms = [u["symbol"] for u in universe.index_list(a.universe)]
    if a.universe == "ALL" and len(syms) <= len(n500):
        sys.exit("Could not download NSE's full list of stocks (EQUITY_L.csv). Try again in a few minutes.")
    if a.limit:
        syms = syms[: a.limit]
    print(f"{len(syms)} stocks ({UNIVERSES[a.universe]}) · level rules v{pricemap.LEVEL_RULES_VERSION} · {a.workers or btrun.default_workers()} CPU workers")
    skipped, t0 = defaultdict(int), time.time()
    rows: list = []
    ntests = [0]

    def fetch(sym):
        fresh, _, ohlc = technicals.get_bars(sym)
        if not ohlc:
            return None, "short or close-only price history"
        bars, _ = btrun.archived(sym, fresh)
        if len(bars) < pricemap.SWING_BARS + 300:
            return None, "short or close-only price history"
        if not any(b.get("v") for b in bars[-btrun.LIQ_DAYS:]):
            return None, "no volume data"
        hit = store.get_company(f"BTCACHE::levels::{sym}")
        return (bars, hit[1] if hit else None), None

    def on_result(sym, res, why):
        nonlocal rows
        if res is None:
            skipped[why] += 1
            return
        got, cache = res
        if cache:
            store.put_company(f"BTCACHE::levels::{sym}", cache)
        grp = "N500" if sym in n500 else "OTHER"
        rows += [dict(r, sym=sym, group=grp) for r in got]
        ntests[0] += sum(1 for r in got if not r.get("placebo") and not r.get("skip"))

    btrun.run(syms, fetch, btrun.level_stock, on_result, workers=a.workers,
              progress=lambda: f"{ntests[0]} level tests")
    if not rows:
        sys.exit(f"No results (skipped: {dict(skipped)}). The saved result was kept as it was.")

    res = pricemap.summarize_levels(rows)
    groups = {g: pricemap.summarize_levels([r for r in rows if r["group"] == g]) for g in ("N500", "OTHER")}
    result = {"built": time.strftime("%Y-%m-%d"), "rules_version": pricemap.LEVEL_RULES_VERSION,
              "universe": a.universe, "universe_label": UNIVERSES[a.universe],
              "test_version": pricemap.TEST_VERSION,
              "stocks": len({r["sym"] for r in rows}), "skipped": dict(skipped),
              "tests": sum(1 for r in rows if not r.get("placebo") and not r.get("skip")),
              "random_tests": sum(1 for r in rows if r.get("placebo")),
              "split": pricemap.LEVEL_SPLIT,
              "result": res, "groups": groups,
              "pass_test": "Per side: levels that held 75%+ of 3+ earlier tests held again 10+ points more often than levels "
                           "that held under 50%, and 5+ points more often than all levels, in both halves (before 2021 / "
                           "from 2021), with 100+ tests in each of those buckets in each half. Fixed before any run.",
              "chance_test": "Per side: real zones held at their next test at least 5 points more often than random-price zones "
                             "of the same width, compared within the same distance bands (weighted by real tests), not "
                             "overlapping a real zone, same rules; in both halves, with 100+ tests of each in each half. "
                             "Fixed before the run.",
              "note": "Stocks listed today only (delisted companies are missing). Price history from about 2016, and a level "
                      "needs 2 years of prices first, so the first half is roughly 2018-2020. Tests of the same stock are "
                      "not independent, so the count overstates how sure this is."}
    store.put_company("LEVELS_TRACK::IN", result)
    (config.DATA_DIR / "levels_track.json").write_text(json.dumps(result, indent=1))

    pc = lambda x: "  n/a" if x is None else f"{x:5.1f}%"
    print(f"\nDone in {(time.time() - t0) / 60:.1f} min · {result['tests']} level tests on {result['stocks']} stocks · skipped {dict(skipped)}")
    for side in ("support", "resistance"):
        b = res[side]
        print(f"\n{side.upper()}: all levels held at the next test {pc(b['all']['held_pct'])} (n={b['all']['n']}) · "
              f"before 2021 {pc(b['halves']['first_half']['held_pct'])} · from 2021 {pc(b['halves']['second_half']['held_pct'])}")
        print(f"  {'record before the test':28} {'n':>7} {'held next':>9} {'before 2021':>12} {'from 2021':>10}")
        for k in pricemap.BUCKETS_L:
            x = b["buckets"][k]
            print(f"  {k:28} {x['n']:7} {pc(x['held_pct']):>9} {pc(x['first_half']['held_pct']):>12} {pc(x['second_half']['held_pct']):>10}")
        print("  zones with one kind vs 2+ kinds of level: " + " · ".join(f"{k} {pc(v['held_pct'])} (n={v['n']})" for k, v in b["confluence"].items()))
        print("  by kind of level: " + " · ".join(f"{s} {pc(v['held_pct'])} (n={v['n']})" for s, v in b["sources"].items()))
        if b.get("random"):
            print(f"  edge over random prices at the same distance: {b.get('edge_pts')} pts · before 2021 {b['edge_by_half'].get('first_half')} · from 2021 {b['edge_by_half'].get('second_half')}")
            rp = b.get("random_placed") or {}
            print(f"  random zones could be placed (a free price with no real zone) for {rp.get('pct')}% of {rp.get('tried')} real zones")
            print(f"  random-price zones held {pc(b['random']['held_pct'])} (n={b['random']['n']}) · before 2021 {pc(b['random']['halves']['first_half']['held_pct'])} · from 2021 {pc(b['random']['halves']['second_half']['held_pct'])}")
        yn = lambda x: 'YES' if x else 'NO' if x is False else 'n/a (too few tests)'
        print(f"  zone record predicts the next test: {yn(b['passed'])} · real zones beat random prices: {yn(b.get('beats_chance'))}")


if __name__ == "__main__":
    main()
