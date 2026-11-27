"""Glue: fetch -> parse -> cache -> analyse. Also runs the universe scan."""
from __future__ import annotations

import logging
import random
import statistics
import threading
import time
from typing import Optional

from . import analysis, config, money, parser, scraper, store, universe, us

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


def us_fx(cur: str) -> Optional[dict]:
    """US$ per 1 unit of `cur`, latest daily close of Yahoo's <CUR>USD=X (cached 12 h). None when unavailable."""
    from . import technicals
    key = f"FX::{cur}USD"
    hit = store.get_company(key)
    if hit and time.time() - hit[0] < 12 * 3600:
        return hit[1]
    try:
        bars = technicals._yahoo(f"{cur}USD=X", "1mo")
        b = bars[-1] if bars else None
        if b and b["c"] and b["c"] > 0:
            out = {"rate": b["c"], "date": b["t"], "source": f"Yahoo {cur}USD=X"}
            store.put_company(key, out)
            return out
    except Exception:  # noqa: BLE001
        pass
    return hit[1] if hit else None


def _save_us_raw(ticker: str, facts: dict, subs: dict) -> None:
    import json as _json
    try:
        d = config.DATA_DIR / "us_raw"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"sec_facts_{ticker}.json").write_text(_json.dumps(facts), encoding="utf-8")
        (d / f"sec_subs_{ticker}.json").write_text(_json.dumps(subs), encoding="utf-8")
    except OSError:
        pass


def fetch_payload_us(sym: str, full: bool = True) -> dict:
    from . import ipo, technicals, usuniverse
    info, facts, subs = us.fetch_raw(sym)
    try:
        bars, _, _ = technicals.get_bars(sym)
    except Exception:  # noqa: BLE001 - fundamentals still useful without prices
        bars = []
    price = bars[-1]["c"] if bars else None
    yr = bars[-252:]
    hi52 = max(b["h"] for b in yr) if yr else None
    lo52 = min(b["l"] for b in yr) if yr else None
    F = us.Facts(facts)
    fx = us_fx(F.cur) if F.cur != "USD" else None
    try:
        usuniverse.listed()                       # Nasdaq's list (cached 4 h): market cap, sector, country
    except Exception:  # noqa: BLE001
        pass
    nq = usuniverse.info(info["ticker"])
    form = F.annual_form()
    if form in ("20-F", "40-F") or F.cur != "USD":
        _save_us_raw(info["ticker"], facts, subs)
    if not F.annual_flow(us.REVENUE):
        _save_us_raw(info["ticker"], facts, subs)
        prof = us.profile(info, facts, subs, bars, ipo.us_ipo_for(f"US:{info['ticker']}"), nq, fx)
        raise us.USNoFinancials(f"No annual financials in SEC filings for {info['ticker']} yet.", prof)
    company = us.build_company(sym, price, hi52, lo52, info, facts, subs, fx=fx, nasdaq_cap=(nq or {}).get("market_cap"))
    pe = us.pe_history(bars[-2600:], company.pop("annual_eps_points", []))
    weekly = bars[-2600::5]
    extras = {"errors": [] if bars else ["Price history unavailable"], "full": True,
              "pe_chart": pe,
              "price_chart": {"Price": [[b["t"], b["c"]] for b in weekly]} if bars else None,
              "peers": None}
    return {"symbol": f"US:{info['ticker']}", "view": "consolidated", "company": company, "extras": extras}


def us_peers(symbol: str, company: dict) -> Optional[dict]:
    sector = (company.get("sector_path") or [None])[-1]
    rows = [r for r in store.all_rankings() if r.get("market") == "US" and r.get("sector") == sector]
    if len(rows) < 2:
        return None
    rows.sort(key=lambda r: -(r.get("market_cap") or 0))
    cols = ["Name", "CMP $", "P/E", "Mar Cap $M", "Div Yld %", "ROCE %"]
    out = [{"name": r["name"], "symbol": r["symbol"], "CMP $": r.get("price"), "P/E": r.get("pe"),
            "Mar Cap $M": r.get("market_cap"), "Div Yld %": r.get("dividend_yield"), "ROCE %": r.get("roce")} for r in rows[:10]]
    import statistics as st
    med = {}
    for k in cols[1:]:
        vals = [x[k] for x in out if isinstance(x.get(k), (int, float))]
        med[k] = round(st.median(vals), 2) if vals else None
    return {"columns": cols, "rows": out, "median": med}


def fetch_payload(symbol: str, full: bool = True) -> dict:
    sym = scraper.clean_symbol(symbol)
    if money.market_of(sym) == "US":
        return fetch_payload_us(sym, full)
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


def live_price(company: dict, symbol: str) -> tuple[dict, Optional[dict]]:
    """Put the latest session's price on top of the (daily-cached) fundamentals.
    Price-based figures (P/E, market cap) are scaled to the new price; the financials stay as they are."""
    from . import technicals
    try:
        bars, src, _, fetched = technicals.get_bars(symbol, with_time=True)
    except Exception:  # noqa: BLE001 - keep the report's own price
        return company, None
    if not bars:
        return company, None
    top = dict(company.get("ratios") or {})
    old, new = top.get("current_price"), bars[-1]["c"]
    if isinstance(old, (int, float)) and old > 0 and new:
        k = new / old
        for key in ("pe", "market_cap"):
            if isinstance(top.get(key), (int, float)):
                top[key] = top[key] * k
    top["current_price"] = new
    now = time.time()
    today = technicals.dt.datetime.fromtimestamp(now, technicals.IST).date().isoformat()
    info = {"date": bars[-1]["t"], "source": src,
            "fetched_at": technicals.dt.datetime.fromtimestamp(fetched, technicals.IST).isoformat(timespec="minutes"),
            "live": bars[-1]["t"] == today and technicals._market_open(now)}
    return dict(company, ratios=top), info


def entry_decision(symbol: str, a: dict, extras: dict) -> Optional[dict]:
    """Entry decision for the stock page (see entry.py). Never breaks the report."""
    from . import calendars, entry, technicals
    try:
        bars, _, ohlc = technicals.get_bars(symbol)
        if not ohlc or len(bars) < 260:
            return None
        m, scores = a["metrics"], a["scores"]
        pe_series = (extras.get("pe_chart") or {}).get("Price to Earning") or []
        nr = calendars.next_results(symbol)
        days = None
        if nr:
            today = technicals.dt.datetime.now(technicals.IST).date()
            days = (technicals.dt.date.fromisoformat(nr["date"]) - today).days
        sv = store.get_company("SURV::IN")
        surv = bool(sv and sv[1].get("flags", {}).get(symbol))
        out = entry.decide(
            bars, pe_hist=[v for _, v in pe_series], pe_now=m.get("pe"), business=scores.get("business"),
            high_flags=sum(1 for f in a.get("flags", []) if f.get("severity") == "high"),
            loss_making=isinstance(m.get("eps_ttm"), (int, float)) and m["eps_ttm"] <= 0,
            fair_value=(a.get("valuation") or {}).get("fair_value"), results_in_days=days, surveillance=surv)
        track = store.get_company("ENTRY_TRACK::IN")
        out["track"] = track[1] if track else None
        try:
            out["group"] = "N500" if symbol in universe.membership() else "OTHER"
        except Exception:  # noqa: BLE001
            out["group"] = None
        return out
    except Exception:  # noqa: BLE001 - the rest of the report still works
        return None


def build_report(symbol: str, refresh: bool = False) -> dict:
    money.set_market(money.market_of(scraper.clean_symbol(symbol)))
    payload, ts = get_payload(symbol, refresh=refresh, full=True)
    company, extras = payload["company"], payload["extras"]
    price_info = None
    if company.get("market", "IN") == "IN":
        company, price_info = live_price(company, payload["symbol"])
    if company.get("market") == "US":
        extras = dict(extras, peers=us_peers(payload["symbol"], company))
    a = analysis.analyse(company, median_pe_from(extras), extras.get("peers"), extras.get("pe_chart"))
    if company.get("market", "IN") == "IN":
        a = dict(a, entry=entry_decision(payload["symbol"], a, extras))
    store.put_ranking(payload["symbol"], ranking_row(payload, a))
    return {
        "symbol": payload["symbol"],
        "view": payload["view"],
        "fetched_at": ts,
        "price_info": price_info,
        "company": company,
        "peers": extras.get("peers"),
        "price_chart": extras.get("price_chart"),
        "pe_chart": extras.get("pe_chart"),
        "extras_errors": extras.get("errors", []),
        "analysis": a,
        "source": (f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={company.get('cik')}&type=10-K"
                   if company.get("market") == "US" else f"{config.SOURCE_BASE}/company/{payload['symbol']}/"),
        "market": company.get("market", "IN"),
        "currency": company.get("currency") or {"code": "INR", "symbol": "₹", "unit": "Cr"},
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
        "symbol": payload["symbol"], "name": c.get("name"), "market": c.get("market", "IN"),
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
SCAN = {"market": "IN", "running": False, "total": 0, "done": 0, "failed": 0, "current": None,
        "started_at": None, "finished_at": None, "source": None, "errors": [], "stop": False}
_scan_lock = threading.Lock()


def us_scan_list(which: str, min_cap: float = 0) -> tuple[list[dict], str]:
    """🇺🇸 SP500 (Wikipedia list) · NDX (Nasdaq-100, from Nasdaq) · ALL (every listed US stock with a Nasdaq-stated
    market cap of at least min_cap $ million, biggest first)."""
    from . import usuniverse
    if which == "NDX":
        rows = usuniverse.nasdaq100()
        return [{"symbol": r["symbol"], "name": r["name"], "industry": ""} for r in rows], "Nasdaq-100 (Nasdaq)"
    if which == "ALL":
        rows = [r for r in usuniverse.listed()["rows"] if (r.get("market_cap") or 0) >= max(min_cap, 1)]
        rows.sort(key=lambda r: -r["market_cap"])
        lab = f"All US stocks with market cap ≥ ${min_cap / 1000:g} B (Nasdaq)" if min_cap >= 1000 else f"All US stocks with market cap ≥ ${min_cap:g} M (Nasdaq)"
        return [{"symbol": r["symbol"], "name": r["name"], "industry": r.get("sector") if r.get("sector") != "Other" else ""} for r in rows], lab
    return us.sp500_universe(download=True)


def _scan_worker(limit: Optional[int], market: str = "IN", which: str = "N500", symbols: Optional[list] = None,
                 min_cap: float = 0) -> None:
    if symbols:
        rows, src = [{"symbol": s, "name": "", "industry": ""} for s in symbols], "your portfolio"
    elif market == "US":
        rows, src = us_scan_list(which, min_cap)
    elif which == "N500":
        rows, src = universe.load(download=True)
    else:
        rows, src = universe.index_list(which), universe.LABELS.get(which, which)
    SCAN["market"] = market
    if limit:
        rows = rows[:limit]
    SCAN.update(total=len(rows), done=0, failed=0, source=src, errors=[], started_at=time.time(), finished_at=None)
    for r in rows:
        if SCAN["stop"]:
            break
        sym = r["symbol"]
        SCAN["current"] = sym.replace("US:", "")
        money.set_market(market)
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
            if symbols is not None:                    # a portfolio holding with no financials (ETF, bond…)
                _no_score_add(sym)
            time.sleep(config.SCAN_DELAY_SECONDS)
        SCAN["done"] += 1
    SCAN.update(running=False, current=None, finished_at=time.time(), stop=False)


def _no_score_add(sym: str) -> None:
    got = store.get_company("PORTFOLIO_NOSCORE")
    syms = set(got[1]["symbols"]) if got else set()
    syms.add(sym)
    store.put_company("PORTFOLIO_NOSCORE", {"symbols": sorted(syms)})


def start_scan(limit: Optional[int] = None, block: bool = False, market: str = "IN", which: str = "N500",
               symbols: Optional[list] = None, min_cap: float = 0) -> dict:
    with _scan_lock:
        if SCAN["running"]:
            return scan_status()
        SCAN.update(running=True, stop=False, universe=which)
    if block:
        _scan_worker(limit, market, which, symbols, min_cap)
    else:
        threading.Thread(target=_scan_worker, args=(limit, market, which, symbols, min_cap), daemon=True).start()
    return scan_status()


def stop_scan() -> dict:
    SCAN["stop"] = True
    return scan_status()


def scan_status() -> dict:
    return {k: v for k, v in SCAN.items() if k != "stop"}
