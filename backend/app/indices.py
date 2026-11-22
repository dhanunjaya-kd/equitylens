"""Headline indices for the top card (Yahoo Finance public chart feed, no key).

🇮🇳 NIFTY 50 · BANK NIFTY · SENSEX · INDIA VIX
🇺🇸 S&P 500 · NASDAQ · DOW JONES · RUSSELL 2000 · VIX
"""
from __future__ import annotations

import math
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional
from urllib.parse import quote

import requests

from . import config

INDICES = {
    "IN": [("^NSEI", "NIFTY 50", "index"), ("^NSEBANK", "BANK NIFTY", "index"), ("^BSESN", "SENSEX", "index"), ("^INDIAVIX", "INDIA VIX", "vix")],
    "US": [("^GSPC", "S&P 500", "index"), ("^IXIC", "NASDAQ", "index"), ("^DJI", "DOW JONES", "index"),
           ("^RUT", "RUSSELL 2000", "index"), ("^VIX", "VIX", "vix")],
}
URL = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"}
TTL = 60
_cache: dict = {}
_lock = threading.Lock()


def vix_mood(level: Optional[float], market: str) -> Optional[dict]:
    """Plain-English band for the volatility index (India VIX runs a little lower than the US VIX)."""
    if level is None:
        return None
    cuts = (12, 16, 22) if market == "IN" else (13, 20, 30)
    if level < cuts[0]:
        return {"label": "Calm", "tone": "good", "read": "Very low fear: traders expect small moves. Complacency can precede sharp moves."}
    if level < cuts[1]:
        return {"label": "Normal", "tone": "ok", "read": "Normal level of expected movement."}
    if level < cuts[2]:
        return {"label": "Nervous", "tone": "warn", "read": "Traders are paying up for protection: expect bigger daily swings."}
    return {"label": "Fear", "tone": "bad", "read": "High fear: large swings likely. Panic phases have often been better buying zones for long-term investors than euphoric ones."}


def prev_close_from_daily(daily: dict, price_time: Optional[int]) -> Optional[float]:
    """The previous session's close: the last daily close dated before the session of `price_time`
    (dates on the exchange's own clock). Yahoo's chartPreviousClose on a 1-day chart can point to an
    older session on weekends and holidays, which doubled the shown change."""
    res = ((daily or {}).get("chart") or {}).get("result") or []
    if not res or not price_time:
        return None
    r = res[0]
    meta = r.get("meta") or {}
    try:
        off = int(meta.get("gmtoffset"))
    except (TypeError, ValueError):
        off = 19800
    day = lambda t: time.strftime("%Y-%m-%d", time.gmtime(t + off))
    session = day(price_time)
    closes = ((r.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
    prev = None
    for t, c in zip(r.get("timestamp") or [], closes):
        if c is not None and day(t) < session:
            prev = c
    return prev


def parse(j: dict, sym: str, name: str, kind: str, market: str, daily: Optional[dict] = None) -> dict:
    res = ((j or {}).get("chart") or {}).get("result") or []
    if not res:
        raise ValueError(f"no data for {sym}")
    r = res[0]
    meta = r.get("meta") or {}
    closes = ((r.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
    ts = r.get("timestamp") or []
    pts = [(t, c) for t, c in zip(ts, closes) if c is not None]
    price = meta.get("regularMarketPrice") or (pts[-1][1] if pts else None)
    prev = prev_close_from_daily(daily, meta.get("regularMarketTime")) or meta.get("previousClose") or meta.get("chartPreviousClose")
    per = (meta.get("currentTradingPeriod") or {}).get("regular") or {}
    now = time.time()
    is_open = bool(per.get("start") and per.get("end") and per["start"] <= now < per["end"])
    chg = price - prev if price is not None and prev else None
    return {
        "symbol": sym, "name": name, "kind": kind, "market": market,
        "price": round(price, 2) if price is not None else None, "prev_close": round(prev, 2) if prev else None,
        "change": round(chg, 2) if chg is not None else None,
        "change_pct": round(chg / prev * 100, 2) if chg is not None and prev else None,
        "high": meta.get("regularMarketDayHigh"), "low": meta.get("regularMarketDayLow"),
        "hi52": meta.get("fiftyTwoWeekHigh"), "lo52": meta.get("fiftyTwoWeekLow"),
        "time": meta.get("regularMarketTime"), "open": is_open,
        "spark": [round(c, 2) for _, c in pts][-80:],
        "mood": vix_mood(price, market) if kind == "vix" else None,
    }


def _demo(sym: str, name: str, kind: str, market: str) -> dict:
    base = {"^NSEI": 24850, "^NSEBANK": 53900, "^BSESN": 81600, "^INDIAVIX": 13.4, "^GSPC": 6420, "^IXIC": 21350,
            "^DJI": 45100, "^RUT": 2310, "^VIX": 17.8}[sym]
    rnd = random.Random(sym)
    prev = base
    pts, p = [], prev
    for i in range(75):
        p *= 1 + rnd.uniform(-0.0012, 0.0013) + 0.0004 * math.sin(i / 9)
        pts.append(round(p, 2))
    return {"symbol": sym, "name": name, "kind": kind, "market": market, "price": pts[-1], "prev_close": prev,
            "change": round(pts[-1] - prev, 2), "change_pct": round((pts[-1] / prev - 1) * 100, 2), "high": max(pts), "low": min(pts),
            "hi52": round(base * 1.08, 2), "lo52": round(base * 0.86, 2), "time": int(time.time()), "open": False, "spark": pts,
            "mood": vix_mood(pts[-1], market) if kind == "vix" else None}


def _one(sym: str, name: str, kind: str, market: str) -> dict:
    if config.DEMO:
        return _demo(sym, name, kind, market)
    r = requests.get(URL.format(sym=quote(sym)), params={"range": "1d", "interval": "5m", "includePrePost": "false"},
                     headers=_UA, timeout=config.REQUEST_TIMEOUT)
    if r.status_code != 200:
        raise ValueError(f"Yahoo answered {r.status_code} for {sym}")
    daily = None
    try:
        d = requests.get(URL.format(sym=quote(sym)), params={"range": "10d", "interval": "1d"}, headers=_UA, timeout=config.REQUEST_TIMEOUT)
        daily = d.json() if d.status_code == 200 else None
    except (requests.RequestException, ValueError):
        daily = None
    return parse(r.json(), sym, name, kind, market, daily)


def get(market: str) -> dict:
    market = market.upper() if market.upper() in INDICES else "IN"
    with _lock:
        hit = _cache.get(market)
        if hit and time.time() - hit[0] < TTL:
            return hit[1]

    def safe(x):
        try:
            return _one(*x, market)
        except Exception as e:  # noqa: BLE001 - one failing index must not hide the others
            old = next((i for i in (_cache.get(market, (0, {"items": []}))[1]["items"]) if i["symbol"] == x[0]), None)
            return old or {"symbol": x[0], "name": x[1], "kind": x[2], "market": market, "price": None, "error": str(e)}

    with ThreadPoolExecutor(max_workers=5) as ex:
        items = list(ex.map(safe, INDICES[market]))
    out = {"market": market, "items": items, "updated": time.time(), "source": "Yahoo Finance public chart feed (may be delayed)"}
    with _lock:
        _cache[market] = (time.time(), out)
    return out
