"""Chart patterns: found only when every written rule passes, and never with future candles (offline):
python tests/test_patterns.py"""
import datetime
import os
import random
import sys
import tempfile
from pathlib import Path

os.environ["EQL_DEMO"] = "1"
os.environ.setdefault("EQL_DATA_DIR", tempfile.mkdtemp())
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import patterns as P  # noqa: E402


def path(points, seed=1, noise=0.004, vol=100000, spike=()):
    rnd = random.Random(seed)
    out, d, prev = [], datetime.date(2022, 1, 3), points[0][1]
    for (i0, p0), (i1, p1) in zip(points, points[1:]):
        for i in range(i0, i1):
            px = p0 + (p1 - p0) * (i - i0) / (i1 - i0)
            o, c = prev, px * (1 + rnd.uniform(-noise, noise))
            h, l = max(o, c) * (1 + rnd.uniform(0, noise)), min(o, c) * (1 - rnd.uniform(0, noise))
            while d.weekday() > 4:
                d += datetime.timedelta(days=1)
            out.append({"t": d.isoformat(), "o": o, "h": h, "l": l, "c": c, "v": vol * (3 if i in spike else 1)})
            prev = c
            d += datetime.timedelta(days=1)
    return out


DB = [(0, 200), (60, 150), (80, 175), (100, 151), (130, 190), (150, 185)]


def test_double_bottom_found_with_levels():
    ev = P.scan(path(DB), "D")["events"]
    assert [(e["type"], e["dir"]) for e in ev] == [("double_bottom", "up")]
    cut = P.scan(path(DB)[:108], "D")["now"]
    db = [x for x in cut if x["type"] == "double_bottom"][0]
    assert db["status"] == "forming" and db["dir"] == "up"
    low = min(b["l"] for b in path(DB)[55:105])
    assert abs(db["stop"] - low) < 0.01                          # stop = the lower of the two lows
    assert abs((db["target"] - db["level"]) - (db["level"] - db["stop"])) < 0.05   # target = neckline + height
    piv = db["draw"]["pivots"]
    assert [p[2] for p in piv] == ["L", "H", "L"]
    bars = db["draw"]["bars"]
    for i, price, kind in piv:                                    # drawn on the real candle highs / lows
        assert abs(price - (bars[i][1] if kind == "H" else bars[i][2])) < 0.01


def test_near_misses_are_not_shown():
    far = path([(0, 200), (60, 150), (80, 175), (100, 160), (130, 190), (150, 185)])   # lows 6.6% apart
    no_fall = path([(0, 140), (60, 150), (80, 175), (100, 151), (130, 190), (150, 185)])  # no fall into it
    assert not [e for e in P.scan(far, "D")["events"] if e["type"] == "double_bottom"]
    assert not [e for e in P.scan(no_fall, "D")["events"] if e["type"] == "double_bottom"]


def test_other_shapes():
    ihs = P.scan(path([(0, 210), (40, 160), (52, 176), (72, 140), (92, 177), (108, 160), (150, 200), (170, 198)]), "D")["events"]
    assert ("inv_head_shoulders", "up") in [(e["type"], e["dir"]) for e in ihs]
    asc = P.scan(path([(0, 150), (30, 200), (45, 170), (60, 200), (75, 182), (90, 200), (103, 191), (115, 215), (130, 212)]), "D")["events"]
    assert ("asc_triangle", "up") in [(e["type"], e["dir"]) for e in asc]
    sym = P.scan(path([(0, 150), (30, 210), (50, 160), (70, 200), (88, 170), (104, 193), (118, 178), (140, 150), (150, 152)]), "D")["events"]
    assert ("sym_triangle", "down") in [(e["type"], e["dir"]) for e in sym]


def test_volume_decides_confirmed():
    b = path(DB, spike=set(range(118, 122)))
    e = [x for x in P.scan(b, "D")["events"] if x["type"] == "double_bottom"][0]
    assert e["confirmed"] is True
    e2 = [x for x in P.scan(path(DB), "D")["events"] if x["type"] == "double_bottom"][0]
    assert e2["confirmed"] is False


def test_no_future_candles():
    """History cut at any day finds exactly the breakouts the full history has up to that day."""
    rnd = random.Random(11)
    pts, p = [(0, 100)], 100
    for i in range(1, 50):
        p *= 1 + rnd.gauss(0, 0.035)
        pts.append((i * 7, p))
    b = path(pts, noise=0.012)
    full = {(e["type"], e["i"], e["dir"]) for e in P.scan(b, "D")["events"]}
    assert full
    for t in range(80, len(b), 4):
        cut = {(e["type"], e["i"], e["dir"]) for e in P.scan(b[:t + 1], "D")["events"]}
        assert cut == {x for x in full if x[1] <= t}, t


def test_outcome_target_or_stop_first():
    b = path(DB + [(200, 260)])                                   # rallies well past the target
    e = [x for x in P.scan(b, "D")["events"] if x["type"] == "double_bottom"][0]
    assert e["result"] == "target"
    b2 = path(DB[:-2] + [(118, 178), (140, 120), (200, 118)])      # breaks out then collapses below the lows
    e2 = [x for x in P.scan(b2, "D")["events"] if x["type"] == "double_bottom"][0]
    assert e2["result"] == "stop"


def test_weekly_bars():
    b = path([(0, 100), (30, 110)])
    w = P.weekly(b)
    assert sum(1 for _ in w) == 6 and w[0]["o"] == b[0]["o"] and w[-1]["c"] == b[-1]["c"]
    assert w[0]["h"] == max(x["h"] for x in b[:5]) and w[0]["v"] == sum(x["v"] for x in b[:5])


def test_candles_and_gaps():
    b = path([(0, 120), (20, 100)], noise=0.001)
    b.append({"t": "2022-02-01", "o": 98.9, "h": 99.7, "l": 96.0, "c": 99.6, "v": 1})       # hammer after the fall (body 19% of the range)
    tags = P.candle_tags(b, len(b) - 1, 104.0)
    assert "hammer" in tags and "dragonfly_doji" not in tags
    doji = b[:-1] + [dict(b[-1], o=99.5)]                    # body only 3% of the range: a dragonfly doji, not a hammer
    assert P.candle_tags(doji, len(doji) - 1, 104.0) == ["dragonfly_doji"]
    b.append({"t": "2022-02-02", "o": 102.0, "h": 103.0, "l": 101.5, "c": 102.8, "v": 1})   # gap up over 99.7
    g = P.gaps(b + [dict(b[-1], t="2022-02-03")] * 50)
    assert any(x["dir"] == "up" and x["t"] == "2022-02-02" for x in g["events"])


def test_record_adds_up():
    rec = P.Record()
    rec.add(P.analyse(path(DB + [(200, 260)])), "2022-01-03", "2022-10-01")
    out = rec.finish()
    r = out["patterns"]["D:double_bottom:up"]
    assert r["n"] == 1 and r["target_first"] == 100.0 and out["stocks"] == 1 and out["base"]["n"] > 0


if __name__ == "__main__":
    bad = 0
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            try:
                f(); print("PASS", n)
            except Exception as e:  # noqa: BLE001
                bad += 1; print("FAIL", n, repr(e))
    sys.exit(1 if bad else 0)
