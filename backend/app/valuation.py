"""Valuation lab: several independent ways to value a share, so you can see
where they agree. The interactive DCF re-runs in the app as you move the
sliders. Here we compute the defaults and the reference values.
"""
from __future__ import annotations

import math
import statistics
from typing import Optional

from . import config
from .analysis import Table, _valid, last, r1

Num = Optional[float]


def dcf_value(base: float, g1: float, g2: float, gt: float, r: float, years1: int = 5, years2: int = 5) -> dict:
    """Two-stage DCF + terminal value, all per share. Rates in %."""
    g1, g2, gt, r = g1 / 100, g2 / 100, gt / 100, r / 100
    if r <= gt:
        return {"value": None, "pv_stage": None, "pv_terminal": None}
    cf, pv = base, 0.0
    for t in range(1, years1 + years2 + 1):
        cf *= 1 + (g1 if t <= years1 else g2)
        pv += cf / (1 + r) ** t
    tv = cf * (1 + gt) / (r - gt)
    pv_tv = tv / (1 + r) ** (years1 + years2)
    return {"value": pv + pv_tv, "pv_stage": pv, "pv_terminal": pv_tv}


def _percentile(vals: list[float], q: float) -> Num:
    if not vals:
        return None
    s = sorted(vals)
    k = (len(s) - 1) * q
    f, c = math.floor(k), math.ceil(k)
    return s[f] + (s[c] - s[f]) * (k - f)


def compute(c: dict, m: dict, pe_chart: dict | None, peers: dict | None, median_pe: Num) -> dict:
    fin = m.get("is_financial", False)
    price, eps, bv = m.get("price"), m.get("eps_ttm"), m.get("book_value")
    pl = Table(c["tables"].get("profit_loss"))
    out: dict = {"methods": [], "notes": []}

    # --- base cash per share for the DCF
    shares = None
    if _valid(m.get("market_cap")) and _valid(price) and price > 0:
        shares = m["market_cap"] / price  # crore shares
    fcf_series = [v for v in (m.get("fcf_series") or [])[-3:] if _valid(v)]
    fcf_ps = (sum(fcf_series) / len(fcf_series)) / shares if fcf_series and shares else None
    options = {}
    if _valid(eps) and eps > 0:
        options["eps"] = {"label": "Earnings per share (TTM)", "value": r1(eps, 2)}
    if not fin and _valid(fcf_ps) and fcf_ps > 0:
        options["fcf"] = {"label": "Free cash per share (3-yr avg)", "value": r1(fcf_ps, 2)}
    payout = m.get("dividend_payout_avg_5")
    if fin and _valid(eps) and eps > 0:
        # lenders must retain capital to grow; value what they can distribute
        dist = eps * max(min((payout or 25) / 100 + 0.25, 0.8), 0.35)
        options["dist"] = {"label": "Distributable earnings per share", "value": r1(dist, 2)}
    default_base = "fcf" if "fcf" in options and options["fcf"]["value"] >= (eps or 0) * 0.5 else ("dist" if "dist" in options else "eps")
    if default_base not in options:
        default_base = next(iter(options), None)

    hist = [v for v in (m.get("profit_cagr_5"), m.get("profit_cagr_10")) if _valid(v)]
    g_hist = sum(hist) / len(hist) if hist else (m.get("sales_cagr_5") or 8)
    g1 = max(min(g_hist, 25), 3)
    g2 = max(min(g1 * 0.6, 15), 3)
    defaults = {"base": default_base, "g1": round(g1, 1), "g2": round(g2, 1), "gt": 5.0,
                "r": round(config.REQUIRED_RETURN * 100, 1)}
    out["dcf"] = {"options": options, "defaults": defaults, "price": price}
    if default_base:
        res = dcf_value(options[default_base]["value"], g1, g2, 5.0, defaults["r"])
        out["dcf"]["default_value"] = r1(res["value"], 0)
        out["methods"].append({"name": "DCF (default inputs)", "value": r1(res["value"], 0),
                               "how": f"{options[default_base]['label']}, growth {g1:.0f}% → {g2:.0f}% → 5%, discount {defaults['r']:.0f}%"})

    # --- Graham number
    if _valid(eps) and eps > 0 and _valid(bv) and bv > 0:
        gn = math.sqrt(22.5 * eps * bv)
        out["graham_number"] = r1(gn, 0)
        out["methods"].append({"name": "Graham number", "value": r1(gn, 0), "how": "√(22.5 × EPS × book value) — a strict value-investor ceiling"})

    # --- Earnings power at historical P/E
    if _valid(eps) and eps > 0 and _valid(median_pe):
        out["methods"].append({"name": "Median P/E × EPS", "value": r1(eps * median_pe, 0), "how": f"Own 10-yr median P/E {median_pe:.1f} × EPS"})
    peer_pe = (peers or {}).get("median", {}).get("P/E")
    if _valid(eps) and eps > 0 and _valid(peer_pe) and peer_pe > 0:
        out["methods"].append({"name": "Peer median P/E × EPS", "value": r1(eps * peer_pe, 0), "how": f"Peers' median P/E {peer_pe:.1f} × EPS"})
    if fin and _valid(bv) and _valid(m.get("roe_avg_5")):
        # justified P/B = (ROE - g) / (r - g)
        roe, r, g = m["roe_avg_5"] / 100, config.REQUIRED_RETURN, 0.06
        if roe > g:
            jpb = (roe - g) / (r - g)
            out["methods"].append({"name": "Justified P/B × book", "value": r1(jpb * bv, 0),
                                   "how": f"(ROE {roe*100:.0f}% − 6%) ÷ (12% − 6%) = {jpb:.2f}x book"})

    # --- EV multiples (non-financial)
    if not fin:
        mcap, debt = m.get("market_cap"), m.get("borrowings") or 0
        ebitda = pl.ttm("Operating Profit")
        if not _valid(ebitda):
            ebitda = last(pl.annual("Operating Profit"))
        sales = m.get("sales_latest")
        if _valid(mcap):
            ev = mcap + debt
            out["ev"] = {"ev": r1(ev, 0), "ev_ebitda": r1(ev / ebitda, 1) if _valid(ebitda) and ebitda > 0 else None,
                         "ev_sales": r1(ev / sales, 2) if _valid(sales) and sales > 0 else None,
                         "note": "EV = market cap + borrowings (cash isn't split out on the source, so EV is slightly overstated)."}

    # --- P/E bands over time
    pe_chart = pe_chart or {}
    pe_s = pe_chart.get("Price to Earning") or pe_chart.get("PE") or []
    eps_s = dict(pe_chart.get("EPS") or [])
    vals = [v for _, v in pe_s if v and 0 < v < 300]
    if len(vals) >= 30:
        qs = {"p10": 0.1, "p25": 0.25, "p50": 0.5, "p75": 0.75, "p90": 0.9}
        bands = {k: _percentile(vals, q) for k, q in qs.items()}
        series = []
        for d, pe in pe_s:
            e = eps_s.get(d)
            if not _valid(e) or e <= 0:
                continue
            row = {"d": d, "price": r1(pe * e, 1)}
            for k, b in bands.items():
                row[k] = r1(b * e, 1)
            series.append(row)
        out["pe_bands"] = {"bands": {k: r1(v, 1) for k, v in bands.items()}, "series": series[-260:],
                           "current_pe": m.get("pe"),
                           "percentile_now": r1(sum(1 for v in vals if v <= (m.get("pe") or 0)) / len(vals) * 100, 0) if _valid(m.get("pe")) else None}

    # --- summary
    vals_ok = [x["value"] for x in out["methods"] if _valid(x["value"]) and x["value"] > 0]
    if vals_ok and _valid(price):
        mid = statistics.median(vals_ok)
        out["fair_value"] = {"low": r1(min(vals_ok), 0), "mid": r1(mid, 0), "high": r1(max(vals_ok), 0),
                             "margin_of_safety": r1((mid - price) / mid * 100, 1),
                             "upside": r1((mid / price - 1) * 100, 1)}
        for x in out["methods"]:
            x["upside"] = r1((x["value"] / price - 1) * 100, 1) if _valid(x["value"]) else None
    return out
