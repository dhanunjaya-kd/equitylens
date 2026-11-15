"""Portfolio X-ray: every connected broker + uploaded file, merged and checked with EquityLens."""
from __future__ import annotations

import re
import time
from datetime import date, datetime, timedelta

from . import calendars, enrich, store

HOLD_KEYS = ("zerodha", "upstox", "fyers", "angel", "dhan", "alpaca", "tradier", "schwab", "file")


def merged(market: str) -> list[dict]:
    """Same stock held at two brokers → one row (quantities added, average cost weighted)."""
    by: dict = {}
    for bid in HOLD_KEYS:
        hit = store.get_company(f"PORTFOLIO::{bid}")
        for h in (hit[1]["rows"] if hit else []):
            if h["market"] != market:
                continue
            r = by.get(h["symbol"])
            if not r:
                by[h["symbol"]] = {**h, "brokers": [h["broker"]], "synced": hit[0]}
                continue
            q = r["qty"] + h["qty"]
            if r.get("avg") and h.get("avg"):
                r["avg"] = (r["avg"] * r["qty"] + h["avg"] * h["qty"]) / q
            r["qty"] = q
            r["ltp"] = r.get("ltp") or h.get("ltp")
            r["brokers"] = sorted(set(r["brokers"] + [h["broker"]]))
    return list(by.values())


def _price_maps(market: str) -> dict:
    mv = store.get_company(f"MOVERS::{market}")
    return {r["symbol"]: (r.get("spark") or [None])[-1] for r in (mv[1]["rows"] if mv else [])}


FUND_RE = re.compile(r"(BEES$|ETF|^SGB|IETF$|GOLD.?BOND|LIQUID|INAV)", re.I)


def is_fund(sym: str, name: str = "") -> bool:
    """ETFs, gold bonds and index funds have no company financials to score."""
    s = sym.replace("US:", "")
    return bool(FUND_RE.search(s) or re.search(r"\b(ETF|Gold Bond|Index Fund|Trust)\b", name or "", re.I))


def xray(market: str) -> dict:
    market = market.upper()
    rows = merged(market)
    if not rows:
        return {"market": market, "rows": [], "summary": None}
    ranks = {r["symbol"]: r for r in store.all_rankings() if r.get("market", "IN") == market}
    px = _price_maps(market)
    maps = enrich.live_maps(market)
    today = datetime.now(calendars.IST).date()
    ns = store.get_company("PORTFOLIO_NOSCORE")
    no_score = set(ns[1]["symbols"]) if ns else set()
    for r in rows:
        k = ranks.get(r["symbol"]) or {}
        r["ltp"] = r.get("ltp") or px.get(r["symbol"]) or k.get("price")
        r["value"] = round(r["qty"] * r["ltp"], 2) if r.get("ltp") else None
        r["invested"] = round(r["qty"] * r["avg"], 2) if r.get("avg") else None
        r["pnl"] = round(r["value"] - r["invested"], 2) if r["value"] is not None and r["invested"] else None
        r["pnl_pct"] = round(r["pnl"] / r["invested"] * 100, 2) if r["pnl"] is not None and r["invested"] else None
        for f in ("overall", "business", "valuation", "verdict", "tone", "sector", "high_flags", "pledged", "pe", "market_cap",
                  "off_high_pct", "piotroski", "fair_value_upside"):
            r[f] = k.get(f)
        if k.get("name"):
            r["name"] = k["name"]
        r["scored"] = bool(k)
        r["fund"] = not k and (is_fund(r["symbol"], r.get("name", "")) or r["symbol"] in no_score)
        enrich.join(r, maps)
        nr = calendars.next_results(r["symbol"])
        r["next_results"] = nr["date"] if nr and nr["date"] <= (today + timedelta(days=45)).isoformat() else None
    total = sum(r["value"] or 0 for r in rows)
    invested = sum(r["invested"] or 0 for r in rows if r["value"] is not None)
    for r in rows:
        r["weight"] = round((r["value"] or 0) / total * 100, 2) if total else None
    rows.sort(key=lambda r: -(r["value"] or 0))

    scored = [r for r in rows if r["scored"] and r.get("overall") is not None and r["value"]]
    sw = sum(r["value"] for r in scored)
    w_score = round(sum(r["overall"] * r["value"] for r in scored) / sw) if sw else None
    w_bus = round(sum((r.get("business") or 0) * r["value"] for r in scored) / sw) if sw else None
    sectors: dict = {}
    for r in rows:
        s = r.get("sector") or "Not scored yet"
        sectors[s] = sectors.get(s, 0) + (r["weight"] or 0)
    sec = sorted(({"sector": k, "weight": round(v, 1)} for k, v in sectors.items()), key=lambda x: -x["weight"])
    top5 = round(sum(r["weight"] or 0 for r in rows[:5]), 1)

    warn = []
    for r in rows:
        why = []
        if r.get("surveillance"):
            why.append("🚨 " + ", ".join(r.get("surv_labels") or ["NSE surveillance"]))
        if (r.get("high_flags") or 0) > 0:
            why.append(f"🚩 {r['high_flags']} serious red flag{'s' if r['high_flags'] > 1 else ''}")
        if (r.get("pledged") or 0) >= 10:
            why.append(f"🔒 promoter pledge {r['pledged']}%")
        if r.get("tone") == "bad":
            why.append(f"verdict: {r.get('verdict')}")
        if (r.get("weight") or 0) >= 25:
            why.append(f"⚖️ {r['weight']}% of the portfolio in one stock")
        if why:
            warn.append({"symbol": r["symbol"], "name": r["name"], "why": why, "weight": r["weight"]})
    if market == "IN":
        mix = {"NIFTY 50": 0.0, "NIFTY 51–100": 0.0, "NIFTY 101–500": 0.0, "Outside NIFTY 500": 0.0}
        for r in rows:
            idx = r.get("idx") or []
            key = "NIFTY 50" if "N50" in idx else "NIFTY 51–100" if "N100" in idx else "NIFTY 101–500" if "N500" in idx else "Outside NIFTY 500"
            mix[key] += r["weight"] or 0
        mix = {k: round(v, 1) for k, v in mix.items()}
    else:
        mix = None
    summary = {
        "value": round(total, 2), "invested": round(invested, 2), "pnl": round(total - invested, 2) if invested else None,
        "pnl_pct": round((total - invested) / invested * 100, 2) if invested else None, "count": len(rows),
        "score": w_score, "business": w_bus, "scored": len(scored), "unscored": [r["symbol"] for r in rows if not r["scored"] and not r["fund"]],
        "funds": [r["symbol"] for r in rows if r["fund"]],
        "sectors": sec, "top5": top5, "warnings": warn, "mix": mix,
        "fno": sum(1 for r in rows if r.get("fno")), "results_soon": [{"symbol": r["symbol"], "name": r["name"], "date": r["next_results"]}
                                                                     for r in rows if r.get("next_results")],
        "brokers": sorted({b for r in rows for b in r["brokers"]}),
        "synced": max((r.get("synced") or 0) for r in rows),
    }
    return {"market": market, "rows": rows, "summary": summary}
