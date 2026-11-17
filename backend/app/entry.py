"""Entry decision engine: is this a good time to buy, for a 1-3 year holding?

One set of fixed rules, used both live on the stock page and in tools/entry_backtest.py,
so the track record shown on the page is the track record of exactly these rules.

Rules v2 (17 Nov 2026), after the first 500-stock backtest showed (vs same-month peers):
  - waiting on "stretched" stocks was harmful (they did best: momentum), so it is dropped;
  - the 3-part plan cost ~8 points a year vs buying at once, so it is dropped;
  - price buy zones were reached only ~24% of the time, so they are dropped;
  - P/E vs its own history did not order 12-month returns, so value no longer changes the
    verdict (it is shown as information, and tested again at 24 and 36 months);
  - stocks below a falling 200-day average did worst, so that is the one WAIT rule.

Rules v3 (17 Nov 2026), after the all-NSE backtest (1,541 stocks, vs same-month peers):
  - stocks below a falling 200-day average trailed peers (-4.0% over 12 months, in both halves and
    80% of months), and waiting for the close back above the average, then buying, did worse than
    buying at once (17.5% vs 25.2%). So it is AVOID with no buy level, not "wait for X";
  - stretched stocks did best (+5.7%), so they are "strong trend", still ENTER;
  - an Expensive P/E vs its own history trailed peers over 2-3 years (the value test fixed before
    the run passed), so it adds a caution; it still does not change the verdict.

Verdicts and the rule behind each:
  AVOID  avoid_business  loss-making, serious red flag, surveillance or weak business (live only, not backtested)
  AVOID  avoid_falling   below a falling 200-day average (turns to ENTER by itself once it is not)
  ENTER  enter_stretched not falling, strong trend: stretched above its 50-day average
  ENTER  enter           not falling
Results within 7 days is a warning only (not backtested). No numbers were tuned.
"""
from __future__ import annotations

import bisect
from typing import Optional

RULES_VERSION = 3
# --- rule constants: chosen up front, not tuned on results -------------------------------
CHEAP, FAIR, FULL = 0.30, 0.60, 0.85        # P/E percentile edges: cheap < 30% < fair < 60% < full < 85% < expensive
MIN_PE_POINTS = 100                         # ~3 years of P/E history before the value check is trusted
STRETCH_ATR = 3.0                           # more than 3 ATRs above the 50-day average = stretched
HOT_RSI = 75
RESULTS_DAYS = 7
GOOD_BUSINESS = 55                          # below this the business check fails (same line as the verdict's "weak")
STATES = ["Cheap", "Fair", "Full", "Expensive"]
# What each rule claims, so the backtest can check the claim: +1 = should beat peers, -1 = should trail them.
EXPECT = {"enter": 1, "enter_stretched": 1, "avoid_falling": -1}


def _sma(c, n, i):
    return sum(c[i - n + 1:i + 1]) / n if i + 1 >= n else None


def _atr(h, l, c, i, n=14):
    if i < n + 1:
        return None
    tr = [max(h[k] - l[k], abs(h[k] - c[k - 1]), abs(l[k] - c[k - 1])) for k in range(i - n + 1, i + 1)]
    return sum(tr) / n


def _rsi(c, i, n=14):
    if i < n * 3:
        return None
    gains = losses = 0.0
    start = i - n * 3        # Wilder smoothing over a short warm-up window
    ag = al = None
    for k in range(start + 1, i + 1):
        d = c[k] - c[k - 1]
        g, lo = max(d, 0.0), max(-d, 0.0)
        if ag is None:
            gains += g
            losses += lo
            if k - start == n:
                ag, al = gains / n, losses / n
        else:
            ag = (ag * (n - 1) + g) / n
            al = (al * (n - 1) + lo) / n
    if ag is None:
        return None
    return 100.0 if al == 0 else 100 - 100 / (1 + ag / al)


def pe_state(pe_hist: list[float], pe_now: Optional[float]) -> tuple[Optional[str], Optional[float], dict]:
    """Where today's P/E sits in the stock's own past P/E (percentile), plus the P/E at each edge."""
    vals = sorted(v for v in pe_hist if v and v > 0)
    if not pe_now or pe_now <= 0 or len(vals) < MIN_PE_POINTS:
        return None, None, {}
    pct = bisect.bisect_left(vals, pe_now) / len(vals)
    q = lambda p: vals[min(len(vals) - 1, int(p * len(vals)))]
    edges = {"cheap": q(CHEAP), "fair": q(FAIR), "full": q(FULL)}
    state = "Cheap" if pct < CHEAP else "Fair" if pct < FAIR else "Full" if pct < FULL else "Expensive"
    return state, pct, edges


def fv_state(price: float, fv: Optional[dict]) -> Optional[str]:
    if not fv or not fv.get("low") or not fv.get("mid") or not fv.get("high"):
        return None
    return "Cheap" if price < fv["low"] else "Fair" if price <= fv["mid"] else "Full" if price <= fv["high"] else "Expensive"


def _r(x, n=0):
    return None if x is None else round(x, n)


def decide(bars: list[dict], i: Optional[int] = None, pe_hist: Optional[list[float]] = None,
           pe_now: Optional[float] = None, business: Optional[float] = None, high_flags: int = 0,
           loss_making: bool = False, fair_value: Optional[dict] = None,
           results_in_days: Optional[int] = None, surveillance: bool = False) -> dict:
    """The verdict at bar i (default: the latest). Uses only bars[:i+1]."""
    i = len(bars) - 1 if i is None else i
    h = [b["h"] for b in bars]
    l = [b["l"] for b in bars]
    c = [b["c"] for b in bars]
    px = c[i]
    s50, s200, s200_prev = _sma(c, 50, i), _sma(c, 200, i), _sma(c, 200, i - 20) if i >= 220 else None
    atr, rsi = _atr(h, l, c, i), _rsi(c, i)
    if s200 is None or atr is None or atr <= 0 or px <= 0:     # flat/suspended prices: no call
        return {"verdict": "NA", "label": "Not enough price history", "reasons": ["Needs about 1 year of prices."],
                "rules_version": RULES_VERSION}

    reasons, checks = [], {}

    # 1. business (live only; cannot be backtested)
    gate_fail = None
    if loss_making:
        gate_fail = "The company is making losses right now."
    elif high_flags:
        gate_fail = f"{high_flags} serious red flag{'s' if high_flags > 1 else ''} in the forensic checks."
    elif surveillance:
        gate_fail = "The stock is under exchange surveillance (ASM/GSM)."
    elif business is not None and business < GOOD_BUSINESS:
        gate_fail = f"Business score {business:.0f}/100 is below {GOOD_BUSINESS}."
    checks["business"] = {"ok": gate_fail is None if business is not None or loss_making or high_flags or surveillance else None,
                          "text": gate_fail or ("Strong, no serious red flags" if business is not None else "Not scored")}

    # 2. value - information only, not used in the verdict
    st_pe, pct, edges = pe_state(pe_hist or [], pe_now)
    st_fv = fv_state(px, fair_value)
    states = [s for s in (st_pe, st_fv) if s]
    state = max(states, key=STATES.index) if states else None          # the more cautious one
    why = []
    if st_pe:
        why.append(f"P/E {st_pe.lower()} vs its own history ({pct * 100:.0f}th percentile)")
    if st_fv:
        why.append(f"{st_fv.lower()} vs fair value")
    caution = state == "Expensive"
    checks["value"] = {"state": state, "pe_state": st_pe, "fv_state": st_fv, "caution": caution,
                       "pe_percentile": _r(pct * 100 if pct is not None else None), "ok": False if caution else None,
                       "text": (f"{state} — {'; '.join(why)}." + (" A caution; it does not change the verdict." if caution
                                                                   else " Shown for information; not used in the verdict.")
                                if state else "Value not available")}

    # 3. trend - the one tested rule that decides between ENTER and WAIT
    down = px < s200 and s200_prev is not None and s200 < s200_prev
    up = px > s200 and s50 is not None and s50 > s200
    stretch = (px - s50) / atr if s50 else 0
    hot = stretch > STRETCH_ATR or (rsi is not None and rsi > HOT_RSI)
    trend = "Uptrend" if up else "Downtrend" if down else "Sideways"
    checks["timing"] = {"trend": trend, "stretch_atr": _r(stretch, 1), "rsi": _r(rsi), "ok": not down,
                        "text": (f"Below a falling 200-day average (₹{s200:,.0f})" if down else
                                 f"{trend}, strong: stretched above its 50-day average — expect swings" if hot else
                                 f"{trend}, not falling")}

    # 4. events - a warning only (not backtested)
    soon = results_in_days is not None and 0 <= results_in_days <= RESULTS_DAYS
    checks["events"] = {"ok": not soon, "text": (f"Results in {results_in_days} day(s) — expect a bigger move; not part of the tested rules"
                                                 if soon else "No results in the next 7 days")}

    if gate_fail:
        verdict, label, rule = "AVOID", "Avoid for now", "avoid_business"
        reasons.append(gate_fail)
    elif down:
        verdict, label, rule = "AVOID", "Avoid for now — below a falling 200-day average", "avoid_falling"
        reasons.append("The price is below its 200-day average, and that average is falling. Prefer stocks that are "
                       "not falling; there is no buy level to wait for (the track record below shows how this rule did).")
    elif hot:
        verdict, label, rule = "ENTER", "Enter — strong trend, expect swings", "enter_stretched"
        reasons.append(f"A strong trend: the price is {stretch:.1f} ATRs above its 50-day average"
                       + (f" and RSI is {rsi:.0f}" if rsi and rsi > HOT_RSI else "")
                       + ". Short dips are likely, but the tested rules do not say to wait for them.")
    else:
        verdict, label, rule = "ENTER", "Enter now", "enter"
        reasons.append("Not in a downtrend; nothing in the tested rules argues for waiting.")
    if soon and verdict != "AVOID":
        reasons.append(f"Results are due in {results_in_days} day(s); the price may move sharply either way.")

    return {
        "verdict": verdict, "rule": rule, "label": label, "price": round(px, 2), "date": bars[i]["t"],
        "review_if": {"below": round(s200, 2), "falling": bool(s200_prev is not None and s200 < s200_prev)},
        "checks": checks, "reasons": reasons, "rules_version": RULES_VERSION,
        "levels": {"sma50": _r(s50, 2), "sma200": _r(s200, 2), "atr": _r(atr, 2),
                   "value_edges": {k: _r(px * edges[k] / pe_now, 2) for k in ("cheap", "fair", "full")} if edges and pe_now else None},
    }
