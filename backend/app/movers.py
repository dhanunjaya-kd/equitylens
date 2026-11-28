"""Market movers for 🇮🇳 NIFTY 500 and 🇺🇸 S&P 500 + Nasdaq-100 over 1D / 1W / 1M / 3M / 1Y.

🇺🇸 "All US" (every NYSE / Nasdaq / NYSE American stock, ~6-7k) adds Nasdaq's own daily snapshot for the
stocks outside S&P 500 / Nasdaq-100: last sale, day change, volume and market cap only (no daily history),
so for them only 1D moves exist; 52-week, average and pressure fields stay empty (None), never guessed.

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

from . import config, patterns, scanners, store, technicals, universe, us, usuniverse

TF = {"1D": 1, "1W": 5, "1M": 21, "3M": 63, "1Y": 252}
TTL = 6 * 3600
OPEN_TTL = 15 * 60      # while the market is open: a full NIFTY 500 pass takes a few minutes, so every 15 min
STATE: dict = {"IN": {"running": False, "done": 0, "total": 0, "failed": 0, "started": None},
               "US": {"running": False, "done": 0, "total": 0, "failed": 0, "started": None}}
_lock = threading.Lock()


# ------------------------------------------------------------------ universe
def _universe(market: str, which: str = "N500") -> list[dict]:
    if config.DEMO and which == "ALL" and market == "IN":
        return _universe(market) + [{"symbol": f"SMALL{i:02d}", "name": f"Small Co {i:02d}", "industry": "Textiles"} for i in range(1, 11)]
    if config.DEMO:
        sectors = ["IT", "Banks", "Pharma", "Auto", "FMCG", "Metals", "Energy", "Capital Goods"] if market == "IN" else \
                  ["Information Technology", "Financials", "Health Care", "Consumer Discretionary", "Energy", "Industrials"]
        rows = [{"symbol": ("US:" if market == "US" else "") + f"DEMO{i:02d}", "name": f"Demo {('US ' if market == 'US' else '')}Co {i:02d}",
                 "industry": sectors[i % len(sectors)]} for i in range(1, 41)]
        rows.insert(0, {"symbol": "US:TSTUS" if market == "US" else "TESTCO",
                        "name": "Test Corp US" if market == "US" else "Test Industries Ltd", "industry": sectors[0]})
        return rows
    if market == "US":
        sp = [dict(r, idx=["SP500"]) for r in us.sp500_universe(download=True)[0]]
        have = {r["symbol"]: r for r in sp}
        ndx = usuniverse.nasdaq100()
        snap = usuniverse.by_symbol() if ndx else {}
        for x in ndx:
            if x["symbol"] in have:
                have[x["symbol"]]["idx"].append("NDX")
            else:
                sec = (snap.get(x["symbol"]) or {}).get("sector") or "Other"
                sp.append({"symbol": x["symbol"], "name": x["name"], "industry": sec, "idx": ["NDX"]})
        return sp
    return universe.index_list(which) if which == "ALL" else universe.load(download=True)[0]


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


def _last_2y(bars: list[dict]) -> list[dict]:
    """Movers, scanners and their record keep using 2 years (as before the 5-year download)."""
    if not bars:
        return bars
    from datetime import date as _d, timedelta as _td
    cut = (_d.fromisoformat(bars[-1]["t"][:10]) - _td(days=730)).isoformat()
    return [b for b in bars if b["t"][:10] >= cut]


def _bars(sym: str) -> list[dict]:
    if config.DEMO:
        return _demo_bars(sym)
    for attempt in range(2):
        try:
            bars, meta = technicals._yahoo(_yahoo_symbol(sym), "5y", with_meta=True)    # 5 years: weekly patterns + their record
            return technicals.apply_meta(bars, meta)     # long series can lag the latest session
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
    return f"MOVERS::v2::{market}"     # v2: US dates on New York's clock (v1 had a duplicate "Saturday" close)


def refresh(market: str, block: bool = False, which: str = "") -> dict:
    with _lock:
        st = STATE[market]
        if st["running"]:
            return status(market)
        if not which:
            old = store.get_company(f"MOVERS::{market}")
            which = (old[1].get("universe") if old else None) or "N500"
        st.update(running=True, done=0, failed=0, total=0, started=time.time(), universe=which)

    def work():
        try:
            uni = _universe(market, which if market == "IN" else "N500")
            STATE[market]["total"] = len(uni)
            rows: list[dict] = []
            idx_close = _index_closes(market)
            rec_key = f"SCANTEST::{market}::{which if market == 'IN' else 'US'}"
            old_rec = store.get_company(rec_key)
            history = not old_rec or time.time() - old_rec[0] > 20 * 3600     # tested record: once a day is enough
            rec = scanners.Record() if history else None
            rec_lock = threading.Lock()

            prec = patterns.Record()
            prows: list[dict] = []

            def one(u):
                try:
                    full = _bars(u["symbol"])
                    bars = _last_2y(full)
                    r = compute_row(u["symbol"], u.get("name", ""), u.get("industry", ""), bars, market)
                    if r and u.get("idx"):
                        r["idx"] = u["idx"]
                    if r and u.get("sub"):
                        r["sub"] = u["sub"]
                    if r:
                        try:
                            a = scanners.analyse(bars, idx_close, history=history)
                            if a:
                                r["scan"] = {"tags": a["tags"], "ind": a["ind"], "date": a["date"]}
                                if rec is not None:
                                    with rec_lock:
                                        rec.add(u["symbol"], a)
                        except Exception:  # noqa: BLE001 - a scanner problem never loses the mover row
                            pass
                    if r:
                        try:                       # chart patterns, gaps, candlesticks on the full 5 years
                            pa = patterns.analyse(full)
                            with rec_lock:
                                prec.add(pa, full[0]["t"][:10] if full else None, full[-1]["t"][:10] if full else None)
                            if pa["now"] or pa["gaps_now"] or pa["candles_now"]:
                                prows.append({"symbol": u["symbol"], "name": r.get("name"), "sector": r.get("sector"),
                                              "idx": u.get("idx") or [], "close": r.get("price"), "chg": (r.get("ret") or {}).get("1D"),
                                              "date": r.get("date"), "patterns": pa["now"], "gaps": pa["gaps_now"],
                                              "candles": pa["candles_now"], "rvol": r.get("rvol")})
                        except Exception:  # noqa: BLE001 - a pattern problem never loses the mover row
                            pass
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
                _finish_scans(rows, market)
                if rec is not None and rec.stocks:
                    store.put_company(rec_key, dict(rec.finish(), updated=time.time(), index=bool(idx_close)))
                if prec.stocks:
                    store.put_company(f"PATTERNS::{market}", {"rows": prows, "record": prec.finish(), "updated": time.time(),
                                                             "stocks": prec.stocks, "universe": which if market == "IN" else "SP500+NDX"})
                store.put_company(_key(market), {"rows": rows, "updated": time.time(), "count": len(rows),
                                                 "universe": which if market == "IN" else "SP500+NDX"})
        finally:
            STATE[market]["running"] = False

    if block:
        work()
    else:
        threading.Thread(target=work, daemon=True).start()
    return status(market)


INDEX_FOR = {"IN": ("^CRSLDX", "^NSEI"), "US": ("^GSPC",)}     # NIFTY 500 (NIFTY 50 if missing) / S&P 500


def _index_closes(market: str) -> dict:
    """date -> close of the market index, for the RS line. Empty when it cannot be loaded (then RS-line rules are off)."""
    if config.DEMO:
        return {}
    for sym in INDEX_FOR.get(market, ()):
        try:
            bars = technicals._yahoo(sym, "2y")
            if len(bars) > 200:
                return {b["t"][:10]: b["c"] for b in bars}
        except Exception:  # noqa: BLE001
            continue
    return {}


def _finish_scans(rows: list[dict], market: str) -> None:
    """Across the list: RS rating, then the RS-based tags (Minervini >= 70, Leader >= 90), and the results mark."""
    rs = scanners.rs_ratings({r["symbol"]: (r.get("scan") or {}).get("ind", {}).get("wperf") for r in rows})
    results: set = set()
    try:
        from datetime import date as _d, timedelta as _td
        from . import calendars
        day = calendars.us_eastern_now().date() if market == "US" else _d.today()
        got = calendars.earnings(market, day - _td(days=3), 4)
        results = {x["symbol"] for x in got.get("rows", [])}
    except Exception:  # noqa: BLE001
        pass
    for r in rows:
        sc = r.get("scan")
        if not sc:
            continue
        rr = rs.get(r["symbol"])
        sc["ind"]["rs"] = rr
        tags = [t for t in sc["tags"] if not t.endswith("_pre")]
        if "minervini_pre" in sc["tags"] and rr is not None and rr >= 70:
            tags.append("minervini")
        if "leader_pre" in sc["tags"] and rr is not None and rr >= 90:
            tags.append("leader")
        sc["tags"] = sorted(tags)
        sc["results"] = "gap_up" in tags and r["symbol"] in results
        sc["ind"].pop("wperf", None)


def status(market: str) -> dict:
    return dict(STATE[market], market=market)


# ------------------------------------------------------------------ reading
def _mood(rows: list[dict], tf: str) -> dict:
    rs = [r["ret"].get(tf) for r in rows if r["ret"].get(tf) is not None]
    if not rs:
        return {}
    adv = sum(1 for x in rs if x > 0)
    dec = sum(1 for x in rs if x < 0)
    hist = [r for r in rows if r.get("above200") is not None]      # stocks with daily history (not snapshot-only)
    a200 = sum(1 for r in hist if r["above200"]) / len(hist) * 100 if hist else None
    a50 = sum(1 for r in hist if r["above50"]) / len(hist) * 100 if hist else None
    nh = sum(1 for r in hist if r["new_high"])
    nl = sum(1 for r in hist if r["new_low"])
    near_hi = sum(1 for r in hist if (r["from_hi"] or -99) >= -5)
    near_lo = sum(1 for r in hist if (r["from_lo"] or 99) <= 5)
    med = statistics.median(rs)
    spread = {"1D": 2, "1W": 4, "1M": 8, "3M": 15, "1Y": 30}[tf]
    parts = [adv / max(adv + dec, 1) * 100, max(0, min(100, 50 + med / spread * 50))]
    if hist:
        parts += [a200, a50, (near_hi / max(near_hi + near_lo, 1)) * 100]
    score = round(sum(parts) / len(parts))
    label = ("Extreme fear" if score < 25 else "Fear" if score < 45 else "Neutral" if score <= 55
             else "Greed" if score <= 75 else "Extreme greed")
    tone = {"Extreme fear": "bad", "Fear": "warn", "Neutral": "neutral", "Greed": "ok", "Extreme greed": "good"}[label]
    read = f"{adv} stocks rose and {dec} fell over {tf}."
    if hist:
        of = f" (of the {len(hist)} with daily history)" if len(hist) < len(rows) else ""
        read += (f" {a200:.0f}%{of} trade above their 200-day average "
                 f"({'a healthy long-term trend' if a200 >= 60 else 'a weak long-term trend' if a200 < 40 else 'a mixed trend'}). "
                 f"{nh} hit a fresh 52-week high today and {nl} a fresh low.")
    return {"score": score, "label": label, "tone": tone, "advances": adv, "declines": dec, "unchanged": len(rs) - adv - dec,
            "above200": round(a200) if a200 is not None else None, "above50": round(a50) if a50 is not None else None,
            "new_highs": nh, "new_lows": nl, "median": round(med, 2), "read": read, "with_history": len(hist), "count": len(rows)}


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


def snapshot_row(x: dict) -> dict:
    """A Nasdaq-snapshot stock (no daily history): only what Nasdaq states."""
    pct = x.get("chg_pct")
    val = round(x["price"] * x["volume"] / 1e6, 2) if x.get("price") and x.get("volume") else None
    return {"symbol": x["symbol"], "name": x["name"], "sector": x.get("sector") or "Other", "market": "US",
            "price": x.get("price"), "open": None, "high": None, "low": None,
            "ret": {tf: (pct if tf == "1D" else None) for tf in TF}, "pressure": {}, "turnover": {"1D": val},
            "vol_change": {}, "hi52": None, "lo52": None, "from_hi": None, "from_lo": None, "new_high": None, "new_low": None,
            "vol": x.get("volume"), "rvol": None, "above50": None, "above200": None, "closed_high": False, "closed_low": False,
            "spark": [], "spark_t": [], "date": None, "snapshot": True, "idx": [], "exchange": x.get("exchange"),
            "mcap_nasdaq": x.get("market_cap")}


_NO_SCAN_TRIED: dict = {}


def is_stale(market: str, hit=None) -> bool:
    """Saved prices are out of date: none yet, older than the TTL, a market close since, 15 min old in market hours,
    saved before Nasdaq-100 / scanners existed."""
    meta = _meta(hit) if hit is not None else _saved_meta(market)
    now = time.time()
    us_mkt = market == "US"
    if meta is None:
        return True
    ts = meta["ts"]
    return (now - ts > TTL) or technicals._last_close_after(ts, now, us_mkt) \
        or ((not us_mkt) and technicals._market_open(now) and now - ts > OPEN_TTL) \
        or (us_mkt and meta["universe"] != "SP500+NDX") \
        or (meta["rows"] and not meta["scan"]
            and now - _NO_SCAN_TRIED.get(market, 0) > 6 * 3600)          # saved before scanners existed: reload once


_meta_memo: dict = {}


def _meta(hit) -> Optional[dict]:
    if not hit:
        return None
    data = hit[1] or {}
    rows = data.get("rows") or []
    return {"ts": hit[0], "universe": data.get("universe"), "rows": bool(rows), "scan": any("scan" in r for r in rows[:20])}


def _saved_meta(market: str) -> Optional[dict]:
    """The few facts is_stale needs, worked out once per save: the scan status asks every few seconds."""
    key = _key(market)
    t = store.stamp(key)
    if t is None:
        return None
    m = _meta_memo.get(key)
    if m and m["ts"] == t:
        return m
    m = _meta(store.get_company(key))
    if m:
        _meta_memo[key] = m
    return m


def get(market: str, tf: str = "1D", which: str = "") -> dict:
    market = market.upper()
    tf = tf if tf in TF else "1D"
    hit = store.get_company(_key(market))
    data = hit[1] if hit else None
    now = time.time()
    if is_stale(market, hit) and not STATE[market]["running"]:
        from . import automation
        if automation.allowed(f"prices_{market.lower()}"):          # Manual mode: only "Run now" loads prices
            if data and data.get("rows") and not any("scan" in r for r in data["rows"][:20]):
                _NO_SCAN_TRIED[market] = now
            refresh(market)
    rows = data["rows"] if data else []
    loaded = (data or {}).get("universe") or ("N500" if market == "IN" else "SP500")
    if market == "IN":
        from . import sectors
        member = universe.membership()
        smap = sectors.sector_map()
        for r in rows:
            r["idx"] = member.get(r["symbol"], [])
            r["sector"] = smap.get(r["symbol"]) or (r["sector"] if r["sector"] not in ("", "Other") else sectors.UNKNOWN)
        if which in ("N50", "N100", "N500"):
            rows = [r for r in rows if which in r["idx"]]
    snap_info = None
    if market == "US":
        for r in rows:
            r.setdefault("idx", ["SP500"])               # rows saved before Nasdaq-100 was added came from the S&P 500 list
        which = which if which in ("SP500", "NDX", "ALL") else "SP500"
        lst = usuniverse.listed() if which == "ALL" else {"rows": usuniverse_rows_cached()}
        caps = {x["symbol"]: x.get("market_cap") for x in lst["rows"]}
        for r in rows:
            r["mcap_nasdaq"] = caps.get(r["symbol"])
        if which in ("SP500", "NDX"):
            rows = [r for r in rows if which in r["idx"]]
        else:
            have = {r["symbol"] for r in rows}
            rows = rows + [snapshot_row(x) for x in lst["rows"] if x["symbol"] not in have]
            snap_info = {"updated": lst.get("updated"), "sources": lst.get("sources", []), "snapshot": sum(1 for r in rows if r.get("snapshot"))}
        loaded = which
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
    session = max((r.get("date") or "" for r in rows), default="") or None
    live = (market == "IN" and session == technicals.dt.datetime.fromtimestamp(now, technicals.IST).date().isoformat()
            and technicals._market_open(now))
    return {"market": market, "tf": tf, "rows": rows, "updated": data["updated"] if data else None,
            "session": session, "live": live,
            "mood": _mood(rows, tf) if rows else None, "sectors": _sectors(rows, tf) if rows else [],
            "status": status(market), "scanned": len(ranks), "universe": loaded, "count": len(rows), "snapshot": snap_info}


def usuniverse_rows_cached() -> list[dict]:
    hit = store.get_company("USUNIV::listed")
    return hit[1]["rows"] if hit else []
