"""Earnings calendar + economic-events calendar for India and the US. No keys, no logins.

Sources (all public):
  🇺🇸 earnings        Nasdaq public calendar JSON (api.nasdaq.com/api/calendar/earnings?date=)
  🇮🇳 results/events  NSE event calendar JSON (nseindia.com/api/event-calendar), board meetings
  🌐 economy          Nasdaq public economic-events JSON (api.nasdaq.com/api/calendar/economicevents?date=)
  📌 official dates   RBI MPC, MoSPI (CPI / IIP / GDP), DPIIT (WPI), Federal Reserve (FOMC) published schedules

Every day is fetched once and cached (past days for a week, future days for a few hours).
"""
from __future__ import annotations

import random
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import requests

from . import config, store

UTC = timezone.utc
IST = timezone(timedelta(hours=5, minutes=30))
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
_NQ_HEADERS = {"User-Agent": _UA, "Accept": "application/json, text/plain, */*", "Accept-Language": "en-US,en;q=0.9",
               "Origin": "https://www.nasdaq.com", "Referer": "https://www.nasdaq.com/"}
_NSE_HEADERS = {"User-Agent": _UA, "Accept": "application/json, text/plain, */*", "Accept-Language": "en-IN,en;q=0.9",
                "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-event-calendar"}
_lock = threading.Lock()
_last = [0.0]


class CalendarError(Exception):
    pass


def _pace(gap: float = 0.4) -> None:
    with _lock:
        w = gap - (time.time() - _last[0])
        if w > 0:
            time.sleep(w)
        _last[0] = time.time()


def _ttl(d: date) -> float:
    today = datetime.now(IST).date()
    if d < today - timedelta(days=1):
        return 7 * 86400          # past: actuals no longer change
    if d <= today + timedelta(days=1):
        return 1800               # yesterday/today/tomorrow: times and actuals still filling in
    return 4 * 3600


def _cached(key: str, d: date, fetch) -> tuple[list[dict], Optional[str]]:
    hit = store.get_company(key)
    if hit and time.time() - hit[0] < _ttl(d):
        return hit[1]["rows"], None
    try:
        rows = fetch(d)
        store.put_company(key, {"rows": rows})
        return rows, None
    except Exception as e:  # noqa: BLE001 - show stale data with a note instead of failing
        if hit:
            return hit[1]["rows"], f"showing saved data ({e})"
        return [], str(e)


# ------------------------------------------------------------------ parsing helpers
def _clean(v) -> Optional[str]:
    if v is None:
        return None
    s = re.sub(r"<[^>]+>", "", str(v)).replace("&nbsp;", " ").replace("\xa0", " ").strip()
    return s if s and s not in ("-", "N/A", "--") else None


def money(v) -> Optional[float]:
    """'$1.23' → 1.23, '($0.59)' → -0.59, '$131,271,743,181' → 131271743181."""
    s = _clean(v)
    if not s:
        return None
    neg = s.startswith("(") or s.startswith("-")
    s = re.sub(r"[^\d.]", "", s)
    try:
        x = float(s)
    except ValueError:
        return None
    return -x if neg else x


def number(v) -> Optional[float]:
    """First number in a printed value: '3.2%' → 3.2, '-60.30B' → -60.3, '221K' → 221 (units stay in the text)."""
    s = _clean(v)
    if not s:
        return None
    m = re.search(r"-?\d+(?:,\d{3})*(?:\.\d+)?", s)
    return float(m.group(0).replace(",", "")) if m else None


def _rows(j: dict) -> list[dict]:
    d = (j or {}).get("data") or {}
    rows = d.get("rows")
    if rows is None and isinstance(d.get("calendar"), dict):
        rows = d["calendar"].get("rows")
    return rows or []


# ------------------------------------------------------------------ 🇺🇸 earnings (Nasdaq)
TIMING = {"time-pre-market": "BMO", "time-after-hours": "AMC", "time-not-supplied": "TBD"}


def parse_nasdaq_earnings(j: dict, d: date) -> list[dict]:
    out = []
    for r in _rows(j):
        sym = _clean(r.get("symbol"))
        if not sym:
            continue
        mcap = money(r.get("marketCap"))
        est, eps = money(r.get("epsForecast")), money(r.get("eps"))
        surprise = number(r.get("surprise"))
        out.append({
            "market": "US", "symbol": "US:" + sym.replace(".", "-").upper(), "ticker": sym, "name": _clean(r.get("name")) or sym,
            "date": d.isoformat(), "timing": TIMING.get(r.get("time") or "", "TBD"), "type": "Earnings",
            "fiscal_quarter": _clean(r.get("fiscalQuarterEnding")),
            "eps_estimate": est, "estimates": int(number(r.get("noOfEsts")) or 0) or None,
            "eps_last_year": money(r.get("lastYearEPS")), "last_year_date": _clean(r.get("lastYearRptDt")),
            "eps_actual": eps, "surprise_pct": surprise,
            "market_cap": round(mcap / 1e6, 1) if mcap else None,      # $ M
        })
    return out


def _fetch_us_earnings(d: date) -> list[dict]:
    if config.DEMO:
        return parse_nasdaq_earnings(_demo_nasdaq_earnings(d), d)
    _pace()
    r = requests.get("https://api.nasdaq.com/api/calendar/earnings", params={"date": d.isoformat()},
                     headers=_NQ_HEADERS, timeout=config.REQUEST_TIMEOUT)
    if r.status_code != 200:
        raise CalendarError(f"Nasdaq earnings calendar answered {r.status_code}")
    return parse_nasdaq_earnings(r.json(), d)


# ------------------------------------------------------------------ 🇮🇳 results & board meetings (NSE)
_nse = {"s": None, "t": 0.0}


def _nse_session() -> requests.Session:
    if _nse["s"] is None or time.time() - _nse["t"] > 600:
        s = requests.Session()
        s.headers.update(_NSE_HEADERS)
        s.get("https://www.nseindia.com/", timeout=config.REQUEST_TIMEOUT)            # sets the cookies the API needs
        s.get("https://www.nseindia.com/companies-listing/corporate-filings-event-calendar", timeout=config.REQUEST_TIMEOUT)
        _nse.update(s=s, t=time.time())
    return _nse["s"]


def classify_purpose(text: str) -> str:
    t = (text or "").lower()
    if "result" in t:
        return "Results"
    for k, v in (("bonus", "Bonus"), ("split", "Stock split"), ("sub-division", "Stock split"), ("buy back", "Buyback"),
                 ("buyback", "Buyback"), ("dividend", "Dividend"), ("fund rais", "Fund raising"), ("preferential", "Fund raising"),
                 ("qip", "Fund raising"), ("rights", "Rights issue"), ("merger", "Merger / scheme"), ("amalgamation", "Merger / scheme"),
                 ("scheme", "Merger / scheme"), ("delisting", "Delisting")):
        if k in t:
            return v
    return "Board meeting"


def _nse_date(s: str) -> Optional[date]:
    s = (s or "").strip()
    for cand in (s, s.split(" ")[0], s[:11].strip(), s[:10]):          # NSE sometimes adds a time: "13-Nov-2026 18:42"
        for fmt in ("%d-%b-%Y", "%d-%m-%Y", "%Y-%m-%d", "%d %b %Y", "%d/%m/%Y", "%d-%B-%Y"):
            try:
                return datetime.strptime(cand, fmt).date()
            except ValueError:
                pass
    return None


def parse_nse_events(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows or []:
        d = _nse_date(r.get("date") or r.get("bm_date") or "")
        sym = (r.get("symbol") or "").strip().upper()
        if not d or not sym:
            continue
        purpose = _clean(r.get("purpose")) or ""
        desc = _clean(r.get("bm_desc")) or ""
        kind = classify_purpose(purpose + " " + desc)
        out.append({"market": "IN", "symbol": sym, "ticker": sym, "name": _clean(r.get("company")) or sym,
                    "date": d.isoformat(), "timing": None, "type": kind,
                    "purpose": purpose or kind, "detail": desc[:400] if desc and desc.lower() != purpose.lower() else None})
    return out


def _fetch_in_range(start: date, end: date) -> list[dict]:
    if config.DEMO:
        return parse_nse_events(_demo_nse(start, end))
    for attempt in range(2):
        try:
            s = _nse_session()
            _pace(1.0)
            r = s.get("https://www.nseindia.com/api/event-calendar", timeout=config.REQUEST_TIMEOUT,
                      params={"index": "equities", "from_date": start.strftime("%d-%m-%Y"), "to_date": end.strftime("%d-%m-%Y")})
            if r.status_code == 200:
                j = r.json()
                return parse_nse_events(j if isinstance(j, list) else j.get("data") or [])
            _nse["s"] = None                      # expired cookies → new session once
        except (requests.RequestException, ValueError) as e:
            _nse["s"] = None
            if attempt:
                raise CalendarError(f"NSE event calendar not reachable: {e}") from e
    raise CalendarError("NSE event calendar refused the request (try again in a minute)")


def _in_events(start: date, end: date) -> tuple[list[dict], Optional[str]]:
    """NSE answers a whole range in one call; cache per range-week."""
    key = f"CAL::IN::{start.isoformat()}::{end.isoformat()}"
    return _cached(key, start, lambda _d: _fetch_in_range(start, end))


# ------------------------------------------------------------------ 🌐 economic events (Nasdaq)
COUNTRY = {"US": "United States", "IN": "India"}


def parse_nasdaq_econ(j: dict, d: date) -> list[dict]:
    out = []
    for r in _rows(j):
        name = _clean(r.get("eventName") or r.get("event"))
        if not name:
            continue
        t = _clean(r.get("gmt") or r.get("time_gmt") or r.get("time"))
        at = None
        if t and re.fullmatch(r"\d{1,2}:\d{2}", t):
            hh, mm = map(int, t.split(":"))
            at = datetime(d.year, d.month, d.day, hh, mm, tzinfo=UTC).isoformat()
        out.append({"date": d.isoformat(), "at": at, "country": _clean(r.get("country")) or "", "event": name,
                    "actual": _clean(r.get("actual")), "forecast": _clean(r.get("consensus")), "previous": _clean(r.get("previous")),
                    "about_source": (_clean(r.get("description")) or "")[:600] or None, "source": "Nasdaq economic calendar"})
    return out


def _fetch_econ(d: date) -> list[dict]:
    if config.DEMO:
        return parse_nasdaq_econ(_demo_nasdaq_econ(d), d)
    _pace()
    r = requests.get("https://api.nasdaq.com/api/calendar/economicevents", params={"date": d.isoformat()},
                     headers=_NQ_HEADERS, timeout=config.REQUEST_TIMEOUT)
    if r.status_code != 200:
        raise CalendarError(f"Nasdaq economic calendar answered {r.status_code}")
    return parse_nasdaq_econ(r.json(), d)


# ------------------------------------------------------------------ 📌 official schedules (published by the agencies)
def _next_working(d: date) -> date:
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def _ist(d: date, hh: int, mm: int = 0) -> str:
    return datetime(d.year, d.month, d.day, hh, mm, tzinfo=IST).astimezone(UTC).isoformat()


def _et(d: date, hh: int, mm: int = 0) -> str:
    # US Eastern: EDT (UTC-4) from 2nd Sunday of March to 1st Sunday of November, else EST (UTC-5)
    mar = date(d.year, 3, 8) + timedelta(days=(6 - date(d.year, 3, 8).weekday()) % 7)
    nov = date(d.year, 11, 1) + timedelta(days=(6 - date(d.year, 11, 1).weekday()) % 7)
    off = -4 if mar <= d < nov else -5
    return datetime(d.year, d.month, d.day, hh, mm, tzinfo=timezone(timedelta(hours=off))).astimezone(UTC).isoformat()


RBI_SRC = "https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx?prid=62422"
MOSPI_SRC = "https://www.mospi.gov.in/uploads/documents/releaseCalender/1791356248513-ARC_2026_27_Sept_2026.pdf"
WPI_SRC = "https://www.eaindustry.nic.in/uploaded_files/Advance_Release_Calander_WPI.pdf"
FOMC_SRC = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"


def official_events() -> list[dict]:
    ev = []

    def add(country, d, at, name, src, note=None):
        ev.append({"date": d.isoformat(), "at": at, "country": country, "event": name, "actual": None, "forecast": None,
                   "previous": None, "source": src, "official": True, "note": note})

    # RBI MPC 2026-27 (RBI press release, 23 Mar 2026): decision on the last day, ~10:00 IST
    for d in (date(2026, 4, 8), date(2026, 6, 5), date(2026, 8, 5), date(2026, 10, 7), date(2026, 12, 4), date(2027, 2, 5)):
        add("India", d, _ist(d, 10), "RBI Interest Rate Decision (MPC)", RBI_SRC, "3-day MPC meeting ends; Governor's statement ~10:00 IST")
    # MoSPI Advance Release Calendar 2026-27: CPI on the 12th, IIP on the 28th, 4:00 PM IST; holidays → next working day
    for y, m in [(2026, k) for k in range(4, 13)] + [(2027, k) for k in range(1, 4)]:
        d = _next_working(date(y, m, 12))
        add("India", d, _ist(d, 16), "CPI Inflation (YoY)", MOSPI_SRC, "MoSPI release, 4:00 PM IST")
        d = _next_working(date(y, m, 28))
        add("India", d, _ist(d, 16), "Industrial Production (IIP, YoY)", MOSPI_SRC, "MoSPI release, 4:00 PM IST")
    for d, what in ((date(2026, 5, 29), "GDP Growth Rate (Q4 FY26) & FY26 provisional"), (date(2026, 8, 31), "GDP Growth Rate (Q1 FY27)"),
                    (date(2026, 11, 30), "GDP Growth Rate (Q2 FY27)"), (date(2027, 1, 7), "GDP First Advance Estimate FY27"),
                    (date(2027, 2, 26), "GDP Growth Rate (Q3 FY27) & 2nd Advance Estimate")):
        add("India", d, _ist(d, 16), what, MOSPI_SRC, "MoSPI release, 4:00 PM IST")
    # DPIIT WPI advance release calendar: 14th (next working day), 12:00 noon IST
    for d in (date(2026, 7, 14), date(2026, 8, 14), date(2026, 9, 14), date(2026, 10, 14), date(2026, 11, 16), date(2026, 12, 14),
              date(2027, 1, 14), _next_working(date(2027, 2, 14)), _next_working(date(2027, 3, 14))):
        add("India", d, _ist(d, 12), "WPI Inflation (YoY)", WPI_SRC, "Office of the Economic Adviser, 12:00 noon IST")
    # Federal Reserve FOMC: statement 2:00 PM ET on the 2nd day (2027 dates tentative per the Fed)
    sep = {date(2026, 3, 18), date(2026, 6, 17), date(2026, 9, 16), date(2026, 12, 9), date(2027, 3, 17), date(2027, 6, 9),
           date(2027, 9, 15), date(2027, 12, 8)}
    for d in (date(2026, 1, 28), date(2026, 3, 18), date(2026, 4, 29), date(2026, 6, 17), date(2026, 7, 29), date(2026, 9, 16),
              date(2026, 10, 28), date(2026, 12, 9), date(2027, 1, 27), date(2027, 3, 17), date(2027, 4, 28), date(2027, 6, 9),
              date(2027, 7, 28), date(2027, 9, 15), date(2027, 10, 27), date(2027, 12, 8)):
        add("United States", d, _et(d, 14), "Fed Interest Rate Decision (FOMC)", FOMC_SRC,
            "Statement 2:00 PM ET, press conference 2:30 PM" + (" · new projections & dot plot" if d in sep else "") +
            (" · 2027 dates tentative" if d.year == 2027 else ""))
    return ev


# ------------------------------------------------------------------ meaning of each event (own words)
# key words → (topic, importance 3/2/1, what it is, why markets care)
GUIDE = [
    (("interest rate decision", "fomc", "fed funds", "mpc", "repo rate", "monetary policy"), "rates", 3,
     "The central bank's policy rate decision.",
     "Sets the cost of money. A cut usually helps banks, real estate, autos and growth stocks; a hike or a hawkish tone usually hurts them."),
    (("nonfarm", "non-farm", "payroll"), "jobs", 3, "Jobs added in the US last month (outside farming).",
     "Strong hiring keeps the Fed cautious on cuts (yields up); weak hiring raises cut hopes but also growth worries."),
    (("unemployment rate",), "jobs", 3, "Share of the workforce looking for work.", "Rising unemployment = slowing economy; the Fed watches it closely."),
    (("core pce", "pce price"), "inflation", 3, "The Fed's preferred inflation gauge.", "Hotter than expected makes rate cuts less likely."),
    (("core cpi", "cpi", "consumer price", "inflation rate"), "inflation", 3, "How fast consumer prices are rising.",
     "Above forecast → fewer/later rate cuts, bond yields up, rate-sensitive stocks down. Below forecast → the opposite."),
    (("wpi", "wholesale price"), "inflation", 2, "Wholesale (factory-gate) price inflation.", "An early signal for retail inflation and company margins."),
    (("ppi", "producer price"), "inflation", 2, "Prices companies receive for goods and services.", "Feeds into consumer inflation and margins."),
    (("gdp",), "growth", 3, "Total output of the economy.", "Shows whether the economy (and corporate earnings) is speeding up or slowing down."),
    (("retail sales",), "growth", 3, "Spending at shops and online.", "Consumer spending drives most of the US economy."),
    (("ism", "pmi"), "growth", 2, "Purchasing managers' survey: above 50 = expanding, below 50 = shrinking.", "An early read on business activity and orders."),
    (("industrial production", "iip"), "growth", 2, "Output of factories, mines and utilities.", "Tracks the industrial cycle — capital goods, metals, power."),
    (("jobless claims", "initial claims"), "jobs", 2, "New unemployment-benefit applications last week.", "A rise is an early warning of layoffs."),
    (("jolts", "job openings"), "jobs", 2, "Open job positions.", "Shows labour demand; fewer openings = cooling job market."),
    (("consumer confidence", "consumer sentiment", "michigan"), "mood", 2, "How confident households feel.", "Hints at future spending; includes inflation expectations."),
    (("housing starts", "building permits", "home sales", "pending home"), "housing", 1, "Housing activity.", "Rate-sensitive; signals how higher rates bite."),
    (("durable goods",), "growth", 2, "Orders for long-lasting goods.", "A proxy for business investment."),
    (("trade balance", "current account"), "trade", 1, "Exports minus imports.", "Affects the currency and GDP."),
    (("fomc minutes", "minutes"), "rates", 2, "Notes from the last policy meeting.", "Shows how many members lean toward cuts or hikes."),
    (("fed chair", "powell", "speaks", "testimony", "governor"), "rates", 2, "A central-bank official speaks.", "Markets look for hints on the next rate move."),
    (("crude oil inventories", "eia"), "energy", 1, "Weekly US oil stock change.", "Moves crude prices — matters for oil companies, paints, airlines, OMCs."),
    (("treasury", "bill auction", "note auction", "bond auction"), "rates", 1, "Government borrowing auction.", "Weak demand can push yields up."),
    (("fx reserves", "foreign exchange reserves"), "trade", 1, "RBI's foreign-currency reserves.", "A buffer that steadies the rupee."),
    (("bank loan", "deposit growth"), "credit", 1, "Bank credit and deposit growth.", "Shows credit demand — relevant for banks and NBFCs."),
    (("plfs", "employment"), "jobs", 1, "Employment survey.", "Labour-market health."),
]


def guide(name: str) -> dict:
    n = (name or "").lower()
    for keys, topic, imp, what, why in GUIDE:
        if any(k in n for k in keys):
            return {"topic": topic, "importance": imp, "what": what, "why": why}
    return {"topic": "other", "importance": 1, "what": None, "why": None}


def _key(e: dict) -> str:
    n = e["event"].lower()
    for k in ("rate decision", "fomc", "core cpi", "cpi", "wpi", "iip", "industrial production", "gdp"):
        if k in n:
            return f"{e['date']}|{e['country']}|{'rate' if k in ('rate decision', 'fomc') else 'iip' if k == 'industrial production' else k}"
    return f"{e['date']}|{e['country']}|{n}"


def surprise(e: dict) -> Optional[str]:
    a, f = number(e.get("actual")), number(e.get("forecast"))
    if a is None or f is None:
        return None
    if abs(a - f) <= max(abs(f) * 0.01, 0.01):
        return "in line"
    return "above" if a > f else "below"


# ------------------------------------------------------------------ public API
def _days(start: date, days: int) -> list[date]:
    return [start + timedelta(days=i) for i in range(days)]


def _index_symbols(market: str) -> set[str]:
    from . import movers
    try:
        return {u["symbol"] for u in movers._universe(market)}
    except Exception:  # noqa: BLE001
        return set()


def _reaction(row: dict, mv: dict) -> Optional[float]:
    """Close the session after the results vs close the session before (covers BMO, AMC and Indian evening results)."""
    m = mv.get(row["symbol"])
    if not m or not m.get("spark_t"):
        return None
    t, c = m["spark_t"], m["spark"]
    d = row["date"]
    before = [i for i, x in enumerate(t) if x < d]
    after = [i for i, x in enumerate(t) if x > d] if row.get("timing") != "BMO" else [i for i, x in enumerate(t) if x >= d]
    if not before or not after:
        return None
    return round((c[after[0]] / c[before[-1]] - 1) * 100, 2)


def earnings(market: str, start: date, days: int = 7) -> dict:
    market = market.upper()
    days = max(1, min(days, 21))
    end = start + timedelta(days=days - 1)
    notes = []
    if market == "US":
        with ThreadPoolExecutor(max_workers=1 if config.DEMO else 3) as ex:
            got = list(ex.map(lambda d: _cached(f"CAL::US::{d.isoformat()}", d, _fetch_us_earnings), _days(start, days)))
        rows = [r for rs, _ in got for r in rs]
        notes = sorted({n for _, n in got if n})
        source = "Nasdaq earnings calendar (EPS estimates = analyst consensus)"
    else:
        rows, n = _in_events(start, end)
        notes = [n] if n else []
        source = "NSE event calendar (board meetings announced by the companies)"
    ranks = {r["symbol"]: r for r in store.all_rankings() if r.get("market", "IN") == market}
    idx = _index_symbols(market)
    mv_hit = store.get_company(f"MOVERS::{market}")
    mv = {r["symbol"]: r for r in (mv_hit[1]["rows"] if mv_hit else [])}
    today = datetime.now(IST).date().isoformat()
    from . import enrich, universe
    lots = enrich.fno() if market == "IN" else {}
    member = universe.membership() if market == "IN" else {}
    for r in rows:
        r["fno"] = r["symbol"] in lots
        if market == "IN":
            r["idx"] = member.get(r["symbol"], [])
        k = ranks.get(r["symbol"])
        r["in_index"] = r["symbol"] in idx
        r["fund"] = ({"overall": k.get("overall"), "business": k.get("business"), "verdict": k.get("verdict"), "tone": k.get("tone"),
                      "sales_cagr_3": k.get("sales_cagr_3"), "profit_cagr_3": k.get("profit_cagr_3"), "pe": k.get("pe"),
                      "high_flags": k.get("high_flags"), "sector": k.get("sector"), "market_cap": k.get("market_cap")} if k else None)
        if market == "IN" and k and k.get("market_cap"):
            r["market_cap"] = k["market_cap"]     # ₹ Cr
        r["reaction"] = _reaction(r, mv) if r["date"] < today or (r["date"] == today and r.get("timing") == "BMO") else None
        if market == "US" and r.get("eps_actual") is not None and r.get("eps_estimate") and r.get("surprise_pct") is None:
            r["surprise_pct"] = round((r["eps_actual"] - r["eps_estimate"]) / abs(r["eps_estimate"]) * 100, 1)
    rows = [r for r in rows if start.isoformat() <= r["date"] <= end.isoformat()]
    rows.sort(key=lambda r: (r["date"], not r["in_index"], -(r.get("market_cap") or 0)))
    by_day = {}
    for r in rows:
        if market == "IN" and r["type"] != "Results":
            continue
        by_day[r["date"]] = by_day.get(r["date"], 0) + 1
    return {"market": market, "start": start.isoformat(), "end": end.isoformat(), "rows": rows, "per_day": by_day,
            "source": source, "notes": notes, "scanned": len(ranks)}


def economy(market: str, start: date, days: int = 7) -> dict:
    market = market.upper()
    days = max(1, min(days, 21))
    end = start + timedelta(days=days - 1)
    country = COUNTRY.get(market, "United States")
    with ThreadPoolExecutor(max_workers=1 if config.DEMO else 3) as ex:
        got = list(ex.map(lambda d: _cached(f"CAL::ECON::{d.isoformat()}", d, _fetch_econ), _days(start, days)))
    live = [e for rs, _ in got for e in rs if e["country"] == country]
    notes = sorted({n for _, n in got if n})
    seen = {_key(e) for e in live}
    off = [e for e in official_events() if e["country"] == country and start.isoformat() <= e["date"] <= end.isoformat()]
    for e in live:   # attach the official note to the matching live row
        for o in off:
            if _key(o) == _key(e):
                e["note"], e["official_source"] = o["note"], o["source"]
    events = live + [o for o in off if _key(o) not in seen]
    for e in events:
        g = guide(e["event"])
        e.update(importance=g["importance"], topic=g["topic"], what=g["what"], why=g["why"], vs_forecast=surprise(e))
    events.sort(key=lambda e: (e["date"], e["at"] or "9", -e["importance"]))
    nxt = [o for o in official_events() if o["country"] == country and o["date"] >= datetime.now(IST).date().isoformat()]
    nxt.sort(key=lambda e: e["at"] or e["date"])
    big = []
    for kind in ("rate", "cpi", "gdp", "iip" if market == "IN" else "zzz"):
        for o in nxt:
            if kind in _key(o).split("|")[-1]:
                big.append({**o, **guide(o["event"])})
                break
    big.sort(key=lambda e: e["at"] or e["date"])
    return {"market": market, "country": country, "start": start.isoformat(), "end": end.isoformat(), "events": events,
            "next_big": big, "notes": notes,
            "source": "Nasdaq economic calendar (actual · forecast · previous) + official schedules from "
                      + ("RBI, MoSPI and DPIIT" if market == "IN" else "the Federal Reserve")}


def next_results(symbol: str) -> Optional[dict]:
    """Next results date for a stock, from whatever calendar days are already saved (no network)."""
    today = datetime.now(IST).date()
    market = "US" if symbol.startswith("US:") else "IN"
    if market == "US":
        for i in range(0, 45):
            hit = store.get_company(f"CAL::US::{(today + timedelta(days=i)).isoformat()}")
            for r in (hit[1]["rows"] if hit else []):
                if r["symbol"] == symbol:
                    return r
        return None
    best = None
    for k in store.keys_like("CAL::IN::%"):
        hit = store.get_company(k)
        for r in (hit[1]["rows"] if hit else []):
            if r["symbol"] == symbol and r["type"] == "Results" and r["date"] >= today.isoformat():
                if not best or r["date"] < best["date"]:
                    best = r
    return best


# ------------------------------------------------------------------ demo data (same raw formats as the live sources)
def _demo_syms(market: str) -> list[dict]:
    from . import movers
    return movers._universe(market)


def _demo_nasdaq_earnings(d: date) -> dict:
    if d.weekday() >= 5:
        return {"data": {"rows": []}}
    rnd = random.Random(f"us{d}")
    today = datetime.now(IST).date()
    rows = []
    syms = _demo_syms("US")
    for u in rnd.sample(syms, 6) + ([syms[0]] if d == _next_working(today + timedelta(days=3)) else []):
        est = round(rnd.uniform(0.2, 4.0), 2)
        past = d < today
        act = round(est * rnd.uniform(0.85, 1.2), 2) if past else None
        rows.append({"lastYearRptDt": (d - timedelta(days=364)).strftime("%m/%d/%Y"), "lastYearEPS": f"${est * 0.9:.2f}",
                     "time": rnd.choice(["time-pre-market", "time-after-hours", "time-not-supplied"]), "symbol": u["symbol"][3:],
                     "name": u["name"], "marketCap": f"${rnd.randint(5, 900) * 1_000_000_000:,}", "fiscalQuarterEnding": "Sep/2026",
                     "epsForecast": f"${est:.2f}" if rnd.random() > 0.1 else "", "noOfEsts": str(rnd.randint(2, 30)),
                     **({"eps": f"${act:.2f}" if act >= 0 else f"(${-act:.2f})", "surprise": f"{(act - est) / est * 100:.2f}"} if past else {})})
    rows.append({"time": "time-after-hours", "symbol": "SMLL", "name": "Small Cap Holdings Inc.", "marketCap": "$95,000,000",
                 "fiscalQuarterEnding": "Sep/2026", "epsForecast": "($0.12)", "noOfEsts": "1", "lastYearRptDt": "", "lastYearEPS": "($0.20)"})
    return {"data": {"asOf": d.strftime("%a, %b %d, %Y"), "headers": {}, "rows": rows}}


def _demo_nse(start: date, end: date) -> list[dict]:
    out, syms, today = [], _demo_syms("IN"), datetime.now(IST).date()
    d = start
    while d <= end:
        if d.weekday() < 5:
            rnd = random.Random(f"in{d}")
            pick = rnd.sample(syms, 5) + ([syms[0]] if d == _next_working(today + timedelta(days=2)) else [])
            for u in pick:
                p = rnd.choice(["Financial Results", "Financial Results", "Financial Results/Dividend", "Dividend", "Fund Raising", "Bonus"])
                out.append({"symbol": u["symbol"], "company": u["name"], "purpose": p,
                            "bm_desc": f"To consider and approve the {'Un-audited Financial Results for the quarter ended September 30, 2026' if 'Results' in p else p.lower()}",
                            "date": d.strftime("%d-%b-%Y")})
        d += timedelta(days=1)
    return out


def _demo_nasdaq_econ(d: date) -> dict:
    if d.weekday() >= 5:
        return {"data": {"rows": []}}
    rnd = random.Random(f"ec{d}")
    past = d < datetime.now(IST).date()
    us_pool = [("13:30", "CPI (YoY)", "3.1%"), ("13:30", "Core CPI (MoM)", "0.3%"), ("13:30", "Initial Jobless Claims", "221K"),
               ("15:00", "ISM Manufacturing PMI", "49.2"), ("13:30", "Retail Sales (MoM)", "0.4%"), ("15:30", "Crude Oil Inventories", "-1.2M"),
               ("15:00", "CB Consumer Confidence", "101.3"), ("18:00", "10-Year Note Auction", "4.21%")]
    in_pool = [("10:30", "Bank Loan Growth", "11.2%"), ("11:30", "FX Reserves, USD", "689.5B"), ("05:00", "HSBC Manufacturing PMI", "57.4"),
               ("05:00", "HSBC Services PMI", "58.9")]
    rows = []
    for country, pool in (("United States", us_pool), ("India", in_pool)):
        for t, name, prev in rnd.sample(pool, 3 if country == "United States" else 1):
            f = number(prev)
            unit = re.sub(r"[-\d.,]", "", prev)
            fc = f"{f * rnd.uniform(0.95, 1.05):.1f}{unit}"
            act = f"{f * rnd.uniform(0.9, 1.1):.1f}{unit}" if past else "&nbsp;"
            rows.append({"gmt": t, "country": country, "eventName": name, "actual": act, "consensus": fc, "previous": prev,
                         "description": f"{name} — demo description."})
    rows.append({"gmt": "All Day", "country": "Japan", "eventName": "Bank Holiday", "actual": "&nbsp;", "consensus": "&nbsp;", "previous": "&nbsp;"})
    return {"data": {"rows": rows}}
