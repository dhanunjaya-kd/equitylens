"""FII / DII activity (India) and big-money positions in US index futures (CFTC), from the official files only.

India
  Cash market   NSE's provisional FII/FPI and DII buy, sell and net (Rs crore), published after ~6 pm on trading days.
                NSE gives only the latest day, so EquityLens saves it every evening: the cash history starts the day
                this runs and is never filled with estimates.
  Derivatives   NSE participant-wise open interest (fao_participant_oi_DDMMYYYY.csv), one file per trading day,
                about 5 years kept: Client / DII / FII / Pro long and short contracts in index and stock futures and
                index options. "Long share" = long / (long + short), the usual FII long-short measure.
US
  Positions     CFTC Traders in Financial Futures, futures only, weekly (Tuesday positions, published Friday):
                dealers, asset managers / institutions, leveraged funds, other reportables, non-reportable,
                for E-mini S&P 500 (#13874A) and E-mini Nasdaq-100 (#209742). About 8 years kept.

Longer history (NSDL confirmed FPI figures, sector reports, SEBI mutual fund trades): see fpi.py.
Stocks institutions added or cut: see instholdings.py.

Does it predict the index?  (rules fixed before any result, 22 Nov 2026; the NSDL FPI test uses the same rules)
  A reading is "extreme" when it is in the bottom or top 10% of its own previous year (250 sessions in India,
  52 weeks in the US; only data before that day). Each extreme day (at least 5 sessions / 1 week apart) is
  followed for 5 and 21 sessions (US: 4 weeks from the Friday the report came out). Its record = how often the
  index was higher, against every day with a reading. Called better or worse only when the 90% (Wilson) range
  of that rate is wholly above or below the every-day figure; fewer than 10 cases = too few.
"""
from __future__ import annotations

import csv
import io
import json
import math
import random
import re
import threading
import time
from datetime import date, datetime, timedelta
from typing import Optional

import requests

from . import config, flows, fpi, premarket, store

IST = flows.IST
PART_URL = flows.ARCH + "/content/nsccl/fao_participant_oi_{d}.csv"
CASH_API = "https://www.nseindia.com/api/fiidiiTradeReact"
COT_URL = "https://www.cftc.gov/files/dea/cotarchives/{y}/futures/financial_lf{d}.htm"
COT_LATEST = "https://www.cftc.gov/dea/futures/financial_lf.htm"
COT_MARKETS = {"13874A": "S&P 500 (E-mini)", "209742": "Nasdaq-100 (E-mini)"}
COT_GROUPS = ["dealer", "asset_mgr", "lev_funds", "other", "nonrep"]
COT_LABEL = {"dealer": "Dealers (banks)", "asset_mgr": "Asset managers / institutions", "lev_funds": "Leveraged funds (hedge funds)",
             "other": "Other reportables", "nonrep": "Small traders (non-reportable)"}
PARTICIPANTS = ["FII", "DII", "Pro", "Client"]
HIST_DAYS = 1830           # calendar days looked back: ~5 years, ~1,250 trading days
HIST_WEEKS = 420           # ~8 years of weekly CFTC reports
EXTREME = 0.10
LOOKBACK_IN, LOOKBACK_US = 250, 52
GAP = 5
MIN_CASES = 10
STATE = {"in": {"running": False, "done": 0, "total": 0}, "us": {"running": False, "done": 0, "total": 0}, "error": None}
_started = [False]


def _num(v) -> Optional[float]:
    s = str(v if v is not None else "").replace(",", "").strip()
    if s in ("", ".", "-"):
        return 0.0 if s == "." else None
    try:
        return float(s)
    except ValueError:
        return None


def _pct(vals, q):
    v = sorted(vals)
    if not v:
        return None
    k = (len(v) - 1) * q
    f = math.floor(k)
    c = min(f + 1, len(v) - 1)
    return v[f] + (v[c] - v[f]) * (k - f)


def wilson(k: int, n: int, z: float = 1.645) -> tuple[float, float]:
    if n <= 0:
        return 0.0, 1.0
    p = k / n
    den = 1 + z * z / n
    mid = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, mid - half), min(1.0, mid + half)


# ================================================================ India: cash
def parse_cash(text: str) -> Optional[dict]:
    """NSE fiidiiTradeReact JSON -> {"date": iso, "fii": {buy, sell, net}, "dii": {...}}."""
    try:
        rows = json.loads(text)
    except (TypeError, ValueError):
        return None
    out: dict = {}
    for r in rows if isinstance(rows, list) else []:
        cat = str(r.get("category", "")).upper()
        key = "fii" if ("FII" in cat or "FPI" in cat) else "dii" if "DII" in cat else None
        if not key:
            continue
        vals = {k: _num(r.get(f)) for k, f in (("buy", "buyValue"), ("sell", "sellValue"), ("net", "netValue"))}
        if vals["net"] is None:
            continue
        out[key] = vals
        try:
            out["date"] = datetime.strptime(str(r.get("date")).strip(), "%d-%b-%Y").date().isoformat()
        except ValueError:
            pass
    return out if "date" in out and ("fii" in out or "dii" in out) else None


def cash_history() -> dict:
    hit = store.get_company("FIIDII::CASH")
    return hit[1] if hit else {}


def fetch_cash() -> Optional[dict]:
    """Today's provisional figures from NSE, saved under their own date."""
    if config.DEMO:
        return _demo_cash()
    try:
        text = flows._nse_text(CASH_API)
    except Exception as e:  # noqa: BLE001
        STATE["error"] = f"NSE cash figures: {e}"
        return None
    d = parse_cash(text) if text else None
    if d:
        hist = cash_history()
        hist[d["date"]] = {"fii": d.get("fii"), "dii": d.get("dii"), "saved": time.time()}
        store.put_company("FIIDII::CASH", hist)
    return d


# ================================================================ India: participant-wise open interest
COLS = {  # normalised header -> key
    "futureindexlong": "fut_idx_long", "futureindexshort": "fut_idx_short",
    "futurestocklong": "fut_stk_long", "futurestockshort": "fut_stk_short",
    "optionindexcalllong": "idx_call_long", "optionindexputlong": "idx_put_long",
    "optionindexcallshort": "idx_call_short", "optionindexputshort": "idx_put_short",
    "optionstockcalllong": "stk_call_long", "optionstockputlong": "stk_put_long",
    "optionstockcallshort": "stk_call_short", "optionstockputshort": "stk_put_short",
    "totallongcontracts": "total_long", "totalshortcontracts": "total_short",
}


def parse_participant(text: str) -> dict:
    """fao_participant_oi CSV -> {"FII": {...}, "DII": {...}, "Pro": {...}, "Client": {...}} (contracts)."""
    lines = [ln for ln in (text or "").splitlines() if ln.strip()]
    start = next((i for i, ln in enumerate(lines) if "client type" in ln.lower()), None)
    if start is None:
        return {}
    rd = csv.reader(io.StringIO("\n".join(lines[start:])))
    head = [re.sub(r"[^a-z]", "", h.lower()) for h in next(rd)]
    out = {}
    for row in rd:
        if not row:
            continue
        who = row[0].strip().upper()
        name = {"FII": "FII", "FPI": "FII", "DII": "DII", "PRO": "Pro", "CLIENT": "Client"}.get(who)
        if not name:
            continue
        vals = {}
        for h, v in zip(head[1:], row[1:]):
            k = COLS.get(h)
            if k:
                vals[k] = _num(v)
        if "fut_idx_long" in vals and "fut_idx_short" in vals:
            out[name] = vals
    return out


def derived(p: dict) -> dict:
    """Long share and net for each participant (index futures, stock futures, index options)."""
    out = {}
    for who, v in p.items():
        g = lambda k: v.get(k) or 0.0
        share = lambda l, s: round(100 * l / (l + s), 1) if (l + s) > 0 else None
        out[who] = {
            "fut_idx_long": g("fut_idx_long"), "fut_idx_short": g("fut_idx_short"),
            "fut_idx_net": g("fut_idx_long") - g("fut_idx_short"), "fut_idx_share": share(g("fut_idx_long"), g("fut_idx_short")),
            "fut_stk_net": g("fut_stk_long") - g("fut_stk_short"), "fut_stk_share": share(g("fut_stk_long"), g("fut_stk_short")),
            "idx_call_net": g("idx_call_long") - g("idx_call_short"), "idx_put_net": g("idx_put_long") - g("idx_put_short"),
        }
    return out


def part_day(d: date) -> Optional[dict]:
    key = f"PARTOI::{d.isoformat()}"
    hit = store.get_company(key)
    if hit:
        return hit[1]["p"] or None
    if config.DEMO:
        p = _demo_part(d)
    else:
        text = flows._nse_text(PART_URL.format(d=d.strftime("%d%m%Y")))
        p = parse_participant(text) if text else {}
    now = datetime.now(IST)
    final = bool(p) or d < now.date() - timedelta(days=1) or (d == now.date() - timedelta(days=1) and now.hour >= 9)
    if final:                                 # a missing past day is a holiday; today's file comes out in the evening
        store.put_company(key, {"p": p})
    return p or None


def part_history(n: int = HIST_DAYS, fetch: bool = False) -> list[tuple[str, dict]]:
    """[(iso date, participants)] oldest first. Without fetch, only what is saved."""
    out = []
    d = datetime.now(IST).date()
    for _ in range(n):
        if d.weekday() < 5:
            hit = store.get_company(f"PARTOI::{d.isoformat()}")
            p = (hit[1]["p"] if hit else None) if not fetch else part_day(d)
            if p:
                out.append((d.isoformat(), p))
        d -= timedelta(days=1)
    return out[::-1]


# ================================================================ US: CFTC Commitments of Traders (financial futures)
def parse_cot(text: str) -> dict:
    """Weekly TFF futures-only page -> {"date": iso, code: {"oi": n, group: {"long", "short"}}}."""
    out: dict = {}
    m = re.search(r"Positions as of ([A-Z][a-z]+ \d{1,2}, \d{4})", text or "")
    if m:
        out["date"] = datetime.strptime(m.group(1), "%B %d, %Y").date().isoformat()
    lines = (text or "").splitlines()
    for code in COT_MARKETS:
        for i, ln in enumerate(lines):
            if f"CFTC Code #{code}" not in ln:
                continue
            oi = re.search(r"Open Interest is\s+([\d,]+)", ln)
            for nxt in lines[i + 1:i + 6]:
                toks = nxt.split()
                if len(toks) >= 14 and all(re.fullmatch(r"[\d,]+|\.", t) for t in toks[:14]):
                    n = [_num(t) or 0.0 for t in toks[:14]]
                    out[code] = {"oi": _num(oi.group(1)) if oi else None,
                                 "dealer": {"long": n[0], "short": n[1]}, "asset_mgr": {"long": n[3], "short": n[4]},
                                 "lev_funds": {"long": n[6], "short": n[7]}, "other": {"long": n[9], "short": n[10]},
                                 "nonrep": {"long": n[12], "short": n[13]}}
                    break
            break
    return out


def _get(url: str) -> Optional[str]:
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0 EquityLens research tool"}, timeout=config.REQUEST_TIMEOUT)
    return r.text if r.status_code == 200 else None


def cot_week(tuesday: date) -> Optional[dict]:
    key = f"COT::{tuesday.isoformat()}"
    hit = store.get_company(key)
    if hit:
        return hit[1]["w"] or None
    if config.DEMO:
        w = _demo_cot(tuesday)
    else:
        w = {}
        for d in (tuesday, tuesday - timedelta(days=1), tuesday + timedelta(days=1)):   # holiday weeks move a day
            try:
                text = _get(COT_URL.format(y=d.year, d=d.strftime("%m%d%y")))
            except requests.RequestException as e:
                STATE["error"] = f"CFTC: {e}"
                return None
            if text:
                w = parse_cot(text)
                if any(c in w for c in COT_MARKETS):
                    break
    released = tuesday + timedelta(days=3)
    if w or released < datetime.now(IST).date() - timedelta(days=7):
        store.put_company(key, {"w": w})
    return w or None


def _tuesdays(n: int) -> list[date]:
    d = datetime.now(IST).date()
    d -= timedelta(days=(d.weekday() - 1) % 7)
    return [d - timedelta(weeks=k) for k in range(n)]


def cot_history(fetch: bool = False) -> list[dict]:
    out = []
    for t in _tuesdays(HIST_WEEKS)[::-1]:
        if fetch:
            w = cot_week(t)
        else:
            hit = store.get_company(f"COT::{t.isoformat()}")
            w = hit[1]["w"] if hit else None
        if w and any(c in w for c in COT_MARKETS):
            out.append(dict(w, tuesday=t.isoformat()))
    return out


# ================================================================ does it predict the index?
def entry_index(d: str, pos: dict, shift: int) -> Optional[int]:
    """Index of the first trading day on/after d + shift calendar days (None if not within 6 days)."""
    start = date.fromisoformat(d) + timedelta(days=shift)
    for k in range(6):
        x = (start + timedelta(days=k)).isoformat()
        if x in pos:
            return pos[x]
    return None


def extreme_test(series: list[tuple[str, float]], closes: dict, lookback: int, horizons: tuple, start_shift: int = 0, gap: int = GAP) -> dict:
    """series: [(date, reading)] oldest first; closes: {date: index close} (trading days).
    Low/high = reading in the bottom/top 10% of the previous `lookback` readings (only earlier data).
    start_shift: calendar days after the reading's date before anyone could act on it. India: 1 (figures
    come out after the close, so the next session's close). US: 4 (Tuesday positions released Friday
    afternoon, so the first close after the release day)."""
    days = sorted(closes)
    pos = {d: i for i, d in enumerate(days)}
    entry = lambda d: entry_index(d, pos, start_shift)

    res = {}
    for h in horizons:
        base, lows, highs = [], [], []
        last = {"low": -10 ** 9, "high": -10 ** 9}
        for i in range(lookback, len(series)):
            d, v = series[i]
            e = entry(d)
            if e is None or e + h >= len(days):
                continue
            fwd = closes[days[e + h]] / closes[days[e]] - 1
            base.append(fwd)
            prior = [x for _, x in series[i - lookback:i]]
            lo, hi = _pct(prior, EXTREME), _pct(prior, 1 - EXTREME)
            if v <= lo and i - last["low"] >= gap:
                lows.append((d, fwd)); last["low"] = i
            elif v >= hi and i - last["high"] >= gap:
                highs.append((d, fwd)); last["high"] = i
        b_up = 100 * sum(1 for x in base if x > 0) / len(base) if base else None

        def rec(ev):
            n = len(ev)
            r = {"n": n}
            if n < MIN_CASES:
                r["verdict"] = "too_few"
                return r
            ups = sum(1 for _, x in ev if x > 0)
            lo_, hi_ = wilson(ups, n)
            r.update(up_pct=round(100 * ups / n), range=[round(lo_ * 100), round(hi_ * 100)],
                     median_pct=round(100 * _pct([x for _, x in ev], 0.5), 2),
                     verdict="better" if lo_ * 100 > b_up else "worse" if hi_ * 100 < b_up else "same")
            return r
        res[str(h)] = {"base_n": len(base), "base_up_pct": round(b_up) if b_up is not None else None,
                       "low": rec(lows), "high": rec(highs)}
    return res


def _closes(sym: str) -> dict:
    try:
        return {b["t"]: b["c"] for b in premarket.daily(sym, max_age=6 * 3600)}
    except Exception:  # noqa: BLE001
        return {}


# ================================================================ payloads
def india(fetch: bool = True) -> dict:
    today = fetch_cash() if fetch else None
    hist = cash_history()
    days = sorted(hist)
    latest = today or (dict(hist[days[-1]], date=days[-1]) if days else None)
    cash_rows = [{"date": d, "fii": (hist[d].get("fii") or {}).get("net"), "dii": (hist[d].get("dii") or {}).get("net")} for d in days]

    def streak(key):
        n, sign = 0, None
        for r in reversed(cash_rows):
            v = r[key]
            if v is None or v == 0:
                break
            s = v > 0
            if sign is None:
                sign = s
            if s != sign:
                break
            n += 1
        return {"days": n, "buying": sign} if n else None

    def total(key, since):
        vals = [r[key] for r in cash_rows if r["date"] >= since and r[key] is not None]
        return {"sum": round(sum(vals), 2), "days": len(vals), "buy_days": sum(1 for v in vals if v > 0)} if vals else None
    month0 = date.today().replace(day=1).isoformat()
    last5 = cash_rows[-5:]
    parts = part_history()
    latest_p = parts[-1] if parts else None
    dp = derived(latest_p[1]) if latest_p else {}
    prev = derived(parts[-2][1]) if len(parts) > 1 else {}
    week = derived(parts[-6][1]) if len(parts) > 5 else {}
    share_series = [(d, derived(p)["FII"]["fut_idx_share"]) for d, p in parts if "FII" in p and derived(p)["FII"]["fut_idx_share"] is not None]
    nifty = _closes("^NSEI")
    test_part = extreme_test(share_series, nifty, LOOKBACK_IN, (5, 21), start_shift=1) if len(share_series) > LOOKBACK_IN and nifty else None
    if fetch and not config.DEMO:
        threading.Thread(target=fpi.refresh_daily, daemon=True).start()   # NSDL + SEBI pages, at most every 3 hours
    try:
        extra = fpi.payload()
    except Exception as e:  # noqa: BLE001 - the longer history failing must not take the page down
        STATE["error"] = f"History: {e.__class__.__name__}: {str(e)[:160]}"
        extra = fpi.empty_payload()
    fpi_series = [(r["date"], r["net"]) for r in extra["nsdl"]["rows"]]
    # NSDL's reporting date carries the previous day's trades and is public that day: count from the next close
    test_fpi = extreme_test(fpi_series, nifty, LOOKBACK_IN, (5, 21), start_shift=1) if len(fpi_series) > LOOKBACK_IN and nifty else None
    fut_series = [(r["date"], r["idx_fut_net"]) for r in extra["nsdl"]["deriv"] if r["idx_fut_net"] is not None]
    test_fut = extreme_test(fut_series, nifty, LOOKBACK_IN, (5, 21), start_shift=1) if len(fut_series) > LOOKBACK_IN and nifty else None
    series = []
    for d, p in parts:
        x = derived(p)
        g = lambda w, k: (x.get(w) or {}).get(k)
        series.append({"date": d, "fii_fut": g("FII", "fut_idx_net"), "client_fut": g("Client", "fut_idx_net"), "pro_fut": g("Pro", "fut_idx_net"),
                       "dii_fut": g("DII", "fut_idx_net"), "fii_call": g("FII", "idx_call_net"), "fii_put": g("FII", "idx_put_net"),
                       "fii_share": g("FII", "fut_idx_share")})
    return {
        "market": "IN", "latest": latest, "saved_days": len(days), "first_saved": days[0] if days else None,
        "cash": cash_rows[-260:],
        "streak": {"fii": streak("fii"), "dii": streak("dii")},
        "month": {"fii": total("fii", month0), "dii": total("dii", month0)},
        "last5": {"fii": round(sum(r["fii"] or 0 for r in last5), 2) if last5 else None, "dii": round(sum(r["dii"] or 0 for r in last5), 2) if last5 else None,
                  "days": len(last5)},
        "positions": {"date": latest_p[0] if latest_p else None, "now": dp,
                      "change_1d": {w: {k: (dp[w][k] - prev[w][k]) if prev.get(w) and dp[w][k] is not None and prev[w][k] is not None else None
                                        for k in ("fut_idx_net", "fut_idx_share", "idx_call_net", "idx_put_net", "fut_stk_net")} for w in dp},
                      "change_1w": {w: {k: (dp[w][k] - week[w][k]) if week.get(w) and dp[w][k] is not None and week[w][k] is not None else None
                                        for k in ("fut_idx_share",)} for w in dp},
                      "fii_share_series": share_series[-260:], "days_saved": len(parts), "series": series},
        "nifty": [(d, nifty[d]) for d in sorted(nifty)[-1300:]] if nifty else [],
        "fpi": extra,
        "history_from": parts[0][0] if parts else None,
        "tests": {"fii_futures_share": test_part, "fpi_net": test_fpi, "fpi_fut": test_fut,
                  "fut_days_needed": max(0, LOOKBACK_IN + 1 - len(fut_series)),
                  "fpi_days_needed": max(0, LOOKBACK_IN + 1 - len(fpi_series)),
                  "part_days_needed": max(0, LOOKBACK_IN + 1 - len(share_series))},
        "backfill": dict(STATE["in"]), "error": STATE["error"],
    }


def us() -> dict:
    hist = cot_history()
    spx = _closes("^GSPC")
    ndx = _closes("^NDX")
    markets = {}
    for code, name in COT_MARKETS.items():
        rows = []
        for w in hist:
            m = w.get(code)
            if not m or not m.get("oi"):
                continue
            r = {"date": w.get("date") or w["tuesday"], "oi": m["oi"]}
            for g in COT_GROUPS:
                r[g] = {"long": m[g]["long"], "short": m[g]["short"], "net": m[g]["long"] - m[g]["short"],
                        "net_pct": round(100 * (m[g]["long"] - m[g]["short"]) / m["oi"], 1)}
            rows.append(r)
        idx = spx if code == "13874A" else ndx
        tests = {}
        for g in ("asset_mgr", "lev_funds"):
            ser = [(r["date"], r[g]["net_pct"]) for r in rows]
            tests[g] = extreme_test(ser, idx, LOOKBACK_US, (20,), start_shift=4, gap=1) if len(ser) > LOOKBACK_US and idx else None
        last, prev = (rows[-1] if rows else None), (rows[-2] if len(rows) > 1 else None)
        pctl = {}
        if rows:
            for g in COT_GROUPS:
                vals = [r[g]["net_pct"] for r in rows[-156:]]          # where this week sits in the last 3 years
                pctl[g] = round(100 * sum(1 for v in vals if v <= rows[-1][g]["net_pct"]) / len(vals))
        markets[code] = {"name": name, "latest": last, "prev": prev, "percentile_3y": pctl, "weeks": len(rows),
                         "series": [{"date": r["date"], **{g: r[g]["net_pct"] for g in COT_GROUPS}} for r in rows],
                         "tests": tests}
    return {"market": "US", "markets": markets, "labels": COT_LABEL,
            "index": {"13874A": [(d, spx[d]) for d in sorted(spx)[-800:]] if spx else [], "209742": [(d, ndx[d]) for d in sorted(ndx)[-800:]] if ndx else []},
            "backfill": dict(STATE["us"]), "error": STATE["error"],
            "not_included": "Weekly US fund flows and monthly foreign purchases of US stocks are not included yet."}


# ================================================================ background: save every evening, fill history once
def _backfill_in():
    st = STATE["in"]
    days = [datetime.now(IST).date() - timedelta(days=k) for k in range(HIST_DAYS)]
    todo = [d for d in days if d.weekday() < 5 and store.get_company(f"PARTOI::{d.isoformat()}") is None]
    st.update(running=bool(todo), done=0, total=len(todo))
    for k, d in enumerate(todo, 1):
        try:
            part_day(d)
        except Exception as e:  # noqa: BLE001 - NSE busy: try this day again next round
            STATE["error"] = f"NSE positions file: {e}"
            time.sleep(5)
        st["done"] = k
    st["running"] = False


def _backfill_us():
    st = STATE["us"]
    todo = [t for t in _tuesdays(HIST_WEEKS) if store.get_company(f"COT::{t.isoformat()}") is None]
    st.update(running=bool(todo), done=0, total=len(todo))
    for k, t in enumerate(todo, 1):
        try:
            cot_week(t)
        except Exception as e:  # noqa: BLE001
            STATE["error"] = f"CFTC: {e}"
        st["done"] = k
        time.sleep(0.3)
    st["running"] = False


def _loop():
    while True:
        try:
            now = datetime.now(IST)
            if now.weekday() < 5 and now.hour >= 18:
                fetch_cash()
            fpi.refresh_daily()
            _backfill_in()
            fpi.backfill_all()
            _backfill_us()
        except Exception as e:  # noqa: BLE001
            STATE["error"] = str(e)
        time.sleep(30 * 60)


def start_background() -> None:
    if config.DEMO or _started[0]:
        return
    _started[0] = True
    threading.Thread(target=_loop, name="fiidii", daemon=True).start()


# ================================================================ demo data (offline screenshots and tests)
def _demo_cash() -> dict:
    hist = cash_history()
    if not hist:
        rnd = random.Random(7)
        d = date(2026, 11, 20)
        n = 0
        while n < 300:
            if d.weekday() < 5:
                f = round(rnd.gauss(-400, 2200), 2)
                hist[d.isoformat()] = {"fii": {"buy": 12000.0, "sell": 12000.0 - f, "net": f},
                                       "dii": {"buy": 11000.0, "sell": 11000.0 + f * 0.8, "net": round(-f * 0.8 + rnd.gauss(600, 900), 2)}}
                n += 1
            d -= timedelta(days=1)
        store.put_company("FIIDII::CASH", hist)
    last = max(hist)
    return dict(hist[last], date=last)


def _demo_part(d: date) -> dict:
    rnd = random.Random(d.toordinal())
    t = d.toordinal() / 30.0
    share = 0.35 + 0.2 * math.sin(t)
    fl = 100000 + rnd.randint(0, 20000)
    fs = int(fl * (1 - share) / share)
    return {"FII": {"fut_idx_long": fl, "fut_idx_short": fs, "fut_stk_long": 3.6e6, "fut_stk_short": 1.9e6, "idx_call_long": 4e5,
                    "idx_call_short": 3.5e5, "idx_put_long": 5e5, "idx_put_short": 3e5},
            "DII": {"fut_idx_long": 80000, "fut_idx_short": 12000, "fut_stk_long": 2e5, "fut_stk_short": 4.5e6, "idx_call_long": 0, "idx_call_short": 0, "idx_put_long": 1e4, "idx_put_short": 0},
            "Pro": {"fut_idx_long": 40000, "fut_idx_short": 45000, "fut_stk_long": 6e5, "fut_stk_short": 5e5, "idx_call_long": 9e5, "idx_call_short": 9.5e5, "idx_put_long": 8e5, "idx_put_short": 8.2e5},
            "Client": {"fut_idx_long": 200000, "fut_idx_short": 90000, "fut_stk_long": 2e6, "fut_stk_short": 1.1e6, "idx_call_long": 2.5e6, "idx_call_short": 2.6e6, "idx_put_long": 2e6, "idx_put_short": 2.2e6}}


def _demo_cot(t: date) -> dict:
    rnd = random.Random(t.toordinal())
    out = {"date": t.isoformat()}
    for code, oi in (("13874A", 2.0e6), ("209742", 2.6e5)):
        am = 0.45 + 0.1 * math.sin(t.toordinal() / 60) + rnd.uniform(-0.02, 0.02)
        lf = -0.15 - 0.08 * math.sin(t.toordinal() / 60) + rnd.uniform(-0.02, 0.02)
        out[code] = {"oi": oi, "dealer": {"long": 0.08 * oi, "short": 0.45 * oi}, "asset_mgr": {"long": (0.12 + am) * oi, "short": 0.12 * oi},
                     "lev_funds": {"long": 0.1 * oi, "short": (0.1 - lf) * oi}, "other": {"long": 0.08 * oi, "short": 0.05 * oi},
                     "nonrep": {"long": 0.07 * oi, "short": 0.06 * oi}}
    return out


def demo_fill() -> None:
    """Demo mode: build the saved history so the page and the tests have something to show."""
    _demo_cash()
    fpi.demo_fill()
    for d in [date(2026, 11, 20) - timedelta(days=k) for k in range(HIST_DAYS)]:
        if d.weekday() < 5:
            part_day(d)
    for t in _tuesdays(HIST_WEEKS):
        cot_week(t)
