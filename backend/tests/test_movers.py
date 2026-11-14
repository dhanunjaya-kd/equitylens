"""Market Movers maths on hand-built bars (offline):  python tests/test_movers.py"""
import os
import sys
import tempfile
from pathlib import Path

os.environ["EQL_DEMO"] = "1"
os.environ.setdefault("EQL_DATA_DIR", tempfile.mkdtemp())
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import movers, store  # noqa: E402

store.init()


def bars(closes, vols=None, last=None):
    out = []
    for k, c in enumerate(closes):
        out.append({"t": f"d{k}", "o": c, "h": c * 1.01, "l": c * 0.99, "c": c, "v": (vols[k] if vols else 1000)})
    if last:
        out[-1].update(last)
    return out


def test_returns_per_timeframe():
    cl = [100.0] * 300 + [110.0]
    r = movers.compute_row("X", "X Ltd", "IT", bars(cl), "IN")
    assert r["ret"]["1D"] == 10.0 and r["ret"]["1W"] == 10.0 and r["ret"]["1Y"] == 10.0


def test_short_history_skipped_and_partial_tf_none():
    assert movers.compute_row("X", "", "", bars([100.0] * 20), "IN") is None
    r = movers.compute_row("X", "", "", bars([100.0] * 60), "IN")
    assert r["ret"]["3M"] is None and r["ret"]["1Y"] is None and r["ret"]["1M"] is not None


def test_one_day_pressure_is_close_location():
    b = bars([100.0] * 60, last={"o": 100, "h": 110, "l": 100, "c": 110})
    assert movers.compute_row("X", "", "", b, "IN")["pressure"]["1D"] == 1.0      # closed at high = only buyers
    b = bars([100.0] * 60, last={"o": 100, "h": 100, "l": 90, "c": 90})
    assert movers.compute_row("X", "", "", b, "IN")["pressure"]["1D"] == -1.0     # closed at low = only sellers


def test_weekly_pressure_uses_up_down_volume():
    cl = [100.0] * 50 + [101, 102, 101, 102, 103]          # 4 up days, 1 down day in the last week
    vols = [1000] * 50 + [100, 100, 400, 100, 100]
    r = movers.compute_row("X", "", "", bars(cl, vols), "IN")
    assert r["pressure"]["1W"] == 0.0                       # 400 up-volume vs 400 down-volume = balanced
    vols[-3] = 0
    assert movers.compute_row("X", "", "", bars(cl, vols), "IN")["pressure"]["1W"] == 1.0


def test_turnover_units_and_rvol():
    vols = [1_000_000] * 59 + [3_000_000]
    r = movers.compute_row("X", "", "", bars([100.0] * 60, vols), "IN")
    assert r["turnover"]["1D"] == 30.0                      # 100 × 3M shares = ₹30 Cr
    assert r["rvol"] == 3.0
    u = movers.compute_row("US:X", "", "", bars([100.0] * 60, vols), "US")
    assert u["turnover"]["1D"] == 300.0                     # $300 M


def test_52w_breakout_and_breakdown():
    up = movers.compute_row("X", "", "", bars([100.0] * 299 + [120.0]), "IN")
    assert up["new_high"] and not up["new_low"] and up["from_hi"] > -2
    dn = movers.compute_row("X", "", "", bars([100.0] * 299 + [80.0]), "IN")
    assert dn["new_low"] and not dn["new_high"]


def test_trend_flags():
    r = movers.compute_row("X", "", "", bars([float(100 + k) for k in range(260)]), "IN")
    assert r["above50"] and r["above200"]


def _rows():
    rows = []
    for k in range(10):
        c = [100.0] * 260 + [100.0 + (k - 3)]                # 6 up, 3 down, 1 flat
        rows.append(movers.compute_row(f"S{k}", f"S{k}", "IT" if k < 5 else "Banks", bars(c), "IN"))
    return rows


def test_mood_counts_and_label():
    m = movers._mood(_rows(), "1D")
    assert m["advances"] == 6 and m["declines"] == 3 and m["unchanged"] == 1
    assert 0 <= m["score"] <= 100 and m["label"] in ("Extreme fear", "Fear", "Neutral", "Greed", "Extreme greed")
    assert "6 stocks rose" in m["read"]


def test_sector_heatmap_sorted():
    s = movers._sectors(_rows(), "1D")
    assert [x["sector"] for x in s] == ["Banks", "IT"] and s[0]["avg"] > s[1]["avg"]
    assert s[0]["best"]["symbol"] == "S9" and s[1]["worst"]["symbol"] == "S0"


def test_demo_refresh_and_get_both_markets():
    for mk in ("IN", "US"):
        movers.refresh(mk, block=True)
        for tf in movers.TF:
            d = movers.get(mk, tf)
            assert d["rows"] and d["mood"]["score"] is not None and d["sectors"]
        assert all(r["market"] == mk for r in d["rows"])
        assert any(r["symbol"].startswith("US:") for r in d["rows"]) == (mk == "US")


if __name__ == "__main__":
    bad = 0
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            try:
                f(); print("PASS", n)
            except Exception as e:  # noqa: BLE001
                bad += 1; print("FAIL", n, repr(e))
    sys.exit(1 if bad else 0)
