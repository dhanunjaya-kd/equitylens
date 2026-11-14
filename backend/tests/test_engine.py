"""Offline tests:  python -m pytest tests   (or: python tests/test_engine.py)"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import analysis, parser  # noqa: E402

FX = Path(__file__).parent / "fixtures"


def _load(name):
    return parser.parse_company((FX / name).read_text(encoding="utf-8"), name.split(".")[0].upper())


def test_parse_manufacturer():
    c = _load("testco.html")
    assert c["name"] == "Test Industries Ltd" and c["nse_symbol"] == "TESTCO"
    assert c["ratios"]["current_price"] == 1450 and c["ratios"]["high"] == 1650
    assert len(c["tables"]["profit_loss"]["columns"]) == 13
    assert "Raw PDF" not in c["tables"]["quarters"]["rows"]
    assert c["growth"]["Compounded Profit Growth"]["5 Years"] == 13
    assert not c["is_financial"]


def test_engine_manufacturer():
    a = analysis.analyse(_load("testco.html"), 32.0)
    m = a["metrics"]
    assert m["debt_to_equity"] < 0.1 and m["cfo_to_pat_5"] > 1
    assert a["scores"]["business"] >= 70
    assert a["verdict"]["tone"] == "good"
    assert a["projection"]["available"]
    h = a["projection"]["horizons"]
    for n in ("3", "5", "10"):
        assert h[n]["bear"]["price"] < h[n]["base"]["price"] < h[n]["bull"]["price"]


def test_bank_is_financial():
    a = analysis.analyse(_load("testbank.html"), None)
    assert a["metrics"]["is_financial"]
    assert a["scores"]["cash"] is None
    assert not any("Other income" in f["text"] for f in a["flags"])


def test_peers():
    p = parser.parse_peers((FX / "peers.html").read_text(encoding="utf-8"))
    assert len(p["rows"]) == 3 and p["median"]["P/E"] == 38.5


def test_loss_maker():
    c = _load("testco.html")
    c["tables"]["profit_loss"]["rows"]["EPS in Rs"][-1] = -2.0
    a = analysis.analyse(c, None)
    assert not a["projection"]["available"]
    assert a["verdict"]["tone"] == "bad"


def test_forensics_and_valuation():
    a = analysis.analyse(_load("testco.html"), 31.5)
    fx, v = a["forensics"], a["valuation"]
    assert fx["piotroski"]["available"] and 0 <= fx["piotroski"]["score_9"] <= 9
    assert fx["altman"]["zone"] in ("Safe", "Grey zone", "Distress")
    assert fx["beneish"]["available"] and isinstance(fx["beneish"]["m"], float)
    assert len(fx["dupont"]) >= 5
    assert v["graham_number"] > 0 and v["dcf"]["default_value"] > 0
    assert v["fair_value"]["low"] <= v["fair_value"]["mid"] <= v["fair_value"]["high"]


def test_bank_forensics_skip():
    a = analysis.analyse(_load("testbank.html"), None)
    assert not a["forensics"]["altman"]["available"] and not a["forensics"]["beneish"]["available"]
    assert a["forensics"]["piotroski"]["available"]


def test_documents():
    c = _load("testco.html")
    cats = [d["category"] for d in c["documents"]]
    assert "Annual reports" in cats and "Concalls" in cats


if __name__ == "__main__":
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f()
            print("PASS", k)
