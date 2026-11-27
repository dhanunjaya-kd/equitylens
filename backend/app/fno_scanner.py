"""Evening stock-option watchlists and next-session paper confirmation."""
import csv
import io
import math
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, time, timedelta

from . import analysis, calendars, config, enrich, flows, service, store, technicals, terminal

KEY = "FNO_SCANNER::v1"
lock = threading.Lock()
state = {"running": False, "done": 0, "total": 0, "error": None}


def setup(bars, day):
    bars = [b for b in bars if b["t"] <= day][-50:]
    if len(bars) < 50 or bars[-1]["t"] != day:
        raise ValueError("Missing completed history")
    if any(not all(isinstance(b.get(k), (int, float)) and math.isfinite(b[k])
                   for k in ("h", "l", "c", "v")) or not (0 < b["l"] <= b["c"] <= b["h"])
           or b["v"] <= 0 for b in bars):
        raise ValueError("Incomplete candles")
    close = bars[-1]["c"]
    sma = sum(b["c"] for b in bars) / 50
    volume = bars[-1]["v"] / (sum(b["v"] for b in bars[-21:-1]) / 20)
    high = max(b["h"] for b in bars[-20:])
    low = min(b["l"] for b in bars[-20:])
    if volume < 1.25:
        return None
    if close > sma and close >= high * .98:
        side, level = "CE", high
    elif close < sma and close <= low * 1.02:
        side, level = "PE", low
    else:
        return None
    return dict(side=side, level=round(level, 4), close=round(close, 2), rvol=round(volume, 2))


def candidate(symbol, lot, day):
    result = setup(technicals._yahoo(symbol + ".NS", "6mo"), day)
    if result and result["side"] == "CE":
        payload, _ = service.get_payload(symbol, full=False, max_age_h=24)
        extras = payload["extras"]
        a = analysis.analyse(payload["company"], service.median_pe_from(extras), None, extras.get("pe_chart"))
        row = service.ranking_row(payload, a)
        if any(row.get(k) is None for k in ("roce", "profit_cagr_5", "debt_to_equity", "cfo_to_pat")):
            raise ValueError("Incomplete quality metrics")
        if not (row["roce"] >= 20 and row["profit_cagr_5"] >= 15
                and 0 <= row["debt_to_equity"] <= .5 and row["cfo_to_pat"] >= .8):
            return None
    return dict(result, symbol=symbol, lot=lot) if result else None


def run():
    try:
        if config.DEMO:
            raise ValueError("Live market data is required. Disable demo mode to scan.")
        now = datetime.now(calendars.IST)
        today = now.date().isoformat()
        sessions = [b["t"] for b in technicals._yahoo("^NSEI", "1mo")
                    if b["t"] < today or (b["t"] == today and now.time() >= time(15, 35))]
        day = sessions[-1]
        if (now.date() - date.fromisoformat(day)).days > 6:
            raise ValueError("Index session is stale. Retry after the feed updates.")
        lots = enrich.parse_fno(flows._nse_text(enrich.FNO_URL) or "")
        if not lots:
            raise ValueError("NSE stock F&O universe unavailable")
        rows, skipped = [], []
        with lock:
            state["total"] = len(lots)
        with ThreadPoolExecutor(max_workers=3) as pool:
            jobs = {pool.submit(candidate, sym, lot, day): sym for sym, lot in lots.items()}
            for job in as_completed(jobs):
                try:
                    row = job.result()
                    if row:
                        rows.append(row)
                except Exception:
                    skipped.append(jobs[job])
                with lock:
                    state["done"] += 1
        if len(skipped) == len(lots):
            raise ValueError("No usable stock histories or fundamentals. Retry when feeds recover.")
        result = dict(day=day, rows=sorted(rows, key=lambda r: (-r["rvol"], r["symbol"])),
                      total=len(lots), skipped=sorted(skipped))
        store.put_company(KEY, result)
    except Exception as exc:
        with lock:
            state["error"] = str(exc)
    finally:
        with lock:
            state["running"] = False


def status(start=False):
    with lock:
        if start and not state["running"]:
            state.update(running=True, done=0, total=0, error=None)
            threading.Thread(target=run, daemon=True).start()
        snapshot = dict(state)
    old = store.get_company(KEY)
    return dict(snapshot, result=old[1] if old else None)


def opening_trigger(bars, row, day):
    start = datetime.combine(day, time(9, 15), calendars.IST)
    times = [int(start.timestamp()) + i * 300 for i in range(3)]
    candles = {b["t"]: b for b in bars if b["t"] in times}
    if len(candles) != 3 or any(b["v"] <= 0 for b in candles.values()):
        return "Opening candles unavailable"
    close = candles[times[-1]]["c"]
    vwap = sum((b["h"] + b["l"] + b["c"]) * b["v"] / 3 for b in candles.values()) / sum(b["v"] for b in candles.values())
    direction = 1 if row["side"] == "CE" else -1
    move = direction * (close / row["level"] - 1)
    if move <= 0 or direction * (close - vwap) <= 0:
        return "Opening close did not confirm"
    if move > .01000000001:
        return "Skipped: opening move exceeded 1%"
    return None


def banned(day):
    url = "https://nsearchives.nseindia.com/archives/fo/sec_ban/fo_secban_" + day.strftime("%d%m%Y") + ".csv"
    data = flows._nse_text(url)
    lines = [[v.strip().upper() for v in r] for r in csv.reader(io.StringIO(data or ""))]
    for i, r in enumerate(lines):
        if "SYMBOL" in r:
            col = r.index("SYMBOL")
            return {r[col] for r in lines[i+1:] if len(r) > col}
    raise ValueError("Dated NSE ban list unavailable")


def contract(row, now):
    sym, side = row["symbol"], row["side"]
    expiries = [(calendars._nse_date(e), e) for e in terminal._expiries(sym, False)]
    eligible = [(d, e) for d, e in expiries if d and (d - now.date()).days >= 7]
    if not eligible:
        return "Eligible expiry unavailable"
    expiry_day, expiry = min(eligible)
    raw = terminal._chain_raw(sym, False, expiry)
    rec = raw.get("records") or raw
    stamp = datetime.strptime(rec.get("timestamp") or raw.get("timestamp") or "", "%d-%b-%Y %H:%M:%S").replace(tzinfo=calendars.IST)
    if not 0 <= (datetime.now(calendars.IST) - stamp).total_seconds() <= 120:
        return "Option quote stale"
    chain = terminal.parse_chain(raw, expiry)
    atm = chain["atm"]
    if atm is None or not chain["ok"]:
        return "ATM contract unavailable"
    for line in rec.get("data") or []:
        if calendars._nse_date(line.get("expiryDate") or line.get("expiryDates")) != expiry_day or terminal.num(line.get("strikePrice")) != atm:
            continue
        q = line.get(side) or {}
        bid = terminal.num(q.get("buyPrice1") or q.get("bidprice"))
        ask = terminal.num(q.get("sellPrice1") or q.get("askPrice"))
        size = terminal.num(q.get("sellQuantity1") or q.get("askQty"))
        if not (bid and ask and 0 < bid <= ask and row["lot"] and size and size >= row["lot"]):
            return "Insufficient quote or one-lot ask depth"
        spread = 2 * (ask - bid) / (ask + bid)
        if spread > .02000000001:
            return "Spread exceeds 2%"
        return f"Paper trigger · {atm:g} {side} · {expiry} · bid {bid:g} / ask {ask:g} · {spread:.2%} spread · {stamp:%H:%M:%S} IST"
    return "Contract unavailable"


def confirm():
    now = datetime.now(calendars.IST)
    hit = store.get_company(KEY)
    if not hit:
        raise ValueError("Run an evening scan first")
    result = hit[1]
    if not time(9, 30) <= now.time() < time(9, 45):
        raise ValueError("Opening confirmation window is 09:30–09:45 IST")
    today = now.date()
    sessions = [b["t"] for b in technicals._yahoo("^NSEI", "1mo") if b["t"] <= today.isoformat()]
    if sessions[-2:] != [result["day"], today.isoformat()]:
        raise ValueError("Watchlist and today's NSE session are not consecutive, or index feed has not updated")
    bans = banned(today)
    events = {e["symbol"] for e in calendars._fetch_in_range(date.fromisoformat(result["day"]), today)}
    lots = enrich.parse_fno(flows._nse_text(enrich.FNO_URL) or "")
    if not lots:
        raise ValueError("NSE membership unavailable")
    def check(row):
        sym = row["symbol"]
        if not lots.get(sym) or sym in bans or sym in events:
            return sym, "Excluded by eligibility, ban or event"
        try:
            reason = opening_trigger(terminal.candles(sym, "5m")["bars"], row, today)
            if datetime.now(calendars.IST).time() >= time(9, 45):
                return sym, "Opening window closed"
            return sym, reason or contract(dict(row, lot=lots[sym]), now)
        except Exception:
            return sym, "Market data unavailable"
    with ThreadPoolExecutor(max_workers=3) as pool:
        return dict(day=result["day"], checks=dict(pool.map(check, result["rows"])))
