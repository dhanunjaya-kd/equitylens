"""Market dashboard: market pulse, breadth, index pulse and sector rotation. Every number comes from saved prices:
the app's price list (every stock's daily candles), NSE's full end-of-day file, Nasdaq's stock list and Yahoo's
index candles. Nothing is estimated.

Market pulse (0-100) = weighted average of five parts, each 0-100:
  breadth 30%   share of stocks that closed up on the day
  momentum 25%  share of stocks above their 50-day average
  trend 15%     share of stocks above their 200-day average
  volume 20%    share of all traded volume that was in rising stocks
  calm 10%      100 minus where today's volatility index sits in its last year (percentile)
Zones: 0-25 extreme fear, 25-45 fear, 45-60 neutral, 60-75 greed, 75-100 extreme greed.

Sector rotation: RS = sector index / benchmark. RS-Ratio = 100 x RS / its n-bar average; RS-Momentum = 100 x RS-Ratio /
RS-Ratio m bars earlier (daily n=20, m=5; weekly n=10, m=4). Above 100 on both = leading; ratio above, momentum below =
weakening; both below = lagging; ratio below, momentum above = improving. (A plain method in the spirit of relative
rotation graphs, not the proprietary JdK formula.)
"""
from __future__ import annotations

import statistics
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from typing import Optional

from . import config, indices, store, technicals

WEIGHTS = [("breadth", "Stocks up today", 0.30), ("momentum", "Above their 50-day average", 0.25),
           ("trend", "Above their 200-day average", 0.15), ("volume", "Volume in rising stocks", 0.20),
           ("calm", "Calm (inverse of the volatility index's 1-year rank)", 0.10)]
ZONES = [(25, "Extreme fear"), (45, "Fear"), (60, "Neutral"), (75, "Greed"), (101, "Extreme greed")]
VIX = {"IN": "^INDIAVIX", "US": "^VIX"}
BENCH = {"IN": ("^NSEI", "NIFTY 50"), "US": ("^GSPC", "S&P 500")}
PULSE = {
    "IN": [("^NSEI", "Nifty 50", "index"), ("^NSEBANK", "Bank Nifty", "index"), ("NIFTY_MIDCAP_100.NS", "Midcap 100", "index"),
           ("^CNXSC", "Smallcap 100", "index"), ("^BSESN", "Sensex", "index"), ("^INDIAVIX", "India VIX", "vix"),
           ("^CNXIT", "Nifty IT", "index"), ("NIFTY_FIN_SERVICE.NS", "Fin Services", "index")],
    "US": [("^GSPC", "S&P 500", "index"), ("^NDX", "Nasdaq 100", "index"), ("^DJI", "Dow Jones", "index"), ("^RUT", "Russell 2000", "index"),
           ("^VIX", "VIX", "vix"), ("^SOX", "Semiconductors", "index"), ("XLF", "Financials (XLF)", "index"), ("XLE", "Energy (XLE)", "index")],
}
SECTORS = {
    "IN": [("^NSEBANK", "Bank"), ("^CNXPSUBANK", "PSU Bank"), ("NIFTY_FIN_SERVICE.NS", "Fin services"), ("^CNXIT", "IT"),
           ("^CNXAUTO", "Auto"), ("^CNXPHARMA", "Pharma"), ("^CNXFMCG", "FMCG"), ("^CNXMETAL", "Metal"), ("^CNXREALTY", "Realty"),
           ("^CNXENERGY", "Energy"), ("^CNXMEDIA", "Media"), ("^CNXINFRA", "Infra")],
    "US": [("XLK", "Technology"), ("XLF", "Financials"), ("XLV", "Health care"), ("XLY", "Cons. discretionary"), ("XLP", "Cons. staples"),
           ("XLE", "Energy"), ("XLI", "Industrials"), ("XLB", "Materials"), ("XLU", "Utilities"), ("XLRE", "Real estate"), ("XLC", "Communication")],
}
_mem: dict = {}
_lock = threading.Lock()


def zone(score: Optional[float]) -> Optional[str]:
    if score is None:
        return None
    return next(z for cut, z in ZONES if score < cut)


def score_of(parts: dict) -> Optional[float]:
    have = [(parts.get(k), w) for k, _, w in WEIGHTS if parts.get(k) is not None]
    if not have:
        return None
    tw = sum(w for _, w in have)
    return round(sum(v * w for v, w in have) / tw, 1)


# ------------------------------------------------------------------ daily history of the parts, from every stock's candles
class BreadthHistory:
    """Added to by the price refresh, one stock at a time. Per day: [stocks, up, stocks with 50 days, above 50-day,
    stocks with 200 days, above 200-day, traded value in rising stocks, all traded value]."""

    def __init__(self):
        self.d: dict = defaultdict(lambda: [0, 0, 0, 0, 0, 0, 0.0, 0.0])
        self.lock = threading.Lock()

    def add(self, bars: list[dict]) -> None:
        c = [b["c"] for b in bars]
        s50 = s200 = 0.0
        rows = []
        for i in range(len(c)):
            s50 += c[i]
            s200 += c[i]
            if i >= 50:
                s50 -= c[i - 50]
            if i >= 200:
                s200 -= c[i - 200]
            if i == 0:
                continue
            rows.append((bars[i]["t"][:10], c[i] > c[i - 1], (c[i] > s50 / 50) if i >= 49 else None,
                         (c[i] > s200 / 200) if i >= 199 else None, (bars[i].get("v") or 0) * c[i]))
        with self.lock:
            for day, up, a50, a200, v in rows:
                r = self.d[day]
                r[0] += 1
                r[1] += up
                if a50 is not None:
                    r[2] += 1
                    r[3] += a50
                if a200 is not None:
                    r[4] += 1
                    r[5] += a200
                if up:
                    r[6] += v
                r[7] += v

    def finish(self) -> dict:
        return {k: list(r) for k, r in self.d.items()}


def parts_from_hist(row: list) -> dict:
    n, up, n50, a50, n200, a200, upv, tv = row
    return {"breadth": round(up / n * 100, 1) if n else None, "momentum": round(a50 / n50 * 100, 1) if n50 else None,
            "trend": round(a200 / n200 * 100, 1) if n200 else None, "volume": round(upv / tv * 100, 1) if tv else None}


def _yahoo_daily(sym: str, rng: str = "5y", ttl: float = 6 * 3600) -> list[dict]:
    key = f"YDAILY::{sym}::{rng}"
    hit = store.get_company(key)
    if hit and time.time() - hit[0] < ttl and hit[1].get("bars"):
        return hit[1]["bars"]
    if config.DEMO:
        bars = technicals._demo(sym)[-1250:]
    else:
        try:
            bars = technicals._yahoo(sym, rng)
        except Exception:  # noqa: BLE001
            return hit[1]["bars"] if hit else []
    store.put_company(key, {"bars": bars})
    return bars


def _vix_rank(vbars: list[dict]) -> dict:
    """date -> 100 - percentile of that day's volatility-index close within the 252 sessions before it (inclusive)."""
    out = {}
    cs = [b["c"] for b in vbars]
    for i in range(len(cs)):
        w = cs[max(0, i - 251):i + 1]
        if len(w) < 60:
            continue
        rank = sum(1 for x in w if x <= cs[i]) / len(w) * 100
        out[vbars[i]["t"][:10]] = round(100 - rank, 1)
    return out


# ------------------------------------------------------------------ market pulse
def pulse(market: str) -> dict:
    from . import movers
    mk = market.upper()
    hit = store.get_company(movers._key(mk))
    rows = (hit[1].get("rows") if hit else None) or []
    session = max((r.get("date") or "" for r in rows), default="") or None
    today = [r for r in rows if r.get("date") == session]
    parts = {}
    if today:
        n = len(today)
        parts["breadth"] = round(sum(1 for r in today if (r.get("ret") or {}).get("1D", 0) and r["ret"]["1D"] > 0) / n * 100, 1)
        parts["momentum"] = round(sum(1 for r in today if r.get("above50")) / n * 100, 1)
        parts["trend"] = round(sum(1 for r in today if r.get("above200")) / n * 100, 1)
        tv = sum((r.get("vol") or 0) * (r.get("price") or 0) for r in today)
        uv = sum((r.get("vol") or 0) * (r.get("price") or 0) for r in today if ((r.get("ret") or {}).get("1D") or 0) > 0)
        parts["volume"] = round(uv / tv * 100, 1) if tv else None
    vb = _yahoo_daily(VIX[mk], "2y")
    vr = _vix_rank(vb)
    parts["calm"] = vr.get(vb[-1]["t"][:10]) if vb else None
    sc = score_of(parts)
    rec = store.get_company(f"PULSEHIST::{mk}")
    record = rec[1].get("record") if rec else None
    hist = rec[1].get("series", [])[-120:] if rec else []
    return {"market": mk, "score": sc, "zone": zone(sc), "parts": parts, "stocks": len(today), "session": session,
            "weights": [{"key": k, "label": l, "weight": w} for k, l, w in WEIGHTS], "zones": [{"below": c, "name": z} for c, z in ZONES],
            "vix_level": vb[-1]["c"] if vb else None, "record": record, "history": hist,
            "universe": (hit[1].get("universe") if hit else None)}


def build_history(market: str, hist: dict) -> None:
    """Score for every past day (from every stock's candles + the volatility index), and what the benchmark did in the
    20 sessions after each zone. Saved by the price refresh."""
    mk = market.upper()
    vr = _vix_rank(_yahoo_daily(VIX[mk], "5y"))
    bench = _yahoo_daily(BENCH[mk][0], "5y")
    bc = {b["t"][:10]: b["c"] for b in bench}
    bdays = [b["t"][:10] for b in bench]
    series = []
    for day in sorted(hist):
        row = hist[day]
        if row[0] < 20 or row[4] < 20:              # too few stocks with 200 days of history that day
            continue
        p = parts_from_hist(row)
        p["calm"] = vr.get(day)
        sc = score_of(p)
        if sc is not None:
            series.append([day, sc])
    pos = {d: i for i, d in enumerate(bdays)}
    by_zone: dict = defaultdict(list)
    for day, sc in series:
        i = pos.get(day)
        if i is None or i + 20 >= len(bdays):
            continue
        by_zone[zone(sc)].append((bc[bdays[i + 20]] / bc[day] - 1) * 100)
    allr = [(bc[bdays[i + 20]] / bc[bdays[i]] - 1) * 100 for i in range(len(bdays) - 20)]
    rec = {z: {"n": len(xs), "median_r20": round(statistics.median(xs), 2) if xs else None,
               "up_r20": round(sum(1 for x in xs if x > 0) / len(xs) * 100, 1) if xs else None} for _, z in ZONES for xs in [by_zone.get(z, [])]}
    rec["_any"] = {"n": len(allr), "median_r20": round(statistics.median(allr), 2) if allr else None,
                   "up_r20": round(sum(1 for x in allr if x > 0) / len(allr) * 100, 1) if allr else None}
    store.put_company(f"PULSEHIST::{mk}", {"series": series, "record": {"zones": rec, "bench": BENCH[mk][1],
                                                                        "from": series[0][0] if series else None, "to": series[-1][0] if series else None}})


# ------------------------------------------------------------------ breadth (every listed stock)
def breadth(market: str) -> dict:
    mk = market.upper()
    if mk == "US":
        from . import usuniverse
        lst = usuniverse.listed()
        ch = [r["chg_pct"] for r in lst.get("rows", []) if r.get("chg_pct") is not None]
        src, day = "Nasdaq stock screener (every NASDAQ, NYSE and AMEX stock)", lst.get("updated")
        day = date.fromtimestamp(day).isoformat() if isinstance(day, (int, float)) else day
    else:
        from . import flows
        days = flows.delivery_days(2)
        if not days:
            return {"market": mk, "error": "NSE's end-of-day file is not available yet"}
        day, rows = days[0]
        ch = [(r["close"] / r["prev"] - 1) * 100 for r in rows.values() if r.get("prev")]
        src = "NSE end-of-day file (every stock traded that day)"
    adv = sum(1 for x in ch if x > 0)
    dec = sum(1 for x in ch if x < 0)
    unch = len(ch) - adv - dec
    up5 = sum(1 for x in ch if x >= 5)
    dn5 = sum(1 for x in ch if x <= -5)
    dist = [{"label": "-5% or more", "n": dn5}, {"label": "-5 to -2%", "n": sum(1 for x in ch if -5 < x <= -2)},
            {"label": "-2 to 0%", "n": sum(1 for x in ch if -2 < x < 0)}, {"label": "flat", "n": unch},
            {"label": "0 to 2%", "n": sum(1 for x in ch if 0 < x < 2)}, {"label": "2 to 5%", "n": sum(1 for x in ch if 2 <= x < 5)},
            {"label": "+5% or more", "n": up5}]
    total = adv + dec
    return {"market": mk, "day": day, "total": len(ch), "adv": adv, "dec": dec, "unch": unch, "up5": up5, "dn5": dn5,
            "net": adv - dec, "adv_share": round(adv / total * 100, 1) if total else None, "dist": dist, "source": src}


# ------------------------------------------------------------------ index pulse
def index_pulse(market: str) -> dict:
    mk = market.upper()
    with _lock:
        hit = _mem.get(("pulse", mk))
        if hit and time.time() - hit[0] < 60:
            return hit[1]

    def one(x):
        sym, name, kind = x
        try:
            if config.DEMO:
                it = indices._demo(sym, name, kind, mk) if sym in ("^NSEI", "^NSEBANK", "^BSESN", "^INDIAVIX", "^GSPC", "^IXIC", "^DJI", "^RUT", "^VIX") \
                    else dict(indices._demo("^NSEI", name, kind, mk), symbol=sym)
            else:
                it = indices._one(sym, name, kind, mk)
            return it
        except Exception as e:  # noqa: BLE001
            return {"symbol": sym, "name": name, "kind": kind, "price": None, "error": str(e)[:160]}
    with ThreadPoolExecutor(max_workers=4) as ex:
        items = list(ex.map(one, PULSE[mk]))
    out = {"market": mk, "items": items, "source": "Yahoo Finance chart feed (may be delayed)", "updated": time.time()}
    with _lock:
        _mem[("pulse", mk)] = (time.time(), out)
    return out


# ------------------------------------------------------------------ sector rotation
def _weekly_closes(bars: list[dict]) -> list[tuple[str, float]]:
    out, key = [], None
    for b in bars:
        k = date.fromisoformat(b["t"][:10]).isocalendar()[:2]
        if k != key:
            out.append([b["t"][:10], b["c"]])
            key = k
        else:
            out[-1][1] = b["c"]
    return [tuple(x) for x in out]


def rotation_points(sec: list[tuple[str, float]], bench: dict, n: int, m: int, tail: int) -> list[list]:
    rs = [(d, c / bench[d]) for d, c in sec if bench.get(d)]
    rsr = []
    for i in range(len(rs)):
        if i < n - 1:
            continue
        avg = sum(x for _, x in rs[i - n + 1:i + 1]) / n
        rsr.append((rs[i][0], 100 * rs[i][1] / avg))
    pts = []
    for i in range(m, len(rsr)):
        pts.append([rsr[i][0], round(rsr[i][1], 2), round(100 * rsr[i][1] / rsr[i - m][1], 2)])
    return pts[-tail:]


def quadrant(r: float, m: float) -> str:
    return "leading" if r >= 100 and m >= 100 else "weakening" if r >= 100 else "lagging" if m < 100 else "improving"


def rotation(market: str, frame: str = "daily") -> dict:
    mk = market.upper()
    bsym, bname = BENCH[mk]
    bbars = _yahoo_daily(bsym, "2y")
    weekly = frame == "weekly"
    if weekly:
        bench = dict(_weekly_closes(bbars))
        n, m, tail = 10, 4, 8
    else:
        bench = {b["t"][:10]: b["c"] for b in bbars}
        n, m, tail = 20, 5, 10
    out, errors = [], []

    def one(x):
        sym, name = x
        bars = _yahoo_daily(sym, "2y")
        if len(bars) < 60:
            return None, f"{name}: no candles"
        closes = _weekly_closes(bars) if weekly else [(b["t"][:10], b["c"]) for b in bars]
        pts = rotation_points(closes, bench, n, m, tail)
        if len(pts) < 2:
            return None, f"{name}: too little history"
        last = pts[-1]
        c = [b["c"] for b in bars]
        return {"symbol": sym, "name": name, "tail": pts, "rs_ratio": last[1], "rs_mom": last[2], "quadrant": quadrant(last[1], last[2]),
                "speed": round(last[2] - pts[-2][2], 2), "chg_1d": round((c[-1] / c[-2] - 1) * 100, 2) if len(c) > 1 else None,
                "chg_1w": round((c[-1] / c[-6] - 1) * 100, 2) if len(c) > 5 else None}, None
    with ThreadPoolExecutor(max_workers=4) as ex:
        for got, err in ex.map(one, SECTORS[mk]):
            if got:
                out.append(got)
            if err:
                errors.append(err)
    lead = sorted([x for x in out if x["quadrant"] == "leading"], key=lambda x: -(x["rs_ratio"] + x["rs_mom"]))
    headline = None
    if lead:
        t = lead[0]
        headline = f"{t['name']} leads {bname} and is {'still gaining speed' if t['speed'] > 0 else 'losing a little speed'}."
    entered = []
    for x in out:
        prevq = quadrant(x["tail"][0][1], x["tail"][0][2])
        if x["quadrant"] == "leading" and prevq != "leading":
            entered.append(x["name"])
    return {"market": mk, "frame": "weekly" if weekly else "daily", "benchmark": bname, "sectors": out, "headline": headline,
            "entered_leading": entered, "errors": errors, "params": {"n": n, "m": m, "tail": tail},
            "source": "Yahoo Finance daily candles of the sector indices" + (" (sector funds)" if mk == "US" else " (NSE sector indices)")}
