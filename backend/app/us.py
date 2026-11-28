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


class USNoFinancials(USFetchError):
    """SEC has no machine-readable annual figures yet (fresh IPO, SPAC, fund...). .profile holds what does exist."""
    def __init__(self, msg: str, profile: dict):
        super().__init__(msg)
        self.profile = profile


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
           "SalesRevenueNet", "SalesRevenueGoodsNet", "RevenuesNetOfInterestExpense", "InterestAndDividendIncomeOperating",
           "Revenue", "RevenueFromContractsWithCustomers"]   # US GAAP, then IFRS (20-F / 40-F filers)
OPINC = ["OperatingIncomeLoss",
         "ProfitLossFromOperatingActivities"]   # US GAAP, then IFRS (20-F / 40-F filers)
DEP = ["DepreciationDepletionAndAmortization", "DepreciationAndAmortization", "DepreciationAmortizationAndAccretionNet", "Depreciation",
       "DepreciationAndAmortisationExpense", "DepreciationAmortisationAndImpairmentLossReversalOfImpairmentLossRecognisedInProfitOrLoss", "DepreciationExpense"]   # US GAAP, then IFRS (20-F / 40-F filers)
INTEREST = ["InterestExpense", "InterestExpenseNonoperating", "InterestExpenseDebt", "InterestPaidNet",
            "FinanceCosts", "InterestExpense"]   # US GAAP, then IFRS (20-F / 40-F filers)
OTHER_INC = ["NonoperatingIncomeExpense", "OtherNonoperatingIncomeExpense",
             "OtherIncome"]   # US GAAP, then IFRS (20-F / 40-F filers)
PBT = ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
       "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
       "IncomeLossFromContinuingOperationsBeforeIncomeTaxesDomestic",
       "ProfitLossBeforeTax"]   # US GAAP, then IFRS (20-F / 40-F filers)
TAX = ["IncomeTaxExpenseBenefit",
       "IncomeTaxExpenseContinuingOperations"]   # US GAAP, then IFRS (20-F / 40-F filers)
NI = ["NetIncomeLoss", "ProfitLossAttributableToOwnersOfParent", "ProfitLoss",      # owners' share first (IFRS tag
      "NetIncomeLossAvailableToCommonStockholdersBasic"]                               # does not exist in US GAAP)
EPS = ["EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted", "EarningsPerShareBasic",
       "DilutedEarningsLossPerShare", "BasicEarningsLossPerShare", "BasicAndDilutedEarningsLossPerShare"]   # US GAAP, then IFRS (20-F / 40-F filers)
DPS = ["CommonStockDividendsPerShareDeclared", "CommonStockDividendsPerShareCashPaid",
       "DividendsRecognisedAsDistributionsToOwnersPerShare"]   # US GAAP, then IFRS (20-F / 40-F filers)
DIV_PAID = ["PaymentsOfDividendsCommonStock", "PaymentsOfDividends",
            "DividendsPaidClassifiedAsFinancingActivities", "DividendsPaid"]   # US GAAP, then IFRS (20-F / 40-F filers)
ASSETS = ["Assets"]
LIAB = ["Liabilities"]
EQUITY = ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
          "EquityAttributableToOwnersOfParent", "Equity"]   # US GAAP, then IFRS (20-F / 40-F filers)
COMMON = ["CommonStockValue", "CommonStocksIncludingAdditionalPaidInCapital",
          "IssuedCapital"]   # US GAAP, then IFRS (20-F / 40-F filers)
LTD = ["LongTermDebtNoncurrent", "LongTermDebt", "LongTermDebtAndCapitalLeaseObligations",
       "NoncurrentBorrowings", "LongtermBorrowings"]   # US GAAP, then IFRS (20-F / 40-F filers)
STD = ["LongTermDebtCurrent", "DebtCurrent", "ShortTermBorrowings", "CommercialPaper",
       "CurrentBorrowings", "ShorttermBorrowings", "CurrentPortionOfLongtermBorrowings"]   # US GAAP, then IFRS (20-F / 40-F filers)
PPE = ["PropertyPlantAndEquipmentNet",
       "PropertyPlantAndEquipment"]   # US GAAP, then IFRS (20-F / 40-F filers)
CWIP = ["ConstructionInProgressGross",
        "ConstructionInProgress"]   # US GAAP, then IFRS (20-F / 40-F filers)
INVEST = ["LongTermInvestments", "MarketableSecuritiesNoncurrent", "AvailableForSaleSecuritiesDebtSecuritiesNoncurrent",
          "NoncurrentInvestments", "OtherNoncurrentFinancialAssets"]   # US GAAP, then IFRS (20-F / 40-F filers)
RECV = ["AccountsReceivableNetCurrent", "ReceivablesNetCurrent",
        "TradeAndOtherCurrentReceivables", "CurrentTradeReceivables"]   # US GAAP, then IFRS (20-F / 40-F filers)
INVENT = ["InventoryNet",
          "Inventories"]   # US GAAP, then IFRS (20-F / 40-F filers)
COGS = ["CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold",
        "CostOfSales"]   # US GAAP, then IFRS (20-F / 40-F filers)
CFO = ["NetCashProvidedByUsedInOperatingActivities", "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
       "CashFlowsFromUsedInOperatingActivities"]   # US GAAP, then IFRS (20-F / 40-F filers)
CFI = ["NetCashProvidedByUsedInInvestingActivities", "NetCashProvidedByUsedInInvestingActivitiesContinuingOperations",
       "CashFlowsFromUsedInInvestingActivities"]   # US GAAP, then IFRS (20-F / 40-F filers)
CFF = ["NetCashProvidedByUsedInFinancingActivities", "NetCashProvidedByUsedInFinancingActivitiesContinuingOperations",
       "CashFlowsFromUsedInFinancingActivities"]   # US GAAP, then IFRS (20-F / 40-F filers)
SHARES = ["EntityCommonStockSharesOutstanding"]
WSHARES = ["WeightedAverageNumberOfDilutedSharesOutstanding", "WeightedAverageNumberOfSharesOutstandingBasic",
           "AdjustedWeightedAverageShares", "WeightedAverageShares"]   # US GAAP, then IFRS (20-F / 40-F filers)


def _d(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


def _label(end: str) -> str:
    return _d(end).strftime("%b %Y")


ANNUAL_FORMS = ("10-K", "20-F", "40-F")


class Facts:
    """SEC company facts. Reads US GAAP, or IFRS (ifrs-full) when a foreign filer reports under IFRS.
    Money is read in the company's reporting currency (self.cur): never mixed with another currency."""

    def __init__(self, raw: dict):
        f = raw.get("facts", {})
        self.dei = f.get("dei", {})
        gaap, ifrs = f.get("us-gaap", {}), f.get("ifrs-full", {})
        self.ns = "us-gaap"
        self.gaap = gaap
        if ifrs and not self._has_annual(gaap, REVENUE) and (self._has_annual(ifrs, REVENUE) or not gaap):
            self.ns, self.gaap = "ifrs-full", ifrs
        self.cur = self._currency()

    @staticmethod
    def _has_annual(node: dict, tags: list[str]) -> bool:
        for t in tags:
            for es in ((node.get(t) or {}).get("units") or {}).values():
                if any(str(e.get("form", "")).startswith(ANNUAL_FORMS) for e in es):
                    return True
        return False

    def _currency(self) -> str:
        """The unit most used by the revenue / assets / profit tags (e.g. USD, EUR, TWD)."""
        count: dict[str, int] = {}
        for t in REVENUE + ASSETS + NI:
            for u, es in ((self.gaap.get(t) or {}).get("units") or {}).items():
                if "/" not in u and u not in ("shares", "pure"):
                    count[u] = count.get(u, 0) + len(es)
        return max(count, key=count.get) if count else "USD"

    def annual_form(self) -> Optional[str]:
        """'10-K', '20-F' or '40-F': the annual report form behind the revenue figures."""
        for t in REVENUE:
            for es in ((self.gaap.get(t) or {}).get("units") or {}).values():
                forms = [str(e.get("form", "")) for e in es if str(e.get("form", "")).startswith(ANNUAL_FORMS)]
                if forms:
                    return max(set(forms), key=forms.count)[:4]
        return None

    def _entries(self, tag: str, ns: str = "gaap") -> list[dict]:
        node = (self.gaap if ns == "gaap" else self.dei).get(tag)
        if not node:
            return []
        units = node.get("units", {})
        for u in (self.cur, f"{self.cur}/shares", "shares", "pure"):
            if u in units:
                return units[u]
        if ns == "dei":
            return next(iter(units.values()), [])
        return []          # a money tag in another currency only: not used (never mixed)

    def annual_flow(self, tags: list[str]) -> dict[str, float]:
        """{fiscal-year-end ISO date: value} from 10-K full-year durations; earlier tags win per year."""
        out: dict[str, float] = {}
        for tag in tags:
            best: dict[str, tuple] = {}
            for e in self._entries(tag):
                if "start" not in e or not str(e.get("form", "")).startswith(ANNUAL_FORMS):
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
                  info: dict, facts_raw: dict, subs: dict, fx: Optional[dict] = None, nasdaq_cap: Optional[float] = None) -> dict:
    """fx: {"rate": US$ per 1 unit of the reporting currency, "date", "source"} - needed when the company does not
    report in US$. nasdaq_cap: market cap in $ M as Nasdaq states it - used for 20-F / 40-F filers, whose US-traded
    share (often an ADS) can stand for several home-market shares, so SEC share counts x the US price would be wrong."""
    F = Facts(facts_raw)
    sales_a = F.annual_flow(REVENUE)
    if len(sales_a) < 1:
        raise USFetchError(f"No annual financials in SEC filings for {ticker}.")
    k = 1.0
    if F.cur != "USD":
        if not fx or not fx.get("rate"):
            raise USFetchError(f"{ticker} reports in {F.cur}; the {F.cur}→US$ exchange rate could not be loaded, so its numbers are not shown.")
        k = fx["rate"]
    form = F.annual_form() or "10-K"
    foreign = form in ("20-F", "40-F")

    def _m(v):  # reporting currency -> US$ million
        return None if v is None else round(v * k / 1e6, 2)
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
    eps = row(EPS, conv=lambda v: round(v * k, 2))
    dps = row(DPS, conv=lambda v: round(v * k, 4))
    adr_shares = None
    if foreign:
        # per-share figures on the basis of the US-traded share: Nasdaq market cap ÷ US price = traded-share count
        adr_shares = nasdaq_cap * 1e6 / price if nasdaq_cap and price else None
        eps = [round(n * 1e6 / adr_shares, 2) if n is not None and adr_shares else None for n in ni]
        dps = [None] * len(years)
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
        ttm = {"sales": _m(sum(q_sales[q] for q in qk)),
               "ni": _m(sum(q_ni.get(q, 0) for q in qk)) if all(q in q_ni for q in qk) else None,
               "eps": round(sum(q_eps[q] for q in qk) * k, 2) if all(q in q_eps for q in qk) else None}
        if foreign:
            ttm["eps"] = round(ttm["ni"] * 1e6 / adr_shares, 2) if ttm.get("ni") is not None and adr_shares else None
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
        return [_m(d.get(q)) for q in bs_keys]

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
    q_ebitda = {q: q_op[q] + (q_dep.get(q) or 0) for q in qkeys if q in q_op}
    quarters = {"columns": [_label(q) for q in qkeys], "rows": {
        "Sales": [_m(q_sales.get(q)) for q in qkeys],
        "Operating Profit": [_m(q_ebitda.get(q)) for q in qkeys],
        "OPM %": [round(q_ebitda[q] / q_sales[q] * 100, 1) if q in q_ebitda and q_sales.get(q) else None for q in qkeys],
        "Net Profit": [_m(q_ni.get(q)) for q in qkeys],
        "EPS in Rs": [(round(q_eps[q] * k, 2) if not foreign else None) if q in q_eps else None for q in qkeys],
    }} if qkeys else {"columns": [], "rows": {}}
    quarters["rows"] = {k: v for k, v in quarters["rows"].items() if any(x is not None for x in v)}

    # top ratios
    shares = adr_shares if foreign else (F.latest_dei(SHARES) or F.latest_weighted_shares())
    eps_ttm = ttm.get("eps") if ttm_ok and ttm.get("eps") is not None else (eps[-1] if eps else None)
    eq_latest = eq_l[-1] if eq_l else None
    dps_ttm = dps[-1] if dps and dps[-1] is not None else (
        abs(divpaid[-1]) * 1e6 / shares if divpaid and divpaid[-1] is not None and shares else None)
    ratios = {}
    if price:
        ratios["current_price"] = round(price, 2)
        if foreign and nasdaq_cap:
            ratios["market_cap"] = round(nasdaq_cap, 0)
        elif shares:
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
             + (f" Financials are from its SEC filings ({form} annual reports"
                + (", IFRS" if F.ns == "ifrs-full" else "") + ")." if foreign else " Financials are from its SEC filings (10-K and 10-Q).")
             + (f" It reports in {F.cur}; amounts are shown in US$ converted at 1 {F.cur} = ${k:.6g} ({fx.get('source')}, {fx.get('date')}) for every year, so growth rates stay in {F.cur} terms." if F.cur != "USD" else "")
             + (" Per-share figures are per US-traded share (Nasdaq market cap ÷ US price)." if foreign and adr_shares else
                " Per-share figures, P/E and market cap are not shown: the US-traded share's market cap is not available yet." if foreign else ""))

    return {
        "name": subs.get("name") or info["name"], "symbol": f"US:{info['ticker']}", "bse_code": None,
        "nse_symbol": None, "us_ticker": info["ticker"], "cik": info["cik"], "market": "US",
        "currency": {"code": "USD", "symbol": "$", "unit": "M"},
        "reporting": {"currency": F.cur, "standard": "IFRS" if F.ns == "ifrs-full" else "US GAAP", "form": form,
                      "fx": fx if F.cur != "USD" else None, "foreign": foreign,
                      "per_share": "US-traded share (Nasdaq market cap ÷ price)" if foreign and adr_shares else None},
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


PROSPECTUS = ("S-1", "S-1/A", "F-1", "F-1/A", "424B4", "424B1", "424B3", "S-11", "F-3")
SPAC_SIC = "6770"
FUND_SIC = ("6722", "6726", "6798")      # investment offices / trusts, REIT-like trusts (shown as "fund or trust")


def _filings(cik: int, subs: dict, forms: tuple, limit: int = 6) -> list[dict]:
    rec = (subs.get("filings") or {}).get("recent") or {}
    out = []
    for i, form in enumerate(rec.get("form") or []):
        if form not in forms:
            continue
        acc = (rec.get("accessionNumber") or [""])[i].replace("-", "")
        doc = (rec.get("primaryDocument") or [""])[i]
        if acc and doc:
            out.append({"form": form, "filed": (rec.get("filingDate") or [""])[i], "period": (rec.get("reportDate") or [""])[i] or None,
                        "url": f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}"})
        if len(out) >= limit:
            break
    return out


def profile(info: dict, facts_raw: dict, subs: dict, bars: list[dict], ipo_row: Optional[dict], nasdaq: Optional[dict],
            fx: Optional[dict] = None) -> dict:
    """What a company without annual SEC figures does have: identity, listing, IPO, price, any quarterly figures,
    latest balance sheet and its filings. Every figure comes from SEC, Nasdaq or the price feed; nothing estimated."""
    F = Facts(facts_raw)
    sic = str(subs.get("sic") or "")
    rec = (subs.get("filings") or {}).get("recent") or {}
    forms = rec.get("form") or []
    dates = [d for d in (rec.get("filingDate") or []) if d]
    first = min(dates) if dates else None
    kind = ("spac" if sic == SPAC_SIC else "fund" if sic in FUND_SIC
            else "new_listing" if (ipo_row or any(f in PROSPECTUS for f in forms)) else "no_financials")
    k = (fx or {}).get("rate") if F.cur != "USD" else 1.0
    qs = {}
    if k:
        q_sales, q_ni = F.quarterly_flow(REVENUE), F.quarterly_flow(NI)
        keys = sorted(set(q_sales) | set(q_ni))[-8:]
        if keys:
            qs = {"columns": [_label(q) for q in keys], "rows": {
                "Sales": [round(q_sales[q] * k / 1e6, 2) if q in q_sales else None for q in keys],
                "Net Profit": [round(q_ni[q] * k / 1e6, 2) if q in q_ni else None for q in keys]}}
    bal = None
    if k:
        ad, eqd = F.instant(ASSETS, []), F.instant(EQUITY, [])
        if ad:
            end = max(ad)
            bal = {"date": end, "assets": round(ad[end] * k / 1e6, 2),
                   "equity": round(eqd[end] * k / 1e6, 2) if end in eqd else None}
    last = bars[-1] if bars else None
    move = None
    if ipo_row and ipo_row.get("final_price") and bars:
        from . import ipo as ipo_mod
        m = ipo_mod.us_listing_move(bars, ipo_row["priced"], ipo_row["final_price"])
        move = m if isinstance(m, dict) else None
    exch = ", ".join(subs.get("exchanges") or []) or (nasdaq or {}).get("exchange")
    why = {"spac": "It is a SPAC (blank-check company): it has no operating business until it merges with one.",
           "fund": "It is an investment fund or trust, so it has no operating financials to score.",
           "new_listing": "It listed recently and has not filed a 10-K or 10-Q with tagged financial figures yet; "
                          "its numbers are only in the prospectus text. This page fills in by itself once SEC has them.",
           "no_financials": "SEC has no tagged annual figures for it (this can happen for some foreign filers, "
                            "trusts and recently restructured companies)."}[kind]
    return {"kind": kind, "why": why, "symbol": f"US:{info['ticker']}", "ticker": info["ticker"], "cik": info["cik"],
            "name": subs.get("name") or info["name"], "exchange": exch, "sic": sic or None,
            "industry": subs.get("sicDescription") or (nasdaq or {}).get("industry"), "sector": (nasdaq or {}).get("sector"),
            "country": (nasdaq or {}).get("country"), "state": subs.get("stateOfIncorporation") or None,
            "website": subs.get("website") or None, "fiscal_year_end": subs.get("fiscalYearEnd") or None,
            "first_filing": first, "market_cap": (nasdaq or {}).get("market_cap"),
            "price": round(last["c"], 2) if last else None, "price_date": last["t"] if last else None,
            "first_trade": bars[0]["t"] if bars else None,
            "ipo": ({k2: ipo_row.get(k2) for k2 in ("priced", "final_price", "range_text", "shares", "value_m", "exchange")}
                    if ipo_row else None),
            "listing_move": move, "quarters": qs, "balance": bal,
            "reporting": {"currency": F.cur, "standard": "IFRS" if F.ns == "ifrs-full" else "US GAAP", "fx": fx if F.cur != "USD" else None},
            "prospectus": _filings(info["cik"], subs, PROSPECTUS, 4),
            "reports": _filings(info["cik"], subs, ("10-Q", "10-K", "20-F", "40-F", "6-K", "8-K"), 6)}


def sec_documents(cik: int, subs: dict) -> list[dict]:
    rec = (subs.get("filings") or {}).get("recent") or {}
    forms = rec.get("form") or []
    groups = {"Annual reports (10-K / 20-F)": [], "Quarterly reports (10-Q)": [], "Announcements (8-K / 6-K)": [],
              "Prospectus (IPO / offering)": []}
    for i, form in enumerate(forms):
        key = ("Annual reports (10-K / 20-F)" if form in ("10-K", "20-F", "40-F") else "Quarterly reports (10-Q)" if form == "10-Q"
               else "Announcements (8-K / 6-K)" if form in ("8-K", "6-K") else "Prospectus (IPO / offering)" if form in PROSPECTUS else None)
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
                                     "name": td[1].get_text(strip=True), "industry": td[2].get_text(strip=True),
                                     "sub": td[3].get_text(strip=True) if len(td) >= 4 else ""})   # GICS sector, GICS sub-industry
                if len(rows) > 400:
                    cached.write_text(json.dumps(rows), encoding="utf-8")
        except Exception:  # noqa: BLE001 - fall back to cache / starter list
            pass
    if cached.exists():
        return json.loads(cached.read_text(encoding="utf-8")), "S&P 500 (Wikipedia)"
    return [{"symbol": f"US:{t}", "name": "", "industry": ""} for t in STARTER_US], "built-in US starter list"
