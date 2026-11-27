"""🇺🇸 Every US-listed stock, and the Nasdaq-100 list, from Nasdaq's public JSON.

* All listed stocks: api.nasdaq.com/api/screener/stocks?exchange=nasdaq|nyse|amex&download=true
  (one request per exchange; rows: symbol, name, last sale, net change, % change, volume, market cap,
  country, IPO year, sector, industry). Saved raw as data/us_raw/nasdaq_screener_<exchange>.json.
* Nasdaq-100 members: api.nasdaq.com/api/quote/list-type/nasdaq100 (saved raw as nasdaq100.json).

Checks before a row is used:
  - common stock and ADRs only: names that say warrant, right, unit, preferred, note or depositary shares
    "each representing" a fraction of a preferred are dropped; tickers must look like a share ticker;
  - % change must agree with net change and last sale (within 0.05 points), otherwise the day move is left out;
  - market cap is kept as Nasdaq states it (dollars -> $ million); 0 or missing stays missing, never estimated;
  - the Nasdaq-100 list must have 95-110 names or it is not used.
Nasdaq's sector names are mapped to the S&P (GICS) sector names the app uses elsewhere (a name crosswalk,
listed in SECTOR_MAP); a stock keeps "Other" when Nasdaq gives no sector.
"""
from __future__ import annotations

import json
import re
import threading
import time
from typing import Optional

import requests

from . import calendars, config, store

SCREENER = "https://api.nasdaq.com/api/screener/stocks"
NDX_URL = "https://api.nasdaq.com/api/quote/list-type/nasdaq100"
EXCHANGES = ("nasdaq", "nyse", "amex")
EXCH_LABEL = {"nasdaq": "Nasdaq", "nyse": "NYSE", "amex": "NYSE American"}
RAW_DIR = config.DATA_DIR / "us_raw"
TTL_LISTED = 4 * 3600
TTL_NDX = 24 * 3600
SECTOR_MAP = {"Technology": "Information Technology", "Finance": "Financials", "Health Care": "Health Care",
              "Consumer Discretionary": "Consumer Discretionary", "Consumer Staples": "Consumer Staples",
              "Energy": "Energy", "Industrials": "Industrials", "Basic Materials": "Materials", "Utilities": "Utilities",
              "Real Estate": "Real Estate", "Telecommunications": "Communication Services"}
_NOT_COMMON = re.compile(r"\b(warrants?|rights?|units?|preferred|notes? due|debentures?|subordinated|trust preferred|"
                         r"depositary shares,? each representing a 1/|perpetual)\b", re.I)
_TICKER = re.compile(r"^[A-Z]{1,5}(-[A-Z]{1,2})?$")
_lock = threading.Lock()


def _save_raw(name: str, text: str) -> None:
    try:
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        (RAW_DIR / name).write_text(text, encoding="utf-8")
    except OSError:
        pass


def _num(v) -> Optional[float]:
    if v is None:
        return None
    s = re.sub(r"[$,%\s]", "", str(v))
    if s in ("", "NA", "N/A", "--", "-"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _rows(js: dict) -> list[dict]:
    d = (js or {}).get("data") or {}
    rows = d.get("rows")
    if rows is None and isinstance(d.get("table"), dict):
        rows = d["table"].get("rows")
    if rows is None and isinstance(d.get("data"), dict):
        rows = d["data"].get("rows")
    return [r for r in rows or [] if isinstance(r, dict)]


def ticker_of(raw: str) -> Optional[str]:
    t = str(raw or "").strip().upper().replace("/", "-").replace(".", "-")
    return t if _TICKER.match(t) else None


def parse_screener(js: dict, exchange: str) -> list[dict]:
    out = []
    for r in _rows(js):
        t, name = ticker_of(r.get("symbol")), str(r.get("name") or "").strip()
        if not t or not name or _NOT_COMMON.search(name):
            continue
        price, chg, pct = _num(r.get("lastsale")), _num(r.get("netchange")), _num(r.get("pctchange"))
        if price and chg is not None and pct is not None and price - chg > 0:
            if abs(chg / (price - chg) * 100 - pct) > 0.05:
                pct = None                                          # numbers disagree: leave the day move out
        cap = _num(r.get("marketCap"))
        sec = str(r.get("sector") or "").strip()
        ipo = _num(r.get("ipoyear"))
        out.append({"symbol": f"US:{t}", "name": name, "exchange": EXCH_LABEL.get(exchange, exchange),
                    "price": price, "change": chg, "chg_pct": pct, "volume": _num(r.get("volume")),
                    "market_cap": round(cap / 1e6, 1) if cap else None,
                    "sector": SECTOR_MAP.get(sec, "Other"), "nasdaq_sector": sec or None,
                    "industry": str(r.get("industry") or "").strip() or None,
                    "country": str(r.get("country") or "").strip() or None,
                    "ipo_year": int(ipo) if ipo and 1800 < ipo < 2100 else None})
    return out


def parse_ndx(js: dict) -> list[dict]:
    out = []
    for r in _rows(js):
        t = ticker_of(r.get("symbol"))
        if t:
            out.append({"symbol": f"US:{t}", "name": str(r.get("companyName") or r.get("name") or "").strip()})
    return out


def _get(url: str, params: dict, raw: str) -> dict:
    calendars._pace()
    r = requests.get(url, params=params, headers=calendars._NQ_HEADERS, timeout=max(config.REQUEST_TIMEOUT, 30))
    if r.status_code != 200:
        raise RuntimeError(f"Nasdaq answered {r.status_code}")
    _save_raw(raw, r.text)
    return r.json()


def listed(refresh: bool = False) -> dict:
    """{"rows": [...], "updated", "sources": [{exchange, ok, count, error}]} for every listed US common stock / ADR."""
    key = "USUNIV::listed"
    hit = store.get_company(key)
    if hit and not refresh and time.time() - hit[0] < TTL_LISTED:
        return hit[1]
    if config.DEMO:
        return {"rows": [], "updated": None, "sources": [], "demo": True}
    with _lock:
        rows, sources, seen = [], [], set()
        for ex in EXCHANGES:
            try:
                got = parse_screener(_get(SCREENER, {"tableonly": "true", "download": "true", "exchange": ex},
                                          f"nasdaq_screener_{ex}.json"), ex)
                new = [x for x in got if x["symbol"] not in seen]
                seen.update(x["symbol"] for x in new)
                rows += new
                sources.append({"exchange": EXCH_LABEL[ex], "ok": True, "count": len(new)})
            except Exception as e:  # noqa: BLE001
                sources.append({"exchange": EXCH_LABEL[ex], "ok": False, "count": 0, "error": str(e)[:120]})
        if not rows:
            if hit:
                return dict(hit[1], stale=True, sources=sources)
            return {"rows": [], "updated": None, "sources": sources}
        out = {"rows": rows, "updated": time.time(), "sources": sources}
        store.put_company(key, out)
        return out


def nasdaq100(refresh: bool = False) -> list[dict]:
    key = "USUNIV::ndx"
    hit = store.get_company(key)
    if hit and not refresh and time.time() - hit[0] < TTL_NDX:
        return hit[1]["rows"]
    if config.DEMO:
        return []
    try:
        rows = parse_ndx(_get(NDX_URL, {}, "nasdaq100.json"))
        if 95 <= len(rows) <= 110:
            store.put_company(key, {"rows": rows})
            return rows
    except Exception:  # noqa: BLE001
        pass
    return hit[1]["rows"] if hit else []


def by_symbol() -> dict:
    hit = store.get_company("USUNIV::listed")
    return {r["symbol"]: r for r in (hit[1]["rows"] if hit else [])}


def info(symbol: str) -> Optional[dict]:
    """The Nasdaq screener row for one stock (saved list only; no download here)."""
    return by_symbol().get(symbol if symbol.startswith("US:") else f"US:{symbol.upper()}")
