"""Price map: levels, hold rates, fall cases, turn signals (offline):  python tests/test_pricemap.py"""
import os
import random
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

os.environ["EQL_DEMO"] = "1"
os.environ.setdefault("EQL_DATA_DIR", tempfile.mkdtemp())
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import pricemap as pmap, store  # noqa: E402

store.init()


def _bars(closes, vol=1_000_000, spread=0.005):
    d0 = date(2016, 1, 4)
    days = [d for d in (d0 + timedelta(days=i) for i in range(len(closes) * 2)) if d.weekday() < 5][:len(closes)]
    return [{"t": d.isoformat(), "o": c, "h": c * (1 + spread), "l": c * (1 - spread), "c": c, "v": vol} for d, c in zip(days, closes)]


def _walk(n, seed=3, sd=0.015):
    rnd, c, out = random.Random(seed), 100.0, []
    for _ in range(n):
        c *= 1 + rnd.gauss(0.0003, sd)
        out.append(c)
    return out


def test_stage_bands():
    assert pmap.stage(0.5) == "At its high" and pmap.stage(5) == "Pullback"
    assert pmap.stage(10) == "Correction" and pmap.stage(20) == "Correction" and pmap.stage(20.1) == "Bear phase"


def _hlc(c, w=0.3):
    return [x + w for x in c], [x - w for x in c], c


def test_support_held_and_broken_on_atr_scale():
    # ATR fixed at 1: test = low within 0.25 of the zone top; held = high 2 above it; broken = close 0.5 below the bottom
    c = [110] * 5 + [105, 102, 100.3, 101, 102.5, 104, 106, 108, 110] + [110] * 6 + [106, 103, 100.2, 99.2, 98, 97] + [97] * 30
    h, l, _ = _hlc(c)
    r = pmap.tests(h, l, c, [1.0] * len(c), 100.0, 100.0, "support", 1)
    assert (r["tests"], r["held"], r["broken"]) == (2, 1, 1)


def test_same_move_is_not_a_test_on_a_wilder_stock():
    # the same 2.5-point bounce is a "held" test when ATR is 1, but not resolved when ATR is 3 (needs 6 away)
    c = [110] * 5 + [105, 102, 100.3, 101, 102.5, 101.5] + [101.5] * 30
    h, l, _ = _hlc(c)
    assert pmap.tests(h, l, c, [1.0] * len(c), 100.0, 100.0, "support", 1)["held"] == 1
    assert pmap.tests(h, l, c, [3.0] * len(c), 100.0, 100.0, "support", 1)["tests"] == 0


def test_tests_are_five_sessions_apart():
    # price bounces off 100 every 3 sessions: only every other touch can count
    c = [106] * 3
    for _ in range(8):
        c += [100.2, 103, 106]
    c += [106] * 25
    h, l, _ = _hlc(c, 0.1)
    r = pmap.tests(h, l, c, [1.0] * len(c), 100.0, 100.0, "support", 1)
    starts = [i for i, _ in r["events"]]
    assert r["tests"] >= 2 and all(b - a >= pmap.TEST_GAP for a, b in zip(starts, starts[1:]))
    assert r["tests"] < 8


def test_resistance_needs_approach_from_below():
    c = [90, 92, 95, 99.9, 96, 93, 92, 92, 95, 99.8, 101, 102, 103] + [103] * 25
    h, l, _ = _hlc(c, 0.1)
    r = pmap.tests(h, l, c, [1.0] * len(c), 100.0, 100.0, "resistance", 1)
    assert (r["tests"], r["held"], r["broken"]) == (2, 1, 1)


def test_unresolved_test_is_not_counted():
    c = [110, 105, 100.3] + [100.6] * 30        # sits on the zone, never 2 ATR away, never 0.5 ATR through
    h, l, _ = _hlc(c, 0.1)
    assert pmap.tests(h, l, c, [1.0] * len(c), 100.0, 100.0, "support", 1)["tests"] == 0


def test_zigzag_major_swings_only_and_never_the_one_forming():
    # wiggles of 2% are not swings when the threshold is 5%; the final drop's low is still forming
    c = [100 + (2 if k % 2 else 0) for k in range(40)] + [100 + 2 * k for k in range(1, 16)] + [130 - 3 * k for k in range(1, 9)]
    h, l, _ = _hlc(c, 0.01)
    atr = [0.1] * len(c)                         # tiny ATR -> the 5% floor applies
    zz = pmap.zigzag(h, l, atr, c)
    assert [p["kind"] for p in zz] == ["low", "high"]
    assert abs(zz[-1]["price"] - 130.01) < 1e-6 and zz[-1]["confirmed"] > zz[-1]["i"]
    assert all(p["i"] < len(c) - 1 for p in zz)


def test_volume_profile_value_area_holds_70_percent():
    c = [100.0] * 150 + [120.0] * 100 + [110.0] * 10
    bars = _bars(c, vol=1000, spread=0.001)
    for b in bars[:150]:
        b["v"] = 3000                              # most volume traded near 100
    h = [b["h"] for b in bars]; l = [b["l"] for b in bars]; v = [b["v"] for b in bars]
    vp = pmap.volume_profile(h, l, c, v)
    assert vp["poc"][0] <= 100.1 and vp["poc"][1] >= 99.9 and vp["val"] <= 100 < vp["vah"]


def test_unfilled_gap_and_recent_52w_low_rules():
    c = [100.0] * 300 + [110.0] * 40 + [108.0] * 3 + [104.0]
    bars = _bars(c, spread=0.002)
    atr = pmap.atr_series([b["h"] for b in bars], [b["l"] for b in bars], c)
    cand = pmap.candidates(bars, atr)
    gaps = [x for x in cand if x["src"] == "gap"]
    assert gaps and abs(gaps[0]["lo"] - 100.2) < 0.01 and gaps[0]["hi"] <= 110 * 0.998 + 1e-9
    lows = [x for x in cand if x["what"].startswith("52-week low")]
    assert lows                                                       # the old low, not today's
    bars2 = _bars(c[:-1] + [90.0], spread=0.002)                      # new 52-week low today: not a level yet
    atr2 = pmap.atr_series([b["h"] for b in bars2], [b["l"] for b in bars2], [b["c"] for b in bars2])
    assert not [x for x in pmap.candidates(bars2, atr2) if x["what"].startswith("52-week low")]


def test_fall_cases_exclude_the_fall_still_running():
    up = [100 * 1.001 ** i for i in range(300)]
    top = up[-1]
    fall1 = [top * (1 - 0.01 * k) for k in range(1, 26)]           # -25%
    rec = [fall1[-1] * 1.02 ** k for k in range(1, 40)]           # back to a new high
    rec = [x for x in rec if x < top * 1.2] + [top * 1.25]
    top2 = rec[-1]
    fall2 = [top2 * (1 - 0.01 * k) for k in range(1, 18)]          # -17%, still running
    c = up + fall1 + rec + [top2] * 5 + fall2
    cases = pmap.fall_cases(_bars(c), 0.15)
    assert len(cases) == 1                                       # only the finished fall
    x = cases[0]
    assert x["further_pct"] < -10 and x["days_to_low"] > 0 and x["recovered"]


def test_too_few_cases_gives_no_percentages():
    few = [{"further_pct": -5.0, "days_to_low": 10, "back_in_3m": True}] * 9
    s = pmap.summarize_cases(few)
    assert s["n"] == 9 and not s["enough"] and "median" not in s and sum(b["n"] for b in s["buckets"]) == 9
    many = few + [{"further_pct": -20.0, "days_to_low": 40, "back_in_3m": False}]
    s = pmap.summarize_cases(many)
    assert s["enough"] and s["worst"] == 20.0 and s["back_3m_pct"] == 90


def test_signals_use_no_future_bars():
    c = _walk(1500)
    base = _bars(c)
    book = pmap.SignalBook(base, _bars(_walk(1500, seed=9)))
    i = 1100
    before = {k: book.on(k, i) for k, _ in pmap.SIGNALS}
    changed = base[:i + 1] + [dict(b, c=b["c"] * 3, h=b["h"] * 3, l=b["l"] * 0.3, v=b["v"] * 9) for b in base[i + 1:]]
    book2 = pmap.SignalBook(changed, _bars(_walk(1500, seed=9)))
    assert before == {k: book2.on(k, i) for k, _ in pmap.SIGNALS}


def test_signal_record_has_counts_and_honest_verdict():
    book = pmap.SignalBook(_bars(_walk(2500, sd=0.025)))
    for k, _ in pmap.SIGNALS[:4]:
        r = book.record(k)
        assert "n" in r and r["base_n"] > 0
        if r["n"] < pmap.MIN_CASES:
            assert r["verdict"] == "too_few" and "up_pct" not in r
        else:
            assert r["verdict"] in ("better", "same", "worse")
    assert book.on("sector_up", 2000) is None          # no sector series -> unknown, not "no"


def test_sector_mapping():
    assert pmap.sector_ticker("IN", ["Financial Services", "Finance", "Non Banking Financial Company (NBFC)"])["ticker"] == "NIFTY_FIN_SERVICE.NS"
    assert pmap.sector_ticker("IN", ["Financial Services", "Banks", "Private Sector Bank"])["ticker"] == "^NSEBANK"
    assert pmap.sector_ticker("IN", ["Information Technology", "IT - Software", "Computers - Software & Consulting"])["ticker"] == "^CNXIT"
    assert pmap.sector_ticker("US", ["United States", "SEMICONDUCTORS & RELATED DEVICES"])["ticker"] == "SMH"
    assert pmap.sector_ticker("IN", ["Diversified", "Something new"]) is None


def test_ladder_levels_sit_on_the_right_side():
    bars = _bars(_walk(900, seed=5))
    lv = pmap.level_ladder(bars)
    band = pmap.BAND_ATR * lv["atr"]
    assert all(x["lo"] - band > lv["price"] for x in lv["resistance"]) and all(x["hi"] + band < lv["price"] for x in lv["support"])
    assert all(0 <= x["held"] <= x["tests"] for x in lv["resistance"] + lv["support"])
    assert all(x["hi"] - x["lo"] <= pmap.MAX_ZONE_ATR * lv["atr"] + 1e-6 for x in lv["resistance"] + lv["support"])


def test_build_on_demo_stock():
    from app import service, technicals
    rep = service.build_report("TESTCO")
    bars, _, _ = technicals.get_bars("TESTCO")
    d = pmap.build(rep, bars, refresh=True)
    assert d["where"]["stage"] in ("At its high", "Pullback", "Correction", "Bear phase")
    assert len(d["signals"]) == 5 and d["sector"]["answer"] and d["business"]["plus"]
    assert "Held" in d["rules"]


def test_ai_research_checks_its_numbers():
    from app import ai, service, technicals
    rep = service.build_report("TESTCO")
    bars, _, _ = technicals.get_bars("TESTCO")
    r = ai.pricemap_research(rep, pmap.build(rep, bars), refresh=True)
    assert r["structured"] and r["numbers"]["checked"] > 0 and r["numbers"]["found"] == r["numbers"]["checked"]
    n, miss = ai.verify_numbers("support at 987654.3", ai.json.dumps({"x": 1}))
    assert n == 1 and miss == ["987654.3"]


def test_level_buckets():
    assert pmap.bucket(0, 0) == "untested" and pmap.bucket(2, 2) == "1-2 tests"
    assert pmap.bucket(4, 1) == "3+ tests, held under 50%" and pmap.bucket(4, 2) == "3+ tests, held 50-74%"
    assert pmap.bucket(4, 3) == "3+ tests, held 75%+" and pmap.bucket(3, 2) == "3+ tests, held 50-74%"


def test_level_samples_use_no_future_and_count_each_test_once():
    bars = _bars(_walk(2000, seed=11, sd=0.02))
    rows = [r for r in pmap.level_samples(bars) if not r.get("skip")]
    assert rows
    keys = [(r["side"], r["source"], r["date"]) for r in rows]
    assert len(keys) == len(set(keys))
    assert all(r["seen"] < r["date"] for r in rows)                 # the test comes after the day the level was seen
    k = 1500
    cut = bars[k - 25]["t"]                                         # a test resolves within 20 sessions
    changed = bars[:k] + [dict(b, c=b["c"] * 0.5, h=b["h"] * 0.5, l=b["l"] * 0.5) for b in bars[k:]]
    a = [r for r in rows if r["date"] < cut]
    b = [r for r in pmap.level_samples(changed) if not r.get("skip") and r["date"] < cut]
    assert a and a == b


def _lv(side, bucket, held, date):
    return {"side": side, "bucket": bucket, "held": held, "date": date, "source": "swing"}


def _half(date, strong_pct, weak_pct, other_pct, n=200):
    out = []
    for b, p in (("3+ tests, held 75%+", strong_pct), ("3+ tests, held under 50%", weak_pct), ("1-2 tests", other_pct)):
        out += [_lv("support", b, i < n * p / 100, date) for i in range(n)]
    return out


def test_level_pass_rule_is_the_fixed_one():
    ok = _half("2019-06-01", 70, 50, 55) + _half("2023-06-01", 68, 52, 55)
    assert pmap.summarize_levels(ok)["support"]["passed"] is True
    small_gap = _half("2019-06-01", 70, 62, 55) + _half("2023-06-01", 70, 62, 55)       # only 8 points over weak
    assert pmap.summarize_levels(small_gap)["support"]["passed"] is False
    one_half = _half("2019-06-01", 70, 50, 55) + _half("2023-06-01", 55, 50, 55)        # fails in the second half
    assert pmap.summarize_levels(one_half)["support"]["passed"] is False
    thin = _half("2019-06-01", 70, 50, 55, n=60) + _half("2023-06-01", 70, 50, 55, n=60)
    assert pmap.summarize_levels(thin)["support"]["passed"] is None                    # under 100 tests: no verdict
    assert pmap.summarize_levels(ok)["resistance"]["passed"] is None


def test_layers_answer():
    assert pmap.layers_answer(5, 20, 20).startswith("The stock is 5.0%")
    assert pmap.layers_answer(15, 12, 11).startswith("Broad fall")
    assert pmap.layers_answer(15, 12, 3).startswith("Sector fall")
    assert pmap.layers_answer(15, 4, 12).startswith("Market fall")
    assert pmap.layers_answer(15, 2, 3).startswith("Mostly this stock")
    assert pmap.layers_answer(15, None, None).startswith("No sector")


def test_value_floor_record_matches_pe_state_only():
    st = {k: {"n": 120, "p12": {"avg": 1.0}, "p24": {"avg": -2.0}, "p36": {"avg": 3.0}} for k in ("Cheap", "Fair", "Full", "Expensive")}
    rep = {"market": "IN", "analysis": {"entry": {
        "checks": {"value": {"state": "Full", "pe_state": "Fair", "fv_state": "Full", "pe_percentile": 44}},
        "levels": {"value_edges": {"cheap": 90.0, "fair": 110.0, "full": 130.0}},
        "group": "N500", "track": {"by_state_groups": {"N500": st}, "groups": {"N500": "NIFTY 500"}, "built": "2026-11-17",
                                   "value_test": {"passed": True, "rule": "r"}}}}}
    v = pmap.value_floor(rep)
    assert v["ranges"][0] == {"state": "Cheap", "below": 90.0} and v["ranges"][3] == {"state": "Expensive", "above": 130.0}
    assert v["record"]["Fair"]["p24"] == -2.0 and v["record"]["Fair"]["n"] == 120 and "P/E state only" in v["record_basis"]
    rep["analysis"]["entry"]["track"] = None
    assert pmap.value_floor(rep)["record"] is None
    rep["analysis"]["entry"]["levels"]["value_edges"] = None
    assert pmap.value_floor(rep)["ranges"] is None


def test_market_layer_and_untested_levels_on_demo():
    from app import service, technicals
    rep = service.build_report("TESTCO")
    bars, _, _ = technicals.get_bars("TESTCO")
    d = pmap.build(rep, bars, refresh=True)
    assert d["market"]["name"] == "NIFTY 50" and d["market"]["fall_pct"] is not None and d["sector"]["layers"]
    assert d["level_track"] is None                                    # nothing invented before the backtest runs
    assert all(r["bucket"] in pmap.BUCKETS_L for r in d["levels"]["support"] + d["levels"]["resistance"])


def test_old_level_results_are_marked_stale():
    store.put_company("LEVELS_TRACK::IN", {"built": "2026-11-21", "rules_version": pmap.LEVEL_RULES_VERSION - 1, "result": {}})
    assert pmap.level_track("IN")["stale"] is True
    store.put_company("LEVELS_TRACK::IN", {"built": "2026-11-21", "rules_version": pmap.LEVEL_RULES_VERSION, "result": {}, "tests": 5})
    assert "stale" not in pmap.level_track("IN") and pmap.level_track("US")["market_note"]
    with store._conn() as c:
        c.execute("DELETE FROM company WHERE symbol='LEVELS_TRACK::IN'")


def test_job_status_reads_progress_and_finish_from_the_log():
    from app import jobs, config
    log = config.DATA_DIR / "job_levels.log"
    log.write_text("1541 stocks (All NSE stocks) · level rules v2\n  410/1541 stocks · 9120 level tests · 6.2 min\n", encoding="utf-8")
    st = jobs.status("levels")
    assert st["running"] and st["progress"] == {"done": 410, "total": 1541} and not st["failed"]
    log.write_text(log.read_text(encoding="utf-8") + "\nDone in 31.0 min · 50000 level tests\n", encoding="utf-8")
    st = jobs.status("levels")
    assert st["finished"] and not st["running"] and not st["failed"]
    log.write_text("Turn demo mode off first.\n", encoding="utf-8")
    import os, time as _t
    os.utime(log, (_t.time() - 3600, _t.time() - 3600))
    assert jobs.status("levels")["failed"]
    log.unlink()


def test_random_zones_copy_width_and_never_overlap_real_zones():
    import random
    made = 0
    for w in range(1, 15):
      bars = _bars(_walk(1200, seed=w, sd=0.02))
      lad = pmap.level_ladder(bars)
      real = [(z["lo"], z["hi"]) for z in lad["support"] + lad["resistance"] + lad["inside"]]
      gap = pmap.BAND_ATR * lad["atr"]
      for row in lad["support"][:1] + lad["resistance"][:1]:
        for seed in range(10):
            pz = pmap._placebo(row, lad, random.Random(seed))
            if not pz:
                continue
            made += 1
            lo, hi, x = pz
            assert abs((hi - lo) - (row["hi"] - row["lo"])) < 1e-9                       # same width
            assert all(hi + gap < a or lo - gap > b for a, b in real)                     # clear of every real zone
            assert (hi < lad["price"]) if row["kind"] == "support" else (lo > lad["price"])  # same side
            assert pz == pmap._placebo(row, lad, random.Random(seed))                     # repeatable
    assert made > 0


def _cz(side, placebo, held, date, d):
    return {"side": side, "placebo": placebo, "held": held, "date": date, "dist_atr": d, "source": "random" if placebo else "zigzag",
            "bucket": None if placebo else "1-2 tests", "sources": 0 if placebo else 1}


def _crowd(date, real_pct, rand_pct, d_real, d_rand, n=150):
    rows = [_cz("support", False, i < n * real_pct / 100, date, d_real) for i in range(n)]
    rows += [_cz("support", True, i < n * rand_pct / 100, date, d_rand) for i in range(n)]
    return rows


def test_chance_rule_and_random_rows_kept_out_of_real_stats():
    rows = _crowd("2019-05-01", 70, 50, 1.5, 1.5) + _crowd("2023-05-01", 68, 52, 1.5, 1.5)
    rows += [{"skip": True, "side": "support", "date": "2019-05-01", "placed": k % 4 != 0} for k in range(40)]
    b = pmap.summarize_levels(rows)["support"]
    assert b["random_placed"] == {"tried": 40, "placed": 30, "pct": 75.0}
    assert b["all"]["n"] == 300 and b["random"]["n"] == 300 and b["beats_chance"] is True and b["edge_pts"] >= 5
    rows = _crowd("2019-05-01", 70, 67, 1.5, 1.5) + _crowd("2023-05-01", 70, 67, 1.5, 1.5)
    assert pmap.summarize_levels(rows)["support"]["beats_chance"] is False


def test_distance_alone_cannot_fake_an_edge():
    # real zones are near (held 60%); most random zones are far (held 30%) but the near ones held 58%:
    # a raw comparison would show +30 points, the same-distance comparison shows only ~2 -> no pass
    rows = []
    for date in ("2019-05-01", "2023-05-01"):
        rows += [_cz("support", False, i < 120, date, 0.5) for i in range(200)]
        rows += [_cz("support", True, i < 29, date, 0.5) for i in range(50)]          # 58% near
        rows += [_cz("support", True, i < 45, date, 5.0) for i in range(150)]          # 30% far
    b = pmap.summarize_levels(rows)["support"]
    assert b["all"]["held_pct"] - b["random"]["held_pct"] > 20                          # raw gap is large
    assert b["edge_pts"] < 5 and b["beats_chance"] is False                             # but not at the same distance


def test_small_samples_are_not_called_better():
    lo, hi = pmap.wilson(8, 10)                    # KPIT's RSI signal: 8 of 10 higher a month later
    assert lo * 100 < 58 < hi * 100                 # against 58% on any day in a fall: not clearly different
    lo, hi = pmap.wilson(160, 200)                  # the same 80% on 200 cases is clearly above 58%
    assert lo * 100 > 58
    assert pmap.wilson(0, 0) == (0.0, 1.0)


def test_recent_results_from_the_tables():
    rep = {"currency": {"symbol": "₹", "unit": "Cr"}, "company": {"tables": {
        "quarters": {"columns": ["Sep 2025", "Dec 2025", "Mar 2026", "Jun 2026", "Sep 2026"],
                     "rows": {"Net Profit": [245, 230, 210, 150, 121], "Sales": [1000, 1010, 1020, 1030, 1050],
                              "OPM %": [21.0, 20.0, 19.0, 17.0, 16.0]}},
        "profit_loss": {"columns": ["Mar 2025", "Mar 2026", "TTM"], "rows": {"Net Profit": [840, 637, 600]}}}}}
    got = pmap.recent_results(rep)
    texts = [t for _, t in got]
    assert (False, "Quarterly profit down 51% on a year ago (₹121 Cr in Sep 2026 vs ₹245 Cr in Sep 2025)") in got
    assert not any(t.startswith("Quarterly sales") for t in texts)          # +5%: under the 10% bar
    assert (False, "Operating margin 16.0% in Sep 2026 vs 21.0% a year earlier") in got
    assert (False, "Yearly profit down 24% (₹637 Cr in Mar 2026 vs ₹840 Cr in Mar 2025)") in got   # TTM ignored
    assert pmap.recent_results({"company": {"tables": {}}}) == []


if __name__ == "__main__":
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f()
            print("PASS", k)
