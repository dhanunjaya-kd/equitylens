"""Who may use this EquityLens, and how to reach it from a phone.

- EQL_PASSWORD (backend/.env): when set, every /api call needs a login cookie.
  Needed whenever EquityLens is reachable from the internet (cloud server),
  because Settings holds AI keys and broker keys.
- Sessions use revocable random tokens (with IP-based login rate limiting).
- network_info(): the addresses a phone can use (same Wi-Fi, Tailscale).
- tail_logs(): last lines of the log files for Settings -> Logs.
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import os
import secrets
import socket
import time
from collections import deque

from . import config

COOKIE = "eql_auth"
OPEN_PATHS = ("/api/health", "/api/auth", "/api/login", "/api/logout", "/api/shutdown")
_sessions: dict[str, str] = {}   # token -> password digest at issuance
_fails: dict[str, list[float]] = {}


def password() -> str:
    return os.getenv("EQL_PASSWORD", "").strip()


def _pw_digest(pw: str | None = None) -> str:
    pw = password() if pw is None else pw
    return hashlib.sha256(f"equitylens|{pw}".encode()).hexdigest()


def token(pw: str | None = None) -> str:
    """Issue a new revocable session token bound to the current password."""
    tok = secrets.token_urlsafe(32)
    _sessions[tok] = _pw_digest(pw)
    return tok


def revoke(cookie_value: str | None) -> None:
    if cookie_value:
        _sessions.pop(cookie_value, None)


def limited(ip: str) -> bool:
    now = time.time()
    xs = [t for t in _fails.get(ip or "local", []) if now - t < 600]
    _fails[ip or "local"] = xs
    return len(xs) >= 5


def record_fail(ip: str) -> None:
    _fails.setdefault(ip or "local", []).append(time.time())


def check(cookie_value: str | None) -> bool:
    pw = password()
    if not pw:
        return True
    if not cookie_value:
        return False
    digest = _sessions.get(cookie_value)
    if digest is not None:
        return hmac.compare_digest(digest, _pw_digest(pw))
    return False


def is_open(path: str) -> bool:
    return not path.startswith("/api/") or path.startswith(OPEN_PATHS)


def is_local(client_host: str | None, headers) -> bool:
    """A request made on this computer itself (not through a proxy)."""
    if headers.get("x-forwarded-for") or headers.get("x-real-ip"):
        return False
    try:
        return ipaddress.ip_address(client_host or "").is_loopback
    except ValueError:
        return False


def _addresses() -> list[str]:
    ips: set[str] = set()
    try:                                                    # the address used to reach the internet
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))                    # no packet is sent
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    return sorted(i for i in ips if not i.startswith("127."))


def classify(ip: str) -> str:
    a = ipaddress.ip_address(ip)
    if a in ipaddress.ip_network("100.64.0.0/10"):
        return "tailscale"
    if a.is_private:
        return "wifi"
    return "public"


def network_info(request_host: str = "") -> dict:
    port = config.PORT
    out = []
    for ip in _addresses():
        kind = classify(ip)
        out.append({"ip": ip, "kind": kind, "url": f"http://{ip}:{port}"})
    order = {"wifi": 0, "tailscale": 1, "public": 2}
    out.sort(key=lambda a: order[a["kind"]])
    host = (request_host or "").split(":")[0]
    cloud = bool(host) and host not in ("localhost", "127.0.0.1") and not any(a["ip"] == host for a in out)
    return {
        "port": port, "addresses": out, "password": bool(password()),
        "listening_all": config.HOST in ("0.0.0.0", "::", ""),
        "opened_from": host, "cloud": cloud,
    }


def tail_logs(lines: int = 200) -> dict:
    d = config.DATA_DIR / "logs"
    out = {}
    for name in ("equitylens.log", "console.log"):
        p = d / name
        if p.exists():
            with open(p, encoding="utf-8", errors="replace") as f:
                out[name] = "".join(deque(f, maxlen=max(10, min(lines, 2000))))
    return {"folder": str(d), "files": out}
