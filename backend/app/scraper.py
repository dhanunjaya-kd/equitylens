"""Fetches public company pages (no API key, no login).

Source: screener.in public pages. Everything here is plain HTTP GET of the same
pages a browser opens. Requests are paced and cached, so normal use stays light.
"""
from __future__ import annotations

import random
import re
import threading
import time
from typing import Optional
from urllib.parse import quote

import requests

from . import config

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-IN,en;q=0.9",
}

_session = requests.Session()
_session.headers.update(_HEADERS)
_lock = threading.Lock()
_last_call = 0.0
_MIN_GAP = 1.0  # never more than ~1 request/second, even for single lookups


class FetchError(Exception):
    pass


class NotFound(FetchError):
    pass


def _get(url: str, params: Optional[dict] = None, expect_json: bool = False):
    global _last_call
    with _lock:
        wait = _MIN_GAP - (time.time() - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.time()
    for attempt in range(3):
        try:
            r = _session.get(url, params=params, timeout=config.REQUEST_TIMEOUT)
        except requests.RequestException as e:
            if attempt == 2:
                raise FetchError(f"Network error: {e}") from e
            time.sleep(2 + attempt * 2)
            continue
        if r.status_code == 404:
            raise NotFound(url)
        if r.status_code == 429:
            # Source is asking us to slow down: back off properly
            time.sleep(15 * (attempt + 1) + random.random() * 5)
            continue
        if r.status_code >= 500:
            time.sleep(3 * (attempt + 1))
            continue
        if r.status_code != 200:
            raise FetchError(f"HTTP {r.status_code} for {url}")
        return r.json() if expect_json else r.text
    raise FetchError(f"Gave up after retries: {url}")


def clean_symbol(symbol: str) -> str:
    s = symbol.strip().upper()
    s = re.sub(r"^(NSE|BSE):", "", s)
    s = re.sub(r"-EQ$", "", s)
    return s


# ------------------------------------------------------------------ demo mode
_DEMO = {"TESTCO": ("testco.html", "Test Industries Ltd"), "TESTBANK": ("testbank.html", "Test Bank Ltd")}


def _demo_chart(query: str, days: int) -> dict:
    import datetime as dt
    import math
    start = dt.date.today() - dt.timedelta(days=days)
    pts = [(start + dt.timedelta(days=i)) for i in range(0, days, 3)]
    if query.startswith("Price to Earning"):
        pe = [[d.isoformat(), round(28 + 6 * math.sin(i / 60), 1)] for i, d in enumerate(pts)]
        eps = [[d.isoformat(), round(30 * 1.13 ** (i * 3 / 365), 2)] for i, d in enumerate(pts)]
        return {"datasets": [{"metric": "Price to Earning", "values": pe},
                             {"metric": "Median PE", "values": [[d.isoformat(), 31.5] for d in pts]},
                             {"metric": "EPS", "values": eps}]}
    px = [[d.isoformat(), round(300 * 1.17 ** (i * 3 / 365) * (1 + 0.08 * math.sin(i / 25)), 1)] for i, d in enumerate(pts)]
    dma = [[p[0], round(p[1] * 0.97, 1)] for p in px]
    return {"datasets": [{"metric": "Price", "values": px}, {"metric": "DMA200", "values": dma}]}


def search(query: str) -> list[dict]:
    """Company search. Returns [{name, symbol, url}]."""
    q = query.strip()
    if not q:
        return []
    if config.DEMO:
        return [{"name": n, "symbol": s, "url": f"/company/{s}/"} for s, (_, n) in _DEMO.items()
                if q.lower() in s.lower() or q.lower() in n.lower()]
    data = _get(f"{config.SOURCE_BASE}/api/company/search/", {"q": q, "v": 3, "fts": 1}, expect_json=True)
    out = []
    for item in data or []:
        url = item.get("url") or ""
        m = re.match(r"^/company/([^/]+)/", url)
        if not m:
            continue
        out.append({"name": item.get("name", ""), "symbol": m.group(1).upper(), "url": url})
    return out


def fetch_company_html(symbol: str) -> tuple[str, str]:
    """Return (html, view) where view is 'consolidated' or 'standalone'.

    Consolidated numbers are preferred (they include subsidiaries). Some
    companies only file standalone results, so fall back when the
    consolidated page has no annual numbers.
    """
    if config.DEMO:
        f = _DEMO.get(clean_symbol(symbol))
        if not f:
            raise NotFound(symbol)
        return (config.FIXTURE_DIR / f[0]).read_text(encoding="utf-8"), "consolidated"
    sym = quote(clean_symbol(symbol), safe="-")
    try:
        html = _get(f"{config.SOURCE_BASE}/company/{sym}/consolidated/")
        if _has_annual_numbers(html):
            return html, "consolidated"
    except NotFound:
        pass
    html = _get(f"{config.SOURCE_BASE}/company/{sym}/")
    return html, "standalone"


def _has_annual_numbers(html: str) -> bool:
    i = html.find('id="profit-loss"')
    if i < 0:
        return False
    chunk = html[i:i + 20000]
    # at least one cell with a digit inside the P&L table body
    return bool(re.search(r"<td[^>]*>\s*-?[\d,]+\.?\d*\s*</td>", chunk))


def fetch_peers_html(warehouse_id: str) -> str:
    if config.DEMO:
        return (config.FIXTURE_DIR / "peers.html").read_text(encoding="utf-8")
    return _get(f"{config.SOURCE_BASE}/api/company/{warehouse_id}/peers/")


def fetch_chart(company_id: str, query: str, days: int = 3650, consolidated: bool = True) -> dict:
    if config.DEMO:
        return _demo_chart(query, days)
    params = {"q": query, "days": days}
    if consolidated:
        params["consolidated"] = "true"
    return _get(f"{config.SOURCE_BASE}/api/company/{company_id}/chart/", params, expect_json=True)
