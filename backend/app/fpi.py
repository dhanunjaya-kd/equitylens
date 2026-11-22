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


def _iso(s: str) -> Optional[str]:
    m = DATE_RE.match(s.strip())
    if not m:
        return None
    try:
        return datetime.strptime(f"{int(m.group(1)):02d}-{m.group(2).title()}-{m.group(3)}", "%d-%b-%Y").date().isoformat()
    except ValueError:
        return None


def parse_nsdl_daily(html: str) -> tuple[dict, int]:
    """-> ({iso reporting date: {"exch": {buy, sell, net}, "primary": {...}, "sub": {...}}} for Equity, rows that failed the check).
    Only the equity investments table is read; the derivative-trades table further down is ignored."""
    out: dict = {}
    bad = 0
    cur = asset = None
    for cells in _rows(html):
        labels, nums = [], []
        for c in cells:
            d = _iso(c)
            if d:
                cur, asset = d, None
                continue
            if c.startswith("Rs.") or c.startswith("Rs "):      # the USD conversion rate cell
                continue
            v = num(c)
            if v is not None and re.fullmatch(r"\(?-?[\d,]+(\.\d+)?\)?", c.replace(" ", "")):
                nums.append(v)
            elif c:
                labels.append(c.strip().lower())
        for lb in labels:
            if lb in ASSETS:
                asset = ASSETS[lb]
        if "derivative" in " ".join(labels):
            cur = None                                            # the derivative table starts: stop reading
        route = next((ROUTES[lb] for lb in labels if lb in ROUTES), None)
        if cur and asset == "equity" and route and len(nums) >= 3:
            buy, sell, net = nums[:3]
            if abs(buy - sell - net) > TOL:
                bad += 1
                continue
            out.setdefault(cur, {})[route] = {"buy": buy, "sell": sell, "net": net}
    return {d: v for d, v in out.items() if "exch" in v}, bad


def _month_key(y: int, m: int) -> str:
    return f"NSDLFPI::{y:04d}-{m:02d}"


def _save_days(days: dict, final_months: set) -> None:
    by: dict = {}
    for d, v in days.items():
        by.setdefault(d[:7], {})[d] = v
    for ym, rows in by.items():
        y, m = int(ym[:4]), int(ym[5:])
        hit = store.get_company(_month_key(y, m))
        old = hit[1]["days"] if hit else {}
        old.update(rows)
        store.put_company(_month_key(y, m), {"days": old, "final": ym in final_months or bool(hit and hit[1].get("final"))})


def fetch_nsdl_current() -> Optional[int]:
    """The current month so far (plain page). -> number of reporting dates read."""
    if config.DEMO:
        return None
    try:
        html = _get(_session(), NSDL_MONTH)
    except requests.RequestException as e:
        _err("nsdl", f"NSDL: {e.__class__.__name__}")
        return None
    days, bad = parse_nsdl_daily(html or "")
    if not days:
        _err("nsdl", "NSDL's daily page could not be read" + (f" ({bad} rows failed the purchases - sales = net check)" if bad else ""))
        return None
    _err("nsdl", None)
    _save_days(days, set())
    return len(days)


def _aspnet_post(sess: requests.Session, url: str, fields: dict) -> Optional[str]:
    """Load an ASP.NET page, keep every hidden field (view state etc.), set ours, submit like the browser does."""
    page = _get(sess, url)
    if not page:
        return None
    soup = BeautifulSoup(page, "html.parser")
    form = soup.find("form")
    if not form:
        return None
    data = {}
    for inp in form.find_all("input"):
        name = inp.get("name")
        if name and (inp.get("type") or "text").lower() in ("hidden", "text"):
            data[name] = inp.get("value", "")
    for k, v in fields.items():
        hit = [n for n in data if n.lower().endswith(k.lower())]
        for n in hit or [k]:
            data[n] = v
    sub = form.find("input", {"type": "submit"})
    if sub is not None and sub.get("name"):
        data[sub["name"]] = sub.get("value", "")
    host = re.match(r"https?://[^/]+", url).group(0)
    r = sess.post(urljoin(url, form.get("action") or url), data=data, timeout=config.REQUEST_TIMEOUT,
                  headers={"Referer": url, "Origin": host, "Content-Type": "application/x-www-form-urlencoded"})
    return r.text if r.status_code == 200 else None


def fetch_nsdl_month(y: int, m: int, sess: Optional[requests.Session] = None) -> Optional[int]:
    """A past month from NSDL's archive. Saved only if the reply really holds that month's dates."""
    last = (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1))
    html = _aspnet_post(sess or _session(), NSDL_ARCHIVE, {"hdnDate": last.strftime("%d-%b-%Y")})
    days, _ = parse_nsdl_daily(html or "")
    days = {d: v for d, v in days.items() if d[:7] == f"{y:04d}-{m:02d}"}
    if not days:
        return None
    _save_days(days, {f"{y:04d}-{m:02d}"})
    return len(days)


def nsdl_days() -> dict:
    out: dict = {}
    for k in store.keys_like("NSDLFPI::%"):
        hit = store.get_company(k)
        if hit:
            out.update(hit[1]["days"])
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
    todo = []
    for y, m in _months_back(HIST_MONTHS):
        hit = store.get_company(_month_key(y, m))
        if not (hit and hit[1].get("final")):
            todo.append((y, m))
    st.update(running=bool(todo), done=0, total=len(todo))
    sess, misses = _session(), 0
    for k, (y, m) in enumerate(todo, 1):
        try:
            n = fetch_nsdl_month(y, m, sess)
        except requests.RequestException as e:
            n = None
            _err("nsdl_archive", f"NSDL archive: {e.__class__.__name__}")
        if n:
            misses = 0
            st["ok"] = True
            _err("nsdl_archive", None)
        else:
            misses += 1
            if misses >= 3:                                      # the archive is refusing us: stop, try again later
                st["ok"] = False if st["ok"] is None else st["ok"]
                _err("nsdl_archive", "NSDL's archive did not return past months; only months saved from the daily page are shown")
                break
        st["done"] = k
        time.sleep(1.0)
    st["running"] = False


# ================================================================ 2. fortnightly sector-wise FPI data
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
P_AUC = re.compile(r"AUC as on\s+([A-Z][a-z]+)\s+(\d{1,2}),\s*(\d{4})")
P_NET = re.compile(r"Net Investment\s+([A-Z][a-z]+)\s+(\d{1,2})\s*-\s*(\d{1,2}),\s*(\d{4})")


def _d(mon: str, dd: str, yyyy: str) -> Optional[str]:
    try:
        return date(int(yyyy), MONTHS.index(mon) + 1, int(dd)).isoformat()
    except (ValueError, IndexError):
        return None


def parse_sectors(html: str) -> dict:
    """-> {"end": iso, "start": iso, "net_period": (from, to), "prev_period": (...), "sectors": [{name, auc_start, net_prev, net, auc}],
    "total": {...}} with equity figures in Rs crore, or {} if the page does not check out."""
    text = BeautifulSoup(html or "", "html.parser").get_text(" ", strip=True)
    aucs = [_d(*m) for m in P_AUC.findall(text)]
    nets = [(_d(m[0], m[1], m[3]), _d(m[0], m[2], m[3])) for m in P_NET.findall(text)]
    if len(aucs) < 2 or len(nets) < 2 or not all(aucs[:2]) or not all(x for n in nets[:2] for x in n):
        return {}
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


def _fortnights(n: int) -> list[date]:
    """Report dates (15th and month end), newest first, only ones that should already be out (a week's grace)."""
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


def fetch_sector_report(d: date, sess: Optional[requests.Session] = None) -> dict:
    key = f"FPISECT::{d.isoformat()}"
    hit = store.get_company(key)
    if hit:
        return hit[1]["r"]
    if config.DEMO:
        r = _demo_sectors(d)
        store.put_company(key, {"r": r})
        return r
    sess = sess or _session()
    r: dict = {}
    for back in range(0, 4):                                     # a report dated on a holiday can carry the day before
        x = d - timedelta(days=back)
        for url in (SECT_CDSL.format(month=MONTHS[x.month - 1], dd=x.day, yyyy=x.year),
                    SECT_NSDL.format(mon=x.strftime("%b"), dd=x.strftime("%d"), yyyy=x.year)):
            try:
                html = _get(sess, url)
            except requests.RequestException:
                html = None
            if html:
                r = parse_sectors(html)
                if r and abs((date.fromisoformat(r["end"]) - x).days) > 3:
                    r = {}                                       # the page is for another date: not this report
                if r:
                    r["source"] = url
                    break
        if r:
            break
    if r or d < date.today() - timedelta(days=45):               # a missing old report stays missing
        store.put_company(key, {"r": r})
    return r


def backfill_sectors() -> None:
    st = STATE["sectors"]
    todo = [d for d in _fortnights(HIST_FORTNIGHTS) if store.get_company(f"FPISECT::{d.isoformat()}") is None]
    st.update(running=bool(todo), done=0, total=len(todo))
    sess, misses = _session(), 0
    for k, d in enumerate(todo, 1):
        r = fetch_sector_report(d, sess)
        if r:
            misses, st["ok"] = 0, True
            _err("sectors", None)
        else:
            misses += 1
            if misses >= 4 and not st["ok"]:
                st["ok"] = False
                _err("sectors", "NSDL / CDSL sector reports could not be read")
                break
        st["done"] = k
        time.sleep(0.6)
    st["running"] = False


def sector_reports() -> list[dict]:
    out = []
    for k in store.keys_like("FPISECT::%"):
        hit = store.get_company(k)
        if hit and hit[1]["r"]:
            out.append(hit[1]["r"])
    by = {r["end"]: r for r in out}                             # one per report date
    return [by[d] for d in sorted(by)]


# ================================================================ 3. SEBI: mutual funds on the stock exchanges
SEBI_DATE_FMTS = ("%d %b, %Y", "%d %b %Y", "%d-%b-%Y", "%d/%m/%Y", "%d-%m-%Y", "%b %d, %Y", "%d %B, %Y", "%d %B %Y")
PERIOD_RE = re.compile(r"^[A-Z][a-z]+\.?\s+\d{4}\s*-\s*[A-Z][a-z]+\.?\s+\d{4}$")


def _sebi_date(s: str) -> Optional[str]:
    s = re.sub(r"\s+", " ", s.strip())
    for f in SEBI_DATE_FMTS:
        try:
            return datetime.strptime(s, f).date().isoformat()
        except ValueError:
            continue
    return None


def parse_sebi_mf(html: str) -> tuple[dict, list]:
    """-> ({iso trading date: {buy, sell, net}} for equity, [{period, buy, sell, net}] yearly/period equity rows).
    Rows where purchases - sales != net (beyond rounding) are dropped."""
    days, periods = {}, []
    cur_d = cur_p = None
    section = None
    for cells in _rows(html):
        joined = " ".join(cells).lower()
        if "derivative" in joined:
            section = "deriv"
        if section == "deriv":
            continue
        labels, nums = [], []
        for c in cells:
            d = _sebi_date(c)
            if d:
                cur_d, cur_p = d, None
                continue
            if PERIOD_RE.match(re.sub(r"\s+", " ", c.strip())):
                cur_p, cur_d = re.sub(r"\s+", " ", c.strip()), None
                continue
            v = num(c)
            if v is not None and re.fullmatch(r"\(?-?[\d,]+(\.\d+)?\)?", c.replace(" ", "")):
                nums.append(v)
            elif c:
                labels.append(c.strip().lower())
        if "equity" in labels and len(nums) >= 3:
            buy, sell, net = nums[:3]
            if abs(buy - sell - net) > TOL:
                continue
            rec = {"buy": buy, "sell": sell, "net": net}
            if cur_d:
                days[cur_d] = rec
            elif cur_p:
                periods.append(dict(rec, period=cur_p))
    return days, periods


def mf_days() -> dict:
    hit = store.get_company("SEBIMF::DAYS")
    return hit[1] if hit else {}


def _save_mf(days: dict) -> None:
    if not days:
        return
    cur = mf_days()
    cur.update(days)
    store.put_company("SEBIMF::DAYS", dict(sorted(cur.items())))


def fetch_mf_current() -> Optional[int]:
    if config.DEMO:
        return None
    try:
        html = _get(_session(), SEBI_MF)
    except requests.RequestException as e:
        _err("mf", f"SEBI: {e.__class__.__name__}")
        return None
    days, periods = parse_sebi_mf(html or "")
    if not days and not periods:
        _err("mf", "SEBI's mutual fund page could not be read")
        return None
    _err("mf", None)
    _save_mf(days)
    if periods:
        store.put_company("SEBIMF::PERIODS", {"rows": periods})
    return len(days)


def fetch_mf_month(y: int, m: int, sess: requests.Session) -> Optional[int]:
    """SEBI's own search for a past date (returns that month). Saved only if the reply holds that month."""
    last = date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)
    page = _get(sess, SEBI_MF)
    if not page:
        return None
    soup = BeautifulSoup(page, "html.parser")
    data = {i.get("name"): i.get("value", "") for i in soup.find_all("input", {"type": "hidden"}) if i.get("name")}
    data["date"] = last.strftime("%d-%m-%Y")
    r = sess.post(SEBI_MF_SEARCH, data=data, timeout=config.REQUEST_TIMEOUT,
                  headers={"Referer": SEBI_MF, "Origin": "https://www.sebi.gov.in", "X-Requested-With": "XMLHttpRequest"})
    if r.status_code != 200:
        return None
    days, _ = parse_sebi_mf(r.text)
    days = {d: v for d, v in days.items() if d[:7] == f"{y:04d}-{m:02d}"}
    _save_mf(days)
    return len(days) or None


def backfill_mf() -> None:
    st = STATE["mf"]
    have = {d[:7] for d in mf_days()}
    todo = [(y, m) for y, m in _months_back(HIST_MONTHS) if f"{y:04d}-{m:02d}" not in have
            and not store.get_company(f"SEBIMF::TRIED::{y:04d}-{m:02d}")]
    st.update(running=bool(todo), done=0, total=len(todo))
    sess, misses = _session(), 0
    for k, (y, m) in enumerate(todo, 1):
        try:
            n = fetch_mf_month(y, m, sess)
        except requests.RequestException:
            n = None
        if n:
            misses, st["archive"] = 0, True
        else:
            misses += 1
            if misses >= 3 and not st["archive"]:
                st["archive"] = False
                break
        if date(y, m, 1) < date.today().replace(day=1) - timedelta(days=62):
            store.put_company(f"SEBIMF::TRIED::{y:04d}-{m:02d}", {"n": n or 0})
        st["done"] = k
        time.sleep(1.0)
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
def _monthly(days: dict, key: str) -> list[dict]:
    by: dict = {}
    for d, v in days.items():
        x = v.get(key) if key != "net" else v
        if x is None:
            continue
        b = by.setdefault(d[:7], {"month": d[:7], "net": 0.0, "days": 0})
        b["net"] += x["net"]
        b["days"] += 1
    return [dict(b, net=round(b["net"], 2)) for b in (by[k] for k in sorted(by))]


def payload() -> dict:
    nd = nsdl_days()
    rows = [{"date": d, "net": v["exch"]["net"], "buy": v["exch"]["buy"], "sell": v["exch"]["sell"],
             "primary": (v.get("primary") or {}).get("net"), "equity": (v.get("sub") or {}).get("net")} for d, v in nd.items()]
    m_exch = {b["month"]: b for b in _monthly(nd, "exch")}
    m_sub = {b["month"]: b for b in _monthly(nd, "sub")}
    months = [{"month": k, "exch": m_exch[k]["net"], "equity": m_sub[k]["net"] if k in m_sub else None, "days": m_exch[k]["days"]} for k in sorted(m_exch)]
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
                                "net_1y": round(sum(next((x["net"] for x in r["sectors"] if x["name"] == s["name"]), 0) for r in reps[-24:]), 2)}
                               for s in last["sectors"]], key=lambda s: -s["auc"]),
        }
    md = mf_days()
    per = store.get_company("SEBIMF::PERIODS")
    return {
        "nsdl": {"rows": rows[-1300:], "months": months, "first": rows[0]["date"] if rows else None, "last": rows[-1]["date"] if rows else None,
                 "days": len(rows), "backfill": dict(STATE["nsdl"])},
        "sectors": sect, "sectors_backfill": dict(STATE["sectors"]),
        "mf": {"days": [{"date": d, **v} for d, v in md.items()][-400:], "months": _monthly(md, "net"),
               "periods": sorted(per[1]["rows"], key=lambda r: -int((re.findall(r"\d{4}", r["period"]) or ["0"])[0])) if per else [], "last": max(md) if md else None, "backfill": dict(STATE["mf"])},
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
    days, d = {}, date(2026, 11, 20)
    while d > date(2021, 11, 1):
        if d.weekday() < 5:
            net = round(rnd.gauss(-150, 2400), 2)
            buy = round(12000 + rnd.uniform(0, 6000), 2)
            prim = round(abs(rnd.gauss(0, 400)), 2)
            days[d.isoformat()] = {"exch": {"buy": buy, "sell": round(buy - net, 2), "net": net},
                                   "primary": {"buy": prim, "sell": 0.0, "net": prim},
                                   "sub": {"buy": round(buy + prim, 2), "sell": round(buy - net, 2), "net": round(net + prim, 2)}}
        d -= timedelta(days=1)
    _save_days(days, {k[:7] for k in days})
    for x in _fortnights(HIST_FORTNIGHTS):
        fetch_sector_report(x)
    mf, d = {}, date(2026, 11, 6)
    while d > date(2025, 10, 1):
        if d.weekday() < 5:
            net = round(rnd.gauss(1500, 1800), 2)
            buy = round(9000 + rnd.uniform(0, 5000), 2)
            mf[d.isoformat()] = {"buy": buy, "sell": round(buy - net, 2), "net": net}
        d -= timedelta(days=1)
    _save_mf(mf)
    store.put_company("SEBIMF::PERIODS", {"rows": [{"period": f"April {y}-Mar {y + 1}", "buy": 900000.0, "sell": 900000.0 - n, "net": float(n)}
                                                     for y, n in zip(range(2016, 2026), [52000, 113000, 109000, 35000, -120000, -53000, 180000, 175000, 330000, 420000])]})
