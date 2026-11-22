"""Accounts: sign in with GitHub or email + password, invite-only, and data saved per person.

- Until the first account exists EquityLens works as before (open, or EQL_PASSWORD). The owner account is created
  from THIS computer (or after the EQL_PASSWORD sign-in); from then on every /api call needs a signed-in person.
- Only invited people can create an account: the owner invites an email address or a GitHub username.
- Passwords are stored only as a salted scrypt hash. Sessions are random tokens in an httpOnly cookie; only a SHA-256
  of each token is stored. Wrong passwords are slowed down and limited per address and email.
- Each person's watchlist, saved screens, recent stocks, chart layouts, notes and AI settings live in `user_data`.
  Members bring their own AI key; the owner's keys, broker links and portfolio are never shown to them.
"""
from __future__ import annotations

import contextvars
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
import time
from typing import Optional

from . import config

COOKIE = "eql_session"
SESSION_DAYS = 30
SETTINGS_FILE = config.DATA_DIR / "accounts_settings.json"
DATA_KEYS = {"watchlist", "recent", "screens", "chart_over", "chart_panes", "notes", "premarket_watch", "ai_settings"}
MAX_VALUE_BYTES = 512 * 1024
# owner-only: anything that shows the owner's private data or controls the computer
OWNER_ONLY = ("/api/brokers", "/api/broker/", "/api/portfolio", "/api/ai/portfolio", "/api/logs", "/api/network",
              "/api/scan/start", "/api/premarket/backtest", "/api/jobs/", "/api/alerts")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_lock = threading.Lock()
_current: contextvars.ContextVar[Optional[dict]] = contextvars.ContextVar("eql_user", default=None)
_fails: dict[str, list[float]] = {}


class AccountError(Exception):
    def __init__(self, msg: str, status: int = 400):
        super().__init__(msg)
        self.status = status


# ------------------------------------------------------------------ storage
def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(config.DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    return c


def init() -> None:
    with _lock, _conn() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT UNIQUE, name TEXT,
                     github_id TEXT UNIQUE, github_login TEXT, pw_hash TEXT, role TEXT NOT NULL, created REAL, last_login REAL)""")
        c.execute("""CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL, created REAL, expires REAL, agent TEXT)""")
        c.execute("""CREATE TABLE IF NOT EXISTS invites (who TEXT PRIMARY KEY, kind TEXT, invited_by INTEGER, created REAL, used_by INTEGER)""")
        c.execute("""CREATE TABLE IF NOT EXISTS user_data (user_id INTEGER, key TEXT, value TEXT, updated REAL, PRIMARY KEY (user_id, key))""")


def _row(r) -> Optional[dict]:
    return dict(r) if r else None


def public_user(u: Optional[dict]) -> Optional[dict]:
    if not u:
        return None
    return {"id": u["id"], "email": u["email"], "name": u["name"] or (u["email"] or u["github_login"] or "").split("@")[0],
            "github": u["github_login"], "role": u["role"], "has_password": bool(u["pw_hash"])}


_on = [False]


def enabled() -> bool:
    if _on[0]:
        return True
    with _conn() as c:
        _on[0] = c.execute("SELECT 1 FROM users LIMIT 1").fetchone() is not None
    return _on[0]


def current() -> Optional[dict]:
    return _current.get()


def set_current(u: Optional[dict]):
    return _current.set(u)


def is_owner(u: Optional[dict]) -> bool:
    return bool(u) and u["role"] == "owner"


# ------------------------------------------------------------------ passwords
def hash_password(pw: str) -> str:
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(pw.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return f"scrypt$16384$8$1${salt.hex()}${h.hex()}"


def check_password(pw: str, stored: Optional[str]) -> bool:
    try:
        _, n, r, p, salt, h = (stored or "").split("$")
        got = hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p), dklen=len(h) // 2)
        return hmac.compare_digest(got.hex(), h)
    except (ValueError, TypeError):
        return False


def _check_new_password(pw: str) -> None:
    if len(pw or "") < 10:
        raise AccountError("Use at least 10 characters for the password.")


def _email(e: str) -> str:
    e = (e or "").strip().lower()
    if not _EMAIL.match(e):
        raise AccountError("That doesn't look like an email address.")
    return e


# ------------------------------------------------------------------ sessions
def new_session(user_id: int, agent: str = "") -> str:
    token = secrets.token_urlsafe(32)
    now = time.time()
    with _lock, _conn() as c:
        c.execute("INSERT INTO sessions VALUES (?,?,?,?,?)", (hashlib.sha256(token.encode()).hexdigest(), user_id, now,
                                                              now + SESSION_DAYS * 86400, agent[:200]))
        c.execute("UPDATE users SET last_login=? WHERE id=?", (now, user_id))
        c.execute("DELETE FROM sessions WHERE expires < ?", (now,))
    return token


def user_from_token(token: Optional[str]) -> Optional[dict]:
    if not token:
        return None
    with _conn() as c:
        r = c.execute("""SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id
                         WHERE s.token_hash=? AND s.expires > ?""", (hashlib.sha256(token.encode()).hexdigest(), time.time())).fetchone()
    return _row(r)


def end_session(token: Optional[str]) -> None:
    if token:
        with _lock, _conn() as c:
            c.execute("DELETE FROM sessions WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),))


# ------------------------------------------------------------------ rate limit
def _limited(key: str) -> bool:
    now = time.time()
    xs = [t for t in _fails.get(key, []) if now - t < 600]
    _fails[key] = xs
    return len(xs) >= 5


def _failed(*keys: str) -> None:
    for k in keys:
        _fails.setdefault(k, []).append(time.time())


# ------------------------------------------------------------------ owner set-up, invites, users
def setup_owner(email: str, name: str, password: str) -> dict:
    email = _email(email)
    _check_new_password(password)
    with _lock, _conn() as c:
        if c.execute("SELECT 1 FROM users LIMIT 1").fetchone():
            raise AccountError("Sign-in is already set up. Sign in instead.", 409)
        cur = c.execute("INSERT INTO users (email, name, pw_hash, role, created) VALUES (?,?,?,?,?)",
                        (email, (name or "").strip()[:80], hash_password(password), "owner", time.time()))
        uid = cur.lastrowid
    return _get(uid)


def _get(uid: int) -> Optional[dict]:
    with _conn() as c:
        return _row(c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone())


def invite(who: str, by: int) -> dict:
    who = (who or "").strip().lower().lstrip("@")
    if not who:
        raise AccountError("Enter an email address or a GitHub username.")
    kind = "email" if "@" in who else "github"
    if kind == "email":
        who = _email(who)
    elif not re.match(r"^[a-z0-9](?:[a-z0-9-]{0,38})$", who):
        raise AccountError("That isn't a valid GitHub username.")
    with _lock, _conn() as c:
        c.execute("INSERT OR REPLACE INTO invites (who, kind, invited_by, created, used_by) VALUES (?,?,?,?,NULL)", (who, kind, by, time.time()))
    return {"who": who, "kind": kind}


def remove_invite(who: str) -> None:
    with _lock, _conn() as c:
        c.execute("DELETE FROM invites WHERE who=?", ((who or "").strip().lower().lstrip("@"),))


def _invited(*whos: Optional[str]) -> Optional[str]:
    with _conn() as c:
        for w in whos:
            if w and c.execute("SELECT 1 FROM invites WHERE who=?", (w.lower(),)).fetchone():
                return w.lower()
    return None


def _use_invite(who: str, uid: int, c) -> None:
    c.execute("UPDATE invites SET used_by=? WHERE who=?", (uid, who))


def people() -> dict:
    with _conn() as c:
        users = [public_user(dict(r)) | {"created": r["created"], "last_login": r["last_login"]} for r in c.execute("SELECT * FROM users ORDER BY id")]
        inv = [dict(r) for r in c.execute("SELECT who, kind, created, used_by FROM invites ORDER BY created DESC")]
    return {"users": users, "invites": inv}


def remove_user(uid: int, by: dict) -> None:
    u = _get(uid)
    if not u:
        raise AccountError("No such person.", 404)
    if u["role"] == "owner":
        raise AccountError("The owner account can't be removed.")
    with _lock, _conn() as c:
        for t in ("sessions", "user_data"):
            c.execute(f"DELETE FROM {t} WHERE user_id=?", (uid,))
        c.execute("DELETE FROM users WHERE id=?", (uid,))


# ------------------------------------------------------------------ email + password
def register(email: str, name: str, password: str) -> dict:
    email = _email(email)
    _check_new_password(password)
    who = _invited(email)
    if not who:
        raise AccountError("This EquityLens is invite-only. Ask its owner to invite this email address.", 403)
    with _lock, _conn() as c:
        if c.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
            raise AccountError("There's already an account for this email. Sign in instead.", 409)
        uid = c.execute("INSERT INTO users (email, name, pw_hash, role, created) VALUES (?,?,?,?,?)",
                        (email, (name or "").strip()[:80], hash_password(password), "member", time.time())).lastrowid
        _use_invite(who, uid, c)
    return _get(uid)


def login(email: str, password: str, ip: str = "") -> dict:
    e = (email or "").strip().lower()
    if _limited(f"ip:{ip}") or _limited(f"em:{e}"):
        raise AccountError("Too many wrong tries. Wait 10 minutes and try again.", 429)
    with _conn() as c:
        u = _row(c.execute("SELECT * FROM users WHERE email=?", (e,)).fetchone())
    if not u or not check_password(password or "", u["pw_hash"]):
        _failed(f"ip:{ip}", f"em:{e}")
        time.sleep(0 if config.DEMO else 1.0)
        raise AccountError("Wrong email or password.", 401)
    return u


def change_password(u: dict, old: str, new: str) -> None:
    if u["pw_hash"] and not check_password(old or "", u["pw_hash"]):
        raise AccountError("The current password is wrong.", 401)
    _check_new_password(new)
    with _lock, _conn() as c:
        c.execute("UPDATE users SET pw_hash=? WHERE id=?", (hash_password(new), u["id"]))


# ------------------------------------------------------------------ GitHub
def github_settings() -> dict:
    s = {"client_id": os.getenv("EQL_GITHUB_CLIENT_ID", ""), "client_secret": os.getenv("EQL_GITHUB_CLIENT_SECRET", "")}
    if SETTINGS_FILE.exists():
        try:
            s.update({k: v for k, v in json.loads(SETTINGS_FILE.read_text(encoding="utf-8")).items() if v})
        except (OSError, json.JSONDecodeError):
            pass
    return s


def save_github_settings(client_id: str, client_secret: Optional[str]) -> dict:
    cur = github_settings()
    cur["client_id"] = (client_id or "").strip()
    if client_secret and "•" not in client_secret:
        cur["client_secret"] = client_secret.strip()
    SETTINGS_FILE.write_text(json.dumps({k: cur[k] for k in ("client_id", "client_secret")}, indent=2), encoding="utf-8")
    return public_github()


def public_github() -> dict:
    s = github_settings()
    sec = s.get("client_secret") or ""
    return {"client_id": s.get("client_id") or "", "client_secret": ("•" * 8 + sec[-4:]) if sec else "", "enabled": bool(s.get("client_id") and sec)}


def github_user(code: str, redirect_uri: str, http=None) -> dict:
    """Exchange the code GitHub sent back for the person's GitHub id, username and verified emails."""
    import requests
    http = http or requests
    s = github_settings()
    r = http.post("https://github.com/login/oauth/access_token", headers={"Accept": "application/json"}, timeout=config.REQUEST_TIMEOUT,
                  data={"client_id": s["client_id"], "client_secret": s["client_secret"], "code": code, "redirect_uri": redirect_uri})
    token = (r.json() or {}).get("access_token")
    if not token:
        raise AccountError(f"GitHub didn't accept the sign-in ({(r.json() or {}).get('error_description') or 'no token'}).")
    h = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    me = http.get("https://api.github.com/user", headers=h, timeout=config.REQUEST_TIMEOUT).json()
    emails = http.get("https://api.github.com/user/emails", headers=h, timeout=config.REQUEST_TIMEOUT).json()
    verified = [e["email"].lower() for e in (emails if isinstance(emails, list) else []) if e.get("verified")]
    primary = next((e["email"].lower() for e in (emails if isinstance(emails, list) else []) if e.get("primary") and e.get("verified")), None)
    return {"id": str(me["id"]), "login": str(me.get("login", "")).lower(), "name": me.get("name") or "", "emails": verified, "primary": primary}


def github_login(gh: dict, signed_in: Optional[dict] = None) -> dict:
    """Sign in (or link GitHub to the signed-in account). New people need an invite for their username or email."""
    with _lock, _conn() as c:
        u = _row(c.execute("SELECT * FROM users WHERE github_id=?", (gh["id"],)).fetchone())
        if u:
            c.execute("UPDATE users SET github_login=? WHERE id=?", (gh["login"], u["id"]))
            return u
        if signed_in:                                              # linking GitHub to an account that is signed in
            c.execute("UPDATE users SET github_id=?, github_login=? WHERE id=?", (gh["id"], gh["login"], signed_in["id"]))
            return dict(signed_in, github_id=gh["id"], github_login=gh["login"])
        for e in gh["emails"]:                                     # an account with the same verified email
            u = _row(c.execute("SELECT * FROM users WHERE email=?", (e,)).fetchone())
            if u:
                c.execute("UPDATE users SET github_id=?, github_login=? WHERE id=?", (gh["id"], gh["login"], u["id"]))
                return dict(u, github_id=gh["id"], github_login=gh["login"])
    who = _invited(gh["login"], *gh["emails"])
    if not who:
        raise AccountError(f"This EquityLens is invite-only. Ask its owner to invite the GitHub user @{gh['login']}.", 403)
    with _lock, _conn() as c:
        uid = c.execute("INSERT INTO users (email, name, github_id, github_login, role, created) VALUES (?,?,?,?,?,?)",
                        (gh["primary"] or (gh["emails"] or [None])[0], gh["name"][:80], gh["id"], gh["login"], "member", time.time())).lastrowid
        _use_invite(who, uid, c)
    return _get(uid)


# ------------------------------------------------------------------ per-person data
def get_data(uid: int, key: Optional[str] = None):
    with _conn() as c:
        if key:
            r = c.execute("SELECT value FROM user_data WHERE user_id=? AND key=?", (uid, key)).fetchone()
            return json.loads(r["value"]) if r else None
        return {r["key"]: json.loads(r["value"]) for r in c.execute("SELECT key, value FROM user_data WHERE user_id=?", (uid,))}


def put_data(uid: int, key: str, value) -> None:
    if key not in DATA_KEYS:
        raise AccountError(f"Unknown data '{key}'.")
    raw = json.dumps(value)
    if len(raw) > MAX_VALUE_BYTES:
        raise AccountError("That is too much data to save in one go.")
    with _lock, _conn() as c:
        c.execute("INSERT OR REPLACE INTO user_data VALUES (?,?,?,?)", (uid, key, raw, time.time()))


def export(u: dict) -> dict:
    data = get_data(u["id"])
    if "ai_settings" in data:          # never export keys in plain text
        data["ai_settings"] = {k: ("(saved)" if k.endswith("api_key") and v else v) for k, v in data["ai_settings"].items()}
    return {"account": public_user(u), "data": data, "exported": time.strftime("%Y-%m-%d %H:%M")}
