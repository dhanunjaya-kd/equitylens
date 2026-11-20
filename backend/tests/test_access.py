"""Password gate (cloud), shutdown from this computer only, phone addresses, logs."""
import os
import sys
import tempfile
from pathlib import Path

os.environ["EQL_DEMO"] = "1"
os.environ.setdefault("EQL_DATA_DIR", tempfile.mkdtemp())
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from app import access  # noqa: E402
from app.main import app  # noqa: E402


def test_no_password_means_open():
    os.environ.pop("EQL_PASSWORD", None)
    c = TestClient(app)
    a = c.get("/api/auth").json()
    assert a["required"] is False and a["ok"] is True and a["accounts"] is False
    assert c.get("/api/brokers").status_code == 200


def test_password_gate():
    os.environ["EQL_PASSWORD"] = "s3cret-pass"
    try:
        c = TestClient(app)
        assert c.get("/api/health").status_code == 200            # always open (launcher checks it)
        r = c.get("/api/brokers")
        assert r.status_code == 401 and r.json()["login"] is True
        assert c.get("/api/ai/settings").status_code == 401         # keys are protected
        assert c.get("/").status_code in (200, 404)                  # the page itself loads, then asks to sign in
        a = c.get("/api/auth").json()
        assert a["required"] is True and a["ok"] is False and a["accounts"] is False
        assert c.post("/api/login", json={"password": "nope"}).status_code == 401
        r = c.post("/api/login", json={"password": "s3cret-pass"})
        assert r.status_code == 200 and access.COOKIE in r.cookies
        assert c.get("/api/brokers").status_code == 200
        assert c.get("/api/auth").json()["ok"] is True
        c.post("/api/logout")
        c.cookies.clear()
        assert c.get("/api/brokers").status_code == 401
        # a cookie made with another password does not work
        c.cookies.set(access.COOKIE, access.token("other"))
        assert c.get("/api/brokers").status_code == 401
    finally:
        os.environ.pop("EQL_PASSWORD", None)


def test_shutdown_only_from_this_computer():
    c = TestClient(app)                     # TestClient's client host is "testclient", not loopback
    assert c.post("/api/shutdown").status_code == 403
    assert access.is_local("127.0.0.1", {}) and access.is_local("::1", {})
    assert not access.is_local("127.0.0.1", {"x-forwarded-for": "1.2.3.4"})   # behind a proxy (cloud)
    assert not access.is_local("192.168.1.5", {})


def test_addresses_and_logs():
    assert access.classify("192.168.1.20") == "wifi" and access.classify("10.0.0.4") == "wifi"
    assert access.classify("100.101.5.9") == "tailscale" and access.classify("8.8.8.8") == "public"
    n = TestClient(app).get("/api/network").json()
    assert n["port"] and isinstance(n["addresses"], list) and n["password"] is False
    logs = Path(os.environ["EQL_DATA_DIR"]) / "logs"
    logs.mkdir(exist_ok=True)
    (logs / "equitylens.log").write_text("".join(f"line {i}\n" for i in range(500)))
    j = TestClient(app).get("/api/logs?lines=50").json()
    t = j["files"]["equitylens.log"]
    assert t.count("\n") == 50 and t.endswith("line 499\n")


if __name__ == "__main__":
    bad = 0
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            try:
                f(); print("PASS", n)
            except Exception as e:  # noqa: BLE001
                bad += 1; print("FAIL", n, repr(e))
    sys.exit(1 if bad else 0)
