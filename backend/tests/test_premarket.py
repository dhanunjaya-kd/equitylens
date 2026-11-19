"""Pre-market: the opening call, its backtest and the frozen live calls (offline):  python tests/test_premarket.py"""
import os
import random
import sys
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


if __name__ == "__main__":
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f()
            print("PASS", k)
