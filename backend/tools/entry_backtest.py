"""Track record of the entry decision engine (app/entry.py) on all NSE stocks.

    python tools\\entry_backtest.py                  (all NSE: 2-3 hours the first time; repeat runs reuse every closed month)
    python tools\\entry_backtest.py --universe N500  (NIFTY 500 only, about 30 minutes the first time)
    python tools\\entry_backtest.py --limit 40       (quick trial on 40 stocks)

At the end of every month since 2016, for every stock, it asks the engine for its verdict using
only data known on that day (prices up to that day, the stock's P/E history up to that day),
then measures what really happened over the next 6, 12, 24 and 36 months, against NIFTY 50
and against all tested stocks in the same month ("vs peers", the fair comparison).
Every call is also tagged NIFTY 500 / outside NIFTY 500 and reported per group, with "vs peers"
measured inside the group. A call is skipped when the stock was illiquid at the time (median daily
traded value over the previous 3 months under Rs 1 crore), since its prices may not have been tradable.
The business check is NOT applied here: past business scores aren't available without
look-ahead. So this measures the value and timing rules; the business check is an extra
filter on top live.

Runs on app/btrun.py: a fixed-start price archive, saved results for months whose 36-month window has closed,
prices downloaded 4 at a time and stocks worked out on all CPU cores (--workers N to change). The app also starts
it by itself after each month end (app/jobs.py).

Saves the summary to the app (it appears on every stock page) and to data/entry_track.json.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import threading
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import btrun, config, entry, service, store, technicals, universe  # noqa: E402

SPLIT = "2021-01-01"     # rules fixed before looking: 2016-2020 = first half, 2021 on = second half
MIN_MONTH_CALLS = 5      # a month counts only with at least this many calls
GROUPS = {"N500": "NIFTY 500", "OTHER": "Outside NIFTY 500"}
UNIVERSES = {"ALL": "All NSE stocks", "N500": "NIFTY 500 stocks"}


def pe_series(sym):
    payload, ts = service.get_payload(sym, full=False, max_age_h=24 * 45)
    if time.time() - ts < 5:          # just downloaded from screener.in: be polite, like the scanner
        time.sleep(config.SCAN_DELAY_SECONDS)
    s = (payload["extras"].get("pe_chart") or {}).get("Price to Earning") or []
    return sorted((d, v) for d, v in s if v)


def summarize(rows, halves=False):
    """Average / median / worst 10% for each return; 'p' keys are vs same-month peers."""
    out = {}
    for key in ("r6", "r12", "x12", "p12", "p24", "p36"):
        vals = sorted(r[key] for r in rows if r.get(key) is not None)
        if vals:
            out[key] = {"avg": round(statistics.mean(vals) * 100, 1), "median": round(statistics.median(vals) * 100, 1),
                        "worst10": round(vals[int(len(vals) * 0.1)] * 100, 1), "n": len(vals)}
    x = [r["x12"] for r in rows if r.get("x12") is not None]
    out["beat_nifty"] = round(sum(v > 0 for v in x) / len(x) * 100, 1) if x else None
    out["n"] = len(rows)
    # share of months in which this group's average beat its peers (months with >= 5 calls in the group)
    m = defaultdict(list)
    for r in rows:
        if r.get("p12") is not None:
            m[r["date"][:7]].append(r["p12"])
    ms = [statistics.mean(v) for v in m.values() if len(v) >= MIN_MONTH_CALLS]
    out["months"] = len(ms)
    out["months_beat_pct"] = round(sum(v > 0 for v in ms) / len(ms) * 100, 1) if ms else None
    if halves:
        out["first_half"] = summarize([r for r in rows if r["date"] < SPLIT])
        out["second_half"] = summarize([r for r in rows if r["date"] >= SPLIT])
    return out


def avg(blk, key="p12"):
    return (blk.get(key) or {}).get("avg")


def passes(blk, expect):
    """The test fixed before the rerun (17 Nov 2026): the rule's claim (beat or trail peers over 12 months)
    holds in BOTH halves, and in more than half of the months."""
    f, g, mb = avg(blk["first_half"]), avg(blk["second_half"]), blk.get("months_beat_pct")
    if f is None or g is None or mb is None:
        return None
    share = mb if expect > 0 else 100 - mb
    return bool(f * expect > 0 and g * expect > 0 and share > 50)


def peers(rows, key, out_key, by_group=False):
    """Return minus the average of all tested stocks in the same month (and group, if by_group)."""
    kf = (lambda r: (r["date"][:7], r["group"])) if by_group else (lambda r: r["date"][:7])
    by_month = defaultdict(list)
    for r in rows:
        if r.get(key) is not None:
            by_month[kf(r)].append(r[key])
    m_avg = {m: statistics.mean(v) for m, v in by_month.items() if len(v) >= MIN_MONTH_CALLS}
    for r in rows:
        m = m_avg.get(kf(r))
        r[out_key] = (r[key] - m) if (m is not None and r.get(key) is not None) else None


def by_groups(rows):
    """Per group, with 'vs peers' measured against the same group."""
    out = {}
    for g in GROUPS:
        sub = [dict(r, p12=r["g12"], p24=r["g24"], p36=r["g36"]) for r in rows if r["group"] == g]
        out[g] = summarize(sub, halves=True)
    return out


def wait_test(sub):
    """For falling stocks: buying at the first close back above the 200-day average vs buying at once,
    both measured to the same end date (cash at 0% if the turn never came within 12 months)."""
    w = [r for r in sub if "r12_wait" in r]
    if not w:
        return None
    return {"n": len(w), "turned_pct": round(sum(r["turned"] for r in w) / len(w) * 100, 1),
            "r12_bought_now": round(statistics.mean(r["r12"] for r in w) * 100, 1),
            "r12_waited": round(statistics.mean(r["r12_wait"] for r in w) * 100, 1),
            "waiting_won_pct": round(sum(r["r12_wait"] > r["r12"] for r in w) / len(w) * 100, 1)}


def value_test(by_state):
    vt = []
    for half in ("first_half", "second_half"):
        e, ch, fa = (avg(by_state[s][half], "p24") for s in ("Expensive", "Cheap", "Fair"))
        vt.append(None if None in (e, ch, fa) else (e < ch and e < fa))
    return None if None in vt else all(vt)


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
    nifty, _ = btrun.archived("^NSEI", technicals._latest_daily("^NSEI"))
    print(f"{len(syms)} stocks ({UNIVERSES[a.universe]}), NIFTY bars {nifty[0]['t']} -> {nifty[-1]['t']} · entry rules v{entry.RULES_VERSION}")

    rows, skipped, t0 = [], defaultdict(int), time.time()
    illiquid = 0
    pe_lock = threading.Lock()

    def fetch(sym):
        fresh, _, ohlc = technicals.get_bars(sym)
        if not ohlc or len(fresh) < 400:
            return None, "short or close-only price history"
        bars, _ = btrun.archived(sym, fresh)
        with pe_lock:                     # screener.in: one stock at a time, with the usual pause
            pes = pe_series(sym)
        if len(pes) < entry.MIN_PE_POINTS:
            return None, "P/E history too short"
        if not any(b.get("v") for b in bars[-btrun.LIQ_DAYS:]):
            return None, "no volume data"
        hit = store.get_company(f"BTCACHE::entry::{sym}")
        return (bars, pes, nifty, hit[1] if hit else None), None

    def on_result(sym, res, why):
        nonlocal illiquid
        if res is None:
            skipped[why] += 1
            return
        got, counts, cache = res
        if cache:
            store.put_company(f"BTCACHE::entry::{sym}", cache)
        illiquid += counts["illiquid"]
        if counts["bad"]:
            skipped["bad price data on a date"] += counts["bad"]
        grp = "N500" if sym in n500 else "OTHER"
        rows.extend(dict(r, sym=sym, group=grp) for r in got)

    btrun.run(syms, fetch, btrun.entry_stock, on_result, workers=a.workers, progress=lambda: f"{len(rows)} monthly verdicts")
    if not rows:
        sys.exit(f"No results (skipped: {dict(skipped)}). The saved result was kept as it was.")

    peers(rows, "r12", "p12")
    peers(rows, "r24", "p24")
    peers(rows, "r36", "p36")
    for k in ("12", "24", "36"):
        peers(rows, "r" + k, "g" + k, by_group=True)

    result = {"built": time.strftime("%Y-%m-%d"), "rules_version": entry.RULES_VERSION,
              "universe": a.universe, "universe_label": UNIVERSES[a.universe], "groups": GROUPS,
              "stocks": len(syms) - sum(skipped.values()), "skipped": dict(skipped), "verdicts": len(rows), "split": SPLIT,
              "illiquid_calls_skipped": illiquid,
              "liquidity_rule": "calls skipped when the median daily traded value over the previous 3 months was under Rs 1 crore",
              "note": "Stocks listed today only (companies that were delisted are missing, more so among small caps), so "
                      "absolute returns are flattered; compare 'vs peers' (return minus the average of all tested stocks "
                      "in the same month). Groups use today's NIFTY 500 list. Overlapping monthly windows: the number of "
                      "calls overstates how sure we can be. The business check and the results warning are not tested.",
              "pass_test": "The rule's claim (beat or trail peers over 12 months) holds in both halves "
                           "(2016-20 and 2021 on) and in more than half of the months. Fixed before the rerun.",
              "by_verdict": {}, "by_rule": {}, "by_state": {}}
    for vd in ("ENTER", "AVOID"):
        result["by_verdict"][vd] = summarize([r for r in rows if r["verdict"] == vd], halves=True)
        result["by_verdict"][vd]["groups"] = by_groups([r for r in rows if r["verdict"] == vd])
    for ru, expect in entry.EXPECT.items():
        sub = [r for r in rows if r["rule"] == ru]
        blk = summarize(sub, halves=True)
        blk["expect"] = "beat peers" if expect > 0 else "trail peers"
        blk["passed"] = passes(blk, expect) if sub else None
        blk["groups"] = by_groups(sub)
        for gb in blk["groups"].values():          # shown for information; pass/fail is decided on the whole run
            gb["claim_held"] = passes(gb, expect) if gb["n"] else None
        if ru == "avoid_falling":
            blk["wait_test"] = wait_test(sub)
            for g in GROUPS:
                blk["groups"][g]["wait_test"] = wait_test([r for r in sub if r["group"] == g])
        result["by_rule"][ru] = blk
    for st in entry.STATES:
        result["by_state"][st] = summarize([r for r in rows if r["state"] == st], halves=True)
    result["by_state_groups"] = {g: {st: summarize([dict(r, p12=r["g12"], p24=r["g24"], p36=r["g36"]) for r in rows
                                                    if r["group"] == g and r["state"] == st], halves=True)
                                      for st in entry.STATES} for g in GROUPS}
    # Value test fixed before the NIFTY 500 rerun: Expensive trails BOTH Cheap and Fair at 24 months,
    # in both halves. Passed: Expensive shows a caution (it still does not change the verdict).
    bs = result["by_state"]
    result["value_test"] = {"rule": "Expensive trails both Cheap and Fair at 24m vs peers, in both halves",
                            "passed": value_test(bs),
                            "groups": {g: value_test(result["by_state_groups"][g]) for g in GROUPS}}

    store.put_company("ENTRY_TRACK::IN", result)
    (config.DATA_DIR / "entry_track.json").write_text(json.dumps(result, indent=1))

    fmt = lambda x: "  n/a" if x is None else f"{x:5.1f}%"
    print(f"\nDone in {(time.time() - t0) / 60:.1f} min · {UNIVERSES[a.universe]} · {result['verdicts']} monthly verdicts "
          f"on {result['stocks']} stocks · {illiquid} calls skipped as illiquid (< Rs 1 crore/day)")
    print("'vs peers' = return minus the average of ALL tested stocks in the same month (the fair comparison)")
    print(f"\n{'rule':16} {'n':>6} {'12m vs peers':>12} {'median':>7} {'2016-20':>8} {'2021-':>7} {'months beat':>11} "
          f"{'24m vs peers':>12} {'36m':>7}  claim / passed")
    for ru, b in result["by_rule"].items():
        if not b.get("p12"):
            print(f"{ru:16} {b['n']:6}  (no 12-month results)")
            continue
        print(f"{ru:16} {b['n']:6} {fmt(avg(b)):>12} {fmt(b['p12']['median']):>7} {fmt(avg(b['first_half'])):>8} "
              f"{fmt(avg(b['second_half'])):>7} {fmt(b['months_beat_pct']):>11} {fmt(avg(b, 'p24')):>12} {fmt(avg(b, 'p36')):>7}"
              f"  {b['expect']} / {'YES' if b['passed'] else 'NO' if b['passed'] is False else 'n/a'}")
    for g, gl in GROUPS.items():
        print(f"\n{gl} (vs peers inside the group; information only, pass/fail uses the whole run):")
        for ru, b in result["by_rule"].items():
            gb = b["groups"][g]
            if gb.get("p12"):
                print(f"  {ru:16} n={gb['n']:6}  12m {fmt(avg(gb))}  2016-20 {fmt(avg(gb['first_half']))}  "
                      f"2021- {fmt(avg(gb['second_half']))}  months beat {fmt(gb['months_beat_pct'])}  24m {fmt(avg(gb, 'p24'))}"
                      f"  claim held: {'YES' if gb['claim_held'] else 'NO' if gb['claim_held'] is False else 'n/a'}")
    af = result["by_rule"]["avoid_falling"]
    for label, wt in [("All", af.get("wait_test"))] + [(gl, af["groups"][g].get("wait_test")) for g, gl in GROUPS.items()]:
        if wt:
            print(f"\nAVOID (falling), {label}: if you had waited for the turn instead - it came within 12 months "
                  f"{wt['turned_pct']}% of the time; same end date: bought at once {wt['r12_bought_now']}% vs waited "
                  f"{wt['r12_waited']}% (waiting won {wt['waiting_won_pct']}% of the time)")
    ow = af["groups"]["OTHER"].get("wait_test")
    if ow and ow["r12_waited"] > ow["r12_bought_now"]:
        print("  CHECK (fixed 17 Nov): outside NIFTY 500 waiting for the turn WON - falling stocks there should go back to WAIT.")
    print("\nBy value (information only):")
    for st, b in bs.items():
        print(f"  {st:9} n={b['n']:6}  12m vs peers {fmt(avg(b))}  24m {fmt(avg(b, 'p24'))} "
              f"(2016-20 {fmt(avg(b['first_half'], 'p24'))}, 2021- {fmt(avg(b['second_half'], 'p24'))})  36m {fmt(avg(b, 'p36'))}")
    yn = lambda x: 'YES' if x else 'NO' if x is False else 'n/a'
    for g, gl in GROUPS.items():
        print(f"  {gl}: " + ", ".join(f"{st} 24m {fmt(avg(b, 'p24'))}" for st, b in result["by_state_groups"][g].items()))
    print(f"Value test ({result['value_test']['rule']}): {yn(result['value_test']['passed'])}"
          f" · NIFTY 500 {yn(result['value_test']['groups']['N500'])} · outside NIFTY 500 {yn(result['value_test']['groups']['OTHER'])}")
    if skipped:
        print("Skipped:", dict(skipped))


if __name__ == "__main__":
    main()
