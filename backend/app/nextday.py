"""Next-day view v2 for NIFTY. Rules written down on 20 Nov 2026, BEFORE any of this was tested:

A. The 08:45 call = the overnight call's four factors (premarket.FACTORS) plus what happened after the US close:
     S&P 500 futures from the US cash close to 08:45 IST  x3
     Asia at 08:45 IST (average of Nikkei 225 and Kospi, each since its previous close)  x2
   Each move is divided by that market's own past-year daily volatility and capped at ±3.
   Score = 100 x (weighted sum) / 11, capped ±100; ≥ +20 gap-up likely, ≤ −20 gap-down likely.
   Yahoo keeps hourly prices for about two years only, so it is tested on that window. It REPLACES the overnight
   call only if it beats both the overnight call and always-guessing by at least 5 points, in both halves of the
   window (before / from 1 Jan 2026). Otherwise it is shown as "not proven".
B. Day map (no forecast of direction): expected range from India VIX (last close / √252, around the previous close),
   previous-day levels with pivot / CPR, and how NIFTY behaved after each size of opening gap since 2016.
   Gap buckets fixed: ≤−0.7%, −0.7…−0.3, −0.3…−0.1, −0.1…+0.1, +0.1…+0.3, +0.3…+0.7, ≥+0.7%.
C. Evening preview: the overnight formula on live values while the US is still trading. Preliminary, not tested.
"""
from __future__ import annotations

import math
import random
import statistics
import time
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from urllib.parse import quote

import requests

from . import config, premarket as pm, store

W_FUT, W_ASIA = 3, 2
SCALE2 = pm.SCALE + W_FUT + W_ASIA          # 11
CUTOFF_UTC = (3, 15)                        # 08:45 IST
SPLIT2 = "2026-01-01"
ASIA = [("^N225", "Nikkei 225"), ("^KS11", "Kospi")]
FUT, SPX = "ES=F", "^GSPC"
PASS_RULE2 = ("Replaces the overnight call only if it is right at least 5 points more often than BOTH the overnight call "
              "and always guessing the common direction, in both halves of the test window. Fixed before testing.")
BUCKETS = [(-99, -0.7, "Gap-down of 0.7% or more"), (-0.7, -0.3, "Gap-down 0.3% to 0.7%"), (-0.3, -0.1, "Gap-down 0.1% to 0.3%"),
           (-0.1, 0.1, "Flat open (within ±0.1%)"), (0.1, 0.3, "Gap-up 0.1% to 0.3%"), (0.3, 0.7, "Gap-up 0.3% to 0.7%"),
           (0.7, 99, "Gap-up of 0.7% or more")]


# ------------------------------------------------------------------ hourly prices (about two years on Yahoo)
def _demo_hourly(sym: str) -> list[dict]:
    rnd = random.Random("h" + sym)
    start = datetime(2024, 11, 18, tzinfo=timezone.utc)
    out, px = [], 100.0
    t = start
    end = datetime.now(timezone.utc)
    hours = {SPX: [14.5 + i for i in range(7)], FUT: [h for h in range(24) if h != 21]}.get(sym, list(range(6)))  # real trading hours (UTC)
    while t < end:
        if t.weekday() < 5:
            for h in hours:
                px *= 1 + rnd.gauss(0, 0.002)
                out.append({"ts": int((t + timedelta(hours=h)).timestamp()), "c": px})
        t += timedelta(days=1)
    return out


def hourly(sym: str, max_age: float = 1200) -> list[dict]:
    if config.DEMO:
        return _demo_hourly(sym)
    key = f"PM::HOURLY::{sym}"
    hit = store.get_company(key)
    if hit and time.time() - hit[0] < max_age:
        return hit[1]["bars"]
    r = requests.get(pm.YAHOO.format(sym=quote(sym)), params={"range": "730d", "interval": "1h", "includePrePost": "false"},
                     headers=pm._UA, timeout=config.REQUEST_TIMEOUT)
    if r.status_code != 200:
        raise ValueError(f"Yahoo answered {r.status_code} for {sym} (hourly)")
    res = ((r.json().get("chart") or {}).get("result") or [None])[0] or {}
    closes = (((res.get("indicators") or {}).get("quote") or [{}])[0]).get("close") or []
    bars = [{"ts": int(t), "c": c} for t, c in zip(res.get("timestamp") or [], closes) if c]
    store.put_company(key, {"bars": bars})
    return bars


def _last_before(bars: list[dict], ts: float, done: bool = True) -> Optional[dict]:
    """Last hourly bar that had FINISHED before ts (done) or had started before ts."""
    lo, hi = 0, len(bars)
    lim = ts - (3600 if done else 0)
    while lo < hi:
        mid = (lo + hi) // 2
        if bars[mid]["ts"] <= lim if done else bars[mid]["ts"] < lim:
            lo = mid + 1
        else:
            hi = mid
    return bars[lo - 1] if lo else None


def daily_vol(bars: list[dict], before: str, n: int = pm.VOL_DAYS) -> Optional[float]:
    k = sum(1 for b in bars if b["t"] < before)
    if k < n + 1:
        return None
    closes = [b["c"] for b in bars[k - n - 1:k]]
    rets = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))]
    return statistics.pstdev(rets) or None


def _z(ret: Optional[float], vol: Optional[float]) -> Optional[float]:
    if ret is None or not vol:
        return None
    return max(-pm.CLIP_Z, min(pm.CLIP_Z, ret / vol))


def cutoff_ts(day: str) -> float:
    d = date.fromisoformat(day)
    return datetime(d.year, d.month, d.day, *CUTOFF_UTC, tzinfo=timezone.utc).timestamp()


def after_close_factors(hourly_series: dict, daily_series: dict, day: str, until: Optional[float] = None) -> list[dict]:
    """S&P 500 futures since the US cash close, and Asia since its previous close, as of 08:45 IST (or `until`)."""
    cut = min(cutoff_ts(day), until or cutoff_ts(day))
    out = []
    # futures since the US cash close
    ret = z = None
    spx, fut = hourly_series.get(SPX) or [], hourly_series.get(FUT) or []
    last_cash = _last_before(spx, cut, done=False)
    if last_cash and cut - last_cash["ts"] < 4 * 86400:
        us_close = last_cash["ts"] + 1800                        # the session's last (half-hour) bar ends at the close
        at_close, now = _last_before(fut, us_close), _last_before(fut, cut)   # the futures bar that ended at the close
        if at_close and now and now["ts"] > at_close["ts"]:
            ret = now["c"] / at_close["c"] - 1
            z = _z(ret, daily_vol(daily_series.get(FUT) or [], day))
    out.append({"name": "S&P 500 futures since the US close", "w": W_FUT, "ret": None if ret is None else round(ret * 100, 2),
                "z": None if z is None else round(z, 2), "contrib": round(W_FUT * z, 2) if z is not None else 0.0,
                "why": "How the US has traded overnight, after its close at 02:30 IST"})
    # Asia at 08:45
    d0 = datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp()
    zs, rets, used = [], [], []
    for sym, name in ASIA:
        bars = hourly_series.get(sym) or []
        prev, now = _last_before(bars, d0, done=False), _last_before(bars, cut)
        if prev and now and now["ts"] >= d0 and d0 - prev["ts"] < 5 * 86400:
            r_ = now["c"] / prev["c"] - 1
            zz = _z(r_, daily_vol(daily_series.get(sym) or [], day))
            if zz is not None:
                zs.append(zz)
                rets.append(r_)
                used.append(name)
    z = statistics.mean(zs) if zs else None
    out.append({"name": "Asia at 08:45 IST (" + (", ".join(used) or "Nikkei, Kospi") + ")", "w": W_ASIA,
                "ret": round(statistics.mean(rets) * 100, 2) if rets else None, "z": None if z is None else round(z, 2),
                "contrib": round(W_ASIA * z, 2) if z is not None else 0.0, "why": "Japan and Korea open at 05:30 IST"})
    return out


def score2_of(overnight: list[dict], after: list[dict]) -> Optional[float]:
    if any(f["z"] is None for f in overnight + after):
        return None
    return round(max(-100.0, min(100.0, 100 * sum(f["contrib"] for f in overnight + after) / SCALE2)), 1)


# ------------------------------------------------------------------ backtest of the 08:45 call
def backtest2(hourly_series: Optional[dict] = None, daily_series: Optional[dict] = None, save: bool = True) -> dict:
    if daily_series is None:
        syms = [f["sym"] for f in pm.FACTORS] + [pm.NIFTY, FUT] + [s for s, _ in ASIA]
        daily_series = {s: pm.daily(s, max_age=6 * 3600) for s in syms}
    if hourly_series is None:
        hourly_series = {s: hourly(s, max_age=6 * 3600) for s in [SPX, FUT] + [s for s, _ in ASIA]}
    nifty = daily_series[pm.NIFTY]
    h0 = min((b[0]["ts"] for b in hourly_series.values() if b), default=None)
    start = datetime.fromtimestamp(h0 + 7 * 86400, timezone.utc).date().isoformat() if h0 else "9999"
    rows = []
    for i in range(1, len(nifty)):
        b, p = nifty[i], nifty[i - 1]
        if b["t"] < start or not b.get("o") or abs(b["o"] - p["c"]) < 1e-9:
            continue
        on = pm.factor_values(daily_series, b["t"])
        s1 = pm.score_of(on)
        s2 = score2_of(on, after_close_factors(hourly_series, daily_series, b["t"]))
        if s1 is None or s2 is None:
            continue
        gap, move = b["o"] / p["c"] - 1, b["c"] / b["o"] - 1
        rows.append({"t": b["t"], "v1": {"call": pm.call_of(s1)["call"], "gap": gap, "day": move},
                     "v2": {"call": pm.call_of(s2)["call"], "gap": gap, "day": move}})
    halves = {"first_half": [r for r in rows if r["t"] < SPLIT2], "second_half": [r for r in rows if r["t"] >= SPLIT2]}
    res = {k: {"v1": pm.summarize([dict(r["v1"], t=r["t"]) for r in rs]), "v2": pm.summarize([dict(r["v2"], t=r["t"]) for r in rs])}
           for k, rs in [("all", rows)] + list(halves.items())}
    passed = None
    if all(res[h]["v2"]["gap_hit"] is not None and res[h]["v1"]["gap_hit"] is not None for h in halves):
        passed = all(res[h]["v2"]["gap_hit"] - res[h]["v1"]["gap_hit"] >= 5 and res[h]["v2"]["gap_hit"] - res[h]["v2"]["gap_naive"] >= 5
                     for h in halves)
    out = {"built": datetime.now(pm.IST).strftime("%Y-%m-%d %H:%M"), "from": rows[0]["t"] if rows else None,
           "to": rows[-1]["t"] if rows else None, "days": len(rows), **res, "passed": passed, "split": SPLIT2,
           "pass_rule": PASS_RULE2, "weights": {"futures_since_close": W_FUT, "asia_0845": W_ASIA, "scale": SCALE2}}
    if save:
        store.put_company("PREMARKET_TRACK2::IN", out)
    return out


def track2() -> Optional[dict]:
    hit = store.get_company("PREMARKET_TRACK2::IN")
    return hit[1] if hit else None


# ------------------------------------------------------------------ B. day map
def bucket_of(gap_pct: float) -> int:
    for i, (lo, hi, _) in enumerate(BUCKETS):
        if lo <= gap_pct < hi:
            return i
    return len(BUCKETS) - 1


def gap_table(nifty: list[dict]) -> list[dict]:
    """How NIFTY behaved after each size of opening gap, every day since the series starts."""
    acc = [{"n": 0, "filled": 0, "up_close": 0, "moves": []} for _ in BUCKETS]
    for i in range(1, len(nifty)):
        b, p = nifty[i], nifty[i - 1]
        if not b.get("o") or not b.get("h") or not b.get("l") or abs(b["o"] - p["c"]) < 1e-9:
            continue
        g = (b["o"] / p["c"] - 1) * 100
        a = acc[bucket_of(g)]
        a["n"] += 1
        a["filled"] += (g > 0 and b["l"] <= p["c"]) or (g < 0 and b["h"] >= p["c"])
        a["up_close"] += b["c"] > b["o"]
        a["moves"].append((b["c"] / b["o"] - 1) * 100)
    out = []
    for (lo, hi, label), a in zip(BUCKETS, acc):
        n = a["n"]
        out.append({"label": label, "lo": lo, "hi": hi, "days": n,
                    "gap_filled_pct": round(a["filled"] / n * 100, 1) if n and (lo >= 0.1 or hi <= -0.1) else None,
                    "closed_above_open_pct": round(a["up_close"] / n * 100, 1) if n else None,
                    "avg_open_to_close_pct": round(statistics.mean(a["moves"]), 2) if n else None})
    return out


def range_check(nifty: list[dict], vix: list[dict]) -> dict:
    """How often NIFTY stayed inside the India-VIX expected range (previous close ± VIX/√252)."""
    vx = {b["t"]: b["c"] for b in vix}
    vdays = sorted(vx)
    inside = close_inside = n = 0
    j = 0
    for i in range(1, len(nifty)):
        b, p = nifty[i], nifty[i - 1]
        while j < len(vdays) and vdays[j] < b["t"]:
            j += 1
        if j == 0 or not b.get("h") or not b.get("l"):
            continue
        m = vx[vdays[j - 1]] / 100 / math.sqrt(252)
        lo, hi = p["c"] * (1 - m), p["c"] * (1 + m)
        n += 1
        inside += lo <= b["l"] and b["h"] <= hi
        close_inside += lo <= b["c"] <= hi
    return {"days": n, "stayed_inside_pct": round(inside / n * 100, 1) if n else None,
            "closed_inside_pct": round(close_inside / n * 100, 1) if n else None}


def levels(prev: dict) -> dict:
    h, l, c = prev["h"], prev["l"], prev["c"]
    p = (h + l + c) / 3
    bc = (h + l) / 2
    tc = 2 * p - bc
    r = lambda x: round(x, 1)
    return {"prev_high": r(h), "prev_low": r(l), "prev_close": r(c), "pivot": r(p), "cpr_top": r(max(tc, bc)), "cpr_bottom": r(min(tc, bc)),
            "cpr_width_pct": round(abs(tc - bc) / p * 100, 2), "r1": r(2 * p - l), "s1": r(2 * p - h), "r2": r(p + (h - l)), "s2": r(p - (h - l))}


def day_map(nifty: list[dict], vix: list[dict], day: str) -> Optional[dict]:
    hist = [b for b in nifty if b["t"] < day]
    vhist = [b for b in vix if b["t"] < day]
    if len(hist) < 2 or not vhist or not hist[-1].get("h"):
        return None
    prev = hist[-1]
    m = vhist[-1]["c"] / math.sqrt(252)
    key = "PM::GAPTABLE"
    hit = store.get_company(key)
    if hit and time.time() - hit[0] < 86400 and hit[1].get("upto") == prev["t"]:
        cached = hit[1]
    else:
        cached = {"upto": prev["t"], "gaps": gap_table(hist), "range": range_check(hist, vix)}
        store.put_company(key, cached)
    today = next((b for b in nifty if b["t"] == day and b.get("o")), None)
    actual = round((today["o"] / prev["c"] - 1) * 100, 2) if today else None
    return {"day": day, "prev_day": prev["t"], "vix": round(vhist[-1]["c"], 2), "vix_day": vhist[-1]["t"], "expected_move_pct": round(m, 2),
            "range_low": round(prev["c"] * (1 - m / 100), 1), "range_high": round(prev["c"] * (1 + m / 100), 1),
            "range_history": cached["range"], "levels": levels(prev), "gaps": cached["gaps"], "since": nifty[0]["t"],
            "actual_gap_pct": actual, "actual_bucket": bucket_of(actual) if actual is not None else None}


# ------------------------------------------------------------------ C. evening preview
def evening_preview(quotes: dict, daily_series: dict, day: str, now: Optional[datetime] = None) -> Optional[dict]:
    """While the US is trading (between ~19:00 and 02:30 IST): the overnight formula on live values."""
    now = now or datetime.now(pm.IST)
    if not (now.hour >= 18 or now.hour < 2 or (now.hour == 2 and now.minute < 30)):
        return None
    spx = quotes.get(SPX)
    if not spx or not spx.get("time") or time.time() - float(spx["time"]) > 20 * 60:
        return None                                              # the US isn't trading right now
    fs = []
    for f in pm.FACTORS:
        q = quotes.get(f["sym"])
        ret = (q or {}).get("change_pct")
        z = _z(ret / 100 if ret is not None else None, daily_vol(daily_series.get(f["sym"]) or [], day))
        fs.append({"name": f["name"], "w": f["w"], "ret": ret, "z": None if z is None else round(z, 2),
                   "contrib": round(f["w"] * z, 2) if z is not None else 0.0})
    sc = pm.score_of(fs)
    return {"day": day, "score": sc, **pm.call_of(sc), "factors": fs, "built": now.strftime("%H:%M"),
            "note": "Preliminary: the US is still trading. Not backtested; the call that counts is built at 08:45 IST."}
