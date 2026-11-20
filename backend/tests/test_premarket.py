"""Pre-market: the opening call, its backtest and the frozen live calls (offline):  python tests/test_premarket.py"""
import os
import random
import sys
import time
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

os.environ["EQL_DEMO"] = "1"
os.environ.setdefault("EQL_DATA_DIR", tempfile.mkdtemp())
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import premarket as pm, store  # noqa: E402

store.init()
IST = timezone(timedelta(hours=5, minutes=30))


def _series(n=900, link=1.0, seed=1):
    """Weekday bars; NIFTY's gap = link x the previous S&P 500 day (plus noise)."""
    rnd = random.Random(seed)
    days = [d for d in (date(2018, 1, 1) + timedelta(days=i) for i in range(n * 7 // 5 + 10)) if d.weekday() < 5][:n]
    out = {f["sym"]: [] for f in pm.FACTORS}
    px = {f["sym"]: 100.0 for f in pm.FACTORS}
    for d in days:
        for f in pm.FACTORS:
            px[f["sym"]] *= 1 + rnd.gauss(0, 0.01)
            out[f["sym"]].append({"t": d.isoformat(), "o": px[f["sym"]], "h": 0, "l": 0, "c": px[f["sym"]]})
    nifty, c = [], 10000.0
    spx = out["^GSPC"]
    for i, d in enumerate(days):
        sig = (spx[i - 1]["c"] / spx[i - 2]["c"] - 1) if i >= 2 else 0
        o = c * (1 + link * sig + rnd.gauss(0, 0.004))
        c = o * (1 + rnd.gauss(0, 0.008))
        nifty.append({"t": d.isoformat(), "o": o, "h": 0, "l": 0, "c": c})
    out[pm.NIFTY] = nifty
    return out


def test_factor_uses_only_sessions_before_the_nifty_day():
    s = _series()
    day = s[pm.NIFTY][600]["t"]
    a = pm.factor_values(s, day)
    changed = {k: [dict(b, c=b["c"] * (3 if b["t"] >= day else 1)) for b in v] for k, v in s.items()}
    assert pm.factor_values(changed, day) == a                       # nothing dated on/after the day is used
    assert all(f["date"] < day for f in a)


def test_score_scale_and_calls():
    fv = [dict(f, z=(1.0 if f["w"] > 0 else 0.0), contrib=(f["w"] * (1.0 if f["w"] > 0 else 0.0))) for f in pm.FACTORS]
    assert pm.score_of(fv) == 50.0                                   # S&P +1 sigma alone: 100 x 3 / 6
    assert pm.call_of(20)["call"] == "up" and pm.call_of(-20)["call"] == "down" and pm.call_of(19.9)["call"] == "flat"
    assert pm.call_of(None)["call"] == "na"
    fv[0]["z"] = None
    assert pm.score_of(fv) is None


def test_backtest_finds_a_real_link_and_rejects_noise():
    good = pm.backtest(_series(link=1.0), save=False)
    assert good["all"]["gap_hit"] > 70 and good["gap_passed"] is True
    assert good["day_passed"] is False                               # the close was pure noise
    noise = pm.backtest(_series(link=0.0, seed=7), save=False)
    assert noise["gap_passed"] is False and 35 < noise["all"]["gap_hit"] < 65
    assert noise["rules"]["pass_rule"].startswith("Right more than 55%")


def test_backtest_skips_bad_opens():
    s = _series()
    s[pm.NIFTY][700]["o"] = s[pm.NIFTY][699]["c"]
    s[pm.NIFTY][701]["o"] = None
    r = pm.backtest(s, save=False)
    assert r["skipped"]["open equals the previous close (data gap)"] == 1 and r["skipped"]["no open price"] == 1


def test_daily_dates_stay_in_the_markets_own_time_zone():
    ts = int(datetime(2026, 11, 19, 2, 0, tzinfo=timezone.utc).timestamp())     # 21:00 New York, 18 Nov
    res = {"meta": {"gmtoffset": -18000}, "timestamp": [ts], "indicators": {"quote": [{"open": [1], "high": [1], "low": [1], "close": [5900.5]}]}}
    assert pm.parse_daily(res)[0]["t"] == "2026-11-18"


def test_tile_impact_rules():
    assert pm.impact(1, 0.5, 0.25) == "positive" and pm.impact(-1, 0.9, 0.75) == "negative"
    assert pm.impact(-1, 0.1, 0.75) == "neutral" and pm.impact(0, 3.0, 0.5) == "neutral" and pm.impact(1, None, 0.2) == "neutral"


def test_session_day():
    assert pm.session_day(datetime(2026, 11, 19, 8, 30, tzinfo=IST)) == "2026-11-19"
    assert pm.session_day(datetime(2026, 11, 19, 16, 0, tzinfo=IST)) == "2026-11-20"
    assert pm.session_day(datetime(2026, 11, 20, 18, 0, tzinfo=IST)) == "2026-11-23"     # Friday evening -> Monday


def test_frozen_calls_are_checked_against_the_real_open():
    s = _series()
    nb = s[pm.NIFTY]
    up_day, down_day = nb[-3], nb[-2]
    for b, call in ((up_day, "up"), (down_day, "down")):
        store.put_company(f"PREMARKET::CALL::IN::{b['t']}", {"day": b["t"], "score": 40 if call == "up" else -40, "call": call, "label": call, "built": "x"})
    live = pm.live_calls(nb)
    rows = {r["day"]: r for r in live["rows"]}
    i = len(nb) - 3
    gap = round((nb[i]["o"] / nb[i - 1]["c"] - 1) * 100, 2)
    assert rows[up_day["t"]]["gap"] == gap and rows[up_day["t"]]["right"] == (gap > 0)
    assert live["checked"] == 2 and live["right"] == sum(bool(r["right"]) for r in rows.values())


def test_build_in_demo_has_every_part():
    p = pm.build("IN", refresh=True)
    assert p["label"] and len(p["factors"]) == 4 and {g["name"] for g in p["groups"]} >= {"US close and futures now", "Commodities and crypto"}
    assert p["gift"]["available"] is False and "NSE IX" in p["gift"]["note"]
    assert all(i["impact"] in ("positive", "negative", "neutral") for g in p["groups"] for i in g["items"])
    assert p["flows"] and p["live"] is not None



# ------------------------------------------------------------------ next-day view v2 (nextday.py)
from app import nextday as nd  # noqa: E402


def _ts(y, m, d, h, mi=0):
    return int(datetime(y, m, d, h, mi, tzinfo=timezone.utc).timestamp())


def test_0845_factors_use_only_bars_finished_by_0845_ist():
    day = "2026-11-19"
    spx = [{"ts": _ts(2026, 11, 18, h, 30), "c": 100} for h in range(14, 21)]            # US cash session, last bar 20:30-21:00 UTC
    fut = [{"ts": _ts(2026, 11, 18, h), "c": 100.0} for h in range(14, 24)] + [{"ts": _ts(2026, 11, 19, h), "c": 101.0 + h} for h in range(0, 8)]
    fut[6]["c"] = 100.0                                                                    # bar 20:00-21:00 ends at the close: 100
    asia = [{"ts": _ts(2026, 11, 18, h), "c": 200.0} for h in range(0, 6)] + [{"ts": _ts(2026, 11, 19, h), "c": 202.0 + h * 50} for h in range(0, 6)]
    dly = {s: [{"t": (date(2025, 1, 1) + timedelta(days=i)).isoformat(), "c": 100 * (1.01 if i % 2 else 1)} for i in range(400)] for s in (nd.FUT, "^N225", "^KS11")}
    f = nd.after_close_factors({nd.SPX: spx, nd.FUT: fut, "^N225": asia, "^KS11": asia}, dly, day)
    # futures: from the bar that ended at 21:00 UTC (100) to the last bar finished by 03:15 UTC (02:00 bar: 101+2)
    assert f[0]["ret"] == 3.0
    # Asia: previous close 200 -> last bar finished by 03:15 UTC (02:00 bar: 202+100); later bars ignored
    assert f[1]["ret"] == 51.0 and "Nikkei 225" in f[1]["name"]
    later = {nd.SPX: spx, nd.FUT: fut + [{"ts": _ts(2026, 11, 19, 9), "c": 999.0}], "^N225": asia, "^KS11": asia}
    assert nd.after_close_factors(later, dly, day) == f


def test_0845_backtest_runs_and_applies_its_pass_rule():
    r = nd.backtest2(save=False)
    assert r["days"] > 300 and r["passed"] in (True, False) and r["pass_rule"].startswith("Replaces the overnight call")
    for h in ("first_half", "second_half"):
        assert r[h]["v1"]["days"] == r[h]["v2"]["days"] > 0                       # both calls judged on the same days
    ok = all(r[h]["v2"]["gap_hit"] - max(r[h]["v1"]["gap_hit"], r[h]["v2"]["gap_naive"]) >= 5 for h in ("first_half", "second_half"))
    assert r["passed"] == ok


def test_day_map_levels_gaps_and_range():
    assert nd.bucket_of(-1.0) == 0 and nd.bucket_of(0.05) == 3 and nd.bucket_of(0.5) == 5 and nd.bucket_of(2) == 6
    lv = nd.levels({"h": 110, "l": 90, "c": 100})
    assert lv["pivot"] == 100.0 and lv["r1"] == 110.0 and lv["s1"] == 90.0 and lv["cpr_top"] == lv["cpr_bottom"] == 100.0
    nifty = [{"t": "2026-01-01", "o": 100, "h": 101, "l": 99, "c": 100},
             {"t": "2026-01-02", "o": 101, "h": 102, "l": 99.5, "c": 101.5},      # gap-up 1%, low 99.5 <= 100: filled, closed above open
             {"t": "2026-01-05", "o": 101.0, "h": 101.4, "l": 100.6, "c": 101.2}]  # gap-down 0.5%, high 101.4 < 101.5: not filled
    g = nd.gap_table(nifty)
    assert g[6]["days"] == 1 and g[6]["gap_filled_pct"] == 100.0 and g[6]["closed_above_open_pct"] == 100.0
    assert g[1]["days"] == 1 and g[1]["gap_filled_pct"] == 0.0 and g[3]["gap_filled_pct"] is None
    vix = [{"t": "2026-01-01", "c": 15.87}, {"t": "2026-01-02", "c": 15.87}]                        # ±1% a day
    rc = nd.range_check(nifty, vix)
    assert rc["days"] == 2 and rc["stayed_inside_pct"] == 50.0 and rc["closed_inside_pct"] == 50.0   # day 2 (high 102 > 101) is outside
    m = nd.day_map(nifty, vix, "2026-01-06")
    assert m["prev_day"] == "2026-01-05" and abs(m["expected_move_pct"] - 1.0) < 0.01 and m["actual_bucket"] is None


def test_evening_preview_only_while_the_us_trades():
    s = _series()
    day = s[pm.NIFTY][-1]["t"]
    q = {f["sym"]: {"change_pct": 0.5, "time": time.time()} for f in pm.FACTORS}
    assert nd.evening_preview(q, s, day, datetime(2026, 11, 19, 22, 0, tzinfo=IST))["score"] is not None
    assert nd.evening_preview(q, s, day, datetime(2026, 11, 19, 12, 0, tzinfo=IST)) is None        # daytime
    q[nd.SPX]["time"] = time.time() - 3600
    assert nd.evening_preview(q, s, day, datetime(2026, 11, 19, 22, 0, tzinfo=IST)) is None        # US not trading


def test_build_has_the_0845_check_and_day_map():
    p = pm.build("IN", refresh=True)
    assert p["check_0845"]["factors"] and "proven" in p["check_0845"] and p["overnight"]["label"]
    assert p["day_map"] and len(p["day_map"]["gaps"]) == 7 and p["day_map"]["levels"]["pivot"]


if __name__ == "__main__":
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f()
            print("PASS", k)
