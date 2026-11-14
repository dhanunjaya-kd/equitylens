"""Forensic accounting checks: Piotroski F-score, Altman Z-score, Beneish M-score,
DuPont ROE breakdown and extra accounting red flags.

The public pages give a condensed balance sheet (no separate current assets,
receivables or SG&A lines), so a few inputs use clearly-labelled proxies:
  * working capital / current ratio  ->  Other Assets vs Other Liabilities
  * receivables                      ->  Debtor Days (receivables / sales)
  * gross margin                     ->  Operating margin (OPM)
Inputs that can't be estimated are held neutral and listed in `notes`.
Banks / NBFCs get Piotroski-style checks adapted to lenders; Altman and
Beneish are skipped for them (the models were never built for lenders).
"""
from __future__ import annotations

import math
from typing import Optional

from .analysis import Table, _valid, aligned, r1

Num = Optional[float]


def _div(a: Num, b: Num) -> Num:
    if not (_valid(a) and _valid(b)) or b == 0:
        return None
    return a / b


def _yearly(c: dict) -> list[dict]:
    """One dict per financial year with every line we need, aligned on year label."""
    pl = Table(c["tables"].get("profit_loss"))
    bs = Table(c["tables"].get("balance_sheet"))
    cf = Table(c["tables"].get("cash_flow"))
    ra = Table(c["tables"].get("ratios"))

    def amap(t: Table, *names):
        return t.annual_map(*names)

    maps = {
        "sales": amap(pl, "Sales", "Revenue"), "op": amap(pl, "Operating Profit", "Financing Profit"),
        "opm": amap(pl, "OPM", "Financing Margin"), "other_inc": amap(pl, "Other Income"),
        "interest": amap(pl, "Interest"), "dep": amap(pl, "Depreciation"), "pbt": amap(pl, "Profit before tax"),
        "tax": amap(pl, "Tax"), "np": amap(pl, "Net Profit"), "eps": amap(pl, "EPS in Rs", "EPS"),
        "eq_cap": amap(bs, "Equity Capital", "Share Capital"), "reserves": amap(bs, "Reserves"),
        "borrow": amap(bs, "Borrowings", "Borrowing"), "other_liab": amap(bs, "Other Liabilities"),
        "deposits": amap(bs, "Deposits"), "fixed": amap(bs, "Fixed Assets", "Net Block"), "cwip": amap(bs, "CWIP"),
        "invest": amap(bs, "Investments"), "other_assets": amap(bs, "Other Assets"),
        "ta": amap(bs, "Total Assets", "Total Liabilities"),
        "cfo": amap(cf, "Cash from Operating Activity", "Cash from Operating"),
        "cfi": amap(cf, "Cash from Investing Activity", "Cash from Investing"),
        "debtor_days": amap(ra, "Debtor Days"),
    }
    years = [y for y in maps["sales"] if y in maps["ta"]]
    out = []
    for y in years:
        d = {"year": y}
        for k, mp in maps.items():
            d[k] = mp.get(y)
        eq = (d["eq_cap"] or 0) + (d["reserves"] or 0) if (_valid(d["eq_cap"]) or _valid(d["reserves"])) else None
        d["equity"] = eq
        d["shares"] = _div(d["np"], d["eps"]) if _valid(d["np"]) and _valid(d["eps"]) and d["np"] > 0 and d["eps"] > 0 else None
        out.append(d)
    return out


# ---------------------------------------------------------------- Piotroski
def piotroski(rows: list[dict], fin: bool) -> dict:
    if len(rows) < 2:
        return {"available": False, "reason": "Needs at least 2 years of data."}
    cur, prv = rows[-1], rows[-2]
    checks = []

    def add(group, name, ok, detail, proxy=False):
        checks.append({"group": group, "name": name, "pass": bool(ok) if ok is not None else None, "detail": detail, "proxy": proxy})

    roa_c, roa_p = _div(cur["np"], cur["ta"]), _div(prv["np"], prv["ta"])
    add("Profitability", "Positive net profit", _valid(cur["np"]) and cur["np"] > 0, f"Net profit ₹{_f(cur['np'])} Cr")
    if fin:
        add("Profitability", "Positive operating profit", _valid(cur["op"]) and cur["op"] > 0, f"Financing profit ₹{_f(cur['op'])} Cr")
    else:
        add("Profitability", "Positive operating cash flow", _valid(cur["cfo"]) and cur["cfo"] > 0, f"Operating cash ₹{_f(cur['cfo'])} Cr")
    add("Profitability", "Return on assets improved", _valid(roa_c) and _valid(roa_p) and roa_c > roa_p,
        f"ROA {_p(roa_c)} vs {_p(roa_p)} last year")
    if fin:
        add("Profitability", "Profit grew", _valid(cur["np"]) and _valid(prv["np"]) and cur["np"] > prv["np"],
            f"₹{_f(cur['np'])} vs ₹{_f(prv['np'])} Cr")
    else:
        add("Profitability", "Cash flow beats profit (low accruals)", _valid(cur["cfo"]) and _valid(cur["np"]) and cur["cfo"] > cur["np"],
            f"Operating cash ₹{_f(cur['cfo'])} vs profit ₹{_f(cur['np'])} Cr")

    if fin:
        lev_c, lev_p = _div(cur["equity"], cur["ta"]), _div(prv["equity"], prv["ta"])
        add("Safety", "Capital cushion improved", _valid(lev_c) and _valid(lev_p) and lev_c >= lev_p,
            f"Equity/assets {_p(lev_c)} vs {_p(lev_p)}")
        add("Safety", "Deposits grew", _valid(cur["deposits"]) and _valid(prv["deposits"]) and cur["deposits"] > prv["deposits"],
            f"₹{_f(cur['deposits'])} vs ₹{_f(prv['deposits'])} Cr")
    else:
        lev_c, lev_p = _div(cur["borrow"], cur["ta"]), _div(prv["borrow"], prv["ta"])
        add("Safety", "Debt fell (vs assets)", _valid(lev_c) and _valid(lev_p) and (lev_c <= lev_p or lev_c < 0.02),
            f"Debt/assets {_p(lev_c)} vs {_p(lev_p)}")
        cr_c, cr_p = _div(cur["other_assets"], cur["other_liab"]), _div(prv["other_assets"], prv["other_liab"])
        add("Safety", "Liquidity improved", _valid(cr_c) and _valid(cr_p) and cr_c >= cr_p,
            f"Other assets ÷ other liabilities {_x(cr_c)} vs {_x(cr_p)}", proxy=True)
    sh_c, sh_p = cur["shares"], prv["shares"]
    add("Safety", "No new shares issued", (_valid(sh_c) and _valid(sh_p) and sh_c <= sh_p * 1.02) if (_valid(sh_c) and _valid(sh_p)) else None,
        f"Share count change {_p(_div(sh_c, sh_p) - 1 if _valid(_div(sh_c, sh_p)) else None)}")

    m_c, m_p = cur["opm"], prv["opm"]
    add("Efficiency", "Margin improved", _valid(m_c) and _valid(m_p) and m_c > m_p, f"{_f(m_c)}% vs {_f(m_p)}%", proxy=not fin)
    at_c, at_p = _div(cur["sales"], cur["ta"]), _div(prv["sales"], prv["ta"])
    add("Efficiency", "Asset turnover improved", _valid(at_c) and _valid(at_p) and at_c > at_p, f"Sales/assets {_x(at_c)} vs {_x(at_p)}")

    scored = [c for c in checks if c["pass"] is not None]
    score = sum(1 for c in scored if c["pass"])
    total = len(scored)
    scaled = round(score / total * 9) if total else None
    zone = "Strong" if scaled is not None and scaled >= 7 else "Average" if scaled is not None and scaled >= 4 else "Weak"
    return {"available": True, "score": score, "out_of": total, "score_9": scaled, "zone": zone,
            "year": cur["year"], "vs_year": prv["year"], "checks": checks,
            "tone": {"Strong": "good", "Average": "warn", "Weak": "bad"}[zone]}


# ---------------------------------------------------------------- Altman Z
def altman(rows: list[dict], market_cap: Num, fin: bool) -> dict:
    if fin:
        return {"available": False, "reason": "Altman Z was built for manufacturers and traders, not lenders."}
    if not rows:
        return {"available": False, "reason": "No data."}
    d = rows[-1]
    ta = d["ta"]
    liab = (d["borrow"] or 0) + (d["other_liab"] or 0)
    wc = (d["other_assets"] or 0) - (d["other_liab"] or 0) if _valid(d["other_assets"]) else None
    ebit = (d["pbt"] or 0) + (d["interest"] or 0) if _valid(d["pbt"]) else None
    if not (_valid(ta) and ta > 0 and liab > 0 and _valid(ebit) and _valid(d["sales"])):
        return {"available": False, "reason": "Missing balance-sheet lines."}
    x1, x2, x3 = _div(wc, ta), _div(d["reserves"], ta), _div(ebit, ta)
    x4 = _div(market_cap, liab) if _valid(market_cap) else _div(d["equity"], liab)
    x5 = _div(d["sales"], ta)
    parts = [("Working capital / assets", x1, 1.2), ("Retained earnings / assets", x2, 1.4),
             ("EBIT / assets", x3, 3.3), ("Market value / liabilities", x4, 0.6), ("Sales / assets", x5, 1.0)]
    z = sum((v or 0) * w for _, v, w in parts)
    zone = "Safe" if z > 2.99 else "Grey zone" if z >= 1.81 else "Distress"
    return {"available": True, "z": r1(z, 2), "zone": zone, "tone": {"Safe": "good", "Grey zone": "warn", "Distress": "bad"}[zone],
            "year": d["year"],
            "parts": [{"name": n, "value": r1(v, 3), "weight": w, "contribution": r1((v or 0) * w, 2)} for n, v, w in parts],
            "note": "Working capital uses Other Assets − Other Liabilities as a proxy."}


# ---------------------------------------------------------------- Beneish M
def beneish(rows: list[dict], fin: bool) -> dict:
    if fin:
        return {"available": False, "reason": "Beneish M was built for non-financial companies."}
    if len(rows) < 2:
        return {"available": False, "reason": "Needs 2 years of data."}
    c, p = rows[-1], rows[-2]
    notes = []

    def ratio(a, b, name):
        v = _div(a, b)
        if not _valid(v) or v <= 0 or v > 20:
            notes.append(f"{name} held neutral (missing data)")
            return 1.0, False
        return v, True

    dsri, _ = ratio(c["debtor_days"], p["debtor_days"], "DSRI")
    gmi, _ = ratio(p["opm"], c["opm"], "GMI")
    sgi, _ = ratio(c["sales"], p["sales"], "SGI")
    dep_rate = lambda d: _div(d["dep"], (d["dep"] or 0) + (d["fixed"] or 0)) if _valid(d["dep"]) and _valid(d["fixed"]) else None
    depi, _ = ratio(dep_rate(p), dep_rate(c), "DEPI")
    lev = lambda d: _div((d["borrow"] or 0) + (d["other_liab"] or 0), d["ta"])
    lvgi, _ = ratio(lev(c), lev(p), "LVGI")
    tata = _div((c["np"] or 0) - (c["cfo"] or 0), c["ta"]) if _valid(c["np"]) and _valid(c["cfo"]) else None
    if not _valid(tata):
        notes.append("TATA held neutral (missing cash flow)")
        tata = 0.018  # sample mean of non-manipulators
    aqi, sgai = 1.0, 1.0
    notes.append("AQI and SGAI held neutral (asset-quality and SG&A lines aren't published on the summary page)")
    m = (-4.84 + 0.92 * dsri + 0.528 * gmi + 0.404 * aqi + 0.892 * sgi + 0.115 * depi
         - 0.172 * sgai + 4.679 * tata - 0.327 * lvgi)
    zone = "Unlikely" if m < -2.22 else "Watch" if m < -1.78 else "Possible manipulation"
    parts = [("DSRI · receivables vs sales", dsri, "Rising = sales booked but not collected"),
             ("GMI · margin change", gmi, ">1 = margins fell (pressure to dress up numbers)"),
             ("SGI · sales growth", sgi, "Fast growers face more pressure"),
             ("DEPI · depreciation rate", depi, ">1 = slower depreciation (boosts profit)"),
             ("LVGI · leverage change", lvgi, ">1 = more debt"),
             ("TATA · accruals", tata, "Profit not backed by cash")]
    return {"available": True, "m": r1(m, 2), "zone": zone,
            "tone": {"Unlikely": "good", "Watch": "warn", "Possible manipulation": "bad"}[zone],
            "year": c["year"], "parts": [{"name": n, "value": r1(v, 3), "meaning": t} for n, v, t in parts], "notes": notes}


# ---------------------------------------------------------------- DuPont
def dupont(rows: list[dict]) -> list[dict]:
    out = []
    for i in range(1, len(rows)):
        c, p = rows[i], rows[i - 1]
        avg_ta = ((c["ta"] or 0) + (p["ta"] or 0)) / 2 if _valid(c["ta"]) and _valid(p["ta"]) else None
        avg_eq = ((c["equity"] or 0) + (p["equity"] or 0)) / 2 if _valid(c["equity"]) and _valid(p["equity"]) else None
        npm = _div(c["np"], c["sales"])
        at = _div(c["sales"], avg_ta)
        em = _div(avg_ta, avg_eq)
        roe = npm * at * em if all(_valid(v) for v in (npm, at, em)) else None
        out.append({"year": c["year"], "net_margin": r1(npm * 100 if _valid(npm) else None),
                    "asset_turnover": r1(at, 2), "leverage": r1(em, 2), "roe": r1(roe * 100 if _valid(roe) else None)})
    return out[-10:]


# ---------------------------------------------------------------- extra flags
def accounting_flags(rows: list[dict], fin: bool) -> list[dict]:
    flags = []
    if not rows:
        return flags
    d = rows[-1]
    if not fin and _valid(d["cwip"]) and _valid(d["fixed"]) and d["fixed"] > 0 and d["cwip"] / d["fixed"] > 0.5:
        flags.append({"severity": "medium", "text": f"Capital work-in-progress is {int(d['cwip'] / d['fixed'] * 100)}% of fixed assets — big projects not yet earning."})
    taxes = [r["tax"] for r in rows[-5:] if _valid(r["tax"])]
    if not fin and len(taxes) >= 3 and sum(taxes) / len(taxes) < 15 and all(_valid(r["np"]) and r["np"] > 0 for r in rows[-3:]):
        flags.append({"severity": "medium", "text": f"Average tax rate only {sum(taxes)/len(taxes):.0f}% over 5 years — check for tax holidays or one-offs."})
    if _valid(d["invest"]) and _valid(d["ta"]) and d["ta"] > 0 and not fin and d["invest"] / d["ta"] > 0.4:
        flags.append({"severity": "info", "text": f"Investments are {int(d['invest'] / d['ta'] * 100)}% of assets — value depends partly on what it holds."})
    if len(rows) >= 4 and not fin:
        s0, s1 = rows[-4]["sales"], rows[-1]["sales"]
        dd0, dd1 = rows[-4]["debtor_days"], rows[-1]["debtor_days"]
        if all(_valid(v) for v in (s0, s1, dd0, dd1)) and s0 > 0 and dd0 > 0:
            rec_growth = (s1 * dd1) / (s0 * dd0)
            if rec_growth > (s1 / s0) * 1.3 and dd1 > 45:
                flags.append({"severity": "medium", "text": "Receivables grew much faster than sales over 3 years."})
    neg_cfo = sum(1 for r in rows[-5:] if _valid(r["cfo"]) and r["cfo"] < 0)
    if not fin and neg_cfo >= 2:
        flags.append({"severity": "high", "text": f"Operating cash flow was negative in {neg_cfo} of the last 5 years."})
    return flags


def compute(c: dict, m: dict) -> dict:
    fin = m.get("is_financial", False)
    rows = _yearly(c)
    pio = piotroski(rows, fin)
    alt = altman(rows, m.get("market_cap"), fin)
    ben = beneish(rows, fin)
    return {"piotroski": pio, "altman": alt, "beneish": ben, "dupont": dupont(rows),
            "flags": accounting_flags(rows, fin)}


# ---------------------------------------------------------------- formatting
def _f(v):
    return "—" if not _valid(v) else (f"{v:,.0f}" if abs(v) >= 100 else f"{v:,.1f}")


def _p(v):
    return "—" if not _valid(v) else f"{v * 100:.1f}%"


def _x(v):
    return "—" if not _valid(v) else f"{v:.2f}x"
