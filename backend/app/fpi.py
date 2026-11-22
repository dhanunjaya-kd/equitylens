"""Longer institutional-flow history from the official depository and regulator pages.

1. NSDL daily FPI investments (custodian-confirmed, final figures)
   fpi.nsdl.co.in/web/Reports/Monthly.aspx   current month, every reporting date so far
   fpi.nsdl.co.in/web/Reports/Archive.aspx   any past month (ASP.NET form post, hdnDate=DD-Mon-YYYY)
   Rows per reporting date: asset class (Equity, Debt..., Mutual Funds, AIFs) x route (Stock Exchange,
   Primary market & others, Sub-total): gross purchases, gross sales, net (Rs crore; negatives in brackets).
   A reporting date carries the trades of the previous trading day(s).
2. Fortnightly sector-wise FPI data (NSDL, mirrored by CDSL), published for the 15th and the month end:
   per sector, equity assets under custody (AUC) and net investment for the last two fortnights.
3. SEBI: trends in transactions on stock exchanges by mutual funds (the largest part of DII), daily rows of
   the month SEBI has published so far (it runs about two weeks behind), plus yearly totals since 2000.

Nothing here is estimated. Every row is checked as it is read (purchases - sales = net, sectors add up to
the Grand Total); a page that fails the check is not used and the page says the source is not available.
"""
from __future__ import annotations

import math
import random
import re
import threading
import time
from datetime import date, datetime, timedelta
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from . import config, store

NSDL = "https://www.fpi.nsdl.co.in"
NSDL_MONTH = NSDL + "/web/Reports/Monthly.aspx"
NSDL_ARCHIVE = NSDL + "/web/Reports/Archive.aspx"
SECT_NSDL = NSDL + "/web/StaticReports/Fortnightly_Sector_wise_FII_Investment_Data/FIIInvestSector_{mon}{dd}{yyyy}.html"
SECT_CDSL = "https://www.cdslindia.com/publications/FII/FortnightlySecWisePages/{month} {dd},{yyyy}.html"
SEBI_MF = "https://www.sebi.gov.in/sebiweb/other/OtherAction.do?doMfd=yes&type=2"
SEBI_MF_SEARCH = "https://www.sebi.gov.in/sebiweb/other/OtherAction.do?doMfdTrendsSearch=yes"
BROWSER = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36",
           "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8", "Accept-Language": "en-IN,en;q=0.9"}
HIST_MONTHS = 60          # 5 years of NSDL daily figures
HIST_FORTNIGHTS = 120     # 5 years of sector reports
TOL = 0.06                # Rs crore: purchases - sales may differ from net by rounding only
STATE = {"nsdl": {"running": False, "done": 0, "total": 0, "ok": None},
         "sectors": {"running": False, "done": 0, "total": 0, "ok": None},
         "mf": {"running": False, "done": 0, "total": 0, "ok": None, "archive": None},
         "errors": {}}
_lock = threading.Lock()
_last = {"daily": 0.0}


# ================================================================ helpers
def num(s) -> Optional[float]:
    """'5,09,003' -> 509003, '(2999.02)' -> -2999.02, '-1,159' -> -1159, '' / '-' -> None."""
    if s is None:
        return None
    t = str(s).strip().replace(",", "").replace("−", "-").replace(" ", "")
    if t in ("", "-", "--", "NA", "N.A."):
        return None
    neg = t.startswith("(") and t.endswith(")")
    t = t.strip("()")
    try:
        v = float(t)
    except ValueError:
        return None
    return -v if neg else v


def _cells(tr) -> list[str]:
    return [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"], recursive=False)]


def _rows(html: str) -> list[list[str]]:
    soup = BeautifulSoup(html or "", "html.parser")
    out = []
    for tr in soup.find_all("tr"):
        if tr.find("table"):                     # a layout row wrapping a whole table: its cells are not data
            continue
        c = _cells(tr)
        if c:
            out.append(c)
    return out


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update(BROWSER)
    return s


def _get(sess: requests.Session, url: str, **kw) -> Optional[str]:
    r = sess.get(url, timeout=config.REQUEST_TIMEOUT, **kw)
    return r.text if r.status_code == 200 and r.text else None


def _err(key: str, msg: Optional[str]) -> None:
    if msg:
        STATE["errors"][key] = msg
    else:
        STATE["errors"].pop(key, None)


# ================================================================ 1. NSDL daily FPI investments
DATE_RE = re.compile(r"^(\d{1,2})-([A-Za-z]{3})-(\d{4})$")
ASSETS = {"equity": "equity", "debt": "debt", "debt-general limit": "debt", "debt-vrr": "debt_vrr", "debt-far": "debt_far",
          "hybrid": "hybrid", "mutual funds": "mf", "aifs": "aif", "alternative investment funds (aifs)": "aif", "total": "total"}
ROUTES = {"stock exchange": "exch", "primary market & others": "primary", "primary market and others": "primary", "sub-total": "sub", "subtotal": "sub"}
PRODUCTS = {"index futures": "idx_fut", "index options": "idx_opt", "stock futures": "stk_fut", "stock options": "stk_opt"}
MONTH_TOL = 1.0           # Rs crore: the days of a month against the source's own month total
NUM_RE = re.compile(r"\(?-?[\d,]+(\.\d+)?\)?")


def _iso(s: str) -> Optional[str]:
    m = DATE_RE.match(s.strip())
    if not m:
        return None
    try:
        return datetime.strptime(f"{int(m.group(1)):02d}-{m.group(2).title()}-{m.group(3)}", "%d-%b-%Y").date().isoformat()
    except ValueError:
        return None


def _split(cells: list[str]) -> tuple[list[str], list[float]]:
    labels, nums = [], []
    for c in cells:
        if c.startswith("Rs.") or c.startswith("Rs "):          # the day's USD conversion rate
            continue
        v = num(c)
        if v is not None and NUM_RE.fullmatch(c.replace(" ", "")):
            nums.append(v)
        elif c:
            labels.append(c.strip().lower())
    return labels, nums


def parse_nsdl_daily(html: str) -> dict:
    """NSDL's Monthly / Archive page ->
    {"days": {iso: {"exch"|"primary"|"sub": {buy, sell, net}}},            equity, Rs crore, by reporting date
     "deriv": {iso: {"idx_fut"|"idx_opt"|"stk_fut"|"stk_opt": {buy_n, buy, sell_n, sell, oi_n, oi}}},
     "totals": {"November": {"exch": net, ...}}, "bad": rows failing bought - sold = net}.
    A "Total for <month>" / "Total for <year>" block is never read as a day: its figures go to totals."""
    out = {"days": {}, "deriv": {}, "totals": {}, "bad": 0}
    section, cur, asset = "inv", None, None
    for cells in _rows(html):
        joined = " ".join(cells)
        if "Daily Trends in FPI Investments" in joined:
            section, cur, asset = "inv", None, None
            continue
        if "Derivative Trades" in joined:
            section, cur, asset = "der", None, None
            continue
        if "Derivative Products" in joined:
            continue
        rest = []
        for c in cells:
            d = _iso(c)
            if d:
                cur, asset = d, None
            elif c.startswith("Total for "):
                cur, asset = ("T", c[10:].strip()), None
            else:
                rest.append(c)
        labels, nums = _split(rest)
        if section == "inv":
            for lb in labels:
                if lb in ASSETS:
                    asset = ASSETS[lb]
            route = next((ROUTES[lb] for lb in labels if lb in ROUTES), None)
            if cur is None or asset != "equity" or not route or len(nums) < 3:
                continue
            buy, sell, net = nums[:3]
            if abs(buy - sell - net) > TOL:
                out["bad"] += 1
                continue
            if isinstance(cur, tuple):
                out["totals"].setdefault(cur[1], {})[route] = net
            else:
                out["days"].setdefault(cur, {})[route] = {"buy": buy, "sell": sell, "net": net}
        else:
            prod = next((PRODUCTS[lb] for lb in labels if lb in PRODUCTS), None)
            if prod and isinstance(cur, str) and len(nums) >= 6:
                b_n, b, s_n, s_, oi_n, oi = nums[:6]
                out["deriv"].setdefault(cur, {})[prod] = {"buy_n": b_n, "buy": b, "sell_n": s_n, "sell": s_, "oi_n": oi_n, "oi": oi}
    out["days"] = {d: v for d, v in out["days"].items() if "exch" in v}
    return out


def month_checks(parsed: dict) -> dict:
    """{"YYYY-MM": True/False}: do the month's days add up to NSDL's own "Total for <month>" (equity, exchanges)?"""
    res = {}
    by: dict = {}
    for d, v in parsed["days"].items():
        by.setdefault(d[:7], []).append(v["exch"]["net"])
    for label, routes in parsed["totals"].items():
        if label.isdigit() or "exch" not in routes:
            continue                                            # the year's total: the page holds one month
        for ym, nets in by.items():
            if MONTHS[int(ym[5:]) - 1].lower().startswith(label.lower()[:3]):
                res[ym] = abs(sum(nets) - routes["exch"]) <= MONTH_TOL
    return res


def _month_key(y: int, m: int) -> str:
    return f"NSDL2::{y:04d}-{m:02d}"                             # v2: v1 could hold a month total as a day


def _save_month(ym: str, days: dict, deriv: dict, final: bool, checked: Optional[bool]) -> None:
    y, m = int(ym[:4]), int(ym[5:])
    store.put_company(_month_key(y, m), {"days": days, "deriv": deriv, "final": final, "checked": checked})


def _save_parsed(parsed: dict, final_ym: Optional[str] = None) -> int:
    checks = month_checks(parsed)
    by: dict = {}
    for d in list(parsed["days"]) + list(parsed["deriv"]):
        by.setdefault(d[:7], set()).add(d)
    for ym, ds in by.items():
        days = {d: parsed["days"][d] for d in sorted(ds) if d in parsed["days"]}
        if not days:
            continue
        _save_month(ym, days, {d: parsed["deriv"][d] for d in sorted(ds) if d in parsed["deriv"]},
                    final=(ym == final_ym and checks.get(ym) is not False), checked=checks.get(ym))
    return len(parsed["days"])


def hidden_fields(html: str, names=None) -> dict:
    soup = BeautifulSoup(html or "", "html.parser")
    out = {}
    for i in soup.find_all("input"):
        n = i.get("name")
        if n and (i.get("type") or "").lower() == "hidden" and (names is None or n in names):
            out[n] = i.get("value", "")
    return out


class Web:
    """NSDL / SEBI: one browser identity, 2-4 s between calls (NSDL drops a bare or hurried client)."""

    def __init__(self):
        self.s, self.calls = _session(), 0

    def fetch(self, method: str, url: str, **kw) -> Optional[str]:
        if self.calls:
            time.sleep(random.uniform(2.0, 4.0))
        self.calls += 1
        r = self.s.request(method, url, timeout=60, **kw)
        if r.status_code in (401, 403, 429, 530):
            raise PermissionError(f"HTTP {r.status_code}")
        return r.text if r.status_code == 200 else None


def fetch_nsdl_current() -> Optional[int]:
    """The current month so far (plain page)."""
    if config.DEMO:
        return None
    try:
        html = _get(_session(), NSDL_MONTH)
    except requests.RequestException as e:
        _err("nsdl", f"NSDL: {e.__class__.__name__}")
        return None
    parsed = parse_nsdl_daily(html or "")
    if not parsed["days"]:
        _err("nsdl", "NSDL's daily page could not be read" + (f" ({parsed['bad']} rows failed the bought - sold = net check)" if parsed["bad"] else ""))
        return None
    _err("nsdl", None)
    return _save_parsed(parsed)


def fetch_nsdl_month(y: int, m: int, web: Web) -> Optional[int]:
    """A past month from NSDL's archive (ASP.NET form: the page's own hidden fields + the date, as its button does)."""
    to = date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)
    page = web.fetch("GET", NSDL_ARCHIVE)
    if not page:
        return None
    form = hidden_fields(page)
    ds = to.strftime("%d-%b-%Y")
    form.update({"__EVENTTARGET": "btnSubmit1", "__EVENTARGUMENT": "", "hdnFlag": "", "HdnValexceldata": "", "hdnDate": ds, "txtDate": ds})
    html = web.fetch("POST", NSDL_ARCHIVE, data=form, headers={"Referer": NSDL_ARCHIVE, "Origin": NSDL})
    parsed = parse_nsdl_daily(html or "")
    ym = f"{y:04d}-{m:02d}"
    parsed["days"] = {d: v for d, v in parsed["days"].items() if d[:7] == ym}
    parsed["deriv"] = {d: v for d, v in parsed["deriv"].items() if d[:7] == ym}
    if not parsed["days"]:
        return None
    return _save_parsed(parsed, final_ym=ym)


def _months() -> list[dict]:
    out = []
    for k in sorted(store.keys_like("NSDL2::%")):
        hit = store.get_company(k)
        if hit:
            out.append(dict(hit[1], ym=k.split("::")[1]))
    return out


def nsdl_days() -> dict:
    out: dict = {}
    for m in _months():
        out.update(m["days"])
    return dict(sorted(out.items()))


def nsdl_deriv() -> dict:
    out: dict = {}
    for m in _months():
        out.update(m.get("deriv") or {})
    return dict(sorted(out.items()))


def _months_back(n: int) -> list[tuple[int, int]]:
    t = date.today()
    y, m = t.year, t.month
    out = []
    for _ in range(n):
        m -= 1
        if m == 0:
            y, m = y - 1, 12
        out.append((y, m))
    return out


def backfill_nsdl() -> None:
    st = STATE["nsdl"]
    todo = [(y, m) for y, m in _months_back(HIST_MONTHS)
            if not ((store.get_company(_month_key(y, m)) or (0, {}))[1].get("final"))]
    st.update(running=bool(todo), done=0, total=len(todo))
    web, misses = Web(), 0
    for k, (y, m) in enumerate(todo, 1):
        try:
            n = fetch_nsdl_month(y, m, web)
        except PermissionError as e:
            _err("nsdl_archive", f"NSDL's archive refused the request ({e}); trying again later")
            break
        except requests.RequestException as e:
            n = None
            _err("nsdl_archive", f"NSDL archive: {e.__class__.__name__}")
        if n:
            misses, st["ok"] = 0, True
            _err("nsdl_archive", None)
        else:
            misses += 1
            if misses >= 3:
                st["ok"] = False if not st["ok"] else st["ok"]
                _err("nsdl_archive", "NSDL's archive did not return past months; trying again later")
                break
        st["done"] = k
    st["running"] = False


# ================================================================ 2. fortnightly sector-wise FPI data
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
P_AUC = re.compile(r"AUC as on\s+([A-Z][a-z]+)\s+(\d{1,2}),\s*(\d{4})")
P_NET = re.compile(r"Net Investment\s+([A-Z][a-z]+)\s+(\d{1,2})\s*-\s*(\d{1,2}),\s*(\d{4})")
SECT_LIST = NSDL + "/web/Reports/FPI_Fortnightly_Selection.aspx"


def _d(mon: str, dd: str, yyyy: str) -> Optional[str]:
    try:
        return date(int(yyyy), [x[:3].lower() for x in MONTHS].index(mon[:3].lower()) + 1, int(dd)).isoformat()
    except (ValueError, IndexError):
        return None


def parse_sectors(html: str) -> dict:
    """-> {"end", "start", "net_period", "prev_period", "sectors": [{name, auc_start, net_prev, net, auc}], "total"}
    with equity figures in Rs crore, or {} if the page does not check out."""
    text = BeautifulSoup(html or "", "html.parser").get_text(" ", strip=True)
    aucs = [_d(*m) for m in P_AUC.findall(text)]
    nets = [(_d(m[0], m[1], m[3]), _d(m[0], m[2], m[3])) for m in P_NET.findall(text)]
    if len(aucs) < 2 or len(nets) < 2 or not all(aucs[:2]) or not all(x for n in nets[:2] for x in n):
        return {}
    if aucs[1] != nets[1][1]:
        return {}                                                # the AUC date must be the fortnight's end
    rows, total = [], None
    for cells in _rows(html):
        if len(cells) < 10:
            continue
        name_i = next((i for i, c in enumerate(cells[:3]) if re.search(r"[A-Za-z]", c)), None)
        if name_i is None:
            continue
        name = cells[name_i].strip()
        vals = [num(c) for c in cells[name_i + 1:]]
        if len(vals) < 8 or len(vals) % 8 or any(v is None and c.strip() not in ("", "-") for v, c in zip(vals, cells[name_i + 1:])):
            continue
        vals = [v or 0.0 for v in vals]
        k = len(vals) // 8                                       # columns per block: 4 periods x (INR, USD)
        rec = {"name": name, "auc_start": vals[0], "net_prev": vals[2 * k], "net": vals[4 * k], "auc": vals[6 * k]}
        if name.lower().startswith("grand total") or name.lower() == "total":
            total = rec
        elif name_i > 0 and re.fullmatch(r"\d{1,2}", cells[0].strip()):
            rows.append(rec)
    if not rows or not total:
        return {}
    for key in ("net", "auc"):                                   # the sectors must add up to the Grand Total
        s = sum(r[key] for r in rows)
        if abs(s - total[key]) > max(3.0 * len(rows), 0.002 * abs(total[key])):
            return {}
    return {"start": aucs[0], "end": aucs[1], "prev_period": list(nets[0]), "net_period": list(nets[1]),
            "sectors": rows, "total": total}


def sector_options(html: str) -> list[tuple[str, str]]:
    """NSDL's list page -> [(iso fortnight end, path)] newest first. The date is read from the file name
    (labels are irregular), e.g. FIIInvestSector_Nov152026.html, FIIInvestSector_June302016.html."""
    out = []
    for path, label in re.findall(r'<option[^>]*value="([^"]+)"[^>]*>([^<]*)', html or ""):
        f = re.search(r"FIIInvestSe?c?t?o?r_([A-Za-z]+?)(\d{1,2})(\d{4})\.html", path)
        d = _d(f.group(1), f.group(2), f.group(3)) if f else None
        if not d:
            m = re.match(r"\s*([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})", label)
            d = _d(*m.groups()) if m else None
        if d and "StaticReports" in path:
            out.append((d, path.replace("~/", "/web/", 1)))
    return out


def _sect_key(iso: str) -> str:
    return f"FPISECT2::{iso}"                                    # v2: v1 guessed file names and missed many


def fetch_sector_report(iso: str, path: Optional[str], web: Optional[Web] = None) -> dict:
    key = _sect_key(iso)
    hit = store.get_company(key)
    if hit:
        return hit[1]["r"]
    if config.DEMO:
        r = _demo_sectors(date.fromisoformat(iso))
        store.put_company(key, {"r": r})
        return r
    web = web or Web()
    d = date.fromisoformat(iso)
    urls = ([NSDL + path] if path else []) + [SECT_CDSL.format(month=MONTHS[d.month - 1], dd=d.day, yyyy=d.year)]
    r: dict = {}
    for url in urls:
        try:
            html = web.fetch("GET", url)
        except (requests.RequestException, PermissionError):
            html = None
        r = parse_sectors(html or "")
        if r and r["end"] == iso:
            r["source"] = url
            break
        r = {}
    if r or d < date.today() - timedelta(days=45):               # a missing old report stays missing
        store.put_company(key, {"r": r})
    return r


def backfill_sectors() -> None:
    st = STATE["sectors"]
    web = Web()
    try:
        opts = sector_options(web.fetch("GET", SECT_LIST) or "")
    except (requests.RequestException, PermissionError):
        opts = []
    if not opts:                                                  # list not available: the usual dates, CDSL's copy
        opts = [(x.isoformat(), None) for x in _fortnights(HIST_FORTNIGHTS)]
    todo = [(d, p) for d, p in opts[:HIST_FORTNIGHTS] if store.get_company(_sect_key(d)) is None]
    st.update(running=bool(todo), done=0, total=len(todo))
    misses = 0
    for k, (d, p) in enumerate(todo, 1):
        r = fetch_sector_report(d, p, web)
        if r:
            misses, st["ok"] = 0, True
            _err("sectors", None)
        else:
            misses += 1
            if misses >= 5 and not st["ok"]:
                st["ok"] = False
                _err("sectors", "NSDL / CDSL sector reports could not be read")
                break
        st["done"] = k
    st["running"] = False


def _fortnights(n: int) -> list[date]:
    out, t = [], date.today() - timedelta(days=7)
    y, m = t.year, t.month
    while len(out) < n:
        end = date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)
        for d in (end, date(y, m, 15)):
            if d <= t and len(out) < n:
                out.append(d)
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return out


def sector_reports() -> list[dict]:
    out = []
    for k in store.keys_like("FPISECT2::%"):
        hit = store.get_company(k)
        if hit and hit[1]["r"]:
            out.append(hit[1]["r"])
    by = {r["end"]: r for r in out}
    return [by[d] for d in sorted(by)]


# ================================================================ 3. SEBI: mutual funds on the stock exchanges
SEBI_DATE_FMTS = ("%d %b, %Y", "%d %b %Y", "%d-%b-%Y", "%d/%m/%Y", "%d-%m-%Y")
PERIOD_RE = re.compile(r"^[A-Z][a-z]+\.?\s+\d{4}\s*-\s*[A-Z][a-z]+\.?\s+\d{4}$")


def _sebi_date(s: str) -> Optional[str]:
    s = re.sub(r"\s+", " ", s.strip())
    for f in SEBI_DATE_FMTS:
        try:
            return datetime.strptime(s, f).date().isoformat()
        except ValueError:
            continue
    return None


def parse_sebi_mf(html: str) -> dict:
    """-> {"days": {iso: {buy, sell, net}} equity, "total": equity net of SEBI's Total row or None,
    "periods": [{period, buy, sell, net}], "bad": n}. The Total row and the derivative table are never read as a day."""
    out = {"days": {}, "total": None, "periods": [], "bad": 0}
    cur = None
    for cells in _rows(html):
        joined = " ".join(cells)
        if "Derivative Products" in joined or "Derivative Trades" in joined:
            cur = "SKIP"
            continue
        if cur == "SKIP" and not any(_sebi_date(c) or PERIOD_RE.match(re.sub(r"\s+", " ", c.strip())) for c in cells):
            continue
        rest = []
        for c in cells:
            cc = re.sub(r"\s+", " ", c.strip())
            d = _sebi_date(cc)
            if d:
                cur = d
            elif cc == "Total":
                cur = "TOTAL"
            elif PERIOD_RE.match(cc):
                cur = ("P", cc)
            else:
                rest.append(c)
        labels, nums = _split(rest)
        if cur in (None, "SKIP") or "equity" not in labels or len(nums) < 3 or any(p in labels for p in PRODUCTS):
            continue
        buy, sell, net = nums[:3]
        if abs(buy - sell - net) > TOL:
            out["bad"] += 1
            continue
        rec = {"buy": buy, "sell": sell, "net": net}
        if cur == "TOTAL":
            out["total"] = net
        elif isinstance(cur, tuple):
            out["periods"].append(dict(rec, period=cur[1]))
        else:
            out["days"][cur] = rec
    return out


def _mf_key(ym: str) -> str:
    return f"SEBIMF2::{ym}"                                      # v2: v1 could hold SEBI's Total row as a day


def _save_mf(parsed: dict) -> int:
    by: dict = {}
    for d, v in parsed["days"].items():
        by.setdefault(d[:7], {})[d] = v
    for ym, days in by.items():
        checked = None
        if parsed["total"] is not None and len(by) == 1:          # the page holds one month: check it against SEBI's total
            checked = abs(sum(v["net"] for v in days.values()) - parsed["total"]) <= MONTH_TOL
        store.put_company(_mf_key(ym), {"days": dict(sorted(days.items())), "checked": checked})
    return len(parsed["days"])


def mf_days() -> dict:
    out: dict = {}
    for k in sorted(store.keys_like("SEBIMF2::%")):
        hit = store.get_company(k)
        if hit:
            out.update(hit[1]["days"])
    return dict(sorted(out.items()))


def fetch_mf_current() -> Optional[int]:
    if config.DEMO:
        return None
    try:
        html = _get(_session(), SEBI_MF)
    except requests.RequestException as e:
        _err("mf", f"SEBI: {e.__class__.__name__}")
        return None
    parsed = parse_sebi_mf(html or "")
    if not parsed["days"] and not parsed["periods"]:
        _err("mf", "SEBI's mutual fund page could not be read")
        return None
    _err("mf", None)
    if parsed["periods"]:
        store.put_company("SEBIMF::PERIODS", {"rows": parsed["periods"]})
    return _save_mf(parsed)


def fetch_mf_month(y: int, m: int, web: Web) -> Optional[int]:
    """SEBI's own search for a past month: the page's currdate and token, then the month's last day."""
    to = date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)
    page = web.fetch("GET", SEBI_MF_SEARCH)
    if not page:
        return None
    form = hidden_fields(page, names=("currdate", "org.apache.struts.taglib.html.TOKEN"))
    form["date"] = to.strftime("%d-%m-%Y")
    html = web.fetch("POST", SEBI_MF_SEARCH, data=form, headers={"Referer": SEBI_MF_SEARCH, "Origin": "https://www.sebi.gov.in"})
    parsed = parse_sebi_mf(html or "")
    ym = f"{y:04d}-{m:02d}"
    parsed["days"] = {d: v for d, v in parsed["days"].items() if d[:7] == ym}
    if not parsed["days"]:
        return None
    return _save_mf(parsed)


def backfill_mf() -> None:
    st = STATE["mf"]
    todo = [(y, m) for y, m in _months_back(HIST_MONTHS) if store.get_company(_mf_key(f"{y:04d}-{m:02d}")) is None
            and not store.get_company(f"SEBIMF2::TRIED::{y:04d}-{m:02d}")]
    st.update(running=bool(todo), done=0, total=len(todo))
    web, misses = Web(), 0
    for k, (y, m) in enumerate(todo, 1):
        try:
            n = fetch_mf_month(y, m, web)
        except PermissionError:
            st["archive"] = False if not st["archive"] else st["archive"]
            break
        except requests.RequestException:
            n = None
        if n:
            misses, st["archive"] = 0, True
        else:
            misses += 1
            if misses >= 3 and not st["archive"]:
                st["archive"] = False
                break
            store.put_company(f"SEBIMF2::TRIED::{y:04d}-{m:02d}", {"n": 0})
        st["done"] = k
    st["running"] = False


# ================================================================ refresh + background
def refresh_daily(force: bool = False) -> None:
    """NSDL current month + SEBI page: at most every 3 hours."""
    with _lock:
        if not force and time.time() - _last["daily"] < 3 * 3600:
            return
        _last["daily"] = time.time()
    fetch_nsdl_current()
    fetch_mf_current()


def backfill_all() -> None:
    for f in (backfill_nsdl, backfill_sectors, backfill_mf):
        try:
            f()
        except Exception as e:  # noqa: BLE001 - one source failing must not stop the others
            _err(f.__name__, str(e)[:200])


# ================================================================ payload
def _monthly(days: dict, key: Optional[str]) -> list[dict]:
    by: dict = {}
    for d, v in days.items():
        x = v.get(key) if key else v
        if x is None:
            continue
        b = by.setdefault(d[:7], {"month": d[:7], "net": 0.0, "days": 0})
        b["net"] += x["net"]
        b["days"] += 1
    return [dict(b, net=round(b["net"], 2)) for b in (by[k] for k in sorted(by))]


def _streaks(vals: list[tuple[str, float]]) -> dict:
    """Current run of same-sign days, and the longest buying / selling runs."""
    cur, best = None, {"buy": None, "sell": None}
    run = None
    for d, v in vals:
        if not v:
            run = None
            continue
        side = "buy" if v > 0 else "sell"
        if run and run["side"] == side:
            run.update(n=run["n"] + 1, to=d, sum=run["sum"] + v)
        else:
            run = {"side": side, "n": 1, "from": d, "to": d, "sum": v}
        if not best[side] or run["n"] > best[side]["n"]:
            best[side] = dict(run)
        cur = run
    r = lambda x: dict(x, sum=round(x["sum"], 2)) if x else None
    return {"current": r(cur), "longest_buy": r(best["buy"]), "longest_sell": r(best["sell"])}


def records(rows: list[dict]) -> dict:
    if not rows:
        return {}
    last = rows[-1]["date"]
    y1 = (date.fromisoformat(last) - timedelta(days=365)).isoformat()
    yr = [r for r in rows if r["date"] > y1]
    big = lambda xs, f: (lambda r: {"date": r["date"], "net": r["net"]})(f(xs, key=lambda r: r["net"]))
    s = lambda xs: round(sum(r["net"] for r in xs), 2)
    return {"all": {"buy": big(rows, max), "sell": big(rows, min), "from": rows[0]["date"]},
            "year": {"buy": big(yr, max), "sell": big(yr, min)},
            "streaks": _streaks([(r["date"], r["net"]) for r in yr]),
            "sum5": s(rows[-5:]), "sum20": s(rows[-20:]), "n5": len(rows[-5:]), "n20": len(rows[-20:])}


def payload() -> dict:
    nd = nsdl_days()
    dv = nsdl_deriv()
    rows = [{"date": d, "net": v["exch"]["net"], "buy": v["exch"]["buy"], "sell": v["exch"]["sell"],
             "primary": (v.get("primary") or {}).get("net"), "equity": (v.get("sub") or {}).get("net")} for d, v in nd.items()]
    mons = {m["ym"]: m for m in _months()}
    m_exch = {b["month"]: b for b in _monthly(nd, "exch")}
    m_sub = {b["month"]: b for b in _monthly(nd, "sub")}
    months = [{"month": k, "exch": m_exch[k]["net"], "equity": m_sub[k]["net"] if k in m_sub else None, "days": m_exch[k]["days"],
               "checked": (mons.get(k) or {}).get("checked")} for k in sorted(m_exch)]
    years: dict = {}
    for m in months:
        y = years.setdefault(m["month"][:4], {"year": m["month"][:4], "exch": 0.0, "equity": 0.0, "months": 0})
        y["exch"] += m["exch"]
        y["equity"] += m["equity"] or 0
        y["months"] += 1
    deriv_rows = []
    for d, v in dv.items():
        f = v.get("idx_fut") or {}
        o = v.get("idx_opt") or {}
        sf = v.get("stk_fut") or {}
        deriv_rows.append({"date": d,
                           "idx_fut_net": round(f["buy"] - f["sell"], 2) if f else None, "idx_fut_oi": f.get("oi"), "idx_fut_oi_n": f.get("oi_n"),
                           "idx_opt_net": round(o["buy"] - o["sell"], 2) if o else None, "idx_opt_oi": o.get("oi"),
                           "stk_fut_net": round(sf["buy"] - sf["sell"], 2) if sf else None, "stk_fut_oi": sf.get("oi")})
    reps = sector_reports()
    sect = None
    if reps:
        last = reps[-1]
        tot_auc = last["total"]["auc"] or 1
        hist = reps[-24:]
        sect = {
            "end": last["end"], "net_period": last["net_period"], "prev_period": last["prev_period"], "source": last.get("source"),
            "reports": len(reps), "first": reps[0]["end"],
            "periods": [r["end"] for r in hist],
            "total": last["total"], "total_hist": [r["total"]["net"] for r in hist],
            "sectors": sorted([{**s, "share": round(100 * s["auc"] / tot_auc, 2),
                                "hist": [next((x["net"] for x in r["sectors"] if x["name"] == s["name"]), None) for r in hist],
                                "net_1y": round(sum(next((x["net"] for x in r["sectors"] if x["name"] == s["name"]), 0) for r in hist), 2)}
                               for s in last["sectors"]], key=lambda s: -s["auc"]),
        }
    md = mf_days()
    per = store.get_company("SEBIMF::PERIODS")
    mf_checks = {k.split("::")[1]: (store.get_company(k) or (0, {}))[1].get("checked") for k in store.keys_like("SEBIMF2::____-__")}
    return {
        "nsdl": {"rows": rows[-1300:], "months": months, "years": [dict(y, exch=round(y["exch"], 2), equity=round(y["equity"], 2)) for y in years.values()],
                 "first": rows[0]["date"] if rows else None, "last": rows[-1]["date"] if rows else None,
                 "days": len(rows), "backfill": dict(STATE["nsdl"]), "records": records(rows),
                 "unchecked": [m["month"] for m in months if m["checked"] is False],
                 "deriv": deriv_rows[-1300:], "deriv_latest": dict(dv[max(dv)], date=max(dv)) if dv else None},
        "sectors": sect, "sectors_backfill": dict(STATE["sectors"]),
        "mf": {"days": [{"date": d, **v} for d, v in md.items()][-400:], "months": [dict(m, checked=mf_checks.get(m["month"])) for m in _monthly(md, None)],
               "periods": sorted(per[1]["rows"], key=lambda r: -int((re.findall(r"\d{4}", r["period"]) or ["0"])[0])) if per else [],
               "last": max(md) if md else None, "backfill": dict(STATE["mf"])},
        "errors": dict(STATE["errors"]),
    }


# ================================================================ demo data (offline screenshots and tests only)
SECTOR_NAMES = ["Automobile and Auto Components", "Capital Goods", "Chemicals", "Construction", "Construction Materials", "Consumer Durables",
                "Consumer Services", "Diversified", "Fast Moving Consumer Goods", "Financial Services", "Forest Materials", "Healthcare",
                "Information Technology", "Media, Entertainment & Publication", "Metals & Mining", "Oil, Gas & Consumable Fuels", "Power",
                "Realty", "Services", "Telecommunication", "Textiles", "Utilities", "Sovereign", "Others"]


def _demo_sectors(d: date) -> dict:
    rnd = random.Random(d.toordinal())
    rows = []
    for i, n in enumerate(SECTOR_NAMES):
        base = [480000, 380000, 90000, 110000, 95000, 160000, 170000, 4000, 520000, 2300000, 2000, 470000, 690000, 20000, 260000,
                560000, 230000, 110000, 120000, 300000, 15000, 20000, 0, 50000][i]
        net = round(rnd.gauss(0, base * 0.006)) if base else 0
        rows.append({"name": n, "auc_start": base, "net_prev": round(rnd.gauss(0, base * 0.006)) if base else 0, "net": net,
                     "auc": round(base * (1 + 0.02 * math.sin(d.toordinal() / 40)) + net)})
    tot = {k: sum(r[k] for r in rows) for k in ("auc_start", "net_prev", "net", "auc")}
    m1 = date(d.year, d.month, 1)
    if d.day == 15:
        pe = m1 - timedelta(days=1)
        prev, cur = [date(pe.year, pe.month, 16), pe], [m1, d]
    else:
        prev, cur = [m1, date(d.year, d.month, 15)], [date(d.year, d.month, 16), d]
    return {"start": (cur[0] - timedelta(days=1)).isoformat(), "end": d.isoformat(),
            "prev_period": [x.isoformat() for x in prev], "net_period": [x.isoformat() for x in cur],
            "sectors": rows, "total": dict(tot, name="Grand Total"), "source": "demo"}


def demo_fill() -> None:
    rnd = random.Random(11)
    days, deriv, d = {}, {}, date(2026, 11, 20)
    while d > date(2021, 11, 1):
        if d.weekday() < 5:
            net = round(rnd.gauss(-150, 2400), 2)
            buy = round(12000 + rnd.uniform(0, 6000), 2)
            prim = round(abs(rnd.gauss(0, 400)), 2)
            iso = d.isoformat()
            days[iso] = {"exch": {"buy": buy, "sell": round(buy - net, 2), "net": net},
                         "primary": {"buy": prim, "sell": 0.0, "net": prim},
                         "sub": {"buy": round(buy + prim, 2), "sell": round(buy - net, 2), "net": round(net + prim, 2)}}
            fb, fs = round(rnd.uniform(1500, 5000), 2), round(rnd.uniform(1500, 5000), 2)
            oi = round(40000 + 12000 * math.sin(d.toordinal() / 50), 2)
            deriv[iso] = {"idx_fut": {"buy_n": fb * 6, "buy": fb, "sell_n": fs * 6, "sell": fs, "oi_n": oi * 6, "oi": oi},
                          "idx_opt": {"buy_n": 9e6, "buy": 1.5e6, "sell_n": 9e6, "sell": round(1.5e6 + rnd.gauss(0, 4000), 2), "oi_n": 3.6e6, "oi": 5.5e5},
                          "stk_fut": {"buy_n": 3e5, "buy": 19000.0, "sell_n": 3e5, "sell": round(19000 + rnd.gauss(0, 900), 2), "oi_n": 6.2e6, "oi": 3.9e5},
                          "stk_opt": {"buy_n": 4e5, "buy": 25000.0, "sell_n": 4e5, "sell": 25000.0, "oi_n": 8e5, "oi": 5e4}}
        d -= timedelta(days=1)
    _save_parsed({"days": days, "deriv": deriv, "totals": {}})
    for ym in {k[:7] for k in days}:
        hit = store.get_company(_month_key(int(ym[:4]), int(ym[5:])))
        store.put_company(_month_key(int(ym[:4]), int(ym[5:])), dict(hit[1], final=True, checked=True))
    for x in _fortnights(HIST_FORTNIGHTS):
        fetch_sector_report(x.isoformat(), None)
    mf, d = {}, date(2026, 11, 6)
    while d > date(2025, 10, 1):
        if d.weekday() < 5:
            net = round(rnd.gauss(1500, 1800), 2)
            buy = round(9000 + rnd.uniform(0, 5000), 2)
            mf[d.isoformat()] = {"buy": buy, "sell": round(buy - net, 2), "net": net}
        d -= timedelta(days=1)
    _save_mf({"days": mf, "total": None})
    store.put_company("SEBIMF::PERIODS", {"rows": [{"period": f"April {y}-Mar {y + 1}", "buy": 900000.0, "sell": 900000.0 - n, "net": float(n)}
                                                     for y, n in zip(range(2016, 2026), [52000, 113000, 109000, 35000, -120000, -53000, 180000, 175000, 330000, 420000])]})
