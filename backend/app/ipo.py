"""IPO research: India first. Every figure comes from the source itself or is plain arithmetic on two of its
figures (said so where shown); nothing is estimated.

Sources (all public, no keys)
  NSE   api/ipo-current-issue                 issues open for bidding now (price band, dates, bids so far)
  NSE   api/all-upcoming-issues?category=ipo  issues announced but not open yet
  NSE   api/public-past-issues                closed and listed issues (price range, final issue price, listing date)
  NSE   api/ipo-detail?symbol=&series=        one issue: bids and applications by investor category, shares reserved
                                              per category, bids at each price, NSE's issue facts and documents
  SEBI  draft offer documents filed with SEBI (DRHP): companies that have applied to list
  Yahoo daily prices of listed IPOs (listing day and since), the same feed the rest of the app uses

Checks (a figure that fails is left out, with the reason)
  * subscription times = shares bid ÷ shares offered, and must agree with NSE's own times within 2%
  * the main investor categories must add up to NSE's total bids
  * bids at each price must add up to NSE's total bids (within 1%)
  * fresh issue + offer for sale must add up to the issue size NSE states
  * issue size in ₹ = issue shares × upper price, only when NSE's issue size is confirmed to be a share count
  * a listing move is measured only with one final issue price and a first price bar on the listing date
The latest raw answer of every source is saved in data/ipo_raw/ and each source reports which expected fields
it carried (source check).
"""
from __future__ import annotations

import html as htmllib
import json
import re
import statistics
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
    "current": ("NSE · open issues", f"{NSE}/api/ipo-current-issue", None, ["symbol", "company", "start", "end", "range", "bids"]),
    "upcoming": ("NSE · upcoming issues", f"{NSE}/api/all-upcoming-issues", {"category": "ipo"}, ["symbol", "company", "start", "end", "range"]),
    "past": ("NSE · past issues", f"{NSE}/api/public-past-issues", None, ["symbol", "company", "listing", "range", "final"]),
}
TTL = {"current": 5 * 60, "upcoming": 30 * 60, "past": 6 * 3600, "drhp": 6 * 3600, "detail": 5 * 60, "bars": 6 * 3600}
LISTED_DAYS = 120          # "recently listed" window
LISTED_MAX = 60            # price lookups per refresh
NOT_COMPANY = ("DEBT", "INVIT", "REIT")     # NSE's past list also carries bonds and trusts
_lock = threading.Lock()

# every way NSE names a field; the first one present wins
KEYS = {
    "symbol": ("symbol",),
    "company": ("companyName", "company", "issuerName"),
    "series": ("series",),
    "start": ("issueStartDate", "ipoStartDate", "startDate", "bidStartDate"),
    "end": ("issueEndDate", "ipoEndDate", "endDate", "bidEndDate"),
    "listing": ("listingDate", "dateOfListing"),
    "range": ("priceRange", "priceBand", "issuePrice"),
    "final": ("issuePrice", "offerPrice"),
    "size": ("issueSize",),
    "status": ("status", "issueStatus"),
    "offered": ("noOfSharesOffered", "noOfShareOffered", "sharesOffered"),
    "bids": ("noOfsharesBid", "noOfSharesBid", "noOfshareBid", "sharesBid"),
    "times": ("noOfTime", "noOfTimes", "noOfTotalMeant", "noOfTimesIssueSubscribed"),
    "kind": ("securityType", "segment", "issueType"),
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
            return v.strip() if isinstance(v, str) else v
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
    if offered == 0:
        return None, "NSE does not publish the shares reserved for this category"
    if times is not None:
        return None, "left out: NSE gave times without the shares offered and bid to check it"
    return None, "not published yet"


def is_sme(row: dict, series: Optional[str]) -> bool:
    if (series or "").upper() in ("SM", "ST", "SZ", "SME"):
        return True
    k = pick(row, "kind")
    return isinstance(k, str) and "sme" in k.lower()


def to_cr(shares: Optional[float], price: Optional[float]) -> Optional[float]:
    return round(shares * price / 1e7, 2) if shares and price else None


# ------------------------------------------------------------------ normalising one issue row
def issue(row: dict) -> Optional[dict]:
    name = pick(row, "company")
    if not name:
        return None
    kind = pick(row, "kind")
    if isinstance(kind, str) and kind.strip().upper() in NOT_COMPANY:
        return None
    sym = (pick(row, "symbol") or "").strip().upper() or None
    series = (pick(row, "series") or "").strip().upper() or None
    lo, hi = price_band(pick(row, "range"))
    flo, fhi = price_band(pick(row, "final"))
    final = flo if flo is not None and flo == fhi else None
    final_note = None
    if final is not None and lo is not None and not (lo <= final <= hi):
        final, final_note = None, f"NSE's issue price ({flo:g}) lies outside its own price range"
    start, end, listing = nse_date(pick(row, "start")), nse_date(pick(row, "end")), nse_date(pick(row, "listing"))
    offered, bids, times = num(pick(row, "offered")), num(pick(row, "bids")), num(pick(row, "times"))
    shown, how = check_times(offered, bids, times)
    size = num(pick(row, "size"))
    # NSE's issueSize is a share count when it equals the shares offered in the same row (open issues)
    size_ok = bool(size and offered and abs(size - offered) < 1)
    return {
        "symbol": sym, "series": series, "company": htmllib.unescape(str(name)).strip(),
        "sme": is_sme(row, series),
        "range_text": str(pick(row, "range")) if pick(row, "range") is not None else None,
        "band_low": lo, "band_high": hi, "final_price": final, "final_note": final_note,
        "issue_shares": size,
        "size_cr": to_cr(size, hi) if size_ok else None,
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


def _nse_json(url: str, params: Optional[dict], raw_name: str):
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
        rows = rows_of(_nse_json(url, params, f"nse_{sid}.json"))
        return {"items": [x for x in (issue(r) for r in rows) if x], "count": len(rows), **field_report(rows, expected)}
    return _cached(f"IPO::{sid}::v2", TTL[sid], refresh, fetch)


# ------------------------------------------------------------------ SEBI: draft offer documents
def parse_sebi_drhp(page: str) -> list[dict]:
    """SEBI's listing table. Each row: a date cell, then a link whose title holds the filing name (SEBI leaves
    that last cell unclosed, so rows are read whole). An abridged-prospectus PDF link is kept when present."""
    out = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", page, re.S | re.I):
        dm = re.search(r"<td[^>]*>\s*([A-Z][a-z]{2} \d{1,2}, \d{4})\s*</td>", tr)
        am = re.search(r"<a\s+href=\"([^\"]+)\"[^>]*?title=\"([^\"]*)\"", tr, re.S | re.I)
        if not dm or not am:
            continue
        try:
            d = datetime.strptime(dm.group(1), "%b %d, %Y").date()
        except ValueError:
            continue
        title = htmllib.unescape(re.sub(r"<[^>]+>", "", re.split(r"(?i)<br", am.group(2))[0])).strip()
        if not title:
            continue
        href = am.group(1)
        if href.startswith("/"):
            href = "https://www.sebi.gov.in" + href
        pdf = re.search(r"href=\s*'([^']+\.pdf)'", tr, re.I)
        m = re.match(r"(.*?)\s*[-_–]\s*(?=(?:addendum|draft|drhp|updated|abridged|corrigendum))", title, re.I)
        company = (m.group(1) if m else title).strip(" -_")
        kind = "Addendum" if re.search(r"(?i)addendum|corrigendum", title) else "DRHP" if re.search(r"(?i)drhp|draft", title) else "Filing"
        out.append({"date": d.isoformat(), "title": title, "company": company, "url": href, "kind": kind,
                    "abridged": pdf.group(1).replace(" ", "%20") if pdf else None,
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
        return {"items": items, "count": len(items), "found": ["date", "title", "url"], "missing": []}
    return _cached("IPO::drhp::v2", TTL["drhp"], refresh, fetch)


# ------------------------------------------------------------------ listing performance (measured)
def listing_move(bars: list[dict], listing: str, final_price: float) -> Optional[dict]:
    """Listing-day open / close and the latest close against the issue price. None if the first bar is not
    within 3 days of the listing date (then the price series is not this listing)."""
    if not bars or not final_price:
        return None
    ld = date.fromisoformat(listing)
    first = next((b for b in bars if b["t"] >= listing), None)
    if not first or (date.fromisoformat(first["t"]) - ld).days > 3:
        return None
    last = bars[-1]
    after = [b for b in bars if b["t"] >= listing]
    pct = lambda p: round((p / final_price - 1) * 100, 2) if p else None   # noqa: E731
    return {"first_day": first["t"], "list_open": first.get("o"), "list_close": first["c"],
            "open_vs_issue": pct(first.get("o")), "close_vs_issue": pct(first["c"]),
            "last_day": last["t"], "last_close": last["c"], "now_vs_issue": pct(last["c"]),
            "high_vs_issue": pct(max(b.get("h") or b["c"] for b in after)), "low_vs_issue": pct(min(b.get("l") or b["c"] for b in after)),
            "sessions": len(after)}


def _bars(symbol: str) -> list[dict]:
    from . import technicals
    key = f"IPO::BARS::{symbol}"
    hit = store.get_company(key)
    if hit and time.time() - hit[0] < TTL["bars"]:
        return hit[1]["bars"]
    bars = technicals._yahoo(f"{symbol}.NS", "1y")
    store.put_company(key, {"bars": bars})
    return bars


def recently_listed(past: list[dict], today: Optional[date] = None, prices=None) -> list[dict]:
    today = today or datetime.now(IST).date()
    prices = prices or _bars
    cut = (today - timedelta(days=LISTED_DAYS)).isoformat()
    def fresh_listing(x):     # a listing more than 30 days after the issue closed is not this IPO (bonds, migrations)
        return not x.get("end") or (date.fromisoformat(x["listing"]) - date.fromisoformat(x["end"])).days <= 30
    rows = sorted([x for x in past if x.get("listing") and cut <= x["listing"] <= today.isoformat() and fresh_listing(x)],
                  key=lambda x: x["listing"], reverse=True)
    out = []
    for i, x in enumerate(rows):
        x = dict(x, perf=None, perf_note=None)
        if not x.get("symbol"):
            x["perf_note"] = "no NSE symbol"
        elif x.get("final_price") is None:
            x["perf_note"] = x.get("final_note") or "NSE gives no single final issue price"
        elif i >= LISTED_MAX:
            x["perf_note"] = f"not looked up (older than the newest {LISTED_MAX})"
        else:
            try:
                x["perf"] = listing_move(prices(x["symbol"]), x["listing"], x["final_price"])
                if x["perf"] is None:
                    x["perf_note"] = "no price on the listing day yet" if x["listing"] >= today.isoformat() else "first price bar does not match the listing date"
            except Exception:  # noqa: BLE001
                x["perf_note"] = "daily prices not available for this symbol"
        out.append(x)
    return out


def listed_stats(rows: list[dict]) -> dict:
    """Plain counts over the measured listings only (each row carries its own source)."""
    def one(sel):
        m = [x["perf"] for x in rows if sel(x) and x.get("perf")]
        if not m:
            return {"n": 0}
        cl = [p["close_vs_issue"] for p in m if p.get("close_vs_issue") is not None]
        now = [p["now_vs_issue"] for p in m if p.get("now_vs_issue") is not None]
        return {"n": len(m),
                "above_listing": sum(1 for v in cl if v > 0), "median_listing": round(statistics.median(cl), 2) if cl else None,
                "above_now": sum(1 for v in now if v > 0), "median_now": round(statistics.median(now), 2) if now else None}
    return {"main": one(lambda x: not x.get("sme")), "sme": one(lambda x: x.get("sme"))}


# ------------------------------------------------------------------ page data
def _source_row(sid: str, label: str, url: str, res: Optional[dict], err: Optional[str]) -> dict:
    return {"id": sid, "name": label, "url": url, "ok": res is not None and not res.get("stale"),
            "stale": bool(res and res.get("stale")), "count": (res or {}).get("count"),
            "found": (res or {}).get("found", []), "missing": (res or {}).get("missing", []),
            "fetched": (res or {}).get("fetched"), "error": err or (res or {}).get("error")}


def india(refresh: bool = False) -> dict:
    if config.DEMO:
        return {"open": [], "upcoming": [], "listed": [], "drhp": [], "sources": [], "stats": listed_stats([]), "demo": True}
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
        sources.append(_source_row("drhp", "SEBI · draft offer documents", SEBI_DRHP, got["drhp"], None))
    except Exception as e:  # noqa: BLE001
        got["drhp"] = None
        sources.append(_source_row("drhp", "SEBI · draft offer documents", SEBI_DRHP, None, str(e)))

    today = datetime.now(IST).date().isoformat()
    cur = (got["current"] or {}).get("items", [])
    up = [x for x in (got["upcoming"] or {}).get("items", []) if not x.get("start") or x["start"] > today]
    open_syms = {x["symbol"] for x in cur if x.get("symbol")}
    up = [x for x in up if x.get("symbol") not in open_syms]
    with _lock:
        listed = recently_listed((got["past"] or {}).get("items", []))
    drhp = (got["drhp"] or {}).get("items", [])[:150]
    return {"open": sorted(cur, key=lambda x: x.get("end") or ""), "upcoming": sorted(up, key=lambda x: x.get("start") or "9"),
            "listed": listed, "stats": listed_stats(listed), "drhp": drhp, "sources": sources, "today": today}


# ------------------------------------------------------------------ one issue
_TOP = re.compile(r"^\d+(\.\d+)?$")          # "1", "2", "2.1" — a category, not a sub-category "1(a)"
_MAIN = re.compile(r"^\d+$")                 # top-level categories add up to the total
DOC_TITLES = re.compile(r"(?i)red herring|prospectus|ratios|basis of issue|anchor|addendum|corrigendum|security parameters|application forms")
SHORT_FACTS = ("Issue Type", "Issue Period", "Price Range", "Lot Size", "Face Value", "Tick Size", "Book Running Lead Managers",
               "Name of the Registrar", "Sponsor Bank", "IPO Market Timings")


def _clean(v) -> str:
    return re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", str(v)))).strip().strip('"').strip()


def _shares_in(text: str, what: str) -> Optional[float]:
    m = re.search(what + r"[^.;]*?([\d,]{4,})\s*(?:equity\s+)?shares", text or "", re.I)
    return num(m.group(1)) if m else None


def composition(size_text: str, total: Optional[float]) -> dict:
    """Fresh issue, offer for sale and market-maker shares as NSE's issue-size text states them, kept only when
    fresh + OFS adds up to the issue size."""
    t = size_text or ""
    fresh = _shares_in(t, r"fresh\s+issue\s+of")
    ofs = _shares_in(t, r"offer\s+for\s+sale\s+of")
    mm = _shares_in(t, r"market\s+maker\s+portion\s+of")
    out = {"fresh": fresh, "ofs": ofs, "market_maker": mm, "ok": False, "note": None}
    parts = (fresh or 0) + (ofs or 0)
    if not parts:
        out["note"] = "NSE's issue-size text gives no share split"
    elif total and abs(parts - total) <= max(1, 0.005 * total):
        out["ok"] = True
        out["fresh_pct"] = round((fresh or 0) / parts * 100, 1)
    else:
        out["note"] = (f"left out: fresh + OFS ({parts:,.0f}) does not match the issue size ({total:,.0f})" if total
                       else "no issue size to check against")
    return out


def categories(active: list[dict], bids: list[dict]) -> dict:
    """Merge NSE's two category tables by serial number: shares reserved and times (activeCat) with shares
    bid and applications (bidDetails). Header rows are skipped."""
    by_sr: dict[str, dict] = {}
    order: list[str] = []

    def key(r):
        sr = r.get("srNo")
        if sr not in (None, ""):
            return str(sr).strip()
        return "TOTAL" if re.match(r"(?i)\s*total", str(r.get("category", ""))) else None

    for src, rows in (("bid", bids), ("act", active)):
        for r in rows or []:
            if not isinstance(r, dict) or num(pick(r, "bids")) is None:
                continue                                  # header row ("No. of shares bid for")
            k = key(r)
            if not k:
                continue
            if k not in by_sr:
                by_sr[k] = {"sr": k, "category": _clean(r.get("category"))}
                order.append(k)
            row = by_sr[k]
            if src == "bid":
                row["shares_bid"] = num(pick(r, "bids"))
                row["applications"] = num(r.get("noofapplication") or r.get("noOfApplication"))
            else:
                row.setdefault("shares_bid", num(pick(r, "bids")))
                row["shares_offered"] = num(pick(r, "offered"))
                row["nse_times"] = num(pick(r, "times"))
    rows = []
    for k in order:
        r = by_sr[k]
        t, how = check_times(r.get("shares_offered"), r.get("shares_bid"), r.get("nse_times"))
        r.update(times=t, check=how, level=0 if k == "TOTAL" or _MAIN.match(k) else 1 if _TOP.match(k) else 2, total=k == "TOTAL")
        rows.append(r)
    total = next((r for r in rows if r["total"]), None)
    main_sum = sum(r.get("shares_bid") or 0 for r in rows if _MAIN.match(r["sr"]))
    adds = bool(total and total.get("shares_bid") is not None and abs(main_sum - total["shares_bid"]) <= 1)
    if adds:
        msg = "main categories add up to NSE's total bids"
    elif total and total.get("shares_bid") is not None:
        msg = f"main categories add up to {main_sum:,.0f}, NSE's total is {total['shares_bid']:,.0f}"
    else:
        msg = "no total row"
    return {"rows": rows, "adds_up": adds, "check": msg}


def demand(graph: dict) -> Optional[dict]:
    """Bids at each price (NSE + BSE): NSE gives lakh shares per price. Kept only if they add up to total bids."""
    if not graph:
        return None
    pts = [(num(p.get("type")), num(p.get("value"))) for p in graph.get("graphData") or [] if isinstance(p, dict)]
    pts = [(p, q) for p, q in pts if p is not None and q is not None]
    total = num(graph.get("TOTAL_BIDS") or graph.get("totalBidRecieved"))
    if not pts or not total:
        return None
    s = sum(q for _, q in pts) * 1e5
    if abs(s - total) > 0.01 * total:
        return {"ok": False, "note": f"left out: bids at each price add up to {s:,.0f}, NSE's total is {total:,.0f}"}
    pts.sort()
    return {"ok": True, "levels": [{"price": p, "shares": round(q * 1e5), "pct": round(q * 1e5 / total * 100, 1)} for p, q in pts],
            "at_top": round(pts[-1][1] * 1e5 / total * 100, 1), "top_price": pts[-1][0],
            "cutoff": num(graph.get("totalBidAtCutOff")), "time": _clean(graph.get("timestamp") or "")}


def parse_detail(js: dict) -> dict:
    js = js or {}
    facts, docs, long_facts = {}, [], []
    for r in rows_of(js.get("issueInfo") or {}):
        t, v = r.get("title"), r.get("value")
        if not t or v in (None, ""):
            continue
        t = _clean(t)
        raw = str(v).strip()
        link = re.search(r"href=\s*['\"]?([^'\" >]+)", raw)
        url = raw if re.match(r"https?://\S+$", raw) else (link.group(1) if link else None)
        if url:
            if DOC_TITLES.search(t):
                docs.append({"title": t, "url": url})
            continue
        val = _clean(raw)
        if t in SHORT_FACTS or len(val) <= 90:
            facts[t] = val
        else:
            long_facts.append({"k": t, "v": val})
    g = js.get("demandGraphALL") or js.get("demandGraph") or {}
    total_bid, total_sh = num(g.get("TOTAL_BIDS") or g.get("totalBidRecieved")), num(g.get("totalIssueSize"))
    lo, hi = price_band(facts.get("Price Range"))
    lot_m = re.search(r"[\d,]+", facts.get("Lot Size", ""))
    lot = num(lot_m.group(0)) if lot_m else None
    size_text = facts.get("Issue Size") or next((x["v"] for x in long_facts if x["k"] == "Issue Size"), "")
    stated = [n for n in (num(x) for x in re.findall(r"[\d,]{4,}", size_text)) if n]
    size_ok = bool(total_sh and re.search(r"(?i)shares", size_text) and any(abs(n - total_sh) < 1 for n in stated))
    cats = categories(rows_of(js.get("activeCat") or {}), js.get("bidDetails") or [])
    tot = next((r for r in cats["rows"] if r["total"]), {})
    overall, how = check_times(total_sh, total_bid, num(g.get("noOfTimesIssueSubscribed")))
    return {
        "facts": [{"k": k, "v": v} for k, v in facts.items()], "long_facts": long_facts, "docs": docs,
        "band_low": lo, "band_high": hi, "lot": lot, "lot_value": round(lot * hi) if lot and hi else None,
        "issue_shares": total_sh if size_ok else None, "size_text": size_text,
        "size_cr": to_cr(total_sh, hi) if size_ok else None,
        "size_check": "issue shares as NSE's issue-size text states them × upper price" if size_ok else "issue size not confirmed as a share count",
        "composition": composition(size_text, total_sh if size_ok else None),
        "total_bids": total_bid, "times": overall, "times_check": how, "applications": tot.get("applications"),
        "categories": cats, "demand": demand(g),
        "updated": _clean(g.get("timestamp") or "") or None,
    }


def detail(symbol: str, series: str = "EQ", refresh: bool = False) -> dict:
    sym = re.sub(r"[^A-Z0-9&\-]", "", symbol.upper())
    ser = re.sub(r"[^A-Za-z]", "", series or "EQ") or "EQ"
    if not sym:
        raise IpoError("No symbol")
    url = f"{NSE}/api/ipo-detail"
    label, link = "NSE · issue details and bids", f"{url}?symbol={sym}&series={ser}"

    def fetch():
        d = parse_detail(_nse_json(url, {"symbol": sym, "series": ser}, f"nse_detail_{sym}.json"))
        return dict(d, count=len(d["facts"]), found=["facts"] if d["facts"] else [], missing=[] if d["facts"] else ["facts"])
    try:
        res = _cached(f"IPO::detail::v2::{sym}", TTL["detail"], refresh, fetch)
        src = _source_row("detail", label, link, res, None)
    except Exception as e:  # noqa: BLE001
        res, src = None, _source_row("detail", label, link, None, str(e))
    return dict(res or {}, symbol=sym, series=ser, sources=[src], ok=res is not None)
