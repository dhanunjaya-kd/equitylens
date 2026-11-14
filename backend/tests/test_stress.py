"""Partial / broken data must never crash the engine and must never be over-rated.
    python tests/test_stress.py"""
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import analysis, parser  # noqa: E402

FX = Path(__file__).parent / "fixtures"
BASE = parser.parse_company((FX / "testco.html").read_text(encoding="utf-8"), "T")
BANK = parser.parse_company((FX / "testbank.html").read_text(encoding="utf-8"), "B")


def _trim(c, n):
    for k in ("profit_loss", "balance_sheet", "cash_flow", "ratios"):
        t = c["tables"][k]
        t["columns"] = t["columns"][-n:]
        t["rows"] = {r: v[-n:] for r, v in t["rows"].items()}


CASES = {
    "no_cashflow": (BASE, lambda c: c["tables"].update(cash_flow={"columns": [], "rows": {}})),
    "no_shareholding": (BASE, lambda c: c["tables"].update(shareholding_quarterly={"columns": [], "rows": {}})),
    "no_ratios_section": (BASE, lambda c: c["tables"].update(ratios={"columns": [], "rows": {}})),
    "no_top_ratios": (BASE, lambda c: c.update(ratios={})),
    "two_years": (BASE, lambda c: _trim(c, 2)),
    "negative_equity": (BASE, lambda c: c["tables"]["balance_sheet"]["rows"].update(Reserves=[-500.0] * 13)),
    "zero_interest": (BASE, lambda c: c["tables"]["profit_loss"]["rows"].update(Interest=[0.0] * 13)),
    "none_values": (BASE, lambda c: [c["tables"]["profit_loss"]["rows"].update({k: [None] * 13}) for k in ("Net Profit", "EPS in Rs")]),
    "loss_all": (BASE, lambda c: c["tables"]["profit_loss"]["rows"].update({"Net Profit": [-10.0] * 13, "EPS in Rs": [-1.0] * 13})),
    "empty_everything": (BASE, lambda c: [c["tables"][k].update(columns=[], rows={}) for k in c["tables"]]),
    "bank_no_cash": (BANK, lambda c: c["tables"].update(cash_flow={"columns": [], "rows": {}})),
    "price_missing": (BASE, lambda c: c["ratios"].pop("current_price")),
}


def _run(name):
    src, fn = CASES[name]
    c = copy.deepcopy(src)
    fn(c)
    out = []
    for mp in (None, 31.5, 0):
        a = analysis.analyse(c, mp)
        json.dumps(a, allow_nan=False)  # must be valid JSON for the app
        out.append(a)
    return out[0]


def test_no_crash_on_any_case():
    for name in CASES:
        _run(name)


def test_too_little_data_is_not_rated():
    for name in ("two_years", "empty_everything"):
        a = _run(name)
        assert a["verdict"]["label"] == "Not enough data" and a["scores"]["overall"] is None


def test_negative_equity_is_flagged():
    a = _run("negative_equity")
    assert any("Negative net worth" in f["text"] for f in a["flags"])
    assert a["verdict"]["tone"] != "good"


def test_losses_are_speculative():
    assert _run("loss_all")["verdict"]["label"].startswith("Loss-making")


def test_missing_price_is_explicit():
    assert _run("no_top_ratios")["verdict"]["label"] == "High quality, price data missing"


def test_timeline_events():
    c = copy.deepcopy(BASE)
    c["tables"]["profit_loss"]["rows"]["Sales"][5] *= 1.6
    tl = analysis.analyse(c, 30)["timeline"]
    assert any("Sales jumped" in e["text"] for t in tl for e in t["events"])


if __name__ == "__main__":
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f()
            print("PASS", k)
