"""Market movers for 🇮🇳 NIFTY 500 and 🇺🇸 S&P 500 over 1D / 1W / 1M / 3M / 1Y.

One background refresh pulls ~2 years of daily bars for every stock in the
universe (Yahoo Finance, paced), then computes per stock and per timeframe:
  return · 52-week high/low distance and fresh highs/lows · relative volume ·
  volume change vs normal · buying/selling pressure (volume on up vs down days;
  for 1D the close's position in the day's range) · traded value · trend vs
  50/200-day averages.
It also builds market breadth ("market mood"), a sector heatmap, and joins each
stock with its EquityLens fundamental score when the stock has been scanned.
"""
from __future__ import annotations

import math
import random
import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from . import config, store, technicals, universe, us

TF = {"1D": 1, "1W": 5, "1M": 21, "3M": 63, "1Y": 252}
TTL = 6 * 3600
STATE: dict = {"IN": {"running": False, "done": 0, "total": 0, "failed": 0, "started": None},
               "US": {"running": False, "done": 0, "total": 0, "failed": 0, "started": None}}
_lock = threading.Lock()


# ------------------------------------------------------------------ universe
def _universe(market: str) -> list[dict]:
    if config.DEMO:
        sectors = ["IT", "Banks", "Pharma", "Auto", "FMCG", "Metals", "Energy", "Capital Goods"] if market == "IN" else \
                  ["Information Technology", "Financials", "Health Care", "Consumer Discretionary", "Energy", "Industrials"]
        rows = [{"symbol": ("US:" if market == "US" else "") + f"DEMO{i:02d}", "name": f"Demo {('US ' if market == 'US' else '')}Co {i:02d}",
                 "industry": sectors[i % len(sectors)]} for i in range(1, 41)]
        rows.insert(0, {"symbol": "US:TSTUS" if market == "US" else "TESTCO",
                        "name": "Test Corp US" if market == "US" else "Test Industries Ltd", "industry": sectors[0]})
        return rows
    if market == "US":
        return us.sp500_universe(download=True)[0]
    return universe.load(download=True)[0]


def _yahoo_symbol(sym: str) -> str:
    return sym[3:] if sym.startswith("US:") else f"{sym}.NS"


def _demo_bars(sym: str) -> list[dict]:
    bars = technicals._demo(sym)[-520:]
    rnd = random.Random(sym + "x")
    k = 1.0 if sym in ("TESTCO", "US:TSTUS") else rnd.uniform(0.05, 2.5)
    drift = 0.0 if sym in ("TESTCO", "US:TSTUS") else rnd.uniform(-0.0012, 0.0012)
    out = []
    for i, b in enumerate(bars):
        f = k * math.exp(drift * i)
        out.append({**b, "o": b["o"] * f, "h": b["h"] * f, "l": b["l"] * f, "c": b["c"] * f,
                    "v": int(b["v"] * (rnd.uniform(2.5, 6) if i == len(bars) - 1 and rnd.random() < 0.2 else 1))})
    return out


def _bars(sym: str) -> list[dict]:
    if config.DEMO:
        return _demo_bars(sym)
    for attempt in range(2):
        try:
            return technicals._yahoo(_yahoo_symbol(sym), "2y")
        except Exception:  # noqa: BLE001
            if attempt:
                raise
            time.sleep(3)
    return []


# ------------------------------------------------------------------ per stock
def _pct(a, b):
    return round((a / b - 1) * 100, 2) if a and b and b > 0 else None


def compute_row(sym: str, name: str, sector: str, bars: list[dict], market: str) -> Optional[dict]:
    if len(bars) < 30:
        return None
    c = [b["c"] for b in bars]
    h = [b["h"] for b in bars]
    l = [b["l"] for b in bars]
    o = [b["o"] for b in bars]
    v = [b["v"] or 0 for b in bars]
    n = len(c)
    i = n - 1
    per = 1e7 if market == "IN" else 1e6       # traded value in ₹ Cr / $ M
    yr = min(252, n - 1)
    hi52, lo52 = max(h[-yr - 1:]), min(l[-yr - 1:])
    prev_hi, prev_lo = max(h[-yr - 1:-1]), min(l[-yr - 1:-1])
    avg20 = sum(v[-21:-1]) / 20 if n > 21 else None
    rvol = round(v[i] / avg20, 2) if avg20 else None
    sma = lambda k: sum(c[-k:]) / k if n >= k else None
    s50, s200 = sma(50), sma(200)

    ret, press, turn, volchg = {}, {}, {}, {}
    for tf, k in TF.items():
        if n > k:
            ret[tf] = _pct(c[i], c[i - k])
        else:
            ret[tf] = None
        if tf == "1D":
            rng = h[i] - l[i]
            press[tf] = round(((c[i] - l[i]) - (h[i] - c[i])) / rng, 2) if rng > 0 else 0.0
        else:
            up = sum(v[j] for j in range(max(1, n - k), n) if c[j] > c[j - 1])
            dn = sum(v[j] for j in range(max(1, n - k), n) if c[j] < c[j - 1])
            press[tf] = round((up - dn) / (up + dn), 2) if up + dn else 0.0
        w = range(max(0, n - k), n)
        turn[tf] = round(sum(c[j] * v[j] for j in w) / len(w) / per, 2)
        base = v[max(0, n - k - 63):max(0, n - k)]
        if tf != "1D" and base and sum(base):
            volchg[tf] = round((sum(v[j] for j in w) / len(w)) / (sum(base) / len(base)), 2)
        else:
            volchg[tf] = rvol
    return {
        "symbol": sym, "name": name or sym.replace("US:", ""), "sector": sector or "Other", "market": market,
        "price": round(c[i], 2), "open": round(o[i], 2), "high": round(h[i], 2), "low": round(l[i], 2),
        "ret": ret, "pressure": press, "turnover": turn, "vol_change": volchg,
        "hi52": round(hi52, 2), "lo52": round(lo52, 2),
        "from_hi": _pct(c[i], hi52), "from_lo": _pct(c[i], lo52),
        "new_high": h[i] >= prev_hi, "new_low": l[i] <= prev_lo,
        "vol": v[i], "rvol": rvol,
        "above50": bool(s50 and c[i] > s50), "above200": bool(s200 and c[i] > s200),
        "closed_high": c[i] >= h[i] * 0.997 and (ret.get("1D") or 0) > 1.5,
        "closed_low": c[i] <= l[i] * 1.003 and (ret.get("1D") or 0) < -1.5,
        "spark": [round(x, 2) for x in c[-40:]],
        "spark_t": [b["t"] for b in bars[-40:]],
        "date": bars[-1]["t"],
    }


# ------------------------------------------------------------------ refresh
def _key(market: str) -> str:
    return f"MOVERS::{market}"


def refresh(market: str, block: bool = False) -> dict:
    with _lock:
        st = STATE[market]
        if st["running"]:
            return status(market)
        st.update(running=True, done=0, failed=0, total=0, started=time.time())

    def work():
        try:
            uni = _universe(market)
            STATE[market]["total"] = len(uni)
            rows: list[dict] = []

            def one(u):
                try:
                    r = compute_row(u["symbol"], u.get("name", ""), u.get("industry", ""), _bars(u["symbol"]), market)
                    if r:
                        rows.append(r)
                    else:
                        STATE[market]["failed"] += 1
                except Exception:  # noqa: BLE001
                    STATE[market]["failed"] += 1
                finally:
                    STATE[market]["done"] += 1
                    if not config.DEMO:
                        time.sleep(0.35)

            with ThreadPoolExecutor(max_workers=1 if config.DEMO else 3) as ex:
                list(ex.map(one, uni))
            if rows:
                store.put_company(_key(market), {"rows": rows, "updated": time.time(), "count": len(rows)})
        finally:
            STATE[market]["running"] = False

    if block:
        work()
    else:
        threading.Thread(target=work, daemon=True).start()
    return status(market)


def status(market: str) -> dict:
    return dict(STATE[market], market=market)


# ------------------------------------------------------------------ reading
def _mood(rows: list[dict], tf: str) -> dict:
    rs = [r["ret"].get(tf) for r in rows if r["ret"].get(tf) is not None]
    if not rs:
        return {}
    adv = sum(1 for x in rs if x > 0)
    dec = sum(1 for x in rs if x < 0)
    a200 = sum(1 for r in rows if r["above200"]) / len(rows) * 100
    a50 = sum(1 for r in rows if r["above50"]) / len(rows) * 100
    nh = sum(1 for r in rows if r["new_high"])
    nl = sum(1 for r in rows if r["new_low"])
    near_hi = sum(1 for r in rows if (r["from_hi"] or -99) >= -5)
    near_lo = sum(1 for r in rows if (r["from_lo"] or 99) <= 5)
    med = statistics.median(rs)
    spread = {"1D": 2, "1W": 4, "1M": 8, "3M": 15, "1Y": 30}[tf]
    parts = [adv / max(adv + dec, 1) * 100, a200, a50,
             (near_hi / max(near_hi + near_lo, 1)) * 100, max(0, min(100, 50 + med / spread * 50))]
    score = round(sum(parts) / len(parts))
    label = ("Extreme fear" if score < 25 else "Fear" if score < 45 else "Neutral" if score <= 55
             else "Greed" if score <= 75 else "Extreme greed")
    tone = {"Extreme fear": "bad", "Fear": "warn", "Neutral": "neutral", "Greed": "ok", "Extreme greed": "good"}[label]
    read = (f"{adv} stocks rose and {dec} fell over {tf}. {a200:.0f}% trade above their 200-day average "
            f"({'a healthy long-term trend' if a200 >= 60 else 'a weak long-term trend' if a200 < 40 else 'a mixed trend'}). "
            f"{nh} hit a fresh 52-week high today and {nl} a fresh low.")
    return {"score": score, "label": label, "tone": tone, "advances": adv, "declines": dec, "unchanged": len(rs) - adv - dec,
            "above200": round(a200), "above50": round(a50), "new_highs": nh, "new_lows": nl, "median": round(med, 2), "read": read}


def _sectors(rows: list[dict], tf: str) -> list[dict]:
    by: dict[str, list] = {}
    for r in rows:
        if r["ret"].get(tf) is not None:
            by.setdefault(r["sector"], []).append(r)
    out = []
    for sec, rs in by.items():
        vals = [r["ret"][tf] for r in rs]
        best = max(rs, key=lambda r: r["ret"][tf])
        worst = min(rs, key=lambda r: r["ret"][tf])
        out.append({"sector": sec, "count": len(rs), "avg": round(sum(vals) / len(vals), 2),
                    "up": sum(1 for x in vals if x > 0), "best": {"symbol": best["symbol"], "name": best["name"], "ret": best["ret"][tf]},
                    "worst": {"symbol": worst["symbol"], "name": worst["name"], "ret": worst["ret"][tf]}})
    out.sort(key=lambda x: -x["avg"])
    return out


def get(market: str, tf: str = "1D") -> dict:
    market = market.upper()
    tf = tf if tf in TF else "1D"
    hit = store.get_company(_key(market))
    data = hit[1] if hit else None
    stale = (not hit) or (time.time() - hit[0] > TTL)
    if stale and not STATE[market]["running"]:
        refresh(market)
    rows = data["rows"] if data else []
    ranks = {r["symbol"]: r for r in store.all_rankings() if r.get("market", "IN") == market}
    dl = store.get_company("DELIVERY::IN") if market == "IN" else None
    dmap = {x["symbol"]: x for x in (dl[1]["rows"] if dl else [])}
    sv = store.get_company("SURV::IN") if market == "IN" else None
    smap = sv[1]["flags"] if sv else {}
    from . import enrich
    lots = enrich.fno() if market == "IN" else {}
    for r in rows:
        r["fno"] = r["symbol"] in lots
        dx = dmap.get(r["symbol"])
        r["deliv"] = {"dp": dx["dp"], "dq_x": dx["dq_x"], "avg_dp": dx["avg_dp"]} if dx else None
        r["surv"] = [f["label"] for f in smap.get(r["symbol"], [])] or None
        k = ranks.get(r["symbol"])
        r["fund"] = ({"overall": k.get("overall"), "business": k.get("business"), "verdict": k.get("verdict"),
                      "tone": k.get("tone"), "market_cap": k.get("market_cap"), "high_flags": k.get("high_flags"),
                      "pe": k.get("pe")} if k else None)
    return {"market": market, "tf": tf, "rows": rows, "updated": data["updated"] if data else None,
            "mood": _mood(rows, tf) if rows else None, "sectors": _sectors(rows, tf) if rows else [],
            "status": status(market), "scanned": len(ranks)}
