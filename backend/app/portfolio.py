"""Portfolio X-ray: every connected broker + uploaded file, merged and checked with EquityLens."""
from __future__ import annotations

import re
import time
from datetime import date, datetime, timedelta

from . import calendars, config, enrich, store, technicals

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
    from . import movers
    mv = store.get_company(movers._key(market))
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
                  "off_high_pct", "piotroski", "fair_value_upside", "dividend_yield", "entry_verdict"):
            r[f] = k.get(f)
        if r.get("dividend_yield") and r.get("value"):
            r["est_dividend"] = round(r["value"] * r["dividend_yield"] / 100.0, 2)
        else:
            r["est_dividend"] = 0.0
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
    est_div = round(sum(r.get("est_dividend") or 0.0 for r in rows), 2)
    div_yield = round(est_div / total * 100, 2) if total else None

    # Fundamental drift & concentration alerts
    drift_hist = (store.get_company("DRIFT::HISTORY") or (0, {}))[1]
    drift = []
    for r in rows:
        d = drift_hist.get(r["symbol"])
        if not d:
            continue
        if isinstance(d.get("prev_business"), (int, float)) and isinstance(d.get("business"), (int, float)):
            diff = round(d["business"] - d["prev_business"])
            if abs(diff) >= 4:
                drift.append({"symbol": r["symbol"], "name": r["name"], "kind": "score",
                              "tone": "good" if diff > 0 else "warn",
                              "text": f"Business score {round(d['prev_business'])} → {round(d['business'])} ({diff:+d} pts)"})
        if d.get("prev_entry") and d.get("entry") and d["prev_entry"] != d["entry"]:
            drift.append({"symbol": r["symbol"], "name": r["name"], "kind": "entry",
                          "tone": "good" if d["entry"] == "ENTER" else "warn",
                          "text": f"Entry signal flipped {d['prev_entry'].title()} → {d['entry'].title()}"})
    for sc in sec:
        if sc["sector"] != "Not scored yet" and sc["weight"] >= 30:
            drift.append({"symbol": None, "name": sc["sector"], "kind": "sector", "tone": "bad",
                          "text": f"{sc['sector']} sector weight {sc['weight']}% (above 25% guideline)"})

    benchmark = _benchmark_series(market, rows, total)

    summary = {
        "value": round(total, 2), "invested": round(invested, 2), "pnl": round(total - invested, 2) if invested else None,
        "pnl_pct": round((total - invested) / invested * 100, 2) if invested else None, "count": len(rows),
        "score": w_score, "business": w_bus, "scored": len(scored), "unscored": [r["symbol"] for r in rows if not r["scored"] and not r["fund"]],
        "funds": [r["symbol"] for r in rows if r["fund"]],
        "sectors": sec, "top5": top5, "warnings": warn, "mix": mix,
        "est_dividend": est_div, "dividend_yield": div_yield, "drift": drift[:8], "benchmark": benchmark,
        "fno": sum(1 for r in rows if r.get("fno")), "results_soon": [{"symbol": r["symbol"], "name": r["name"], "date": r["next_results"]}
                                                                     for r in rows if r.get("next_results")],
        "brokers": sorted({b for r in rows for b in r["brokers"]}),
        "synced": max((r.get("synced") or 0) for r in rows),
    }
    summary["history"] = _history(market, total, invested)
    return {"market": market, "rows": rows, "summary": summary}


def _history(market: str, total: float, invested: float) -> dict:
    """Your portfolio's own value, saved once a day when the portfolio is opened or synced (the latest of the day
    wins). It starts on the first day it was saved; earlier days are never filled in. The index line is the
    market index's close on the same dates, rebased to the portfolio's first saved value."""
    key = f"PFHIST::{market}"
    hit = store.get_company(key)
    days = dict(hit[1]["days"]) if hit else {}
    day = (calendars.us_eastern_now().date() if market == "US" else datetime.now(calendars.IST).date()).isoformat()
    if total:
        days[day] = {"value": round(total, 2), "invested": round(invested or 0, 2)}
        store.put_company(key, {"days": days})
    pts = [{"date": d, **v} for d, v in sorted(days.items())]
    idx_sym, idx_name = ("^GSPC", "S&P 500") if market == "US" else ("^NSEI", "NIFTY 50")
    if len(pts) >= 2 and not config.DEMO:
        try:
            closes = {b["t"][:10]: b["c"] for b in technicals._yahoo(idx_sym, "2y")}
            base = next((closes[p["date"]] for p in pts if p["date"] in closes), None)
            if base:
                for p in pts:
                    if p["date"] in closes:
                        p["index"] = round(pts[0]["value"] * closes[p["date"]] / base, 2)
        except Exception:  # noqa: BLE001
            pass
    return {"points": pts, "since": pts[0]["date"] if pts else None, "index": idx_name}


def _benchmark_series(market: str, rows: list[dict], total: float) -> dict | None:
    """1Y normalized Portfolio vs NIFTY 50 / S&P 500 comparison from cached/demo daily bars."""
    if not rows or not total:
        return None
    idx_sym = "^GSPC" if market == "US" else "^NSEI"
    idx_name = "S&P 500" if market == "US" else "NIFTY 50"
    try:
        idx_bars = technicals._demo(idx_sym)[-252:] if config.DEMO else technicals._yahoo(idx_sym, "1y")
    except Exception:  # noqa: BLE001
        return None
    if len(idx_bars) < 20:
        return None
    idx_bars = idx_bars[-252:]
    idx_dates = [b["t"] for b in idx_bars]
    idx_base = idx_bars[0]["c"] or 1.0
    idx_map = {b["t"]: round((b["c"] / idx_base - 1) * 100, 2) for b in idx_bars}

    # Build weighted portfolio curve from cached daily bars (or demo bars)
    weights = [(r["symbol"], (r.get("value") or 0) / total) for r in rows if (r.get("value") or 0) > 0]
    series_by_sym: dict[str, dict[str, float]] = {}
    covered_w = 0.0
    for sym, w in weights[:25]:
        try:
            if config.DEMO:
                bars = technicals._demo(sym)[-252:]
            else:
                hit = store.get_company(f"TECH::{sym}::1d::v{technicals.CACHE_VERSION}")
                bars = (hit[1].get("bars") if hit else None) or []
            if len(bars) >= 20:
                bmap = {b["t"]: b["c"] for b in bars}
                first = next((bmap[d] for d in idx_dates if d in bmap), None)
                if first and first > 0:
                    series_by_sym[sym] = {d: (bmap[d] / first - 1) * 100 for d in idx_dates if d in bmap}
                    covered_w += w
        except Exception:  # noqa: BLE001
            continue
    if covered_w < 0.2:
        return None

    step = max(1, len(idx_dates) // 30)
    sample_dates = idx_dates[::step]
    if sample_dates[-1] != idx_dates[-1]:
        sample_dates.append(idx_dates[-1])
    pts = []
    last_p = 0.0
    for d in sample_dates:
        num = den = 0.0
        for sym, w in weights:
            sm = series_by_sym.get(sym)
            if sm and d in sm:
                num += sm[d] * w
                den += w
        p_ret = round(num / den, 2) if den > 0 else last_p
        last_p = p_ret
        pts.append({"date": d, "portfolio": p_ret, "benchmark": idx_map.get(d, 0.0)})
    p_1y = pts[-1]["portfolio"]
    b_1y = pts[-1]["benchmark"]
    return {"name": idx_name, "portfolio_1y": p_1y, "benchmark_1y": b_1y,
            "alpha_1y": round(p_1y - b_1y, 2), "covered_pct": round(covered_w * 100), "series": pts}
