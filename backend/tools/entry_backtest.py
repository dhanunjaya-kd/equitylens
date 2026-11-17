"""Track record of the entry decision engine (app/entry.py) on NIFTY 500 stocks.

    python tools\\entry_backtest.py            (about 30-60 minutes the first time; reuses saved data after)
    python tools\\entry_backtest.py --limit 40 (quick trial on 40 stocks)

At the end of every month since 2016, for every stock, it asks the engine for its verdict using
only data known on that day (prices up to that day, the stock's P/E history up to that day),
then measures what really happened over the next 6 and 12 months, against NIFTY 50.
The business check is NOT applied here: past business scores aren't available without
look-ahead. So this measures the value and timing rules; the business check is an extra
filter on top live.

Saves the summary to the app (it appears on every stock page) and to data/entry_track.json.
"""
from __future__ import annotations

import argparse
import bisect
import json
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import config, entry, service, store, technicals, universe  # noqa: E402

SPLIT = "2021-01-01"     # rules fixed before looking: 2016-2020 = first half, 2021 on = second half


def month_ends(bars, start="2016-01-01"):
    out = []
    for k in range(len(bars) - 1):
        if bars[k]["t"] >= start and bars[k]["t"][:7] != bars[k + 1]["t"][:7]:
            out.append(k)
    return out


def fwd(bars, i, n):
    return bars[i + n]["c"] / bars[i]["c"] - 1 if i + n < len(bars) else None


def bench_ret(nifty, d0, n_days):
    ts = [b["t"] for b in nifty]
    a = bisect.bisect_right(ts, d0) - 1
    if a < 0 or a + n_days >= len(nifty):
        return None
    return nifty[a + n_days]["c"] / nifty[a]["c"] - 1


def pe_series(sym):
    payload, ts = service.get_payload(sym, full=False, max_age_h=24 * 45)
    if time.time() - ts < 5:          # just downloaded from screener.in: be polite, like the scanner
        time.sleep(config.SCAN_DELAY_SECONDS)
    s = (payload["extras"].get("pe_chart") or {}).get("Price to Earning") or []
    return sorted((d, v) for d, v in s if v)


def summarize(rows):
    out = {}
    for key in ("r6", "r12", "x12"):
        vals = [r[key] for r in rows if r.get(key) is not None]
        if vals:
            vals.sort()
            out[key] = {"avg": round(statistics.mean(vals) * 100, 1), "median": round(statistics.median(vals) * 100, 1),
                        "worst10": round(vals[int(len(vals) * 0.1)] * 100, 1)}
    x = [r["x12"] for r in rows if r.get("x12") is not None]
    out["beat_nifty"] = round(sum(v > 0 for v in x) / len(x) * 100, 1) if x else None
    out["n"] = len(rows)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    if config.DEMO:
        sys.exit("Turn demo mode off first.")
    syms = [u["symbol"] for u in universe.load(download=True)[0]]
    if a.limit:
        syms = syms[: a.limit]
    nifty = technicals._latest_daily("^NSEI")
    print(f"{len(syms)} stocks, NIFTY bars {nifty[0]['t']} -> {nifty[-1]['t']}")

    rows, skipped, t0 = [], defaultdict(int), time.time()
    for n, sym in enumerate(syms, 1):
        try:
            bars, _, ohlc = technicals.get_bars(sym)
            if not ohlc or len(bars) < 400:
                skipped["short or close-only price history"] += 1
                continue
            pes = pe_series(sym)
        except Exception as e:  # noqa: BLE001
            skipped[f"fetch failed: {type(e).__name__}"] += 1
            continue
        if len(pes) < entry.MIN_PE_POINTS:
            skipped["P/E history too short"] += 1
            continue
        pe_dates = [d for d, _ in pes]
        for i in month_ends(bars):
            d = bars[i]["t"]
            k = bisect.bisect_right(pe_dates, d)
            if k < entry.MIN_PE_POINTS:
                continue
            hist = [v for _, v in pes[:k]]
            v = entry.decide(bars, i, pe_hist=hist, pe_now=hist[-1])
            if v["verdict"] == "NA":
                continue
            r12, b12 = fwd(bars, i, 252), bench_ret(nifty, d, 252)
            row = {"sym": sym, "date": d, "verdict": v["verdict"], "state": v["checks"]["value"]["state"],
                   "r6": fwd(bars, i, 126), "r12": r12, "x12": (r12 - b12) if r12 is not None and b12 is not None else None}
            if v["verdict"] == "WAIT" and v["zone"]:
                hi = v["zone"][1]
                j = next((j for j in range(i + 1, min(i + 127, len(bars))) if bars[j]["l"] <= hi), None)
                row["zone_hit"] = j is not None
                if j is not None and j + 252 < len(bars) and r12 is not None:
                    row["r12_zone"] = bars[j + 252]["c"] / min(hi, bars[j]["o"]) - 1
            if v["verdict"] == "PARTS" and v["plan"] and i + 252 < len(bars):
                cost, fills = [], 0
                for t in v["plan"]:
                    j = next((j for j in range(i, min(i + 127, len(bars))) if bars[j]["l"] <= t["price"]), None)
                    price = min(t["price"], bars[j]["o"]) if j is not None else bars[min(i + 126, len(bars) - 1)]["c"]
                    fills += j is not None
                    cost.append((t["pct"] / 100, price))
                end = bars[i + 252]["c"]
                row["r12_plan"] = sum(w * (end / p - 1) for w, p in cost)
                row["fills"] = fills
            rows.append(row)
        if n % 25 == 0:
            print(f"  {n}/{len(syms)} stocks · {len(rows)} monthly verdicts · {(time.time() - t0) / 60:.1f} min")

    result = {"built": time.strftime("%Y-%m-%d"), "stocks": len(syms) - sum(skipped.values()),
              "skipped": dict(skipped), "verdicts": len(rows), "split": SPLIT,
              "note": "NIFTY 500 as it is today (stocks that dropped out are missing, which flatters all verdicts equally). "
                      "Value and timing rules only; the business check is applied on top live.",
              "by_verdict": {}, "by_state": {}}
    for vd in ("ENTER", "PARTS", "WAIT"):
        sub = [r for r in rows if r["verdict"] == vd]
        blk = {"all": summarize(sub),
               "first_half": summarize([r for r in sub if r["date"] < SPLIT]),
               "second_half": summarize([r for r in sub if r["date"] >= SPLIT])}
        if vd == "WAIT":
            z = [r for r in sub if "zone_hit" in r]
            blk["zone_hit_rate"] = round(sum(r["zone_hit"] for r in z) / len(z) * 100, 1) if z else None
            pair = [r for r in sub if r.get("r12_zone") is not None]
            if pair:
                blk["r12_if_bought_now"] = round(statistics.mean(r["r12"] for r in pair) * 100, 1)
                blk["r12_if_bought_in_zone"] = round(statistics.mean(r["r12_zone"] for r in pair) * 100, 1)
        if vd == "PARTS":
            p = [r for r in sub if r.get("r12_plan") is not None]
            if p:
                blk["r12_plan"] = round(statistics.mean(r["r12_plan"] for r in p) * 100, 1)
                blk["r12_all_at_once"] = round(statistics.mean(r["r12"] for r in p) * 100, 1)
        result["by_verdict"][vd] = blk
    for st in entry.STATES:
        result["by_state"][st] = summarize([r for r in rows if r["state"] == st])

    store.put_company("ENTRY_TRACK::IN", result)
    (config.DATA_DIR / "entry_track.json").write_text(json.dumps(result, indent=1))

    print(f"\nDone in {(time.time() - t0) / 60:.1f} min · {result['verdicts']} monthly verdicts on {result['stocks']} stocks")
    print(f"{'verdict':8} {'n':>6} {'avg 12m':>8} {'median':>7} {'vs NIFTY':>9} {'beat %':>7} {'worst10%':>9}  | 1st half / 2nd half avg vs NIFTY")
    for vd, blk in result["by_verdict"].items():
        s, f, g = blk["all"], blk["first_half"], blk["second_half"]
        if not s.get("r12"):
            continue
        print(f"{vd:8} {s['n']:6} {s['r12']['avg']:7.1f}% {s['r12']['median']:6.1f}% {s['x12']['avg']:8.1f}% {s['beat_nifty']:6.1f}% "
              f"{s['r12']['worst10']:8.1f}%  | {f.get('x12', {}).get('avg')}% / {g.get('x12', {}).get('avg')}%")
    w = result["by_verdict"]["WAIT"]
    print(f"\nWAIT: price reached the buy zone within 6 months {w.get('zone_hit_rate')}% of the time; "
          f"12m return bought now {w.get('r12_if_bought_now')}% vs in the zone {w.get('r12_if_bought_in_zone')}%")
    p = result["by_verdict"]["PARTS"]
    print(f"PARTS: 12m return with the 3-part plan {p.get('r12_plan')}% vs all at once {p.get('r12_all_at_once')}%")
    print("By value: " + ", ".join(f"{k} {v.get('x12', {}).get('avg')}% vs NIFTY (n={v['n']})" for k, v in result["by_state"].items()))
    if skipped:
        print("Skipped:", dict(skipped))


if __name__ == "__main__":
    main()
