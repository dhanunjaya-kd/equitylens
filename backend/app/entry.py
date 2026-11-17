"""Entry decision engine: is this a good time and price to buy, for a 1-3 year holding?

One set of fixed rules, used both live on the stock page and in tools/entry_backtest.py,
so the track record shown on the page is the track record of exactly these rules.

Four checks:
  1. Business  - EquityLens business score and red flags (live only; history isn't available)
  2. Value     - today's P/E against the stock's OWN earlier P/E history (percentile),
                 and, live, also against the fair-value range; the more cautious one wins
  3. Timing    - trend (200-day average), stretch above the 50-day average (in ATRs), RSI
  4. Events    - results within 7 days

Answers: ENTER (buy now) · PARTS (buy in 3 parts at set levels) · WAIT (with a buy zone) · AVOID.
"""
from __future__ import annotations

import bisect
from typing import Optional

# --- rule constants: chosen up front, not tuned on results -------------------------------
CHEAP, FAIR, FULL = 0.30, 0.60, 0.85        # P/E percentile edges: cheap < 30% < fair < 60% < full < 85% < expensive
MIN_PE_POINTS = 100                         # ~3 years of P/E history before the value check is trusted
STRETCH_ATR = 3.0                           # more than 3 ATRs above the 50-day average = stretched
HOT_RSI = 75
RESULTS_DAYS = 7
GOOD_BUSINESS = 55                          # below this the business check fails (same line as the verdict's "weak")
STATES = ["Cheap", "Fair", "Full", "Expensive"]


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


def _supports(h, l, c, i, lookback=250, k=5):
    """Swing lows below today's price, nearest first (only bars up to i)."""
    px = c[i]
    lows = []
    for j in range(max(k, i - lookback), i - k + 1):
        if l[j] == min(l[j - k:j + k + 1]) and l[j] < px * 0.995:
            lows.append(l[j])
    return sorted(set(round(x, 2) for x in lows), reverse=True)


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
    if s200 is None or atr is None:
        return {"verdict": "NA", "label": "Not enough price history", "reasons": ["Needs about 1 year of prices."]}

    reasons, checks = [], {}

    # 1. business (live only)
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

    # 2. value
    st_pe, pct, edges = pe_state(pe_hist or [], pe_now)
    st_fv = fv_state(px, fair_value)
    states = [s for s in (st_pe, st_fv) if s]
    state = max(states, key=STATES.index) if states else None          # the more cautious one
    why = []
    if st_pe:
        why.append(f"P/E {st_pe.lower()} vs its own history ({pct * 100:.0f}th percentile)")
    if st_fv:
        why.append(f"{st_fv.lower()} vs fair value")
    checks["value"] = {"state": state, "pe_state": st_pe, "fv_state": st_fv,
                       "pe_percentile": _r(pct * 100 if pct is not None else None),
                       "ok": state in ("Cheap", "Fair") if state else None,
                       "text": (f"{state} — {'; '.join(why)}" if state else "Value not available")}

    # 3. timing
    down = px < s200 and s200_prev is not None and s200 < s200_prev
    up = px > s200 and s50 is not None and s50 > s200
    stretch = (px - s50) / atr if s50 else 0
    hot = stretch > STRETCH_ATR or (rsi is not None and rsi > HOT_RSI)
    trend = "Uptrend" if up else "Downtrend" if down else "Sideways"
    checks["timing"] = {"trend": trend, "stretch_atr": _r(stretch, 1), "rsi": _r(rsi),
                        "ok": (not hot) and not down,
                        "text": ("Stretched above its trend" if hot else f"{trend}, not stretched")}

    # 4. events
    soon = results_in_days is not None and 0 <= results_in_days <= RESULTS_DAYS
    checks["events"] = {"ok": not soon, "text": f"Results in {results_in_days} day(s)" if soon else "No results in the next 7 days"}

    sup = _supports(h, l, c, i)
    exit_if = min(s200 * 0.90, sup[-1] if sup else s200 * 0.90)

    def value_price(edge):          # price at which the P/E would sit at that edge
        return px * edges[edge] / pe_now if edges and pe_now else None

    def zone_near_trend():
        hi = s50 + 0.5 * atr
        return [max(hi - 1.5 * atr, 0.01), hi]

    plan = None
    if gate_fail:
        verdict, label, zone = "AVOID", "Avoid for now", None
        rule = "avoid_business"
        reasons.append(gate_fail)
    elif soon and state != "Cheap":
        verdict, label, zone = "WAIT", "Wait for the results", None
        rule = "wait_results"
        reasons.append(f"Results are due in {results_in_days} day(s); a surprise can move the price a lot. Decide after them.")
    elif state == "Expensive":
        top = value_price("fair")
        zone = [top * 0.97, top] if top and top < px else zone_near_trend()
        verdict, label = "WAIT", "Wait — price is expensive"
        rule = "wait_expensive"
        reasons.append("The P/E is higher than most of its own history; returns from here depend on everything going right.")
    elif hot:
        zone = zone_near_trend()
        cap = value_price("full")
        if cap and cap < zone[1]:
            zone = [min(zone[0], cap * 0.97), cap]
        verdict, label = "WAIT", "Wait — stretched above its trend"
        rule = "wait_stretched"
        reasons.append(f"The price is {stretch:.1f} ATRs above its 50-day average" + (f" and RSI is {rsi:.0f}" if rsi and rsi > HOT_RSI else "") +
                       "; prices that stretched usually come back toward the average.")
    elif state in ("Cheap", "Fair") or state is None:
        if down:
            verdict, label, zone = "PARTS", "Enter in parts — still falling", None
            rule = "parts_falling"
            t2 = next((s for s in sup if s <= px - atr), px - 1.5 * atr)
            t3 = next((s for s in sup if s <= t2 - atr), t2 - 1.5 * atr)
            plan = [{"pct": 40, "price": px}, {"pct": 30, "price": t2}, {"pct": 30, "price": t3}]
            reasons.append("Good value, but the price is below a falling 200-day average. Buying in steps avoids putting everything in before the fall ends.")
        else:
            verdict, label, zone = "ENTER", "Enter now", None
            rule = "enter"
            reasons.append("Reasonable value and a healthy trend; nothing argues for waiting.")
    else:   # Full
        if up:
            verdict, label, zone = "PARTS", "Enter in parts — fully priced", None
            rule = "parts_full_uptrend"
            t2 = min(s50, px - atr)            # never a "buy more" level above today's price
            plan = [{"pct": 40, "price": px}, {"pct": 30, "price": t2}, {"pct": 30, "price": t2 - atr}]
            reasons.append("Strong uptrend, but the price already asks a lot. Start small and add the rest only on dips."
                           if px >= s50 else
                           "Uptrend, now dipping below its 50-day average, but the price already asks a lot. Start small and add lower.")
        else:
            top = value_price("fair")
            zone = [top * 0.97, top] if top and top < px else zone_near_trend()
            verdict, label = "WAIT", "Wait — fully priced, no trend support"
            rule = "wait_full_no_trend"
            reasons.append("Fully priced without an uptrend behind it; a better price is likely.")

    if plan:   # each later part strictly lower than the one before, at least 1 ATR apart
        for k in (1, 2):
            plan[k]["price"] = min(plan[k]["price"], plan[k - 1]["price"] - atr)

    if verdict == "WAIT" and zone is None and state != "Cheap":
        zone = zone_near_trend()
    if zone:
        zone = [round(min(zone), 2), round(max(zone), 2)]
        if zone[1] >= px:      # the zone must be below today's price to mean "wait"
            zone = [round(px * 0.95, 2), round(px * 0.98, 2)]
        label += f" · buy zone ₹{zone[0]:,.0f}–{zone[1]:,.0f}"

    score_val = (1 - pct) * 100 if pct is not None else 50
    score_tim = (60 if not down else 20) + (0 if hot else 40)
    conviction = round(0.4 * (business if business is not None else 60) + 0.35 * score_val + 0.25 * score_tim)

    return {
        "verdict": verdict, "rule": rule, "label": label, "price": round(px, 2), "date": bars[i]["t"],
        "zone": zone, "plan": [{"pct": p["pct"], "price": round(p["price"], 2)} for p in plan] if plan else None,
        "exit_if": round(exit_if, 2), "checks": checks, "reasons": reasons, "conviction": conviction,
        "levels": {"sma50": _r(s50, 2), "sma200": _r(s200, 2), "atr": _r(atr, 2), "supports": sup[:3],
                   "value_edges": {k: _r(value_price(k), 2) for k in ("cheap", "fair", "full")} if edges else None},
    }
