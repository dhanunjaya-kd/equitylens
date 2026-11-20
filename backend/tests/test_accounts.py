"""Accounts: owner set-up, invite-only sign-up, GitHub sign-in, sessions, owner-only pages, data per person (offline)."""
import os
import sys
import tempfile
from pathlib import Path

os.environ["EQL_DEMO"] = "1"
os.environ["EQL_DATA_DIR"] = tempfile.mkdtemp()         # its own store: accounts get turned on here
os.environ.pop("EQL_PASSWORD", None)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from app import access, accounts  # noqa: E402
from app.main import app  # noqa: E402

OWNER = {"email": "owner@example.com", "name": "Owner", "password": "owner-pass-123"}
MEMBER = {"email": "friend@example.com", "name": "Friend", "password": "friend-pass-123"}
_real_local = access.is_local


def client():
    return TestClient(app)


def test_1_open_until_set_up_and_set_up_only_from_this_computer():
    c = client()
    a = c.get("/api/auth").json()
    assert a["accounts"] is False and a["required"] is False and a["ok"] is True
    assert c.get("/api/rankings").status_code == 200
    access.is_local = lambda *a, **k: False
    try:
        assert c.post("/api/auth/setup", json=OWNER).status_code == 403
    finally:
        access.is_local = _real_local
    access.is_local = lambda *a, **k: True
    try:
        assert c.post("/api/auth/setup", json=dict(OWNER, password="short")).status_code == 400
        r = c.post("/api/auth/setup", json=OWNER)
        assert r.status_code == 200 and r.json()["user"]["role"] == "owner" and accounts.COOKIE in r.cookies
        assert c.post("/api/auth/setup", json=OWNER).status_code == 409                 # only once
    finally:
        access.is_local = _real_local
    a = c.get("/api/auth").json()
    assert a["accounts"] and a["ok"] and a["user"]["email"] == OWNER["email"]


def test_2_everything_needs_sign_in_now():
    c = client()
    r = c.get("/api/rankings")
    assert r.status_code == 401 and r.json()["login"] is True and r.json()["accounts"] is True
    assert c.get("/api/health").status_code == 200 and c.get("/api/auth").json()["ok"] is False
    assert c.get("/").status_code in (200, 404)


def test_3_password_login_and_rate_limit():
    c = client()
    assert c.post("/api/auth/login", json={"email": OWNER["email"], "password": "nope-nope-nope"}).status_code == 401
    r = c.post("/api/auth/login", json={"email": "OWNER@example.com", "password": OWNER["password"]})
    assert r.status_code == 200 and c.get("/api/rankings").status_code == 200
    d = client()
    h = {"x-forwarded-for": "203.0.113.9"}
    codes = [d.post("/api/auth/login", json={"email": "who@example.com", "password": "bad-password!"}, headers=h).status_code for _ in range(6)]
    assert codes[:5] == [401] * 5 and codes[5] == 429
    other = [d.post("/api/auth/login", json={"email": f"p{i}@example.com", "password": "bad-password!"},
                    headers={"x-forwarded-for": f"198.51.100.{i}"}).status_code for i in range(6)]
    assert 429 not in other                                     # a different address and email isn't blocked
    accounts._fails.clear()


def _owner():
    c = client()
    assert c.post("/api/auth/login", json={"email": OWNER["email"], "password": OWNER["password"]}).status_code == 200
    return c


def test_4_invite_only_register_and_owner_only_pages():
    o = _owner()
    m = client()
    r = m.post("/api/auth/register", json=MEMBER)
    assert r.status_code == 403 and "invite-only" in r.json()["detail"]
    assert m.post("/api/auth/invites", json={"who": "x@example.com"}).status_code == 401      # not signed in
    assert o.post("/api/auth/invites", json={"who": MEMBER["email"]}).json()["kind"] == "email"
    assert o.post("/api/auth/invites", json={"who": "@Some-Dev"}).json() == {"who": "some-dev", "kind": "github"}
    assert o.post("/api/auth/invites", json={"who": "not valid!"}).status_code == 400
    r = m.post("/api/auth/register", json=MEMBER)
    assert r.status_code == 200 and r.json()["user"]["role"] == "member"
    assert m.post("/api/auth/register", json=MEMBER).status_code == 409
    for path in ("/api/brokers", "/api/portfolio", "/api/logs", "/api/network", "/api/auth/people", "/api/auth/github/config"):
        assert m.get(path).status_code == 403, path
    assert m.post("/api/auth/invites", json={"who": "y@example.com"}).status_code == 403
    assert m.get("/api/rankings").status_code == 200 and o.get("/api/brokers").status_code == 200
    people = o.get("/api/auth/people").json()
    assert {u["email"] for u in people["users"]} == {OWNER["email"], MEMBER["email"]}
    assert any(i["who"] == MEMBER["email"] and i["used_by"] for i in people["invites"])


def _member():
    c = client()
    assert c.post("/api/auth/login", json={"email": MEMBER["email"], "password": MEMBER["password"]}).status_code == 200
    return c


def test_5_each_person_keeps_their_own_data():
    o, m = _owner(), _member()
    assert o.put("/api/me/data/watchlist", json=[{"symbol": "TCS", "name": "TCS"}]).status_code == 200
    assert m.put("/api/me/data/watchlist", json=[{"symbol": "INFY", "name": "Infosys"}]).status_code == 200
    assert m.put("/api/me/data/notes", json={"INFY": {"text": "watch margins", "updated": 1}}).status_code == 200
    assert o.get("/api/me/data").json()["watchlist"][0]["symbol"] == "TCS"
    md = m.get("/api/me/data").json()
    assert md["watchlist"][0]["symbol"] == "INFY" and md["notes"]["INFY"]["text"] == "watch margins"
    assert m.put("/api/me/data/secrets", json=1).status_code == 400
    assert m.put("/api/me/data/screens", json=["x" * 600_000]).status_code == 400


def test_6_ai_keys_are_per_person():
    o, m = _owner(), _member()
    o.post("/api/ai/settings", json={"provider": "claude", "anthropic_api_key": "sk-ant-owner-0123456789abcdef"})
    ms = m.get("/api/ai/settings").json()
    assert ms["anthropic_api_key"] == "" and ms["provider"] != "claude"        # the owner's key and choice don't leak
    m.post("/api/ai/settings", json={"provider": "openai", "openai_api_key": "sk-member-0123456789abcdef", "ollama_url": "http://10.0.0.5"})
    ms = m.get("/api/ai/settings").json()
    assert ms["provider"] == "openai" and ms["openai_api_key"].endswith("cdef") and ms["ollama_url"] == "http://localhost:11434"
    os_ = o.get("/api/ai/settings").json()
    assert os_["provider"] == "claude" and os_["openai_api_key"] == "" and os_["anthropic_api_key"].endswith("cdef")
    o.post("/api/ai/settings", json={"provider": "demo"})
    exp = m.get("/api/me/export").json()
    assert exp["data"]["ai_settings"]["openai_api_key"] == "(saved)" and exp["account"]["email"] == MEMBER["email"]


def test_7_github_sign_in():
    o = _owner()
    assert o.post("/api/auth/github/config", json={"client_id": "Iv1.abc", "client_secret": "secret-xyz-1234"}).json()["enabled"] is True
    cfg = o.get("/api/auth/github/config").json()
    assert cfg["client_secret"].endswith("1234") and "secret-xyz" not in cfg["client_secret"]
    assert cfg["callback_url"].endswith("/api/auth/github/callback")
    fake = {"id": "777", "login": "some-dev", "name": "Some Dev", "emails": ["dev@example.com"], "primary": "dev@example.com"}
    real = accounts.github_user
    accounts.github_user = lambda code, uri, http=None: fake
    try:
        g = client()
        r = g.get("/api/auth/github/start", follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"].startswith("https://github.com/login/oauth/authorize?")
        state = r.cookies.get("eql_gh_state") or g.cookies.get("eql_gh_state")
        bad = g.get("/api/auth/github/callback", params={"code": "c", "state": "wrong"}, follow_redirects=False)
        assert "/#/signin?error=" in bad.headers["location"]
        ok = g.get("/api/auth/github/callback", params={"code": "c", "state": state}, follow_redirects=False)
        assert ok.headers["location"] == "/" and g.get("/api/auth").json()["user"]["github"] == "some-dev"
        fake2 = dict(fake, id="888", login="stranger", emails=["s@example.com"], primary="s@example.com")
        accounts.github_user = lambda code, uri, http=None: fake2
        s = client()
        r = s.get("/api/auth/github/start", follow_redirects=False)
        st = r.cookies.get("eql_gh_state") or s.cookies.get("eql_gh_state")
        no = s.get("/api/auth/github/callback", params={"code": "c", "state": st}, follow_redirects=False)
        assert "invite-only" in no.headers["location"].replace("%20", " ") and s.get("/api/auth").json()["ok"] is False
    finally:
        accounts.github_user = real


def test_8_github_reply_is_read_correctly():
    class R:
        def __init__(self, j):
            self._j = j

        def json(self):
            return self._j

    class Http:
        def post(self, url, **kw):
            assert kw["data"]["code"] == "abc" and kw["headers"]["Accept"] == "application/json"
            return R({"access_token": "gho_x"})

        def get(self, url, **kw):
            assert kw["headers"]["Authorization"] == "Bearer gho_x"
            return R({"id": 42, "login": "Dev", "name": "D"} if url.endswith("/user") else
                     [{"email": "A@x.com", "verified": True, "primary": True}, {"email": "b@x.com", "verified": False}])
    gh = accounts.github_user("abc", "http://localhost/cb", http=Http())
    assert gh == {"id": "42", "login": "dev", "name": "D", "emails": ["a@x.com"], "primary": "a@x.com"}


def test_9_logout_password_change_and_removing_a_member():
    m = _member()
    assert m.post("/api/auth/password", json={"old": "wrong", "new": "another-pass-1"}).status_code == 401
    assert m.post("/api/auth/password", json={"old": MEMBER["password"], "new": "another-pass-1"}).status_code == 200
    MEMBER["password"] = "another-pass-1"
    m.post("/api/auth/logout")
    assert m.get("/api/rankings").status_code == 401
    m2, o = _member(), _owner()
    people = o.get("/api/auth/people").json()["users"]
    owner_id = next(u["id"] for u in people if u["role"] == "owner")
    member_id = next(u["id"] for u in people if u["email"] == MEMBER["email"])
    assert o.delete(f"/api/auth/users/{owner_id}").status_code == 400
    assert o.delete(f"/api/auth/users/{member_id}").status_code == 200
    assert m2.get("/api/rankings").status_code == 401                          # their session ended too


def test_10_passwords_are_hashed():
    h = accounts.hash_password("correct horse")
    assert h.startswith("scrypt$") and "correct" not in h
    assert accounts.check_password("correct horse", h) and not accounts.check_password("wrong", h)
    assert not accounts.check_password("x", None)


if __name__ == "__main__":
    for k, f in sorted(((k, f) for k, f in globals().items() if k.startswith("test_")), key=lambda x: int(x[0].split("_")[1])):
        f()
        print("PASS", k)
