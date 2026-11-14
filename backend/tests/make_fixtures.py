"""Builds synthetic company pages in the same HTML structure as the live source,
so the parser and engine can be tested offline. Numbers are made up."""
from pathlib import Path

HERE = Path(__file__).parent / "fixtures"
HERE.mkdir(exist_ok=True)


def fmt(v):
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    if abs(v) >= 1000:
        return f"{v:,.0f}"
    return f"{v:.2f}".rstrip("0").rstrip(".") if abs(v) < 100 else f"{v:.0f}"


def table(cols, rows, cls="data-table"):
    h = "<table class='%s'><thead><tr><th class='text'></th>" % cls
    h += "".join(f"<th>{c}</th>" for c in cols) + "</tr></thead><tbody>"
    for label, vals in rows:
        btn = f"<button class='button-plain'>{label}&nbsp;<span class='blue-icon'>+</span></button>"
        h += f"<tr><td class='text'>{btn}</td>" + "".join(f"<td>{fmt(v)}</td>" for v in vals) + "</tr>"
    return h + "</tbody></table>"


def ranges(title, d):
    h = f"<table class='ranges-table'><tr><th colspan='2'>{title}</th></tr>"
    for k, v in d.items():
        h += f"<tr><td>{k}:</td><td>{v}</td></tr>"
    return h + "</table>"


def top(items):
    h = "<ul id='top-ratios'>"
    for name, val in items:
        if isinstance(val, tuple):
            inner = f"₹ <span class='number'>{val[0]}</span> / <span class='number'>{val[1]}</span>"
        else:
            inner = f"<span class='number'>{val}</span>"
        h += f"<li class='flex flex-space-between'><span class='name'>{name}</span><span class='nowrap value'>{inner}</span></li>"
    return h + "</ul>"


def manufacturer():
    years = [f"Mar {y}" for y in range(2014, 2026)]
    n = len(years)
    sales = [10000 * 1.12 ** i for i in range(n)]
    opm = [18 + (i % 3) for i in range(n)]
    op = [s * o / 100 for s, o in zip(sales, opm)]
    other = [150 + 10 * i for i in range(n)]
    interest = [120 - 5 * i for i in range(n)]
    dep = [300 + 25 * i for i in range(n)]
    pbt = [a + b - c - d for a, b, c, d in zip(op, other, interest, dep)]
    np_ = [p * 0.75 for p in pbt]
    shares = 100.0  # crore shares
    eps = [x / shares for x in np_]
    ttm = lambda arr, f=1.06: arr[-1] * f
    cols = years + ["TTM"]
    pl = [
        ("Sales", sales + [ttm(sales)]),
        ("Expenses", [s - o for s, o in zip(sales, op)] + [ttm(sales) - ttm(op)]),
        ("Operating Profit", op + [ttm(op)]),
        ("OPM %", [f"{o}%" for o in opm] + [f"{opm[-1]}%"]),
        ("Other Income", other + [other[-1]]),
        ("Interest", interest + [interest[-1]]),
        ("Depreciation", dep + [dep[-1]]),
        ("Profit before tax", pbt + [ttm(pbt)]),
        ("Tax %", ["25%"] * (n + 1)),
        ("Net Profit", np_ + [ttm(np_)]),
        ("EPS in Rs", eps + [ttm(eps)]),
        ("Dividend Payout %", ["30%"] * n + [""]),
    ]
    eqc = [100] * n
    res = [4000 * 1.13 ** i for i in range(n)]
    bor = [2400 - 150 * i for i in range(n)]
    tot = [a + b + c + 1500 for a, b, c in zip(eqc, res, bor)]
    bs_cols = years + ["Sep 2025"]
    bs = [
        ("Equity Capital", eqc + [100]), ("Reserves", res + [res[-1] * 1.05]),
        ("Borrowings", bor + [bor[-1]]), ("Other Liabilities", [1500] * (n + 1)),
        ("Total Liabilities", tot + [tot[-1] * 1.03]), ("Fixed Assets", [t * 0.5 for t in tot] + [tot[-1] * 0.5]),
        ("CWIP", [100] * (n + 1)), ("Investments", [t * 0.1 for t in tot] + [tot[-1] * 0.1]),
        ("Other Assets", [t * 0.4 - 100 for t in tot] + [tot[-1] * 0.4]), ("Total Assets", tot + [tot[-1] * 1.03]),
    ]
    cfo = [p * 1.05 for p in np_]
    cfi = [-p * 0.6 for p in np_]
    cff = [-p * 0.35 for p in np_]
    cf = [
        ("Cash from Operating Activity", cfo), ("Cash from Investing Activity", cfi),
        ("Cash from Financing Activity", cff), ("Net Cash Flow", [a + b + c for a, b, c in zip(cfo, cfi, cff)]),
    ]
    ratios = [
        ("Debtor Days", [45 + (i % 4) for i in range(n)]), ("Inventory Days", [60] * n),
        ("Days Payable", [50] * n), ("Cash Conversion Cycle", [55] * n), ("Working Capital Days", [40] * n),
        ("ROCE %", [f"{18 + (i % 4)}%" for i in range(n)]),
    ]
    qcols = ["Sep 2023", "Dec 2023", "Mar 2024", "Jun 2024", "Sep 2024", "Dec 2024", "Mar 2025", "Jun 2025", "Sep 2025"]
    q = [("Sales", [7500 + 150 * i for i in range(9)]), ("OPM %", ["20%"] * 9),
         ("Net Profit", [900 + 20 * i for i in range(9)]), ("EPS in Rs", [9 + 0.2 * i for i in range(9)]),
         ("Raw PDF", [""] * 9)]
    shp = [("Promoters", ["55.10%", "55.10%", "55.20%", "55.30%", "55.40%", "55.40%", "55.60%", "55.80%", "56.00%"]),
           ("FIIs", ["18.00%", "18.20%", "18.50%", "18.40%", "18.90%", "19.20%", "19.50%", "19.80%", "20.10%"]),
           ("DIIs", ["12.00%", "12.10%", "12.00%", "12.30%", "12.40%", "12.50%", "12.80%", "13.00%", "13.10%"]),
           ("Public", ["14.90%", "14.60%", "14.30%", "14.00%", "13.30%", "12.90%", "12.10%", "11.40%", "10.80%"]),
           ("No. of Shareholders", ["3,10,000"] * 9)]
    price = 1450
    html = f"""<html><body>
<div id="company-info" data-company-id="9999" data-warehouse-id="8888"></div>
<h1 class="margin-0">Test Industries Ltd</h1>
<div class="company-links"><a href="https://www.testindustries.example" target="_blank">testindustries</a>
<a href="https://www.bseindia.com/x" target="_blank"><span>BSE: 599999</span></a>
<a href="https://www.nseindia.com/x" target="_blank"><span>NSE: TESTCO</span></a></div>
<div class="company-profile"><div class="about"><p>Test Industries makes industrial pumps and valves for water and energy customers.</p></div></div>
{top([("Market Cap", "1,45,000"), ("Current Price", f"{price:,}"), ("High / Low", ("1,650", "1,120")),
      ("Stock P/E", f"{price/(eps[-1]*1.06):.1f}"), ("Book Value", f"{(res[-1]+100)/100:.0f}"),
      ("Dividend Yield", "0.80"), ("ROCE", "21.0"), ("ROE", "17.5"), ("Face Value", "1.00")])}
<div class="pros"><ul><li>Company has a good return on equity (ROE) track record.</li></ul></div>
<div class="cons"><ul><li>Stock is trading at 6 times its book value.</li></ul></div>
<section id="peers"><p class="sub"><a href="/market/IN07/" title="Broad Sector">Industrials</a>
<a href="/market/IN07/IN0701/" title="Sector">Capital Goods</a><a href="/market/IN07/IN0701/IN070101/" title="Industry">Industrial Products</a></p></section>
<section id="quarters">{table(qcols, q)}</section>
<section id="profit-loss">{table(cols, pl)}
{ranges("Compounded Sales Growth", {"10 Years": "12%", "5 Years": "12%", "3 Years": "12%", "TTM": "6%"})}
{ranges("Compounded Profit Growth", {"10 Years": "14%", "5 Years": "13%", "3 Years": "12%", "TTM": "6%"})}
{ranges("Stock Price CAGR", {"10 Years": "18%", "5 Years": "20%", "3 Years": "15%", "1 Year": "8%"})}
{ranges("Return on Equity", {"10 Years": "17%", "5 Years": "18%", "3 Years": "18%", "Last Year": "18%"})}
</section>
<section id="balance-sheet">{table(bs_cols, bs)}</section>
<section id="cash-flow">{table(years, cf)}</section>
<section id="ratios">{table(years, ratios)}</section>
<section id="documents"><div class="documents"><h3>Announcements</h3><ul class="list-links">
<li><a href="https://www.bseindia.com/a1" target="_blank">Board Meeting Outcome for Q2 results<div class="ink-600 smaller">12 Nov - Results approved</div></a></li>
<li><a href="https://www.bseindia.com/a2" target="_blank">Investor presentation<div class="ink-600 smaller">13 Nov</div></a></li></ul></div>
<div class="documents annual-reports"><h3>Annual reports</h3><ul class="list-links">
<li><a href="https://www.bseindia.com/ar25.pdf" target="_blank">Financial Year 2025<div class="ink-600 smaller">from bse</div></a></li>
<li><a href="https://www.bseindia.com/ar24.pdf" target="_blank">Financial Year 2024<div class="ink-600 smaller">from bse</div></a></li></ul></div>
<div class="documents concalls"><h3>Concalls</h3><ul class="list-links">
<li class="flex"><div class="ink-600">Nov 2025</div><a class="concall-link" href="https://example.com/t.pdf">Transcript</a><a class="concall-link" href="https://example.com/p.pdf">PPT</a></li>
<li class="flex"><div class="ink-600">Aug 2025</div><a class="concall-link" href="https://example.com/t2.pdf">Transcript</a></li></ul></div></section>
<section id="shareholding"><div id="quarterly-shp">{table(qcols, shp)}</div>
<div id="yearly-shp">{table(["Mar 2023","Mar 2024","Mar 2025"], [(r[0], r[1][-3:]) for r in shp])}</div></section>
</body></html>"""
    (HERE / "testco.html").write_text(html, encoding="utf-8")


def bank():
    years = [f"Mar {y}" for y in range(2016, 2026)]
    n = len(years)
    rev = [20000 * 1.15 ** i for i in range(n)]
    interest = [r * 0.5 for r in rev]
    exp = [r * 0.25 for r in rev]
    fp = [r - i - e for r, i, e in zip(rev, interest, exp)]
    other = [r * 0.15 for r in rev]
    dep = [r * 0.01 for r in rev]
    pbt = [a + b - c for a, b, c in zip(fp, other, dep)]
    np_ = [p * 0.75 for p in pbt]
    eps = [x / 500 for x in np_]
    cols = years + ["TTM"]
    pl = [("Revenue", rev + [rev[-1] * 1.07]), ("Interest", interest + [interest[-1] * 1.07]),
          ("Expenses", exp + [exp[-1]]), ("Financing Profit", fp + [fp[-1]]),
          ("Financing Margin %", ["25%"] * (n + 1)), ("Other Income", other + [other[-1]]),
          ("Depreciation", dep + [dep[-1]]), ("Profit before tax", pbt + [pbt[-1] * 1.07]),
          ("Tax %", ["25%"] * (n + 1)), ("Net Profit", np_ + [np_[-1] * 1.07]), ("EPS in Rs", eps + [eps[-1] * 1.07])]
    eqc = [500] * n
    res = [30000 * 1.15 ** i for i in range(n)]
    dep_ = [r * 6 for r in res]
    bor = [r * 1.2 for r in res]
    tot = [a + b + c + d + 5000 for a, b, c, d in zip(eqc, res, dep_, bor)]
    bs = [("Equity Capital", eqc), ("Reserves", res), ("Deposits", dep_), ("Borrowing", bor),
          ("Other Liabilities", [5000] * n), ("Total Liabilities", tot), ("Total Assets", tot)]
    shp = [("Promoters", ["0.00%"] * 9), ("FIIs", ["48%", "48%", "47%", "47%", "46%", "47%", "47%", "48%", "48%"]),
           ("DIIs", ["30%", "31%", "31%", "32%", "33%", "33%", "34%", "34%", "35%"]), ("Public", ["22%"] * 9)]
    qcols = ["Sep 2023", "Dec 2023", "Mar 2024", "Jun 2024", "Sep 2024", "Dec 2024", "Mar 2025", "Jun 2025", "Sep 2025"]
    html = f"""<html><body><div id="company-info" data-company-id="7777" data-warehouse-id="6666"></div>
<h1>Test Bank Ltd</h1>
{top([("Market Cap", "3,00,000"), ("Current Price", "1,200"), ("High / Low", ("1,300", "950")),
      ("Stock P/E", "18.0"), ("Book Value", "400"), ("Dividend Yield", "1.1"), ("ROCE", "7.5"), ("ROE", "16.0")])}
<section id="peers"><p class="sub"><a href="/market/IN05/">Financial Services</a><a href="/market/IN05/IN0501/">Banks</a></p></section>
<section id="profit-loss">{table(cols, pl)}</section>
<section id="balance-sheet">{table(years, bs)}</section>
<section id="cash-flow">{table(years, [("Cash from Operating Activity", [-x for x in np_]), ("Cash from Investing Activity", [-100]*n)])}</section>
<section id="ratios">{table(years, [("ROE %", [f"{15 + i % 3}%" for i in range(n)])])}</section>
<section id="shareholding"><div id="quarterly-shp">{table(qcols, shp)}</div></section>
</body></html>"""
    (HERE / "testbank.html").write_text(html, encoding="utf-8")


PEERS = """<table class="data-table"><tr><th>S.No.</th><th>Name</th><th>CMP Rs.</th><th>P/E</th><th>Mar Cap Rs.Cr.</th>
<th>Div Yld %</th><th>NP Qtr Rs.Cr.</th><th>Qtr Profit Var %</th><th>Sales Qtr Rs.Cr.</th><th>Qtr Sales Var %</th><th>ROCE %</th></tr>
<tr><td>1.</td><td><a href="/company/TESTCO/consolidated/">Test Industries</a></td><td>1450</td><td>38.5</td><td>145000</td><td>0.8</td><td>1060</td><td>12</td><td>8700</td><td>10</td><td>21</td></tr>
<tr><td>2.</td><td><a href="/company/PEERONE/">Peer One</a></td><td>800</td><td>30.1</td><td>60000</td><td>1.0</td><td>500</td><td>8</td><td>4000</td><td>9</td><td>18</td></tr>
<tr><td>3.</td><td><a href="/company/PEERTWO/consolidated/">Peer Two</a></td><td>2200</td><td>55.0</td><td>90000</td><td>0.4</td><td>420</td><td>25</td><td>3100</td><td>20</td><td>25</td></tr>
<tfoot><tr><td></td><td>Median: 3 Co.</td><td>1450</td><td>38.5</td><td>90000</td><td>0.8</td><td>500</td><td>12</td><td>4000</td><td>10</td><td>21</td></tr></tfoot></table>"""

if __name__ == "__main__":
    manufacturer()
    bank()
    (HERE / "peers.html").write_text(PEERS, encoding="utf-8")
    print("fixtures written to", HERE)
