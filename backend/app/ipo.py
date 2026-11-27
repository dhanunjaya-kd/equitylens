"""IPO research: India first. Every figure comes from the source itself; nothing is estimated.

Sources (all public, no keys)
  NSE   api/ipo-current-issue                 issues open for bidding now (price band, dates, bids so far)
  NSE   api/all-upcoming-issues?category=ipo  issues announced but not open yet
  NSE   api/public-past-issues                closed and listed issues (issue price, listing date)
  NSE   api/ipo-active-category?symbol=       bids by investor category (QIB / NII / Retail ...) for one issue
  NSE   api/ipo-detail?symbol=&series=        the issue's own facts and documents (as NSE lists them)
  SEBI  draft offer documents filed with SEBI (DRHP): companies that have applied to list
  Yahoo daily prices of listed IPOs (listing day and since), the same feed the rest of the app uses

Rules
  * The latest raw answer of every source is saved in data/ipo_raw/, and each source reports which of the
    fields it is expected to carry it actually carried. That is the source check: if NSE changes a format,
    the IPO page says which field went missing instead of showing a wrong number.
  * Subscription "times" is shown only when it agrees with bids ÷ shares offered (within 2%), or is worked
    out from those two NSE figures when NSE gives no times. A row that fails the check is left out.
  * NSE's issue size is shown in NSE's own words: its unit is not always stated, so it is never converted.
  * Listing performance is measured only when NSE gives one final issue price (not a range) and the first
    price bar is within 3 days of the listing date.
"""
from __future__ import annotations

import html as htmllib
import json
import re
import threading
import time
from datetime import date, datetime, timedelta
from typing import Any, Optional

import requests

from . import calendars, config, flows, store

IST = calendars.IST
NSE = "https://www.nseindia.com"
REFERER = {"Referer": "https://www.nseindia.com/market-data/all-upcoming-issues-ipo"}
SEBI_DRHP = "https://www.sebi.gov.in/sebiweb/home/HomeAction.do?doListing=yes&sid=3&ssid=15&smid=10"
SEBI_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36",
           "Accept": "text/html,application/xhtml+xml"}
RAW_DIR = config.DATA_DIR / "ipo_raw"

# id -> (label, url, params, fields expected in a row)
SOURCES = {
    "current": ("NSE · open issues", f"{NSE}/api/ipo-current-issue", None,
                ["symbol", "company", "start", "end", "price", "bids"]),
    "upcoming": ("NSE · upcoming issues", f"{NSE}/api/all-upcoming-issues", {"category": "ipo"},
                 ["symbol", "company", "start", "end", "price"]),
    "past": ("NSE · past issues", f"{NSE}/api/public-past-issues", None,
             ["symbol", "company", "listing", "price"]),
}
TTL = {"current": 5 * 60, "upcoming": 30 * 60, "past": 6 * 3600, "drhp": 6 * 3600, "detail": 5 * 60, "bars": 6 * 3600}
LISTED_DAYS = 120          # "recently listed" window
LISTED_MAX = 40            # price lookups per refresh
_lock = threading.Lock()

# every way NSE has been seen to name a field; the first one present wins
KEYS = {
    "symbol": ("symbol",),
    "company": ("companyName", "company", "companyname", "name", "issuerName"),
    "series": ("series",),
    "start": ("issueStartDate", "startDate", "bidStartDate", "openDate", "issueOpenDate"),
    "end": ("issueEndDate", "endDate", "bidEndDate", "closeDate", "issueCloseDate"),
    "listing": ("listingDate", "dateOfListing", "listing_date"),
    "price": ("issuePrice", "priceRange", "priceBand", "price", "offerPrice"),
    "size": ("issueSize", "issue_size", "issueAmount"),
    "status": ("status", "issueStatus"),
    "offered": ("noOfSharesOffered", "sharesOffered", "noOfShareOffered"),
    "bids": ("noOfsharesBid", "noOfSharesBid", "sharesBid", "noOfSharesBidFor"),
    "times": ("noOfTime", "noOfTimes", "noOfTotalMeant", "timesSubscribed", "subscription"),
    "kind": ("securityType", "issueType", "category", "type", "isSme"),
}


class IpoError(Exception):
    pass


# ------------------------------------------------------------------ small helpers
def _norm(k: str) -> str:
    return re.sub(r"[\s_\-]", "", str(k)).lower()


def pick(row: dict, field: str) -> Any:
    low = {_norm(k): v for k, v in (row or {}).items()}
    for k in KEYS[field]:
        v = low.get(_norm(k))
        if v not in (None, "", "-", "NA", "N.A.", "null"):
            return v
    return None


def num(v) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = re.sub(r"(?i)rs\.?|₹|inr|,", "", str(v)).strip()
    try:
        return float(s)
    except ValueError:
        return None


def nse_date(v) -> Optional[date]:
    return calendars._nse_date(str(v)) if v else None


def price_band(v) -> tuple[Optional[float], Optional[float]]:
    """'Rs.95 to Rs.100' / '95-100' / '100' / 100 -> (low, high). Anything else -> (None, None)."""
    if v is None:
        return None, None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v), float(v)
    s = re.sub(r"(?i)rs\.?|₹|inr|per\s+(equity\s+)?share|/-", " ", str(v).replace(",", ""))
    nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", s)]
    if len(nums) == 1:
        return nums[0], nums[0]
    if len(nums) == 2 and nums[0] <= nums[1] and re.search(r"(?i)\bto\b|-|–", s):
        return nums[0], nums[1]
    return None, None


def rows_of(js) -> list[dict]:
    if isinstance(js, list):
        return [r for r in js if isinstance(r, dict)]
    if isinstance(js, dict):
        for k in ("data", "dataList", "rows", "issues", "result"):
            if isinstance(js.get(k), list):
                return [r for r in js[k] if isinstance(r, dict)]
    return []


def check_times(offered: Optional[float], bids: Optional[float], times: Optional[float]) -> tuple[Optional[float], str]:
    """(times to show, how it was checked). None when the figures disagree or are missing."""
    if offered and offered > 0 and bids is not None and bids >= 0:
        calc = bids / offered
        if times is None:
            return round(calc, 2), "worked out: bids ÷ shares offered"
        if abs(calc - times) <= max(0.02 * max(times, calc), 0.01):
            return round(times, 2), "NSE figure, agrees with bids ÷ shares offered"
        return None, f"left out: NSE says {times:g}x but bids ÷ shares offered is {calc:.2f}x"
    if times is not None:
        return None, "left out: NSE gave times without the shares offered and bid to check it"
    return None, "not published yet"


def is_sme(row: dict, series: Optional[str]) -> bool:
    if (series or "").upper() in ("SM", "ST", "SZ"):
        return True
    k = pick(row, "kind")
    return k is True or (isinstance(k, str) and "sme" in k.lower())


# ------------------------------------------------------------------ normalising one issue row
def issue(row: dict) -> Optional[dict]:
    name = pick(row, "company")
    if not name:
        return None
    sym = (pick(row, "symbol") or "").strip().upper() or None
    series = (pick(row, "series") or "").strip().upper() or None
    lo, hi = price_band(pick(row, "price"))
    start, end, listing = nse_date(pick(row, "start")), nse_date(pick(row, "end")), nse_date(pick(row, "listing"))
    offered, bids, times = num(pick(row, "offered")), num(pick(row, "bids")), num(pick(row, "times"))
    shown, how = check_times(offered, bids, times)
    return {
        "symbol": sym, "series": series, "company": htmllib.unescape(str(name)).strip(),
        "sme": is_sme(row, series),
        "price_text": str(pick(row, "price")) if pick(row, "price") is not None else None,
        "band_low": lo, "band_high": hi, "final_price": lo if lo is not None and lo == hi else None,
        "size_text": str(pick(row, "size")) if pick(row, "size") is not None else None,
        "start": start.isoformat() if start else None, "end": end.isoformat() if end else None,
        "listing": listing.isoformat() if listing else None,
        "status": pick(row, "status"),
        "shares_offered": offered, "shares_bid": bids, "times": shown, "times_check": how,
    }


def field_report(rows: list[dict], expected: list[str]) -> dict:
    found = {f: any(pick(r, f) is not None for r in rows) for f in expected}
    return {"found": [f for f, v in found.items() if v], "missing": [f for f, v in found.items() if not v] if rows else []}


# ------------------------------------------------------------------ fetching (cached, raw copy kept)
def _save_raw(name: str, text: str) -> None:
    try:
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        (RAW_DIR / name).write_text(text, encoding="utf-8")
    except OSError:
        pass


def _nse_json(sid: str, url: str, params: Optional[dict], raw_name: str):
    text = flows._nse_text(url, params, headers=REFERER)
    if text is None:
        raise IpoError("NSE has nothing published here (404)")
    _save_raw(raw_name, text)
    try:
        return json.loads(text)
    except ValueError as e:
        raise IpoError("NSE answered with something that is not JSON (format changed?)") from e


def _cached(key: str, ttl: float, refresh: bool, fn):
    hit = store.get_company(key)
    if hit and not refresh and time.time() - hit[0] < ttl:
        return hit[1]
    try:
        val = fn()
    except Exception as e:  # noqa: BLE001 - a failing source must not break the page
        if hit:      # keep showing the last good copy, marked with its time
            return dict(hit[1], stale=True, error=str(e))
        raise
    store.put_company(key, dict(val, fetched=time.time()))
    return dict(val, fetched=time.time())


def _list(sid: str, refresh: bool) -> dict:
    label, url, params, expected = SOURCES[sid]

    def fetch():
        js = _nse_json(sid, url, params, f"nse_{sid}.json")
        rows = rows_of(js)
        items = [x for x in (issue(r) for r in rows) if x]
        return {"items": items, "rows": len(rows), **field_report(rows, expected)}
    return _cached(f"IPO::{sid}", TTL[sid], refresh, fetch)


def parse_sebi_drhp(page: str) -> list[dict]:
    """SEBI's listing table: one row per filing — date cell, then a link whose text is the filing title."""
    out = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", page, re.S | re.I):
        tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S | re.I)
        if len(tds) < 2:
            continue
        d_txt = re.sub(r"<[^>]+>", "", tds[0]).strip()
        try:
            d = datetime.strptime(d_txt, "%b %d, %Y").date()
        except ValueError:
            continue
        a = re.search(r"<a[^>]+href=['\"]([^'\"]+)['\"][^>]*>(.*?)</a>", tds[1], re.S | re.I)
        if not a:
            continue
        title = htmllib.unescape(re.sub(r"<[^>]+>", "", a.group(2))).strip()
        if not title:
            continue
        href = a.group(1)
        if href.startswith("/"):
            href = "https://www.sebi.gov.in" + href
        parts = re.split(r"\s+[-–]\s+", title)
        company = (" - ".join(parts[:-1]) if len(parts) > 1 and re.search(r"(?i)draft|drhp|prospectus|addendum|offer document", parts[-1])
                   else title).strip()
        out.append({"date": d.isoformat(), "title": title, "company": company, "url": href,
                    "sme": bool(re.search(r"\bsme\b", title, re.I))})
    return out


def _drhp(refresh: bool) -> dict:
    def fetch():
        r = requests.get(SEBI_DRHP, headers=SEBI_UA, timeout=config.REQUEST_TIMEOUT)
        if r.status_code != 200:
            raise IpoError(f"SEBI answered {r.status_code}")
        _save_raw("sebi_drhp.html", r.text)
        items = parse_sebi_drhp(r.text)
        if not items:
            raise IpoError("SEBI's page had no filing rows in the expected table (format changed?)")
        return {"items": items, "rows": len(items), "found": ["date", "title", "url"], "missing": []}
    return _cached("IPO::drhp", TTL["drhp"], refresh, fetch)


# ------------------------------------------------------------------ listing performance (measured)
def listing_move(bars: list[dict], listing: str, final_price: float, today: Optional[date] = None) -> Optional[dict]:
    """Listing-day open / close and the latest close against the issue price. None if the first bar is not
    within 3 days of the listing date (then the price series is not this listing)."""
    if not bars or not final_price:
        return None
    ld = date.fromisoformat(listing)
    first = next((b for b in bars if b["t"] >= listing), None)
    if not first or (date.fromisoformat(first["t"]) - ld).days > 3:
        return None
    last = bars[-1]
    pct = lambda p: round((p / final_price - 1) * 100, 2) if p else None   # noqa: E731
    return {"first_day": first["t"], "list_open": first.get("o"), "list_close": first["c"],
            "open_vs_issue": pct(first.get("o")), "close_vs_issue": pct(first["c"]),
            "last_day": last["t"], "last_close": last["c"], "now_vs_issue": pct(last["c"]),
            "sessions": sum(1 for b in bars if b["t"] >= listing)}


def _bars(symbol: str) -> list[dict]:
    from . import technicals
    key = f"IPO::BARS::{symbol}"
    hit = store.get_company(key)
    if hit and time.time() - hit[0] < TTL["bars"]:
        return hit[1]["bars"]
    bars = technicals._yahoo(f"{symbol}.NS", "1y")
    store.put_company(key, {"bars": bars})
    return bars


def recently_listed(past: list[dict], today: Optional[date] = None) -> list[dict]:
    today = today or datetime.now(IST).date()
    cut = (today - timedelta(days=LISTED_DAYS)).isoformat()
    rows = sorted([x for x in past if x.get("listing") and cut <= x["listing"] <= today.isoformat()],
                  key=lambda x: x["listing"], reverse=True)
    out = []
    for i, x in enumerate(rows):
        x = dict(x, perf=None, perf_note=None)
        if not x.get("symbol"):
            x["perf_note"] = "no NSE symbol"
        elif x.get("final_price") is None:
            x["perf_note"] = "NSE lists a price range, not one final issue price"
        elif i >= LISTED_MAX:
            x["perf_note"] = "not looked up (older than the newest 40)"
        else:
            try:
                x["perf"] = listing_move(_bars(x["symbol"]), x["listing"], x["final_price"])
                if x["perf"] is None:
                    x["perf_note"] = "first price bar does not match the listing date"
            except Exception as e:  # noqa: BLE001
                x["perf_note"] = f"prices not available ({str(e)[:60]})"
        out.append(x)
    return out


# ------------------------------------------------------------------ page data
def _source_row(sid: str, label: str, url: str, res: Optional[dict], err: Optional[str]) -> dict:
    return {"id": sid, "name": label, "url": url, "ok": res is not None and not res.get("stale"),
            "stale": bool(res and res.get("stale")), "rows": (res or {}).get("rows"),
            "found": (res or {}).get("found", []), "missing": (res or {}).get("missing", []),
            "fetched": (res or {}).get("fetched"), "error": err or (res or {}).get("error")}


def india(refresh: bool = False) -> dict:
    if config.DEMO:
        return {"open": [], "upcoming": [], "listed": [], "drhp": [], "sources": [], "demo": True}
    got, sources = {}, []
    for sid in ("current", "upcoming", "past"):
        label, url, _, _ = SOURCES[sid]
        try:
            got[sid] = _list(sid, refresh)
            sources.append(_source_row(sid, label, url, got[sid], None))
        except Exception as e:  # noqa: BLE001
            got[sid] = None
            sources.append(_source_row(sid, label, url, None, str(e)))
    try:
        got["drhp"] = _drhp(refresh)
        sources.append(_source_row("drhp", "SEBI · draft offer documents (DRHP)", SEBI_DRHP, got["drhp"], None))
    except Exception as e:  # noqa: BLE001
        got["drhp"] = None
        sources.append(_source_row("drhp", "SEBI · draft offer documents (DRHP)", SEBI_DRHP, None, str(e)))

    today = datetime.now(IST).date().isoformat()
    cur = (got["current"] or {}).get("items", [])
    up = [x for x in (got["upcoming"] or {}).get("items", []) if not x.get("start") or x["start"] > today]
    open_syms = {x["symbol"] for x in cur if x.get("symbol")}
    up = [x for x in up if x.get("symbol") not in open_syms]
    with _lock:
        listed = recently_listed((got["past"] or {}).get("items", []))
    drhp = (got["drhp"] or {}).get("items", [])[:150]
    return {"open": sorted(cur, key=lambda x: x.get("end") or ""), "upcoming": sorted(up, key=lambda x: x.get("start") or "9"),
            "listed": listed, "drhp": drhp, "sources": sources, "today": today}


# ------------------------------------------------------------------ one issue: categories + NSE's facts
def categories(js) -> list[dict]:
    out = []
    for r in rows_of(js):
        cat = r.get("category") or r.get("categoryName")
        if not cat:
            continue
        offered, bids, times = num(pick(r, "offered")), num(pick(r, "bids")), num(pick(r, "times"))
        shown, how = check_times(offered, bids, times)
        out.append({"category": htmllib.unescape(str(cat)).strip(), "shares_offered": offered, "shares_bid": bids,
                    "times": shown, "check": how, "total": bool(re.match(r"(?i)\s*total", str(cat)))})
    return out


def facts(js) -> tuple[list[dict], list[dict]]:
    """Every title/value pair NSE gives for the issue, as NSE words it, plus any document links."""
    pairs, docs, seen = [], [], set()

    def walk(o, label=None):
        if isinstance(o, dict):
            t = o.get("title") or o.get("label") or o.get("key")
            v = o.get("value") if "value" in o else o.get("val")
            if isinstance(t, str) and isinstance(v, (str, int, float)) and str(v).strip():
                k = (t.strip(), str(v).strip())
                if k not in seen:
                    seen.add(k)
                    clean = htmllib.unescape(re.sub(r"<[^>]+>", " ", str(v))).strip()
                    if re.match(r"https?://\S+$", clean):
                        docs.append({"title": t.strip(), "url": clean})
                    else:
                        pairs.append({"k": htmllib.unescape(t.strip()), "v": re.sub(r"\s+", " ", clean)})
            for kk, vv in o.items():
                if isinstance(vv, str) and re.match(r"https?://\S+\.(pdf|zip)$", vv.strip(), re.I):
                    docs.append({"title": str(o.get("title") or kk), "url": vv.strip()})
                else:
                    walk(vv, kk)
        elif isinstance(o, list):
            for x in o:
                walk(x, label)
    walk(js)
    uniq = {d["url"]: d for d in docs}
    return pairs, list(uniq.values())


def detail(symbol: str, series: str = "EQ", refresh: bool = False) -> dict:
    sym = re.sub(r"[^A-Z0-9&\-]", "", symbol.upper())
    if not sym:
        raise IpoError("No symbol")
    sources = []

    def fcat():
        js = _nse_json("cat", f"{NSE}/api/ipo-active-category", {"symbol": sym}, f"nse_category_{sym}.json")
        rows = categories(js)
        upd = js.get("updateTime") or js.get("timestamp") if isinstance(js, dict) else None
        return {"rows": rows, "updated": upd, "found": ["category"] if rows else [], "missing": [] if rows else ["category"]}

    def fdet():
        js = _nse_json("det", f"{NSE}/api/ipo-detail", {"symbol": sym, "series": series or "EQ"}, f"nse_detail_{sym}.json")
        pairs, docs = facts(js)
        return {"facts": pairs, "docs": docs, "rows": len(pairs), "found": ["facts"] if pairs else [], "missing": [] if pairs else ["facts"]}

    out: dict = {"symbol": sym, "series": series}
    for sid, label, url, fn in (("cat", "NSE · bids by category", f"{NSE}/api/ipo-active-category?symbol={sym}", fcat),
                                ("det", "NSE · issue details", f"{NSE}/api/ipo-detail?symbol={sym}&series={series}", fdet)):
        try:
            res = _cached(f"IPO::{sid}::{sym}", TTL["detail"], refresh, fn)
            out[sid] = res
            sources.append(_source_row(sid, label, url, res, None))
        except Exception as e:  # noqa: BLE001
            out[sid] = None
            sources.append(_source_row(sid, label, url, None, str(e)))
    return {"symbol": sym, "series": series,
            "categories": (out["cat"] or {}).get("rows", []), "updated": (out["cat"] or {}).get("updated"),
            "facts": (out["det"] or {}).get("facts", []), "docs": (out["det"] or {}).get("docs", []),
            "sources": sources}
