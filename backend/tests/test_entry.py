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


def falling():
    return make_bars(drift=0.0006, tail=lambda k: -0.004 if k > 380 else 0)


def test_uptrend_says_enter():
    v = entry.decide(make_bars(drift=0.001, vol=0.008, seed=3), pe_hist=PE, pe_now=20, business=75)
    assert v["verdict"] == "ENTER" and v["rule"] == "enter", v["reasons"]


def test_value_is_information_only():
    """An expensive P/E or price above fair value is a caution only: it does not change the verdict."""
    bars = make_bars()
    px = bars[-1]["c"]
    for kw in ({"pe_now": 29.9}, {"pe_now": 20, "fair_value": {"low": px * 0.5, "mid": px * 0.6, "high": px * 0.7}}):
        v = entry.decide(bars, pe_hist=PE, business=75, **kw)
        assert v["checks"]["value"]["state"] == "Expensive" and v["checks"]["value"]["caution"] is True
        assert v["verdict"] == "ENTER", v["reasons"]


def test_stretched_enters_as_strong_trend():
    bars = make_bars(tail=lambda k: 0.02 if k > 585 else 0)
    v = entry.decide(bars, pe_hist=PE, pe_now=20, business=75)
    assert v["verdict"] == "ENTER" and v["rule"] == "enter_stretched" and "strong trend" in v["label"]


def test_falling_says_avoid_with_no_buy_level():
    for pe_now in (11, 20, 29.9):                   # whatever the value
        v = entry.decide(falling(), pe_hist=PE, pe_now=pe_now, business=75)
        assert v["verdict"] == "AVOID" and v["rule"] == "avoid_falling", v["reasons"]
        assert v["review_if"]["below"] == v["levels"]["sma200"] > v["price"] and "200-day" in v["label"]
        assert not any(k in v for k in ("trigger", "zone", "plan", "conviction"))


def test_expensive_adds_a_caution_only():
    v = entry.decide(make_bars(), pe_hist=PE, pe_now=29.9, business=75)
    assert v["checks"]["value"]["caution"] is True and v["verdict"] == "ENTER"
    assert entry.decide(make_bars(), pe_hist=PE, pe_now=20, business=75)["checks"]["value"]["caution"] is False


def test_business_gate_and_results_warning():
    assert entry.decide(make_bars(), pe_hist=PE, pe_now=20, business=40)["verdict"] == "AVOID"
    assert entry.decide(make_bars(), pe_hist=PE, pe_now=20, business=80, high_flags=1)["verdict"] == "AVOID"
    assert entry.decide(falling(), pe_hist=PE, pe_now=20, business=40)["rule"] == "avoid_business"
    v = entry.decide(make_bars(), pe_hist=PE, pe_now=20, business=80, results_in_days=3)
    assert v["verdict"] == "ENTER" and v["checks"]["events"]["ok"] is False
    assert any("Results are due in 3" in r for r in v["reasons"])


def test_uses_only_past_bars():
    bars = make_bars(n=700)
    keys = ("verdict", "rule", "review_if")
    for i in (450, 500, 650):
        a = entry.decide(bars, i, pe_hist=PE, pe_now=20)
        b = entry.decide(bars[:i + 1], pe_hist=PE, pe_now=20)
        assert {k: a[k] for k in keys} == {k: b[k] for k in keys}


def test_not_enough_history():
    assert entry.decide(make_bars(n=120))["verdict"] == "NA"


def test_backtest_tool_runs_end_to_end(monkeypatch, tmp_path):
    """The track-record tool on a few synthetic stocks: produces per-verdict stats and saves them."""
    import datetime as dt
    import importlib.util
    import sys
    from pathlib import Path
    from app import config, service, store, technicals, universe

    def dated(seed, drift, vol_shares=1e6):
        rnd, c, out, d = random.Random(seed), 100.0, [], dt.date(2013, 1, 1)
        while d < dt.date(2026, 11, 1):
            if d.weekday() < 5:
                o = c
                c = c * math.exp(drift + rnd.gauss(0, 0.015))
                out.append({"t": d.isoformat(), "o": o, "h": max(o, c) * 1.005, "l": min(o, c) * 0.995, "c": c, "v": vol_shares})
            d += dt.timedelta(days=1)
        return out
    stocks = {f"S{k}": dated(k, 0.0004 * (k % 3)) for k in range(12)}
    stocks["THIN"] = dated(7, 0.0004, vol_shares=10)          # ~Rs 1,000 a day: every call skipped as illiquid
    pe = [((dt.date(2013, 1, 1) + dt.timedelta(days=9 * k)).isoformat(), 20 + 8 * math.sin(k / 9)) for k in range(560)]
    monkeypatch.setattr(config, "DEMO", False)
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(universe, "index_list", lambda code: [{"symbol": s} for s in (list(stocks) if code == "ALL" else [f"S{k}" for k in range(6)])])
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
    assert res["universe"] == "ALL" and res["illiquid_calls_skipped"] > 50
    for g in ("N500", "OTHER"):
        gb = res["by_rule"]["enter"]["groups"][g]
        assert gb["n"] and gb["p12"]["n"] and gb["claim_held"] in (True, False, None)
    assert res["rules_version"] == entry.RULES_VERSION and set(res["by_verdict"]) == {"ENTER", "AVOID"}
    assert set(res["by_rule"]) == set(entry.EXPECT)
    for b in res["by_rule"].values():
        if b["n"]:
            assert b["passed"] in (True, False, None) and "first_half" in b and "second_half" in b
    af = res["by_rule"]["avoid_falling"]
    assert af["wait_test"]["turned_pct"] is not None
    assert all("wait_test" in af["groups"][g] for g in ("N500", "OTHER"))
    assert set(res["by_state_groups"]) == {"N500", "OTHER"} and "Expensive" in res["by_state_groups"]["OTHER"]
    assert set(res["value_test"]["groups"]) == {"N500", "OTHER"}
    assert "p24" in res["by_state"]["Fair"] and res["value_test"]["passed"] in (True, False, None)


def test_pass_rule_needs_both_halves_and_most_months():
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("eb", Path(__file__).resolve().parents[1] / "tools" / "entry_backtest.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    blk = lambda f, g, mb: {"first_half": {"p12": {"avg": f}}, "second_half": {"p12": {"avg": g}}, "months_beat_pct": mb}
    assert mod.passes(blk(1.0, 2.0, 60), 1) is True
    assert mod.passes(blk(-3.1, 3.1, 60), 1) is False           # flips between halves
    assert mod.passes(blk(1.0, 2.0, 45), 1) is False            # beat peers in too few months
    assert mod.passes(blk(-2.0, -1.0, 30), -1) is True          # a WAIT rule must trail peers
    assert mod.passes(blk(-2.0, -1.0, 55), -1) is False


def test_flat_suspended_prices_give_no_call():
    bars = [{"t": f"d{k:04d}", "o": 50.0, "h": 50.0, "l": 50.0, "c": 50.0, "v": 0} for k in range(400)]
    assert entry.decide(bars, pe_hist=PE, pe_now=20)["verdict"] == "NA"
