"""Chart patterns, gaps and candlesticks — found on each stock's real candles, by written rules.

How a classic pattern is found (the same code for today's list and for the tested record):
  1. Swing points. A bar is a swing high when its high is above the k bars before it and not below the k bars
     after it (k = 4 daily, 2 weekly); a swing low the same way down. A swing point is only known k bars later,
     so it is used only from then on. Swings smaller than max(1.2 x ATR, 2 %) are ignored, and two highs in a row
     keep the higher one (two lows, the lower one).
  2. Each time a swing point is confirmed, the last 3, 5 or 6 swing points are checked against the rules of each
     pattern (below). Nothing is drawn unless every rule passes.
  3. From then on, bar by bar: a close beyond the breakout line is a breakout; a close beyond the pattern's own
     failure level, or too long without a breakout, ends it.
  4. Tested record: every breakout in the stock's history is followed forward: did the price reach the target
     or the stop first? Only bars after the breakout are used for that, never for finding the pattern.

No pattern is invented: a shape that misses a rule is not shown, not even as "possible".
"""
from __future__ import annotations

import statistics
from datetime import date
from typing import Optional

CFG = {
    "D": {"k": 4, "swing_atr": 1.2, "swing_pct": 2.0, "height_atr": 2.5, "height_pct": 4.0, "min_span": 15, "max_span": 150,
          "db_gap": 15, "low_tol_pct": 3.0, "touch_atr": 0.6, "touch_pct": 1.2, "expire": 30, "recent": 5, "vol_n": 50,
          "vol_x": 1.5, "horizon": 60, "prior": 40, "pad": 10},
    "W": {"k": 2, "swing_atr": 1.0, "swing_pct": 3.0, "height_atr": 2.0, "height_pct": 6.0, "min_span": 8, "max_span": 70,
          "db_gap": 5, "low_tol_pct": 4.0, "touch_atr": 0.5, "touch_pct": 2.0, "expire": 12, "recent": 3, "vol_n": 20,
          "vol_x": 1.3, "horizon": 26, "prior": 20, "pad": 6},
}

NAMES = {
    "double_bottom": "Double bottom", "double_top": "Double top", "triple_bottom": "Triple bottom", "triple_top": "Triple top",
    "inv_head_shoulders": "Inverse head & shoulders", "head_shoulders": "Head & shoulders",
    "asc_triangle": "Ascending triangle", "desc_triangle": "Descending triangle", "sym_triangle": "Symmetrical triangle",
    "rising_wedge": "Rising wedge", "falling_wedge": "Falling wedge", "rectangle": "Rectangle",
    "channel_up": "Rising channel", "channel_down": "Falling channel", "broadening": "Broadening formation",
}

# The written rules, shown on the page ("Learn this pattern")
RULES = {
    "double_bottom": "Two swing lows within 3% of each other (4% weekly) and within 40% of the pattern height, at least 15 sessions "
                     "apart (5 weeks), with a swing high between them. The rise between them is at least max(2.5 x ATR, 4%). "
                     "Price came down into it (it was at or above the middle high in the 40 sessions before). "
                     "Breakout: a close above the middle high. Target: the middle high plus the pattern height. Stop: the lower low.",
    "double_top": "The mirror of a double bottom: two swing highs within 3% (4% weekly), at least 15 sessions apart, after a rise. "
                  "Breakdown: a close below the low between them. Target: that low minus the height. Stop: the higher high.",
    "triple_bottom": "Three swing lows all within the same tolerance as a double bottom, after a fall. Breakout: a close above the "
                     "higher of the two highs between them. Target: that level plus the height. Stop: the lowest low.",
    "triple_top": "Three swing highs within tolerance, after a rise. Breakdown below the lower of the two lows between them.",
    "inv_head_shoulders": "Five swing points low-high-low-high-low after a fall. The middle low (head) is below both shoulders by at "
                          "least max(1 x ATR, 15% of the height); the shoulders are within half the height of each other; the two "
                          "sides take between 0.4x and 2.5x each other's time. Neckline: the line through the two highs. Breakout: a "
                          "close above the neckline. Target: neckline plus the head's depth below it. Stop: the right shoulder.",
    "head_shoulders": "The mirror of the inverse pattern, after a rise. Breakdown: a close below the neckline through the two lows. "
                      "Target: neckline minus the head's height above it. Stop: the right shoulder.",
    "asc_triangle": "At least 5 alternating swing points (2+ highs, 2+ lows) with a flat upper line and a rising lower line; every "
                    "point within max(0.6 x ATR, 1.2%) of its line and every close inside the lines. Breakout: a close above the "
                    "upper line before the lines meet. Target: breakout plus the height at the start. Stop: the last swing low.",
    "desc_triangle": "Like the ascending triangle upside down: a flat lower line and a falling upper line. Breakdown below the lower line.",
    "sym_triangle": "A falling upper line and a rising lower line that meet ahead. Either side can break; the side that breaks decides.",
    "rising_wedge": "Both lines rising and coming together (the gap shrinks by at least a quarter). Usually breaks down: a close below "
                    "the lower line. Target: where the wedge started. Stop: the last swing high.",
    "falling_wedge": "Both lines falling and coming together. Usually breaks up: a close above the upper line. Target: where the wedge "
                     "started (the top of the upper line). Stop: the last swing low.",
    "rectangle": "Flat upper and lower lines (each drifts less than a quarter of the height). Either side can break. Target: the height.",
    "channel_up": "Two parallel rising lines (the gap changes by less than a third). Either side can break. Target: the channel height.",
    "channel_down": "Two parallel falling lines. Either side can break. Target: the channel height.",
    "broadening": "A rising upper line and a falling lower line (the gap grows by at least a third). Either side can break.",
}

BIAS = {"double_bottom": "up", "triple_bottom": "up", "inv_head_shoulders": "up", "asc_triangle": "up", "falling_wedge": "up",
        "double_top": "down", "triple_top": "down", "head_shoulders": "down", "desc_triangle": "down", "rising_wedge": "down",
        "sym_triangle": "both", "rectangle": "both", "channel_up": "both", "channel_down": "both", "broadening": "both"}


# ------------------------------------------------------------------ helpers
def weekly(bars: list[dict]) -> list[dict]:
    """Daily candles -> weekly (ISO week): first open, highest high, lowest low, last close, total volume."""
    out: list[dict] = []
    key = None
    for b in bars:
        d = date.fromisoformat(b["t"][:10])
        k = d.isocalendar()[:2]
        if k != key:
            out.append({"t": b["t"][:10], "o": b["o"], "h": b["h"], "l": b["l"], "c": b["c"], "v": b.get("v") or 0})
            key = k
        else:
            w = out[-1]
            w["h"], w["l"], w["c"], w["v"] = max(w["h"], b["h"]), min(w["l"], b["l"]), b["c"], w["v"] + (b.get("v") or 0)
    return out


def atr(h: list, l: list, c: list, n: int = 14) -> list:
    out, a = [], None
    for i in range(len(c)):
        tr = h[i] - l[i] if i == 0 else max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
        if i < n:
            a = tr if a is None else (a * i + tr) / (i + 1)
        else:
            a = (a * (n - 1) + tr) / n
        out.append(a)
    return out


def _avg_vol(v: list, n: int) -> list:
    """Average volume of the n bars BEFORE each bar (the bar itself not included)."""
    out, s = [], 0.0
    for i in range(len(v)):
        out.append(s / min(i, n) if i else None)
        s += v[i]
        if i >= n:
            s -= v[i - n]
    return out


def _fit(pts: list) -> tuple[float, float]:
    """Least-squares line through (x, y) points -> (slope, intercept)."""
    n = len(pts)
    mx = sum(p[0] for p in pts) / n
    my = sum(p[1] for p in pts) / n
    sxx = sum((p[0] - mx) ** 2 for p in pts)
    if sxx == 0:
        return 0.0, my
    a = sum((p[0] - mx) * (p[1] - my) for p in pts) / sxx
    return a, my - a * mx


class Line:
    def __init__(self, a: float, b: float):
        self.a, self.b = a, b

    def at(self, x: float) -> float:
        return self.a * x + self.b


# ------------------------------------------------------------------ swing points
class Swings:
    def __init__(self, cfg: dict, h: list, l: list, at: list):
        self.cfg, self.h, self.l, self.atr = cfg, h, l, at
        self.piv: list[dict] = []

    def add(self, i: int, kind: str) -> bool:
        """A confirmed swing point at bar i. Returns True when the swing list changed."""
        p = self.h[i] if kind == "H" else self.l[i]
        new = {"i": i, "p": p, "k": kind}
        if self.piv and self.piv[-1]["k"] == kind:
            last = self.piv[-1]
            if (kind == "H" and p > last["p"]) or (kind == "L" and p < last["p"]):
                self.piv[-1] = new
                return True
            return False
        if self.piv:
            need = max(self.cfg["swing_atr"] * self.atr[i], self.cfg["swing_pct"] / 100 * p)
            if abs(p - self.piv[-1]["p"]) < need:
                return False
        self.piv.append(new)
        return True


def _fractals(h: list, l: list, k: int) -> tuple[list, list]:
    n = len(h)
    hi, lo = [False] * n, [False] * n
    for i in range(k, n - k):
        if h[i] > max(h[i - k:i]) and h[i] >= max(h[i + 1:i + k + 1]):
            hi[i] = True
        if l[i] < min(l[i - k:i]) and l[i] <= min(l[i + 1:i + k + 1]):
            lo[i] = True
    return hi, lo


# ------------------------------------------------------------------ the rules
def _shape(ratio: float) -> str:
    return "textbook" if ratio <= 0.08 else "strong" if ratio <= 0.16 else "loose"


def _detect(piv: list, S: dict, cfg: dict) -> list[dict]:
    """Every pattern whose last swing point is the newest one. S = series (o, h, l, c, atr)."""
    out = []
    c, at = S["c"], S["atr"]
    if len(piv) >= 3:
        out += _double(piv[-3:], S, cfg)
    if len(piv) >= 5:
        out += _triple_or_hs(piv[-5:], S, cfg)
    for n in (6, 5):
        if len(piv) >= n:
            got = _lines(piv[-n:], S, cfg)
            if got:
                out.append(got)
                break
    return out


def _prior(S: dict, cfg: dict, i0: int, level: float, up_into: bool) -> bool:
    """Price came into the pattern from the other side: for a bottom it was at or above `level` before the first low."""
    seg = S["c"][max(0, i0 - cfg["prior"]):i0]
    if not seg:
        return False
    return max(seg) >= level if up_into else min(seg) <= level


def _double(p3: list, S: dict, cfg: dict) -> list[dict]:
    a, m, b = p3
    if a["k"] != b["k"] or m["k"] == a["k"]:
        return []
    bottom = a["k"] == "L"
    at = S["atr"][b["i"]]
    if b["i"] - a["i"] < cfg["db_gap"] or b["i"] - a["i"] > cfg["max_span"]:
        return []
    ext = min(a["p"], b["p"]) if bottom else max(a["p"], b["p"])
    height = (m["p"] - ext) if bottom else (ext - m["p"])
    if height < max(cfg["height_atr"] * at, cfg["height_pct"] / 100 * m["p"]):
        return []
    diff = abs(a["p"] - b["p"])
    if diff > cfg["low_tol_pct"] / 100 * ext or diff > 0.4 * height:
        return []
    if not _prior(S, cfg, a["i"], m["p"], bottom):
        return []
    typ = "double_bottom" if bottom else "double_top"
    neck = Line(0.0, m["p"])
    return [{"type": typ, "piv": [a, m, b], "upper": neck if bottom else None, "lower": None if bottom else neck,
             "neck": neck, "height": height, "fail": ext, "shape": _shape(diff / height),
             "why": [f"Two swing {'lows' if bottom else 'highs'} {diff / ext * 100:.1f}% apart, {b['i'] - a['i']} bars between them",
                     f"Height {height / m['p'] * 100:.1f}% ({height / at:.1f} x ATR)",
                     f"Price came {'down' if bottom else 'up'} into it"]}]


def _triple_or_hs(p5: list, S: dict, cfg: dict) -> list[dict]:
    if [x["k"] for x in p5] not in (["L", "H", "L", "H", "L"], ["H", "L", "H", "L", "H"]):
        return []
    bottom = p5[0]["k"] == "L"
    l1, h1, l2, h2, l3 = p5
    span = l3["i"] - l1["i"]
    if span < cfg["min_span"] or span > cfg["max_span"]:
        return []
    at = S["atr"][l3["i"]]
    lows = [l1["p"], l2["p"], l3["p"]]
    out = []
    # triple
    neck_lvl = max(h1["p"], h2["p"]) if bottom else min(h1["p"], h2["p"])
    ext = min(lows) if bottom else max(lows)
    height = (neck_lvl - ext) if bottom else (ext - neck_lvl)
    if height >= max(cfg["height_atr"] * at, cfg["height_pct"] / 100 * neck_lvl):
        spread = max(lows) - min(lows)
        if spread <= cfg["low_tol_pct"] / 100 * ext and spread <= 0.4 * height and _prior(S, cfg, l1["i"], neck_lvl, bottom):
            neck = Line(0.0, neck_lvl)
            typ = "triple_bottom" if bottom else "triple_top"
            out.append({"type": typ, "piv": p5, "upper": neck if bottom else None, "lower": None if bottom else neck, "neck": neck,
                        "height": height, "fail": ext, "shape": _shape(spread / height),
                        "why": [f"Three swing {'lows' if bottom else 'highs'} within {spread / ext * 100:.1f}% of each other over {span} bars",
                                f"Height {height / neck_lvl * 100:.1f}%"]})
            return out
    # head and shoulders (inverse when bottom)
    a, b0 = _fit([(h1["i"], h1["p"]), (h2["i"], h2["p"])])
    neck = Line(a, b0)
    head_depth = (neck.at(l2["i"]) - l2["p"]) if bottom else (l2["p"] - neck.at(l2["i"]))
    if head_depth < max(cfg["height_atr"] * at, cfg["height_pct"] / 100 * l2["p"]):
        return out
    beyond = (min(l1["p"], l3["p"]) - l2["p"]) if bottom else (l2["p"] - max(l1["p"], l3["p"]))
    if beyond < max(at, 0.15 * head_depth):
        return out
    if abs(l1["p"] - l3["p"]) > 0.5 * head_depth:
        return out
    left, right = l2["i"] - l1["i"], l3["i"] - l2["i"]
    if not right or not (0.4 <= left / right <= 2.5):
        return out
    sh1 = (neck.at(l1["i"]) - l1["p"]) if bottom else (l1["p"] - neck.at(l1["i"]))
    sh3 = (neck.at(l3["i"]) - l3["p"]) if bottom else (l3["p"] - neck.at(l3["i"]))
    if sh1 <= 0 or sh3 <= 0:
        return out
    if not _prior(S, cfg, l1["i"], neck.at(l1["i"]), bottom):
        return out
    typ = "inv_head_shoulders" if bottom else "head_shoulders"
    out.append({"type": typ, "piv": p5, "upper": neck if bottom else None, "lower": None if bottom else neck, "neck": neck,
                "height": head_depth, "fail": l3["p"], "shape": _shape(abs(l1["p"] - l3["p"]) / head_depth),
                "why": [f"Head {beyond / l2['p'] * 100:.1f}% beyond the shoulders; shoulders {abs(l1['p'] - l3['p']) / l2['p'] * 100:.1f}% apart",
                        f"Sides {left} and {right} bars; depth below the neckline {head_depth / l2['p'] * 100:.1f}%"]})
    return out


def _lines(pv: list, S: dict, cfg: dict) -> Optional[dict]:
    hs = [(x["i"], x["p"]) for x in pv if x["k"] == "H"]
    ls = [(x["i"], x["p"]) for x in pv if x["k"] == "L"]
    if len(hs) < 2 or len(ls) < 2:
        return None
    i0, i1 = pv[0]["i"], pv[-1]["i"]
    span = i1 - i0
    if span < cfg["min_span"] or span > cfg["max_span"]:
        return None
    up, lo = Line(*_fit(hs)), Line(*_fit(ls))
    at = S["atr"][i1]
    mid = (up.at(i1) + lo.at(i1)) / 2
    tol = max(cfg["touch_atr"] * at, cfg["touch_pct"] / 100 * mid)
    dev = max([abs(p - up.at(i)) for i, p in hs] + [abs(p - lo.at(i)) for i, p in ls])
    if dev > tol:
        return None
    h0, h1 = up.at(i0) - lo.at(i0), up.at(i1) - lo.at(i1)
    if h0 <= 0 or h1 <= 0:
        return None
    if max(h0, h1) < max(cfg["height_atr"] * at, cfg["height_pct"] / 100 * mid):
        return None
    c = S["c"]
    for j in range(i0, i1 + 1):                      # every close inside the lines
        if c[j] > up.at(j) + tol or c[j] < lo.at(j) - tol:
            return None
    hh = max(h0, h1)
    du, dl = up.a * span, lo.a * span                 # how far each line drifts over the pattern
    flat_u, flat_l = abs(du) <= 0.25 * hh, abs(dl) <= 0.25 * hh
    ratio = h1 / h0
    typ = None
    if flat_u and dl > 0.25 * hh and ratio < 0.8:
        typ = "asc_triangle"
    elif flat_l and du < -0.25 * hh and ratio < 0.8:
        typ = "desc_triangle"
    elif du < -0.25 * hh and dl > 0.25 * hh and ratio < 0.8:
        typ = "sym_triangle"
    elif du > 0 and dl > 0 and not flat_l and not flat_u and ratio <= 0.75:
        typ = "rising_wedge"
    elif du < 0 and dl < 0 and not flat_l and not flat_u and ratio <= 0.75:
        typ = "falling_wedge"
    elif flat_u and flat_l and 0.75 <= ratio <= 1.33:
        typ = "rectangle"
    elif du > 0.25 * hh and dl > 0.25 * hh and 0.75 <= ratio <= 1.33:
        typ = "channel_up"
    elif du < -0.25 * hh and dl < -0.25 * hh and 0.75 <= ratio <= 1.33:
        typ = "channel_down"
    elif du >= -0.25 * hh and dl <= 0.25 * hh and (not flat_u or not flat_l) and du > 0 and dl < 0 and ratio >= 1.33:
        typ = "broadening"
    if not typ:
        return None
    apex = None
    if up.a != lo.a and ratio < 1:
        x = (lo.b - up.b) / (up.a - lo.a)
        apex = x if x > i1 else None
    return {"type": typ, "piv": pv, "upper": up, "lower": lo, "neck": None, "height": h0 if typ != "broadening" else h1,
            "fail": None, "apex": apex, "shape": _shape(dev / hh),
            "why": [f"{len(hs)} swing highs and {len(ls)} swing lows over {span} bars, all within {dev / mid * 100:.1f}% of their lines",
                    f"Upper line {'flat' if flat_u else 'rising' if du > 0 else 'falling'}, lower line {'flat' if flat_l else 'rising' if dl > 0 else 'falling'}; "
                    f"gap {h0 / mid * 100:.1f}% at the start, {h1 / mid * 100:.1f}% now"]}


# ------------------------------------------------------------------ levels after a breakout
def _levels(s: dict, d: str, t: int, S: dict) -> tuple[float, float, float]:
    """(breakout level, target, stop) for a break in direction d ('up'/'down') at bar t."""
    typ, pv = s["type"], s["piv"]
    line = s["upper"] if d == "up" else s["lower"]
    lvl = line.at(t)
    if typ in ("falling_wedge", "rising_wedge"):
        tgt = s["upper"].at(pv[0]["i"]) if d == "up" else s["lower"].at(pv[0]["i"])
    else:
        tgt = lvl + s["height"] if d == "up" else lvl - s["height"]
    if s.get("fail") is not None:
        stop = s["fail"]
    else:
        last = [x for x in pv if x["k"] == ("L" if d == "up" else "H")]
        stop = last[-1]["p"]
    return lvl, tgt, stop


# ------------------------------------------------------------------ one series, bar by bar
def scan(bars: list[dict], tf: str = "D") -> dict:
    """Run the detector through the whole series. Returns {"now": [...live patterns...], "events": [...past breakouts...]}."""
    cfg = CFG[tf]
    n = len(bars)
    if n < 60:
        return {"now": [], "events": []}
    o = [b["o"] for b in bars]
    h = [b["h"] for b in bars]
    l = [b["l"] for b in bars]
    c = [b["c"] for b in bars]
    v = [b.get("v") or 0 for b in bars]
    at = atr(h, l, c)
    av = _avg_vol(v, cfg["vol_n"])
    S = {"o": o, "h": h, "l": l, "c": c, "v": v, "atr": at}
    hi, lo = _fractals(h, l, cfg["k"])
    sw = Swings(cfg, h, l, at)
    k = cfg["k"]
    active: list[dict] = []
    done: list[dict] = []
    for t in range(n):
        i = t - k
        if i >= k:
            changed = False
            # an outside bar can be both; take them in time order of the swing (low first after a high, and so on)
            kinds = [x for x, f in (("H", hi[i]), ("L", lo[i])) if f]
            if len(kinds) == 2 and sw.piv and sw.piv[-1]["k"] == "H":
                kinds = ["L", "H"]
            for kd in kinds:
                changed |= sw.add(i, kd)
            if changed:
                for s in _detect(sw.piv, S, cfg):
                    s.update(known=t, last=s["piv"][-1]["i"], state="forming", tf=tf)
                    active.append(s)
                    _advance(s, S, av, cfg, range(s["last"] + 1, t + 1), t)
        for s in active:
            if s["state"] == "forming" and s["known"] < t:
                _advance(s, S, av, cfg, (t,), t)
        keep = []
        for s in active:
            (keep if s["state"] == "forming" else done).append(s)
        active = keep
    # outcomes of each breakout: target or stop first (bars after the entry only)
    events = []
    for s in done:
        if s["state"] != "breakout":
            continue
        e = s["entry_i"]
        res, ret = "open", None
        for j in range(e + 1, min(n, e + 1 + cfg["horizon"])):
            if s["dir"] == "up":
                if l[j] <= s["stop"]:
                    res = "stop"; break
                if h[j] >= s["target"]:
                    res = "target"; break
            else:
                if h[j] >= s["stop"]:
                    res = "stop"; break
                if l[j] <= s["target"]:
                    res = "target"; break
        if res == "open" and e + cfg["horizon"] >= n:
            res = "unfinished"
        r20 = (c[e + 20] / c[e] - 1) * 100 if e + 20 < n else None
        if r20 is not None and s["dir"] == "down":
            r20 = -r20
        events.append({"type": s["type"], "dir": s["dir"], "t": bars[s["brk_i"]]["t"][:10], "i": s["brk_i"], "result": res,
                       "r20": r20, "confirmed": s["confirmed"]})
    # one event per pattern type and breakout bar (a 5- and a 6-point fit of the same triangle are one breakout)
    seen, uniq = set(), []
    for ev in events:
        key = (ev["type"], ev["i"], ev["dir"])
        if key not in seen:
            seen.add(key); uniq.append(ev)
    now = _live(active, done, bars, S, av, cfg, tf)
    return {"now": now, "events": uniq}


def _advance(s: dict, S: dict, av: list, cfg: dict, ts, known_at: int) -> None:
    c = S["c"]
    bias = BIAS[s["type"]]
    for t in ts:
        if s["state"] != "forming":
            return
        up_ok = bias in ("up", "both") and s["upper"] is not None
        dn_ok = bias in ("down", "both") and s["lower"] is not None
        if up_ok and c[t] > s["upper"].at(t):
            _break(s, "up", t, max(t, known_at), S, av, cfg); return
        if dn_ok and c[t] < s["lower"].at(t):
            _break(s, "down", t, max(t, known_at), S, av, cfg); return
        # failure: one-way patterns closing beyond their own failure level / the opposite line
        if bias == "up":
            fl = s["fail"] if s.get("fail") is not None else s["lower"].at(t)
            if c[t] < fl:
                s["state"] = "failed"; s["end_i"] = t; return
        if bias == "down":
            fl = s["fail"] if s.get("fail") is not None else s["upper"].at(t)
            if c[t] > fl:
                s["state"] = "failed"; s["end_i"] = t; return
        if t - s["last"] > cfg["expire"] or (s.get("apex") and t >= s["apex"]):
            s["state"] = "expired"; s["end_i"] = t; return


def _break(s: dict, d: str, t: int, e: int, S: dict, av: list, cfg: dict) -> None:
    lvl, tgt, stop = _levels(s, d, t, S)
    vx = _vol_x(t, S["v"], av)
    s.update(state="breakout", dir=d, brk_i=t, entry_i=e, level=lvl, target=tgt, stop=stop, vol_x=vx,
             confirmed=bool(vx and vx >= cfg["vol_x"]))     # Confirmed: the breakout bar traded 1.5x its usual volume


def _vol_x(t: int, v: list, av: list) -> Optional[float]:
    return round(v[t] / av[t], 2) if av[t] else None


def _live(active: list, done: list, bars: list, S: dict, av: list, cfg: dict, tf: str) -> list[dict]:
    """Patterns to show today: still forming, or broke out within the last few bars."""
    n = len(bars)
    c = S["c"]
    out = []
    for s in active:
        if s["state"] != "forming":
            continue
        bias = BIAS[s["type"]]
        d = "down" if bias == "down" else "up"
        if bias == "both":                        # nearer line decides which breakout to show
            d = "up" if s["upper"].at(n - 1) - c[-1] <= c[-1] - s["lower"].at(n - 1) else "down"
        lvl, tgt, stop = _levels(s, d, n - 1, S)
        out.append(_card(s, "forming", d, lvl, tgt, stop, None, bars, S, cfg, tf))
    for s in done:
        if s["state"] != "breakout" or s["brk_i"] < n - cfg["recent"]:
            continue
        vx = s["vol_x"]
        holds = c[-1] > s["level"] if s["dir"] == "up" else c[-1] < s["level"]
        out.append(_card(s, "breakout" if holds else "failed", s["dir"], s["level"], s["target"], s["stop"], vx, bars, S, cfg, tf))
    # one card per pattern type: the newest
    best: dict = {}
    for x in out:
        k = x["type"]
        if k not in best or x["_known"] > best[k]["_known"]:
            best[k] = x
    res = []
    for x in best.values():
        x.pop("_known", None)
        res.append(x)
    return res


def _card(s: dict, status: str, d: str, lvl: float, tgt: float, stop: float, vx, bars: list, S: dict, cfg: dict, tf: str) -> dict:
    n = len(bars)
    c = S["c"]
    pv = s["piv"]
    w0 = max(0, pv[0]["i"] - cfg["pad"])
    win = bars[w0:]
    risk = abs(lvl - stop)
    rr = round(abs(tgt - lvl) / risk, 1) if risk else None
    lines = []
    end = n - 1
    for nm in ("upper", "lower"):
        ln = s.get(nm)
        if ln is not None:
            x0 = pv[0]["i"]
            lines.append([x0 - w0, round(ln.at(x0), 2), end - w0, round(ln.at(end), 2), nm])
    out = {
        "type": s["type"], "name": NAMES[s["type"]], "tf": tf, "status": status, "dir": d, "bias": BIAS[s["type"]],
        "level": round(lvl, 2), "target": round(tgt, 2), "stop": round(stop, 2), "rr": rr, "shape": s["shape"],
        "close": round(c[-1], 2), "pct_from_level": round((c[-1] / lvl - 1) * 100, 2) if lvl else None,
        "formed": bars[s["known"]]["t"][:10], "start": bars[pv[0]["i"]]["t"][:10], "why": s["why"],
        "draw": {"bars": [[round(b["o"], 2), round(b["h"], 2), round(b["l"], 2), round(b["c"], 2)] for b in win],
                 "t0": win[0]["t"][:10], "t1": win[-1]["t"][:10],
                 "pivots": [[x["i"] - w0, round(x["p"], 2), x["k"]] for x in pv], "lines": lines},
        "_known": s["known"],
    }
    if status != "forming":
        out.update(bars_ago=n - 1 - s["brk_i"], broke=bars[s["brk_i"]]["t"][:10], vol_x=vx, confirmed=s.get("confirmed", False))
    return out


# ------------------------------------------------------------------ gaps
def gaps(bars: list[dict], recent: int = 10) -> dict:
    """Full gaps (open beyond the previous day's whole range) of at least 1%.
    now: gaps in the last `recent` sessions with whether they are filled; events: every gap with its outcome."""
    n = len(bars)
    out_now, events = [], []
    if n < 60:
        return {"now": out_now, "events": events}
    v = [b.get("v") or 0 for b in bars]
    av = _avg_vol(v, 50)
    for i in range(1, n):
        p, b = bars[i - 1], bars[i]
        if b["o"] > p["h"] * 1.01:
            d, size, edge = "up", (b["o"] / p["h"] - 1) * 100, p["h"]
        elif b["o"] < p["l"] * 0.99:
            d, size, edge = "down", (1 - b["o"] / p["l"]) * 100, p["l"]
        else:
            continue
        fill_i = None
        for j in range(i, n):
            if (d == "up" and bars[j]["l"] <= edge) or (d == "down" and bars[j]["h"] >= edge):
                fill_i = j
                break
        held = (b["c"] > b["o"]) if d == "up" else (b["c"] < b["o"])
        r20 = (bars[i + 20]["c"] / b["c"] - 1) * 100 if i + 20 < n else None
        ev = {"t": b["t"][:10], "i": i, "dir": d, "size": round(size, 2), "bucket": "big" if size >= 3 else "small",
              "filled_5": fill_i is not None and fill_i - i <= 5 if i + 5 < n or fill_i is not None else None,
              "filled_20": fill_i is not None and fill_i - i <= 20 if i + 20 < n or fill_i is not None else None,
              "held": held, "r20": r20, "vol_x": round(v[i] / av[i], 2) if av[i] else None}
        events.append(ev)
        if i >= n - recent:
            out_now.append({**ev, "edge": round(edge, 2), "open": round(b["o"], 2), "close_day": round(b["c"], 2),
                            "filled": fill_i is not None, "filled_on": bars[fill_i]["t"][:10] if fill_i is not None else None,
                            "days_ago": n - 1 - i, "close": round(bars[-1]["c"], 2)})
    return {"now": out_now, "events": events}


# ------------------------------------------------------------------ candlesticks
CANDLES = {
    "hammer": ("Hammer", "up", "After a fall: small body in the top third, lower wick at least 2x the body, upper wick at most 10% of the range."),
    "inverted_hammer": ("Inverted hammer", "up", "After a fall: small body in the bottom 40%, upper wick at least 2x the body, lower wick at most 10% of the range."),
    "bull_engulfing": ("Bullish engulfing", "up", "After a fall: a red candle, then a green candle whose body covers the red body entirely."),
    "piercing": ("Piercing line", "up", "After a fall: a red candle, then a green candle opening below its close and closing above the middle of its body (not above its open)."),
    "morning_star": ("Morning star", "up", "After a fall: a long red candle, a small-bodied candle (at most 30% of the first body), then a green candle closing above the middle of the first body."),
    "three_soldiers": ("Three white soldiers", "up", "Three green candles in a row, each closing higher, each opening inside the previous body, bodies at least half the range, small upper wicks."),
    "dragonfly_doji": ("Dragonfly doji", "up", "After a fall: body at most 10% of the range, lower wick at least 60%, upper wick at most 10%."),
    "shooting_star": ("Shooting star", "down", "After a rise: small body in the bottom 40%, upper wick at least 2x the body, lower wick at most 10% of the range."),
    "hanging_man": ("Hanging man", "down", "After a rise: the hammer's shape."),
    "bear_engulfing": ("Bearish engulfing", "down", "After a rise: a green candle, then a red candle whose body covers the green body entirely."),
    "dark_cloud": ("Dark cloud cover", "down", "After a rise: a green candle, then a red candle opening above its close and closing below the middle of its body (not below its open)."),
    "evening_star": ("Evening star", "down", "After a rise: a long green candle, a small-bodied candle, then a red candle closing below the middle of the first body."),
    "three_crows": ("Three black crows", "down", "Three red candles in a row, each closing lower, each opening inside the previous body, bodies at least half the range, small lower wicks."),
    "gravestone_doji": ("Gravestone doji", "down", "After a rise: body at most 10% of the range, upper wick at least 60%, lower wick at most 10%."),
}


def candle_tags(bars: list[dict], i: int, sma20: Optional[float]) -> list[str]:
    """Candlestick patterns completed on bar i (uses bars up to i only). 'After a fall' = the previous close is below the close
    5 bars earlier and below the 20-day average; 'after a rise' the opposite."""
    if i < 6:
        return []
    b, p, q = bars[i], bars[i - 1], bars[i - 2]
    rng = b["h"] - b["l"]
    if rng <= 0:
        return []
    down = p["c"] < bars[i - 6]["c"] and (sma20 is None or p["c"] < sma20)
    up = p["c"] > bars[i - 6]["c"] and (sma20 is None or p["c"] > sma20)
    body = abs(b["c"] - b["o"])
    top, bot = max(b["o"], b["c"]), min(b["o"], b["c"])
    upper, lower = b["h"] - top, bot - b["l"]
    out = []
    small = 0.05 * rng <= body <= 0.35 * rng
    if small and lower >= 2 * body and upper <= 0.1 * rng and bot >= b["l"] + 0.6 * rng:
        if down:
            out.append("hammer")
        if up:
            out.append("hanging_man")
    if small and upper >= 2 * body and lower <= 0.1 * rng and top <= b["l"] + 0.4 * rng:
        if down:
            out.append("inverted_hammer")
        if up:
            out.append("shooting_star")
    if body <= 0.1 * rng:
        if down and lower >= 0.6 * rng and upper <= 0.1 * rng:
            out.append("dragonfly_doji")
        if up and upper >= 0.6 * rng and lower <= 0.1 * rng:
            out.append("gravestone_doji")
    pb = abs(p["c"] - p["o"])
    if down and p["c"] < p["o"] and b["c"] > b["o"] and b["o"] <= p["c"] and b["c"] >= p["o"] and body > pb:
        out.append("bull_engulfing")
    if up and p["c"] > p["o"] and b["c"] < b["o"] and b["o"] >= p["c"] and b["c"] <= p["o"] and body > pb:
        out.append("bear_engulfing")
    pmid = (p["o"] + p["c"]) / 2
    prng = p["h"] - p["l"]
    if down and prng > 0 and p["c"] < p["o"] and pb >= 0.5 * prng and b["c"] > b["o"] and b["o"] < p["c"] and pmid < b["c"] < p["o"]:
        out.append("piercing")
    if up and prng > 0 and p["c"] > p["o"] and pb >= 0.5 * prng and b["c"] < b["o"] and b["o"] > p["c"] and p["o"] < b["c"] < pmid:
        out.append("dark_cloud")
    qb, qr = abs(q["c"] - q["o"]), q["h"] - q["l"]
    qmid = (q["o"] + q["c"]) / 2
    pre_down = bars[i - 3]["c"] < bars[i - 6]["c"] if i >= 6 else False
    pre_up = bars[i - 3]["c"] > bars[i - 6]["c"] if i >= 6 else False
    if qr > 0 and qb >= 0.6 * qr and pb <= 0.3 * qb:
        if pre_down and q["c"] < q["o"] and b["c"] > b["o"] and b["c"] > qmid:
            out.append("morning_star")
        if pre_up and q["c"] > q["o"] and b["c"] < b["o"] and b["c"] < qmid:
            out.append("evening_star")
    three = [q, p, b]
    def strong(x):
        r = x["h"] - x["l"]
        return r > 0 and abs(x["c"] - x["o"]) >= 0.5 * r
    if all(x["c"] > x["o"] and strong(x) and x["h"] - x["c"] <= 0.3 * abs(x["c"] - x["o"]) for x in three) \
            and q["c"] < p["c"] < b["c"] and q["o"] < p["o"] <= q["c"] and p["o"] < b["o"] <= p["c"] and not pre_up:
        out.append("three_soldiers")
    if all(x["c"] < x["o"] and strong(x) and x["c"] - x["l"] <= 0.3 * abs(x["c"] - x["o"]) for x in three) \
            and q["c"] > p["c"] > b["c"] and q["o"] > p["o"] >= q["c"] and p["o"] > b["o"] >= p["c"] and not pre_down:
        out.append("three_crows")
    return out


def candles(bars: list[dict], recent: int = 3) -> dict:
    """now: candlestick patterns on the last `recent` bars; events: every one in history with 5- and 10-bar results
    (signed in the pattern's direction)."""
    n = len(bars)
    c = [b["c"] for b in bars]
    now, events = [], []
    s = 0.0
    for i in range(n):
        s += c[i]
        if i >= 20:
            s -= c[i - 20]
        sma = s / 20 if i >= 19 else None
        prev_sma = (s - c[i] + (c[i - 20] if i >= 20 else 0)) / 20 if i >= 20 else None
        for tag in candle_tags(bars, i, prev_sma):
            d = CANDLES[tag][1]
            sign = 1 if d == "up" else -1
            r5 = (c[i + 5] / c[i] - 1) * 100 * sign if i + 5 < n else None
            r10 = (c[i + 10] / c[i] - 1) * 100 * sign if i + 10 < n else None
            events.append({"type": tag, "dir": d, "t": bars[i]["t"][:10], "r5": r5, "r10": r10})
            if i >= n - recent:
                now.append({"type": tag, "name": CANDLES[tag][0], "dir": d, "t": bars[i]["t"][:10], "days_ago": n - 1 - i,
                            "close": round(c[-1], 2), "draw": [[round(x["o"], 2), round(x["h"], 2), round(x["l"], 2), round(x["c"], 2)]
                                                               for x in bars[max(0, i - 14):i + 1]]})
    return {"now": now, "events": events}


# ------------------------------------------------------------------ one stock, everything
def analyse(bars: list[dict]) -> dict:
    """Daily and weekly classic patterns, gaps and candlesticks for one stock."""
    d = scan(bars, "D")
    w = scan(weekly(bars), "W")
    g = gaps(bars)
    k = candles(bars)
    return {"now": d["now"] + w["now"], "events": [dict(e, tf="D") for e in d["events"]] + [dict(e, tf="W") for e in w["events"]],
            "gaps_now": g["now"], "gap_events": g["events"], "candles_now": k["now"], "candle_events": k["events"],
            "fwd": {k: _fwd(bars, k) for k in (5, 10, 20)}}


def _fwd(bars: list[dict], k: int) -> list[float]:
    """k-session returns from every 5th bar: the 'any day' baseline the patterns are compared with."""
    c = [b["c"] for b in bars]
    return [round((c[i + k] / c[i] - 1) * 100, 3) for i in range(0, len(c) - k, 5)]


# ------------------------------------------------------------------ across the list: the tested record
class Record:
    def __init__(self):
        self.p: dict = {}
        self.g: dict = {}
        self.k: dict = {}
        self.base: dict = {5: [], 10: [], 20: []}
        self.stocks = 0
        self.first: Optional[str] = None
        self.last: Optional[str] = None

    def add(self, a: dict, t0: Optional[str], t1: Optional[str]) -> None:
        self.stocks += 1
        if t0 and (self.first is None or t0 < self.first):
            self.first = t0
        if t1 and (self.last is None or t1 > self.last):
            self.last = t1
        for e in a["events"]:
            r = self.p.setdefault(f"{e['tf']}:{e['type']}:{e['dir']}", {"n": 0, "target": 0, "stop": 0, "open": 0, "unfinished": 0, "r20": [],
                                                                         "conf_n": 0, "conf_target": 0})
            if e["result"] == "unfinished":
                r["unfinished"] += 1
                continue
            r["n"] += 1
            r[e["result"]] += 1
            if e.get("r20") is not None:
                r["r20"].append(e["r20"])
        for e in a["gap_events"]:
            r = self.g.setdefault(f"{e['dir']}:{e['bucket']}", {"n": 0, "f5": 0, "f20": 0, "n20": 0, "held": 0, "r20": []})
            if e["filled_5"] is None:
                continue
            r["n"] += 1
            r["f5"] += bool(e["filled_5"])
            r["held"] += bool(e["held"])
            if e["filled_20"] is not None:
                r["n20"] += 1
                r["f20"] += bool(e["filled_20"])
            if e["r20"] is not None:
                r["r20"].append(e["r20"])
        for e in a["candle_events"]:
            r = self.k.setdefault(e["type"], {"n": 0, "w5": 0, "w10": 0, "r5": [], "r10": []})
            if e["r10"] is None:
                continue
            r["n"] += 1
            r["w5"] += e["r5"] > 0
            r["w10"] += e["r10"] > 0
            r["r5"].append(e["r5"])
            r["r10"].append(e["r10"])
        for k, xs in (a.get("fwd") or {}).items():
            self.base[int(k)] += xs

    def finish(self) -> dict:
        def med(xs):
            return round(statistics.median(xs), 2) if xs else None
        pats = {}
        for k, r in self.p.items():
            n = r["n"]
            pats[k] = {"n": n, "target_first": round(r["target"] / n * 100, 1) if n else None,
                       "stop_first": round(r["stop"] / n * 100, 1) if n else None, "neither": round(r["open"] / n * 100, 1) if n else None,
                       "median_r20": med(r["r20"]), "unfinished": r["unfinished"]}
        gp = {}
        for k, r in self.g.items():
            gp[k] = {"n": r["n"], "filled_5": round(r["f5"] / r["n"] * 100, 1) if r["n"] else None,
                     "filled_20": round(r["f20"] / r["n20"] * 100, 1) if r["n20"] else None,
                     "held_day": round(r["held"] / r["n"] * 100, 1) if r["n"] else None, "median_r20": med(r["r20"])}
        kd = {}
        for k, r in self.k.items():
            n = r["n"]
            kd[k] = {"n": n, "win5": round(r["w5"] / n * 100, 1) if n else None, "win10": round(r["w10"] / n * 100, 1) if n else None,
                     "median_r5": med(r["r5"]), "median_r10": med(r["r10"])}
        base = {}
        for k, b in self.base.items():
            base[f"median_r{k}"] = med(b)
            base[f"up_r{k}"] = round(sum(1 for x in b if x > 0) / len(b) * 100, 1) if b else None
        base["n"] = len(self.base[20])
        return {"patterns": pats, "gaps": gp, "candles": kd, "stocks": self.stocks, "from": self.first, "to": self.last, "base": base}
