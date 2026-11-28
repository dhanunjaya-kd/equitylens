"""Indicators and scanners on daily prices (the same daily bars Market Movers downloads).

Every scanner is one written rule (RULES below, shown in the app word for word). Nothing is estimated:
a stock either meets the rule on a day or it does not. Bars are Yahoo daily OHLCV as Market Movers loads
them; a stock needs enough history for a rule (e.g. 252 sessions for 52-week rules) or the rule is skipped.

Tested record: for every stock and every past session (from session 253 of its ~2-year history, so that every
rule has its full look-back), each scanner is checked as of that day's close, and the stock's move 5, 20 and 60
sessions later (close to close) is collected. The same moves for every stock-day in the same window are the
baseline ("any stock, any day"). Limits, shown in the app: only stocks in today's list (survivorship), about one
year of signals, no costs, prices not adjusted for every corporate action.
"""
from __future__ import annotations

import math
from array import array
from datetime import date
from typing import Optional

HORIZONS = (5, 20, 60)
START = 252                     # first session index checked in the tested record

GROUPS = [
    ("price", "Price patterns", ["vcp", "inside_bar", "nr7", "mini_coil", "wtc", "flag", "double_bottom", "cup_handle", "flat_base"]),
    ("volume", "Volume", ["lowest_volume", "highest_volume", "pocket_pivot", "bull_snort"]),
    ("trend", "Trend and strength", ["minervini", "stage2", "ti65", "rs_first", "leader"]),
    ("results", "Results", ["gap_up"]),
]
RULES = {
    "vcp": ("VCP", "Tightening into a pivot",
            "Close above its 50-day average, which is above the 200-day; the high-low depth of the last three 15-session "
            "windows shrinks each time (oldest deepest) and the latest is 8% or less; 10-day average volume below the "
            "50-day average; close within 15% of the 52-week high."),
    "inside_bar": ("Inside bar", "Pauses inside a big candle", "Today's high is not above yesterday's high and today's low is not below yesterday's low."),
    "nr7": ("Tight range (NR7)", "Narrowest day in 7", "Today's high-low range is the smallest of the last 7 sessions."),
    "mini_coil": ("Mini coil", "Two days inside one candle", "Today and yesterday both trade inside the high-low range of the session before them."),
    "wtc": ("3 weeks tight", "Three quiet weekly closes",
            "The last three weekly closes (this week counts as of today) are within 1.5% of each other, and the close is above the 50-day average."),
    "flag": ("Flag", "Pole, then a tight pause",
             "A rise of 25% or more into a high made 3 to 25 sessions ago (from the lowest low of the 15 sessions before that high); "
             "since then the price has not fallen more than 12% below that high nor gone 2% above it, and the close is within 8% of it."),
    "double_bottom": ("W double bottom", "Two lows near the pivot",
                      "A low 20-60 sessions ago, a second low at least 10 sessions later within 3% of it, a peak in between at least "
                      "8% above the lows, and today's close within -5% to +3% of that peak."),
    "cup_handle": ("Cup and handle", "Base plus a shallow handle",
                   "A high 35-150 sessions ago (left side), a fall of 12-40% from it, a recovery to within 5% of it in the last 20 "
                   "sessions (right side), then at least 4 sessions of handle that dip no more than 12% and stay in the upper half of "
                   "the cup; close within 5% of the right-side high and not above it by more than 2%."),
    "flat_base": ("Flat base", "Sideways after a run-up",
                  "The last 25 sessions trade within 15% (high to low), the stock rose 20% or more in the 60 sessions before them, and "
                  "the close is in the top third of the base."),
    "lowest_volume": ("Lowest volume", "Quietest day in 50", "Today's volume is the lowest of the last 50 sessions."),
    "highest_volume": ("Highest volume", "Heaviest day in a year", "Today's volume is the highest of the last 252 sessions."),
    "pocket_pivot": ("Pocket pivot", "Buyers showing on volume",
                     "An up close on volume above the biggest down-day volume of the previous 10 sessions, with the close at or above the 50-day average."),
    "bull_snort": ("Bull snort", "Big up day on volume",
                   "Close 4% or more above yesterday's close, volume above yesterday's and at least 1.5× the 50-day average, close in the top 30% of the day's range."),
    "minervini": ("Minervini trend", "Stage-2 trend check",
                  "All 8 of Mark Minervini's trend-template rules: close above the 150- and 200-day averages; 150-day above 200-day; "
                  "200-day higher than 22 sessions ago; 50-day above 150- and 200-day; close above the 50-day; close 30%+ above the "
                  "52-week low; close within 25% of the 52-week high; RS rating 70 or more."),
    "stage2": ("Stage 2", "Weekly uptrend",
               "Weekly close above its 30-week average, and that average higher than 4 weeks ago (Stan Weinstein's stage 2)."),
    "ti65": ("TI65 strong", "Steady trend strength", "7-day average close divided by the 65-day average close is 1.05 or more (Pradeep Bonde's trend intensity)."),
    "rs_first": ("RS high before price", "RS leads, price follows",
                 "The stock's price relative to the market index is at its highest of the last 252 sessions while the price itself is more than 2% below its own 252-session high."),
    "leader": ("Leader", "Strongest stocks",
               "RS rating 90 or more, close within 25% of the 52-week high, TI65 at least 1.0 and close above the 50-day average."),
    "gap_up": ("Gap up on volume", "Opens 4%+ up on 2× volume",
               "Opens 4% or more above yesterday's close, closes at least 4% above it, on volume at least 2× the 50-day average. "
               "Marked 'results' when the company's results were in the 2 days before (from the results calendar)."),
}
RS_NEEDED = ("minervini", "leader")
INDICATORS = {
    "adr": "ADR %: average of (high ÷ low − 1) over the last 20 sessions.",
    "rs": "RS rating 1-99: rank of 12-month performance among the stocks in this list, weighting the last 3 months double "
          "(40% last 3 months, 20% each earlier quarter), like IBD's rating. 99 = stronger than 99% of them.",
    "ti65": "TI65: 7-day average close ÷ 65-day average close (Pradeep Bonde). Above 1 = rising trend; 1.05+ = strong.",
    "lin": "Linearity: how straight the last 65 closes rise (R² of a straight line through log prices, 0 to 1); 0 when the line slopes down.",
    "turn20": "Turnover: average of close × volume over the last 20 sessions.",
}


# ------------------------------------------------------------------ fast window queries
class _Sparse:
    """O(1) max / min (with position) over any window of a list."""

    def __init__(self, xs: list[float], op):
        self.op = op
        n = len(xs)
        self.t = [list(range(n))]
        j = 1
        while (1 << j) <= n:
            prev, half = self.t[-1], 1 << (j - 1)
            row = []
            for i in range(n - (1 << j) + 1):
                a, b = prev[i], prev[i + half]
                row.append(a if op(xs[a], xs[b]) else b)
            self.t.append(row)
            j += 1
        self.xs = xs

    def idx(self, lo: int, hi: int) -> int:          # inclusive window lo..hi
        k = (hi - lo + 1).bit_length() - 1
        a, b = self.t[k][lo], self.t[k][hi - (1 << k) + 1]
        return a if self.op(self.xs[a], self.xs[b]) else b

    def val(self, lo: int, hi: int) -> float:
        return self.xs[self.idx(lo, hi)]


def _sma(xs: list[float], n: int) -> list[Optional[float]]:
    out: list[Optional[float]] = [None] * len(xs)
    s = 0.0
    for i, x in enumerate(xs):
        s += x
        if i >= n:
            s -= xs[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def _ge(a, b):
    return a >= b


def _le(a, b):
    return a <= b


class Series:
    def __init__(self, bars: list[dict], idx_close: Optional[dict] = None):
        self.t = [b["t"] for b in bars]
        self.o = [float(b["o"]) for b in bars]
        self.h = [float(b["h"]) for b in bars]
        self.l = [float(b["l"]) for b in bars]
        self.c = [float(b["c"]) for b in bars]
        self.v = [float(b.get("v") or 0) for b in bars]
        self.n = len(bars)
        self.hi = _Sparse(self.h, _ge)
        self.lo = _Sparse(self.l, _le)
        self.vmax = _Sparse(self.v, _ge)
        self.vmin = _Sparse([v if v > 0 else float("inf") for v in self.v], _le)
        self.rng = [h - l for h, l in zip(self.h, self.l)]
        self.rmin = _Sparse(self.rng, _le)
        self.sma = {k: _sma(self.c, k) for k in (7, 10, 50, 65, 150, 200)}
        self.vsma50 = _sma(self.v, 50)
        self.vsma10 = _sma(self.v, 10)
        # weekly closes: index of the last bar of each ISO week up to i
        wk = [date.fromisoformat(x[:10]).isocalendar()[:2] for x in self.t]
        self.week = wk
        self.week_end = [i for i in range(self.n) if i == self.n - 1 or wk[i + 1] != wk[i]]
        # relative-strength line vs the index
        self.rsl: Optional[list[Optional[float]]] = None
        if idx_close:
            self.rsl = [(c / idx_close[t[:10]]) if idx_close.get(t[:10]) else None for c, t in zip(self.c, self.t)]
            self.rsl_max = _Sparse([x if x is not None else float("-inf") for x in self.rsl], _ge)
            cnt, k = [], 0
            for x in self.rsl:
                k += x is not None
                cnt.append(k)
            self.rsl_cnt = cnt

    # weekly closes as of day i (the current week counts with day i as its close)
    def weekly(self, i: int, k: int) -> list[float]:
        out = [self.c[i]]
        for j in reversed(self.week_end):
            if j < i and self.week[j] != self.week[i]:
                out.append(self.c[j])
                if len(out) >= k:
                    break
        return out[::-1]


def _wperf(s: Series, i: int) -> Optional[float]:
    if i < 252:
        return None
    c = s.c
    r = lambda k: c[i] / c[i - k] - 1     # noqa: E731
    return 0.4 * r(63) + 0.2 * r(126) + 0.2 * r(189) + 0.2 * r(252)


def linearity(s: Series, i: int, n: int = 65) -> Optional[float]:
    if i < n - 1:
        return None
    ys = [math.log(x) for x in s.c[i - n + 1:i + 1] if x > 0]
    if len(ys) < n:
        return None
    mx = (n - 1) / 2
    my = sum(ys) / n
    sxy = sum((k - mx) * (y - my) for k, y in enumerate(ys))
    sxx = sum((k - mx) ** 2 for k in range(n))
    syy = sum((y - my) ** 2 for y in ys)
    if sxy <= 0 or syy == 0:
        return 0.0
    return round(sxy * sxy / (sxx * syy), 2)


# ------------------------------------------------------------------ the rules (as of day i's close)
def check(s: Series, i: int) -> set[str]:
    """Scanner tags true at day i (RS-dependent ones are returned as '<name>_pre': all conditions but RS)."""
    h, l, c, o, v = s.h, s.l, s.c, s.o, s.v
    out: set[str] = set()
    if i < 2:
        return out
    sm = s.sma
    s50, s200 = sm[50][i], sm[200][i]
    if h[i] <= h[i - 1] and l[i] >= l[i - 1]:
        out.add("inside_bar")
    if i >= 6 and s.rng[i] <= s.rmin.val(i - 6, i):
        out.add("nr7")
    if h[i] <= h[i - 2] and l[i] >= l[i - 2] and h[i - 1] <= h[i - 2] and l[i - 1] >= l[i - 2]:
        out.add("mini_coil")
    if s50 and c[i] > s50:
        w = s.weekly(i, 3)
        if len(w) == 3 and max(w) / min(w) - 1 <= 0.015:
            out.add("wtc")
    hi252 = s.hi.val(i - 251, i) if i >= 251 else None
    lo252 = s.lo.val(i - 251, i) if i >= 251 else None
    # VCP
    if i >= 251 and s50 and s200 and c[i] > s50 > s200 and c[i] >= 0.85 * hi252 and s.vsma10[i] and s.vsma50[i] and s.vsma10[i] < s.vsma50[i]:
        d = []
        for k in (2, 1, 0):
            a, b = i - 15 * (k + 1) + 1, i - 15 * k
            mx = s.hi.val(a, b)
            d.append((mx - s.lo.val(a, b)) / mx)
        if d[0] > d[1] > d[2] and d[2] <= 0.08:
            out.add("vcp")
    # Flag
    if i >= 45:
        p = s.hi.idx(i - 25, i - 3)
        P = h[p]
        B = s.lo.val(p - 15, p - 1)
        if B > 0 and P / B - 1 >= 0.25 and s.lo.val(p + 1, i) >= P * 0.88 and s.hi.val(p + 1, i) <= P * 1.02 and c[i] >= P * 0.92:
            out.add("flag")
    # W double bottom
    if i >= 60:
        a = s.lo.idx(i - 60, i - 20)
        if a + 10 <= i - 3:
            b = s.lo.idx(a + 10, i - 3)
            L1, L2 = l[a], l[b]
            if L1 > 0 and abs(L2 / L1 - 1) <= 0.03 and b - a >= 2:
                M = s.hi.val(a + 1, b - 1)
                if M / max(L1, L2) - 1 >= 0.08 and M * 0.95 <= c[i] <= M * 1.03:
                    out.add("double_bottom")
    # Cup and handle
    if i >= 150:
        a = s.hi.idx(i - 150, i - 35)
        H = h[a]
        C = s.lo.val(a, i - 10)
        if H > 0 and 0.12 <= 1 - C / H <= 0.40:
            r = s.hi.idx(i - 20, i)
            if h[r] >= H * 0.95 and r <= i - 4:
                hl = s.lo.val(r, i)
                if 1 - hl / h[r] <= 0.12 and hl >= C + (H - C) / 2 and h[r] * 0.95 <= c[i] <= h[r] * 1.02:
                    out.add("cup_handle")
    # Flat base
    if i >= 85:
        mx, mn = s.hi.val(i - 24, i), s.lo.val(i - 24, i)
        prior = s.lo.val(i - 85, i - 25)
        if mx > 0 and (mx - mn) / mx <= 0.15 and prior > 0 and c[i - 25] / prior - 1 >= 0.20 and c[i] >= mn + (mx - mn) * 2 / 3:
            out.add("flat_base")
    # Volume
    if i >= 49 and v[i] > 0 and v[i] <= s.vmin.val(i - 49, i):
        out.add("lowest_volume")
    if i >= 251 and v[i] > 0 and v[i] >= s.vmax.val(i - 251, i):
        out.add("highest_volume")
    if i >= 11 and c[i] > c[i - 1] and s50 and c[i] >= s50:
        downs = [v[j] for j in range(i - 10, i) if c[j] < c[j - 1]]
        if downs and v[i] > max(downs):
            out.add("pocket_pivot")
    if c[i - 1] > 0 and c[i] / c[i - 1] >= 1.04 and v[i] > v[i - 1] and s.vsma50[i] and v[i] >= 1.5 * s.vsma50[i] \
            and h[i] > l[i] and (c[i] - l[i]) / (h[i] - l[i]) >= 0.7:
        out.add("bull_snort")
    if c[i - 1] > 0 and o[i] >= c[i - 1] * 1.04 and c[i] >= c[i - 1] * 1.04 and s.vsma50[i] and v[i] >= 2 * s.vsma50[i]:
        out.add("gap_up")
    # Trend
    s7, s65 = sm[7][i], sm[65][i]
    if s7 and s65 and s7 / s65 >= 1.05:
        out.add("ti65")
    wk = s.weekly(i, 35)
    if len(wk) >= 35:
        ma = sum(wk[-30:]) / 30
        ma4 = sum(wk[-34:-4]) / 30
        if wk[-1] > ma and ma > ma4:
            out.add("stage2")
    s150 = sm[150][i]
    if i >= 251 and s50 and s150 and s200 and sm[200][i - 22]:
        if (c[i] > s150 and c[i] > s200 and s150 > s200 and s200 > sm[200][i - 22] and s50 > s150 and s50 > s200
                and c[i] > s50 and c[i] >= 1.30 * lo252 and c[i] >= 0.75 * hi252):
            out.add("minervini_pre")
    if i >= 251 and s50 and s7 and s65 and c[i] >= 0.75 * hi252 and s7 / s65 >= 1.0 and c[i] > s50:
        out.add("leader_pre")
    if s.rsl and i >= 251 and s.rsl[i] is not None:
        have = s.rsl_cnt[i] - (s.rsl_cnt[i - 252] if i >= 252 else 0)
        if have >= 200 and s.rsl[i] >= s.rsl_max.val(i - 251, i) and c[i] < 0.98 * hi252:
            out.add("rs_first")
    return out


def indicators(s: Series, i: int) -> dict:
    sm = s.sma
    adr = None
    if i >= 19:
        xs = [s.h[k] / s.l[k] - 1 for k in range(i - 19, i + 1) if s.l[k] > 0]
        adr = round(sum(xs) / len(xs) * 100, 2) if xs else None
    turn = sum(s.c[k] * s.v[k] for k in range(max(0, i - 19), i + 1)) / min(20, i + 1)
    return {"adr": adr, "ti65": round(sm[7][i] / sm[65][i], 3) if sm[7][i] and sm[65][i] else None,
            "lin": linearity(s, i), "turn20": turn, "wperf": _wperf(s, i),
            "vol_x50": round(s.v[i] / s.vsma50[i], 2) if s.vsma50[i] else None}


# ------------------------------------------------------------------ one stock: today + its history
def analyse(bars: list[dict], idx_close: Optional[dict] = None, history: bool = True) -> Optional[dict]:
    if len(bars) < 30:
        return None
    s = Series(bars, idx_close)
    i = s.n - 1
    today = check(s, i)
    out = {"tags": sorted(today), "ind": indicators(s, i), "date": s.t[i][:10]}
    if history:
        ev: dict[str, list] = {}
        base = {k: array("f") for k in HORIZONS}
        wp: dict[str, float] = {}
        pre: dict[str, list] = {"minervini_pre": [], "leader_pre": []}
        for j in range(START, s.n):
            w = _wperf(s, j)
            if w is not None:
                wp[s.t[j][:10]] = w
            fw = {k: (s.c[j + k] / s.c[j] - 1) * 100 for k in HORIZONS if j + k < s.n and s.c[j] > 0}
            if not fw:
                continue
            for k, x in fw.items():
                base[k].append(x)
            for tag in check(s, j):
                if tag.endswith("_pre"):
                    pre[tag].append((s.t[j][:10], fw))
                else:
                    ev.setdefault(tag, []).append(fw)
        out.update(events=ev, base=base, wperf=wp, pre=pre)
    return out


# ------------------------------------------------------------------ across the list
def rs_ratings(wperf: dict[str, Optional[float]]) -> dict[str, int]:
    """symbol -> 1..99 percentile of weighted 12-month performance."""
    xs = sorted((w, s) for s, w in wperf.items() if w is not None)
    n = len(xs)
    return {s: max(1, min(99, int(round((k + 1) / n * 99)))) for k, (w, s) in enumerate(xs)} if n else {}


def _stats(vals) -> Optional[dict]:
    vs = sorted(vals)
    n = len(vs)
    if not n:
        return None
    med = vs[n // 2] if n % 2 else (vs[n // 2 - 1] + vs[n // 2]) / 2
    return {"n": n, "mean": round(sum(vs) / n, 2), "median": round(med, 2), "win": round(sum(1 for x in vs if x > 0) / n * 100, 1)}


class Record:
    """Collects every stock's signals and finishes the tested record (incl. RS-based scanners, ranked per day)."""

    def __init__(self):
        self.ev: dict[str, dict[int, array]] = {}
        self.base = {k: array("f") for k in HORIZONS}
        self.wp_by_day: dict[str, list] = {}
        self.pre: dict[str, list] = {"minervini_pre": [], "leader_pre": []}
        self.stocks = 0
        self.first: Optional[str] = None
        self.last: Optional[str] = None

    def add(self, sym: str, a: dict) -> None:
        if not a or "events" not in a:
            return
        self.stocks += 1
        for tag, fws in a["events"].items():
            d = self.ev.setdefault(tag, {k: array("f") for k in HORIZONS})
            for fw in fws:
                for k, x in fw.items():
                    d[k].append(x)
        for k in HORIZONS:
            self.base[k].extend(a["base"][k])
        for day, w in a["wperf"].items():
            self.wp_by_day.setdefault(day, []).append((w, sym))
            self.first = min(self.first or day, day)
            self.last = max(self.last or day, day)
        for tag, rows in a["pre"].items():
            self.pre[tag].extend((sym, day, fw) for day, fw in rows)

    def finish(self) -> dict:
        # RS rating per day, then the RS-based scanners
        rank: dict[tuple, int] = {}
        for day, xs in self.wp_by_day.items():
            xs.sort()
            n = len(xs)
            for k, (w, s) in enumerate(xs):
                rank[(s, day)] = max(1, min(99, int(round((k + 1) / n * 99))))
        for tag, need in (("minervini", 70), ("leader", 90)):
            d = self.ev.setdefault(tag, {k: array("f") for k in HORIZONS})
            for s, day, fw in self.pre[f"{tag}_pre"]:
                if rank.get((s, day), 0) >= need:
                    for k, x in fw.items():
                        d[k].append(x)
        out = {"baseline": {str(k): _stats(self.base[k]) for k in HORIZONS}, "stocks": self.stocks,
               "from": self.first, "to": self.last, "scanners": {}}
        for tag in RULES:
            d = self.ev.get(tag)
            out["scanners"][tag] = {str(k): _stats(d[k]) for k in HORIZONS} if d else None
        return out
