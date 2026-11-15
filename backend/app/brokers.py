"""Read-only broker connections: import holdings, never place orders.

🇮🇳 Zerodha (Kite Connect Personal) · Upstox · Fyers · Angel One (SmartAPI) · Dhan
🇺🇸 Alpaca · Tradier · Charles Schwab
📄 Any other broker: upload the holdings file (CSV / Excel) exported from the broker

Every user creates their OWN free API app on their broker's developer site and pastes the
key/secret here. Keys and tokens are stored only in backend/data/brokers.json (git-ignored).
"""
from __future__ import annotations

import base64
import csv
import hashlib
import hmac
import io
import json
import re
import struct
import time
from typing import Optional
from urllib.parse import parse_qs, quote, unquote, urlencode, urlparse

import requests

from . import config, store

FILE = config.DATA_DIR / "brokers.json"
T = 20  # request timeout


class BrokerError(Exception):
    pass


# ------------------------------------------------------------------ catalogue shown in the app
BROKERS = {
    "zerodha": {
        "name": "Zerodha", "market": "IN", "auth": "oauth", "expires": "every morning (SEBI rule): tap Reconnect once a day",
        "fields": [("api_key", "API key", False), ("api_secret", "API secret", True)],
        "steps": ["Open developers.kite.trade and sign up (free).", "Create an app → choose **Personal (free)**.",
                  "Set the Redirect URL to the address shown below.", "Copy the API key and API secret here, Save, then Connect."],
        "site": "https://developers.kite.trade",
    },
    "upstox": {
        "name": "Upstox", "market": "IN", "auth": "oauth", "expires": "daily: tap Reconnect once a day",
        "fields": [("api_key", "API key", False), ("api_secret", "API secret", True)],
        "steps": ["Open account.upstox.com/developer/apps and create a new app (free).", "Set the Redirect URL to the address shown below.",
                  "Copy the API key and API secret here, Save, then Connect."],
        "site": "https://account.upstox.com/developer/apps",
    },
    "fyers": {
        "name": "Fyers", "market": "IN", "auth": "oauth", "expires": "daily: tap Reconnect once a day",
        "fields": [("app_id", "App ID (e.g. XB12345-100)", False), ("secret", "Secret key", True)],
        "steps": ["Open myapi.fyers.in/dashboard and create an app (free).", "Set the Redirect URL to the address shown below.",
                  "Copy the App ID and Secret key here, Save, then Connect."],
        "site": "https://myapi.fyers.in/dashboard",
    },
    "angel": {
        "name": "Angel One", "market": "IN", "auth": "direct", "expires": "daily: tap Connect again the next day",
        "fields": [("api_key", "SmartAPI key", False), ("client_code", "Client ID", False), ("pin", "4-digit PIN", True),
                   ("totp_secret", "TOTP secret (text under the QR code)", True)],
        "steps": ["Open smartapi.angelone.in, sign up and create a 'Trading API' app (free).",
                  "Enable TOTP at smartapi.angelone.in/enable-totp and copy the secret text shown under the QR code.",
                  "Paste the API key, Client ID, PIN and TOTP secret here, Save, then Connect."],
        "site": "https://smartapi.angelone.in",
    },
    "dhan": {
        "name": "Dhan", "market": "IN", "auth": "token", "expires": "when the token expires: paste a new one",
        "fields": [("client_id", "Dhan Client ID", False), ("access_token", "Access token", True)],
        "steps": ["Log in to web.dhan.co → Profile → 'Access DhanHQ APIs'.", "Generate an access token (free).",
                  "Paste your Client ID and the token here, Save, then Connect."],
        "site": "https://web.dhan.co",
    },
    "alpaca": {
        "name": "Alpaca", "market": "US", "auth": "token", "expires": "keys don't expire",
        "fields": [("key_id", "API key ID", False), ("secret", "Secret key", True), ("paper", "Paper account? (yes / no)", False)],
        "steps": ["Log in to app.alpaca.markets → API keys → Generate (free).", "Paste the key ID and secret here (type 'yes' for a paper account), Save, then Connect."],
        "site": "https://app.alpaca.markets",
    },
    "tradier": {
        "name": "Tradier", "market": "US", "auth": "token", "expires": "the token doesn't expire unless you revoke it",
        "fields": [("token", "Access token", True)],
        "steps": ["Log in to dash.tradier.com → Settings → API Access.", "Copy your account access token here, Save, then Connect."],
        "site": "https://dash.tradier.com",
    },
    "schwab": {
        "name": "Charles Schwab", "market": "US", "auth": "paste", "expires": "every 7 days (Schwab rule): reconnect weekly",
        "fields": [("app_key", "App key", False), ("app_secret", "Secret", True),
                   ("callback", "Callback URL from your Schwab app (e.g. https://127.0.0.1)", False)],
        "steps": ["Open developer.schwab.com, create an app with 'Accounts and Trading Production' (approval can take a few days).",
                  "Use https://127.0.0.1 as the callback URL.", "Paste the app key, secret and callback here, Save, then Connect.",
                  "After you log in, the browser shows an error page — copy that page's full address and paste it back here."],
        "site": "https://developer.schwab.com",
    },
}


# ------------------------------------------------------------------ local storage (git-ignored)
def _load() -> dict:
    try:
        return json.loads(FILE.read_text(encoding="utf-8")) if FILE.exists() else {}
    except (OSError, ValueError):
        return {}


def _save(d: dict) -> None:
    FILE.parent.mkdir(parents=True, exist_ok=True)
    FILE.write_text(json.dumps(d, indent=2), encoding="utf-8")


def _cfg(bid: str) -> dict:
    return _load().get(bid, {})


def _set(bid: str, **kv) -> dict:
    d = _load()
    d.setdefault(bid, {}).update(kv)
    _save(d)
    return d[bid]


def mask(v: str) -> str:
    v = str(v or "")
    return "" if not v else ("•" * 6 + v[-4:] if len(v) > 6 else "•" * len(v))


def redirect_uri(base: str, bid: str) -> str:
    return f"{base.rstrip('/')}/api/broker/{bid}/callback"


def status(base: str) -> list[dict]:
    d = _load()
    out = []
    for bid, b in BROKERS.items():
        c = d.get(bid, {})
        snap = store.get_company(f"PORTFOLIO::{bid}")
        out.append({
            "id": bid, "name": b["name"], "market": b["market"], "auth": b["auth"], "steps": b["steps"], "site": b["site"],
            "expires": b["expires"], "redirect_uri": redirect_uri(base, bid) if b["auth"] in ("oauth",) else None,
            "fields": [{"key": k, "label": lab, "secret": sec, "value": (mask(c.get(k)) if sec else c.get(k, "")), "set": bool(c.get(k))}
                       for k, lab, sec in b["fields"]],
            "configured": all(c.get(k) for k, _, _ in b["fields"] if k != "paper"),
            "connected": bool(c.get("token")) and not c.get("error"),
            "last_sync": snap[0] if snap else None, "holdings": len(snap[1]["rows"]) if snap else 0,
            "error": c.get("error"),
        })
    f = store.get_company("PORTFOLIO::file")
    out.append({"id": "file", "name": "Holdings file (any broker)", "market": "ANY", "auth": "file", "fields": [], "steps": [],
                "last_sync": f[0] if f else None, "holdings": len(f[1]["rows"]) if f else 0, "file": f[1].get("filename") if f else None,
                "connected": bool(f), "configured": True})
    return out


def configure(bid: str, values: dict) -> dict:
    if bid not in BROKERS:
        raise BrokerError("Unknown broker")
    keep = {}
    for k, _, sec in BROKERS[bid]["fields"]:
        v = (values.get(k) or "").strip()
        if v and not (sec and v.startswith("•")):        # a masked value means "unchanged"
            keep[k] = v
    return _set(bid, **keep, error=None)


def forget(bid: str) -> None:
    d = _load()
    d.pop(bid, None)
    _save(d)
    with store._conn() as c:                       # also delete the saved holdings
        c.execute("DELETE FROM company WHERE symbol = ?", (f"PORTFOLIO::{bid}",))


# ------------------------------------------------------------------ helpers
def _need(c: dict, *keys) -> None:
    miss = [k for k in keys if not c.get(k)]
    if miss:
        raise BrokerError("Save these first: " + ", ".join(miss))


def _json(r: requests.Response, who: str):
    try:
        j = r.json()
    except ValueError:
        raise BrokerError(f"{who} answered {r.status_code} (not JSON)")
    if r.status_code >= 400:
        msg = j.get("message") or j.get("errorMessage") or j.get("error_description") or j.get("error") or j.get("errors") or r.status_code
        raise BrokerError(f"{who}: {msg}")
    return j


def totp(secret: str, t: Optional[float] = None, digits: int = 6, step: int = 30) -> str:
    """RFC 6238 TOTP (the 6-digit code an authenticator app shows)."""
    key = base64.b32decode(re.sub(r"\s", "", secret).upper() + "=" * (-len(re.sub(r"\s", "", secret)) % 8))
    counter = int((t or time.time()) // step)
    h = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    o = h[-1] & 0x0F
    return str((struct.unpack(">I", h[o:o + 4])[0] & 0x7FFFFFFF) % 10 ** digits).zfill(digits)


def _f(v) -> Optional[float]:
    try:
        x = float(str(v).replace(",", "").replace("₹", "").replace("$", "").strip())
        return x
    except (TypeError, ValueError):
        return None


def norm_symbol(sym: str, market: str) -> str:
    s = str(sym or "").strip().upper()
    s = re.sub(r"^(NSE|BSE|NASDAQ|NYSE)[:|_ ]", "", s)
    s = re.sub(r"-(EQ|BE|BZ|SM|ST|BL)$", "", s)
    if market == "US":
        return "US:" + s.replace(".", "-")
    return s


def holding(market: str, symbol: str, name: str, qty, avg, ltp=None, isin=None, broker="", exchange="") -> Optional[dict]:
    q, a, l = _f(qty), _f(avg), _f(ltp)
    if not symbol or not q:
        return None
    return {"market": market, "symbol": norm_symbol(symbol, market), "name": (name or symbol).strip(), "qty": q, "avg": a,
            "ltp": l if l else None, "isin": isin or None, "broker": broker, "exchange": exchange or ("NSE" if market == "IN" else "")}


# ------------------------------------------------------------------ login flows
def login_url(bid: str, base: str) -> str:
    c, ru = _cfg(bid), redirect_uri(base, bid)
    if bid == "zerodha":
        _need(c, "api_key")
        return f"https://kite.zerodha.com/connect/login?v=3&api_key={quote(c['api_key'])}"
    if bid == "upstox":
        _need(c, "api_key")
        return "https://api.upstox.com/v2/login/authorization/dialog?" + urlencode({"response_type": "code", "client_id": c["api_key"], "redirect_uri": ru})
    if bid == "fyers":
        _need(c, "app_id")
        return "https://api-t1.fyers.in/api/v3/generate-authcode?" + urlencode(
            {"client_id": c["app_id"], "redirect_uri": ru, "response_type": "code", "state": "equitylens"})
    if bid == "schwab":
        _need(c, "app_key", "callback")
        return "https://api.schwabapi.com/v1/oauth/authorize?" + urlencode({"client_id": c["app_key"], "redirect_uri": c["callback"]})
    raise BrokerError("This broker connects directly — tap Connect")


def callback(bid: str, params: dict, base: str) -> None:
    """Exchange the one-time code the broker sent back for an access token."""
    c, ru = _cfg(bid), redirect_uri(base, bid)
    if config.DEMO:
        _set(bid, token="demo-token", token_time=time.time(), error=None)
        return
    if bid == "zerodha":
        rt = params.get("request_token")
        if not rt or params.get("status") not in (None, "success"):
            raise BrokerError("Zerodha login was cancelled")
        _need(c, "api_key", "api_secret")
        chk = hashlib.sha256((c["api_key"] + rt + c["api_secret"]).encode()).hexdigest()
        j = _json(requests.post("https://api.kite.trade/session/token", headers={"X-Kite-Version": "3"},
                                data={"api_key": c["api_key"], "request_token": rt, "checksum": chk}, timeout=T), "Zerodha")
        tok = j["data"]["access_token"]
    elif bid == "upstox":
        _need(c, "api_key", "api_secret")
        j = _json(requests.post("https://api.upstox.com/v2/login/authorization/token", headers={"Accept": "application/json"},
                                data={"code": params.get("code", ""), "client_id": c["api_key"], "client_secret": c["api_secret"],
                                      "redirect_uri": ru, "grant_type": "authorization_code"}, timeout=T), "Upstox")
        tok = j["access_token"]
    elif bid == "fyers":
        _need(c, "app_id", "secret")
        code = params.get("auth_code") or params.get("code")
        if not code:
            raise BrokerError("Fyers login was cancelled")
        h = hashlib.sha256(f"{c['app_id']}:{c['secret']}".encode()).hexdigest()
        j = _json(requests.post("https://api-t1.fyers.in/api/v3/validate-authcode",
                                json={"grant_type": "authorization_code", "appIdHash": h, "code": code}, timeout=T), "Fyers")
        if j.get("s") != "ok":
            raise BrokerError(f"Fyers: {j.get('message')}")
        tok = j["access_token"]
    elif bid == "schwab":
        _need(c, "app_key", "app_secret", "callback")
        code = unquote(params.get("code", ""))
        auth = base64.b64encode(f"{c['app_key']}:{c['app_secret']}".encode()).decode()
        j = _json(requests.post("https://api.schwabapi.com/v1/oauth/token", headers={"Authorization": f"Basic {auth}"},
                                data={"grant_type": "authorization_code", "code": code, "redirect_uri": c["callback"]}, timeout=T), "Schwab")
        _set(bid, refresh_token=j.get("refresh_token"))
        tok = j["access_token"]
    else:
        raise BrokerError("No browser login for this broker")
    _set(bid, token=tok, token_time=time.time(), error=None)


def schwab_paste(url: str, base: str) -> None:
    q = parse_qs(urlparse(url.strip()).query)
    if "code" not in q:
        raise BrokerError("That address has no 'code=' in it. Copy the full address of the page you landed on after logging in.")
    callback("schwab", {"code": q["code"][0]}, base)


def direct_login(bid: str) -> None:
    c = _cfg(bid)
    if config.DEMO:
        _set(bid, token="demo-token", token_time=time.time(), error=None)
        return
    if bid == "angel":
        _need(c, "api_key", "client_code", "pin", "totp_secret")
        h = {"X-PrivateKey": c["api_key"], "X-UserType": "USER", "X-SourceID": "WEB", "X-ClientLocalIP": "127.0.0.1",
             "X-ClientPublicIP": "127.0.0.1", "X-MACAddress": "00:00:00:00:00:00", "Content-Type": "application/json", "Accept": "application/json"}
        j = _json(requests.post("https://apiconnect.angelone.in/rest/auth/angelbroking/user/v1/loginByPassword", headers=h,
                                json={"clientcode": c["client_code"], "password": c["pin"], "totp": totp(c["totp_secret"])}, timeout=T), "Angel One")
        if not j.get("status"):
            raise BrokerError(f"Angel One: {j.get('message')}")
        _set(bid, token=j["data"]["jwtToken"], token_time=time.time(), error=None)
    elif bid in ("dhan", "alpaca", "tradier"):
        need = {"dhan": ("client_id", "access_token"), "alpaca": ("key_id", "secret"), "tradier": ("token",)}[bid]
        _need(c, *need)
        _set(bid, token="keys", token_time=time.time(), error=None)
    else:
        raise BrokerError("Use the browser login for this broker")


# ------------------------------------------------------------------ holdings
def parse_zerodha(j) -> list[dict]:
    return [h for h in (holding("IN", r.get("tradingsymbol"), r.get("tradingsymbol"), (r.get("quantity") or 0) + (r.get("t1_quantity") or 0),
                                r.get("average_price"), r.get("last_price"), r.get("isin"), "Zerodha", r.get("exchange"))
                        for r in (j.get("data") or [])) if h]


def parse_upstox(j) -> list[dict]:
    return [h for h in (holding("IN", r.get("tradingsymbol") or r.get("trading_symbol"), r.get("company_name"), r.get("quantity"),
                                r.get("average_price"), r.get("last_price"), r.get("isin"), "Upstox", r.get("exchange"))
                        for r in (j.get("data") or [])) if h]


def parse_fyers(j) -> list[dict]:
    return [h for h in (holding("IN", r.get("symbol"), r.get("symbol"), r.get("quantity") or r.get("remainingQuantity"), r.get("costPrice"),
                                r.get("ltp"), r.get("isin"), "Fyers") for r in (j.get("holdings") or [])) if h]


def parse_angel(j) -> list[dict]:
    rows = ((j.get("data") or {}).get("holdings")) if isinstance(j.get("data"), dict) else (j.get("data") or [])
    return [h for h in (holding("IN", r.get("tradingsymbol"), r.get("tradingsymbol"), r.get("quantity"), r.get("averageprice"),
                                r.get("ltp"), r.get("isin"), "Angel One", r.get("exchange")) for r in (rows or [])) if h]


def parse_dhan(j) -> list[dict]:
    rows = j if isinstance(j, list) else (j.get("data") or [])
    return [h for h in (holding("IN", r.get("tradingSymbol"), r.get("tradingSymbol"), r.get("totalQty"), r.get("avgCostPrice"),
                                r.get("lastTradedPrice") or r.get("ltp"), r.get("isin"), "Dhan", r.get("exchange")) for r in rows) if h]


def parse_alpaca(j) -> list[dict]:
    return [h for h in (holding("US", r.get("symbol"), r.get("symbol"), r.get("qty"), r.get("avg_entry_price"), r.get("current_price"),
                                None, "Alpaca", r.get("exchange")) for r in (j or []) if (r.get("asset_class") or "us_equity") == "us_equity") if h]


def parse_tradier(j) -> list[dict]:
    p = (j.get("positions") or {}) if isinstance(j.get("positions"), dict) else {}
    rows = p.get("position") or []
    rows = rows if isinstance(rows, list) else [rows]
    return [h for h in (holding("US", r.get("symbol"), r.get("symbol"), r.get("quantity"),
                                (_f(r.get("cost_basis")) or 0) / (_f(r.get("quantity")) or 1), None, None, "Tradier") for r in rows) if h]


def parse_schwab(j) -> list[dict]:
    out = []
    for acc in (j or []):
        for p in ((acc.get("securitiesAccount") or {}).get("positions") or []):
            ins = p.get("instrument") or {}
            if ins.get("assetType") not in (None, "EQUITY", "ETF", "COLLECTIVE_INVESTMENT"):
                continue
            q = (_f(p.get("longQuantity")) or 0) - (_f(p.get("shortQuantity")) or 0)
            mv = _f(p.get("marketValue"))
            h = holding("US", ins.get("symbol"), ins.get("description") or ins.get("symbol"), q, p.get("averagePrice"),
                        (mv / q) if mv and q else None, None, "Schwab")
            if h:
                out.append(h)
    return out


def _get(url: str, headers: dict, who: str):
    return _json(requests.get(url, headers=headers, timeout=T), who)


def fetch(bid: str) -> list[dict]:
    c = _cfg(bid)
    if config.DEMO:
        return _demo_holdings(bid)
    if not c.get("token"):
        raise BrokerError("Not connected yet — tap Connect")
    t = c["token"]
    if bid == "zerodha":
        return parse_zerodha(_get("https://api.kite.trade/portfolio/holdings",
                                  {"X-Kite-Version": "3", "Authorization": f"token {c['api_key']}:{t}"}, "Zerodha"))
    if bid == "upstox":
        return parse_upstox(_get("https://api.upstox.com/v2/portfolio/long-term-holdings",
                                 {"Accept": "application/json", "Authorization": f"Bearer {t}"}, "Upstox"))
    if bid == "fyers":
        j = _get("https://api-t1.fyers.in/api/v3/holdings", {"Authorization": f"{c['app_id']}:{t}"}, "Fyers")
        if j.get("s") not in (None, "ok"):
            raise BrokerError(f"Fyers: {j.get('message')}")
        return parse_fyers(j)
    if bid == "angel":
        h = {"Authorization": f"Bearer {t}", "X-PrivateKey": c["api_key"], "X-UserType": "USER", "X-SourceID": "WEB",
             "X-ClientLocalIP": "127.0.0.1", "X-ClientPublicIP": "127.0.0.1", "X-MACAddress": "00:00:00:00:00:00", "Accept": "application/json"}
        return parse_angel(_get("https://apiconnect.angelone.in/rest/secure/angelbroking/portfolio/v1/getAllHolding", h, "Angel One"))
    if bid == "dhan":
        return parse_dhan(_get("https://api.dhan.co/v2/holdings", {"access-token": c["access_token"], "Accept": "application/json"}, "Dhan"))
    if bid == "alpaca":
        host = "paper-api.alpaca.markets" if (c.get("paper") or "").lower().startswith("y") else "api.alpaca.markets"
        return parse_alpaca(_get(f"https://{host}/v2/positions", {"APCA-API-KEY-ID": c["key_id"], "APCA-API-SECRET-KEY": c["secret"]}, "Alpaca"))
    if bid == "tradier":
        h = {"Authorization": f"Bearer {c['token']}", "Accept": "application/json"}
        prof = _get("https://api.tradier.com/v1/user/profile", h, "Tradier").get("profile") or {}
        accs = prof.get("account") or []
        accs = accs if isinstance(accs, list) else [accs]
        rows = []
        for a in accs:
            rows += parse_tradier(_get(f"https://api.tradier.com/v1/accounts/{a['account_number']}/positions", h, "Tradier"))
        return rows
    if bid == "schwab":
        if time.time() - (c.get("token_time") or 0) > 25 * 60 and c.get("refresh_token"):     # access token lives 30 min
            auth = base64.b64encode(f"{c['app_key']}:{c['app_secret']}".encode()).decode()
            j = _json(requests.post("https://api.schwabapi.com/v1/oauth/token", headers={"Authorization": f"Basic {auth}"},
                                    data={"grant_type": "refresh_token", "refresh_token": c["refresh_token"]}, timeout=T), "Schwab")
            c = _set("schwab", token=j["access_token"], token_time=time.time(), refresh_token=j.get("refresh_token") or c["refresh_token"])
        return parse_schwab(_get("https://api.schwabapi.com/trader/v1/accounts?fields=positions", {"Authorization": f"Bearer {c['token']}"}, "Schwab"))
    raise BrokerError("Unknown broker")


def sync(bid: str) -> dict:
    try:
        rows = fetch(bid)
    except BrokerError as e:
        msg = str(e)
        if any(w in msg.lower() for w in ("token", "expired", "invalid", "unauthor", "401", "403", "session")):
            _set(bid, token=None, error=f"Session expired — tap Reconnect ({msg})")
        else:
            _set(bid, error=msg)
        raise
    except requests.RequestException as e:
        _set(bid, error=f"Network error: {e}")
        raise BrokerError(f"Could not reach {BROKERS[bid]['name']}: {e}")
    store.put_company(f"PORTFOLIO::{bid}", {"rows": rows, "broker": BROKERS[bid]["name"]})
    _set(bid, error=None)
    return {"broker": bid, "holdings": len(rows)}


# ------------------------------------------------------------------ holdings file (any broker)
SYM_KEYS = ("symbol", "tradingsymbol", "trading symbol", "instrument", "stock", "stock name", "scrip", "scrip name", "ticker", "security", "name", "company")
QTY_KEYS = ("quantity", "qty", "qty.", "shares", "quantity available", "available qty", "net qty", "holding qty", "total quantity")
AVG_KEYS = ("avg. cost", "avg cost", "average cost", "average price", "avg. price", "avg price", "buy price", "buy avg", "cost price",
            "average buy price", "avg buy price", "avg. buy price", "purchase price", "cost basis per share")
LTP_KEYS = ("ltp", "last price", "current price", "cur. val price", "market price", "close price", "closing price", "price", "last")
ISIN_KEYS = ("isin", "isin code")


def _rows_from_bytes(data: bytes, filename: str) -> list[list[str]]:
    if filename.lower().endswith((".xlsx", ".xlsm")):
        try:
            import openpyxl
        except ImportError:
            raise BrokerError("Excel support needs: pip install openpyxl  (or save the file as CSV)")
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        best: list = []
        for ws in wb.worksheets:                       # the holdings sheet is the one with the most rows
            rows = [["" if v is None else str(v) for v in r] for r in ws.iter_rows(values_only=True)]
            if len(rows) > len(best):
                best = rows
        return best
    text = data.decode("utf-8-sig", errors="replace")
    return list(csv.reader(io.StringIO(text)))


def _isin_map() -> dict:
    f = config.DATA_DIR / "nse_all.csv"
    if not f.exists():
        return {}
    out = {}
    for r in csv.DictReader(io.StringIO(f.read_text(encoding="utf-8"))):
        r = {(k or "").strip().upper(): (v or "").strip() for k, v in r.items()}
        if r.get("ISIN NUMBER"):
            out[r["ISIN NUMBER"]] = r.get("SYMBOL")
    return out


def parse_file(data: bytes, filename: str, market: str = "IN") -> list[dict]:
    rows = _rows_from_bytes(data, filename)
    norm = lambda s: re.sub(r"\s+", " ", str(s or "").strip().lower())
    hi = None
    for i, r in enumerate(rows[:40]):                  # header row = first row naming a symbol and a quantity column
        cells = [norm(c) for c in r]
        if any(c in SYM_KEYS for c in cells) and any(c in QTY_KEYS for c in cells):
            hi = i
            break
    if hi is None:
        raise BrokerError("Couldn't find the header row. The file needs columns like Symbol / Instrument and Quantity / Qty.")
    head = [norm(c) for c in rows[hi]]

    def col(keys):
        for k in keys:
            if k in head:
                return head.index(k)
        return None
    cs, cq, ca, cl, ci = col(SYM_KEYS), col(QTY_KEYS), col(AVG_KEYS), col(LTP_KEYS), col(ISIN_KEYS)
    isin_sym = _isin_map() if market == "IN" else {}
    out = []
    for r in rows[hi + 1:]:
        if cs is None or len(r) <= max(x for x in (cs, cq) if x is not None):
            continue
        sym, isin = (r[cs] or "").strip(), (r[ci].strip() if ci is not None and ci < len(r) else None)
        if isin and isin in isin_sym:
            sym = isin_sym[isin]
        if not sym or sym.lower() in ("total", "grand total"):
            continue
        h = holding(market, sym, sym, r[cq], r[ca] if ca is not None and ca < len(r) else None,
                    r[cl] if cl is not None and cl < len(r) else None, isin, "File")
        if h:
            out.append(h)
    if not out:
        raise BrokerError("No holdings found in the file")
    return out


def import_file(data: bytes, filename: str, market: str) -> dict:
    rows = parse_file(data, filename, market)
    store.put_company("PORTFOLIO::file", {"rows": rows, "broker": "File", "filename": filename})
    return {"holdings": len(rows), "file": filename}


# ------------------------------------------------------------------ demo
def _demo_holdings(bid: str) -> list[dict]:
    if BROKERS[bid]["market"] == "US":
        return [holding("US", "TSTUS", "Test Corp US", 40, 152.4, 180.0, None, BROKERS[bid]["name"]),
                holding("US", "DEMO03", "Demo US Co 03", 25, 61.2, 58.9, None, BROKERS[bid]["name"])]
    return [holding("IN", "TESTCO", "Test Industries Ltd", 30, 1210.0, 1450.0, "INE000T01011", BROKERS[bid]["name"]),
            holding("IN", "TESTBANK", "Test Bank Ltd", 60, 512.5, 488.0, "INE000T01029", BROKERS[bid]["name"]),
            holding("IN", "DEMO03", "Demo Co 03", 120, 300.0, 341.2, None, BROKERS[bid]["name"]),
            holding("IN", "DEMO07", "Demo Co 07", 80, 520.0, 455.5, None, BROKERS[bid]["name"])]
