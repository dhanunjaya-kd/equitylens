"""Price map: where buyers and sellers stepped in before, how far falls like this one went,
whether the sector is falling too, and which turn signals are on, each with its own record.

Everything here is measured on real daily candles (the stock's, its sector index's and its
peers'). Nothing is forecast. Every rule below was fixed before looking at any result and is
not tuned:

  Fall from the high     close vs the highest close of the last 252 sessions (52 weeks).
  Stage                  pullback < 10%  ·  correction 10-20%  ·  bear > 20%.
  Swing levels           a high/low that is the extreme of the 5 bars either side, last 500 bars;
                         pivots within 1.5% of each other are one level ("touches" = pivots in it).
  Other levels           50- and 200-day averages, 52-week high and low, heavy-trading zones
                         (volume by price, last 250 bars, 50 bins, top 20% of bins).
  A test of a level      price comes within 1% of it from the other side.
  Held                   a 3% move away from the level before any close 1% through it, within 20 bars.
  Broken                 a close 1% through it first.  Neither in 20 bars = not counted.
  Further-fall cases     every earlier time the stock first fell this far from its 52-week high;
                         the case ends at the next 52-week high. The fall still in progress is excluded.
  Turn signals           five fixed signals; record = 21-session return after each time a signal
                         switched on while the stock was 10%+ below its 52-week high (events at
                         least 10 sessions apart), against every day in such a fall.
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

VERSION = 1
LOOK = 252            # 52-week high
SWING_K = 5
SWING_BARS = 500
CLUSTER = 0.015
NEAR = 0.01
BOUNCE = 0.03
RESOLVE = 20
HVN_BINS = 50
HVN_TOP = 0.80
FALL_MIN = 0.05       # the further-fall section needs at least a 5% fall
IN_A_FALL = 0.10      # signal records are measured during falls of 10%+
FWD = 21              # "a month later"
GAP = 10              # signal events at least 10 sessions apart
MIN_CASES = 10
CLEAR_EDGE = 5.0      # points vs the baseline before a signal is called better or worse
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


# ------------------------------------------------------------------ levels
def pivots(h, l, k=SWING_K, bars=SWING_BARS):
    n = len(h)
    hi, lo = [], []
    for i in range(max(k, n - bars), n - k):
        if h[i] == max(h[i - k:i + k + 1]):
            hi.append((i, h[i]))
        if l[i] == min(l[i - k:i + k + 1]):
            lo.append((i, l[i]))
    return hi, lo


def cluster(points: list[tuple[int, float]], tol: float = CLUSTER) -> list[dict]:
    """Greedy: sort by price, join a pivot to the current group while within tol of the group's mean."""
    groups: list[list[tuple[int, float]]] = []
    for p in sorted(points, key=lambda x: x[1]):
        if groups:
            g = groups[-1]
            m = sum(v for _, v in g) / len(g)
            if abs(p[1] / m - 1) <= tol:
                g.append(p)
                continue
        groups.append([p])
    out = []
    for g in groups:
        out.append({"price": sum(v for _, v in g) / len(g), "touches": len(g),
                    "first": min(i for i, _ in g), "last": max(i for i, _ in g)})
    return out


def tests(h, l, c, level, side: str, start: int, end: Optional[int] = None) -> dict:
    """Count tests of a level and how they ended. `level` is a number or a list (moving average).

    side 'support': price comes down to within 1% of it from above.
    side 'resistance': price comes up to within 1% of it from below.
    Uses only bars after `start`; each test is resolved before the next one is looked for."""
    end = len(c) if end is None else end
    lv = (lambda i: level[i]) if isinstance(level, list) else (lambda i: level)
    held = broken = 0
    dates = []
    i = max(start, 1)
    while i < end:
        L, Lp = lv(i), lv(i - 1)
        if L is None or Lp is None:
            i += 1
            continue
        if side == "support":
            began = l[i] <= L * (1 + NEAR) and c[i - 1] > Lp * (1 + NEAR)
        else:
            began = h[i] >= L * (1 - NEAR) and c[i - 1] < Lp * (1 - NEAR)
        if not began:
            i += 1
            continue
        outcome, j = None, i
        for j in range(i, min(end, i + RESOLVE)):
            Lj = lv(j)
            if Lj is None:
                continue
            if side == "support":
                if c[j] < Lj * (1 - NEAR):
                    outcome = "broken"
                elif h[j] >= L * (1 + BOUNCE):
                    outcome = "held"
            else:
                if c[j] > Lj * (1 + NEAR):
                    outcome = "broken"
                elif l[j] <= L * (1 - BOUNCE):
                    outcome = "held"
            if outcome:
                break
        if outcome == "held":
            held += 1
        elif outcome == "broken":
            broken += 1
        if outcome:
            dates.append((i, outcome))
            i = j + 1
        else:
            i += RESOLVE
    return {"held": held, "broken": broken, "tests": held + broken, "events": dates}


def volume_zones(h, l, c, v, bars=250, bins=HVN_BINS):
    n = len(c)
    s = max(0, n - bars)
    lo, hi = min(l[s:]), max(h[s:])
    if hi <= lo or not any(v[s:]):
        return []
    w = (hi - lo) / bins
    vol = [0.0] * bins
    for i in range(s, n):
        tp = (h[i] + l[i] + c[i]) / 3
        vol[min(bins - 1, int((tp - lo) / w))] += v[i] or 0
    cut = _pct(vol, HVN_TOP)
    return [(lo + k * w, lo + (k + 1) * w, vol[k]) for k in range(bins) if vol[k] >= cut and vol[k] > 0]


def _month(t: str) -> str:
    d = dt.date.fromisoformat(t)
    return d.strftime("%b %Y")


def level_ladder(bars: list[dict]) -> dict:
    t = [b["t"] for b in bars]
    h = [b["h"] for b in bars]
    l = [b["l"] for b in bars]
    c = [b["c"] for b in bars]
    v = [b.get("v") or 0 for b in bars]
    n, px = len(c), c[-1]
    win0 = max(1, n - SWING_BARS)
    cands = []
    hi_p, lo_p = pivots(h, l)
    for g in cluster(hi_p):
        cands.append({"price": g["price"], "what": f"Swing high from {_month(t[g['last']])}" + (f" · {g['touches']} touches" if g["touches"] > 1 else ""),
                      "touches": g["touches"], "start": g["first"] + SWING_K + 1, "src": "swing"})
    for g in cluster(lo_p):
        cands.append({"price": g["price"], "what": f"Swing low from {_month(t[g['last']])}" + (f" · {g['touches']} touches" if g["touches"] > 1 else ""),
                      "touches": g["touches"], "start": g["first"] + SWING_K + 1, "src": "swing"})
    s50, s200 = technicals.sma(c, 50), technicals.sma(c, 200)
    for name, ma in (("50-day average", s50), ("200-day average", s200)):
        if ma[-1] is None:
            continue
        slope = "rising" if ma[-21] is not None and ma[-1] > ma[-21] else "falling"
        cands.append({"price": ma[-1], "what": f"{name}, {slope}", "touches": 0, "start": win0, "src": "ma", "ma": ma})
    s = max(0, n - LOOK)
    i_hi = max(range(s, n), key=lambda i: h[i])
    i_lo = min(range(s, n), key=lambda i: l[i])
    cands.append({"price": h[i_hi], "what": f"52-week high ({t[i_hi]})", "touches": 1, "start": i_hi + 1, "src": "52w"})
    cands.append({"price": l[i_lo], "what": f"52-week low ({t[i_lo]})", "touches": 1, "start": i_lo + 1, "src": "52w"})
    zones = volume_zones(h, l, c, v)

    def in_zone(p):
        return any(a <= p <= b for a, b, _ in zones)

    # merge candidates within 1.5% (keep the one with the most touches, join the labels)
    cands.sort(key=lambda x: x["price"])
    merged: list[dict] = []
    for cd in cands:
        if merged and abs(cd["price"] / merged[-1]["price"] - 1) <= CLUSTER and "ma" not in cd and "ma" not in merged[-1]:
            m = merged[-1]
            keep, other = (m, cd) if m["touches"] >= cd["touches"] else (cd, m)
            keep = dict(keep)
            keep["what"] = keep["what"] + " · " + other["what"]
            keep["start"] = min(m["start"], cd["start"])
            keep["touches"] = m["touches"] + cd["touches"]
            merged[-1] = keep
        else:
            merged.append(cd)
    for z in zones:  # heavy-trading zone with nothing else near it becomes its own level
        mid = (z[0] + z[1]) / 2
        if not any(abs(m["price"] / mid - 1) <= CLUSTER for m in merged):
            merged.append({"price": mid, "what": "Heavy-trading zone (volume by price)", "touches": 0, "start": win0, "src": "volume"})

    out_r, out_s = [], []
    for m in merged:
        if abs(m["price"] / px - 1) < 0.003:
            continue
        side = "resistance" if m["price"] > px else "support"
        ts = tests(h, l, c, m.get("ma", m["price"]), side, max(m["start"], win0))
        row = {"kind": side, "price": round(m["price"], 2), "dist_pct": round((m["price"] / px - 1) * 100, 1),
               "what": m["what"] + (" · heavy-trading zone" if in_zone(m["price"]) and m["src"] != "volume" else ""),
               "held": ts["held"], "tests": ts["tests"], "source": m["src"],
               "last_test": t[ts["events"][-1][0]] if ts["events"] else None}
        (out_r if side == "resistance" else out_s).append(row)
    out_r.sort(key=lambda x: x["price"])
    out_s.sort(key=lambda x: -x["price"])
    return {"price": round(px, 2), "resistance": out_r[:3], "support": out_s[:3],
            "zones": [{"from": round(a, 2), "to": round(b, 2)} for a, b, _ in zones]}


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
            out.update({"up_pct": _r(100 * ups / len(events), 0), "median_pct": _r(100 * _pct([x for _, x in events], 0.5))})
            d = out["up_pct"] - (out["base_up_pct"] or 0)
            out["verdict"] = "better" if d >= CLEAR_EDGE else ("worse" if d <= -CLEAR_EDGE else "same")
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
def business(rep: dict) -> dict:
    a = rep.get("analysis") or {}
    sc = a.get("scores") or {}
    plus = list((a.get("strengths") or [])[:5])
    minus = [f["text"] for f in (a.get("flags") or []) if f.get("severity") in ("high", "medium")][:5]
    val = ((a.get("entry") or {}).get("checks") or {}).get("value") or {}
    vt = (val.get("text") or "").split(" Shown for information")[0].rstrip(".")
    if val.get("state") in ("Full", "Expensive"):
        minus.append(f"Price vs value: {vt}")
    elif val.get("state") in ("Cheap", "Fair") and vt:
        plus.append(f"Price vs value: {vt}")
    names = {"growth": "Growth", "quality": "Quality", "strength": "Balance sheet", "cash": "Cash flow"}
    for k, lab in names.items():
        x = sc.get(k)
        if x is not None and x < 40:
            minus.append(f"{lab} score {x:.0f}/100 (weak)")
    return {"score": sc.get("business"), "overall": sc.get("overall"), "plus": plus, "minus": minus,
            "verdict": (a.get("verdict") or {}).get("label")}


# ------------------------------------------------------------------ build
def build(rep: dict, bars: list[dict], refresh: bool = False) -> dict:
    sym = rep.get("symbol")
    key = f"PRICEMAP::{sym}"
    hit = store.get_company(key)
    if hit and not refresh and time.time() - hit[0] < TTL and hit[1].get("v") == VERSION and hit[1].get("last") == bars[-1]["t"]:
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
            "levels": level_ladder(bars), "further": further, "sector": sector, "signals": signals,
            "business": business(rep), "rules": __doc__.split("\n\n", 2)[2].strip(), "version": VERSION,
            "bars_from": bars[0]["t"], "bars_n": len(bars)}
    store.put_company(key, {"v": VERSION, "last": bars[-1]["t"], "data": data})
    return data
