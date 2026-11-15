"""Smart-money data: who is really buying or selling. All official, free, no keys.

🇮🇳 NSE (nsearchives.nseindia.com / nseindia.com)
  📦 Delivery %          products/content/sec_bhavdata_full_DDMMYYYY.csv   (daily bhavcopy with deliverable quantity)
  🤝 Bulk & block deals  content/equities/bulk.csv · block.csv               (latest trading day, kept day by day)
  👔 Insider trades      api/corporates-pit                                  (SEBI PIT disclosures: promoters, directors, KMP)
  🚨 Surveillance        archives/equities/mkt/REG_INDDDMMYY.csv             (GSM, ASM, ESM, IBC, pledge, default… per NSE spec)
🇺🇸 SEC EDGAR
  👔 Form 4 insider trades (officers, directors, 10% owners), open-market buys & sells
"""
from __future__ import annotations

import csv
import io
import random
import re
import statistics
import threading
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from typing import Optional

from . import calendars, config, store, us

ARCH = "https://nsearchives.nseindia.com"
IST = calendars.IST
_lock = threading.Lock()
_last = [0.0]


class FlowError(Exception):
    pass


def _today() -> date:
    return datetime.now(IST).date()


def _nse_text(url: str, params: Optional[dict] = None, headers: Optional[dict] = None) -> Optional[str]:
    """GET from NSE with the browser-like cookie session. None = file not published (holiday / not yet)."""
    for attempt in range(2):
        with _lock:
            w = 1.0 - (time.time() - _last[0])
            if w > 0:
                time.sleep(w)
            _last[0] = time.time()
        try:
            r = calendars._nse_session().get(url, params=params, headers=headers, timeout=config.REQUEST_TIMEOUT)
        except Exception as e:  # noqa: BLE001
            calendars._nse["s"] = None
            if attempt:
                raise FlowError(f"NSE not reachable: {e}") from e
            continue
        if r.status_code == 404:
            return None
        if r.status_code == 200 and r.text.strip() and not r.text.lstrip().startswith("<"):
            return r.text
        calendars._nse["s"] = None            # expired cookies / blocked page → one fresh session
    raise FlowError("NSE refused the request (try again in a minute)")


def _f(v) -> Optional[float]:
    try:
        s = str(v).replace(",", "").strip()
        return float(s) if s not in ("", "-", "NA", "nil") else None
    except (TypeError, ValueError):
        return None


def _csv(text: str) -> list[dict]:
    rows = list(csv.reader(io.StringIO(text.lstrip("﻿"))))
    if not rows:
        return []
    head = [h.strip() for h in rows[0]]
    return [{head[i]: (c.strip() if isinstance(c, str) else c) for i, c in enumerate(r) if i < len(head)} for r in rows[1:] if any(x.strip() for x in r)]


def _pick(row: dict, *keys) -> Optional[str]:
    low = {k.lower().replace(" ", "").replace("_", ""): v for k, v in row.items()}
    for k in keys:
        v = low.get(k.lower().replace(" ", "").replace("_", ""))
        if v not in (None, ""):
            return v
    return None


# ================================================================== 📦 delivery %
def parse_bhav(text: str) -> dict:
    out = {}
    for r in _csv(text):
        if (r.get("SERIES") or "").strip() not in ("EQ", "BE", "BZ", "SM", "ST"):
            continue
        close, prev = _f(r.get("CLOSE_PRICE")), _f(r.get("PREV_CLOSE"))
        qty, dq, dp = _f(r.get("TTL_TRD_QNTY")), _f(r.get("DELIV_QTY")), _f(r.get("DELIV_PER"))
        if not close or not qty:
            continue
        out[r["SYMBOL"].strip()] = {"close": close, "prev": prev, "qty": qty, "dq": dq, "dp": dp,
                                     "turnover": round((_f(r.get("TURNOVER_LACS")) or 0) / 100, 2)}   # ₹ Cr
    return out


def _bhav_day(d: date) -> Optional[dict]:
    key = f"BHAV::{d.isoformat()}"
    hit = store.get_company(key)
    if hit:
        return hit[1]["rows"] or None
    if config.DEMO:
        rows = _demo_bhav(d)
    else:
        text = _nse_text(f"{ARCH}/products/content/sec_bhavdata_full_{d.strftime('%d%m%Y')}.csv")
        rows = parse_bhav(text) if text else {}
    final = bool(rows) or d < _today() - timedelta(days=1) or (d == _today() - timedelta(days=1) and datetime.now(IST).hour >= 9)
    if final:                                   # a missing past day is a holiday; today's file appears ~6 PM
        store.put_company(key, {"rows": rows})
    return rows or None


def delivery_days(n: int = 10) -> list[tuple[str, dict]]:
    out, d, tries = [], _today(), 0
    while len(out) < n and tries < n + 12:
        if d.weekday() < 5:
            rows = _bhav_day(d)
            if rows:
                out.append((d.isoformat(), rows))
        d -= timedelta(days=1)
        tries += 1
    return out


def delivery() -> dict:
    hit = store.get_company("DELIVERY::IN")
    if hit and time.time() - hit[0] < 1800:
        return hit[1]
    days = delivery_days(10)
    if not days:
        raise FlowError("No NSE bhavcopy found for the last two weeks")
    (d0, today), hist = days[0], days[1:]
    from . import movers
    idx = {u["symbol"] for u in movers._universe("IN")}
    rows = []
    for sym, t in today.items():
        past = [h[sym] for _, h in hist if sym in h and h[sym].get("dq")]
        avg_dq = statistics.mean(p["dq"] for p in past) if past else None
        avg_dp = statistics.mean(p["dp"] for p in past if p.get("dp") is not None) if past else None
        ret = round((t["close"] / t["prev"] - 1) * 100, 2) if t.get("prev") else None
        rows.append({"symbol": sym, "close": t["close"], "ret": ret, "dp": t["dp"], "dq": t["dq"], "turnover": t["turnover"],
                     "avg_dp": round(avg_dp, 1) if avg_dp is not None else None,
                     "dq_x": round(t["dq"] / avg_dq, 2) if avg_dq and t.get("dq") else None, "in_index": sym in idx,
                     "deliv_value": round((t["dq"] or 0) * t["close"] / 1e7, 2)})     # ₹ Cr actually taken delivery
    out = {"date": d0, "days": [d for d, _ in days], "rows": rows,
           "source": "NSE daily bhavcopy with deliverable quantity (sec_bhavdata_full)"}
    store.put_company("DELIVERY::IN", out)
    return out


def delivery_lists(d: dict, only_index: bool = True, min_turnover: float = 5.0) -> dict:
    rs = [r for r in d["rows"] if (not only_index or r["in_index"]) and (r["turnover"] or 0) >= min_turnover and r.get("dp") is not None]
    strong = lambda r: (r.get("dq_x") or 0) >= 1.5 and r["dp"] >= 50
    return {
        "buying": sorted([r for r in rs if (r["ret"] or 0) > 0 and strong(r)], key=lambda r: -(r["dq_x"] * r["dp"])),
        "selling": sorted([r for r in rs if (r["ret"] or 0) < 0 and strong(r)], key=lambda r: -(r["dq_x"] * r["dp"])),
        "highest": sorted(rs, key=lambda r: -r["dp"])[:60],
        "value": sorted(rs, key=lambda r: -r["deliv_value"])[:60],
    }


def delivery_for(sym: str) -> Optional[dict]:
    if sym.startswith("US:"):
        return None
    days = delivery_days(10)
    series = [{"date": d, "dp": rows[sym]["dp"], "dq": rows[sym]["dq"], "close": rows[sym]["close"], "qty": rows[sym]["qty"]}
              for d, rows in days if sym in rows]
    if not series:
        return None
    t, past = series[0], series[1:]
    avg = statistics.mean(p["dp"] for p in past if p["dp"] is not None) if past else None
    avg_dq = statistics.mean(p["dq"] for p in past if p["dq"]) if past else None
    return {"today": t, "series": list(reversed(series)), "avg_dp": round(avg, 1) if avg is not None else None,
            "dq_x": round(t["dq"] / avg_dq, 2) if avg_dq and t["dq"] else None}


# ================================================================== 🤝 bulk & block deals
def parse_deals(text: str, kind: str) -> list[dict]:
    out = []
    for r in _csv(text):
        sym = _pick(r, "Symbol")
        qty, px = _f(_pick(r, "Quantity Traded", "Quantity", "QTY")), _f(_pick(r, "Trade Price / Wght. Avg. Price", "Trade Price", "Price", "WAP"))
        side = (_pick(r, "Buy/Sell", "Buy / Sell", "BuySell") or "").strip().upper()
        dt_ = calendars._nse_date(_pick(r, "Date") or "")
        if not sym or not qty or not px or not dt_:
            continue
        out.append({"kind": kind, "date": dt_.isoformat(), "symbol": sym.strip().upper(), "name": _pick(r, "Security Name", "Name") or sym,
                    "client": (_pick(r, "Client Name", "Client") or "").strip(), "side": "BUY" if side.startswith("B") else "SELL",
                    "qty": qty, "price": px, "value": round(qty * px / 1e7, 2), "remarks": _pick(r, "Remarks")})
    return out


def deals() -> dict:
    hit = store.get_company("DEALS::latest")
    if hit and time.time() - hit[0] < 3600:
        return hit[1]
    got = []
    for kind in ("bulk", "block"):
        text = _demo_deals(kind) if config.DEMO else _nse_text(f"{ARCH}/content/equities/{kind}.csv")
        got += parse_deals(text, kind) if text else []
    by_day: dict = {}
    for g in got:
        by_day.setdefault(g["date"], []).append(g)
    for d, rows in by_day.items():                  # keep a growing day-by-day history for the stock pages
        store.put_company(f"DEALS::{d}", {"rows": rows})
    latest = max(by_day) if by_day else None
    out = {"date": latest, "rows": sorted(by_day.get(latest, []), key=lambda r: -r["value"]),
           "source": "NSE bulk & block deal files (nsearchives)"}
    store.put_company("DEALS::latest", out)
    return out


def deals_for(sym: str) -> list[dict]:
    rows = []
    for k in store.keys_like("DEALS::20%"):
        hit = store.get_company(k)
        rows += [r for r in (hit[1]["rows"] if hit else []) if r["symbol"] == sym]
    return sorted(rows, key=lambda r: r["date"], reverse=True)


# ================================================================== 👔 India insider (PIT) trades
def parse_pit(j) -> list[dict]:
    data = j if isinstance(j, list) else (j or {}).get("data") or []
    out = []
    for r in data:
        sym = (r.get("symbol") or "").strip().upper()
        sec = (r.get("secType") or "").lower()
        if not sym or (sec and not any(w in sec for w in ("equity", "share"))):
            continue
        typ = (r.get("tdpTransactionType") or r.get("transactionType") or "").strip()
        qty, val = _f(r.get("secAcq")), _f(r.get("secVal"))
        d = next((x for x in (calendars._nse_date(r.get(k) or "") for k in ("acqfromDt", "acqtoDt", "date", "intimDt")) if x), None)
        cat = (r.get("personCategory") or "").strip()
        mode = (r.get("acqMode") or "").strip()
        side = "BUY" if typ.lower().startswith("buy") or typ.lower() == "acquisition" else "SELL" if typ.lower().startswith(("sell", "sale", "disposal")) \
            else "PLEDGE" if "pledge" in typ.lower() and "revok" not in typ.lower() and "release" not in typ.lower() else "OTHER"
        out.append({"symbol": sym, "name": (r.get("company") or sym).strip(), "person": (r.get("acqName") or "").strip(), "category": cat,
                    "promoter": "promoter" in cat.lower(), "type": typ or side, "side": side, "mode": mode,
                    "market": "market" in mode.lower(), "qty": qty, "value": round(val / 1e7, 3) if val else None,   # ₹ Cr
                    "price": round(val / qty, 2) if val and qty else None, "date": d.isoformat() if d else None,
                    "after_pct": _f(r.get("afterAcqSharesPer")), "before_pct": _f(r.get("befAcqSharesPer")),
                    "reported": (r.get("intimDt") or "")[:11].strip() or None})
    return out


PIT_API = "https://www.nseindia.com/api/corporates-pit"
PIT_GG_API = "https://www.nseindia.com/api/corporates-pit-gg"     # newer list (XBRL-era filings, since May 2026)

# old-style field -> fragments of the field names a newer NSE list may use
_PIT_FIELDS = {
    "symbol": ("symbol",), "company": ("companyname", "company", "smname", "issuer"),
    "acqName": ("acqname", "nameoftheperson", "nameofperson", "personname", "acquirer", "insidername"),
    "personCategory": ("personcategory", "categoryofperson", "category"),
    "tdpTransactionType": ("tdptransactiontype", "transactiontype", "typeoftransaction", "acqdisp", "buysell"),
    "acqMode": ("acqmode", "modeofacq", "mode"),
    "secAcq": ("secacq", "noofsecurities", "numberofsecurities", "quantity", "noofshares"),
    "secVal": ("secval", "valueofsecurit", "value"),
    "acqfromDt": ("acqfromdt", "acqfrom", "dateofallotment", "fromdate", "transactiondate", "tradedate"),
    "acqtoDt": ("acqtodt", "acqto", "todate"),
    "intimDt": ("intimdt", "intimation", "broadcast", "submission", "disseminat", "date"),
    "secType": ("sectype", "typeofsecurit", "securitytype"),
    "befAcqSharesPer": ("befacqsharesper", "beforeper", "prepercent", "preholding"),
    "afterAcqSharesPer": ("afteracqsharesper", "afterper", "postpercent", "postholding"),
    "xbrl": ("xbrl",),
}


def pit_normalise(r: dict) -> dict:
    """Map a record from either NSE insider list onto the classic corporates-pit field names."""
    if not isinstance(r, dict) or ("symbol" in r and "secAcq" in r):
        return r
    norm = {re.sub(r"[^a-z0-9]", "", k.lower()): k for k in r}
    out, used = {}, set()
    for field, frags in _PIT_FIELDS.items():
        for frag in frags:
            key = next((orig for low, orig in norm.items() if low not in used and (low == frag or frag in low)), None)
            if key is not None:
                out[field] = r[key]
                used.add(re.sub(r"[^a-z0-9]", "", key.lower()))
                break
    return out
PIT_PAGE = "https://www.nseindia.com/companies-listing/corporate-filings-insider-trading"


def _pit_json(params: dict, api: str = PIT_API) -> list:
    import json as _json
    text = _nse_text(api, params, headers={"Referer": PIT_PAGE})
    j = _json.loads(text) if text else {}
    return j if isinstance(j, list) else (j or {}).get("data") or []


def pit_variants(start, end) -> list[tuple[str, dict]]:
    f = "%d-%m-%Y"
    return [("date range", {"index": "equities", "from_date": start.strftime(f), "to_date": end.strftime(f)}),
            ("latest (as NSE's page loads it)", {"index": "equities"}),
            ("date range, no index", {"from_date": start.strftime(f), "to_date": end.strftime(f)})]


def pit_gg_variants(start, end) -> list[dict]:
    f = "%d-%m-%Y"
    return [{"index": "equities", "from_date": start.strftime(f), "to_date": end.strftime(f)}, {"index": "equities"}, {}]


def pit_fetch(start, end) -> dict:
    """NSE's insider API can answer an empty list unless it is asked the way its own page asks:
    open the insider-trading page first (cookies + referer), then try the request shapes the page uses,
    and finally week by week."""
    try:
        calendars._nse_session().get(PIT_PAGE, timeout=config.REQUEST_TIMEOUT)
    except Exception:  # noqa: BLE001
        pass
    for _, params in pit_variants(start, end):
        try:
            data = _pit_json(params)
        except Exception:  # noqa: BLE001
            data = []
        if data:
            return {"data": data}
    for params in pit_gg_variants(start, end):            # NSE's newer insider list
        try:
            data = _pit_json(params, PIT_GG_API)
        except Exception:  # noqa: BLE001
            data = []
        if data:
            return {"data": [pit_normalise(r) for r in data]}
    data, d = [], end
    while d > start:                                      # last resort: 7-day windows
        a = max(start, d - timedelta(days=6))
        try:
            data += _pit_json({"index": "equities", "from_date": a.strftime("%d-%m-%Y"), "to_date": d.strftime("%d-%m-%Y")})
        except Exception:  # noqa: BLE001
            pass
        d = a - timedelta(days=1)
    return {"data": data}


def insiders_in(days: int = 30) -> dict:
    key = f"PIT2::IN::{days}"   # v2: dates with a time part no longer dropped
    hit = store.get_company(key)
    if hit and time.time() - hit[0] < 6 * 3600:
        return hit[1]
    end, start = _today(), _today() - timedelta(days=days)
    if config.DEMO:
        j = _demo_pit(start, end)
    else:
        j = pit_fetch(start, end)
    rows = [r for r in parse_pit(j) if r["date"]]
    rows.sort(key=lambda r: (r["date"], r["value"] or 0), reverse=True)
    out = {"rows": rows, "from": start.isoformat(), "to": end.isoformat(),
           "source": "NSE insider-trading disclosures (SEBI PIT regulations)"}
    store.put_company(key, out)
    return out


def summarise(rows: list[dict], money_key: str = "value") -> dict:
    mk = [r for r in rows if r.get("market") and r["side"] in ("BUY", "SELL")]
    b = [r for r in mk if r["side"] == "BUY"]
    s = [r for r in mk if r["side"] == "SELL"]
    bv, sv = sum(r[money_key] or 0 for r in b), sum(r[money_key] or 0 for r in s)
    buyers = {r["person"] for r in b if r["person"]}
    recent = [r for r in b if r["date"] and r["date"] >= (_today() - timedelta(days=30)).isoformat()]
    return {"buys": len(b), "sells": len(s), "buy_value": round(bv, 2), "sell_value": round(sv, 2), "net_value": round(bv - sv, 2),
            "buyers": len(buyers), "cluster": len({r["person"] for r in recent if r["person"]}) >= 2,
            "pledges": sum(1 for r in rows if r["side"] == "PLEDGE")}


# ================================================================== 🚨 NSE surveillance (REG_IND)
# column → (label for code, severity) per NSE's REG_IND file structure (100 = not under the measure)
SURV = [
    ("GSM", lambda c: "Shortlisted for GSM" if c == "0" else f"GSM stage {c}", "high"),
    ("Long_Term_Additional_Surveillance_Measure", lambda c: f"Long-term ASM stage {c}", "high"),
    ("Unsolicited_SMS", lambda c: "Unsolicited SMS/tips watchlist", "medium"),
    ("Insolvency_Resolution_Process", lambda c: "Insolvency (IBC) disclosure" if c == "0" else f"Insolvency (IBC) stage {'I' if c == '1' else 'II'}", "high"),
    ("Short_Term_Additional_Surveillance_Measure", lambda c: f"Short-term ASM stage {c}", "medium"),
    ("Default", lambda c: "Loan default disclosed" if c == "0" else "Under surveillance for loan default", "high"),
    ("ICA", lambda c: "Inter-creditor agreement (stressed loans)", "medium"),
    ("Pledge", lambda c: "High promoter pledge (surveillance)", "high"),
    ("Add-on_PB", lambda c: "Add-on price band", "medium"),
    ("Total Pledge", lambda c: "High total pledge (promoter + others)", "medium"),
    ("Social Media Platforms", lambda c: "Under social-media tip surveillance", "medium"),
    ("ESM", lambda c: f"Enhanced Surveillance (ESM) stage {'I' if c == '1' else 'II'}", "high"),
    ("Loss making", lambda c: "Loss-making for 8+ quarters", "medium"),
    ("The Overall encumbered share in the scrip is more than 50 Percent", lambda c: "Promoter encumbrance ≥ 50% of capital", "high"),
    ("Under BZ/SZ Series", lambda c: "Moved to BZ/SZ series (non-compliance)", "high"),
    ("Company has failed to pay Annual listing fee", lambda c: "Annual listing fee unpaid", "medium"),
    ("Derivative contracts in the scrip to be moved out of F and O", lambda c: "Being moved out of F&O", "medium"),
]
# positions per the published layout, used when a header name differs slightly
SURV_POS = {"GSM": 5, "Long_Term_Additional_Surveillance_Measure": 6, "Unsolicited_SMS": 7, "Insolvency_Resolution_Process": 8,
            "Short_Term_Additional_Surveillance_Measure": 9, "Default": 10, "ICA": 11, "Pledge": 14, "Add-on_PB": 15, "Total Pledge": 16,
            "Social Media Platforms": 17, "ESM": 18, "Loss making": 19,
            "The Overall encumbered share in the scrip is more than 50 Percent": 20, "Under BZ/SZ Series": 21,
            "Company has failed to pay Annual listing fee": 22, "Derivative contracts in the scrip to be moved out of F and O": 24}


def parse_reg_ind(text: str) -> dict:
    rows = list(csv.reader(io.StringIO(text.lstrip("﻿"))))
    if not rows:
        return {}
    head = [h.strip() for h in rows[0]]
    norm = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())
    hidx = {norm(h): i for i, h in enumerate(head)}
    sym_i = hidx.get("symbol", 1)
    out = {}
    for r in rows[1:]:
        if len(r) <= sym_i or not r[sym_i].strip():
            continue
        flags = []
        for col, label, sev in SURV:
            i = next((v for k, v in hidx.items() if k.startswith(norm(col)[:14])), SURV_POS[col])
            if i >= len(r):
                continue
            code = r[i].strip()
            if code and code != "100":
                flags.append({"measure": col, "code": code, "label": label(code), "severity": sev})
        if flags:
            out[r[sym_i].strip().upper()] = flags
    return out


REPORTS_API = "https://www.nseindia.com/api/daily-reports"


def report_files(key: str = "CM") -> list[dict]:
    """NSE's 'All reports' page lists each day's files with their real names and folders.
    Returns [{"name": "REG_IND131126.csv", "url": "https://nsearchives…/REG_IND131126.csv", "group": "CurrentDay"}]."""
    import json as _json
    text = _nse_text(REPORTS_API, {"key": key}, headers={"Referer": "https://www.nseindia.com/all-reports"})
    j = _json.loads(text) if text else {}
    out = []
    for group, items in (j.items() if isinstance(j, dict) else [("all", j)]):
        for it in items if isinstance(items, list) else []:
            if not isinstance(it, dict):
                continue
            vals = [str(v) for v in it.values() if isinstance(v, str)]
            name = next((v for v in vals if re.search(r"\.(csv|zip|txt|dat)$", v, re.I) and "/" not in v), "")
            path = next((v for v in vals if v.startswith("http")), "")
            if name and path:
                url = path if path.lower().endswith(name.lower()) else path.rstrip("/") + "/" + name
                out.append({"name": name, "url": url, "group": group, "title": it.get("displayName") or it.get("fileKey") or ""})
    return out


def surveillance_report_urls() -> list[str]:
    try:
        files = report_files("CM")
    except Exception:  # noqa: BLE001
        return []
    hits = [f for f in files if re.match(r"REG1?_IND", f["name"], re.I) or "surveillance" in f["title"].lower()]
    hits.sort(key=lambda f: (f["group"] != "CurrentDay", not f["name"].upper().startswith("REG_IND")))
    return [f["url"] for f in hits]


def _fetch_report(url: str) -> Optional[str]:
    """A report file as text; zipped reports are unpacked."""
    if not url.lower().endswith(".zip"):
        return _nse_text(url)
    import zipfile
    r = calendars._nse_session().get(url, timeout=config.REQUEST_TIMEOUT)
    if r.status_code != 200:
        return None
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        inner = next((n for n in z.namelist() if n.lower().endswith(".csv")), None)
        return z.read(inner).decode("utf-8", "replace") if inner else None


def surveillance_urls(d) -> list[str]:
    """REG_IND file names NSE has used: DDMMYY, DDMMYYYY, and the REG1_IND variant."""
    a, b = d.strftime("%d%m%y"), d.strftime("%d%m%Y")
    return [f"{ARCH}/archives/equities/mkt/REG_IND{a}.csv", f"{ARCH}/archives/equities/mkt/REG1_IND{a}.csv",
            f"{ARCH}/archives/equities/mkt/REG_IND{b}.csv", f"{ARCH}/archives/equities/mkt/REG1_IND{b}.csv"]


def surveillance() -> dict:
    hit = store.get_company("SURV::IN")
    if hit and time.time() - hit[0] < 6 * 3600:
        return hit[1]
    d, text, used, tried = _today(), None, None, 0
    if not config.DEMO:                                  # 1) the file NSE's own report list points to
        for url in surveillance_report_urls():
            tried += 1
            try:
                text = _fetch_report(url)
            except Exception:  # noqa: BLE001
                text = None
            if text and parse_reg_ind(text):
                used = _today()
                m = re.search(r"(\d{6,8})\.", url)
                if m:
                    try:
                        used = datetime.strptime(m.group(1), "%d%m%y" if len(m.group(1)) == 6 else "%d%m%Y").date()
                    except ValueError:
                        pass
                out = {"date": used.isoformat(), "flags": parse_reg_ind(text), "source": "NSE surveillance indicator file (REG_IND)"}
                store.put_company("SURV::IN", out)
                return out
            text = None
    for _ in range(12):                                  # 2) the usual archive file names
        if d.weekday() < 5:
            if config.DEMO:
                text = _demo_reg_ind()
            else:
                for url in surveillance_urls(d):
                    tried += 1
                    try:
                        text = _nse_text(url)
                    except FlowError:
                        text = None
                    if text:
                        break
            if text:
                used = d
                break
        d -= timedelta(days=1)
    if not text:
        raise FlowError(f"NSE surveillance file not found for the last two weeks ({tried} file names tried)")
    out = {"date": used.isoformat(), "flags": parse_reg_ind(text), "source": "NSE surveillance indicator file (REG_IND)"}
    store.put_company("SURV::IN", out)
    return out


# ================================================================== 🇺🇸 SEC Form 4
CODES = {"P": "Open-market buy", "S": "Open-market sale", "A": "Grant / award", "M": "Option exercise", "F": "Tax withholding",
         "G": "Gift", "D": "Sold back to company", "C": "Conversion", "X": "Option exercise", "J": "Other", "W": "Inheritance"}


def _t(el, path: str) -> Optional[str]:
    x = el.find(path)
    if x is None:
        return None
    v = x.find("value")
    return ((v.text if v is not None else x.text) or "").strip() or None


def parse_form4(xml: str, url: str = "") -> list[dict]:
    root = ET.fromstring(re.sub(r'\sxmlns="[^"]+"', "", xml, count=1))
    owners = root.findall("reportingOwner")
    names, roles = [], []
    for o in owners:
        names.append(_t(o, "reportingOwnerId/rptOwnerName") or "")
        rel = o.find("reportingOwnerRelationship")
        r = []
        if rel is not None:
            if (_t(rel, "isDirector") or "") in ("1", "true"):
                r.append("Director")
            if (_t(rel, "isOfficer") or "") in ("1", "true"):
                r.append(_t(rel, "officerTitle") or "Officer")
            if (_t(rel, "isTenPercentOwner") or "") in ("1", "true"):
                r.append("10% owner")
        roles.append(", ".join(r) or "Insider")
    out = []
    for tx in root.findall("nonDerivativeTable/nonDerivativeTransaction"):
        code = _t(tx, "transactionCoding/transactionCode") or ""
        sh, px = _f(_t(tx, "transactionAmounts/transactionShares")), _f(_t(tx, "transactionAmounts/transactionPricePerShare"))
        ad = _t(tx, "transactionAmounts/transactionAcquiredDisposedCode") or ""
        out.append({"date": (_t(tx, "transactionDate") or "")[:10], "person": " / ".join(n for n in names if n), "role": roles[0] if roles else "Insider",
                    "code": code, "type": CODES.get(code, code or "Other"), "side": "BUY" if code == "P" else "SELL" if code == "S" else ("ACQ" if ad == "A" else "DISP"),
                    "market": code in ("P", "S"), "qty": sh, "price": px, "value": round(sh * px / 1e6, 3) if sh and px else None,   # $ M
                    "owned_after": _f(_t(tx, "postTransactionAmounts/sharesOwnedFollowingTransaction")), "url": url})
    return out


def insiders_us(sym: str, days: int = 180, max_filings: int = 30) -> dict:
    key = f"FORM4::{sym}"
    hit = store.get_company(key)
    if hit and time.time() - hit[0] < 12 * 3600:
        return hit[1]
    info = us.lookup(sym)
    if not info:
        raise FlowError("Not found on SEC EDGAR")
    if config.DEMO:
        rows = _demo_form4(sym)
    else:
        subs = us._get_json(us.SUBS_URL.format(cik=info["cik"]))
        rec = (subs.get("filings") or {}).get("recent") or {}
        since = (_today() - timedelta(days=days)).isoformat()
        rows, n = [], 0
        for i, form in enumerate(rec.get("form") or []):
            if form != "4" or (rec["filingDate"][i] or "") < since:
                continue
            acc, doc = rec["accessionNumber"][i].replace("-", ""), rec["primaryDocument"][i].split("/")[-1]
            url = f"https://www.sec.gov/Archives/edgar/data/{info['cik']}/{acc}/{doc}"
            try:
                rows += parse_form4(us.get_text(url), url)
            except (ET.ParseError, us.USFetchError):
                pass
            n += 1
            if n >= max_filings:
                break
    rows = [r for r in rows if r["date"]]
    rows.sort(key=lambda r: r["date"], reverse=True)
    out = {"symbol": sym, "rows": rows, "summary": summarise(rows), "source": "SEC EDGAR Form 4 filings"}
    store.put_company(key, out)
    return out


def insiders_us_many(symbols: list[str]) -> dict:
    rows, errs = [], {}
    for sym in symbols[:25]:
        try:
            d = insiders_us(sym)
            name = (us.lookup(sym) or {}).get("name", sym)
            rows += [{**r, "symbol": sym, "name": name} for r in d["rows"]]
        except Exception as e:  # noqa: BLE001
            errs[sym] = str(e)
    rows.sort(key=lambda r: r["date"], reverse=True)
    return {"rows": rows, "errors": errs, "source": "SEC EDGAR Form 4 filings"}


# ================================================================== per-stock bundle
def for_stock(sym: str) -> dict:
    out: dict = {"symbol": sym, "errors": {}}
    if sym.startswith("US:"):
        try:
            out["insiders"] = insiders_us(sym)
        except Exception as e:  # noqa: BLE001
            out["errors"]["insiders"] = str(e)
        return out
    for k, fn in (("surveillance", lambda: surveillance()["flags"].get(sym, [])), ("delivery", lambda: delivery_for(sym)),
                  ("deals", lambda: (deals(), deals_for(sym))[1]),
                  ("insiders", lambda: (lambda rs: {"rows": rs, "summary": summarise(rs)})([r for r in insiders_in(90)["rows"] if r["symbol"] == sym]))):
        try:
            out[k] = fn()
        except Exception as e:  # noqa: BLE001 - one source down must not hide the rest
            out["errors"][k] = str(e)
    return out


# ================================================================== demo data (same raw formats as the live files)
def _demo_syms() -> list[dict]:
    from . import movers
    return movers._universe("IN")


def _demo_bhav(d: date) -> dict:
    if d.weekday() >= 5:
        return {}
    head = "SYMBOL, SERIES, DATE1, PREV_CLOSE, OPEN_PRICE, HIGH_PRICE, LOW_PRICE, LAST_PRICE, CLOSE_PRICE, AVG_PRICE, TTL_TRD_QNTY, TURNOVER_LACS, NO_OF_TRADES, DELIV_QTY, DELIV_PER"
    lines = [head]
    for i, u in enumerate(_demo_syms()):
        rnd = random.Random(f"{u['symbol']}{d}")
        base = 200 + i * 37
        prev = round(base * (1 + rnd.uniform(-0.03, 0.03)), 2)
        close = round(prev * (1 + rnd.uniform(-0.04, 0.045)), 2)
        qty = int(rnd.uniform(2e5, 4e6) * (3 if (i % 7 == 0 and d >= _today() - timedelta(days=3)) else 1))
        dp = round(rnd.uniform(25, 70) + (20 if i % 7 == 0 else 0), 2)
        lines.append(f"{u['symbol']}, EQ, {d.strftime('%d-%b-%Y')}, {prev}, {prev}, {max(prev, close) * 1.01:.2f}, {min(prev, close) * 0.99:.2f}, "
                     f"{close}, {close}, {(prev + close) / 2:.2f}, {qty}, {qty * close / 1e5:.2f}, {qty // 300}, {int(qty * dp / 100)}, {dp}")
    lines.append(f"SOMEBOND, N1, {d.strftime('%d-%b-%Y')}, 1000, 1000, 1000, 1000, 1000, 1000, 1000, 10, 0.1, 1, -, -")
    return parse_bhav("\n".join(lines))


def _demo_deals(kind: str) -> str:
    d = _today() - timedelta(days=(_today().weekday() - 4) if _today().weekday() > 4 else 0)
    rnd = random.Random(kind + d.isoformat())
    lines = ["Date,Symbol,Security Name,Client Name,Buy/Sell,Quantity Traded,Trade Price / Wght. Avg. Price,Remarks"]
    clients = ["GOLDMAN SACHS (SINGAPORE) PTE", "SBI MUTUAL FUND", "SOCIETE GENERALE", "HDFC MUTUAL FUND", "GRAVITON RESEARCH CAPITAL LLP", "PROMOTER HOLDINGS LLP"]
    for u in rnd.sample(_demo_syms(), 6 if kind == "bulk" else 3):
        lines.append(f"{d.strftime('%d-%b-%Y')},{u['symbol']},{u['name']},{rnd.choice(clients)},{rnd.choice(['BUY', 'SELL'])},"
                     f"{rnd.randint(2, 40) * 100000},{rnd.uniform(150, 2500):.2f},-")
    return "\n".join(lines)


def _demo_pit(start: date, end: date) -> dict:
    rnd = random.Random(f"pit{end}")
    data = []
    for u in rnd.sample(_demo_syms(), 10) + [_demo_syms()[0]]:
        cat = rnd.choice(["Promoters", "Promoter Group", "Director", "Key Managerial Personnel", "Employees/Designated Employees"])
        typ = rnd.choice(["Buy", "Buy", "Sell", "Pledge Creation"])
        qty = rnd.randint(1, 50) * 10000
        px = rnd.uniform(150, 2500)
        d = end - timedelta(days=rnd.randint(0, (end - start).days))
        data.append({"symbol": u["symbol"], "company": u["name"], "acqName": rnd.choice(["Rakesh Kumar", "ABC Family Trust", "Sunita Rao", "XYZ Holdings Pvt Ltd"]),
                     "personCategory": cat, "secType": "Equity Shares", "secAcq": str(qty), "secVal": f"{qty * px:.0f}", "tdpTransactionType": typ,
                     "acqMode": "Market Purchase" if typ == "Buy" else "Market Sale" if typ == "Sell" else "-", "acqfromDt": d.strftime("%d-%b-%Y"),
                     "acqtoDt": d.strftime("%d-%b-%Y"), "intimDt": (d + timedelta(days=2)).strftime("%d-%b-%Y %H:%M"),
                     "befAcqSharesPer": "51.20", "afterAcqSharesPer": "51.35"})
    data.append({"symbol": "BONDCO", "company": "x", "secType": "Debentures", "secAcq": "1", "secVal": "1", "tdpTransactionType": "Buy", "acqfromDt": end.strftime("%d-%b-%Y")})
    return {"acqNameList": [], "data": data}


def _demo_reg_ind() -> str:
    head = ("ScripCode,Symbol,NSE Exclusive,Status,Series,GSM,Long_Term_Additional_Surveillance_Measure (Long Term ASM),Unsolicited_SMS,"
            "Insolvency_Resolution_Process(IRP),Short_Term_Additional_Surveillance_Measure (Short Term ASM),Default,ICA,Filler4,Filler5,Pledge,"
            "Add-on_PB,Total Pledge,Social Media Platforms,ESM,Loss making,The Overall encumbered share in the scrip is more than 50 Percent,"
            "Under BZ/SZ Series,Company has failed to pay Annual listing fee,Filler12,Derivative contracts in the scrip to be moved out of F and O,"
            "Filler13,Filler14,Filler15,Filler16")
    base = ["100"] * 24
    rows = [head]
    for i, u in enumerate(_demo_syms()[:8]):
        v = list(base)
        if i == 3:
            v[0] = "2"        # GSM stage 2
        if i == 5:
            v[1] = "1"; v[14] = "0"   # LT ASM 1, loss making
        if i == 7:
            v[9] = "1"        # pledge
        rows.append(",".join([str(1000 + i), u["symbol"], "N", "A", "EQ"] + v))
    return "\n".join(rows)


def _demo_form4(sym: str) -> list[dict]:
    rnd = random.Random("f4" + sym)
    xmls = []
    for k in range(6):
        d = _today() - timedelta(days=rnd.randint(2, 150))
        code = rnd.choice(["P", "S", "S", "A", "M", "F", "P"])
        xmls.append(f"""<?xml version="1.0"?><ownershipDocument><issuer><issuerTradingSymbol>{sym[3:]}</issuerTradingSymbol></issuer>
<reportingOwner><reportingOwnerId><rptOwnerName>{rnd.choice(['Doe Jane', 'Smith John', 'Lee Ann'])}</rptOwnerName></reportingOwnerId>
<reportingOwnerRelationship><isDirector>{rnd.choice(['0', '1'])}</isDirector><isOfficer>1</isOfficer><officerTitle>{rnd.choice(['CEO', 'CFO', 'EVP Sales'])}</officerTitle></reportingOwnerRelationship></reportingOwner>
<nonDerivativeTable><nonDerivativeTransaction><transactionDate><value>{d.isoformat()}</value></transactionDate>
<transactionCoding><transactionCode>{code}</transactionCode></transactionCoding>
<transactionAmounts><transactionShares><value>{rnd.randint(1, 80) * 500}</value></transactionShares><transactionPricePerShare><value>{rnd.uniform(120, 220):.2f}</value></transactionPricePerShare>
<transactionAcquiredDisposedCode><value>{'A' if code in 'PAM' else 'D'}</value></transactionAcquiredDisposedCode></transactionAmounts>
<postTransactionAmounts><sharesOwnedFollowingTransaction><value>{rnd.randint(50, 900) * 1000}</value></sharesOwnedFollowingTransaction></postTransactionAmounts>
</nonDerivativeTransaction></nonDerivativeTable></ownershipDocument>""")
    rows = []
    for x in xmls:
        rows += parse_form4(x, "https://www.sec.gov/")
    return rows
