"""US stocks: fundamentals from SEC EDGAR (official, free, no key), prices from Yahoo.

SEC endpoints used (public JSON):
  * https://www.sec.gov/files/company_tickers.json            ticker -> CIK, name
  * https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json   every XBRL fact filed
  * https://data.sec.gov/submissions/CIK##########.json        name, industry (SIC), filings

SEC asks every client to identify itself in the User-Agent (name + contact email),
and to stay under 10 requests/second. Set EQL_SEC_USER_AGENT in backend/.env.

The output has exactly the same shape as parser.parse_company(), so the whole
research engine (scores, forensics, valuation, scenarios, AI) works unchanged.
Money is in US$ million; EPS and per-share values in dollars.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import threading
import time
from typing import Optional

import requests

from . import config

SEC_UA = os.getenv("EQL_SEC_USER_AGENT", "EquityLens personal research tool (set EQL_SEC_USER_AGENT to your email)")
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
SUBS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
_lock = threading.Lock()
_last = 0.0


class USFetchError(Exception):
    pass


# ------------------------------------------------------------------ http
def _get_json(url: str) -> dict:
    global _last
    with _lock:
        wait = 0.15 - (time.time() - _last)
        if wait > 0:
            time.sleep(wait)
        _last = time.time()
    for attempt in range(3):
        try:
            r = requests.get(url, headers={"User-Agent": SEC_UA, "Accept-Encoding": "gzip, deflate"}, timeout=config.REQUEST_TIMEOUT)
        except requests.RequestException as e:
            if attempt == 2:
                raise USFetchError(f"SEC network error: {e}") from e
            time.sleep(2)
            continue
        if r.status_code == 404:
            raise USFetchError("Not found on SEC EDGAR.")
        if r.status_code in (403, 429):
            time.sleep(3 * (attempt + 1))
            if attempt == 2:
                raise USFetchError("SEC refused the request. Set EQL_SEC_USER_AGENT to 'YourName your@email.com' in backend/.env.")
            continue
        if r.status_code != 200:
            raise USFetchError(f"SEC HTTP {r.status_code}")
        return r.json()
    raise USFetchError("SEC: gave up after retries")


def get_text(url: str) -> str:
    """Raw text from sec.gov with the same pacing and User-Agent rules (Form 4 XML, filing indexes, feeds)."""
    global _last
    with _lock:
        wait = 0.15 - (time.time() - _last)
        if wait > 0:
            time.sleep(wait)
        _last = time.time()
    for attempt in range(3):
        try:
            r = requests.get(url, headers={"User-Agent": SEC_UA, "Accept-Encoding": "gzip, deflate"}, timeout=config.REQUEST_TIMEOUT)
        except requests.RequestException as e:
            if attempt == 2:
                raise USFetchError(f"SEC network error: {e}") from e
            time.sleep(2)
            continue
        if r.status_code in (403, 429):
            time.sleep(3 * (attempt + 1))
            continue
        if r.status_code != 200:
            raise USFetchError(f"SEC HTTP {r.status_code}")
        return r.text
    raise USFetchError("SEC refused the request. Set EQL_SEC_USER_AGENT to 'YourName your@email.com' in backend/.env.")


def _demo(name: str) -> dict:
    path = config.FIXTURE_DIR / name
    if not path.exists():
        raise USFetchError("Not found on SEC EDGAR.")
    return json.loads(path.read_text(encoding="utf-8"))


# ------------------------------------------------------------------ tickers
_tickers: Optional[list[dict]] = None


def tickers() -> list[dict]:
    """[{ticker, cik, name}] — cached on disk for a week."""
    global _tickers
    if _tickers is not None:
        return _tickers
    if config.DEMO:
        raw = _demo("us_tickers.json")
    else:
        path = config.DATA_DIR / "sec_tickers.json"
        if path.exists() and time.time() - path.stat().st_mtime < 7 * 86400:
            raw = json.loads(path.read_text(encoding="utf-8"))
        else:
            raw = _get_json(TICKERS_URL)
            path.write_text(json.dumps(raw), encoding="utf-8")
    _tickers = [{"ticker": v["ticker"].upper(), "cik": int(v["cik_str"]), "name": v["title"]} for v in raw.values()]
    return _tickers


def lookup(ticker: str) -> Optional[dict]:
    t = ticker.upper().replace("US:", "")
    return next((x for x in tickers() if x["ticker"] == t), None)


def _nice(name: str) -> str:
    if not name.isupper():
        return name
    keep = {"US", "USA", "II", "III", "IV", "LP", "PLC", "NV", "SA", "AG", "SE", "ETF", "REIT", "AI"}
    return " ".join(w if w.strip(".,&") in keep else w.capitalize() for w in name.split())


def search(q: str, limit: int = 12) -> list[dict]:
    ql = q.lower().strip()
    if not ql:
        return []
    rows = tickers()
    exact = [r for r in rows if r["ticker"].lower() == ql]
    starts = [r for r in rows if r["ticker"].lower().startswith(ql) and r not in exact]
    named = [r for r in rows if ql in r["name"].lower() and r not in exact and r not in starts]
    return [{"name": _nice(r["name"]), "symbol": f"US:{r['ticker']}", "market": "US"}
            for r in (exact + starts + named)[:limit]]


# ------------------------------------------------------------------ facts helpers
REVENUE = ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "RevenueFromContractWithCustomerIncludingAssessedTax",
           "SalesRevenueNet", "SalesRevenueGoodsNet", "RevenuesNetOfInterestExpense", "InterestAndDividendIncomeOperating"]
OPINC = ["OperatingIncomeLoss"]
DEP = ["DepreciationDepletionAndAmortization", "DepreciationAndAmortization", "DepreciationAmortizationAndAccretionNet", "Depreciation"]
INTEREST = ["InterestExpense", "InterestExpenseNonoperating", "InterestExpenseDebt", "InterestPaidNet"]
OTHER_INC = ["NonoperatingIncomeExpense", "OtherNonoperatingIncomeExpense"]
PBT = ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
       "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
       "IncomeLossFromContinuingOperationsBeforeIncomeTaxesDomestic"]
TAX = ["IncomeTaxExpenseBenefit"]
NI = ["NetIncomeLoss", "ProfitLoss", "NetIncomeLossAvailableToCommonStockholdersBasic"]
EPS = ["EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted", "EarningsPerShareBasic"]
DPS = ["CommonStockDividendsPerShareDeclared", "CommonStockDividendsPerShareCashPaid"]
DIV_PAID = ["PaymentsOfDividendsCommonStock", "PaymentsOfDividends"]
ASSETS = ["Assets"]
LIAB = ["Liabilities"]
EQUITY = ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"]
COMMON = ["CommonStockValue", "CommonStocksIncludingAdditionalPaidInCapital"]
LTD = ["LongTermDebtNoncurrent", "LongTermDebt", "LongTermDebtAndCapitalLeaseObligations"]
STD = ["LongTermDebtCurrent", "DebtCurrent", "ShortTermBorrowings", "CommercialPaper"]
PPE = ["PropertyPlantAndEquipmentNet"]
CWIP = ["ConstructionInProgressGross"]
INVEST = ["LongTermInvestments", "MarketableSecuritiesNoncurrent", "AvailableForSaleSecuritiesDebtSecuritiesNoncurrent"]
RECV = ["AccountsReceivableNetCurrent", "ReceivablesNetCurrent"]
INVENT = ["InventoryNet"]
COGS = ["CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold"]
CFO = ["NetCashProvidedByUsedInOperatingActivities", "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"]
CFI = ["NetCashProvidedByUsedInInvestingActivities", "NetCashProvidedByUsedInInvestingActivitiesContinuingOperations"]
CFF = ["NetCashProvidedByUsedInFinancingActivities", "NetCashProvidedByUsedInFinancingActivitiesContinuingOperations"]
SHARES = ["EntityCommonStockSharesOutstanding"]
WSHARES = ["WeightedAverageNumberOfDilutedSharesOutstanding", "WeightedAverageNumberOfSharesOutstandingBasic"]


def _d(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


def _label(end: str) -> str:
    return _d(end).strftime("%b %Y")


class Facts:
    def __init__(self, raw: dict):
        f = raw.get("facts", {})
        self.gaap = f.get("us-gaap", {})
        self.dei = f.get("dei", {})

    def _entries(self, tag: str, ns: str = "gaap") -> list[dict]:
        node = (self.gaap if ns == "gaap" else self.dei).get(tag)
        if not node:
            return []
        units = node.get("units", {})
        for u in ("USD", "USD/shares", "shares", "pure"):
            if u in units:
                return units[u]
        return next(iter(units.values()), [])

    def annual_flow(self, tags: list[str]) -> dict[str, float]:
        """{fiscal-year-end ISO date: value} from 10-K full-year durations; earlier tags win per year."""
        out: dict[str, float] = {}
        for tag in tags:
            best: dict[str, tuple] = {}
            for e in self._entries(tag):
                if "start" not in e or not str(e.get("form", "")).startswith(("10-K", "20-F", "40-F")):
                    continue
                days = (_d(e["end"]) - _d(e["start"])).days
                if 340 <= days <= 380:
                    k = e["end"]
                    if k not in best or e.get("filed", "") > best[k][1]:
                        best[k] = (e["val"], e.get("filed", ""))
            for k, (v, _) in best.items():
                out.setdefault(k, v)
        return out

    def quarterly_flow(self, tags: list[str]) -> dict[str, float]:
        """{quarter-end: value} for ~3-month periods (10-Q), Q4 derived as FY minus Q1-Q3."""
        q: dict[str, float] = {}
        for tag in tags:
            best: dict[str, tuple] = {}
            for e in self._entries(tag):
                if "start" not in e:
                    continue
                days = (_d(e["end"]) - _d(e["start"])).days
                if 80 <= days <= 100:
                    k = e["end"]
                    if k not in best or e.get("filed", "") > best[k][1]:
                        best[k] = (e["val"], e.get("filed", ""))
            for k, (v, _) in best.items():
                q.setdefault(k, v)
        for fy_end, v in self.annual_flow(tags).items():
            if fy_end in q:
                continue
            e = _d(fy_end)
            inside = [k for k in q if 0 < (e - _d(k)).days < 300]
            if len(inside) == 3:
                q[fy_end] = v - sum(q[k] for k in inside)
        return dict(sorted(q.items()))

    def instant(self, tags: list[str], annual_ends: list[str]) -> dict[str, float]:
        """Balance-sheet values at each fiscal year end (+ the latest quarter end)."""
        out: dict[str, float] = {}
        latest: Optional[tuple] = None
        for tag in tags:
            vals: dict[str, tuple] = {}
            for e in self._entries(tag):
                if "start" in e:
                    continue
                k = e["end"]
                if k not in vals or e.get("filed", "") > vals[k][1]:
                    vals[k] = (e["val"], e.get("filed", ""))
            for k in annual_ends:
                if k in vals:
                    out.setdefault(k, vals[k][0])
            if vals:
                k = max(vals)
                if latest is None or k > latest[0]:
                    latest = (k, vals[k][0])
        if latest and latest[0] not in out:
            out[latest[0]] = latest[1]
        return out

    def latest_dei(self, tags: list[str]) -> Optional[float]:
        for tag in tags:
            es = self._entries(tag, "dei")
            if es:
                return max(es, key=lambda e: (e["end"], e.get("filed", "")))["val"]
        return None

    def latest_weighted_shares(self) -> Optional[float]:
        a = self.annual_flow(WSHARES)
        return a[max(a)] if a else None


# ------------------------------------------------------------------ build
def _m(v):  # dollars -> $ million
    return None if v is None else round(v / 1e6, 2)


def fetch_raw(ticker: str) -> tuple[dict, dict, dict]:
    info = lookup(ticker)
    if not info:
        raise USFetchError(f"'{ticker}' isn't a US-listed ticker on SEC EDGAR.")
    if config.DEMO:
        return info, _demo(f"us_facts_{info['ticker']}.json"), _demo(f"us_subs_{info['ticker']}.json")
    return info, _get_json(FACTS_URL.format(cik=info["cik"])), _get_json(SUBS_URL.format(cik=info["cik"]))


def build_company(ticker: str, price: Optional[float], hi52: Optional[float], lo52: Optional[float],
                  info: dict, facts_raw: dict, subs: dict) -> dict:
    F = Facts(facts_raw)
    sales_a = F.annual_flow(REVENUE)
    if len(sales_a) < 1:
        raise USFetchError(f"No annual financials in SEC filings for {ticker} (foreign filers using 20-F/IFRS may be missing).")
    years = sorted(sales_a)[-12:]
    cols = [_label(y) for y in years]

    def row(tags, conv=_m, src=None):
        d = src if src is not None else F.annual_flow(tags)
        return [conv(d.get(y)) if d.get(y) is not None else None for y in years]

    sales = row(REVENUE)
    opinc = row(OPINC)
    dep = row(DEP)
    ebitda = [(o + (dd or 0)) if o is not None else None for o, dd in zip(opinc, dep)]
    interest = row(INTEREST)
    other = row(OTHER_INC)
    pbt = row(PBT)
    tax = row(TAX)
    ni = row(NI)
    eps = row(EPS, conv=lambda v: round(v, 2))
    dps = row(DPS, conv=lambda v: round(v, 4))
    divpaid = row(DIV_PAID)
    opm = [round(e / s * 100, 1) if e is not None and s else None for e, s in zip(ebitda, sales)]
    taxp = [round(t / p * 100) if t is not None and p else None for t, p in zip(tax, pbt)]
    payout = []
    for i in range(len(years)):
        if dps[i] is not None and eps[i] and eps[i] > 0:
            payout.append(round(dps[i] / eps[i] * 100))
        elif divpaid[i] is not None and ni[i] and ni[i] > 0:
            payout.append(round(abs(divpaid[i]) / ni[i] * 100))
        else:
            payout.append(None)

    # TTM from the last 4 quarters
    q_sales, q_ni, q_eps = F.quarterly_flow(REVENUE), F.quarterly_flow(NI), F.quarterly_flow(EPS)
    q_op, q_dep = F.quarterly_flow(OPINC), F.quarterly_flow(DEP)
    qk = sorted(q_sales)[-4:]
    ttm_ok = len(qk) == 4 and qk[-1] > years[-1] and (_d(qk[-1]) - _d(qk[0])).days < 300
    ttm = {}
    if ttm_ok:
        ttm = {"sales": _m(sum(q_sales[k] for k in qk)),
               "ni": _m(sum(q_ni.get(k, 0) for k in qk)) if all(k in q_ni for k in qk) else None,
               "eps": round(sum(q_eps[k] for k in qk), 2) if all(k in q_eps for k in qk) else None}
        cols_pl = cols + ["TTM"]
    else:
        cols_pl = cols

    def add_ttm(vals, key=None):
        return vals + ([ttm.get(key)] if ttm_ok else [])

    pl_rows = {
        "Sales": add_ttm(sales, "sales"),
        "Expenses": add_ttm([round(s - e, 2) if s is not None and e is not None else None for s, e in zip(sales, ebitda)]),
        "Operating Profit": add_ttm(ebitda), "OPM %": add_ttm(opm), "Other Income": add_ttm(other),
        "Interest": add_ttm(interest), "Depreciation": add_ttm(dep), "Profit before tax": add_ttm(pbt),
        "Tax %": add_ttm(taxp), "Net Profit": add_ttm(ni, "ni"), "EPS in Rs": add_ttm(eps, "eps"),
        "Dividend Payout %": add_ttm(payout),
    }

    # balance sheet (fiscal year ends + latest quarter)
    bs_ends = years
    eqd, ld, sd = F.instant(EQUITY, bs_ends), F.instant(LTD, bs_ends), F.instant(STD, bs_ends)
    ad, lid = F.instant(ASSETS, bs_ends), F.instant(LIAB, bs_ends)
    common, ppe, cw, inv = F.instant(COMMON, bs_ends), F.instant(PPE, bs_ends), F.instant(CWIP, bs_ends), F.instant(INVEST, bs_ends)
    bs_keys = sorted(set(years) | ({max(ad)} if ad else set()))[-13:]
    bs_cols = [_label(k) for k in bs_keys]

    def bs(d):
        return [_m(d.get(k)) for k in bs_keys]

    eq_l, common_l = bs(eqd), bs(common)
    borrow = [round((l or 0) + (s or 0), 2) if (l is not None or s is not None) else None for l, s in zip(bs(ld), bs(sd))]
    assets = bs(ad)
    liab = bs(lid)
    liab = [lv if lv is not None else (a - e if a is not None and e is not None else None) for lv, a, e in zip(liab, assets, eq_l)]
    reserves = [round(e - (c or 0), 2) if e is not None else None for e, c in zip(eq_l, common_l)]
    bs_rows = {
        "Equity Capital": [c if c is not None else (0.0 if e is not None else None) for c, e in zip(common_l, eq_l)],
        "Reserves": reserves, "Borrowings": borrow,
        "Other Liabilities": [round(l - (b or 0), 2) if l is not None else None for l, b in zip(liab, borrow)],
        "Total Liabilities": assets, "Fixed Assets": bs(ppe), "CWIP": bs(cw), "Investments": bs(inv),
        "Other Assets": [round(a - (p or 0) - (c or 0) - (i or 0), 2) if a is not None else None
                         for a, p, c, i in zip(assets, bs(ppe), bs(cw), bs(inv))],
        "Total Assets": assets,
    }

    cf_rows = {"Cash from Operating Activity": row(CFO), "Cash from Investing Activity": row(CFI),
               "Cash from Financing Activity": row(CFF)}
    cf_rows["Net Cash Flow"] = [round(sum(x for x in t if x is not None), 2) if any(x is not None for x in t) else None
                                for t in zip(*cf_rows.values())]

    recv, invt, cogs = F.instant(RECV, years), F.instant(INVENT, years), F.annual_flow(COGS)
    debtor = [round(_m(recv[y]) / s * 365) if recv.get(y) is not None and s else None for y, s in zip(years, sales)]
    inv_days = [round(invt[y] / cogs[y] * 365) if invt.get(y) is not None and cogs.get(y) else None for y in years]
    roce = []
    for i, y in enumerate(years):
        ebit = (pbt[i] + (interest[i] or 0)) if pbt[i] is not None else opinc[i]
        e_now, d_now = _m(eqd.get(y)), _m((ld.get(y) or 0) + (sd.get(y) or 0))
        e_prv = _m(eqd.get(years[i - 1])) if i else None
        d_prv = _m((ld.get(years[i - 1]) or 0) + (sd.get(years[i - 1]) or 0)) if i else None
        cap = [(e or 0) + (d or 0) for e, d in ((e_now, d_now), (e_prv, d_prv)) if e is not None]
        avg = sum(cap) / len(cap) if cap else None
        roce.append(round(ebit / avg * 100, 1) if ebit is not None and avg and avg > 0 else None)
    ratio_rows = {"Debtor Days": debtor, "Inventory Days": inv_days, "ROCE %": roce}

    # quarters (last 12)
    qkeys = sorted(q_sales)[-12:]
    q_ebitda = {k: q_op[k] + (q_dep.get(k) or 0) for k in qkeys if k in q_op}
    quarters = {"columns": [_label(k) for k in qkeys], "rows": {
        "Sales": [_m(q_sales.get(k)) for k in qkeys],
        "Operating Profit": [_m(q_ebitda.get(k)) for k in qkeys],
        "OPM %": [round(q_ebitda[k] / q_sales[k] * 100, 1) if k in q_ebitda and q_sales.get(k) else None for k in qkeys],
        "Net Profit": [_m(q_ni.get(k)) for k in qkeys],
        "EPS in Rs": [round(q_eps[k], 2) if k in q_eps else None for k in qkeys],
    }} if qkeys else {"columns": [], "rows": {}}
    quarters["rows"] = {k: v for k, v in quarters["rows"].items() if any(x is not None for x in v)}

    # top ratios
    shares = F.latest_dei(SHARES) or F.latest_weighted_shares()
    eps_ttm = ttm.get("eps") if ttm_ok and ttm.get("eps") is not None else (eps[-1] if eps else None)
    eq_latest = eq_l[-1] if eq_l else None
    dps_ttm = dps[-1] if dps and dps[-1] is not None else (
        abs(divpaid[-1]) * 1e6 / shares if divpaid and divpaid[-1] is not None and shares else None)
    ratios = {}
    if price:
        ratios["current_price"] = round(price, 2)
        if shares:
            ratios["market_cap"] = round(price * shares / 1e6, 0)
        if eps_ttm and eps_ttm > 0:
            ratios["pe"] = round(price / eps_ttm, 1)
        if dps_ttm:
            ratios["dividend_yield"] = round(dps_ttm / price * 100, 2)
    if hi52 and lo52:
        ratios["high"], ratios["low"] = round(hi52, 2), round(lo52, 2)
    if eq_latest is not None and shares:
        ratios["book_value"] = round(eq_latest * 1e6 / shares, 2)
    if roce and roce[-1] is not None:
        ratios["roce"] = roce[-1]
    if ni and ni[-1] is not None and eq_latest and eq_latest > 0:
        ratios["roe"] = round(ni[-1] / eq_latest * 100, 1)

    sic = str(subs.get("sic") or "")
    is_fin = sic[:2] in ("60", "61", "62", "63", "64", "67") and sic not in ("6770",)
    exch = ", ".join(subs.get("exchanges") or []) or "US"
    fye = subs.get("fiscalYearEnd") or ""
    about = (f"{subs.get('name') or info['name']} is a US-listed company ({exch}) in "
             f"{(subs.get('sicDescription') or 'its industry').lower()}."
             + (f" Its fiscal year ends in {dt.date(2000, int(fye[:2]), 1).strftime('%B')}." if len(fye) == 4 and fye[:2].isdigit() else "")
             + " Financials are from its SEC filings (10-K and 10-Q).")

    return {
        "name": subs.get("name") or info["name"], "symbol": f"US:{info['ticker']}", "bse_code": None,
        "nse_symbol": None, "us_ticker": info["ticker"], "cik": info["cik"], "market": "US",
        "currency": {"code": "USD", "symbol": "$", "unit": "M"},
        "website": subs.get("website") or None, "about": about, "key_points": "", "key_points_md": "",
        "sector_path": [x for x in ("United States", subs.get("sicDescription")) if x],
        "ratios": ratios,
        "tables": {
            "quarters": quarters,
            "profit_loss": {"columns": cols_pl, "rows": pl_rows},
            "balance_sheet": {"columns": bs_cols, "rows": bs_rows},
            "cash_flow": {"columns": cols, "rows": cf_rows},
            "ratios": {"columns": cols, "rows": ratio_rows},
            "shareholding_quarterly": {"columns": [], "rows": {}},
            "shareholding_yearly": {"columns": [], "rows": {}},
        },
        "growth": {}, "pros": [], "cons": [],
        "documents": sec_documents(info["cik"], subs),
        "company_id": None, "warehouse_id": None, "is_financial": is_fin,
        "annual_eps_points": [(y, e) for y, e in zip(years, eps) if e is not None],
    }


def sec_documents(cik: int, subs: dict) -> list[dict]:
    rec = (subs.get("filings") or {}).get("recent") or {}
    forms = rec.get("form") or []
    groups = {"Annual reports (10-K)": [], "Quarterly reports (10-Q)": [], "Announcements (8-K)": []}
    for i, form in enumerate(forms):
        key = ("Annual reports (10-K)" if form in ("10-K", "20-F", "40-F") else "Quarterly reports (10-Q)" if form == "10-Q"
               else "Announcements (8-K)" if form == "8-K" else None)
        if not key or len(groups[key]) >= 5:
            continue
        acc = (rec.get("accessionNumber") or [""])[i].replace("-", "")
        doc = (rec.get("primaryDocument") or [""])[i]
        if not acc or not doc:
            continue
        rd = (rec.get("reportDate") or [""] * len(forms))[i] or ""
        fd = (rec.get("filingDate") or [""] * len(forms))[i] or ""
        desc = (rec.get("primaryDocDescription") or [""] * len(forms))[i] or form
        title = f"{form} for period {rd}" if rd else f"{form} filed {fd}"
        if form == "8-K":
            title = f"8-K · {desc}" if desc and desc != "8-K" else "8-K current report"
        groups[key].append({"title": title, "sub": f"filed {fd}", "url": f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}", "links": []})
    return [{"category": k, "items": v} for k, v in groups.items() if v]


def pe_history(bars: list[dict], eps_points: list[tuple]) -> dict:
    """Monthly P/E from price bars and annual EPS (each EPS used ~2 months after year end)."""
    if not bars or not eps_points:
        return {}
    pts = sorted((_d(y) + dt.timedelta(days=60), e) for y, e in eps_points)
    pe, eps_s = [], []
    seen = set()
    for b in bars:
        mo = b["t"][:7]
        if mo in seen:
            continue
        seen.add(mo)
        day = _d(b["t"])
        known = [e for d, e in pts if d <= day]
        if not known or known[-1] <= 0:
            continue
        pe.append([b["t"], round(b["c"] / known[-1], 2)])
        eps_s.append([b["t"], known[-1]])
    return {"Price to Earning": pe, "EPS": eps_s} if pe else {}


STARTER_US = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "BRK-B", "LLY", "AVGO", "JPM", "TSLA", "V", "UNH", "XOM", "MA",
              "JNJ", "PG", "HD", "COST", "ABBV", "MRK", "WMT", "NFLX", "CRM", "BAC", "KO", "PEP", "ORCL", "ADBE", "AMD",
              "TMO", "LIN", "MCD", "CSCO", "ACN", "ABT", "DHR", "TXN", "INTU", "QCOM", "CAT", "GE", "IBM", "AMGN", "NOW",
              "ISRG", "SPGI", "UNP", "HON", "LOW", "GS", "BKNG", "NKE", "SBUX", "MDT", "DE", "ADP", "PLD", "BLK", "TJX"]


def sp500_universe(download: bool = True) -> tuple[list[dict], str]:
    if config.DEMO:
        return [{"symbol": f"US:{t['ticker']}", "name": t["name"], "industry": ""} for t in tickers()], "demo"
    own = config.DATA_DIR / "universe_us.txt"
    if own.exists():
        syms = [l.strip().upper() for l in own.read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]
        return [{"symbol": f"US:{s}", "name": "", "industry": ""} for s in syms], "data/universe_us.txt"
    cached = config.DATA_DIR / "sp500.json"
    if download:
        try:
            from bs4 import BeautifulSoup
            r = requests.get("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies", timeout=20,
                             headers={"User-Agent": "Mozilla/5.0 EquityLens"})
            if r.status_code == 200:
                t = BeautifulSoup(r.text, "lxml").select_one("table#constituents")
                rows = []
                for tr in (t.select("tbody tr") if t else [])[1:]:
                    td = tr.find_all("td")
                    if len(td) >= 3:
                        rows.append({"symbol": "US:" + td[0].get_text(strip=True).replace(".", "-"),
                                     "name": td[1].get_text(strip=True), "industry": td[2].get_text(strip=True)})
                if len(rows) > 400:
                    cached.write_text(json.dumps(rows), encoding="utf-8")
        except Exception:  # noqa: BLE001 - fall back to cache / starter list
            pass
    if cached.exists():
        return json.loads(cached.read_text(encoding="utf-8")), "S&P 500 (Wikipedia)"
    return [{"symbol": f"US:{t}", "name": "", "industry": ""} for t in STARTER_US], "built-in US starter list"
