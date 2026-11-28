"""💰 Money flow: which groups of stocks money is going into and out of, from exchange data only.

🇮🇳 India - NSE's daily bhavcopy with deliverable quantity (sec_bhavdata_full), last 5 sessions:
    a stock's day flow = shares actually delivered × close, counted + on an up day (close above the previous
    close), − on a down day, 0 when unchanged. The exchange does not publish who bought or sold, so this is an
    estimate of direction, stated as such in the app. "Delivery vs before" = delivered value of the last 5
    sessions ÷ the 5 before them.
🇺🇸 US - no delivery data exists, so the same rule uses traded value (close × volume) from the daily bars.

Groups are NSE's own four-level classification (macro-economic sector, sector, industry, basic industry,
from NSE's quote data) - US: GICS sector and GICS sub-industry (S&P 500 list) or Nasdaq's industry.
Price strength per group is the median of its stocks' 1W / 1M / 3M / 6M moves.

Flow score 0-100 (per level, among groups with enough stocks) = average of four percentile ranks:
net 5-day flow as a share of the group's delivered (US: traded) value over 10 sessions · delivery vs before ·
median 1W move · median 1M move. Higher = more money coming in, with price confirming.
The page receives every stock with its numbers, so filters (F&O, turnover, ADR, price, distance from the
52-week high / low, market cap) regroup on the spot.
"""
from __future__ import annotations

import time
from typing import Optional

from . import config, flows, movers, sectors, store

LEVELS_IN = [("macro", "Macro sector"), ("sector", "Sector"), ("industry", "Industry"), ("basic", "Basic industry")]
LEVELS_US = [("sector", "Sector (GICS)"), ("industry", "Industry")]


def _delivery_flows(n: int = 10) -> tuple[dict, list[str]]:
    """{symbol: {"flow5", "val5", "val_prev5", "days"}} in ₹ (not crore) from the last n bhavcopies."""
    days = flows.delivery_days(n)
    out: dict[str, dict] = {}
    for k, (d, rows) in enumerate(days):            # newest first
        for sym, t in rows.items():
            dq, c, p = t.get("dq"), t.get("close"), t.get("prev")
            if not dq or not c:
                continue
            v = dq * c
            o = out.setdefault(sym, {"flow5": 0.0, "val5": 0.0, "val_prev5": 0.0, "days5": 0})
            if k < 5:
                o["val5"] += v
                o["days5"] += 1
                if p:
                    o["flow5"] += v if c > p else -v if c < p else 0.0
            else:
                o["val_prev5"] += v
    return out, [d for d, _ in days]


def get(market: str = "IN", which: str = "") -> dict:
    mk = market.upper()
    d = movers.get(mk, "1W", which.upper())
    rows = [r for r in d.get("rows", []) if r.get("scan")]
    cls, deliv, ddays, missing = {}, {}, [], 0
    lookup = None
    if mk == "IN":
        cls = sectors.classes()
        try:
            deliv, ddays = _delivery_flows(10)
        except Exception:  # noqa: BLE001
            deliv, ddays = {}, []
        need = [r["symbol"] for r in rows if r["symbol"] not in cls]
        missing = len(need)
        from . import automation
        if need:
            lookup = sectors.start_fill(need) if automation.allowed("classify_in") else sectors.status()
        sh = sectors.shares()
    else:
        from . import usuniverse
        snap = usuniverse.by_symbol()
    out = []
    for r in rows:
        sym = r["symbol"]
        ind = r["scan"]["ind"]
        f = r.get("fund") or {}
        if mk == "IN":
            c = cls.get(sym)
            if not c:
                continue
            dv = deliv.get(sym)
            flow = {"flow5": dv["flow5"] / 1e7, "val5": dv["val5"] / 1e7, "prev5": dv["val_prev5"] / 1e7} if dv and dv["days5"] >= 3 else None
            mcap = f.get("market_cap") or (round(sh[sym] * r["price"] / 1e7, 0) if sh.get(sym) and r.get("price") else None)
            groups = {k: c.get(k) for k, _ in LEVELS_IN}
        else:
            flow = ({"flow5": ind["flow5"] / 1e6, "val5": ind["val5"] / 1e6, "prev5": ind["val_prev5"] / 1e6}
                    if ind.get("val5") else None)
            mcap = f.get("market_cap") or r.get("mcap_nasdaq")
            groups = {"sector": r.get("sector"), "industry": r.get("sub") or (snap.get(sym) or {}).get("industry")}
        out.append({"symbol": sym, "name": r["name"], "g": groups, "price": r["price"], "fno": r.get("fno"),
                    "r1d": r["ret"].get("1D"), "r1w": r["ret"].get("1W"), "r1m": r["ret"].get("1M"), "r3m": r["ret"].get("3M"),
                    "r6m": ind.get("r6m"), "adr": ind.get("adr"), "turn": round(ind["turn20"] / (1e7 if mk == "IN" else 1e6), 2) if ind.get("turn20") else None,
                    "from_hi": r.get("from_hi"), "from_lo": r.get("from_lo"), "mcap": mcap, "rs": ind.get("rs"),
                    "tags": r["scan"].get("tags", []), "spark": r.get("spark", [])[-40:],
                    "flow": {k: round(v, 2) for k, v in flow.items()} if flow else None})
    return {"market": mk, "universe": d.get("universe"), "session": d.get("session"), "updated": d.get("updated"),
            "levels": [{"key": k, "label": l} for k, l in (LEVELS_IN if mk == "IN" else LEVELS_US)],
            "stocks": out, "unit": "₹ Cr" if mk == "IN" else "$ M",
            "flow_days": ddays[:5] if mk == "IN" else None, "unclassified": missing,
            "lookup": lookup, "status": d.get("status"),
            "method": ("Delivered shares × close, + on up days and − on down days, last 5 sessions (NSE bhavcopy). "
                       "An estimate of direction: exchanges do not publish who bought or sold.") if mk == "IN" else
                      ("Traded value (close × volume), + on up days and − on down days, last 5 sessions (daily prices). "
                       "US exchanges publish no delivery data; an estimate of direction, not who bought or sold.")}
