"""Live terminal (a screen, no orders): NSE stocks, index and stock F&O, US stocks.

Sources (public, no keys) and how fresh they are
  NSE   api/quote-equity?symbol=                 price, day range, circuit band, VWAP            (asked every few seconds)
  NSE   api/quote-equity?symbol=&section=trade_info  5-level market depth, traded value, delivery %
  NSE   api/quote-derivative?symbol=             futures (and options) contracts: price, OI
  NSE   api/option-chain-v3 / option-chain-indices / option-chain-equities   option chain by expiry
  Yahoo chart feed                               intraday candles (1, 5, 15 min) and US prices (may lag a little)

Every answer carries the time the source stamped on it. Checks before showing (a failing figure is left out with
the reason): change = price − previous close; best bid below best ask, bids falling and asks rising; option-chain
strikes in order and one expiry per table; futures basis = futures price − spot (arithmetic, labelled).
PCR (put OI ÷ call OI) and max pain are worked out from NSE's open interest and labelled as such.
The latest raw answer of each kind is saved in data/term_raw/ for the source check.
"""
from __future__ import annotations

import json
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import quote

import requests

from . import calendars, config, flows

IST = calendars.IST
NSE = "https://www.nseindia.com"
YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"}
RAW_DIR = config.DATA_DIR / "term_raw"
INDICES = {"NIFTY": ("^NSEI", "NIFTY 50"), "BANKNIFTY": ("^NSEBANK", "NIFTY BANK"), "FINNIFTY": ("NIFTY_FIN_SERVICE.NS", "NIFTY FIN SERVICE"),
           "MIDCPNIFTY": ("NIFTY_MID_SELECT.NS", "NIFTY MIDCAP SELECT")}
TTL = {"quote": 3, "trade": 5, "deriv": 15, "chain": 15, "candles": 30, "watch": 15, "expiries": 600}
_cache: dict = {}
_lock = threading.Lock()


class TermError(Exception):
    pass


def num(v) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def _get(d: Any, *path, default=None):
    for p in path:
        if not isinstance(d, dict):
            return default
        d = d.get(p)
    return default if d is None else d


def _save_raw(name: str, text: str) -> None:
    try:
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        (RAW_DIR / name).write_text(text, encoding="utf-8")
    except OSError:
        pass


def _cached(key: str, ttl: float, fn):
    now = time.time()
    with _lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < ttl:
            return hit[1]
    val = fn()
    with _lock:
        _cache[key] = (time.time(), val)
    return val


def _note_failure(raw: str, path: str, params: dict, what: str) -> None:
    """Keep what NSE answered when a request fails (status, start of the reply), for the source check."""
    try:
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        log = RAW_DIR / "failures.json"
        rows = json.loads(log.read_text(encoding="utf-8")) if log.exists() else []
        rows = (rows + [{"at": datetime.now(IST).isoformat(timespec="seconds"), "kind": raw, "path": path, "params": params,
                         "what": what[:400]}])[-40:]
        log.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    except (OSError, ValueError):
        pass


def _nse_once(path: str, params: dict, raw: str, referer: str):
    """One NSE request with the app's cookie session and pacing. Records the status and reply when it fails."""
    with flows._lock:
        w = 1.0 - (time.time() - flows._last[0])
        if w > 0:
            time.sleep(w)
        flows._last[0] = time.time()
    try:
        r = calendars._nse_session().get(f"{NSE}{path}", params=params, headers={"Referer": referer}, timeout=config.REQUEST_TIMEOUT)
    except Exception as e:  # noqa: BLE001
        calendars._nse["s"] = None
        _note_failure(raw, path, params, f"not reachable: {e}")
        raise TermError(f"NSE not reachable: {e}") from e
    body = r.text or ""
    if r.status_code != 200 or not body.strip() or body.lstrip().startswith("<"):
        _note_failure(raw, path, params, f"HTTP {r.status_code}: {body[:300]}")
        if r.status_code in (401, 403):
            calendars._nse["s"] = None            # expired cookies: a fresh session next time
        raise TermError(f"NSE answered HTTP {r.status_code} for {path}")
    _save_raw(raw, body)
    try:
        return json.loads(body)
    except ValueError as e:
        _note_failure(raw, path, params, f"not JSON: {body[:300]}")
        raise TermError("NSE answered with something that is not JSON (format changed?)") from e


def _nse(path: str, params: dict, raw: str, referer: str, fallbacks: tuple = ()):
    """Try NSE's address, then any newer addresses for the same data; the first that answers is used."""
    errors = []
    for p, prm, rw in ((path, params, raw),) + tuple(fallbacks):
        for attempt in range(2):
            try:
                return _nse_once(p, prm, rw, referer)
            except TermError as e:
                errors.append(str(e))
                if "401" not in str(e) and "403" not in str(e):
                    break                          # a 404 / format error won't change on a retry
    raise TermError("; ".join(dict.fromkeys(errors)))


def clean(sym: str) -> str:
    return re.sub(r"[^A-Z0-9&\-^_.:]", "", (sym or "").upper())


# ------------------------------------------------------------------ NSE stock: quote + depth
def parse_quote(js: dict) -> dict:
    pi = js.get("priceInfo") or {}
    info = js.get("info") or {}
    md = js.get("metadata") or {}
    ltp, prev, chg, pchg = num(pi.get("lastPrice")), num(pi.get("previousClose")), num(pi.get("change")), num(pi.get("pChange"))
    check = None
    if ltp is not None and prev and chg is not None and abs((ltp - prev) - chg) > max(0.02, abs(chg) * 0.01):
        check = f"NSE's change ({chg:g}) does not equal price − previous close ({ltp - prev:.2f}); worked out instead"
        chg, pchg = round(ltp - prev, 2), round((ltp / prev - 1) * 100, 2)
    elif ltp is not None and prev and chg is None:
        chg, pchg = round(ltp - prev, 2), round((ltp / prev - 1) * 100, 2)
    day = pi.get("intraDayHighLow") or {}
    wk = pi.get("weekHighLow") or {}
    return {
        "symbol": info.get("symbol") or md.get("symbol"), "name": info.get("companyName"), "industry": info.get("industry"),
        "fno": bool(info.get("isFNOSec")), "series": md.get("series"),
        "ltp": ltp, "prev": prev, "change": chg, "pchange": pchg, "change_check": check,
        "open": num(pi.get("open")), "high": num(day.get("max")), "low": num(day.get("min")), "vwap": num(pi.get("vwap")),
        "close": num(pi.get("close")), "upper_circuit": num(pi.get("upperCP")), "lower_circuit": num(pi.get("lowerCP")),
        "band": pi.get("pPriceBand"), "wk_high": num(wk.get("max")), "wk_low": num(wk.get("min")),
        "time": md.get("lastUpdateTime") or js.get("lastUpdateTime"),
    }


def parse_trade(js: dict) -> dict:
    ob = js.get("marketDeptOrderBook") or {}
    ti = ob.get("tradeInfo") or {}
    dp = js.get("securityWiseDP") or {}
    side = lambda rows: [{"price": num(r.get("price")), "qty": num(r.get("quantity"))} for r in rows or [] if num(r.get("price"))]  # noqa: E731
    bids, asks = side(ob.get("bid")), side(ob.get("ask"))
    ok, why = True, None
    if bids and any(bids[i]["price"] < bids[i + 1]["price"] for i in range(len(bids) - 1)):
        ok, why = False, "bids are not in falling price order"
    elif asks and any(asks[i]["price"] > asks[i + 1]["price"] for i in range(len(asks) - 1)):
        ok, why = False, "asks are not in rising price order"
    elif bids and asks and bids[0]["price"] >= asks[0]["price"]:
        ok, why = False, "best bid is not below best ask"
    return {
        "depth": {"bids": bids, "asks": asks, "ok": ok, "why": why,
                  "total_buy": num(ob.get("totalBuyQuantity")), "total_sell": num(ob.get("totalSellQuantity"))} if (bids or asks) else None,
        "volume": num(ti.get("totalTradedVolume")), "value_cr": num(ti.get("totalTradedValue")),
        "mcap_cr": num(ti.get("totalMarketCap")), "impact_cost": num(ti.get("impactCost")),
        "delivery_pct": num(dp.get("deliveryToTradedQuantity")), "delivery_qty": num(dp.get("deliveryQuantity")),
        "delivery_date": dp.get("secWiseDelPosDate"),
    }


def stock(symbol: str) -> dict:
    sym = clean(symbol)
    ref = f"{NSE}/get-quotes/equity?symbol={quote(sym)}"
    out = {"symbol": sym, "sources": []}
    try:
        out["quote"] = _cached(f"q::{sym}", TTL["quote"], lambda: parse_quote(_nse(
            "/api/quote-equity", {"symbol": sym}, "nse_quote.json", ref,
            fallbacks=(("/api/NextApi/apiClient/GetQuoteApi", {"functionName": "getSymbolData", "marketType": "N", "series": "EQ", "symbol": sym},
                        "nse_quote_next.json"),))))
        out["sources"].append({"name": "NSE quote", "ok": True})
    except Exception as e:  # noqa: BLE001
        out["quote"] = None
        out["sources"].append({"name": "NSE quote", "ok": False, "error": str(e)[:160]})
    try:
        out["trade"] = _cached(f"t::{sym}", TTL["trade"], lambda: parse_trade(
            _nse("/api/quote-equity", {"symbol": sym, "section": "trade_info"}, "nse_trade.json", ref,
                 fallbacks=(("/api/NextApi/apiClient/GetQuoteApi", {"functionName": "getSymbolData", "marketType": "N", "series": "EQ",
                             "symbol": sym}, "nse_trade_next.json"),))))
        out["sources"].append({"name": "NSE depth and trade info", "ok": True})
    except Exception as e:  # noqa: BLE001
        out["trade"] = None
        out["sources"].append({"name": "NSE depth and trade info", "ok": False, "error": str(e)[:160]})
    out["fetched"] = time.time()
    return out


# ------------------------------------------------------------------ F&O: futures and option chain
def parse_deriv(js: dict) -> dict:
    spot = num(js.get("underlyingValue"))
    futs = []
    for s in js.get("stocks") or []:
        md = s.get("metadata") or {}
        if "fut" not in str(md.get("instrumentType", "")).lower():
            continue
        ti = _get(s, "marketDeptOrderBook", "tradeInfo", default={})
        px = num(md.get("lastPrice"))
        futs.append({"expiry": md.get("expiryDate"), "ltp": px, "change": num(md.get("change")), "pchange": num(md.get("pChange")),
                     "oi": num(ti.get("openInterest")), "oi_change": num(ti.get("changeinOpenInterest")),
                     "volume": num(md.get("numberOfContractsTraded")), "basis": round(px - spot, 2) if px is not None and spot else None})
    futs.sort(key=lambda f: calendars._nse_date(f["expiry"] or "") or datetime.max.date())
    return {"spot": spot, "time": js.get("fut_timestamp") or js.get("opt_timestamp") or js.get("timestamp"), "futures": futs}


def max_pain(rows: list[dict]) -> Optional[float]:
    """Strike at which option buyers' total intrinsic value (on NSE's open interest) is smallest."""
    strikes = [r["strike"] for r in rows if r.get("ce_oi") is not None or r.get("pe_oi") is not None]
    if len(strikes) < 3:
        return None
    best, best_v = None, None
    for k in strikes:
        v = sum((r.get("ce_oi") or 0) * max(0.0, k - r["strike"]) + (r.get("pe_oi") or 0) * max(0.0, r["strike"] - k) for r in rows)
        if best_v is None or v < best_v:
            best, best_v = k, v
    return best


def parse_chain(js: dict, expiry: Optional[str] = None) -> dict:
    rec = js.get("records") or js
    data = rec.get("data") or js.get("data") or []
    exps = rec.get("expiryDates") or sorted({r.get("expiryDate") or r.get("expiryDates") for r in data if r.get("expiryDate") or r.get("expiryDates")},
                                              key=lambda d: calendars._nse_date(d) or datetime.max.date())
    exp = expiry if expiry in exps else (exps[0] if exps else None)
    rows = []
    for r in data:
        e = r.get("expiryDate") or r.get("expiryDates")
        if exp and e and e != exp:
            continue
        k = num(r.get("strikePrice"))
        if k is None:
            continue
        ce, pe = r.get("CE") or {}, r.get("PE") or {}
        f = lambda d, *keys: next((num(d.get(x)) for x in keys if num(d.get(x)) is not None), None)  # noqa: E731
        rows.append({"strike": k,
                     "ce_oi": f(ce, "openInterest"), "ce_oi_chg": f(ce, "changeinOpenInterest"), "ce_iv": f(ce, "impliedVolatility"),
                     "ce_ltp": f(ce, "lastPrice"), "ce_chg": f(ce, "change"), "ce_vol": f(ce, "totalTradedVolume"),
                     "pe_oi": f(pe, "openInterest"), "pe_oi_chg": f(pe, "changeinOpenInterest"), "pe_iv": f(pe, "impliedVolatility"),
                     "pe_ltp": f(pe, "lastPrice"), "pe_chg": f(pe, "change"), "pe_vol": f(pe, "totalTradedVolume")})
    rows.sort(key=lambda r: r["strike"])
    spot = num(rec.get("underlyingValue")) or next((num(_get(r, side, "underlyingValue")) for r in data for side in ("CE", "PE")
                                                    if num(_get(r, side, "underlyingValue"))), None)
    ce_oi = sum(r["ce_oi"] or 0 for r in rows)
    pe_oi = sum(r["pe_oi"] or 0 for r in rows)
    atm = min(rows, key=lambda r: abs(r["strike"] - spot))["strike"] if rows and spot else None
    return {"expiries": exps, "expiry": exp, "spot": spot, "time": rec.get("timestamp") or js.get("timestamp"), "rows": rows,
            "atm": atm, "ce_oi": ce_oi or None, "pe_oi": pe_oi or None,
            "pcr": round(pe_oi / ce_oi, 2) if ce_oi else None, "max_pain": max_pain(rows),
            "ok": len({r["strike"] for r in rows}) == len(rows)}


def _chain_raw(sym: str, index: bool, expiry: Optional[str]):
    ref = f"{NSE}/option-chain"
    params = {"type": "Indices" if index else "Equity", "symbol": sym}
    if expiry:
        params["expiry"] = expiry
    try:
        js = _nse("/api/option-chain-v3", params, "nse_chain_v3.json", ref)
        if _get(js, "records", "data") or js.get("data"):
            return js
    except Exception:  # noqa: BLE001 - older endpoint below
        pass
    return _nse("/api/option-chain-indices" if index else "/api/option-chain-equities", {"symbol": sym}, "nse_chain.json", ref)


def _expiries(sym: str, index: bool) -> list[str]:
    def fetch():
        js = _nse("/api/option-chain-contract-info", {"symbol": sym}, "nse_contract_info.json", f"{NSE}/option-chain")
        return js.get("expiryDates") or _get(js, "records", "expiryDates", default=[])
    try:
        return _cached(f"x::{sym}", TTL["expiries"], fetch)
    except Exception:  # noqa: BLE001
        return []


def fno(symbol: str, expiry: Optional[str] = None) -> dict:
    sym = clean(symbol)
    index = sym in INDICES
    out = {"symbol": sym, "index": index, "sources": []}
    try:
        exps = _expiries(sym, index)
        exp = expiry or (exps[0] if exps else None)
        out["chain"] = _cached(f"c::{sym}::{exp}", TTL["chain"], lambda: parse_chain(_chain_raw(sym, index, exp), exp))
        out["sources"].append({"name": "NSE option chain", "ok": True})
    except Exception as e:  # noqa: BLE001
        out["chain"] = None
        out["sources"].append({"name": "NSE option chain", "ok": False, "error": str(e)[:160]})
    try:
        ref = f"{NSE}/get-quotes/derivatives?symbol={quote(sym)}"
        out["deriv"] = _cached(f"d::{sym}", TTL["deriv"], lambda: parse_deriv(_nse(
            "/api/quote-derivative", {"symbol": sym}, "nse_deriv.json", ref,
            fallbacks=(("/api/NextApi/apiClient/GetQuoteApi", {"functionName": "getSymbolDerivativesData", "symbol": sym},
                        "nse_deriv_next.json"),))))
        out["sources"].append({"name": "NSE futures", "ok": True})
    except Exception as e:  # noqa: BLE001
        out["deriv"] = None
        out["sources"].append({"name": "NSE futures", "ok": False, "error": str(e)[:160]})
    out["fetched"] = time.time()
    return out


# ------------------------------------------------------------------ candles and US / index quotes (Yahoo)
def yahoo_symbol(sym: str) -> str:
    s = clean(sym)
    if s.startswith("US:"):
        return s[3:]
    if s in INDICES:
        return INDICES[s][0]
    if s.startswith("^") or s.endswith(".NS") or s.endswith(".BO"):
        return s
    return f"{s}.NS"


def parse_yahoo(res: dict) -> dict:
    meta = res.get("meta") or {}
    ts = res.get("timestamp") or []
    q = ((res.get("indicators") or {}).get("quote") or [{}])[0]
    bars = []
    for i, t in enumerate(ts):
        o, h, l, c, v = (q.get(k, [None] * len(ts))[i] for k in ("open", "high", "low", "close", "volume"))
        if None in (o, h, l, c) or c <= 0:
            continue
        bars.append({"t": int(t), "o": o, "h": h, "l": l, "c": c, "v": v or 0})
    price, prev = num(meta.get("regularMarketPrice")), num(meta.get("chartPreviousClose") or meta.get("previousClose"))
    vw, vol = 0.0, 0.0
    day0 = None
    vwap = []
    for b in bars:                               # session VWAP from the candles (typical price × volume)
        d = datetime.fromtimestamp(b["t"] + int(meta.get("gmtoffset") or 0), timezone.utc).date()
        if d != day0:
            day0, vw, vol = d, 0.0, 0.0
        vw += (b["h"] + b["l"] + b["c"]) / 3 * b["v"]
        vol += b["v"]
        vwap.append(round(vw / vol, 2) if vol else None)
    return {"bars": bars, "vwap": vwap, "price": price, "prev": prev,
            "change": round(price - prev, 2) if price is not None and prev else None,
            "pchange": round((price / prev - 1) * 100, 2) if price is not None and prev else None,
            "currency": meta.get("currency"), "time": meta.get("regularMarketTime"), "tz": meta.get("exchangeTimezoneName"),
            "offset": int(meta.get("gmtoffset") or 0), "name": meta.get("longName") or meta.get("shortName")}


def _yahoo(sym: str, interval: str, rng: str) -> dict:
    r = requests.get(YAHOO.format(sym=quote(sym)), params={"interval": interval, "range": rng, "includePrePost": "false"},
                     headers=UA, timeout=config.REQUEST_TIMEOUT)
    if r.status_code != 200:
        raise TermError(f"Yahoo answered {r.status_code} for {sym}")
    res = ((r.json().get("chart") or {}).get("result") or [None])[0]
    if not res:
        raise TermError(f"Yahoo has no prices for {sym}")
    return parse_yahoo(res)


FRAMES = {"1m": ("1m", "1d"), "5m": ("5m", "5d"), "15m": ("15m", "1mo"), "30m": ("30m", "1mo"), "1h": ("60m", "3mo"),
          "4h": ("60m", "6mo"), "1D": ("1d", "2y"), "1W": ("1wk", "10y")}


def group_hours(bars: list[dict], offset: int, n: int = 4) -> list[dict]:
    """4-hour candles from hourly ones: within each trading day, hours 1-4 form the first candle, 5-8 the next
    (NSE: 09:15-13:15 and 13:15-15:30)."""
    out, day, k = [], None, 0
    for b in bars:
        d = datetime.fromtimestamp(b["t"] + offset, timezone.utc).date()
        if d != day:
            day, k = d, 0
        if k % n == 0:
            out.append(dict(b))
        else:
            o = out[-1]
            o.update(h=max(o["h"], b["h"]), l=min(o["l"], b["l"]), c=b["c"], v=(o["v"] or 0) + (b["v"] or 0))
        k += 1
    return out


def candles(symbol: str, frame: str = "5m") -> dict:
    frame = frame if frame in FRAMES else "5m"
    iv, rng = FRAMES[frame]
    ys = yahoo_symbol(symbol)
    out = _cached(f"k::{ys}::{frame}", TTL["candles"], lambda: _yahoo(ys, iv, rng))
    if frame == "4h":
        out = dict(out, bars=group_hours(out["bars"], out["offset"]), vwap=[])
    elif frame in ("1D", "1W"):
        out = dict(out, vwap=[])
    return dict(out, symbol=clean(symbol), yahoo=ys, frame=frame, source="Yahoo Finance chart feed (may lag a little)")


def watch(symbols: list[str]) -> dict:
    from concurrent.futures import ThreadPoolExecutor

    def one(s):
        try:
            d = _cached(f"w::{s}", TTL["watch"], lambda: _yahoo(yahoo_symbol(s), "5m", "1d"))
            return {"symbol": clean(s), "price": d["price"], "change": d["change"], "pchange": d["pchange"], "time": d["time"],
                    "spark": [b["c"] for b in d["bars"]][-60:]}
        except Exception as e:  # noqa: BLE001
            return {"symbol": clean(s), "error": str(e)[:80]}
    with ThreadPoolExecutor(max_workers=6) as ex:
        return {"rows": list(ex.map(one, [clean(s) for s in symbols if clean(s)][:40])), "source": "Yahoo Finance (may lag a little)"}


def market_open_ist(now: Optional[datetime] = None) -> bool:
    now = now or datetime.now(IST)
    return now.weekday() < 5 and (9, 15) <= (now.hour, now.minute) <= (15, 30)
