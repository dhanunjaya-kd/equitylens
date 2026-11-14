"""Research engine: turns parsed company numbers into scores, flags,
3/5/10-year scenarios and a plain-English verdict.

Everything is rule-based and transparent: every score can be traced to
the inputs shown in the report. Past numbers do not guarantee the future;
the scenarios show what happens under stated assumptions, they are not
predictions.
"""
from __future__ import annotations

import math
import statistics
from typing import Optional

from . import config

Num = Optional[float]


# ----------------------------------------------------------------- helpers
def _valid(x) -> bool:
    return x is not None and isinstance(x, (int, float)) and not math.isnan(x)


def scale(x: Num, points: list[tuple[float, float]]) -> Num:
    """Piecewise-linear map of x onto a 0-100 score."""
    if not _valid(x):
        return None
    if x <= points[0][0]:
        return points[0][1]
    for (x0, s0), (x1, s1) in zip(points, points[1:]):
        if x <= x1:
            return s0 + (s1 - s0) * (x - x0) / (x1 - x0)
    return points[-1][1]


def wavg(pairs: list[tuple[Num, float]]) -> Num:
    got = [(v, w) for v, w in pairs if _valid(v)]
    if not got:
        return None
    tw = sum(w for _, w in got)
    return sum(v * w for v, w in got) / tw


def r1(x: Num, nd: int = 1) -> Num:
    return round(x, nd) if _valid(x) else None


class Table:
    def __init__(self, t: dict | None):
        t = t or {}
        self.columns: list[str] = t.get("columns", [])
        self.rows: dict[str, list] = t.get("rows", {})
        self.annual_idx = [i for i, c in enumerate(self.columns) if "ttm" not in c.lower()]
        self.ttm_idx = next((i for i, c in enumerate(self.columns) if "ttm" in c.lower()), None)

    def row(self, *names: str) -> list:
        """First row whose label starts with any of the given names (case-insensitive)."""
        for n in names:
            n = n.lower()
            for label, vals in self.rows.items():
                if label.lower() == n:
                    return vals
        for n in names:
            n = n.lower()
            for label, vals in self.rows.items():
                if label.lower().startswith(n):
                    return vals
        return []

    def annual(self, *names: str) -> list:
        vals = self.row(*names)
        return [vals[i] if i < len(vals) else None for i in self.annual_idx] if vals else []

    def ttm(self, *names: str) -> Num:
        vals = self.row(*names)
        if vals and self.ttm_idx is not None and self.ttm_idx < len(vals):
            return vals[self.ttm_idx]
        return None

    def annual_map(self, *names: str) -> dict:
        vals = self.row(*names)
        if not vals:
            return {}
        return {self.columns[i]: vals[i] for i in self.annual_idx if i < len(vals)}

    @property
    def annual_columns(self) -> list[str]:
        return [self.columns[i] for i in self.annual_idx]


def aligned(map_a: dict, map_b: dict) -> tuple[list, list]:
    """Values of two {period: value} maps over the periods both share, in order of map_a."""
    keys = [k for k in map_a if k in map_b]
    return [map_a[k] for k in keys], [map_b[k] for k in keys]


def last(vals: list, k: int = 1) -> Num:
    """k-th last valid value (k=1 -> latest)."""
    got = [v for v in vals if _valid(v)]
    return got[-k] if len(got) >= k else None


def cagr(vals: list, years: int) -> Num:
    """CAGR between the latest value and the value `years` periods before it."""
    if not vals or len(vals) <= years:
        return None
    end, start = vals[-1], vals[-1 - years]
    if not (_valid(end) and _valid(start)) or start <= 0 or end <= 0:
        return None
    return ((end / start) ** (1 / years) - 1) * 100


def mean_last(vals: list, n: int) -> Num:
    got = [v for v in vals[-n:] if _valid(v)]
    return sum(got) / len(got) if got else None


# ----------------------------------------------------------------- metrics
def compute_metrics(c: dict) -> dict:
    pl = Table(c["tables"].get("profit_loss"))
    bs = Table(c["tables"].get("balance_sheet"))
    cf = Table(c["tables"].get("cash_flow"))
    ra = Table(c["tables"].get("ratios"))
    sh = Table(c["tables"].get("shareholding_quarterly"))
    top = c.get("ratios", {})
    fin = c.get("is_financial", False)

    sales = pl.annual("Sales", "Revenue")
    op_profit = pl.annual("Operating Profit", "Financing Profit")
    opm = pl.annual("OPM", "Financing Margin")
    other_inc = pl.annual("Other Income")
    interest = pl.annual("Interest")
    pbt = pl.annual("Profit before tax")
    np_ = pl.annual("Net Profit")
    eps = pl.annual("EPS in Rs", "EPS")
    payout = pl.annual("Dividend Payout")

    eq_cap = bs.annual("Equity Capital", "Share Capital")
    reserves = bs.annual("Reserves")
    borrow = bs.annual("Borrowings", "Borrowing")
    total_assets = bs.annual("Total Assets", "Total Liabilities")

    cfo = cf.annual("Cash from Operating Activity", "Cash from Operating")
    cfi = cf.annual("Cash from Investing Activity", "Cash from Investing")

    roce_series = ra.annual("ROCE")
    roe_series = ra.annual("ROE")
    debtor_days = ra.annual("Debtor Days")
    wc_days = ra.annual("Working Capital Days")

    m: dict = {"is_financial": fin, "years": pl.annual_columns}

    # -- growth (prefer the source's own compounded figures, else compute)
    g = c.get("growth", {})

    def from_growth(title_start: str, key: str) -> Num:
        for title, vals in g.items():
            if title.lower().startswith(title_start):
                for k, v in vals.items():
                    if k.lower().startswith(key):
                        return v
        return None

    for n in (3, 5, 10):
        m[f"sales_cagr_{n}"] = r1(from_growth("compounded sales", f"{n} year") if _valid(from_growth("compounded sales", f"{n} year")) else cagr(sales, n))
        m[f"profit_cagr_{n}"] = r1(from_growth("compounded profit", f"{n} year") if _valid(from_growth("compounded profit", f"{n} year")) else cagr(np_, n))
        m[f"eps_cagr_{n}"] = r1(cagr(eps, n))
    m["price_cagr_5"] = r1(from_growth("stock price", "5 year"))
    m["price_cagr_10"] = r1(from_growth("stock price", "10 year"))
    m["roe_10_src"] = r1(from_growth("return on equity", "10 year"))
    m["roe_5_src"] = r1(from_growth("return on equity", "5 year"))
    m["roe_3_src"] = r1(from_growth("return on equity", "3 year"))

    # consistency: how many of the last up-to-9 year-on-year changes grew profit
    ups = tot = 0
    seq = [v for v in np_[-10:]]
    for a, b in zip(seq, seq[1:]):
        if _valid(a) and _valid(b):
            tot += 1
            ups += 1 if b > a else 0
    m["profit_up_years"], m["profit_years_checked"] = ups, tot

    m["sales_latest"] = r1(pl.ttm("Sales", "Revenue") if _valid(pl.ttm("Sales", "Revenue")) else last(sales))
    m["profit_latest"] = r1(pl.ttm("Net Profit") if _valid(pl.ttm("Net Profit")) else last(np_))
    m["eps_ttm"] = r1(pl.ttm("EPS in Rs", "EPS") if _valid(pl.ttm("EPS in Rs", "EPS")) else last(eps), 2)

    # -- profitability
    m["opm_latest"] = r1(last(opm))
    m["opm_avg_5"] = r1(mean_last(opm, 5))
    opm5 = [v for v in opm[-5:] if _valid(v)]
    m["opm_cv"] = r1(statistics.pstdev(opm5) / abs(statistics.mean(opm5)), 3) if len(opm5) >= 3 and statistics.mean(opm5) else None

    m["roce_latest"] = r1(top.get("roce") if _valid(top.get("roce")) else last(roce_series))
    m["roce_avg_5"] = r1(mean_last(roce_series, 5)) if roce_series else m["roce_latest"]

    equity = [(a or 0) + (b or 0) if (_valid(a) or _valid(b)) else None for a, b in zip(eq_cap, reserves)] if eq_cap else []
    eq_map = dict(zip(bs.annual_columns, equity))
    np_al, eq_al = aligned(pl.annual_map("Net Profit"), eq_map)
    roe_calc = []
    for i in range(1, len(np_al)):
        a, e1, e0 = np_al[i], eq_al[i], eq_al[i - 1]
        roe_calc.append(a / ((e1 + e0) / 2) * 100 if _valid(a) and _valid(e1) and _valid(e0) and (e1 + e0) > 0 else None)
    m["roe_latest"] = r1(top.get("roe") if _valid(top.get("roe")) else last(roe_series or roe_calc))
    m["roe_avg_5"] = r1(m["roe_5_src"] if _valid(m["roe_5_src"]) else mean_last(roe_series or roe_calc, 5))

    # -- balance sheet
    eq_latest = last(equity) if equity else None
    m["net_worth"] = r1(eq_latest)
    m["borrowings"] = r1(last(borrow))
    m["debt_to_equity"] = r1(last(borrow) / eq_latest, 2) if _valid(last(borrow)) and _valid(eq_latest) and eq_latest > 0 else (r1(top.get("debt_to_equity"), 2))
    if _valid(last(interest)) and _valid(last(pbt)) and not fin:
        it = last(interest)
        m["interest_coverage"] = r1((last(pbt) + it) / it) if it > 0.01 else 999.0
    else:
        m["interest_coverage"] = None
    ta = last(total_assets)
    m["equity_to_assets"] = r1(eq_latest / ta * 100) if _valid(eq_latest) and _valid(ta) and ta > 0 else None

    # -- cash flow
    cfo_al, np_cf = aligned(cf.annual_map("Cash from Operating Activity", "Cash from Operating"), pl.annual_map("Net Profit"))
    pairs = [(a, b) for a, b in zip(cfo_al[-5:], np_cf[-5:]) if _valid(a) and _valid(b)]
    tot_np = sum(b for _, b in pairs)
    m["cfo_to_pat_5"] = r1(sum(a for a, _ in pairs) / tot_np, 2) if pairs and tot_np > 0 else None
    fcf = [(a + b) if _valid(a) and _valid(b) else None for a, b in zip(cfo, cfi)]
    m["fcf_series"] = [r1(x) for x in fcf]
    f5 = [x for x in fcf[-5:] if _valid(x)]
    m["fcf_positive_years_5"] = sum(1 for x in f5 if x > 0) if f5 else None
    m["fcf_sum_5"] = r1(sum(f5)) if f5 else None

    # -- earnings quality
    if _valid(last(other_inc)) and _valid(last(pbt)) and last(pbt) > 0:
        m["other_income_share"] = r1(last(other_inc) / last(pbt) * 100)
    else:
        m["other_income_share"] = None
    m["dividend_payout_avg_5"] = r1(mean_last(payout, 5))

    # -- dilution: implied share count = net profit / EPS
    shares = [(n / e) if _valid(n) and _valid(e) and e > 0 and n > 0 else None for n, e in zip(np_, eps)]
    s_now, s_old = last(shares), (shares[-6] if len(shares) >= 6 else None)
    m["share_count_change_5"] = r1((s_now / s_old - 1) * 100) if _valid(s_now) and _valid(s_old) and s_old > 0 else None

    m["debtor_days_latest"] = r1(last(debtor_days))
    m["debtor_days_5y_ago"] = r1(debtor_days[-6]) if len(debtor_days) >= 6 else None
    m["wc_days_latest"] = r1(last(wc_days))

    # -- ownership (quarterly)
    prom = sh.row("Promoters", "Promoter")
    fii = sh.row("FIIs", "FII")
    dii = sh.row("DIIs", "DII")
    pub = sh.row("Public")
    m["promoter_latest"] = r1(last(prom)) if prom else (r1(top.get("promoter_holding")))
    m["promoter_change_8q"] = r1(last(prom) - prom[-9]) if prom and len(prom) >= 9 and _valid(prom[-9]) and _valid(last(prom)) else (
        r1(last(prom) - next((v for v in prom if _valid(v)), None)) if prom and _valid(last(prom)) and _valid(next((v for v in prom if _valid(v)), None)) else None)
    inst = [(a or 0) + (b or 0) if (_valid(a) or _valid(b)) else None for a, b in zip(fii or [None] * len(dii), dii or [None] * len(fii))]
    m["fii_latest"], m["dii_latest"] = r1(last(fii)) if fii else None, r1(last(dii)) if dii else None
    m["public_latest"] = r1(last(pub)) if pub else None
    first_inst = inst[-9] if len(inst) >= 9 else next((v for v in inst if _valid(v)), None)
    m["institutional_change_8q"] = r1(last(inst) - first_inst) if inst and _valid(last(inst)) and _valid(first_inst) else None
    m["pledged"] = r1(top.get("pledged"))

    # -- valuation
    m["price"] = r1(top.get("current_price"), 2)
    m["market_cap"] = r1(top.get("market_cap"), 0)
    m["pe"] = r1(top.get("pe"))
    if not _valid(m["pe"]) and _valid(m["price"]) and _valid(m["eps_ttm"]) and m["eps_ttm"] > 0:
        m["pe"] = r1(m["price"] / m["eps_ttm"])
    bv = top.get("book_value")
    m["book_value"] = r1(bv)
    m["pb"] = r1(m["price"] / bv, 2) if _valid(m["price"]) and _valid(bv) and bv > 0 else r1(top.get("pb"), 2)
    m["dividend_yield"] = r1(top.get("dividend_yield"), 2)
    m["face_value"] = r1(top.get("face_value"), 2)
    m["high_52w"], m["low_52w"] = top.get("high"), top.get("low")
    if _valid(m["price"]) and _valid(m["high_52w"]) and m["high_52w"] > 0:
        m["off_high_pct"] = r1((m["price"] / m["high_52w"] - 1) * 100)
    else:
        m["off_high_pct"] = None
    m["earnings_yield"] = r1(100 / m["pe"], 2) if _valid(m["pe"]) and m["pe"] > 0 else None
    g5 = m["profit_cagr_5"]
    m["peg"] = r1(m["pe"] / g5, 2) if _valid(m["pe"]) and m["pe"] > 0 and _valid(g5) and g5 > 0 else None
    return m


# ----------------------------------------------------------------- scores
def compute_scores(m: dict, median_pe: Num) -> dict:
    fin = m["is_financial"]
    s: dict = {}

    consistency = (m["profit_up_years"] / m["profit_years_checked"] * 100) if m.get("profit_years_checked") else None
    growth_pts = [(-10, 0), (0, 20), (10, 60), (15, 75), (20, 90), (30, 100)]
    s["growth"] = wavg([
        (scale(m["profit_cagr_5"], growth_pts), 0.45),
        (scale(m["sales_cagr_5"], growth_pts), 0.35),
        (consistency, 0.20),
    ])

    if fin:
        s["quality"] = wavg([(scale(m["roe_avg_5"] if _valid(m["roe_avg_5"]) else m["roe_latest"],
                                    [(0, 0), (8, 25), (12, 55), (15, 70), (18, 85), (22, 100)]), 1.0)])
        s["strength"] = scale(m["equity_to_assets"], [(3, 10), (5, 25), (8, 50), (12, 70), (20, 90), (30, 100)])
        s["cash"] = None  # cash-flow statements of lenders don't measure the same thing
    else:
        roce = m["roce_avg_5"] if _valid(m["roce_avg_5"]) else m["roce_latest"]
        s["quality"] = wavg([
            (scale(roce, [(0, 0), (5, 15), (10, 45), (15, 65), (20, 80), (30, 100)]), 0.75),
            (scale(m["opm_cv"], [(0.05, 100), (0.15, 75), (0.3, 40), (0.6, 10)]), 0.25),
        ])
        de = m["debt_to_equity"]
        s["strength"] = wavg([
            (scale(de, [(0, 100), (0.1, 95), (0.3, 85), (0.6, 65), (1.0, 45), (2.0, 15), (3.0, 0)]), 0.6),
            (scale(m["interest_coverage"], [(1, 5), (3, 40), (6, 70), (10, 90), (20, 100)]), 0.4),
        ])
        fcf_frac = (m["fcf_positive_years_5"] / 5 * 100) if _valid(m["fcf_positive_years_5"]) else None
        s["cash"] = wavg([
            (scale(m["cfo_to_pat_5"], [(0, 0), (0.3, 10), (0.6, 40), (0.8, 65), (1.0, 85), (1.2, 100)]), 0.75),
            (fcf_frac, 0.25),
        ])

    prom = m["promoter_latest"]
    prom_level = 55.0 if (prom is not None and prom < 0.5) else scale(prom, [(10, 30), (25, 40), (40, 60), (50, 70), (60, 80), (75, 85)])
    prom_trend = None if (prom is not None and prom < 0.5) else scale(m["promoter_change_8q"], [(-10, 10), (-5, 30), (-2, 50), (0, 65), (2, 80), (5, 95)])
    pledge_pen = scale(m.get("pledged"), [(0, 100), (5, 70), (15, 30), (40, 0)])
    s["ownership"] = wavg([
        (prom_level, 0.25), (prom_trend, 0.35),
        (scale(m["institutional_change_8q"], [(-5, 30), (0, 55), (3, 75), (6, 90)]), 0.25),
        (pledge_pen, 0.15),
    ])

    pe = m["pe"]
    if _valid(m.get("eps_ttm")) and m["eps_ttm"] <= 0:
        s["valuation"] = 10.0
    else:
        parts = [
            (scale(pe, [(5, 95), (8, 95), (15, 80), (25, 60), (40, 35), (60, 15), (100, 5)]), 0.35),
            (scale(m["peg"], [(0.5, 95), (1.0, 75), (1.5, 55), (2.0, 40), (3.0, 20), (5.0, 5)]), 0.30),
        ]
        if _valid(median_pe) and median_pe > 0 and _valid(pe):
            parts.append((scale(pe / median_pe, [(0.6, 90), (0.8, 75), (1.0, 60), (1.3, 40), (1.8, 15)]), 0.35))
        if fin:
            parts.append((scale(m["pb"], [(0.8, 90), (1.5, 75), (3, 50), (5, 25), (8, 10)]), 0.35))
        s["valuation"] = wavg(parts)

    s["business"] = wavg([(s["growth"], 0.28), (s["quality"], 0.28), (s["strength"], 0.17),
                          (s["cash"], 0.17), (s["ownership"], 0.10)])
    s["overall"] = wavg([(s["business"], 0.8), (s["valuation"], 0.2)])
    return {k: r1(v, 0) for k, v in s.items()}


# ----------------------------------------------------------------- flags
def compute_flags(m: dict, c: dict) -> tuple[list[dict], list[str]]:
    fin = m["is_financial"]
    flags: list[dict] = []

    def add(sev, text):
        flags.append({"severity": sev, "text": text})

    if _valid(m.get("eps_ttm")) and m["eps_ttm"] <= 0:
        add("high", "Loss-making on the latest 12 months — earnings-based valuation doesn't apply.")
    if not fin:
        de = m["debt_to_equity"]
        if _valid(de) and de > 1:
            add("high", f"High debt: borrowings are {de}x net worth.")
        elif _valid(de) and de > 0.6:
            add("medium", f"Debt is notable at {de}x net worth.")
        ic = m["interest_coverage"]
        if _valid(ic) and ic < 2:
            add("high", f"Interest coverage only {ic}x — profits barely cover interest.")
        elif _valid(ic) and ic < 3:
            add("medium", f"Interest coverage is thin at {ic}x.")
        cp = m["cfo_to_pat_5"]
        if _valid(cp) and cp < 0.5:
            add("high", f"Over 5 years only {int(cp*100)}% of reported profit turned into operating cash.")
        elif _valid(cp) and cp < 0.7:
            add("medium", f"Cash conversion is weak: {int(cp*100)}% of profit became operating cash over 5 years.")
        if _valid(m["opm_latest"]) and _valid(m["opm_avg_5"]) and m["opm_latest"] < m["opm_avg_5"] - 5:
            add("medium", f"Margins slipping: operating margin {m['opm_latest']}% vs 5-yr average {m['opm_avg_5']}%.")
        dd, dd0 = m["debtor_days_latest"], m["debtor_days_5y_ago"]
        if _valid(dd) and _valid(dd0) and dd0 > 0 and dd > 60 and dd > dd0 * 1.5:
            add("medium", f"Customers paying slower: debtor days rose from {dd0} to {dd}.")
    pc = m["promoter_change_8q"]
    if _valid(pc) and pc < -5:
        add("high", f"Promoters cut their stake by {abs(pc)} percentage points over ~2 years.")
    elif _valid(pc) and pc < -2:
        add("medium", f"Promoter stake down {abs(pc)} percentage points over ~2 years.")
    if _valid(m.get("pledged")) and m["pledged"] > 10:
        add("high", f"{m['pledged']}% of promoter shares are pledged.")
    if _valid(m["profit_cagr_3"]) and m["profit_cagr_3"] < -5:
        add("medium", f"Profits shrinking: {m['profit_cagr_3']}% a year over 3 years.")
    if _valid(m["share_count_change_5"]) and m["share_count_change_5"] > 15:
        add("medium", f"Share count up ~{m['share_count_change_5']}% in 5 years (dilution or a split/bonus — check).")
    if not fin and _valid(m["other_income_share"]) and m["other_income_share"] > 30:
        add("medium", f"Other income is {m['other_income_share']}% of pre-tax profit — core business earns less than it looks.")
    if _valid(m["pe"]) and m["pe"] > 80:
        add("medium", f"Very expensive: P/E of {m['pe']}.")
    if _valid(m["market_cap"]) and m["market_cap"] < 500:
        add("info", f"Small company (market cap ₹{int(m['market_cap'])} Cr): lower liquidity, higher risk.")
    if len(m.get("years") or []) < 5:
        add("info", "Less than 5 years of annual data — long-term numbers are limited.")

    strengths: list[str] = []
    roce = m["roe_avg_5"] if fin else m["roce_avg_5"]
    if _valid(roce) and roce >= (16 if fin else 20):
        strengths.append(f"High returns on capital: {'ROE' if fin else 'ROCE'} averaged {roce}% over 5 years.")
    if _valid(m["profit_cagr_5"]) and m["profit_cagr_5"] >= 15:
        strengths.append(f"Profits compounded at {m['profit_cagr_5']}% a year over 5 years.")
    if not fin and _valid(m["debt_to_equity"]) and m["debt_to_equity"] <= 0.1:
        strengths.append("Almost debt-free balance sheet.")
    if not fin and _valid(m["cfo_to_pat_5"]) and m["cfo_to_pat_5"] >= 0.9:
        strengths.append("Profits convert well into cash.")
    if m.get("profit_years_checked") and m["profit_up_years"] / m["profit_years_checked"] >= 0.75 and m["profit_years_checked"] >= 5:
        strengths.append(f"Consistent: profit grew in {m['profit_up_years']} of the last {m['profit_years_checked']} years.")
    if _valid(pc) and pc >= 1:
        strengths.append(f"Promoters raised their stake by {pc} points in ~2 years.")
    if _valid(m["institutional_change_8q"]) and m["institutional_change_8q"] >= 2:
        strengths.append(f"Institutions (FII + DII) added {m['institutional_change_8q']} points in ~2 years.")
    if _valid(m["peg"]) and m["peg"] <= 1:
        strengths.append(f"Price looks reasonable for its growth (PEG {m['peg']}).")

    # Holding-company discount (the Elcid-type situation)
    sector_text = " ".join(c.get("sector_path") or []).lower() + " " + (c.get("about") or "").lower()[:300]
    if ("investment" in sector_text or "holding" in sector_text) and _valid(m["pb"]) and m["pb"] < 0.5:
        flags.append({"severity": "info", "text": (
            f"Holding/investment company trading at {m['pb']}x book value. Such discounts often persist "
            "for years; they close only with a trigger (buyback, delisting, restructuring, special auction).")})
    return flags, strengths


# ----------------------------------------------------------------- future
def _fade_path(g0: float, g_end: float, years: int = 10) -> list[float]:
    return [g0 + (g_end - g0) * (t / (years - 1)) for t in range(years)]


def project(m: dict, median_pe: Num) -> dict:
    eps0, price, pe_now = m.get("eps_ttm"), m.get("price"), m.get("pe")
    out: dict = {"available": False, "assumptions": {}, "horizons": {}, "reverse_dcf": None}
    if not (_valid(eps0) and eps0 > 0 and _valid(price) and price > 0):
        out["reason"] = "Company is loss-making or price/EPS is missing, so earnings can't be projected."
        return out

    hist = wavg([(m.get("profit_cagr_10"), 0.3), (m.get("profit_cagr_5"), 0.5), (m.get("profit_cagr_3"), 0.2)])
    if not _valid(hist):
        hist = (m.get("sales_cagr_5") or 6) * 0.8
    # profits can't outgrow sales forever: cap at sales growth + 5
    sg = m.get("sales_cagr_5")
    if _valid(sg):
        hist = min(hist, max(sg, 0) + 5)
    base_g0 = max(min(hist, 25.0), 2.0)
    scen = {
        "bear": (max(base_g0 * 0.5, 0.0), 4.0),
        "base": (base_g0, 8.0),
        "bull": (min(base_g0 * 1.3 + 2, 30.0), 11.0),
    }

    if _valid(median_pe) and median_pe > 0:
        pe_base = max(min(median_pe, 45), 8)
        pe_src = "10-yr median P/E"
    else:
        pe_base = max(min((pe_now or 20) * 0.85, 40), 8)
        pe_src = "current P/E less 15%"
    pe_long = max(min(pe_base, 25), 12)          # where multiples tend to settle as growth slows
    pe_mult = {"bear": 0.75, "base": 1.0, "bull": 1.15}
    dy = (m.get("dividend_yield") or 0) / 100

    for name, (g0, gend) in scen.items():
        path = _fade_path(g0, gend)
        eps = eps0
        series = []
        for t, g in enumerate(path, start=1):
            eps *= (1 + g / 100)
            series.append(eps)
        for n in (3, 5, 10):
            pe_n = (pe_base + (pe_long - pe_base) * n / 10) * pe_mult[name]
            pe_n = min(pe_n, 60)
            eps_n = series[n - 1]
            px = eps_n * pe_n
            ret = ((px / price) ** (1 / n) - 1 + dy) * 100
            out["horizons"].setdefault(str(n), {})[name] = {
                "eps": r1(eps_n, 2), "pe": r1(pe_n), "price": r1(px, 0),
                "cagr": r1(ret), "multiple": r1(px / price, 2),
                "avg_growth": r1(sum(path[:n]) / n),
            }
        out["assumptions"][name] = {"start_growth": r1(g0), "end_growth": r1(gend)}

    out["assumptions"].update({
        "eps_start": r1(eps0, 2), "price_start": r1(price, 2), "pe_base": r1(pe_base), "pe_base_source": pe_src,
        "pe_long_run": r1(pe_long), "dividend_yield": r1(dy * 100, 2),
        "history_profit_growth": r1(hist),
    })

    # reverse DCF: growth needed for REQUIRED_RETURN with a fair exit P/E in 10 years
    rr, fair_pe = config.REQUIRED_RETURN, config.FAIR_EXIT_PE
    need = ((price * (1 + rr) ** 10) / (eps0 * fair_pe)) ** 0.1 - 1
    out["reverse_dcf"] = {
        "required_return": r1(rr * 100), "exit_pe": fair_pe, "implied_growth": r1(need * 100),
        "delivered_growth_5y": m.get("profit_cagr_5"), "delivered_growth_10y": m.get("profit_cagr_10"),
    }
    out["available"] = True
    return out


def horizon_views(proj: dict, scores: dict) -> dict:
    if not proj.get("available"):
        return {n: {"stance": "Not projectable", "tone": "neutral", "why": proj.get("reason", "")} for n in ("3", "5", "10")}
    views = {}
    levels = ["Unattractive", "Modest", "Reasonable", "Attractive"]
    tones = {"Unattractive": "bad", "Modest": "warn", "Reasonable": "ok", "Attractive": "good"}
    biz = scores.get("business") or 50
    for n in ("3", "5", "10"):
        base = proj["horizons"][n]["base"]["cagr"]
        bear = proj["horizons"][n]["bear"]["cagr"]
        lvl = 3 if base >= 15 else 2 if base >= 10 else 1 if base >= 5 else 0
        if n in ("5", "10") and biz < 50:
            lvl = max(lvl - 1, 0)
        if n == "10" and biz >= 75 and lvl < 2 and base >= 7:
            lvl += 1
        if bear < -5 and lvl > 0:
            lvl -= 1
        stance = levels[lvl]
        driver = {"3": "price you pay and the near-term cycle",
                  "5": "earnings growth plus any change in valuation",
                  "10": "business quality and how long growth lasts"}[n]
        views[n] = {
            "stance": stance, "tone": tones[stance],
            "why": f"Base case ≈ {base}%/yr (bear {bear}%, bull {proj['horizons'][n]['bull']['cagr']}%). Over {n} years returns depend mostly on the {driver}.",
        }
    return views


def verdict(scores: dict, flags: list[dict], m: dict) -> dict:
    biz, val = scores.get("business"), scores.get("valuation")
    high = sum(1 for f in flags if f["severity"] == "high")
    if _valid(m.get("eps_ttm")) and m["eps_ttm"] <= 0:
        label, tone = "Loss-making — speculative", "bad"
        line = "No current earnings. Any investment is a bet on a turnaround."
    elif biz is None:
        label, tone, line = "Not enough data", "neutral", "Too few numbers to judge."
    elif biz >= 70 and (val or 0) >= 50 and high == 0:
        label, tone = "High quality, fairly priced", "good"
        line = "Strong business at a price that still leaves room for returns — a long-term candidate for deeper research."
    elif biz >= 70 and high == 0:
        label, tone = "High quality, but expensive", "ok"
        line = "Great business; the current price already expects a lot. Better entry points may come."
    elif biz >= 55 and high <= 1:
        label, tone = "Average — keep on watch", "warn"
        line = "Mixed picture. Fine to track, but needs improvement or a cheaper price."
    else:
        label, tone = "Weak — avoid for now", "bad"
        line = "Fundamentals or red flags argue against holding this long-term right now."
    if high >= 2 and tone in ("good", "ok"):
        label, tone = "Good numbers, serious red flags", "warn"
        line = "Scores look fine, but red flags need checking before trusting them."
    return {"label": label, "tone": tone, "summary": line}


def narrative(c: dict, m: dict, scores: dict, proj: dict, median_pe: Num) -> list[str]:
    nm = c.get("name") or c.get("symbol")
    fin = m["is_financial"]
    out = []
    if _valid(m["profit_cagr_5"]) or _valid(m["sales_cagr_5"]):
        out.append(f"Over the last 5 years {nm} grew sales {m['sales_cagr_5'] if _valid(m['sales_cagr_5']) else '—'}% a year "
                   f"and profit {m['profit_cagr_5'] if _valid(m['profit_cagr_5']) else '—'}% a year.")
    rv = m["roe_avg_5"] if fin else m["roce_avg_5"]
    if _valid(rv):
        tag = "excellent" if rv >= 22 else "good" if rv >= 15 else "average" if rv >= 10 else "weak"
        out.append(f"It earns {'an ROE' if fin else 'a ROCE'} of about {rv}% — {tag} returns on the money it uses.")
    if not fin and _valid(m["debt_to_equity"]):
        de = m["debt_to_equity"]
        out.append("The balance sheet is " + ("almost debt-free." if de <= 0.1 else "lightly leveraged." if de <= 0.5 else f"carrying meaningful debt ({de}x equity)."))
    if _valid(m["pe"]):
        if _valid(median_pe):
            rel = "below" if m["pe"] < median_pe * 0.9 else "above" if m["pe"] > median_pe * 1.1 else "close to"
            out.append(f"At a P/E of {m['pe']} it trades {rel} its 10-year median P/E of {r1(median_pe)}.")
        else:
            out.append(f"It trades at a P/E of {m['pe']}.")
    rd = proj.get("reverse_dcf")
    if rd:
        dg = rd["delivered_growth_5y"]
        cmp_ = ""
        if _valid(dg):
            cmp_ = (" That is below what it delivered in the last 5 years (" if rd["implied_growth"] < dg else " That is more than it delivered in the last 5 years (") + f"{dg}%)."
        out.append(f"To earn {rd['required_return']}% a year for 10 years (exit P/E {int(rd['exit_pe'])}), profits must grow about "
                   f"{rd['implied_growth']}% a year.{cmp_}")
    return out


# ----------------------------------------------------------------- entry
def analyse(c: dict, median_pe: Num = None, peers: dict | None = None, pe_chart: dict | None = None) -> dict:
    from . import forensics, valuation  # local import: both modules reuse helpers from here

    m = compute_metrics(c)
    scores = compute_scores(m, median_pe)
    flags, strengths = compute_flags(m, c)
    fx = forensics.compute(c, m)
    flags += fx["flags"]
    alt, ben, pio = fx["altman"], fx["beneish"], fx["piotroski"]
    if alt.get("available") and alt["zone"] == "Distress":
        flags.append({"severity": "high", "text": f"Altman Z-score {alt['z']} is in the distress zone (bankruptcy-risk model)."})
    if ben.get("available") and ben["zone"] == "Possible manipulation":
        flags.append({"severity": "medium", "text": f"Beneish M-score {ben['m']} is above -1.78 — numbers look aggressive; read the annual report."})
    if pio.get("available") and pio.get("score_9") is not None:
        if pio["score_9"] >= 8:
            strengths.append(f"Piotroski F-score {pio['score_9']}/9 — fundamentals improving across the board.")
        elif pio["score_9"] <= 2:
            flags.append({"severity": "medium", "text": f"Piotroski F-score only {pio['score_9']}/9 — fundamentals weakening."})
    order = {"high": 0, "medium": 1, "info": 2}
    flags.sort(key=lambda f: order.get(f["severity"], 3))
    proj = project(m, median_pe)
    val = valuation.compute(c, m, pe_chart, peers, median_pe)
    return {
        "metrics": m,
        "median_pe": r1(median_pe),
        "scores": scores,
        "flags": flags,
        "strengths": strengths,
        "forensics": fx,
        "valuation": val,
        "projection": proj,
        "horizons": horizon_views(proj, scores),
        "verdict": verdict(scores, flags, m),
        "narrative": narrative(c, m, scores, proj, median_pe),
    }
