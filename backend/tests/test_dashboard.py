"""Market dashboard maths (offline):  python tests/test_dashboard.py"""
import os
import sys
import tempfile
from pathlib import Path

os.environ["EQL_DEMO"] = "1"
os.environ.setdefault("EQL_DATA_DIR", tempfile.mkdtemp())
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import dashboard as D, store  # noqa: E402

store.init()


def test_score_is_the_weighted_average_of_its_parts():
    p = {"breadth": 60, "momentum": 50, "trend": 40, "volume": 70, "calm": 20}
    assert D.score_of(p) == round(60 * .3 + 50 * .25 + 40 * .15 + 70 * .2 + 20 * .1, 1)
    assert D.score_of({"breadth": 80, "calm": None}) == 80.0          # a missing part is left out, not counted as 0
    assert D.zone(10) == "Extreme fear" and D.zone(50) == "Neutral" and D.zone(75) == "Extreme greed" and D.zone(None) is None


def test_breadth_history_counts_each_day():
    bars = [{"t": f"2024-01-{i + 1:02d}", "c": 100 + (i % 3) - 1, "v": 10} for i in range(30)]
    h = D.BreadthHistory()
    h.add(bars)
    h.add([dict(b, c=200 - i) for i, b in enumerate(bars)])               # a falling stock
    out = h.finish()
    day = out["2024-01-02"]
    assert day[0] == 2 and day[1] == 1                                      # two stocks, one up
    assert day[2] == 0                                                      # nobody has 50 days yet
    p = D.parts_from_hist(day)
    assert p["breadth"] == 50.0 and p["momentum"] is None


def test_rotation_quadrants_and_formula():
    bench = {f"d{i:03d}": 100.0 for i in range(60)}
    rising = [(f"d{i:03d}", 50 + i) for i in range(60)]                    # steadily stronger than a flat benchmark
    pts = D.rotation_points(rising, bench, 20, 5, 10)
    assert len(pts) == 10 and all(p[1] > 100 for p in pts)
    # RS-Ratio = 100 x RS / its 20-bar average
    rs = [c / 100 for _, c in rising]
    assert abs(pts[-1][1] - 100 * rs[-1] / (sum(rs[-20:]) / 20)) < 0.01
    assert D.quadrant(101, 101) == "leading" and D.quadrant(101, 99) == "weakening"
    assert D.quadrant(99, 99) == "lagging" and D.quadrant(99, 101) == "improving"


def test_vix_rank_inverts_the_percentile():
    bars = [{"t": f"2024-{1 + i // 28:02d}-{1 + i % 28:02d}", "c": float(i)} for i in range(100)]
    r = D._vix_rank(bars)
    last = bars[-1]["t"]
    assert r[last] == 0.0                                                   # highest volatility in the window = calm 0


def test_breadth_from_the_full_file():
    b = D.breadth("IN")
    assert b["adv"] + b["dec"] + b["unch"] == b["total"] and b["net"] == b["adv"] - b["dec"]
    assert sum(x["n"] for x in b["dist"]) == b["total"]


if __name__ == "__main__":
    bad = 0
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            try:
                f(); print("PASS", n)
            except Exception as e:  # noqa: BLE001
                bad += 1; print("FAIL", n, repr(e))
    sys.exit(1 if bad else 0)
