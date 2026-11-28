"""NSE sector and issued shares for every listed stock, from NSE's own data only.

1. NSE index lists that carry a sector ("Industry") column: NIFTY 500 and NIFTY Total Market
   (NIFTY 500 + Microcap 250, about 750 stocks), downloaded from niftyindices.com.
2. For every stock: NSE's quote data, looked up once in the background (NSE allows about one request a
   second) and saved. NSE's current quote answer (NextApi getSymbolData, secInfo) carries NSE's full
   four-level classification - macro-economic sector, sector, industry, basic industry - used by Money flow;
   the old quote-equity address (refused since Nov 2026) is only a fallback.
The same quote data gives the issued shares, so market cap = issued shares x last close for any stock
(shares are asked again after 90 days). Both use NSE's 22 sector names ("Financial Services", "Information Technology", ...), so all stocks are
grouped the same way. A stock NSE gives no sector for stays "Sector not known yet": nothing is guessed.
"""
from __future__ import annotations

import json
import threading
import time
from typing import Optional

from . import config, store, universe

UNKNOWN = "Sector not known yet"
KEY = "SECTORS::IN"
LIST_URLS = [  # (file, url) - the first that downloads is used for each list
    ("nifty_total_market.csv", "https://www.niftyindices.com/IndexConstituent/ind_niftytotalmarket_list.csv"),
    ("nifty_microcap250.csv", "https://www.niftyindices.com/IndexConstituent/ind_niftymicrocap250_list.csv"),
]
QUOTE_API = "https://www.nseindia.com/api/quote-equity"
NEXT_QUOTE = "https://www.nseindia.com/api/NextApi/apiClient/GetQuoteApi"
LEVELS = ("macro", "sector", "industry", "basic")
RETRY_DAYS = 30          # a stock NSE gave no sector for is asked again after a month
SHARES_DAYS = 90         # issued shares are refreshed every 3 months
STATE = {"running": False, "done": 0, "total": 0, "found": 0, "failed": 0, "started": None, "error": None}
_lock = threading.Lock()
_mem: dict = {}


def _saved() -> dict:
    hit = store.get_company(KEY)
    return hit[1] if hit else {"sectors": {}, "asked": {}}


def from_lists() -> dict:
    """{symbol: sector} from NSE index lists that carry a sector column."""
    hit = _mem.get("lists")
    if hit and time.time() - hit[0] < 3600:
        return hit[1]
    out: dict = {}
    if not config.DEMO:
        for name, url in LIST_URLS:
            for r in universe._cached_csv(name, url, universe._from_csv_text, max_age_days=30):
                if r.get("industry"):
                    out[r["symbol"]] = r["industry"]
    for r in universe.load(download=not config.DEMO)[0]:
        if r.get("industry"):
            out[r["symbol"]] = r["industry"]
    _mem["lists"] = (time.time(), out)
    return out


def sector_map() -> dict:
    """{symbol: NSE sector} from the lists, plus the stocks looked up one by one."""
    out = dict(_saved().get("sectors", {}))
    out.update(from_lists())
    return out


def _clean(v) -> Optional[str]:
    s = str(v or "").strip()
    return s if s and s.upper() not in ("NA", "-", "NULL", "N/A") else None


def parse_class(text: str) -> tuple[Optional[dict], Optional[float]]:
    """NSE quote JSON (current NextApi answer or the old quote-equity one) ->
    ({macro, sector, industry, basic} as NSE states them, issued shares)."""
    try:
        d = json.loads(text) or {}
    except (ValueError, TypeError):
        return None, None
    if isinstance(d, dict) and d.get("equityResponse"):
        e = (d["equityResponse"] or [{}])[0] or {}
        si, ti = e.get("secInfo") or {}, e.get("tradeInfo") or {}
        cls = {"macro": _clean(si.get("macro")), "sector": _clean(si.get("sector")),
               "industry": _clean(si.get("industryInfo")), "basic": _clean(si.get("basicIndustry"))}
        size = ti.get("issuedSize")
    else:
        ii = (d.get("industryInfo") or {}) if isinstance(d, dict) else {}
        cls = {"macro": _clean(ii.get("macro")), "sector": _clean(ii.get("sector")),
               "industry": _clean(ii.get("industry")), "basic": _clean(ii.get("basicIndustry"))}
        size = ((d.get("securityInfo") or {}) if isinstance(d, dict) else {}).get("issuedSize")
    try:
        sh = float(size)
        sh = sh if sh > 0 else None
    except (TypeError, ValueError):
        sh = None
    return (cls if any(cls.values()) else None), sh


def parse_quote(text: str) -> tuple[Optional[str], Optional[float]]:
    """NSE quote JSON -> (NSE sector, issued shares)."""
    cls, sh = parse_class(text)
    return (cls or {}).get("sector"), sh


def classes() -> dict:
    """{symbol: {macro, sector, industry, basic}} for every stock looked up so far."""
    return dict(_saved().get("class", {}))


def shares() -> dict:
    """{symbol: issued shares} from NSE."""
    return {k: v["n"] for k, v in _saved().get("shares", {}).items()}


def missing(symbols: list[str]) -> list[str]:
    """Stocks whose sector or issued shares are not known (or are due a refresh), in the order given."""
    known = sector_map()
    saved = _saved()
    asked, sh, cl = saved.get("asked", {}), saved.get("shares", {}), saved.get("class", {})
    now = time.time()
    out = []
    for s in symbols:
        need_sec = (s not in known or s not in cl) and now - asked.get(s, 0) > RETRY_DAYS * 86400
        need_sh = now - (sh.get(s) or {}).get("t", 0) > SHARES_DAYS * 86400 and now - asked.get(s, 0) > RETRY_DAYS * 86400
        if need_sec or need_sh:
            out.append(s)
    return out


def start_fill(symbols: list[str]) -> dict:
    """Look up the sector of each stock that has none yet, in the background (once; saved)."""
    if config.DEMO:
        return status()
    todo = missing(symbols)
    with _lock:
        if STATE["running"] or not todo:
            return status()
        STATE.update(running=True, done=0, total=len(todo), found=0, failed=0, started=time.time(), error=None)
    threading.Thread(target=_fill, args=(todo,), daemon=True).start()
    return status()


def _fill(todo: list[str]) -> None:
    from . import flows
    saved = _saved()
    sectors, asked, sh = saved.setdefault("sectors", {}), saved.setdefault("asked", {}), saved.setdefault("shares", {})
    cl = saved.setdefault("class", {})
    try:
        for k, sym in enumerate(todo, 1):
            try:
                ref = {"Referer": f"https://www.nseindia.com/get-quotes/equity?symbol={sym}"}
                text = flows._nse_text(NEXT_QUOTE, {"functionName": "getSymbolData", "marketType": "N", "series": "EQ", "symbol": sym}, headers=ref)
                c, n = parse_class(text) if text else (None, None)
                if not c and not n:
                    text = flows._nse_text(QUOTE_API, {"symbol": sym}, headers=ref)
                    c, n = parse_class(text) if text else (None, None)
                sec = (c or {}).get("sector")
                if c:
                    cl[sym] = c
                if sec:
                    sectors[sym] = sec
                if n:
                    sh[sym] = {"n": n, "t": time.time()}
                if sec or n:
                    STATE["found"] += 1
                if not sec or not n:
                    asked[sym] = time.time()
            except Exception:  # noqa: BLE001 - NSE busy for this one: ask again next time
                STATE["failed"] += 1
            STATE["done"] = k
            if k % 25 == 0:
                store.put_company(KEY, saved)
    except Exception as e:  # noqa: BLE001
        STATE["error"] = str(e)
    finally:
        store.put_company(KEY, saved)
        STATE["running"] = False


def status() -> dict:
    return dict(STATE)
