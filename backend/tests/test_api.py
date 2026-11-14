"""Every API endpoint, happy paths and error paths, offline (demo mode).
    python tests/test_api.py"""
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ["EQL_DEMO"] = "1"
os.environ.setdefault("EQL_DATA_DIR", tempfile.mkdtemp())
os.environ["EQL_SCAN_DELAY"] = "0"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import logging  # noqa: E402

logging.disable(logging.INFO)
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

C = TestClient(app)
CHECKS = [
    ("get", "/api/health", 200, None), ("get", "/api/search?q=test", 200, None),
    ("get", "/api/stock/TESTCO", 200, None), ("get", "/api/stock/testbank", 200, None),
    ("get", "/api/stock/NSE:TESTCO-EQ", 200, None), ("get", "/api/stock/NOPE", 404, None),
    ("get", "/api/chart/TESTCO?interval=1d", 200, None), ("get", "/api/chart/TESTCO?interval=1wk", 200, None),
    ("get", "/api/chart/TESTCO?interval=5m", 400, None), ("get", "/api/compare?symbols=TESTCO,TESTBANK,NOPE", 200, None),
    ("post", "/api/ai/settings", 200, {"provider": "demo"}), ("post", "/api/ai/test", 200, None),
    ("post", "/api/ai/note/TESTCO", 200, None), ("post", "/api/ai/debate/TESTCO", 200, None),
    ("post", "/api/ai/guidance/TESTCO", 200, None), ("post", "/api/ai/chart/TESTCO", 200, None),
    ("post", "/api/ai/chat/TESTCO", 200, {"messages": [{"role": "user", "content": "hi"}]}),
    ("post", "/api/ai/chat/TESTCO", 400, {"messages": []}),
    ("post", "/api/ai/doc/TESTCO", 200, {"url": "https://example.com/t.pdf", "title": "Concall"}),
    ("post", "/api/ai/doc/TESTCO", 400, {"url": "http://169.254.169.254/latest"}),  # only the stock's own links
    ("post", "/api/ai/picks", 400, {"symbols": ["NOPE"]}),
    ("post", "/api/ai/settings", 200, {"provider": "gemini", "gemini_api_key": ""}),
    ("post", "/api/ai/note/TESTCO?refresh=1", 400, None),  # no key -> friendly 400
    ("get", "/api/ai/gemini-models", 400, None),
    ("post", "/api/ai/settings", 200, {"provider": "demo"}),
    ("get", "/api/search?q=tst&market=US", 200, None), ("get", "/api/stock/US:TSTUS", 200, None),
    ("get", "/api/stock/US:ZZZZ", 404, None), ("get", "/api/chart/US:TSTUS", 200, None),
    ("post", "/api/ai/note/US:TSTUS", 200, None), ("get", "/api/rankings?market=US", 200, None),
    ("get", "/", 200, None),
]


def test_endpoints():
    bad = []
    for method, url, code, body in CHECKS:
        r = getattr(C, method)(url, json=body) if body is not None else getattr(C, method)(url)
        if r.status_code != code:
            bad.append(f"{method.upper()} {url} -> {r.status_code} (wanted {code}) {r.text[:100]}")
    assert not bad, "\n".join(bad)


def test_scan_and_rankings():
    C.post("/api/scan/start?limit=2")
    for _ in range(50):
        if not C.get("/api/scan/status").json()["running"]:
            break
        time.sleep(0.1)
    rows = C.get("/api/rankings?sort=overall").json()["rows"]
    assert {r["symbol"] for r in rows} >= {"TESTCO", "TESTBANK"}
    assert all("piotroski" in r and "fair_value_upside" in r for r in rows)
    assert C.post("/api/ai/picks", json={"symbols": ["TESTCO", "TESTBANK"]}).status_code == 200


def test_stock_report_shape():
    d = C.get("/api/stock/TESTCO").json()
    a = d["analysis"]
    for k in ("verdict", "scores", "forensics", "valuation", "projection", "horizons", "timeline", "data_quality"):
        assert k in a, k
    u = C.get("/api/stock/US:TSTUS").json()
    assert u["market"] == "US" and u["currency"]["symbol"] == "$" and "₹" not in str(u["analysis"]["flags"])
    assert d["currency"]["symbol"] == "₹"
    t = C.get("/api/chart/TESTCO").json()
    assert t["outlook"]["scenarios"] and len(t["t"]) == len(t["rsi"]) == len(t["ema200"])



def test_movers_endpoints():
    for mk in ("IN", "US"):
        C.post(f"/api/movers/refresh?market={mk}")
        for _ in range(100):
            if not C.get(f"/api/movers?market={mk}").json()["status"]["running"]:
                break
            time.sleep(0.1)
        for tf in ("1D", "1W", "1M", "3M", "1Y", "bogus"):
            d = C.get(f"/api/movers?market={mk}&tf={tf}").json()
            assert d["rows"] and d["mood"] and d["sectors"] and d["tf"] in ("1D", "1W", "1M", "3M", "1Y")
        assert C.post(f"/api/ai/movers?market={mk}&tf=1W").status_code == 200


if __name__ == "__main__":
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f()
            print("PASS", k)
