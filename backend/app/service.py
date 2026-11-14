"""Glue: fetch -> parse -> cache -> analyse. Also runs the universe scan."""
from __future__ import annotations

import logging
import random
import statistics
import threading
import time
from typing import Optional

from . import analysis, config, parser, scraper, store, universe

log = logging.getLogger("equitylens")


# ----------------------------------------------------------------- fetching
def _downsample(points: list, max_points: int = 600) -> list:
    if len(points) <= max_points:
        return points
    step = len(points) / max_points
    out = [points[int(i * step)] for i in range(max_points)]
    if out[-1] is not points[-1]:
        out.append(points[-1])
    return out


def _fetch_extras(company: dict, view: str, full: bool) -> dict:
    """Optional extras. Each one may fail on its own without breaking the report."""
    extras: dict = {"errors": []}
    cid, wid = company.get("company_id"), company.get("warehouse_id")
    cons = view == "consolidated"
    if cid:
        try:
            pe = parser.parse_chart(scraper.fetch_chart(cid, "Price to Earning-Median PE-EPS", 3650, cons))
            extras["pe_chart"] = {k: _downsample(v, 400) for k, v in pe.items()}
        except Exception as e:  # noqa: BLE001
            extras["errors"].append(f"P/E history: {e}")
    if full and cid:
        try:
            pc = parser.parse_chart(scraper.fetch_chart(cid, "Price-DMA50-DMA200-Volume", 3650, cons))
            extras["price_chart"] = {k: _downsample(v, 700) for k, v in pc.items() if k != "Volume"}
        except Exception as e:  # noqa: BLE001
            extras["errors"].append(f"Price history: {e}")
    if full and wid:
        try:
            extras["peers"] = parser.parse_peers(scraper.fetch_peers_html(wid))
        except Exception as e:  # noqa: BLE001
            extras["errors"].append(f"Peers: {e}")
    extras["full"] = full
    return extras


def fetch_payload(symbol: str, full: bool = True) -> dict:
    sym = scraper.clean_symbol(symbol)
    html, view = scraper.fetch_company_html(sym)
    company = parser.parse_company(html, sym)
    if not company["tables"]["profit_loss"]["rows"]:
        raise scraper.FetchError(f"No financial data found for {sym}. Check the symbol.")
    extras = _fetch_extras(company, view, full)
    return {"symbol": sym, "view": view, "company": company, "extras": extras}


def get_payload(symbol: str, refresh: bool = False, full: bool = True, max_age_h: Optional[float] = None) -> tuple[dict, float]:
    sym = scraper.clean_symbol(symbol)
    max_age = (config.CACHE_TTL_HOURS if max_age_h is None else max_age_h) * 3600
    cached = store.get_company(sym)
    if cached and not refresh:
        ts, payload = cached
        fresh = time.time() - ts < max_age
        if fresh and (payload["extras"].get("full") or not full):
            return payload, ts
        if fresh and full:  # cached from a scan: just add the missing extras
            payload["extras"] = _fetch_extras(payload["company"], payload["view"], True)
            store.put_company(sym, payload)
            return payload, time.time()
    payload = fetch_payload(sym, full=full)
    store.put_company(sym, payload)
    return payload, time.time()


# ----------------------------------------------------------------- analysis
def median_pe_from(extras: dict) -> Optional[float]:
    pe = extras.get("pe_chart") or {}
    for key in ("Median PE", "Median P/E"):
        if pe.get(key):
            return pe[key][-1][1]
    series = pe.get("Price to Earning") or pe.get("PE") or []
    vals = [v for _, v in series if v and 0 < v < 500]
    return statistics.median(vals) if len(vals) >= 20 else None


def build_report(symbol: str, refresh: bool = False) -> dict:
    payload, ts = get_payload(symbol, refresh=refresh, full=True)
    company, extras = payload["company"], payload["extras"]
    a = analysis.analyse(company, median_pe_from(extras), extras.get("peers"), extras.get("pe_chart"))
    store.put_ranking(payload["symbol"], ranking_row(payload, a))
    return {
        "symbol": payload["symbol"],
        "view": payload["view"],
        "fetched_at": ts,
        "company": company,
        "peers": extras.get("peers"),
        "price_chart": extras.get("price_chart"),
        "pe_chart": extras.get("pe_chart"),
        "extras_errors": extras.get("errors", []),
        "analysis": a,
        "source": f"{config.SOURCE_BASE}/company/{payload['symbol']}/",
    }


def ranking_row(payload: dict, a: dict) -> dict:
    """Flat row per company: everything the Top Picks list and the Screener filter on."""
    c, m, s = payload["company"], a["metrics"], a["scores"]
    proj = a["projection"]
    h = proj.get("horizons", {}) if proj.get("available") else {}
    fx, val = a.get("forensics", {}), a.get("valuation", {})
    fv = val.get("fair_value") or {}
    sector_path = c.get("sector_path") or []
    text = (" ".join(sector_path) + " " + (c.get("name") or "")).lower()
    fin = m.get("is_financial")
    return {
        "symbol": payload["symbol"], "name": c.get("name"),
        "sector": sector_path[-1] if sector_path else "",
        "broad_sector": sector_path[0] if sector_path else "",
        "is_financial": fin,
        "is_holdco": any(w in text for w in ("investment compan", "holding compan", "investments", "holdings", "finance - investment")),
        # size & price
        "market_cap": m.get("market_cap"), "price": m.get("price"), "off_high_pct": m.get("off_high_pct"),
        # valuation
        "pe": m.get("pe"), "pb": m.get("pb"), "peg": m.get("peg"), "earnings_yield": m.get("earnings_yield"),
        "dividend_yield": m.get("dividend_yield"), "median_pe": a.get("median_pe"),
        "pe_vs_median": round(m["pe"] / a["median_pe"], 2) if m.get("pe") and a.get("median_pe") else None,
        "ev_ebitda": (val.get("ev") or {}).get("ev_ebitda"),
        "graham_upside": round((val["graham_number"] / m["price"] - 1) * 100, 1) if val.get("graham_number") and m.get("price") else None,
        "fair_value_upside": fv.get("upside"), "margin_of_safety": fv.get("margin_of_safety"),
        # growth
        "sales_cagr_3": m.get("sales_cagr_3"), "sales_cagr_5": m.get("sales_cagr_5"), "sales_cagr_10": m.get("sales_cagr_10"),
        "profit_cagr_3": m.get("profit_cagr_3"), "profit_cagr_5": m.get("profit_cagr_5"), "profit_cagr_10": m.get("profit_cagr_10"),
        "eps_cagr_5": m.get("eps_cagr_5"),
        # quality & safety
        "roce": m.get("roe_avg_5") if fin else m.get("roce_avg_5"),
        "roe": m.get("roe_avg_5"), "opm": m.get("opm_latest"),
        "debt_to_equity": None if fin else m.get("debt_to_equity"),
        "interest_coverage": m.get("interest_coverage"), "cfo_to_pat": m.get("cfo_to_pat_5"),
        # ownership
        "promoter": m.get("promoter_latest"), "promoter_change": m.get("promoter_change_8q"),
        "inst_change": m.get("institutional_change_8q"), "pledged": m.get("pledged"),
        # forensics
        "piotroski": (fx.get("piotroski") or {}).get("score_9"),
        "altman_z": (fx.get("altman") or {}).get("z"),
        "beneish_m": (fx.get("beneish") or {}).get("m"),
        # scores & outlook
        "overall": s.get("overall"), "business": s.get("business"), "valuation": s.get("valuation"),
        "growth": s.get("growth"), "quality": s.get("quality"), "strength": s.get("strength"),
        "cash": s.get("cash"), "ownership": s.get("ownership"),
        "verdict": a["verdict"]["label"], "tone": a["verdict"]["tone"],
        "base_3y": h.get("3", {}).get("base", {}).get("cagr"),
        "base_5y": h.get("5", {}).get("base", {}).get("cagr"),
        "base_10y": h.get("10", {}).get("base", {}).get("cagr"),
        "high_flags": sum(1 for f in a["flags"] if f["severity"] == "high"),
    }


# ----------------------------------------------------------------- scan
SCAN = {"running": False, "total": 0, "done": 0, "failed": 0, "current": None,
        "started_at": None, "finished_at": None, "source": None, "errors": [], "stop": False}
_scan_lock = threading.Lock()


def _scan_worker(limit: Optional[int]) -> None:
    rows, src = universe.load(download=True)
    if limit:
        rows = rows[:limit]
    SCAN.update(total=len(rows), done=0, failed=0, source=src, errors=[], started_at=time.time(), finished_at=None)
    for r in rows:
        if SCAN["stop"]:
            break
        sym = r["symbol"]
        SCAN["current"] = sym
        try:
            cached = store.get_company(scraper.clean_symbol(sym))
            fresh = cached and time.time() - cached[0] < config.SCAN_REUSE_HOURS * 3600
            payload, _ = get_payload(sym, full=False, max_age_h=config.SCAN_REUSE_HOURS)
            a = analysis.analyse(payload["company"], median_pe_from(payload["extras"]), None, payload["extras"].get("pe_chart"))
            row = ranking_row(payload, a)
            if not row["sector"] and r.get("industry"):
                row["sector"] = r["industry"]
            store.put_ranking(payload["symbol"], row)
            if not fresh:
                time.sleep(config.SCAN_DELAY_SECONDS + random.random() * 1.5)
        except Exception as e:  # noqa: BLE001
            SCAN["failed"] += 1
            SCAN["errors"] = (SCAN["errors"] + [f"{sym}: {e}"])[-30:]
            log.warning("scan %s failed: %s", sym, e)
            time.sleep(config.SCAN_DELAY_SECONDS)
        SCAN["done"] += 1
    SCAN.update(running=False, current=None, finished_at=time.time(), stop=False)


def start_scan(limit: Optional[int] = None, block: bool = False) -> dict:
    with _scan_lock:
        if SCAN["running"]:
            return scan_status()
        SCAN.update(running=True, stop=False)
    if block:
        _scan_worker(limit)
    else:
        threading.Thread(target=_scan_worker, args=(limit,), daemon=True).start()
    return scan_status()


def stop_scan() -> dict:
    SCAN["stop"] = True
    return scan_status()


def scan_status() -> dict:
    return {k: v for k, v in SCAN.items() if k != "stop"}
