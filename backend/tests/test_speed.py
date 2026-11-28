"""Speed-ups that must not change any answer (offline):  python tests/test_speed.py"""
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ["EQL_DEMO"] = "1"
os.environ.setdefault("EQL_DATA_DIR", tempfile.mkdtemp())
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import automation, config, logos, movers, store  # noqa: E402

store.init()


def _big(n=2000, tag="a"):
    return {"rows": [{"symbol": f"S{i}", "name": f"Company {i} {tag}", "ret": {"1D": i / 10}, "scan": {"tags": ["vcp"]}}
                     for i in range(n)], "universe": "N500", "updated": time.time()}


def test_big_entries_come_back_as_separate_copies():
    store.put_company("SPEED::big", _big())
    a = store.get_company("SPEED::big")
    a[1]["rows"][0]["name"] = "changed by a caller"
    a[1]["rows"].append({"symbol": "EXTRA"})
    b = store.get_company("SPEED::big")
    assert b[1]["rows"][0]["name"] == "Company 0 a" and len(b[1]["rows"]) == 2000
    assert b[0] == a[0]


def test_a_new_save_is_seen_at_once():
    store.put_company("SPEED::big2", _big(tag="old"))
    assert store.get_company("SPEED::big2")[1]["rows"][5]["name"].endswith("old")
    time.sleep(0.01)
    store.put_company("SPEED::big2", _big(tag="new"))
    assert store.get_company("SPEED::big2")[1]["rows"][5]["name"].endswith("new")
    with store._conn() as c:                       # removed outside put_company (as a broker disconnect does)
        c.execute("DELETE FROM company WHERE symbol=?", ("SPEED::big2",))
    assert store.get_company("SPEED::big2") is None


def test_stamp_and_get_many():
    store.put_company("SPEED::s1", {"x": 1})
    store.put_company("SPEED::s2", {"x": 2})
    assert abs(store.stamp("SPEED::s1") - store.get_company("SPEED::s1")[0]) < 1e-9
    assert store.stamp("SPEED::none") is None
    got = store.get_many(["SPEED::s1", "SPEED::s2", "SPEED::none", "SPEED::s1"])
    assert {k: v[1]["x"] for k, v in got.items()} == {"SPEED::s1": 1, "SPEED::s2": 2}


def test_staleness_and_symbols_follow_each_save():
    key = movers._key("IN")
    store.put_company(key, {"rows": [{"symbol": "AAA"}], "universe": "N500"})      # saved before scanners existed
    assert automation._price_symbols("IN") == ["AAA"]
    assert movers.is_stale("IN") is True
    time.sleep(0.01)
    store.put_company(key, {"rows": [{"symbol": "BBB", "scan": {"tags": []}}], "universe": "N500"})
    assert automation._price_symbols("IN") == ["BBB"]
    assert movers._saved_meta("IN")["scan"] is True
    assert movers.is_stale("IN") == movers.is_stale("IN", store.get_company(key))   # same answer both ways


def test_a_missing_logo_never_makes_the_page_wait():
    calls = []

    def slow(sym):
        calls.append(sym)
        time.sleep(1.5)
        return b"\x89PNG" + b"0" * 400, "png"
    old_dl, old_demo = logos._download, config.DEMO
    logos._download, config.DEMO = slow, False
    try:
        t = time.time()
        data, media, final = logos.lookup("NEWCO", "Nova Ceramics Ltd")
        assert time.time() - t < 0.5                                 # answered at once
        assert media == "image/svg+xml" and b"NC" in data and final is False
        for _ in range(40):                                          # the real logo arrives in the background
            time.sleep(0.1)
            if logos.lookup("NEWCO")[2]:
                break
        data, media, final = logos.lookup("NEWCO")
        assert final and media == "image/png" and calls == ["NEWCO"]
    finally:
        logos._download, config.DEMO = old_dl, old_demo


if __name__ == "__main__":
    bad = 0
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            try:
                f(); print("PASS", n)
            except Exception as e:  # noqa: BLE001
                bad += 1; print("FAIL", n, repr(e))
    sys.exit(1 if bad else 0)
