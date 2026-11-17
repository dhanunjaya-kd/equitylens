"""Entry decision engine: each rule produces the verdict it promises, using only past data."""
import math
import random

from app import entry


def make_bars(n=600, drift=0.001, vol=0.008, seed=3, tail=None):
    rnd = random.Random(seed)
    c, out = 100.0, []
    for k in range(n):
        d = drift + (tail(k) if tail else 0)
        o = c
        c = c * math.exp(d + rnd.gauss(0, vol))
        out.append({"t": f"2024-{1 + k // 28 % 12:02d}-{1 + k % 28:02d}", "o": o, "h": max(o, c) * 1.004, "l": min(o, c) * 0.996, "c": c, "v": 1})
    return out


PE = [20 + 10 * math.sin(k / 15) for k in range(300)]      # own history: 10..30


def test_uptrend_fair_value_says_enter():
    v = entry.decide(make_bars(drift=0.001, vol=0.008, seed=3), pe_hist=PE, pe_now=20, business=75)
    assert v["verdict"] == "ENTER", v["reasons"]


def test_expensive_says_wait_with_zone_below_price():
    v = entry.decide(make_bars(), pe_hist=PE, pe_now=29.9, business=75)
    assert v["verdict"] == "WAIT" and v["zone"][1] < v["price"]
    assert v["checks"]["value"]["state"] == "Expensive"


def test_stretched_spike_says_wait():
    bars = make_bars(tail=lambda k: 0.02 if k > 585 else 0)
    v = entry.decide(bars, pe_hist=PE, pe_now=20, business=75)
    assert v["verdict"] == "WAIT" and "stretched" in v["label"] and v["zone"][1] < v["price"]


def test_cheap_but_falling_says_parts_with_lower_levels():
    bars = make_bars(drift=0.0006, tail=lambda k: -0.004 if k > 380 else 0)
    v = entry.decide(bars, pe_hist=PE, pe_now=11, business=75)
    assert v["verdict"] == "PARTS", v["reasons"]
    prices = [p["price"] for p in v["plan"]]
    assert prices[0] > prices[1] > prices[2] and sum(p["pct"] for p in v["plan"]) == 100


def test_business_gate_and_results_wait():
    assert entry.decide(make_bars(), pe_hist=PE, pe_now=20, business=40)["verdict"] == "AVOID"
    assert entry.decide(make_bars(), pe_hist=PE, pe_now=20, business=80, high_flags=1)["verdict"] == "AVOID"
    v = entry.decide(make_bars(), pe_hist=PE, pe_now=20, business=80, results_in_days=3)
    assert v["verdict"] == "WAIT" and "results" in v["label"].lower()


def test_cautious_side_wins_between_pe_and_fair_value():
    bars = make_bars()
    px = bars[-1]["c"]
    v = entry.decide(bars, pe_hist=PE, pe_now=20, business=75, fair_value={"low": px * 0.5, "mid": px * 0.6, "high": px * 0.7})
    assert v["checks"]["value"]["state"] == "Expensive" and v["verdict"] == "WAIT"


def test_uses_only_past_bars():
    bars = make_bars(n=700)
    a = entry.decide(bars, 500, pe_hist=PE, pe_now=20)
    b = entry.decide(bars[:501], pe_hist=PE, pe_now=20)
    assert {k: a[k] for k in ("verdict", "zone", "plan", "exit_if")} == {k: b[k] for k in ("verdict", "zone", "plan", "exit_if")}


def test_not_enough_history():
    assert entry.decide(make_bars(n=120))["verdict"] == "NA"


def test_backtest_tool_runs_end_to_end(monkeypatch, tmp_path):
    """The track-record tool on a few synthetic stocks: produces per-verdict stats and saves them."""
    import datetime as dt
    import importlib.util
    import sys
    from pathlib import Path
    from app import config, service, store, technicals, universe

    def dated(seed, drift):
        rnd, c, out, d = random.Random(seed), 100.0, [], dt.date(2013, 1, 1)
        while d < dt.date(2026, 11, 1):
            if d.weekday() < 5:
                o = c
                c = c * math.exp(drift + rnd.gauss(0, 0.015))
                out.append({"t": d.isoformat(), "o": o, "h": max(o, c) * 1.005, "l": min(o, c) * 0.995, "c": c, "v": 1})
            d += dt.timedelta(days=1)
        return out
    stocks = {f"S{k}": dated(k, 0.0004 * (k % 3)) for k in range(6)}
    pe = [((dt.date(2013, 1, 1) + dt.timedelta(days=9 * k)).isoformat(), 20 + 8 * math.sin(k / 9)) for k in range(560)]
    monkeypatch.setattr(config, "DEMO", False)
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(universe, "load", lambda download=True: ([{"symbol": s} for s in stocks], "x"))
    monkeypatch.setattr(technicals, "_latest_daily", lambda sym: dated(99, 0.0003))
    monkeypatch.setattr(technicals, "get_bars", lambda sym, refresh=False, with_time=False: (stocks[sym], "x", True))
    monkeypatch.setattr(service, "get_payload", lambda sym, full=False, max_age_h=None: ({"extras": {"pe_chart": {"Price to Earning": pe}}}, 0))
    saved = {}
    monkeypatch.setattr(store, "put_company", lambda k, v: saved.__setitem__(k, v))
    spec = importlib.util.spec_from_file_location("eb", Path(__file__).resolve().parents[1] / "tools" / "entry_backtest.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(sys, "argv", ["entry_backtest.py"])
    mod.main()
    res = saved["ENTRY_TRACK::IN"]
    assert res["verdicts"] > 300 and (tmp_path / "entry_track.json").exists()
    assert {"ENTER", "PARTS", "WAIT"} <= set(res["by_verdict"])
    assert res["by_verdict"]["WAIT"]["zone_hit_rate"] is not None


def test_plan_levels_are_always_below_todays_price():
    for seed in range(12):
        for tail in (lambda k: -0.004 if k > 380 else 0, lambda k: -0.003 if k > 560 else 0):
            bars = make_bars(seed=seed, tail=tail)
            for pe_now in (11, 20, 25):
                v = entry.decide(bars, pe_hist=PE, pe_now=pe_now, business=75)
                if v["plan"]:
                    p = [x["price"] for x in v["plan"]]
                    assert p[0] >= p[1] + v["levels"]["atr"] - 0.02 and p[1] >= p[2] + v["levels"]["atr"] - 0.02, (seed, p)
                if v["zone"]:
                    assert v["zone"][1] < v["price"]


def test_flat_suspended_prices_give_no_call():
    bars = [{"t": f"d{k:04d}", "o": 50.0, "h": 50.0, "l": 50.0, "c": 50.0, "v": 0} for k in range(400)]
    assert entry.decide(bars, pe_hist=PE, pe_now=20)["verdict"] == "NA"
