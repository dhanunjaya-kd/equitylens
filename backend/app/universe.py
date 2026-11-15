"""Which stocks a scan / the movers cover: 🇮🇳 NIFTY 50 · NIFTY 100 · NIFTY 500 · All NSE.

Sources (official, free):
* NIFTY 50 / 100 / 500 constituents — NSE Indices CSVs (niftyindices.com/IndexConstituent/…)
* All NSE stocks — NSE's list of every listed equity (EQUITY_L.csv), EQ and BE series

Order of preference for the default (NIFTY 500) list:
1. backend/data/universe.txt  — your own list, one NSE symbol per line (wins if present)
2. NIFTY 500 constituents downloaded from niftyindices.com (saved to data/nifty500.csv)
3. A built-in starter list of large, well-known companies
"""
from __future__ import annotations

import csv
import io
import time

import requests

from . import config

NIFTY500_URL = "https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv"
INDEX_URLS = {"N50": "https://www.niftyindices.com/IndexConstituent/ind_nifty50list.csv",
              "N100": "https://www.niftyindices.com/IndexConstituent/ind_nifty100list.csv",
              "N500": NIFTY500_URL}
ALL_NSE_URL = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
LABELS = {"N50": "NIFTY 50", "N100": "NIFTY 100", "N500": "NIFTY 500", "ALL": "All NSE stocks"}
_mem: dict = {}

STARTER = [
    "RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "INFY", "BHARTIARTL", "ITC", "SBIN", "LT", "HINDUNILVR",
    "KOTAKBANK", "AXISBANK", "BAJFINANCE", "ASIANPAINT", "MARUTI", "SUNPHARMA", "TITAN", "ULTRACEMCO",
    "NESTLEIND", "WIPRO", "HCLTECH", "TECHM", "POWERGRID", "NTPC", "ONGC", "COALINDIA", "M&M", "BAJAJ-AUTO",
    "HEROMOTOCO", "EICHERMOT", "DRREDDY", "CIPLA", "DIVISLAB", "BRITANNIA", "TATASTEEL", "JSWSTEEL",
    "HINDALCO", "GRASIM", "ADANIPORTS", "BAJAJFINSV", "INDUSINDBK", "SBILIFE", "HDFCLIFE", "APOLLOHOSP",
    "TATACONSUM", "PIDILITIND", "DMART", "HAVELLS", "DABUR", "MARICO", "COLPAL", "BERGEPAINT", "PAGEIND",
    "TRENT", "BEL", "HAL", "SIEMENS", "ABB", "LTIM", "BAJAJHLDNG",
]


def _from_csv_text(text: str) -> list[dict]:
    rows = []
    for r in csv.DictReader(io.StringIO(text)):
        sym = (r.get("Symbol") or "").strip()
        if sym:                                            # index lists: keep every constituent (a few trade in BE / BZ series)
            rows.append({"symbol": sym, "name": (r.get("Company Name") or "").strip(),
                         "industry": (r.get("Industry") or "").strip()})
    return rows


def load(download: bool = True) -> tuple[list[dict], str]:
    if config.DEMO:
        return [{"symbol": "TESTCO", "name": "Test Industries Ltd", "industry": "Industrial Products"},
                {"symbol": "TESTBANK", "name": "Test Bank Ltd", "industry": "Banks"}], "demo"
    own = config.DATA_DIR / "universe.txt"
    if own.exists():
        syms = [l.strip().upper() for l in own.read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]
        return [{"symbol": s, "name": "", "industry": ""} for s in syms], "data/universe.txt"

    cached = config.DATA_DIR / "nifty500.csv"
    if download:
        try:
            r = requests.get(NIFTY500_URL, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code == 200 and "Symbol" in r.text[:500]:
                cached.write_text(r.text, encoding="utf-8")
        except requests.RequestException:
            pass
    if cached.exists():
        rows = _from_csv_text(cached.read_text(encoding="utf-8"))
        if rows:
            return rows, "NIFTY 500 (niftyindices.com)"
    return [{"symbol": s, "name": "", "industry": ""} for s in STARTER], "built-in starter list"


def local_search(q: str, limit: int = 10) -> list[dict]:
    rows, _ = load(download=False)
    ql = q.lower().strip()
    hits = [r for r in rows if ql in r["symbol"].lower() or ql in r["name"].lower()]
    hits.sort(key=lambda r: (not r["symbol"].lower().startswith(ql), r["symbol"]))
    return [{"name": r["name"] or r["symbol"], "symbol": r["symbol"]} for r in hits[:limit]]


# ---------------------------------------------------------------- NIFTY 50 / 100 / 500 / All NSE
def _demo_lists() -> dict:
    from . import movers
    syms = movers._universe("IN")
    extra = [{"symbol": f"SMALL{i:02d}", "name": f"Small Co {i:02d}", "industry": "Textiles"} for i in range(1, 11)]
    return {"N50": syms[:10], "N100": syms[:20], "N500": syms, "ALL": syms + extra}


def parse_equity_l(text: str) -> list[dict]:
    """NSE EQUITY_L.csv → every listed company (EQ and BE series)."""
    rows = []
    for r in csv.DictReader(io.StringIO(text.lstrip("\ufeff"))):
        r = {(k or "").strip().upper(): (v or "").strip() for k, v in r.items()}
        if r.get("SYMBOL") and r.get("SERIES") in ("EQ", "BE"):
            rows.append({"symbol": r["SYMBOL"].upper(), "name": r.get("NAME OF COMPANY", ""), "industry": ""})
    return rows


def _cached_csv(name: str, url: str, parse, max_age_days: float = 7) -> list[dict]:
    f = config.DATA_DIR / name
    if not f.exists() or time.time() - f.stat().st_mtime > max_age_days * 86400:
        try:
            if "nsearchives" in url:
                from . import flows
                text = flows._nse_text(url) or ""
            else:
                r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
                text = r.text if r.status_code == 200 else ""
            if text and parse(text):
                f.write_text(text, encoding="utf-8")
        except Exception:  # noqa: BLE001 - keep the old copy if the site is down
            pass
    return parse(f.read_text(encoding="utf-8")) if f.exists() else []


def index_list(code: str) -> list[dict]:
    """code: N50 · N100 · N500 · ALL"""
    code = code.upper() if code and code.upper() in LABELS else "N500"
    if config.DEMO:
        return _demo_lists()[code]
    hit = _mem.get(code)
    if hit and time.time() - hit[0] < 3600:
        return hit[1]
    if code == "ALL":
        rows = _cached_csv("nse_all.csv", ALL_NSE_URL, parse_equity_l)
        if not rows:                                   # fall back to the biggest list we have
            rows = index_list("N500")
    elif code == "N500":
        rows = load(download=True)[0]
    else:
        rows = _cached_csv(f"{code.lower()}.csv", INDEX_URLS[code], _from_csv_text) or load(download=True)[0]
    _mem[code] = (time.time(), rows)
    return rows


def membership() -> dict:
    """{symbol: ["N50", "N100", "N500"]} — which NIFTY indices each stock belongs to."""
    hit = _mem.get("member")
    if hit and time.time() - hit[0] < 3600:
        return hit[1]
    out: dict = {}
    for code in ("N500", "N100", "N50"):
        for r in index_list(code):
            out.setdefault(r["symbol"], []).append(code)
    _mem["member"] = (time.time(), out)
    return out
