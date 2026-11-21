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


def test_support_held_and_broken():
    # price falls to 100, bounces 5% (held), later falls to 100 again and closes 3% below (broken)
    c = [110] * 5 + [105, 102, 100.5, 103, 106, 108, 110, 110, 107, 104, 101, 97, 96, 95] + [95] * 30
    h = [x * 1.002 for x in c]
    l = [x * 0.998 for x in c]
    r = pmap.tests(h, l, c, 100.0, "support", 1)
    assert r["tests"] == 2 and r["held"] == 1 and r["broken"] == 1


def test_resistance_needs_approach_from_below():
    c = [90, 92, 95, 99.5, 96, 93, 95, 99.3, 102, 104, 106] + [106] * 25
    h = [x * 1.001 for x in c]
    l = [x * 0.999 for x in c]
    r = pmap.tests(h, l, c, 100.0, "resistance", 1)
    assert r["tests"] == 2 and r["held"] == 1 and r["broken"] == 1


def test_unresolved_test_is_not_counted():
    c = [110, 105, 100.5] + [100.8] * 30       # sits on the level, never 3% away, never 1% through
    r = pmap.tests([x * 1.001 for x in c], [x * 0.999 for x in c], c, 100.0, "support", 1)
    assert r["tests"] == 0


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
    assert all(x["price"] > lv["price"] for x in lv["resistance"]) and all(x["price"] < lv["price"] for x in lv["support"])
    assert all(0 <= x["held"] <= x["tests"] for x in lv["resistance"] + lv["support"])


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


if __name__ == "__main__":
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f()
            print("PASS", k)
