"""Heatmap data (offline):  python tests/test_heatmap.py"""
import os
import sys
import tempfile
from pathlib import Path

os.environ["EQL_DEMO"] = "1"
os.environ.setdefault("EQL_DATA_DIR", tempfile.mkdtemp())
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import heatmap, movers, store  # noqa: E402

store.init()
movers.refresh("IN", block=True)


def test_rows_are_slim_and_honest_about_market_cap():
    d = heatmap.get("IN", "1W")
    assert d["tf"] == "1W" and d["count"] == len(d["rows"]) > 0
    r = d["rows"][0]
    assert set(r["ret"]) == set(movers.TF) and "spark" not in r
    assert d["no_mcap"] == sum(1 for x in d["rows"] if not x["mcap"])      # nothing scanned in demo: all counted
    assert all(x["mcap"] is None for x in d["rows"])                         # never a guessed market cap


def test_sector_totals_add_up():
    d = heatmap.get("IN", "1D")
    assert sum(s["count"] for s in d["sectors"]) == d["count"]
    for s in d["sectors"]:
        rs = [r for r in d["rows"] if r["sector"] == s["sector"]]
        vals = [r["ret"]["1D"] for r in rs if r["ret"]["1D"] is not None]
        assert s["up"] == sum(1 for v in vals if v > 0) and s["down"] == sum(1 for v in vals if v < 0)
        assert abs(s["avg"] - sum(vals) / len(vals)) < 0.01


def test_sector_index_mapping():
    assert heatmap.sector_index("IN", "Information Technology")["index"]["ticker"] == "^CNXIT"
    assert heatmap.sector_index("IN", "Financial Services")["index"]["ticker"] == "NIFTY_FIN_SERVICE.NS"
    assert heatmap.sector_index("IN", "Chemicals")["index"] is None                      # no index: says so
    assert heatmap.sector_index("US", "Information Technology")["index"]["ticker"] == "XLK"
    assert heatmap.sector_index("US", "Unknown")["index"] is None
    ix = heatmap.sector_index("IN", "Information Technology")["index"]
    assert ix["fall_pct"] >= 0 and set(ix["ret"]) == set(movers.TF)


if __name__ == "__main__":
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f()
            print("PASS", k)
