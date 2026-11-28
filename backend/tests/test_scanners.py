"""Scanner rules on hand-built price paths (each path is made to meet, or just miss, one written rule):  python tests/test_scanners.py"""
import os
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

os.environ["EQL_DEMO"] = "1"
os.environ.setdefault("EQL_DATA_DIR", tempfile.mkdtemp())
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import scanners  # noqa: E402


def days(n, start=date(2025, 1, 6)):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def path(closes, vols=None, spread=0.01, opens=None):
    ts = days(len(closes))
    out = []
    for k, (t, c) in enumerate(zip(ts, closes)):
        o = opens[k] if opens else (closes[k - 1] if k else c)
        out.append({"t": t, "o": o, "h": max(o, c) * (1 + spread), "l": min(o, c) * (1 - spread), "c": c,
                    "v": (vols[k] if vols else 1000)})
    return out


def tags(bars, idx=None):
    s = scanners.Series(bars, idx)
    return scanners.check(s, s.n - 1)


def test_inside_bar_nr7_mini_coil():
    b = path([100] * 20, spread=0.10)          # every day 90-110 wide ...
    b[-3].update(h=110, l=90)
    b[-2].update(h=105, l=95)
    b[-1].update(h=104, l=96)
    t = tags(b)
    assert {"inside_bar", "nr7", "mini_coil"} <= t
    b[-1].update(h=106)                     # above yesterday's high: not an inside bar, still inside the bar before
    assert "inside_bar" not in tags(b) and "mini_coil" in tags(b)
    b[-1].update(h=111)                     # above that one too: no coil
    assert "mini_coil" not in tags(b)


def test_volume_rules():
    v = [1000] * 300
    v[-1] = 5000
    b = path([100 + k * 0.1 for k in range(300)], v)
    assert "highest_volume" in tags(b)
    v[-1] = 10
    assert "lowest_volume" in tags(path([100 + k * 0.1 for k in range(300)], v))


def test_pocket_pivot_needs_above_down_day_volume():
    c = [100 + k * 0.2 for k in range(80)]
    c[-3] = c[-4] - 1                        # a down day with big volume
    v = [1000] * 80
    v[-3] = 3000
    v[-1] = 3500
    assert "pocket_pivot" in tags(path(c, v))
    v[-1] = 2900
    assert "pocket_pivot" not in tags(path(c, v))


def test_bull_snort_and_gap_up():
    c = [100.0] * 60 + [105.0]
    v = [1000] * 60 + [2500]
    b = path(c, v, spread=0.0)
    b[-1].update(o=100.5, h=105.2, l=100.5)
    assert "bull_snort" in tags(b) and "gap_up" not in tags(b)
    b[-1].update(o=104.5, l=104.4)
    assert "gap_up" in tags(b)


def test_ti65_and_minervini_pre_on_a_steady_rise():
    c = [100 * (1.003 ** k) for k in range(300)]
    t = tags(path(c))
    s = scanners.Series(path(c))
    ti = s.sma[7][-1] / s.sma[65][-1]
    assert ("ti65" in scanners.check(s, s.n - 1)) == (ti >= 1.05)
    assert "minervini_pre" in t and "stage2" in t


def test_flat_base_and_flag():
    c = [100 + k for k in range(60)] + [160 + (k % 3) for k in range(30)]
    assert "flat_base" in tags(path(c, spread=0.005))
    c = [100.0] * 40 + [100 + 3 * k for k in range(1, 11)] + [128, 127, 126, 127, 128]
    assert "flag" in tags(path(c, spread=0.003))


def test_rs_first_uses_the_index():
    c = [100.0] * 300                                  # price goes nowhere, below an old high
    c[100] = 110
    b = path(c)
    idx = {x["t"]: 1000 * (1 - 0.001 * k) for k, x in enumerate(b)}    # market keeps falling -> RS line at a high
    assert "rs_first" in tags(b, idx)
    assert "rs_first" not in tags(b)                                  # no index: rule is off


def test_record_and_rs_rating():
    a = scanners.analyse(path([100 * (1.002 ** k) for k in range(320)]))
    assert a["events"] and len(a["base"][5]) > 0
    rec = scanners.Record()
    rec.add("A", a)
    rec.add("B", scanners.analyse(path([100 * (0.999 ** k) for k in range(320)])))
    out = rec.finish()
    assert out["stocks"] == 2 and out["baseline"]["5"]["n"] > 0
    r = scanners.rs_ratings({"A": 0.5, "B": -0.1, "C": None})
    assert r["A"] > r["B"] and "C" not in r



def test_movers_refresh_feeds_the_scanners_api():
    from app import main, movers
    movers.refresh("IN", block=True)
    d = main.scanners_get("IN", "")
    assert d["rows"] and all("tags" in r and "adr" in r for r in d["rows"])
    assert all(r["rs"] is None or 1 <= r["rs"] <= 99 for r in d["rows"])
    assert set(d["rules"]) == {k for g in d["groups"] for k in g["items"]}
    assert d["record"] and d["record"]["stocks"] > 0 and d["record"]["baseline"]["5"]["n"] > 0


if __name__ == "__main__":
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f()
            print("PASS", k)
