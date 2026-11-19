"""Pre-market (India): overnight markets and the NIFTY opening call, with its own track record.

The opening call is one fixed, transparent score, written down on 19 Nov 2026 BEFORE any data was looked at:

    S&P 500 change x3 · US VIX change x-1 · Brent crude change x-1 · USD/INR change x-1

Each change is the last session that had CLOSED before 09:15 IST on the NIFTY day (a market's session date, in its
own time zone, earlier than the NIFTY date), divided by that market's own past-year daily volatility and capped at
±3. Score = 100 x (weighted sum) / 6, capped at ±100.  Score ≥ +20 → gap-up likely · ≤ −20 → gap-down likely ·
otherwise flat or mixed. The backtest (backtest()) uses exactly the same function on every NIFTY day since 2016, and
every live call is frozen at 09:14 and checked against the real open afterwards. Nothing here was tuned on results.

GIFT Nifty has no free official feed and no free history, so it can't be read or tested here; the page says so.
"""
from __future__ import annotations

import logging
import random
import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from urllib.parse import quote

import requests

from . import config, store

log = logging.getLogger("equitylens.premarket")
IST = timezone(timedelta(hours=5, minutes=30))
YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"}

# --- the opening-call rules: fixed up front, not tuned -------------------------------------------------------------
FACTORS = [
    {"sym": "^GSPC", "name": "S&P 500", "w": 3, "why": "US stocks set the tone for Asia and India the next morning"},
    {"sym": "^VIX", "name": "US VIX", "w": -1, "why": "Rising fear in the US usually means a weaker open"},
    {"sym": "BZ=F", "name": "Brent crude", "w": -1, "why": "India imports most of its oil, so dearer crude hurts"},
    {"sym": "INR=X", "name": "USD/INR", "w": -1, "why": "A weaker rupee usually comes with foreign selling"},
]
SCALE = sum(abs(f["w"]) for f in FACTORS)     # 6
CLIP_Z, VOL_DAYS = 3.0, 250
UP, DOWN = 20, -20
SPLIT = "2021-01-01"
PASS_RULE = ("Right more than 55% of the time on its up/down calls AND at least 5 points better than always guessing "
             "the more common direction, in both 2016-20 and 2021 on. Fixed before the backtest was run.")
NIFTY = "^NSEI"

# --- the overnight board: what each tile means for NIFTY (direction +1: up is good, -1: up is bad, 0: mixed) --------
GROUPS_IN = [
    ("India before the open", [("^INDIAVIX", "India VIX (last close)", -1, 3.0, "Expected NIFTY volatility for the next 30 days")]),
    ("US close and futures now", [("^GSPC", "S&P 500", 1, 0.25, "US close at 02:30 IST sets the morning mood"),
                                  ("^IXIC", "NASDAQ", 1, 0.3, "Leads Indian IT and tech stocks"),
                                  ("^DJI", "Dow Jones", 1, 0.25, "Broad US mood"),
                                  ("ES=F", "S&P 500 futures (now)", 1, 0.2, "How the US is trading after its close")]),
    ("Asia this morning", [("^N225", "Nikkei 225", 1, 0.3, "Japan, open since 05:30 IST"),
                           ("^HSI", "Hang Seng", 1, 0.3, "Hong Kong and China mood; metals watch it"),
                           ("^KS11", "Kospi", 1, 0.3, "Korea, often moves with global tech")]),
    ("Commodities and crypto", [("BZ=F", "Brent crude", -1, 0.75, "Dearer crude hurts India's import bill, oil marketers, paints and airlines"),
                                ("GC=F", "Gold", 0, 0.5, "Safe-haven demand: rising gold can mean rising worry"),
                                ("SI=F", "Silver", 0, 0.75, "Industrial and safe-haven metal"),
                                ("BTC-USD", "Bitcoin", 1, 1.5, "A read on global risk appetite")]),
    ("Currency and rates", [("INR=X", "USD / INR", -1, 0.15, "A weaker rupee hurts importers, helps IT and pharma exporters"),
                            ("DX-Y.NYB", "Dollar index", -1, 0.2, "A strong dollar usually pulls money out of India"),
                            ("^TNX", "US 10-year yield", -1, 1.0, "Higher US yields weigh on emerging markets")]),
    ("Risk", [("^VIX", "US VIX", -1, 3.0, "US fear gauge: falling is good for risk")]),
]
GIFT_NOTE = ("It trades on NSE IX, which has no free official data feed, and it has no free price history, so "
             "EquityLens can't read or test it. Check it in your broker app before 09:15: it is the closest guide to the open.")

_lock = threading.Lock()
_cache: dict = {}


# ------------------------------------------------------------------ prices
def _yahoo(sym: str, rng: str) -> tuple[list[dict], dict]:
    r = requests.get(YAHOO.format(sym=quote(sym)), params={"range": rng, "interval": "1d", "includePrePost": "false"},
                     headers=_UA, timeout=config.REQUEST_TIMEOUT)
    if r.status_code != 200:
        raise ValueError(f"Yahoo answered {r.status_code} for {sym}")
    res = ((r.json().get("chart") or {}).get("result") or [None])[0]
    if not res:
        raise ValueError(f"no data for {sym}")
    return parse_daily(res), res.get("meta") or {}


def parse_daily(res: dict) -> list[dict]:
    """Daily candles dated in the market's OWN time zone (a US session keeps its US date)."""
    meta = res.get("meta") or {}
    off = int(meta.get("gmtoffset") or 0)
    ts = res.get("timestamp") or []
    q = ((res.get("indicators") or {}).get("quote") or [{}])[0]
    out = {}
    for i, t in enumerate(ts):
        o, h, l, c = (q.get(k, [None] * len(ts))[i] for k in ("open", "high", "low", "close"))
        if c is None or c <= 0:
            continue
        day = (datetime.fromtimestamp(t + off, timezone.utc)).date().isoformat()
        out[day] = {"t": day, "o": o if o and o > 0 else None, "h": h, "l": l, "c": c}
    return [out[k] for k in sorted(out)]


def _demo_daily(sym: str) -> list[dict]:
    """Synthetic 10 years: NIFTY's gap follows the S&P 500 and crude, so the demo shows a working call."""
    rnd = random.Random(sym)
    start = date(2016, 1, 1)
    days = [start + timedelta(days=i) for i in range((date.today() - start).days) if (start + timedelta(days=i)).weekday() < 5]
    if sym == NIFTY:
        spx = {b["t"]: b for b in _demo_daily("^GSPC")}
        crude = {b["t"]: b for b in _demo_daily("BZ=F")}
        out, c = [], 8000.0
        prev_s = prev_c = None
        for d in days:
            k = (d - timedelta(days=1 if d.weekday() else 3)).isoformat()
            s, cr = spx.get(k), crude.get(k)
            sig = 0.0
            if s and prev_s:
                sig += 0.6 * (s["c"] / prev_s - 1)
            if cr and prev_c:
                sig -= 0.1 * (cr["c"] / prev_c - 1)
            prev_s, prev_c = (s or {}).get("c", prev_s), (cr or {}).get("c", prev_c)
            o = c * (1 + sig + rnd.gauss(0, 0.002))
            c = o * (1 + rnd.gauss(0.0003, 0.008))
            out.append({"t": d.isoformat(), "o": o, "h": max(o, c), "l": min(o, c), "c": c})
        return out
    vol = {"^VIX": 0.06, "BZ=F": 0.02, "INR=X": 0.003}.get(sym, 0.01)
    px, out = 100.0, []
    for d in days:
        px *= 1 + rnd.gauss(0.0002, vol)
        out.append({"t": d.isoformat(), "o": px, "h": px, "l": px, "c": px})
    return out


def daily(sym: str, max_age: float = 1200) -> list[dict]:
    if config.DEMO:
        return _demo_daily(sym)
    key = f"PM::BARS::{sym}"
    hit = store.get_company(key)
    if hit and time.time() - hit[0] < max_age:
        return hit[1]["bars"]
    bars, _ = _yahoo(sym, "10y")
    try:
        recent, _ = _yahoo(sym, "5d")
        by = {b["t"]: b for b in bars}
        by.update({b["t"]: b for b in recent})
        bars = [by[k] for k in sorted(by)]
    except Exception:  # noqa: BLE001 - the long series is still usable
        pass
    store.put_company(key, {"bars": bars})
    return bars


# ------------------------------------------------------------------ the score (one function: live and backtest)
def factor_values(series: dict, day: str) -> list[dict]:
    """Each factor's last session that closed before the NIFTY day, scaled by its own past-year volatility."""
    out = []
    for f in FACTORS:
        bars = series.get(f["sym"]) or []
        lo, hi = 0, len(bars)
        while lo < hi:                       # first bar dated on/after the NIFTY day
            mid = (lo + hi) // 2
            if bars[mid]["t"] < day:
                lo = mid + 1
            else:
                hi = mid
        k = lo - 1                           # last bar strictly before
        if k < VOL_DAYS + 1:
            out.append(dict(f, ret=None, z=None, contrib=0.0, date=None))
            continue
        closes = [b["c"] for b in bars[k - VOL_DAYS - 1:k + 1]]
        rets = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))]
        vol = statistics.pstdev(rets[:-1]) or 1e-9
        z = max(-CLIP_Z, min(CLIP_Z, rets[-1] / vol))
        out.append(dict(f, ret=round(rets[-1] * 100, 2), z=round(z, 2), contrib=round(f["w"] * z, 2), date=bars[k]["t"]))
    return out


def score_of(factors: list[dict]) -> Optional[float]:
    if any(f["z"] is None for f in factors):
        return None
    return round(max(-100.0, min(100.0, 100 * sum(f["contrib"] for f in factors) / SCALE)), 1)


def call_of(score: Optional[float]) -> dict:
    if score is None:
        return {"call": "na", "label": "Not enough data", "lean": "No call"}
    if score >= UP:
        return {"call": "up", "label": "Gap-up likely", "lean": "Leaning positive"}
    if score <= DOWN:
        return {"call": "down", "label": "Gap-down likely", "lean": "Leaning negative"}
    return {"call": "flat", "label": "Flat or mixed open", "lean": "No clear lean"}


# ------------------------------------------------------------------ backtest
def _pct(n, d):
    return round(n / d * 100, 1) if d else None


def summarize(rows: list[dict]) -> dict:
    up = [r for r in rows if r["call"] == "up"]
    dn = [r for r in rows if r["call"] == "down"]
    fl = [r for r in rows if r["call"] == "flat"]
    dirn = up + dn
    gap_right = sum(r["gap"] > 0 for r in up) + sum(r["gap"] < 0 for r in dn)
    day_right = sum(r["day"] > 0 for r in up) + sum(r["day"] < 0 for r in dn)
    p_up_gap = _pct(sum(r["gap"] > 0 for r in rows), len(rows))
    p_up_day = _pct(sum(r["day"] > 0 for r in rows), len(rows))
    avg = lambda xs: round(statistics.mean(xs) * 100, 2) if xs else None
    return {
        "days": len(rows), "up_calls": len(up), "down_calls": len(dn), "flat_calls": len(fl),
        "gap_hit": _pct(gap_right, len(dirn)), "gap_up_hit": _pct(sum(r["gap"] > 0 for r in up), len(up)),
        "gap_down_hit": _pct(sum(r["gap"] < 0 for r in dn), len(dn)),
        "gap_naive": round(max(p_up_gap, 100 - p_up_gap), 1) if p_up_gap is not None else None, "gap_up_share": p_up_gap,
        "avg_gap_up_calls": avg([r["gap"] for r in up]), "avg_gap_down_calls": avg([r["gap"] for r in dn]),
        "avg_abs_gap_flat_calls": avg([abs(r["gap"]) for r in fl]),
        "day_hit": _pct(day_right, len(dirn)),
        "day_naive": round(max(p_up_day, 100 - p_up_day), 1) if p_up_day is not None else None,
    }


def _passes(first: dict, second: dict, hit: str, naive: str) -> Optional[bool]:
    vals = [(h.get(hit), h.get(naive)) for h in (first, second)]
    if any(a is None or b is None for a, b in vals):
        return None
    return all(a > 55 and a - b >= 5 for a, b in vals)


def backtest(series: Optional[dict] = None, save: bool = True) -> dict:
    """Replay the opening call on every NIFTY day since 2016 and measure the real open (and close)."""
    if series is None:
        series = {f["sym"]: daily(f["sym"], max_age=6 * 3600) for f in FACTORS}
        series[NIFTY] = daily(NIFTY, max_age=6 * 3600)
    nifty = series[NIFTY]
    rows, skipped = [], {"no open price": 0, "open equals the previous close (data gap)": 0, "not enough history": 0}
    for i in range(1, len(nifty)):
        b, p = nifty[i], nifty[i - 1]
        if not b.get("o"):
            skipped["no open price"] += 1
            continue
        if abs(b["o"] - p["c"]) < 1e-9:
            skipped["open equals the previous close (data gap)"] += 1
            continue
        fv = factor_values(series, b["t"])
        s = score_of(fv)
        if s is None:
            skipped["not enough history"] += 1
            continue
        rows.append({"t": b["t"], "score": s, "call": call_of(s)["call"], "gap": b["o"] / p["c"] - 1, "day": b["c"] / b["o"] - 1})
    first = summarize([r for r in rows if r["t"] < SPLIT])
    second = summarize([r for r in rows if r["t"] >= SPLIT])
    out = {"built": datetime.now(IST).strftime("%Y-%m-%d %H:%M"), "market": "IN", "from": rows[0]["t"] if rows else None,
           "to": rows[-1]["t"] if rows else None, "all": summarize(rows), "first_half": first, "second_half": second,
           "gap_passed": _passes(first, second, "gap_hit", "gap_naive"),
           "day_passed": _passes(first, second, "day_hit", "day_naive"),
           "rules": {"factors": [{k: f[k] for k in ("name", "w", "why")} for f in FACTORS], "up": UP, "down": DOWN,
                     "pass_rule": PASS_RULE, "split": SPLIT},
           "skipped": skipped}
    if save:
        store.put_company("PREMARKET_TRACK::IN", out)
    return out


def track() -> Optional[dict]:
    hit = store.get_company("PREMARKET_TRACK::IN")
    return hit[1] if hit else None


# ------------------------------------------------------------------ live board
def quote_one(sym: str) -> dict:
    """Latest price and change vs the previous close (Yahoo chart meta)."""
    if config.DEMO:
        rnd = random.Random(sym + date.today().isoformat())
        prev = 100.0
        px = prev * (1 + rnd.uniform(-0.012, 0.012))
        return {"price": round(px, 2), "prev_close": prev, "change_pct": round((px / prev - 1) * 100, 2), "time": int(time.time())}
    r = requests.get(YAHOO.format(sym=quote(sym)), params={"range": "1d", "interval": "5m", "includePrePost": "false"},
                     headers=_UA, timeout=config.REQUEST_TIMEOUT)
    if r.status_code != 200:
        raise ValueError(f"Yahoo answered {r.status_code} for {sym}")
    meta = (((r.json().get("chart") or {}).get("result") or [{}])[0] or {}).get("meta") or {}
    px, prev = meta.get("regularMarketPrice"), meta.get("chartPreviousClose") or meta.get("previousClose")
    if not px or not prev:
        raise ValueError(f"no price for {sym}")
    return {"price": round(px, 4 if px < 10 else 2), "prev_close": prev, "change_pct": round((px / prev - 1) * 100, 2),
            "time": meta.get("regularMarketTime")}


def impact(direction: int, chg: Optional[float], neutral: float) -> str:
    if chg is None or direction == 0 or abs(chg) < neutral:
        return "neutral"
    return "positive" if chg * direction > 0 else "negative"


def fii_dii() -> list[dict]:
    """Yesterday's provisional FII / DII cash-market net (NSE). Empty if NSE doesn't answer."""
    if config.DEMO:
        return [{"name": "FII / FPI cash", "net": -1234.5, "date": "18-Nov-2026"}, {"name": "DII cash", "net": 2210.3, "date": "18-Nov-2026"}]
    hit = store.get_company("PM::FIIDII")
    if hit and time.time() - hit[0] < 3600:
        return hit[1]["rows"]
    import json as _json

    from . import flows
    txt = flows._nse_text("https://www.nseindia.com/api/fiidiiTradeReact")
    rows = []
    for r in (_json.loads(txt) if txt else []):
        cat = str(r.get("category", ""))
        try:
            net = float(str(r.get("netValue", "")).replace(",", ""))
        except ValueError:
            continue
        rows.append({"name": "FII / FPI cash" if "FII" in cat.upper() or "FPI" in cat.upper() else "DII cash", "net": net, "date": r.get("date")})
    store.put_company("PM::FIIDII", {"rows": rows})
    return rows


def session_day(now: Optional[datetime] = None) -> str:
    """The NIFTY session the call is for: today until the 15:30 close on a weekday, else the next weekday."""
    now = now or datetime.now(IST)
    d = now.date()
    if d.weekday() >= 5 or (now.hour, now.minute) >= (15, 30):
        d += timedelta(days=1)
        while d.weekday() >= 5:
            d += timedelta(days=1)
    return d.isoformat()


def _today_items(day: str) -> list[dict]:
    items = []
    try:
        from . import calendars
        d = date.fromisoformat(day)
        ev = calendars.economy("IN", d, 1)
        for e in ev.get("events", [])[:4]:
            items.append({"time": (e.get("at") or "")[11:16] or "—", "text": e.get("event"), "kind": "economy"})
        er = calendars.earnings("IN", d, 1)
        res = [r for r in er.get("rows", []) if r.get("type") == "Results"]
        if res:
            names = ", ".join(r["symbol"] for r in res[:6])
            items.append({"time": "Results", "text": f"{len(res)} companies announce results, including {names}", "kind": "results",
                          "symbols": [r["symbol"] for r in res[:12]]})
    except Exception as e:  # noqa: BLE001 - the page works without the calendar
        log.info("pre-market calendar skipped: %s", e)
    if date.fromisoformat(day).weekday() == 1:
        items.append({"time": "15:30", "text": "NIFTY weekly options expiry (Tuesday)", "kind": "expiry"})
    return items


def live_calls(nifty: Optional[list[dict]] = None, n: int = 20) -> dict:
    """Every frozen 09:14 call, checked against the real NIFTY open and close."""
    keys = sorted(store.keys_like("PREMARKET::CALL::IN::%"), reverse=True)[:60]
    if not keys:
        return {"rows": [], "checked": 0, "right": 0}
    try:
        nb = nifty or daily(NIFTY)
    except Exception:  # noqa: BLE001
        nb = []
    bars = {b["t"]: (i, b) for i, b in enumerate(nb)}
    rows, checked, right = [], 0, 0
    for k in keys:
        c = store.get_company(k)[1]
        hit = bars.get(c["day"])
        row = {"day": c["day"], "score": c["score"], "call": c["call"], "label": c["label"], "gap": None, "move": None, "right": None}
        if hit and hit[0] > 0 and hit[1].get("o"):
            i, b = hit
            prev = nb[i - 1]["c"]
            row["gap"], row["move"] = round((b["o"] / prev - 1) * 100, 2), round((b["c"] / b["o"] - 1) * 100, 2)
            if c["call"] in ("up", "down"):
                row["right"] = (row["gap"] > 0) == (c["call"] == "up")
                checked += 1
                right += bool(row["right"])
        rows.append(row)
    return {"rows": rows[:n], "checked": checked, "right": right}


def build(market: str = "IN", refresh: bool = False) -> dict:
    market = "IN"   # the US page comes next
    with _lock:
        hit = _cache.get(market)
        if hit and not refresh and time.time() - hit[0] < 600:
            return hit[1]
    now = datetime.now(IST)
    day = session_day(now)
    notes = []
    series = {}

    def _daily(f):
        try:
            return f, daily(f["sym"]), None
        except Exception as e:  # noqa: BLE001
            return f, None, e

    def _quote(sym):
        try:
            return sym, quote_one(sym), None
        except Exception as e:  # noqa: BLE001 - one missing tile never hides the rest
            return sym, None, e

    tile_syms = sorted({t[0] for _, tiles in GROUPS_IN for t in tiles})
    with ThreadPoolExecutor(max_workers=8) as ex:          # ~25 Yahoo calls in parallel instead of one by one
        got_daily = list(ex.map(_daily, FACTORS + [{"sym": NIFTY, "name": "NIFTY 50"}]))
        quotes = {sym: (q, e) for sym, q, e in ex.map(_quote, tile_syms)}
        flows_future = ex.submit(fii_dii)
        today_future = ex.submit(_today_items, day)
    for f, bars, e in got_daily:
        if bars is None:
            notes.append(f"{f.get('name')}: prices not available ({e})")
        else:
            series[f["sym"]] = bars
    fv = factor_values(series, day)
    sc = score_of(fv)
    call = call_of(sc)

    groups = []
    for gname, tiles in GROUPS_IN:
        items = []
        for sym, name, direction, neutral, why in tiles:
            q, e = quotes.get(sym, (None, "not fetched"))
            if q is None:
                items.append({"sym": sym, "name": name, "price": None, "change_pct": None, "impact": "neutral", "why": why, "error": str(e)})
                continue
            items.append({"sym": sym, "name": name, **q, "impact": impact(direction, q["change_pct"], neutral), "why": why})
        groups.append({"name": gname, "items": items})
    flows_rows = []
    try:
        for r in flows_future.result():
            flows_rows.append({"name": r["name"], "net": r["net"], "date": r["date"],
                               "impact": impact(1, r["net"], 500), "why": "NSE provisional cash-market data, crore rupees"})
    except Exception as e:  # noqa: BLE001
        notes.append(f"FII / DII data not available from NSE right now ({e})")

    t = track()
    out = {"market": market, "day": day, "built": now.strftime("%Y-%m-%d %H:%M"), "built_ts": time.time(),
           "score": sc, **call, "factors": fv, "rules": {"up": UP, "down": DOWN, "scale": SCALE},
           "groups": groups, "flows": flows_rows, "gift": {"available": False, "note": GIFT_NOTE},
           "today": today_future.result(), "track": t, "live": live_calls(series.get(NIFTY)), "notes": notes,
           "frozen": False,
           "after_open": day == now.date().isoformat() and (now.hour, now.minute) >= (9, 15)}
    # freeze the morning call: the last build before 09:15 on the NIFTY day itself is the one that counts
    if day == now.date().isoformat() and (8, 0) <= (now.hour, now.minute) < (9, 15) and sc is not None:
        store.put_company(f"PREMARKET::CALL::IN::{day}", {"day": day, "score": sc, "call": call["call"], "label": call["label"],
                                                          "built": out["built"], "factors": fv})
        out["frozen"] = True
    with _lock:
        _cache[market] = (time.time(), out)
    return out


# ------------------------------------------------------------------ background: build before the open, refresh the backtest weekly
_started = [False]


def _loop() -> None:
    last_build = 0.0
    while True:
        try:
            now = datetime.now(IST)
            t = track()
            if t is None or (time.time() - store.get_company("PREMARKET_TRACK::IN")[0] > 7 * 86400 and now.hour < 8):
                backtest()
            if now.weekday() < 5 and (8, 20) <= (now.hour, now.minute) < (9, 15) and time.time() - last_build > 540:
                build("IN", refresh=True)
                last_build = time.time()
        except Exception as e:  # noqa: BLE001 - keep the loop alive; it retries next minute
            log.warning("pre-market background job: %s", e)
        time.sleep(60)


def start_background() -> None:
    if config.DEMO or _started[0]:
        return
    _started[0] = True
    threading.Thread(target=_loop, name="premarket", daemon=True).start()
