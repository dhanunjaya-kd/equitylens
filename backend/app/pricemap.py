"""Price map: where buyers and sellers stepped in before, how far falls like this one went,
whether the sector is falling too, and which turn signals are on, each with its own record.

Everything here is measured on real daily candles (the stock's, its sector index's and its
peers'). Nothing is forecast. Every rule below was fixed before looking at any result and is
not tuned:

  Fall from the high     close vs the highest close of the last 252 sessions (52 weeks).
  Stage                  pullback < 10%  ·  correction 10-20%  ·  bear > 20%.
  Volatility unit        ATR(14), the stock's normal daily range. Level rules use it, so a quiet and a wild
                         stock are judged on their own scale.
  Major swings           ZigZag: a high/low counts once price reverses max(3 x ATR%, 5%) from it; all history
                         (~10 years); the swing still forming is never used.
  Other levels           50/200-day averages · 52-week high/low (not if set in the last 5 sessions) · last
                         year's volume profile (most-traded price, 70% value-area top and bottom) · unfilled
                         gaps of 0.5+ ATR from the last 3 years · Fibonacci 38.2/50/61.8% of the last major move.
                         Only levels between half and twice today's price.
  Zones                  levels within 1 ATR of each other form one zone (at most 2 ATR wide); 3 shown each side.
  A test of a zone       price comes within 0.25 ATR of it from the other side; tests 5+ sessions apart,
                         counted over the last 3 years.
  Held                   a 2 ATR move away before a close 0.5 ATR through it, within 20 sessions.
  Broken                 that close first.  Neither in 20 sessions = not counted.
  Further-fall cases     every earlier time the stock first fell this far from its 52-week high;
                         the case ends at the next 52-week high. The fall still in progress is excluded.
  Turn signals           five fixed signals; record = 21-session return after each time a signal
                         switched on while the stock was 10%+ below its 52-week high (events at
                         least 10 sessions apart), against every day in such a fall. Called better
                         or worse only when the 90% range of its hit rate (Wilson) is wholly above
                         or below the any-day figure; otherwise "not clearly different".
  Too few cases          fewer than 10 cases: the cases are listed one by one, no percentages.
"""
from __future__ import annotations

import datetime as dt
import logging
import math
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from . import config, store, technicals

VERSION = 4
LOOK = 252            # 52-week high
SWING_BARS = 500     # history needed before the first level backtest sample
RESOLVE = 20
FALL_MIN = 0.05       # the further-fall section needs at least a 5% fall
IN_A_FALL = 0.10      # signal records are measured during falls of 10%+
FWD = 21              # "a month later"
GAP = 10              # signal events at least 10 sessions apart
MIN_CASES = 10
MAX_PEERS = 25
TTL = 3600


def _r(x, n=1):
    return None if x is None else round(x, n)


def _pct(vals, q):
    if not vals:
        return None
    v = sorted(vals)
    k = (len(v) - 1) * q
    f = math.floor(k)
    c = min(f + 1, len(v) - 1)
    return v[f] + (v[c] - v[f]) * (k - f)


def stage(dd_pct: float) -> str:
    """dd_pct is the fall in % (positive number)."""
    if dd_pct < 1:
        return "At its high"
    if dd_pct < 10:
        return "Pullback"
    if dd_pct <= 20:
        return "Correction"
    return "Bear phase"


# ------------------------------------------------------------------ series helpers
def rolling_high(c: list[float], n: int = LOOK) -> list[float]:
    from collections import deque
    out, q = [], deque()
    for i, v in enumerate(c):
        while q and c[q[-1]] <= v:
            q.pop()
        q.append(i)
        if q[0] <= i - n:
            q.popleft()
        out.append(c[q[0]])
    return out


def drawdowns(c: list[float]) -> list[float]:
    """Fall from the 52-week high close, as a negative fraction (0 = at the high)."""
    hi = rolling_high(c)
    return [v / h - 1 for v, h in zip(c, hi)]


# ------------------------------------------------------------------ levels (rules v2, fixed 21 Nov 2026)
ATR_N = 14
ZZ_ATR, ZZ_MIN = 3.0, 0.05      # a swing counts when price then reverses by max(3 x ATR%, 5%)
MERGE_ATR = 1.0                 # levels within 1 ATR of each other are one zone ...
MAX_ZONE_ATR = 2.0              # ... as long as the zone stays under 2 ATR wide
BAND_ATR = 0.25                 # a test = price comes within 0.25 ATR of the zone
HOLD_ATR = 2.0                  # held = it moves 2 ATR away from the zone ...
BREAK_ATR = 0.5                 # ... before a close 0.5 ATR through it
TEST_GAP = 5                    # tests at least 5 sessions apart
TEST_BARS = 750                 # tests counted over the last 3 years
REACH = (0.5, 2.0)              # levels between half and twice today's price
VP_BARS, VP_BINS, VA_SHARE = 250, 50, 0.70
GAP_ATR = 0.5                   # gaps of at least 0.5 ATR, last 3 years, still (partly) unfilled
FIBS = (0.382, 0.5, 0.618)
RECENT = 5                      # a 52-week extreme set in the last 5 sessions is not a level yet
SHOW = 3                        # zones shown each side
PRIORITY = ["zigzag", "gap", "volume", "fib", "ma", "52w"]


def atr_series(h, l, c) -> list:
    return technicals.wilder(technicals.true_range(h, l, c), ATR_N)


def zigzag(h, l, atr, c) -> list[dict]:
    """Confirmed major swings: a high (low) is a swing once price falls (rises) max(3 x ATR%, 5%) from it.
    The swing still forming at the last bar is never returned."""
    n = len(c)
    out: list[dict] = []
    if n < 3:
        return out
    trend, hi_i, lo_i = None, 0, 0
    for i in range(1, n):
        a = atr[i] if i < len(atr) else None
        thr = max(ZZ_MIN, ZZ_ATR * (a / c[i] if a else 0))
        if trend is None:
            if h[i] > h[hi_i]:
                hi_i = i
            if l[i] < l[lo_i]:
                lo_i = i
            if h[i] >= l[lo_i] * (1 + thr) and lo_i < i:
                out.append({"kind": "low", "i": lo_i, "price": l[lo_i], "confirmed": i})
                trend, hi_i = "up", i
            elif l[i] <= h[hi_i] * (1 - thr) and hi_i < i:
                out.append({"kind": "high", "i": hi_i, "price": h[hi_i], "confirmed": i})
                trend, lo_i = "down", i
        elif trend == "up":
            if h[i] > h[hi_i]:
                hi_i = i
            elif l[i] <= h[hi_i] * (1 - thr):
                out.append({"kind": "high", "i": hi_i, "price": h[hi_i], "confirmed": i})
                trend, lo_i = "down", i
        else:
            if l[i] < l[lo_i]:
                lo_i = i
            elif h[i] >= l[lo_i] * (1 + thr):
                out.append({"kind": "low", "i": lo_i, "price": l[lo_i], "confirmed": i})
                trend, hi_i = "up", i
    return out


def volume_profile(h, l, c, v):
    """Last 250 sessions: point of control and the 70% value area (volume placed at each bar's typical price)."""
    n = len(c)
    s = max(0, n - VP_BARS)
    if sum(1 for x in v[s:] if x) < (n - s) * 0.8:
        return None
    lo, hi = min(l[s:]), max(h[s:])
    if hi <= lo:
        return None
    w = (hi - lo) / VP_BINS
    vol = [0.0] * VP_BINS
    for i in range(s, n):
        vol[min(VP_BINS - 1, int(((h[i] + l[i] + c[i]) / 3 - lo) / w))] += v[i] or 0
    tot = sum(vol)
    if tot <= 0:
        return None
    poc = max(range(VP_BINS), key=lambda k: vol[k])
    a = b = poc
    got = vol[poc]
    while got < VA_SHARE * tot:
        left = vol[a - 1] if a > 0 else -1
        right = vol[b + 1] if b < VP_BINS - 1 else -1
        if right >= left:
            b += 1
            got += right
        else:
            a -= 1
            got += left
    edge = lambda k: lo + k * w
    return {"poc": (edge(poc), edge(poc + 1)), "val": edge(a), "vah": edge(b + 1), "start": s}


def _month(t: str) -> str:
    return dt.date.fromisoformat(t).strftime("%b %Y")


def candidates(bars: list[dict], atr: list) -> list[dict]:
    """Every level the rules produce, each with the bar from which its tests are counted."""
    t = [b["t"] for b in bars]
    h = [b["h"] for b in bars]
    l = [b["l"] for b in bars]
    c = [b["c"] for b in bars]
    v = [b.get("v") or 0 for b in bars]
    n, px = len(c), c[-1]
    out = []

    def add(lo, hi, src, what, start, moving=None):
        if REACH[0] * px <= (lo + hi) / 2 <= REACH[1] * px:
            out.append({"lo": lo, "hi": hi, "src": src, "what": what, "start": start, "moving": moving})

    zz = zigzag(h, l, atr, c)
    for p in zz:
        add(p["price"], p["price"], "zigzag", f"Major swing {p['kind']} {p['price']:.2f} ({_month(t[p['i']])})", p["confirmed"] + 1)
    for mn in (50, 200):
        ma = technicals.sma(c, mn)
        if ma[-1] is None:
            continue
        slope = "rising" if ma[-21] is not None and ma[-1] > ma[-21] else "falling"
        add(ma[-1], ma[-1], "ma", f"{mn}-day average ({slope})", mn, moving=mn)
    s = max(0, n - LOOK)
    i_hi = max(range(s, n), key=lambda i: h[i])
    i_lo = min(range(s, n), key=lambda i: l[i])
    if i_hi < n - RECENT:
        add(h[i_hi], h[i_hi], "52w", f"52-week high ({t[i_hi]})", i_hi + 1)
    if i_lo < n - RECENT:
        add(l[i_lo], l[i_lo], "52w", f"52-week low ({t[i_lo]})", i_lo + 1)
    vp = volume_profile(h, l, c, v)
    if vp:
        add(vp["poc"][0], vp["poc"][1], "volume", "Most-traded price, last year (volume profile)", vp["start"])
        add(vp["val"], vp["val"], "volume", "Bottom of last year's value area (70% of volume)", vp["start"])
        add(vp["vah"], vp["vah"], "volume", "Top of last year's value area (70% of volume)", vp["start"])
    for i in range(max(1, n - TEST_BARS), n):
        a = atr[i]
        if not a:
            continue
        if l[i] - h[i - 1] >= GAP_ATR * a:                 # gap up: support while unfilled
            low_since = min(l[i:])
            if low_since > h[i - 1]:
                add(h[i - 1], min(l[i], low_since), "gap", f"Unfilled gap up from {t[i]}", i + 1)
        if l[i - 1] - h[i] >= GAP_ATR * a:                 # gap down: resistance while unfilled
            high_since = max(h[i:])
            if high_since < l[i - 1]:
                add(max(h[i], high_since), l[i - 1], "gap", f"Unfilled gap down from {t[i]}", i + 1)
    if len(zz) >= 2:                                       # Fibonacci of the last major move
        a, b = zz[-2], zz[-1]
        move = "rise" if b["kind"] == "high" else "fall"
        for r in FIBS:
            p = b["price"] + r * (a["price"] - b["price"])
            add(p, p, "fib", f"Fibonacci {r * 100:.1f}% of the {move} {a['price']:.2f} → {b['price']:.2f} ({_month(t[a['i']])}–{_month(t[b['i']])})",
                b["confirmed"] + 1)
    return out


def zones_from(cands: list[dict], atr_now: float) -> list[dict]:
    """Merge levels within 1 ATR of each other into zones (never wider than 2 ATR)."""
    zs: list[dict] = []
    for cd in sorted(cands, key=lambda x: (x["lo"] + x["hi"]) / 2):
        if zs:
            z = zs[-1]
            if cd["lo"] - z["hi"] <= MERGE_ATR * atr_now and max(z["hi"], cd["hi"]) - min(z["lo"], cd["lo"]) <= MAX_ZONE_ATR * atr_now:
                z["lo"], z["hi"] = min(z["lo"], cd["lo"]), max(z["hi"], cd["hi"])
                z["parts"].append(cd)
                continue
        zs.append({"lo": cd["lo"], "hi": cd["hi"], "parts": [cd]})
    for z in zs:
        srcs = {p["src"] for p in z["parts"]}
        z["sources"] = [s for s in PRIORITY if s in srcs]
        z["source"] = z["sources"][0]
        z["start"] = min(p["start"] for p in z["parts"])
        mv = [p["moving"] for p in z["parts"] if p["moving"]]
        z["moving"] = mv[0] if len(z["parts"]) == 1 and mv else None
    return zs


def tests(h, l, c, atr, lo, hi, side: str, start: int, end: Optional[int] = None, ma: Optional[list] = None) -> dict:
    """Count tests of a zone and how they ended (ATR at each test). `ma` = a moving line instead of a fixed zone.

    support: price comes within 0.25 ATR of the zone top from above.  resistance: of the zone bottom from below.
    held: a 2 ATR move away from the zone before a close 0.5 ATR through it, within 20 sessions; broken: that close
    first; neither: not counted. Tests are at least 5 sessions apart and only use bars from `start`."""
    end = len(c) if end is None else end
    held = broken = 0
    events = []
    i = max(start, 1)
    while i < end:
        a = atr[i]
        zlo, zhi = (ma[i], ma[i]) if ma else (lo, hi)
        plo, phi = (ma[i - 1], ma[i - 1]) if ma else (lo, hi)
        if not a or zlo is None or plo is None:
            i += 1
            continue
        if side == "support":
            began = l[i] <= zhi + BAND_ATR * a and c[i - 1] > phi + BAND_ATR * a
        else:
            began = h[i] >= zlo - BAND_ATR * a and c[i - 1] < plo - BAND_ATR * a
        if not began:
            i += 1
            continue
        outcome, j = None, i
        for j in range(i, min(end, i + RESOLVE)):
            jl, jh = (ma[j], ma[j]) if ma else (zlo, zhi)
            if jl is None:
                continue
            if side == "support":
                if c[j] < jl - BREAK_ATR * a:
                    outcome = "broken"
                elif h[j] >= zhi + HOLD_ATR * a:
                    outcome = "held"
            else:
                if c[j] > jh + BREAK_ATR * a:
                    outcome = "broken"
                elif l[j] <= zlo - HOLD_ATR * a:
                    outcome = "held"
            if outcome:
                break
        if outcome:
            held += outcome == "held"
            broken += outcome == "broken"
            events.append((i, outcome))
            i = max(j + 1, i + TEST_GAP)
        else:
            i += RESOLVE
    return {"held": held, "broken": broken, "tests": held + broken, "events": events}


def _zone_row(z, side, px, atr_now, h, l, c, atr, t, mas):
    n = len(c)
    ma = mas.get(z["moving"]) if z["moving"] else None
    ts = tests(h, l, c, atr, z["lo"], z["hi"], side, max(z["start"], n - TEST_BARS), ma=ma)
    edge = z["hi"] if side == "support" else z["lo"]
    return {"kind": side, "lo": round(z["lo"], 2), "hi": round(z["hi"], 2), "price": round((z["lo"] + z["hi"]) / 2, 2),
            "dist_pct": round((edge / px - 1) * 100, 1), "dist_atr": round((edge - px) / atr_now, 1),
            "what": " · ".join(p["what"] for p in z["parts"]), "parts": [p["what"] for p in z["parts"]],
            "sources": z["sources"], "source": z["source"], "ma_n": z["moving"],
            "held": ts["held"], "tests": ts["tests"], "bucket": bucket(ts["tests"], ts["held"]),
            "last_test": t[ts["events"][-1][0]] if ts["events"] else None}


def level_ladder(bars: list[dict]) -> dict:
    t = [b["t"] for b in bars]
    h = [b["h"] for b in bars]
    l = [b["l"] for b in bars]
    c = [b["c"] for b in bars]
    px = c[-1]
    atr = atr_series(h, l, c)
    atr_now = atr[-1] or px * 0.02
    zs = zones_from(candidates(bars, atr), atr_now)
    mas = {50: technicals.sma(c, 50), 200: technicals.sma(c, 200)}
    band = BAND_ATR * atr_now
    inside = [z for z in zs if z["lo"] - band <= px <= z["hi"] + band]
    below = sorted([z for z in zs if z["hi"] + band < px], key=lambda z: -z["hi"])[:SHOW]
    above = sorted([z for z in zs if z["lo"] - band > px], key=lambda z: z["lo"])[:SHOW]
    row = lambda z, side: _zone_row(z, side, px, atr_now, h, l, c, atr, t, mas)
    return {"price": round(px, 2), "atr": round(atr_now, 2), "atr_pct": round(atr_now / px * 100, 2),
            "resistance": [row(z, "resistance") for z in above], "support": [row(z, "support") for z in below],
            "inside": [{"lo": round(z["lo"], 2), "hi": round(z["hi"], 2), "what": " · ".join(p["what"] for p in z["parts"]),
                        "sources": z["sources"]} for z in inside],
            "zone_count": len(zs)}


# ------------------------------------------------------------------ further-fall cases
def fall_cases(bars: list[dict], depth: float, who: str = "") -> list[dict]:
    """Every earlier time the close first fell `depth` (fraction) below its 52-week high.
    A case ends at the next 52-week high; the case still running at the last bar is excluded."""
    c = [b["c"] for b in bars]
    t = [b["t"] for b in bars]
    if len(c) < LOOK + FWD:
        return []
    dd = drawdowns(c)
    out, i, n = [], LOOK, len(c)
    armed = True
    while i < n:
        if dd[i] >= 0:
            armed = True
        if armed and dd[i] <= -depth and dd[i - 1] > -depth:
            armed = False
            j = i + 1
            while j < n and dd[j] < 0:
                j += 1
            if j >= n:      # still running: that is today's fall (or one that never recovered) -> excluded
                break
            seg = c[i:j + 1]
            k = min(range(len(seg)), key=lambda x: seg[x])
            back = None
            if i + 63 < n:
                back = max(c[i + 1:i + 64]) >= c[i]
            out.append({"date": t[i], "who": who, "price": round(c[i], 2), "further_pct": round((seg[k] / c[i] - 1) * 100, 1),
                        "days_to_low": k, "back_in_3m": back, "recovered": t[j]})
            i = j
            continue
        i += 1
    return out


BUCKETS = [(0, 5, "0–5%"), (5, 10, "5–10%"), (10, 20, "10–20%"), (20, 30, "20–30%"), (30, 1000, "30%+")]


def summarize_cases(cases: list[dict]) -> dict:
    n = len(cases)
    out = {"n": n, "enough": n >= MIN_CASES}
    if not n:
        return out
    falls = [-x["further_pct"] for x in cases]    # positive = fell further
    out["buckets"] = [{"label": lab, "n": sum(1 for f in falls if a <= f < b)} for a, b, lab in BUCKETS]
    if n >= MIN_CASES:
        backs = [x["back_in_3m"] for x in cases if x["back_in_3m"] is not None]
        out.update({"median": _r(_pct(falls, 0.5)), "p75": _r(_pct(falls, 0.75)), "worst": _r(max(falls)),
                    "median_days": int(_pct([x["days_to_low"] for x in cases], 0.5)),
                    "back_3m_pct": _r(100 * sum(backs) / len(backs), 0) if backs else None, "back_n": len(backs)})
    return out


def month_range(c: list[float], bars: int = 756) -> Optional[dict]:
    s = max(0, len(c) - bars)
    rets = [c[i + FWD] / c[i] - 1 for i in range(s, len(c) - FWD)]
    if len(rets) < 100:
        return None
    lo, hi = _pct(rets, 0.10), _pct(rets, 0.90)
    return {"lo_pct": _r(lo * 100), "hi_pct": _r(hi * 100), "lo": round(c[-1] * (1 + lo), 2), "hi": round(c[-1] * (1 + hi), 2),
            "n": len(rets)}


# ------------------------------------------------------------------ turn signals
SIGNALS = [
    ("above20", "Closes back above its 20-day average"),
    ("higher_low", "Higher low after a new low"),
    ("rsi_back", "RSI back above 30 after being oversold"),
    ("dry_volume", "Selling volume drying up"),
    ("sector_up", "Sector back above its 20-day average"),
]
SIGNAL_RULES = {
    "above20": "close above the 20-day average",
    "higher_low": "a 60-day low 5–40 sessions ago, then a swing low (3 bars each side) above it, and the close above that swing low",
    "rsi_back": "RSI(14) above 30 with RSI below 30 at some point in the previous 10 sessions",
    "dry_volume": "average volume on down days in the last 10 sessions below 80% of the average volume of the 50 sessions before",
    "sector_up": "sector index close above its own 20-day average",
}


def wilson(k: int, n: int, z: float = 1.645) -> tuple[float, float]:
    """90% range for a hit rate of k out of n (Wilson). With few cases the range is wide."""
    if n <= 0:
        return 0.0, 1.0
    p = k / n
    den = 1 + z * z / n
    mid = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, mid - half), min(1.0, mid + half)


class SignalBook:
    def __init__(self, bars: list[dict], sector: Optional[list[dict]] = None):
        self.t = [b["t"] for b in bars]
        self.h = [b["h"] for b in bars]
        self.l = [b["l"] for b in bars]
        self.c = [b["c"] for b in bars]
        self.v = [b.get("v") or 0 for b in bars]
        self.s20 = technicals.sma(self.c, 20)
        self.rsi = technicals.rsi(self.c, 14)
        self.has_vol = sum(1 for x in self.v[-60:] if x) > 50
        self.sec = None
        if sector:
            sc = [b["c"] for b in sector]
            ss = technicals.sma(sc, 20)
            self.sec = {b["t"]: (b["c"], m) for b, m in zip(sector, ss) if m is not None}
            self.sec_last = sector[-1]["t"]

    def on(self, key: str, i: int) -> Optional[bool]:
        c, l = self.c, self.l
        if key == "above20":
            return None if self.s20[i] is None else c[i] > self.s20[i]
        if key == "higher_low":
            if i < 60:
                return None
            j = min(range(i - 59, i + 1), key=lambda x: l[x])
            if not (5 <= i - j <= 40):
                return False
            for m in range(j + 4, i - 2):
                if l[m] == min(l[m - 3:m + 4]) and l[m] > l[j] and c[i] > l[m]:
                    return True
            return False
        if key == "rsi_back":
            r = self.rsi[i]
            prev = [x for x in self.rsi[max(0, i - 10):i] if x is not None]
            return None if r is None or not prev else (r > 30 and min(prev) < 30)
        if key == "dry_volume":
            if not self.has_vol or i < 60:
                return None
            downs = [self.v[k] for k in range(i - 9, i + 1) if c[k] < c[k - 1]]
            base = self.v[i - 59:i - 9]
            bm = sum(base) / len(base) if base else 0
            if len(downs) < 2 or bm <= 0:
                return False
            return (sum(downs) / len(downs)) < 0.8 * bm
        if key == "sector_up":
            if not self.sec:
                return None
            x = self.sec.get(self.t[i])
            return None if x is None else x[0] > x[1]
        return None

    def state_text(self, key: str) -> str:
        i = len(self.c) - 1
        on = self.on(key, i)
        if on is None:
            return {"dry_volume": "No volume data", "sector_up": "No sector index"}.get(key, "Not enough history")
        if key == "above20":
            gap = (self.s20[i] / self.c[i] - 1) * 100
            return f"Yes · 20-day average {self.s20[i]:.2f}" if on else f"Not yet · 20-day average at {self.s20[i]:.2f}, {gap:.1f}% above"
        if key == "higher_low":
            j = min(range(i - 59, i + 1), key=lambda x: self.l[x])
            return f"Yes · the {self.t[j]} low of {self.l[j]:.2f} has held" if on else f"Not yet · 60-day low {self.l[j]:.2f} on {self.t[j]}"
        if key == "rsi_back":
            return f"{'Yes' if on else 'No'} · RSI {self.rsi[i]:.0f}"
        if key == "dry_volume":
            downs = [self.v[k] for k in range(i - 9, i + 1) if self.c[k] < self.c[k - 1]]
            base = self.v[i - 59:i - 9]
            if len(downs) < 2:
                return "No · fewer than 2 down days in the last 10"
            ratio = (sum(downs) / len(downs)) / (sum(base) / len(base)) - 1
            return f"{'Yes' if on else 'No'} · down-day volume {abs(ratio) * 100:.0f}% {'below' if ratio < 0 else 'above'} the 50 sessions before"
        if key == "sector_up":
            if self.sec_last != self.t[i]:
                return f"{'Yes' if on else 'No'} (sector data to {self.sec_last})"
            return "Yes" if on else "Not yet"
        return ""

    def record(self, key: str) -> dict:
        c, n = self.c, len(self.c)
        dd = drawdowns(c)
        events, base = [], []
        last, prev = -GAP, None
        for i in range(LOOK, n - FWD):
            if dd[i] > -IN_A_FALL:
                prev = self.on(key, i)
                continue
            fwd = c[i + FWD] / c[i] - 1
            base.append(fwd)
            cur = self.on(key, i)
            if cur and prev is False and i - last >= GAP:
                events.append((self.t[i], fwd))
                last = i
            prev = cur
        out = {"n": len(events), "base_n": len(base),
               "base_up_pct": _r(100 * sum(1 for x in base if x > 0) / len(base), 0) if base else None}
        if len(events) >= MIN_CASES:
            ups = sum(1 for _, x in events if x > 0)
            lo, hi = wilson(ups, len(events))
            out.update({"up_pct": _r(100 * ups / len(events), 0), "median_pct": _r(100 * _pct([x for _, x in events], 0.5)),
                        "range": [_r(lo * 100, 0), _r(hi * 100, 0)]})
            base = out["base_up_pct"] or 0
            out["verdict"] = "better" if lo * 100 > base else ("worse" if hi * 100 < base else "same")
        else:
            out["verdict"] = "too_few"
            out["cases"] = [{"date": d, "fwd_pct": _r(x * 100)} for d, x in events[-9:]]
        return out


# ------------------------------------------------------------------ sector
IN_INDEX = [   # (words in the sector path, Yahoo ticker, index name); first match wins
    (("nbfc", "non banking", "housing finance", "insurance", "asset management", "financial services", "finance"), "NIFTY_FIN_SERVICE.NS", "NIFTY Financial Services"),
    (("bank",), "^NSEBANK", "NIFTY Bank"),
    (("it - software", "it - services", "information technology", "computers - software", "software"), "^CNXIT", "NIFTY IT"),
    (("automobile", "auto components", "auto ancillar", "tyres"), "^CNXAUTO", "NIFTY Auto"),
    (("pharma", "healthcare", "hospital", "drug"), "^CNXPHARMA", "NIFTY Pharma (closest match)"),
    (("fast moving consumer goods", "fmcg", "personal care", "packaged foods", "tobacco", "beverages"), "^CNXFMCG", "NIFTY FMCG"),
    (("metals & mining", "ferrous", "steel", "aluminium", "copper", "zinc", "mining"), "^CNXMETAL", "NIFTY Metal"),
    (("realty", "real estate", "residential, commercial"), "^CNXREALTY", "NIFTY Realty"),
    (("oil", "gas", "petroleum", "refiner", "power", "energy", "coal"), "^CNXENERGY", "NIFTY Energy"),
    (("media", "entertainment", "broadcast"), "^CNXMEDIA", "NIFTY Media"),
    (("construction", "capital goods", "cement", "telecom", "infrastructure", "engineering"), "^CNXINFRA", "NIFTY Infrastructure (closest match)"),
]
US_FUND = [   # (words in the SEC industry text, fund, name)
    (("semiconductor",), "SMH", "VanEck Semiconductor ETF"),
    (("prepackaged software", "computer programming", "computer integrated", "computer processing", "services-computer"), "IGV", "iShares Software ETF"),
    (("computer", "electronic"), "XLK", "Technology Select Sector SPDR"),
    (("pharmaceutical", "biological", "surgical", "medical", "hospital", "health"), "XLV", "Health Care Select Sector SPDR"),
    (("bank", "savings institution", "finance", "insurance", "security brokers", "investment", "credit"), "XLF", "Financial Select Sector SPDR"),
    (("petroleum", "crude", "oil", "natural gas", "drilling"), "XLE", "Energy Select Sector SPDR"),
    (("electric services", "utilit", "water supply", "cogeneration"), "XLU", "Utilities Select Sector SPDR"),
    (("real estate",), "XLRE", "Real Estate Select Sector SPDR"),
    (("telephone", "communications", "cable", "radio", "television"), "XLC", "Communication Services Select Sector SPDR"),
    (("retail", "catalog", "motor vehicles", "hotels", "eating", "apparel", "amusement"), "XLY", "Consumer Discretionary Select Sector SPDR"),
    (("food", "beverage", "tobacco", "soap", "perfume", "cosmetic"), "XLP", "Consumer Staples Select Sector SPDR"),
    (("chemical", "steel", "metal", "mining", "paper", "plastics"), "XLB", "Materials Select Sector SPDR"),
    (("aircraft", "guided missiles", "machinery", "railroad", "trucking", "air transportation", "construction"), "XLI", "Industrials Select Sector SPDR"),
]


def sector_ticker(market: str, sector_path: list[str]) -> Optional[dict]:
    """Match the most specific part of the path first (a bank's path starts with "Financial Services")."""
    table = US_FUND if market == "US" else IN_INDEX
    for part in reversed(sector_path or []):
        text = part.lower()
        for words, tick, name in table:
            if any(w in text for w in words):
                return {"ticker": tick, "name": name, "matched_on": " › ".join(sector_path or [])}
    return None


def _sector_bars(tick: str) -> list[dict]:
    from . import premarket
    return premarket.daily(tick, max_age=6 * 3600)


def beta(a: list[dict], b: list[dict], bars: int = 250) -> Optional[dict]:
    """How much the stock moves per 1% sector move, from daily returns on shared dates."""
    bm = {x["t"]: x["c"] for x in b}
    pairs = [(x["t"], x["c"], bm[x["t"]]) for x in a if x["t"] in bm][-(bars + 1):]
    if len(pairs) < 120:
        return None
    ra = [pairs[i][1] / pairs[i - 1][1] - 1 for i in range(1, len(pairs))]
    rb = [pairs[i][2] / pairs[i - 1][2] - 1 for i in range(1, len(pairs))]
    ma, mb = statistics.fmean(ra), statistics.fmean(rb)
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb)) / len(ra)
    var = sum((y - mb) ** 2 for y in rb) / len(rb)
    if var <= 0:
        return None
    sa = statistics.pstdev(ra)
    corr = cov / (sa * math.sqrt(var)) if sa > 0 else None
    return {"beta": round(cov / var, 2), "corr": _r(corr, 2), "n": len(ra)}


def _ret(bars, k=63):
    return (bars[-1]["c"] / bars[-1 - k]["c"] - 1) * 100 if len(bars) > k else None


def peer_list(rep: dict, market: str) -> tuple[list[str], str]:
    me = rep.get("symbol")
    rows = ((rep.get("peers") or {}).get("rows") or [])
    syms = [r.get("symbol") for r in rows if r.get("symbol") and r.get("symbol") != me]
    if len(syms) >= 4:
        return syms[:MAX_PEERS], "the source's industry peer list"
    sp = (rep.get("company") or {}).get("sector_path") or []
    if not sp:
        return syms, "the source's industry peer list"
    ranks = [r for r in store.all_rankings() if r.get("market", "IN") == market and r.get("symbol") != me]
    steps = [("sector", sp[-1], f"EquityLens's list for {sp[-1]}")]
    if market != "US" and len(sp) > 1:     # a US path is ["United States", industry]: no wider sector group
        steps.append(("broad_sector", sp[0], f"EquityLens's list for {sp[0]} (wider group)"))
    for n_step, (field, val, label) in enumerate(steps):
        same = sorted([r for r in ranks if r.get(field) == val], key=lambda r: -(r.get("market_cap") or 0))
        if len(same) >= 4 or n_step == len(steps) - 1:
            return list(dict.fromkeys(syms + [r["symbol"] for r in same]))[:MAX_PEERS], label
    return syms, "the source's industry peer list"


def _peer_bars(sym: str):
    try:
        bars, _, _ = technicals.get_bars(sym)
        return sym, bars if len(bars) > 260 else None
    except Exception:  # noqa: BLE001 - a peer without prices is skipped (and counted as missing)
        return sym, None


def sector_check(rep: dict, bars: list[dict], depth: float) -> dict:
    market = rep.get("market") or "IN"
    sp = (rep.get("company") or {}).get("sector_path") or []
    out: dict = {"path": sp, "index": None, "peers": [], "peer_source": ""}
    st = sector_ticker(market, sp)
    sb = None
    if st:
        out["index"] = dict(st)
        try:
            sb = _sector_bars(st["ticker"])
        except Exception as e:  # noqa: BLE001
            out["index"]["error"] = f"could not load {st['ticker']}: {e}"
            sb = None
        if sb and len(sb) > LOOK:
            sc = [b["c"] for b in sb]
            dd = drawdowns(sc)[-1] * 100
            s50, s200 = technicals.sma(sc, 50)[-1], technicals.sma(sc, 200)[-1]
            out["index"].update({
                "last_date": sb[-1]["t"], "fall_pct": _r(-dd), "stage": stage(-dd),
                "above50": sc[-1] > s50 if s50 else None, "above200": sc[-1] > s200 if s200 else None,
                "ret_3m": _r(_ret(sb)), "beta": beta(bars, sb)})
        elif not out["index"].get("error"):
            out["index"]["error"] = f"no price history for {st['ticker']}"
    syms, src = peer_list(rep, market)
    out["peer_source"] = src
    got = {}
    if syms:
        with ThreadPoolExecutor(max_workers=8) as ex:
            for s, b in ex.map(_peer_bars, syms):
                if b:
                    got[s] = b
    rows = []
    for s, b in got.items():
        c = [x["c"] for x in b]
        s50 = technicals.sma(c, 50)[-1]
        rows.append({"symbol": s, "fall_pct": _r(-drawdowns(c)[-1] * 100), "above50": c[-1] > s50 if s50 else None,
                     "ret_3m": _r(_ret(b)), "last_date": b[-1]["t"]})
    rows.sort(key=lambda r: r["fall_pct"] or 0)
    out["peers"] = rows
    out["peers_asked"], out["peers_with_prices"] = len(syms), len(rows)
    if rows:
        ab = [r for r in rows if r["above50"] is not None]
        out["breadth"] = {"above50": sum(1 for r in ab if r["above50"]), "of": len(ab)}
        out["peer_median_fall"] = _r(_pct([r["fall_pct"] for r in rows], 0.5))
        out["peer_median_3m"] = _r(_pct([r["ret_3m"] for r in rows if r["ret_3m"] is not None], 0.5))
    me3 = _ret(bars)
    ref = (out["index"] or {}).get("ret_3m")
    ref_name = (out["index"] or {}).get("name") if ref is not None else ("the median peer" if rows else None)
    if ref is None:
        ref = out.get("peer_median_3m")
    if me3 is not None and ref is not None:
        out["vs_sector_3m"] = {"stock": _r(me3), "sector": ref, "diff": _r(me3 - ref), "against": ref_name}
    # the plain answer: is it the sector or the stock?  (fixed thresholds, same bands as the stage)
    me_fall = depth * 100
    sec_fall = (out["index"] or {}).get("fall_pct")
    if sec_fall is None:
        sec_fall = out.get("peer_median_fall")
    if sec_fall is None:
        out["answer"] = "No sector data to compare with."
    elif me_fall < 10:
        out["answer"] = f"The stock is only {me_fall:.1f}% off its high; the sector is {sec_fall:.1f}% off."
    elif sec_fall >= 10:
        out["answer"] = f"Both: the sector is {sec_fall:.1f}% off its high too ({stage(sec_fall).lower()})."
    elif sec_fall < 5:
        out["answer"] = f"Mostly this stock: the sector is only {sec_fall:.1f}% off its high."
    else:
        out["answer"] = f"Partly: the sector is {sec_fall:.1f}% off its high, the stock {me_fall:.1f}%."
    return out, sb, got


# ------------------------------------------------------------------ business
RESULT_MOVE = 10.0      # % change in profit or sales that is reported
MARGIN_MOVE = 3.0       # points of operating margin that are reported


def recent_results(rep: dict) -> list[tuple[bool, str]]:
    """Latest quarter vs the same quarter a year earlier, and the latest full year vs the one before,
    straight from the company's tables. Only moves of 10%+ (3+ margin points) are reported."""
    tabs = (rep.get("company") or {}).get("tables") or {}
    cur = rep.get("currency") or {}
    sym, unit = cur.get("symbol") or "₹", cur.get("unit") or "Cr"
    money = lambda v: f"{sym}{v:,.0f} {unit}" if unit != "M" else f"{sym}{v:,.0f}M"
    out: list[tuple[bool, str]] = []

    def pair(table, row, back):
        cols = table.get("columns") or []
        vals = (table.get("rows") or {}).get(row) or []
        idx = [k for k, c in enumerate(cols) if c != "TTM" and k < len(vals) and vals[k] is not None]
        if len(idx) <= back:
            return None
        a, b = idx[-1], idx[-1 - back]
        return cols[a], vals[a], cols[b], vals[b]

    q = tabs.get("quarters") or {}
    for row, label in (("Net Profit", "Quarterly profit"), ("Sales", "Quarterly sales")):
        x = pair(q, row, 4)
        if x and x[3] and x[3] > 0:
            ch = (x[1] / x[3] - 1) * 100
            if abs(ch) >= RESULT_MOVE:
                out.append((ch > 0, f"{label} {'up' if ch > 0 else 'down'} {abs(ch):.0f}% on a year ago ({money(x[1])} in {x[0]} vs {money(x[3])} in {x[2]})"))
    x = pair(q, "OPM %", 4)
    if x and abs(x[1] - x[3]) >= MARGIN_MOVE:
        out.append((x[1] > x[3], f"Operating margin {x[1]:.1f}% in {x[0]} vs {x[3]:.1f}% a year earlier"))
    x = pair(tabs.get("profit_loss") or {}, "Net Profit", 1)
    if x and x[3] and x[3] > 0:
        ch = (x[1] / x[3] - 1) * 100
        if abs(ch) >= RESULT_MOVE:
            out.append((ch > 0, f"Yearly profit {'up' if ch > 0 else 'down'} {abs(ch):.0f}% ({money(x[1])} in {x[0]} vs {money(x[3])} in {x[2]})"))
    return out


def business(rep: dict) -> dict:
    a = rep.get("analysis") or {}
    sc = a.get("scores") or {}
    plus = list((a.get("strengths") or [])[:4])
    minus = [f["text"] for f in (a.get("flags") or []) if f.get("severity") in ("high", "medium")][:5]
    val = ((a.get("entry") or {}).get("checks") or {}).get("value") or {}
    vt = (val.get("text") or "").split(" Shown for information")[0].rstrip(".")
    if val.get("state") in ("Full", "Expensive"):
        minus.append(f"Price vs value: {vt}")
    elif val.get("state") in ("Cheap", "Fair") and vt:
        plus.append(f"Price vs value: {vt}")
    for good, text in recent_results(rep):
        (plus if good else minus).append(text)
    names = {"growth": "Growth", "quality": "Quality", "strength": "Balance sheet", "cash": "Cash flow"}
    for k, lab in names.items():
        x = sc.get(k)
        if x is not None and x < 40:
            minus.append(f"{lab} score {x:.0f}/100 (weak)")
    return {"score": sc.get("business"), "overall": sc.get("overall"), "plus": plus, "minus": minus,
            "verdict": (a.get("verdict") or {}).get("label")}


# ------------------------------------------------------------------ do past hold rates predict the next test?
# Fixed before any run (21 Nov 2026), used by tools/levels_backtest.py and shown on the tab:
#   At every month end, the nearest support and nearest resistance are built from prices up to that day only.
#   Their record so far puts them in one bucket (below). The outcome is the NEXT test after that day
#   (same held / broken definition, within 252 sessions; untested or unresolved = not counted).
#   Each test is counted once (the first month end that saw it).
#   PASS for a side (support / resistance): the "3+ tests, held 75%+" bucket held again at least 10 points more
#   often than the "3+ tests, held under 50%" bucket AND at least 5 points more often than all levels of that
#   side, in BOTH halves (tests before 2021 / from 2021), with at least 100 tests in each of those buckets in
#   each half. Otherwise past hold rates are reported as NOT predictive.
LEVEL_RULES_VERSION = 2
# Chance test, fixed before running it (21 Nov 2026, after the first result showed a zone's record did not predict):
#   Next to every real zone, a "random price" zone is placed on the same side with the SAME WIDTH, its near edge at a
#   random distance from price (uniform 0.25 to max(2 x the real zone's far-edge distance + 1, 8), in ATRs), not overlapping
#   any real zone. Its next test is measured with exactly the same rules. Real and random zones are compared inside
#   the same distance bands (0.25-1, 1-2, 2-4, 4-8, 8+ ATR; bands with 20+ tests of each), weighted by the real
#   tests in each band. Real zones PASS if that weighted edge is at least 5 points in both halves, with 100+ tests
#   of each kind in each half.
TEST_VERSION = 2
CHANCE_EDGE = 5.0
PLACEBO_TRIES = 30
DIST_BANDS = [(0.25, 1), (1, 2), (2, 4), (4, 8), (8, 1e9)]
MIN_BAND = 20
BUCKETS_L = ["untested", "1-2 tests", "3+ tests, held under 50%", "3+ tests, held 50-74%", "3+ tests, held 75%+"]
LEVEL_SPLIT = "2021-01-01"
LEVEL_MIN_N = 100
LEVEL_EDGE_WEAK = 10.0
LEVEL_EDGE_ALL = 5.0


def bucket(tests_n: int, held: int) -> str:
    if not tests_n:
        return BUCKETS_L[0]
    if tests_n < 3:
        return BUCKETS_L[1]
    r = held / tests_n
    return BUCKETS_L[2] if r < 0.5 else (BUCKETS_L[3] if r < 0.75 else BUCKETS_L[4])


def month_ends(bars, start="2016-01-01"):
    return [k for k in range(len(bars) - 1) if bars[k]["t"] >= start and bars[k]["t"][:7] != bars[k + 1]["t"][:7]]


def _placebo(row: dict, lad: dict, rnd) -> Optional[tuple]:
    """A random-price zone for `row`: same side and width, near edge at a random distance, clear of every real zone.
    Returns (lo, hi, distance of the near edge in ATRs)."""
    px, atr_now = lad["price"], lad["atr"]
    width = row["hi"] - row["lo"]
    far = abs(row["dist_atr"]) + width / atr_now
    real = [(z["lo"], z["hi"]) for z in lad["support"] + lad["resistance"] + lad.get("inside", [])]
    gap = BAND_ATR * atr_now
    for _ in range(PLACEBO_TRIES):
        x = rnd.uniform(DIST_BANDS[0][0], max(2 * far + 1, 8.0))
        if row["kind"] == "support":
            hi = px - x * atr_now
            lo = hi - width
        else:
            lo = px + x * atr_now
            hi = lo + width
        if lo <= 0:
            continue
        if all(hi + gap < a or lo - gap > b for a, b in real):
            return lo, hi, x
    return None


def _band(d) -> Optional[int]:
    d = abs(d)
    for k, (a, b) in enumerate(DIST_BANDS):
        if a <= d < b:
            return k
    return None


def level_samples(bars: list[dict], liquid=None, chance: bool = True) -> list[dict]:
    """One stock: at each month end, the nearest support and resistance zone (from prices up to that day only),
    their bucket, and how their NEXT test ended; plus a random-price zone next to each for the chance test."""
    import random
    import zlib
    t = [b["t"] for b in bars]
    h = [b["h"] for b in bars]
    l = [b["l"] for b in bars]
    c = [b["c"] for b in bars]
    n = len(c)
    atr = atr_series(h, l, c)
    mas = {50: technicals.sma(c, 50), 200: technicals.sma(c, 200)}
    seen, out = set(), []

    def nxt(lo, hi, side, i, ma=None):
        r = tests(h, l, c, atr, lo, hi, side, i + 1, min(n, i + 1 + LOOK), ma=ma)
        return r["events"][0] if r["events"] else None

    for i in month_ends(bars):
        if i < SWING_BARS + 20 or (liquid and not liquid(bars, i)):
            continue
        lad = level_ladder(bars[:i + 1])
        for row in lad["support"][:1] + lad["resistance"][:1]:
            ma = mas[row["ma_n"]] if row.get("ma_n") else None
            ev = nxt(row["lo"], row["hi"], row["kind"], i, ma)
            if ev:
                j, outcome = ev
                key = (row["kind"], row["source"], j)
                if key not in seen:
                    seen.add(key)
                    out.append({"date": t[j], "seen": t[i], "side": row["kind"], "source": row["source"],
                                "sources": len(row["sources"]), "bucket": row["bucket"], "held": outcome == "held",
                                "dist_atr": row["dist_atr"]})
            if not chance:
                continue
            rnd = random.Random(zlib.crc32(f"{t[i]}|{row['kind']}|{c[i]:.4f}".encode()))
            pz = _placebo(row, lad, rnd)
            out.append({"skip": True, "side": row["kind"], "date": t[i], "placed": pz is not None})
            if pz:
                ev = nxt(pz[0], pz[1], row["kind"], i)
                if ev:
                    j, outcome = ev
                    key = (row["kind"], "random", j)
                    if key not in seen:
                        seen.add(key)
                        out.append({"date": t[j], "seen": t[i], "side": row["kind"], "source": "random", "placebo": True,
                                    "sources": 0, "bucket": None, "held": outcome == "held", "dist_atr": round(pz[2], 2)})
    return out


def _rate(rows):
    return {"n": len(rows), "held_pct": _r(100 * sum(r["held"] for r in rows) / len(rows)) if rows else None}


def summarize_levels(rows: list[dict]) -> dict:
    out = {}
    tries = [r for r in rows if r.get("skip")]
    rows = [r for r in rows if not r.get("skip")]
    for side in ("support", "resistance"):
        every = [r for r in rows if r["side"] == side]
        sub = [r for r in every if not r.get("placebo")]
        rand = [r for r in every if r.get("placebo")]
        half = lambda rs: {"first_half": [r for r in rs if r["date"] < LEVEL_SPLIT], "second_half": [r for r in rs if r["date"] >= LEVEL_SPLIT]}
        halves, rhalves = half(sub), half(rand)
        blk = {"all": _rate(sub), "halves": {k: _rate(v) for k, v in halves.items()}, "buckets": {}, "sources": {}}
        for b in BUCKETS_L:
            bb = [r for r in sub if r["bucket"] == b]
            blk["buckets"][b] = dict(_rate(bb), **{k: _rate([r for r in v if r["bucket"] == b]) for k, v in halves.items()})
        for src in sorted({r["source"] for r in sub}):
            blk["sources"][src] = dict(_rate([r for r in sub if r["source"] == src]),
                                       **{k: _rate([r for r in v if r["source"] == src]) for k, v in halves.items()})
        blk["confluence"] = {"one kind": _rate([r for r in sub if r.get("sources", 1) == 1]),
                             "2+ kinds": _rate([r for r in sub if r.get("sources", 1) >= 2])}
        # 1) does a zone's own record predict its next test?
        verdicts = []
        for k in halves:
            strong = blk["buckets"][BUCKETS_L[4]][k]
            weak = blk["buckets"][BUCKETS_L[2]][k]
            al = blk["halves"][k]
            if strong["n"] < LEVEL_MIN_N or weak["n"] < LEVEL_MIN_N:
                verdicts.append(None)
                continue
            verdicts.append(strong["held_pct"] - weak["held_pct"] >= LEVEL_EDGE_WEAK and strong["held_pct"] - al["held_pct"] >= LEVEL_EDGE_ALL)
        blk["passed"] = None if None in verdicts else all(verdicts)
        # 2) do real zones hold more often than random prices at the same distance?
        if rand:
            blk["random"] = dict(_rate(rand), halves={k: _rate(v) for k, v in rhalves.items()})
            blk["bands"] = []
            for k, (a, b) in enumerate(DIST_BANDS):
                ra = [r for r in sub if _band(r.get("dist_atr", 0)) == k]
                rr = [r for r in rand if _band(r.get("dist_atr", 0)) == k]
                blk["bands"].append({"band": f"{a:g}-{b:g}" if b < 1e8 else f"{a:g}+", "real": _rate(ra), "random": _rate(rr)})
            cv, edges = [], {}
            for k in halves:
                num = den = 0.0
                for bi in range(len(DIST_BANDS)):
                    ra = [r for r in halves[k] if _band(r.get("dist_atr", 0)) == bi]
                    rr = [r for r in rhalves[k] if _band(r.get("dist_atr", 0)) == bi]
                    if len(ra) < MIN_BAND or len(rr) < MIN_BAND:
                        continue
                    diff = 100 * (sum(r["held"] for r in ra) / len(ra) - sum(r["held"] for r in rr) / len(rr))
                    num += len(ra) * diff
                    den += len(ra)
                edges[k] = _r(num / den) if den else None
                if blk["halves"][k]["n"] < LEVEL_MIN_N or blk["random"]["halves"][k]["n"] < LEVEL_MIN_N or edges[k] is None:
                    cv.append(None)
                else:
                    cv.append(edges[k] >= CHANCE_EDGE)
            blk["edge_by_half"] = edges
            num = den = 0.0
            for bd in blk["bands"]:
                if bd["real"]["n"] >= MIN_BAND and bd["random"]["n"] >= MIN_BAND:
                    num += bd["real"]["n"] * (bd["real"]["held_pct"] - bd["random"]["held_pct"])
                    den += bd["real"]["n"]
            blk["edge_pts"] = _r(num / den) if den else None
            blk["beats_chance"] = None if None in cv else all(cv)
        else:
            blk["random"], blk["beats_chance"], blk["edge_pts"], blk["bands"], blk["edge_by_half"] = None, None, None, [], {}
        tr_side = [r for r in tries if r["side"] == side]
        blk["random_placed"] = {"tried": len(tr_side), "placed": sum(r["placed"] for r in tr_side),
                                "pct": _r(100 * sum(r["placed"] for r in tr_side) / len(tr_side)) if tr_side else None}
        out[side] = blk
    return out


def level_track(market: str) -> Optional[dict]:
    hit = store.get_company("LEVELS_TRACK::IN")
    if not hit:
        return None
    t = hit[1]
    if t.get("rules_version") != LEVEL_RULES_VERSION:
        return {"stale": True, "built": t.get("built"), "rules_version": t.get("rules_version")}
    return {"built": t.get("built"), "universe": t.get("universe_label"), "stocks": t.get("stocks"), "tests": t.get("tests"),
            "result": t.get("result"), "pass_test": t.get("pass_test"), "chance_test": t.get("chance_test"), "note": t.get("note"),
            "has_chance": t.get("test_version", 1) >= TEST_VERSION, "skipped": t.get("skipped"), "split": t.get("split"),
            "market_note": "Tested on NSE stocks only; not tested on US stocks." if market == "US" else None}


# ------------------------------------------------------------------ market layer and value floor
MARKET_INDEX = {"IN": ("^NSEI", "NIFTY 50"), "US": ("^GSPC", "S&P 500")}


def market_check(market: str, bars: list[dict]) -> dict:
    tick, name = MARKET_INDEX.get(market, MARKET_INDEX["IN"])
    out = {"ticker": tick, "name": name}
    try:
        mb = _sector_bars(tick)
    except Exception as e:  # noqa: BLE001
        out["error"] = f"could not load {tick}: {e}"
        return out
    if not mb or len(mb) <= LOOK:
        out["error"] = f"no price history for {tick}"
        return out
    mc = [b["c"] for b in mb]
    dd = -drawdowns(mc)[-1] * 100
    s50, s200 = technicals.sma(mc, 50)[-1], technicals.sma(mc, 200)[-1]
    out.update({"last_date": mb[-1]["t"], "fall_pct": _r(dd), "stage": stage(dd), "above50": mc[-1] > s50 if s50 else None,
                "above200": mc[-1] > s200 if s200 else None, "ret_3m": _r(_ret(mb)), "beta": beta(bars, mb)})
    return out


def layers_answer(stock_fall: float, sector_fall: Optional[float], market_fall: Optional[float]) -> str:
    """Fixed wording from the same bands as the stage: 10%+ = falling."""
    if stock_fall < 10:
        return f"The stock is {stock_fall:.1f}% off its high: not a 10%+ fall."
    if sector_fall is None and market_fall is None:
        return "No sector or market data to compare with."
    mk = market_fall is not None and market_fall >= 10
    sc = sector_fall is not None and sector_fall >= 10
    if mk and sc:
        return "Broad fall: the market and the sector are both 10%+ off their highs too."
    if sc:
        return "Sector fall: the sector is 10%+ off its high, the market is not."
    if mk:
        return "Market fall: the market is 10%+ off its high; the sector less so."
    if sector_fall is not None and sector_fall < 5 and (market_fall is None or market_fall < 5):
        return "Mostly this stock: the sector and the market are within 5% of their highs."
    return "Mostly this stock: the sector and the market are down less than 10%."


def value_floor(rep: dict) -> dict:
    """Price ranges where today's P/E would sit in each band of its own history, with the backtested record."""
    ent = (rep.get("analysis") or {}).get("entry") or {}
    val = (ent.get("checks") or {}).get("value") or {}
    edges = (ent.get("levels") or {}).get("value_edges")
    out = {"state": val.get("state"), "pe_state": val.get("pe_state"), "fv_state": val.get("fv_state"),
           "pe_percentile": val.get("pe_percentile"), "ranges": None}
    if not edges:
        out["note"] = "Not enough P/E history (about 3 years needed), or no positive earnings."
        return out
    out["ranges"] = [{"state": "Cheap", "below": edges["cheap"]},
                     {"state": "Fair", "from": edges["cheap"], "to": edges["fair"]},
                     {"state": "Full", "from": edges["fair"], "to": edges["full"]},
                     {"state": "Expensive", "above": edges["full"]}]
    out["how"] = ("Price at which today's P/E would be at the 30th, 60th and 85th percentile of its own P/E history, "
                  "at today's earnings. It moves when earnings change.")
    tr = ent.get("track") or {}
    g = ent.get("group")
    bs = ((tr.get("by_state_groups") or {}).get(g) or {}) if g else {}
    if not bs:
        bs = tr.get("by_state") or {}
    if bs:
        rec = {}
        for st in ("Cheap", "Fair", "Full", "Expensive"):
            b = bs.get(st) or {}
            rec[st] = {k: (b.get(k) or {}).get("avg") for k in ("p12", "p24", "p36")}
            rec[st]["n"] = b.get("n")
        out["record"] = rec
        out["record_scope"] = ((tr.get("groups") or {}).get(g) if g and tr.get("by_state_groups") else tr.get("universe_label"))
        out["record_built"] = tr.get("built")
        out["value_test"] = tr.get("value_test")
        out["record_basis"] = ("The record groups each past month by its P/E state only (past fair values are not "
                               "available), so it matches the P/E ranges above, not the entry card's combined state.")
    else:
        out["record"] = None
        out["record_note"] = ("Not tested on this install yet." if rep.get("market") != "US"
                              else "The value record is from NSE stocks only; not tested on US stocks.")
    return out


# ------------------------------------------------------------------ build
def build(rep: dict, bars: list[dict], refresh: bool = False) -> dict:
    sym = rep.get("symbol")
    key = f"PRICEMAP::{sym}"
    hit = store.get_company(key)
    lt = store.get_company("LEVELS_TRACK::IN")
    et = store.get_company("ENTRY_TRACK::IN")
    stamp = f"{lt[0] if lt else 0}:{et[0] if et else 0}"     # a new backtest result refreshes the map
    if (hit and not refresh and time.time() - hit[0] < TTL and hit[1].get("v") == VERSION
            and hit[1].get("last") == bars[-1]["t"] and hit[1].get("stamp") == stamp):
        return hit[1]["data"]
    c = [b["c"] for b in bars]
    if len(c) < LOOK + 30:
        raise ValueError(f"Only {len(c)} sessions of price history; the price map needs at least {LOOK + 30}.")
    hi = rolling_high(c)
    dd = c[-1] / hi[-1] - 1
    i_hi = max(range(len(c) - LOOK, len(c)), key=lambda i: c[i])
    fall = -dd
    where = {"price": round(c[-1], 2), "date": bars[-1]["t"], "change_pct": _r((c[-1] / c[-2] - 1) * 100, 2),
             "high": round(c[i_hi], 2), "high_date": bars[i_hi]["t"], "fall_pct": _r(fall * 100),
             "days_since_high": len(c) - 1 - i_hi, "stage": stage(fall * 100)}
    sector, sb, peer_bars = sector_check(rep, bars, fall)
    mkt = market_check(rep.get("market") or "IN", bars)
    sec_fall = (sector.get("index") or {}).get("fall_pct")
    if sec_fall is None:
        sec_fall = sector.get("peer_median_fall")
    sector["layers"] = layers_answer(fall * 100, sec_fall, mkt.get("fall_pct"))
    depth = max(fall, FALL_MIN)
    own = fall_cases(bars, depth) if fall >= FALL_MIN else []
    pooled = []
    if fall >= FALL_MIN:
        for s, b in peer_bars.items():
            pooled += fall_cases(b, depth, who=s)
    further = {"applies": fall >= FALL_MIN, "depth_pct": _r(depth * 100),
               "since": bars[LOOK]["t"], "own": summarize_cases(own), "own_cases": own[-12:],
               "peers": summarize_cases(pooled), "peer_count": len(peer_bars),
               "range_1m": month_range(c)}
    book = SignalBook(bars, sb)
    signals = []
    for k, name in SIGNALS:
        on = book.on(k, len(c) - 1)
        signals.append({"key": k, "name": name, "rule": SIGNAL_RULES[k], "on": on, "state": book.state_text(k),
                        "record": book.record(k) if on is not None or k != "sector_up" else {"n": 0, "verdict": "too_few"}})
    data = {"symbol": sym, "name": (rep.get("company") or {}).get("name"), "market": rep.get("market") or "IN",
            "currency": (rep.get("currency") or {}).get("symbol") or "₹", "where": where,
            "levels": level_ladder(bars), "level_track": level_track(rep.get("market") or "IN"),
            "market": mkt, "value": value_floor(rep), "further": further, "sector": sector, "signals": signals,
            "business": business(rep), "rules": __doc__.split("\n\n", 2)[2].strip(), "version": VERSION,
            "bars_from": bars[0]["t"], "bars_n": len(bars)}
    store.put_company(key, {"v": VERSION, "last": bars[-1]["t"], "stamp": stamp, "data": data})
    return data
