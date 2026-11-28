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


# ================================================================== 🇺🇸 US IPOs (Nasdaq's public IPO calendar)
# api.nasdaq.com/api/ipo/calendar?date=YYYY-MM  ->  data.priced / data.upcoming.upcomingTable / data.filed / data.withdrawn
# One request per month (the last 4 months and the next one), cached 6 hours; the latest raw answer is saved
# (data/ipo_raw/nasdaq_ipo_YYYY-MM.json). Checks: deal value = shares × IPO price for priced deals (within 1%),
# otherwise the value is left out; first-day and since-listing moves only with one IPO price and a first price bar
# within 3 days of the pricing date (US IPOs usually start trading the day after pricing).
NASDAQ_IPO = "https://api.nasdaq.com/api/ipo/calendar"
US_KEYS = {
    "symbol": ("proposedTickerSymbol", "symbol", "ticker"),
    "company": ("companyName", "company", "name"),
    "exchange": ("proposedExchange", "exchange"),
    "price": ("proposedSharePrice", "sharePrice", "price"),
    "shares": ("sharesOffered", "shares"),
    "value": ("dollarValueOfSharesOffered", "dealSize", "dollarValue"),
    "priced": ("pricedDate",),
    "expected": ("expectedPriceDate", "expectedDate"),
    "filed": ("filedDate",),
    "withdrawn": ("withdrawDate", "withdrawnDate"),
    "deal": ("dealID", "dealId", "id"),
}


def _upick(row: dict, field: str):
    low = {_norm(k): v for k, v in (row or {}).items()}
    for k in US_KEYS[field]:
        v = low.get(_norm(k))
        if v not in (None, "", "-", "N/A", "NA"):
            return v.strip() if isinstance(v, str) else v
    return None


def us_date(v) -> Optional[date]:
    s = str(v or "").strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y", "%b %d, %Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def us_money(v) -> Optional[float]:
    return num(re.sub(r"[$,\s]", "", str(v))) if v not in (None, "") else None


def _section(js: dict, name: str) -> list[dict]:
    d = (js or {}).get("data") or {}
    sec = d.get(name) or {}
    if name == "upcoming" and isinstance(sec, dict):
        sec = sec.get("upcomingTable") or sec
    rows = sec.get("rows") if isinstance(sec, dict) else sec
    return [r for r in rows or [] if isinstance(r, dict)]


def us_issue(row: dict, status: str) -> Optional[dict]:
    name = _upick(row, "company")
    if not name:
        return None
    sym = (_upick(row, "symbol") or "").upper() or None
    lo, hi = price_band(_upick(row, "price"))
    shares, value = us_money(_upick(row, "shares")), us_money(_upick(row, "value"))
    final = lo if status == "priced" and lo is not None and lo == hi else None
    value_note = None
    if status == "priced" and value and shares and final:
        if abs(shares * final - value) > 0.01 * value:
            value, value_note = None, "left out: deal value ≠ shares × IPO price"
    d = {k: us_date(_upick(row, k)) for k in ("priced", "expected", "filed", "withdrawn")}
    return {"deal": str(_upick(row, "deal") or ""), "symbol": sym, "company": htmllib.unescape(str(name)).strip(),
            "exchange": _upick(row, "exchange"), "status": status, "range_text": _upick(row, "price"),
            "band_low": lo, "band_high": hi, "final_price": final, "shares": shares,
            "value_m": round(value / 1e6, 2) if value else None, "value_note": value_note,
            **{k: v.isoformat() if v else None for k, v in d.items()}}


def parse_us_month(js: dict) -> dict:
    out = {}
    for sec, status in (("priced", "priced"), ("upcoming", "upcoming"), ("filed", "filed"), ("withdrawn", "withdrawn")):
        out[status] = [x for x in (us_issue(r, status) for r in _section(js, sec)) if x]
    return out


def _us_months(today: date) -> list[str]:
    out, y, m = [], today.year, today.month
    for k in range(-4, 2):
        mm = m + k
        yy, mm = y + (mm - 1) // 12, (mm - 1) % 12 + 1
        out.append(f"{yy}-{mm:02d}")
    return out


def _us_bars(symbol: str) -> list[dict]:
    from . import technicals
    key = f"IPO::USBARS::{symbol}"
    hit = store.get_company(key)
    if hit and time.time() - hit[0] < TTL["bars"]:
        return hit[1]["bars"]
    bars = technicals._yahoo(symbol, "1y")
    store.put_company(key, {"bars": bars})
    return bars


def us_ipo_for(symbol: str) -> Optional[dict]:
    """The Nasdaq IPO-calendar row (priced) for one ticker, from the months the IPO page saved."""
    today = calendars.us_eastern_now().date()
    for mon in reversed(_us_months(today)):
        hit = store.get_company(f"IPO::US::{mon}")
        for x in ((hit[1].get("items") or {}).get("priced") or []) if hit else []:
            if x.get("symbol") and f"US:{x['symbol']}" == symbol:
                return x
    return None


def us_listing_move(bars: list[dict], priced: str, price: float):
    """Like listing_move, but a price series that starts well before the pricing date is not a first listing."""
    if bars and (date.fromisoformat(priced) - date.fromisoformat(bars[0]["t"])).days > 3:
        return "traded_before"
    return listing_move(bars, priced, price)


def us(refresh: bool = False) -> dict:
    if config.DEMO:
        return {"market": "US", "upcoming": [], "priced": [], "filed": [], "withdrawn": [], "sources": [], "stats": listed_stats([]), "demo": True}
    today = calendars.us_eastern_now().date()
    months, sources = _us_months(today), []
    live = set(months[-2:])     # this month and next change often; older months are settled
    merged = {"priced": {}, "upcoming": {}, "filed": {}, "withdrawn": {}}
    for mon in months:
        def fetch(mon=mon):
            calendars._pace()
            r = requests.get(NASDAQ_IPO, params={"date": mon}, headers=calendars._NQ_HEADERS, timeout=config.REQUEST_TIMEOUT)
            if r.status_code != 200:
                raise IpoError(f"Nasdaq answered {r.status_code}")
            _save_raw(f"nasdaq_ipo_{mon}.json", r.text)
            got = parse_us_month(r.json())
            n = sum(len(v) for v in got.values())
            return {"items": got, "count": n, "found": [k for k, v in got.items() if v], "missing": []}
        try:
            res = _cached(f"IPO::US::{mon}", TTL["upcoming"] if mon in live else TTL["past"], refresh, fetch)
            for k, rows in res["items"].items():
                for x in rows:
                    merged[k][x["deal"] or f"{x['company']}|{x.get(k) or ''}"] = x
            sources.append(_source_row(f"us-{mon}", f"Nasdaq IPO calendar · {mon}", f"{NASDAQ_IPO}?date={mon}", res, None))
        except Exception as e:  # noqa: BLE001
            sources.append(_source_row(f"us-{mon}", f"Nasdaq IPO calendar · {mon}", f"{NASDAQ_IPO}?date={mon}", None, str(e)))
    t = today.isoformat()
    upcoming = sorted([x for x in merged["upcoming"].values() if not x["priced"]], key=lambda x: x.get("expected") or "9")
    priced_ids = {x["symbol"] for x in merged["priced"].values() if x["symbol"]}
    upcoming = [x for x in upcoming if x["symbol"] not in priced_ids]
    cut = (today - timedelta(days=LISTED_DAYS)).isoformat()
    priced = sorted([x for x in merged["priced"].values() if x.get("priced") and cut <= x["priced"] <= t], key=lambda x: x["priced"], reverse=True)
    rows = []
    with _lock:
        for i, x in enumerate(priced):
            x = dict(x, listing=x["priced"], sme=False, perf=None, perf_note=None)
            if not x["symbol"]:
                x["perf_note"] = "no ticker"
            elif x["final_price"] is None:
                x["perf_note"] = "Nasdaq gives no single IPO price"
            elif i >= LISTED_MAX:
                x["perf_note"] = f"not looked up (older than the newest {LISTED_MAX})"
            else:
                try:
                    x["perf"] = us_listing_move(_us_bars(x["symbol"]), x["priced"], x["final_price"])
                    if x["perf"] == "traded_before":
                        x["perf"], x["perf_note"] = None, "this ticker traded before the pricing date (uplisting or reused ticker)"
                    elif x["perf"] is None:
                        x["perf_note"] = "not trading yet" if x["priced"] >= t else "first price bar does not match the IPO date"
                except Exception:  # noqa: BLE001
                    x["perf_note"] = "daily prices not available for this ticker"
            rows.append(x)
    filed = sorted(merged["filed"].values(), key=lambda x: x.get("filed") or "", reverse=True)[:150]
    withdrawn = sorted(merged["withdrawn"].values(), key=lambda x: x.get("withdrawn") or "", reverse=True)[:100]
    return {"market": "US", "today": t, "upcoming": upcoming, "priced": rows, "filed": filed, "withdrawn": withdrawn,
            "stats": listed_stats(rows), "sources": sources}


# ================================================================== IPO history: last 2 years, IPO base, lock-ins
# Built in the background (one daily-price download per listing, ~0.5 s each; India ~450 listings, US ~600 deals)
# and saved; the page shows progress until it is ready. Refreshed after 12 hours.
HIST_TTL = 12 * 3600
HIST_STATE = {m: {"running": False, "done": 0, "total": 0, "started": None, "error": None} for m in ("IN", "US")}
BASE_RULES = {
    "too_new": "Listed fewer than 15 sessions ago: too early to read a base.",
    "below_issue": "Last close below the issue price.",
    "breakout": "Last close is the highest close since listing, and the previous highest close was at least 10 sessions ago (it is breaking out of its IPO base).",
    "tight": "Its high since listing was made at least 10 sessions ago, it is within 25% of that high and the last 10 sessions trade within 15% (high to low): a base is forming.",
    "near_high": "Within 5% of its high since listing.",
    "pullback": "5-25% below its high since listing.",
    "deep": "More than 25% below its high since listing.",
}
BASE_LABEL = {"too_new": "Too new", "below_issue": "Below issue price", "breakout": "Breaking out", "tight": "Base forming",
              "near_high": "Near its high", "pullback": "Pulling back", "deep": "Far below its high"}
# SEBI ICDR lock-ins (issues opening on or after 1 Apr 2022), counted from the date of allotment
LOCKINS_MAIN = [(30, "Anchor investors: first 50% free (30 days)", "anchor"), (90, "Anchor investors: other 50% free (90 days)", "anchor"),
                ("6m", "Pre-IPO shareholders and promoters' holding above the minimum: free (6 months)", "pre"),
                ("18m", "Promoters' minimum 20% contribution: free (18 months)", "promoter")]
LOCKINS_SME = [(30, "Anchor investors: first 50% free (30 days)", "anchor"), (90, "Anchor investors: other 50% free (90 days)", "anchor")]


def ipo_base(bars: list[dict], listing: str, issue_price: Optional[float]) -> Optional[dict]:
    after = [b for b in bars if b["t"][:10] >= listing]
    if not after:
        return None
    n, c = len(after), after[-1]["c"]
    hh = max(b.get("h") or b["c"] for b in after)
    closes = [b["c"] for b in after]
    from_high = round((c / hh - 1) * 100, 2) if hh else None
    if n < 15:
        k = "too_new"
    elif issue_price and c < issue_price:
        k = "below_issue"
    else:
        prev_max = max(closes[:-1])
        at = max(range(n - 1), key=lambda j: closes[j])
        last10 = after[-10:]
        hi10, lo10 = max(b.get("h") or b["c"] for b in last10), min(b.get("l") or b["c"] for b in last10)
        if c > prev_max and (n - 1) - at >= 10:
            k = "breakout"
        elif c >= 0.75 * hh and hi10 and (hi10 - lo10) / hi10 <= 0.15 and max(b.get("h") or b["c"] for b in after[-10:]) < hh:
            k = "tight"
        elif c >= 0.95 * hh:
            k = "near_high"
        elif c >= 0.75 * hh:
            k = "pullback"
        else:
            k = "deep"
    adr = None
    if n >= 5:
        xs = [(b["h"] / b["l"] - 1) for b in after[-20:] if b.get("l")]
        adr = round(sum(xs) / len(xs) * 100, 2) if xs else None
    return {"key": k, "label": BASE_LABEL[k], "from_high": from_high, "sessions": n, "adr": adr, "high": round(hh, 2)}


def lockins(listing: str, sme: bool, today: Optional[date] = None) -> list[dict]:
    """Unlock dates counted from the listing date (allotment is about one working day before listing under
    SEBI's T+3 timetable, so shares can be free a day earlier than shown)."""
    import calendar as _cal
    d0 = date.fromisoformat(listing)

    def plus(p):
        if isinstance(p, int):
            return d0 + timedelta(days=p)
        m = int(p[:-1])                                   # calendar months; a day past the month's end -> its last day
        y, mo = d0.year + (d0.month - 1 + m) // 12, (d0.month - 1 + m) % 12 + 1
        return date(y, mo, min(d0.day, _cal.monthrange(y, mo)[1]))
    out = []
    for p, w, who in (LOCKINS_SME if sme else LOCKINS_MAIN):
        d = plus(p)
        out.append({"days": p, "date": d.isoformat(), "what": w, "who": who, "past": today is not None and d < today})
    return out


def _hist_rows_in(today: date) -> list[dict]:
    past = _list("past", False).get("items") or []
    cut = (today - timedelta(days=730)).isoformat()
    def fresh(x):
        return not x.get("end") or (date.fromisoformat(x["listing"]) - date.fromisoformat(x["end"])).days <= 30
    return sorted([x for x in past if x.get("listing") and cut <= x["listing"] <= today.isoformat() and fresh(x)
                   and x.get("symbol")], key=lambda x: x["listing"], reverse=True)


def _us_months_back(today: date, n: int = 24) -> list[str]:
    out, y, m = [], today.year, today.month
    for _ in range(n + 1):
        out.append(f"{y}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return out[::-1]


def _hist_rows_us(today: date) -> list[dict]:
    rows, seen = [], set()
    for mon in _us_months_back(today):
        def fetch(mon=mon):
            calendars._pace()
            r = requests.get(NASDAQ_IPO, params={"date": mon}, headers=calendars._NQ_HEADERS, timeout=config.REQUEST_TIMEOUT)
            if r.status_code != 200:
                raise IpoError(f"Nasdaq answered {r.status_code}")
            _save_raw(f"nasdaq_ipo_{mon}.json", r.text)
            got = parse_us_month(r.json())
            return {"items": got, "count": sum(len(v) for v in got.values()), "found": [], "missing": []}
        recent = mon >= _us_months(today)[0]
        try:
            res = _cached(f"IPO::US::{mon}", TTL["upcoming"] if recent else 7 * 86400, False, fetch)
        except Exception:  # noqa: BLE001
            continue
        for x in res["items"].get("priced", []):
            k = x.get("deal") or (x.get("symbol"), x.get("priced"))
            if k in seen or not x.get("priced") or x["priced"] > today.isoformat():
                continue
            seen.add(k)
            rows.append(dict(x, listing=x["priced"], sme=False, end=None))
    return sorted(rows, key=lambda x: x["listing"], reverse=True)


def _build_history(market: str) -> None:
    st = HIST_STATE[market]
    try:
        if market == "US":
            today = calendars.us_eastern_now().date()
            rows = _hist_rows_us(today)
        else:
            today = datetime.now(IST).date()
            rows = _hist_rows_in(today)
        st.update(total=len(rows), done=0)
        out = []
        for x in rows:
            y = {k: x.get(k) for k in ("symbol", "company", "sme", "listing", "end", "final_price", "range_text", "size_cr", "value_m",
                                       "times", "exchange")}
            px = x.get("final_price")
            try:
                if market == "US":
                    bars = _us_bars(x["symbol"]) if x.get("symbol") else []
                    if bars and (date.fromisoformat(x["listing"]) - date.fromisoformat(bars[0]["t"][:10])).days > 3:
                        bars, y["note"] = [], "this ticker traded before the pricing date (uplisting or reused ticker)"
                else:
                    bars = _bars_2y(x["symbol"])
                y["perf"] = listing_move(bars, x["listing"], px) if bars and px else None
                y["base"] = ipo_base(bars, x["listing"], px) if bars else None
                if not bars and not y.get("note"):
                    y["note"] = "daily prices not available"
                elif bars and not y["perf"] and not y.get("note"):
                    y["note"] = "no single issue price" if not px else "first price bar does not match the listing date"
            except Exception:  # noqa: BLE001
                y["perf"], y["base"], y["note"] = None, None, "daily prices not available"
            if market == "IN":
                y["lockins"] = lockins(x["listing"], bool(x.get("sme")), today)
            out.append(y)
            st["done"] += 1
            if st["done"] % 25 == 0 and not store.get_company(f"IPO::HIST::{market}"):     # first build: show rows as they come
                store.put_company(f"IPO::HIST::{market}::partial", {"rows": list(out), "today": today.isoformat(), "built": None})
        store.put_company(f"IPO::HIST::{market}", {"rows": out, "today": today.isoformat(), "built": time.time()})
    except Exception as e:  # noqa: BLE001
        st["error"] = str(e)[:200]
    finally:
        st["running"] = False


def _bars_2y(symbol: str) -> list[dict]:
    from . import technicals
    key = f"IPO::BARS2::{symbol}"
    hit = store.get_company(key)
    if hit and time.time() - hit[0] < TTL["bars"]:
        return hit[1]["bars"]
    bars = technicals._yahoo(f"{symbol}.NS", "2y")
    store.put_company(key, {"bars": bars})
    return bars


def history(market: str = "IN", refresh: bool = False) -> dict:
    mk = market.upper() if market.upper() in HIST_STATE else "IN"
    hit = store.get_company(f"IPO::HIST::{mk}")
    st = HIST_STATE[mk]
    stale = not hit or time.time() - hit[0] > HIST_TTL or refresh
    if stale and not st["running"] and not config.DEMO:
        st.update(running=True, done=0, total=0, started=time.time(), error=None)
        threading.Thread(target=_build_history, args=(mk,), daemon=True).start()
    part = store.get_company(f"IPO::HIST::{mk}::partial") if not hit else None
    data = hit[1] if hit else (dict(part[1], partial=True) if part else {"rows": [], "today": None, "built": None})
    return dict(data, market=mk, status=dict(st), base_rules={k: {"label": BASE_LABEL[k], "rule": v} for k, v in BASE_RULES.items()},
                lockin_note=("SEBI ICDR lock-ins for issues opening from 1 April 2022, counted from the date of allotment. Shown from "
                             "the listing date: under the T+3 timetable allotment is about one working day earlier, so shares can be free "
                             "a day before the date shown. Anchor dates apply only if the IPO had anchor investors; promoter and pre-IPO "
                             "dates are for mainboard IPOs.") if mk == "IN" else None)
