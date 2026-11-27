"""Home page 'Today' strip: what matters today, from data the app already keeps (nothing new is downloaded here
except the day's results calendar, which is cached). Each part is independent: one failing leaves the rest."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from . import calendars, store

IST = calendars.IST


def _premarket(day: str) -> Optional[dict]:
    hit = store.get_company(f"PREMARKET::CALL::IN::{day}")
    if not hit:
        return None
    c = hit[1]
    return {"day": day, "call": c.get("call"), "label": c.get("label"), "built": c.get("built")}


def _fiidii() -> Optional[dict]:
    hit = store.get_company("FIIDII::CASH")
    if not hit or not hit[1]:
        return None
    d = max(hit[1])
    row = hit[1][d]
    return {"date": d, "fii": (row.get("fii") or {}).get("net"), "dii": (row.get("dii") or {}).get("net")}


def _ipos(today: str) -> Optional[dict]:
    cur, up = store.get_company("IPO::current::v2"), store.get_company("IPO::upcoming::v2")
    if not cur and not up:
        return None
    items = (cur[1].get("items") if cur else []) or []
    ups = (up[1].get("items") if up else []) or []
    return {"open": len(items), "open_main": sum(1 for x in items if not x.get("sme")),
            "closing_today": [{"symbol": x["symbol"], "company": x["company"], "times": x.get("times"), "sme": x.get("sme")}
                              for x in items if x.get("end") == today],
            "opening_next": [{"symbol": x["symbol"], "company": x["company"], "start": x["start"], "sme": x.get("sme")}
                             for x in sorted(ups, key=lambda x: x.get("start") or "9") if x.get("start") and x["start"] > today][:3]}


def _breadth(market: str) -> Optional[dict]:
    """Advances / declines today across the market list the app keeps (Market Movers data)."""
    from . import movers
    hit = store.get_company(movers._key(market))
    rows = (hit[1].get("rows") if hit else None) or []
    if not rows:
        return None
    m = movers._mood(rows, "1D")
    if not m:
        return None
    return {"advances": m["advances"], "declines": m["declines"], "unchanged": m["unchanged"], "above200": m["above200"],
            "new_highs": m["new_highs"], "new_lows": m["new_lows"], "label": m["label"], "tone": m["tone"],
            "session": max((r.get("date") or "" for r in rows), default="") or None, "count": len(rows)}


def _results(today, mine: set) -> Optional[dict]:
    got = calendars.earnings("IN", today, 1)
    rows = [r for r in got["rows"] if r.get("type") == "Results"]
    return {"count": len(rows), "mine": [r["symbol"] for r in rows if r["symbol"] in mine],
            "top": [{"symbol": r["symbol"], "name": r.get("name")} for r in rows[:5]]}


def get(market: str = "IN", symbols: str = "") -> dict:
    from . import news
    now = datetime.now(IST)
    day = now.date()
    mine = {s.strip().upper() for s in (symbols or "").split(",") if s.strip()}
    out = {"market": market, "now": now.isoformat(timespec="minutes"), "errors": {}}
    parts = {"breaking": lambda: news.breaking_now(market)[:2], "breadth": lambda: _breadth(market)}
    if market == "IN":
        parts.update(premarket=lambda: _premarket(day.isoformat()), fiidii=_fiidii,
                     ipo=lambda: _ipos(day.isoformat()), results=lambda: _results(day, mine))
    for k, f in parts.items():
        try:
            out[k] = f()
        except Exception as e:  # noqa: BLE001 - one part failing leaves the rest
            out[k] = None
            out["errors"][k] = str(e)[:120]
    return out
