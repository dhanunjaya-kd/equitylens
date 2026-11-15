"""NIFTY 50 / 100 / 500 / All NSE lists (offline):  python tests/test_universe.py"""
import os
import sys
import tempfile
from pathlib import Path

os.environ["EQL_DEMO"] = "1"
os.environ.setdefault("EQL_DATA_DIR", tempfile.mkdtemp())
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import movers, store, universe  # noqa: E402

store.init()

EQUITY_L = """SYMBOL,NAME OF COMPANY, SERIES, DATE OF LISTING, PAID UP VALUE, MARKET LOT, ISIN NUMBER, FACE VALUE
20MICRONS,20 Microns Limited,EQ,06-OCT-2008,5,1,INE144J01027,5
GRAVITA,Gravita India Limited,EQ,16-NOV-2010,2,1,INE024L01027,2
SOMEBE,Some Trade-for-trade Ltd,BE,01-JAN-2015,10,1,INE000X01011,10
SOMEBOND,Some Debenture,N1,01-JAN-2015,1000,1,INE000X07011,1000"""

NIFTY_CSV = """Company Name,Industry,Symbol,Series,ISIN Code
Reliance Industries Ltd.,Oil Gas & Consumable Fuels,RELIANCE,EQ,INE002A01018
HDFC Bank Ltd.,Financial Services,HDFCBANK,EQ,INE040A01034"""


def test_parse_equity_l():
    rows = universe.parse_equity_l(EQUITY_L)
    assert [r["symbol"] for r in rows] == ["20MICRONS", "GRAVITA", "SOMEBE"]
    assert rows[1]["name"] == "Gravita India Limited"


def test_parse_nifty_constituents():
    rows = universe._from_csv_text(NIFTY_CSV)
    assert [r["symbol"] for r in rows] == ["RELIANCE", "HDFCBANK"] and rows[0]["industry"] == "Oil Gas & Consumable Fuels"


def test_lists_nest_and_membership():
    n50, n100, n500, al = (universe.index_list(k) for k in ("N50", "N100", "N500", "ALL"))
    assert len(n50) < len(n100) < len(n500) < len(al)
    m = universe.membership()
    first = n50[0]["symbol"]
    assert m[first] == ["N500", "N100", "N50"] and "SMALL01" not in m
    assert universe.index_list("bogus") == n500


def test_movers_filter_by_universe():
    movers.refresh("IN", block=True)
    all_rows = movers.get("IN", "1D")["rows"]
    n50 = movers.get("IN", "1D", "N50")
    assert 0 < n50["count"] < len(all_rows) and all("N50" in r["idx"] for r in n50["rows"])
    assert n50["universe"] == "N500"
    movers.refresh("IN", block=True, which="ALL")
    d = movers.get("IN", "1D")
    assert d["universe"] == "ALL" and any(r["symbol"].startswith("SMALL") for r in d["rows"])


if __name__ == "__main__":
    bad = 0
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            try:
                f(); print("PASS", n)
            except Exception as e:  # noqa: BLE001
                bad += 1; print("FAIL", n, repr(e))
    sys.exit(1 if bad else 0)
