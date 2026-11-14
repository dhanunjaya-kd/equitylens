"""Which stocks a full scan covers.

Order of preference:
1. backend/data/universe.txt  — your own list, one NSE symbol per line (wins if present)
2. NIFTY 500 constituents downloaded from niftyindices.com (saved to data/nifty500.csv)
3. A built-in starter list of large, well-known companies
"""
from __future__ import annotations

import csv
import io

import requests

from . import config

NIFTY500_URL = "https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv"

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
        if sym and (r.get("Series") or "EQ").strip() == "EQ":
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
