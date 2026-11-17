"""Price chart + technical indicators.

Daily OHLCV comes from Yahoo Finance's public chart endpoint (no key, no login).
If that fails, it falls back to the research source's daily closing prices
(closes only, so candle-based indicators like ADX/Supertrend are skipped).

All indicators are computed here in plain Python, so they can be checked:
EMA 20/50/200, SMA, Bollinger Bands (20, 2), RSI (14, Wilder), MACD (12, 26, 9),
ATR (14), Supertrend (10, 3), ADX/+DI/-DI (14), relative volume, swing
support/resistance, and a plain-English technical summary.
"""
from __future__ import annotations

import datetime as dt
import math
import statistics
import time
from typing import Optional
from urllib.parse import quote

import requests

from . import config, money, parser, scraper, store

Num = Optional[float]
YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"}
CHART_TTL = 6 * 3600
LIVE_TTL = 5 * 60          # while the market is open, the last candle is still forming
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
CLOSE_SETTLED = dt.time(15, 50)   # NSE closes 15:30; give the data provider ~20 minutes to post the final candle


def _last_close_after(fetched_at: float, now: float, us: bool = False) -> bool:
    """True if a trading session finished after the cache was written (so a newer candle exists)."""
    f = dt.datetime.fromtimestamp(fetched_at, IST)
    n = dt.datetime.fromtimestamp(now, IST)
    # US sessions end around 01:30-02:30 IST the next morning; 03:00 IST covers both DST states
    settle = dt.time(3, 0) if us else CLOSE_SETTLED
    day = n.date()
    for _ in range(8):   # walk back to the most recent weekday settle time at or before now
        cand = dt.datetime.combine(day, settle, IST)
        trading_day = (day - dt.timedelta(days=1)) if us else day
        if cand <= n and trading_day.weekday() < 5:
            return f < cand
        day -= dt.timedelta(days=1)
    return False


def _market_open(now: float) -> bool:
    n = dt.datetime.fromtimestamp(now, IST)
    return n.weekday() < 5 and dt.time(9, 15) <= n.time() <= dt.time(15, 35)


CACHE_VERSION = 2   # bump when the way candles are fetched changes, so old saved charts are thrown away


def expected_last_session(now: float) -> str:
    """Date of the latest NSE session whose final candle should be out by now (weekday, after 15:50 IST)."""
    n = dt.datetime.fromtimestamp(now, IST)
    day = n.date() if n.time() >= CLOSE_SETTLED else n.date() - dt.timedelta(days=1)
    while day.weekday() >= 5:
        day -= dt.timedelta(days=1)
    return day.isoformat()


def is_stale(fetched_at: float, now: float, us: bool = False) -> bool:
    age = now - fetched_at
    max_age = CHART_TTL if us else 20 * 3600   # safety net; normally a session close is what triggers a refresh
    if age > max_age or _last_close_after(fetched_at, now, us):
        return True
    return (not us) and _market_open(now) and age > LIVE_TTL


# ------------------------------------------------------------------ data
def _yahoo(sym: str, rng: str = "10y", with_meta: bool = False):
    r = requests.get(YAHOO.format(sym=quote(sym)), params={"range": rng, "interval": "1d", "includePrePost": "false"},
                     headers=_UA, timeout=config.REQUEST_TIMEOUT)
    if r.status_code != 200:
        raise scraper.FetchError(f"Yahoo HTTP {r.status_code} for {sym}")
    res = (r.json().get("chart") or {}).get("result") or []
    if not res:
        raise scraper.FetchError(f"No chart data for {sym}")
    res = res[0]
    ts = res.get("timestamp") or []
    q = (res.get("indicators") or {}).get("quote", [{}])[0]
    out = []
    for i, t in enumerate(ts):
        o, h, l, c, v = (q.get(k, [None] * len(ts))[i] for k in ("open", "high", "low", "close", "volume"))
        if None in (o, h, l, c) or c <= 0:
            continue
        day = (dt.datetime.fromtimestamp(t, dt.timezone.utc) + dt.timedelta(hours=5, minutes=30)).date().isoformat()
        if out and out[-1]["t"] == day:
            out[-1] = {"t": day, "o": o, "h": h, "l": l, "c": c, "v": v or 0}
        else:
            out.append({"t": day, "o": o, "h": h, "l": l, "c": c, "v": v or 0})
    return (out, res.get("meta") or {}) if with_meta else out


def _latest_daily(sym: str) -> list[dict]:
    """Ten years of daily candles, topped up with the newest sessions.
    Yahoo's long-range series can lag a session or two behind; the short range and the quote
    'meta' carry the latest day, so they are merged in (newer data wins)."""
    bars = _yahoo(sym, "10y")
    try:
        recent, meta = _yahoo(sym, "5d", with_meta=True)
    except Exception:  # noqa: BLE001 - the long series is still usable on its own
        return bars
    by_day = {b["t"]: b for b in bars}
    for b in recent:
        by_day[b["t"]] = b
    return apply_meta([by_day[k] for k in sorted(by_day)], meta)


def apply_meta(out: list[dict], meta: dict) -> list[dict]:
    """Add the latest session from Yahoo's quote 'meta' when the candle list doesn't have it yet."""
    px, ts = meta.get("regularMarketPrice"), meta.get("regularMarketTime")
    if px and ts and px > 0:
        day = (dt.datetime.fromtimestamp(ts, dt.timezone.utc) + dt.timedelta(hours=5, minutes=30)).date().isoformat()
        if not out or day > out[-1]["t"]:
            hi = meta.get("regularMarketDayHigh") or px
            lo = meta.get("regularMarketDayLow") or px
            op = meta.get("regularMarketOpen") or (out[-1]["c"] if out else px)
            out = out + [{"t": day, "o": op, "h": max(hi, op, px), "l": min(lo, op, px), "c": px,
                          "v": meta.get("regularMarketVolume") or 0}]
    return out


def _close_only(company: dict, view: str) -> list[dict]:
    cid = company.get("company_id")
    if not cid:
        return []
    data = parser.parse_chart(scraper.fetch_chart(cid, "Price-Volume", 3650, view == "consolidated"))
    vol = dict(data.get("Volume") or [])
    return [{"t": d, "o": c, "h": c, "l": c, "c": c, "v": vol.get(d, 0)} for d, c in data.get("Price") or []]


def _demo(symbol: str) -> list[dict]:
    import random
    rnd = random.Random(symbol)
    day = dt.date.today() - dt.timedelta(days=3650)
    px, out = 300.0, []
    while day <= dt.date.today():
        if day.weekday() < 5:
            drift = 0.0006 + 0.012 * math.sin(len(out) / 90) / 10
            o = px * (1 + rnd.gauss(0, 0.004))
            c = o * (1 + drift + rnd.gauss(0, 0.014))
            h = max(o, c) * (1 + abs(rnd.gauss(0, 0.006)))
            l = min(o, c) * (1 - abs(rnd.gauss(0, 0.006)))
            out.append({"t": day.isoformat(), "o": o, "h": h, "l": l, "c": c, "v": int(abs(rnd.gauss(2e6, 6e5)))})
            px = c
        day += dt.timedelta(days=1)
    k = (180 if symbol.startswith("US:") else 1450) / out[-1]["c"]
    for b in out:
        for f in "ohlc":
            b[f] *= k
    return out


def _top_up(bars: list[dict], tries: list[str], comp, view: str) -> tuple[list[dict], str]:
    """Yahoo is missing the latest session(s): take them from the BSE listing or screener.in."""
    last = bars[-1]["t"]
    for t in tries[1:]:                    # e.g. the .BO listing
        try:
            newer = [b for b in _latest_daily(t) if b["t"] > last]
        except Exception:  # noqa: BLE001
            newer = []
        if newer:
            return bars + newer, f"latest from {t}"
    if comp:
        try:
            newer = [b for b in _close_only(comp[1]["company"], view) if b["t"] > last]
        except Exception:  # noqa: BLE001
            newer = []
        if newer:
            return bars + newer, "latest close from screener.in"
    return bars, ""


def get_bars(symbol: str, refresh: bool = False, with_time: bool = False):
    """-> (daily bars, source label, has_real_ohlc[, fetched_at])"""
    sym = scraper.clean_symbol(symbol)
    key = f"CHART::{sym}"
    cached = store.get_company(key)
    now = time.time()
    us = sym.startswith("US:")
    if cached and not refresh and cached[1].get("v") == CACHE_VERSION and not is_stale(cached[0], now, us):
        p = cached[1]
        behind = (not us) and p["bars"] and p["bars"][-1]["t"] < expected_last_session(now)
        if not (behind and now - cached[0] > 15 * 60):     # missing the latest session: retry every 15 min
            return (p["bars"], p["source"], p["ohlc"], cached[0]) if with_time else (p["bars"], p["source"], p["ohlc"])
    if config.DEMO:
        bars, src, ohlc = _demo(sym), "demo data", True
    elif sym.startswith("US:"):
        t = sym[3:]
        bars = _latest_daily(t)
        src, ohlc = f"Yahoo Finance ({t})", True
    else:
        comp = store.get_company(sym)
        nse = bse = None
        view = "consolidated"
        if comp:
            c = comp[1]["company"]
            nse, bse, view = c.get("nse_symbol"), c.get("bse_code"), comp[1].get("view", view)
        tries = [f"{nse or sym}.NS"] + ([f"{bse}.BO"] if bse else [])
        bars, src, ohlc, errs = [], "", True, []
        for t in tries:
            try:
                bars = _latest_daily(t)
                if len(bars) > 30:
                    src = f"Yahoo Finance ({t})"
                    break
            except Exception as e:  # noqa: BLE001
                errs.append(str(e))
        if len(bars) <= 30 and comp:
            bars = _close_only(comp[1]["company"], view)
            src, ohlc = "daily closes (screener.in)", False
        if not bars:
            raise scraper.FetchError("Price history unavailable: " + "; ".join(errs))
        want = expected_last_session(now)
        if ohlc and bars[-1]["t"] < want:
            bars, extra = _top_up(bars, tries, comp, view)
            if extra:
                src += f" + {extra}"
    store.put_company(key, {"v": CACHE_VERSION, "bars": bars, "source": src, "ohlc": ohlc})
    return (bars, src, ohlc, time.time()) if with_time else (bars, src, ohlc)


def to_weekly(bars: list[dict]) -> list[dict]:
    out = []
    for b in bars:
        d = dt.date.fromisoformat(b["t"])
        wk = (d - dt.timedelta(days=d.weekday())).isoformat()
        if out and out[-1]["wk"] == wk:
            w = out[-1]
            w["h"], w["l"], w["c"], w["v"] = max(w["h"], b["h"]), min(w["l"], b["l"]), b["c"], w["v"] + b["v"]
            w["t"] = b["t"]
        else:
            out.append({**b, "wk": wk})
    for w in out:
        w.pop("wk", None)
    return out


# ------------------------------------------------------------------ indicators
def sma(x: list[float], n: int) -> list[Num]:
    out, s = [], 0.0
    for i, v in enumerate(x):
        s += v
        if i >= n:
            s -= x[i - n]
        out.append(s / n if i >= n - 1 else None)
    return out


def ema(x: list[float], n: int) -> list[Num]:
    out: list[Num] = [None] * len(x)
    if len(x) < n:
        return out
    k = 2 / (n + 1)
    e = sum(x[:n]) / n
    out[n - 1] = e
    for i in range(n, len(x)):
        e = x[i] * k + e * (1 - k)
        out[i] = e
    return out


def wilder(x: list[float], n: int) -> list[Num]:
    out: list[Num] = [None] * len(x)
    if len(x) < n:
        return out
    a = sum(x[:n]) / n
    out[n - 1] = a
    for i in range(n, len(x)):
        a = (a * (n - 1) + x[i]) / n
        out[i] = a
    return out


def rsi(c: list[float], n: int = 14) -> list[Num]:
    if len(c) <= n:
        return [None] * len(c)
    gains = [0.0] + [max(c[i] - c[i - 1], 0) for i in range(1, len(c))]
    losses = [0.0] + [max(c[i - 1] - c[i], 0) for i in range(1, len(c))]
    ag, al = wilder(gains[1:], n), wilder(losses[1:], n)
    out: list[Num] = [None]
    for g, l in zip(ag, al):
        out.append(None if g is None else (100.0 if l == 0 else 100 - 100 / (1 + g / l)))
    return out


def macd(c: list[float], f: int = 12, s: int = 26, sig: int = 9):
    ef, es = ema(c, f), ema(c, s)
    line = [a - b if a is not None and b is not None else None for a, b in zip(ef, es)]
    start = next((i for i, v in enumerate(line) if v is not None), len(line))
    sig_part = ema([v for v in line[start:]], sig)
    signal = [None] * start + sig_part
    hist = [a - b if a is not None and b is not None else None for a, b in zip(line, signal)]
    return line, signal, hist


def bollinger(c: list[float], n: int = 20, k: float = 2.0):
    mid = sma(c, n)
    up, lo = [], []
    for i, m in enumerate(mid):
        if m is None:
            up.append(None); lo.append(None)
            continue
        w = c[i - n + 1:i + 1]
        sd = math.sqrt(sum((v - m) ** 2 for v in w) / n)
        up.append(m + k * sd); lo.append(m - k * sd)
    return up, mid, lo


def true_range(h, l, c) -> list[float]:
    return [h[0] - l[0]] + [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])) for i in range(1, len(c))]


def supertrend(h, l, c, n: int = 10, mult: float = 3.0):
    atr = wilder(true_range(h, l, c), n)
    st: list[Num] = [None] * len(c)
    trend = [0] * len(c)
    fu = fl = None
    for i in range(len(c)):
        if atr[i] is None:
            continue
        hl2 = (h[i] + l[i]) / 2
        bu, bl = hl2 + mult * atr[i], hl2 - mult * atr[i]
        if fu is None:
            fu, fl, trend[i] = bu, bl, 1
        else:
            fu = bu if (bu < fu or c[i - 1] > fu) else fu
            fl = bl if (bl > fl or c[i - 1] < fl) else fl
            prev = trend[i - 1] or 1
            trend[i] = 1 if (prev == -1 and c[i] > fu) else -1 if (prev == 1 and c[i] < fl) else prev
        st[i] = fl if trend[i] == 1 else fu
    return st, trend, atr


def adx(h, l, c, n: int = 14):
    up = [0.0] + [h[i] - h[i - 1] for i in range(1, len(h))]
    dn = [0.0] + [l[i - 1] - l[i] for i in range(1, len(l))]
    pdm = [u if u > d and u > 0 else 0.0 for u, d in zip(up, dn)]
    mdm = [d if d > u and d > 0 else 0.0 for u, d in zip(up, dn)]
    tr = true_range(h, l, c)
    atr, sp, sm = wilder(tr[1:], n), wilder(pdm[1:], n), wilder(mdm[1:], n)
    pdi, mdi, dx = [None], [None], []
    for a, p, m in zip(atr, sp, sm):
        if a is None or a == 0:
            pdi.append(None); mdi.append(None); dx.append(None)
            continue
        P, M = 100 * p / a, 100 * m / a
        pdi.append(P); mdi.append(M)
        dx.append(100 * abs(P - M) / (P + M) if P + M else 0)
    start = next((i for i, v in enumerate(dx) if v is not None), len(dx))
    adx_part = wilder([v for v in dx[start:]], n)
    return [None] * (start + 1) + adx_part, pdi, mdi


def swing_levels(h, l, c, lookback: int = 250, k: int = 5) -> dict:
    n = len(c)
    hi, lo = [], []
    for i in range(max(k, n - lookback), n - k):
        if h[i] == max(h[i - k:i + k + 1]):
            hi.append(h[i])
        if l[i] == min(l[i - k:i + k + 1]):
            lo.append(l[i])
    px = c[-1]
    res = sorted([v for v in hi if v > px * 1.005])[:3]
    sup = sorted([v for v in lo if v < px * 0.995], reverse=True)[:3]
    return {"resistance": [round(v, 2) for v in res], "support": [round(v, 2) for v in sup]}


# ------------------------------------------------------------------ summary
def summarise(c, e20, e50, e200, rs, mline, msig, mhist, st_trend, ax, pdi, mdi, bb_up, bb_lo, v, ohlc: bool) -> dict:
    i = len(c) - 1
    px = c[i]
    checks = []

    def add(name, state, detail):  # state: 1 bullish, 0 neutral, -1 bearish
        checks.append({"name": name, "state": state, "detail": detail})

    if e200[i]:
        add("Long-term trend (200 EMA)", 1 if px > e200[i] else -1, f"Price {'above' if px > e200[i] else 'below'} 200 EMA ({e200[i]:,.0f})")
    if e50[i] and e200[i]:
        cross = None
        for j in range(i, max(i - 60, 1), -1):
            if e50[j] and e200[j] and e50[j - 1] and e200[j - 1]:
                if (e50[j] > e200[j]) != (e50[j - 1] > e200[j - 1]):
                    cross = j
                    break
        golden = e50[i] > e200[i]
        extra = f" — {'golden' if golden else 'death'} cross {i - cross} sessions ago" if cross else ""
        add("50 vs 200 EMA", 1 if golden else -1, f"50 EMA {'above' if golden else 'below'} 200 EMA{extra}")
    if e20[i]:
        add("Short-term trend (20 EMA)", 1 if px > e20[i] else -1, f"Price {'above' if px > e20[i] else 'below'} 20 EMA ({e20[i]:,.0f})")
    if rs[i] is not None:
        r = rs[i]
        if r >= 70:
            add("RSI (14)", 0, f"{r:.0f} — overbought, pullbacks common")
        elif r >= 55:
            add("RSI (14)", 1, f"{r:.0f} — bullish momentum")
        elif r > 45:
            add("RSI (14)", 0, f"{r:.0f} — neutral")
        elif r > 30:
            add("RSI (14)", -1, f"{r:.0f} — weak momentum")
        else:
            add("RSI (14)", 0, f"{r:.0f} — oversold, bounce possible")
    if mline[i] is not None and msig[i] is not None:
        rising = mhist[i] is not None and mhist[i - 1] is not None and mhist[i] > mhist[i - 1]
        above = mline[i] > msig[i]
        add("MACD (12,26,9)", 1 if above else -1,
            f"MACD {'above' if above else 'below'} signal, histogram {'rising' if rising else 'falling'}")
    if ohlc and ax[i] is not None and pdi[i] is not None:
        strong = ax[i] >= 25
        up = pdi[i] > mdi[i]
        add("ADX (14) trend strength", (1 if up else -1) if strong else 0,
            f"ADX {ax[i]:.0f} ({'strong' if strong else 'weak'} trend), {'buyers' if up else 'sellers'} in control (+DI {pdi[i]:.0f} / −DI {mdi[i]:.0f})")
    if ohlc and st_trend[i]:
        add("Supertrend (10,3)", st_trend[i], "Buy mode" if st_trend[i] == 1 else "Sell mode")
    if bb_up[i] and bb_lo[i]:
        pos = (px - bb_lo[i]) / (bb_up[i] - bb_lo[i]) if bb_up[i] > bb_lo[i] else 0.5
        add("Bollinger position", 0, f"Price at {pos*100:.0f}% of the band ({'near upper' if pos > 0.85 else 'near lower' if pos < 0.15 else 'middle'})")
    if len(v) > 21 and sum(v[-21:-1]) > 0:
        rv = v[i] / (sum(v[-21:-1]) / 20)
        add("Volume vs 20-day avg", 0, f"{rv:.1f}x average volume")

    bull = sum(1 for x in checks if x["state"] == 1)
    bear = sum(1 for x in checks if x["state"] == -1)
    score = bull - bear
    label = ("Strong uptrend" if score >= 4 else "Uptrend" if score >= 2 else "Sideways" if score > -2
             else "Downtrend" if score > -4 else "Strong downtrend")
    tone = {"Strong uptrend": "good", "Uptrend": "ok", "Sideways": "warn", "Downtrend": "bad", "Strong downtrend": "bad"}[label]
    return {"label": label, "tone": tone, "bullish": bull, "bearish": bear, "checks": checks}


# ------------------------------------------------------------------ outlook
def _pct(vals: list[float], q: float) -> Optional[float]:
    if not vals:
        return None
    v = sorted(vals)
    k = (len(v) - 1) * q
    f = math.floor(k)
    c = min(f + 1, len(v) - 1)
    return v[f] + (v[c] - v[f]) * (k - f)


def _future_dates(last: str, n: int, weekly: bool) -> list[str]:
    d = dt.date.fromisoformat(last)
    out = []
    while len(out) < n:
        d += dt.timedelta(days=7 if weekly else 1)
        if weekly or d.weekday() < 5:
            out.append(d.isoformat())
    return out


def outlook(t, h, l, c, e50, e200, rs, ml, ms, levels, interval: str) -> dict:
    """What the chart's own history says about the next months. Not a prediction:
    a volatility range plus how this stock behaved after the same setup before."""
    weekly = interval == "1wk"
    C = money.sym()
    n = len(c)
    i = n - 1
    yr = 52 if weekly else 252
    hz = [("1 month", 4), ("3 months", 13), ("6 months", 26)] if weekly else [("1 month", 21), ("3 months", 63), ("6 months", 126)]

    # -- volatility cone (no direction assumed)
    rets = [math.log(c[k] / c[k - 1]) for k in range(max(1, n - yr), n) if c[k - 1] > 0 and c[k] > 0]
    sd = statistics.pstdev(rets) if len(rets) > 20 else None
    cone, cone_pts = [], []
    if sd:
        z80, z68 = 1.2816, 1.0
        for label, k in hz:
            s_ = sd * math.sqrt(k)
            cone.append({"horizon": label, "low80": round(c[i] * math.exp(-z80 * s_), 2), "high80": round(c[i] * math.exp(z80 * s_), 2),
                         "low68": round(c[i] * math.exp(-z68 * s_), 2), "high68": round(c[i] * math.exp(z68 * s_), 2),
                         "move68_pct": round((math.exp(s_) - 1) * 100, 1)})
        steps = hz[-1][1]
        for k, d in enumerate(_future_dates(t[i], steps, weekly), start=1):
            s_ = sd * math.sqrt(k)
            cone_pts.append({"t": d, "hi": round(c[i] * math.exp(z80 * s_), 2), "lo": round(c[i] * math.exp(-z80 * s_), 2)})

    # -- historical analogs: same trend/momentum setup as today
    def state(k):
        if e200[k] is None or e50[k] is None or rs[k] is None or ml[k] is None or ms[k] is None:
            return None
        r = rs[k]
        return (c[k] > e200[k], e50[k] > e200[k], 0 if r < 40 else 1 if r <= 60 else 2, ml[k] > ms[k])

    now = state(i)
    names = ["price vs 200 EMA", "50 vs 200 EMA", "RSI zone", "MACD vs signal"]
    analogs, used_keys = None, None
    if now:
        for keys in ((0, 1, 2, 3), (0, 1, 2), (0, 1)):
            res = []
            for label, k in hz:
                fw, base = [], []
                for j in range(n - k):
                    sj = state(j)
                    if sj is None:
                        continue
                    r = (c[j + k] / c[j] - 1) * 100
                    base.append(r)
                    if all(sj[q] == now[q] for q in keys):
                        fw.append(r)
                res.append((label, fw, base))
            if min(len(fw) for _, fw, _ in res) >= 20:
                used_keys = keys
                analogs = [{
                    "horizon": label, "count": len(fw), "median": round(_pct(fw, .5), 1), "p10": round(_pct(fw, .1), 1),
                    "p90": round(_pct(fw, .9), 1), "pct_up": round(sum(1 for x in fw if x > 0) / len(fw) * 100),
                    "all_median": round(_pct(base, .5), 1), "all_pct_up": round(sum(1 for x in base if x > 0) / len(base) * 100),
                } for label, fw, base in res]
                break
    zone = {0: "below 40", 1: "40-60", 2: "above 60"}
    setup = None
    if now:
        setup = [f"Price {'above' if now[0] else 'below'} 200 EMA", f"50 EMA {'above' if now[1] else 'below'} 200 EMA",
                 f"RSI {zone[now[2]]}", f"MACD {'above' if now[3] else 'below'} signal"]

    # -- if / then levels
    px = c[i]
    res_ = levels.get("resistance") or []
    sup = levels.get("support") or []
    hi52, lo52 = max(h[-yr:]), min(l[-yr:])
    r1 = res_[0] if res_ else round(hi52, 2)
    r2 = res_[1] if len(res_) > 1 else round(hi52, 2)
    s1 = sup[0] if sup else round(lo52, 2)
    s2 = sup[1] if len(sup) > 1 else round(lo52, 2)
    scenarios = [
        {"kind": "bull", "title": f"Bullish if it closes above {C}{r1:,.0f}",
         "text": f"That clears the nearest resistance ({(r1/px-1)*100:+.1f}%). Next zone {C}{max(r2, r1):,.0f}"
                 + (f", then the 52-week high {C}{hi52:,.0f}." if hi52 > max(r1, r2) * 1.01 else ".")
                 + (" A move back above the 200 EMA would also turn the long-term trend up." if e200[i] and px < e200[i] else "")},
        {"kind": "range", "title": f"Sideways between {C}{s1:,.0f} and {C}{r1:,.0f}",
         "text": "While price stays inside this band, the chart is undecided. Wait for a close outside it."},
        {"kind": "bear", "title": f"Bearish if it closes below {C}{s1:,.0f}",
         "text": f"That breaks the nearest support ({(s1/px-1)*100:+.1f}%). Next support {C}{min(s2, s1):,.0f}"
                 + (f", then the 52-week low {C}{lo52:,.0f}." if lo52 < min(s1, s2) * 0.99 else ".")},
    ]

    # -- chart story
    look = min(yr, i)
    chg = (px / c[i - look] - 1) * 100 if look else 0
    story = [f"Over the last {'year' if look >= yr else f'{look} bars'} the price {'rose' if chg >= 0 else 'fell'} {abs(chg):.1f}%."]
    story.append(f"It is {abs(px/hi52-1)*100:.1f}% below its 52-week high ({C}{hi52:,.0f}) and {abs(px/lo52-1)*100:.1f}% above its 52-week low ({C}{lo52:,.0f}).")
    if e50[i] and e200[i]:
        pos = ("above both" if px > e50[i] and px > e200[i] else "below both" if px < e50[i] and px < e200[i] else
               "between")
        u = "week" if weekly else "day"
        story.append(f"Price is {pos} its 50-{u} ({C}{e50[i]:,.0f}) and 200-{u} ({C}{e200[i]:,.0f}) averages"
                     + (" — sellers have had the upper hand." if pos == "below both" else " — buyers are in control." if pos == "above both" else " — the trend is mixed."))
    if rs[i] is not None:
        story.append(f"RSI is {rs[i]:.0f}: " + ("stretched, short-term pullbacks are common." if rs[i] >= 70 else
                     "oversold, bounces often start here but need confirmation." if rs[i] <= 30 else
                     "momentum is positive." if rs[i] >= 55 else "momentum is weak." if rs[i] <= 45 else "momentum is neutral."))
    if analogs:
        a3 = analogs[1]
        story.append(f"In the past, after a setup like today's, the stock was higher 3 months later {a3['pct_up']}% of the time "
                     f"(median {a3['median']:+.1f}%), versus {a3['all_pct_up']}% on an average day.")
    if cone:
        story.append(f"Based on its own volatility, a typical 3-month move is about ±{cone[1]['move68_pct']}% "
                     f"({C}{cone[1]['low68']:,.0f} – {C}{cone[1]['high68']:,.0f}).")

    return {"story": story, "scenarios": scenarios, "cone": cone, "cone_points": cone_pts,
            "analogs": analogs, "setup": setup, "setup_used": [names[k] for k in (used_keys or ())],
            "volatility_annual": round(sd * math.sqrt(52 if weekly else 252) * 100, 1) if sd else None}


# ------------------------------------------------------------------ entry
def r2(x):
    return None if x is None else round(x, 2)


def build(symbol: str, interval: str = "1d", refresh: bool = False) -> dict:
    money.set_market(money.market_of(scraper.clean_symbol(symbol)))
    bars, src, ohlc, fetched = get_bars(symbol, refresh, with_time=True)
    if interval == "1wk":
        bars = to_weekly(bars)
    t = [b["t"] for b in bars]
    o, h, l, c, v = ([b[k] for b in bars] for k in "ohlcv")
    e20, e50, e200 = ema(c, 20), ema(c, 50), ema(c, 200)
    bb_up, bb_mid, bb_lo = bollinger(c)
    rs = rsi(c)
    ml, ms, mh = macd(c)
    if ohlc:
        st, st_tr, atr = supertrend(h, l, c)
        ax, pdi, mdi = adx(h, l, c)
    else:
        st, st_tr, atr = [None] * len(c), [0] * len(c), [None] * len(c)
        ax = pdi = mdi = [None] * len(c)

    markers = []
    for i in range(1, len(c)):
        if e50[i] and e200[i] and e50[i - 1] and e200[i - 1] and (e50[i] > e200[i]) != (e50[i - 1] > e200[i - 1]):
            gold = e50[i] > e200[i]
            markers.append({"t": t[i], "kind": "golden" if gold else "death", "text": "Golden cross" if gold else "Death cross"})
    yr = c[-252:] if interval == "1d" else c[-52:]
    hi52, lo52 = (max(h[-252:]), min(l[-252:])) if interval == "1d" else (max(h[-52:]), min(l[-52:]))
    i = len(c) - 1
    stats = {
        "last": r2(c[i]), "date": t[i], "change_1d": r2((c[i] / c[i - 1] - 1) * 100) if i else None,
        "high_52w": r2(hi52), "low_52w": r2(lo52), "atr": r2(atr[i]), "atr_pct": r2(atr[i] / c[i] * 100) if atr[i] else None,
        "ret_1m": r2((c[i] / c[max(i - 21, 0)] - 1) * 100) if interval == "1d" else None,
        "ret_6m": r2((c[i] / c[max(i - 126, 0)] - 1) * 100) if interval == "1d" else None,
        "ret_1y": r2((c[i] / yr[0] - 1) * 100) if yr else None,
    }
    lv = swing_levels(h, l, c) if len(c) > 20 else {"support": [], "resistance": []}
    look = outlook(t, h, l, c, e50, e200, rs, ml, ms, lv, interval) if len(c) > 260 or (interval == "1wk" and len(c) > 60) else None
    # indicators were computed on the full history; send the last ~5 years of daily bars
    keep = 1300 if interval == "1d" else len(c)
    cut = max(len(c) - keep, 0)
    out = {
        "symbol": scraper.clean_symbol(symbol), "interval": interval, "source": src, "ohlc": ohlc,
        "fetched_at": dt.datetime.fromtimestamp(fetched, IST).isoformat(timespec="minutes"),
        "expected_last": None if scraper.clean_symbol(symbol).startswith("US:") else expected_last_session(time.time()),
        "t": t, "o": [r2(x) for x in o], "h": [r2(x) for x in h], "l": [r2(x) for x in l], "c": [r2(x) for x in c], "v": v,
        "ema20": [r2(x) for x in e20], "ema50": [r2(x) for x in e50], "ema200": [r2(x) for x in e200],
        "bb_up": [r2(x) for x in bb_up], "bb_lo": [r2(x) for x in bb_lo],
        "rsi": [r2(x) for x in rs], "macd": [r2(x) for x in ml], "macd_signal": [r2(x) for x in ms], "macd_hist": [r2(x) for x in mh],
        "st": [r2(x) for x in st], "st_trend": st_tr, "adx": [r2(x) for x in ax], "pdi": [r2(x) for x in pdi], "mdi": [r2(x) for x in mdi],
        "markers": markers[-12:], "levels": lv, "outlook": look,
        "stats": stats,
        "summary": summarise(c, e20, e50, e200, rs, ml, ms, mh, st_tr, ax, pdi, mdi, bb_up, bb_lo, v, ohlc),
    }
    for k in ("t", "o", "h", "l", "c", "v", "ema20", "ema50", "ema200", "bb_up", "bb_lo", "rsi", "macd", "macd_signal",
              "macd_hist", "st", "st_trend", "adx", "pdi", "mdi"):
        out[k] = out[k][cut:]
    out["markers"] = [mk for mk in out["markers"] if not out["t"] or mk["t"] >= out["t"][0]]
    return out
