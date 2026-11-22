"""Which stocks foreign (FII) and domestic (DII) institutions added or cut last quarter.

Read from the quarterly shareholding table of every Indian stock EquityLens has already scanned (screener.in,
taken from the company's own filings with the exchange). Nothing new is downloaded. Change = latest quarter's
holding minus the quarter before, in percentage points of the company's shares. Stocks are compared only within
the same latest quarter, because companies file at different times.
"""
from __future__ import annotations

import threading
import time
from collections import Counter
from typing import Optional

from . import store

KEY = "INSTHOLD::v1"
_build = {"running": False}


def _row(tbl: dict, *names: str) -> list:
    rows = (tbl or {}).get("rows") or {}
    for n in names:
        for label, vals in rows.items():
            if label.lower().replace("+", "").strip() == n.lower():
                return vals
    for n in names:
        for label, vals in rows.items():
            if label.lower().startswith(n.lower()):
                return vals
    return []


def _ok(v) -> bool:
    return isinstance(v, (int, float))


def stock_change(company: dict) -> Optional[dict]:
    """-> {quarter, prev_quarter, fii, fii_chg, dii, dii_chg} from the quarterly shareholding table, or None."""
    t = (company.get("tables") or {}).get("shareholding_quarterly") or {}
    cols = t.get("columns") or []
    fii, dii = _row(t, "FIIs", "FII"), _row(t, "DIIs", "DII")
    if len(cols) < 2 or not (fii or dii):
        return None
    i = len(cols) - 1

    def pair(vals):
        if len(vals) <= i or not _ok(vals[i]) or not _ok(vals[i - 1]):
            return None, None
        return round(vals[i], 2), round(vals[i] - vals[i - 1], 2)
    f, fc = pair(fii)
    d, dc = pair(dii)
    if fc is None and dc is None:
        return None
    return {"quarter": cols[i], "prev_quarter": cols[i - 1], "fii": f, "fii_chg": fc, "dii": d, "dii_chg": dc}


def build() -> dict:
    ranks = {r["symbol"]: r for r in store.all_rankings() if not str(r["symbol"]).startswith("US:")}
    rows = []
    for sym, r in ranks.items():
        hit = store.get_company(sym)
        if not hit:
            continue
        c = stock_change((hit[1] or {}).get("company") or {})
        if c:
            rows.append(dict(c, symbol=sym, name=r.get("name"), sector=r.get("sector") or r.get("broad_sector") or "",
                             mcap=r.get("market_cap"), score=r.get("overall")))
    q = Counter(x["quarter"] for x in rows)
    out = {"built": time.time(), "stamp": _stamp(), "scanned": len(ranks), "rows": rows,
           "quarters": q.most_common(), "latest": q.most_common(1)[0][0] if q else None}
    store.put_company(KEY, out)
    return out


def _stamp() -> str:
    rs = store.all_rankings()
    return f"{len(rs)}:{round(max((r['updated_at'] for r in rs), default=0))}"


def _bg():
    try:
        build()
    finally:
        _build["running"] = False


def get(quarter: Optional[str] = None, limit: int = 25) -> dict:
    hit = store.get_company(KEY)
    data = hit[1] if hit else None
    if (data is None or data.get("stamp") != _stamp()) and not _build["running"]:
        _build["running"] = True                 # (re)read in the background; the saved answer is shown meanwhile
        threading.Thread(target=_bg, daemon=True).start()
    if data is None:
        return {"building": True, "scanned": len([r for r in store.all_rankings() if not str(r["symbol"]).startswith("US:")])}
    q = quarter or data.get("latest")
    rows = [r for r in data["rows"] if r["quarter"] == q]

    def top(key, rev):
        xs = [r for r in rows if r[key + "_chg"] is not None]
        xs.sort(key=lambda r: r[key + "_chg"], reverse=rev)
        return [r for r in xs if (r[key + "_chg"] > 0 if rev else r[key + "_chg"] < 0)][:limit]
    fi = [r for r in rows if r["fii_chg"] is not None]
    di = [r for r in rows if r["dii_chg"] is not None]
    return {"quarter": q, "prev_quarter": rows[0]["prev_quarter"] if rows else None, "quarters": data.get("quarters", []),
            "scanned": data.get("scanned", 0), "in_quarter": len(rows),
            "fii_up": top("fii", True), "fii_down": top("fii", False), "dii_up": top("dii", True), "dii_down": top("dii", False),
            "summary": {"fii": {"up": sum(1 for r in fi if r["fii_chg"] > 0), "down": sum(1 for r in fi if r["fii_chg"] < 0), "n": len(fi)},
                        "dii": {"up": sum(1 for r in di if r["dii_chg"] > 0), "down": sum(1 for r in di if r["dii_chg"] < 0), "n": len(di)}},
            "updating": _build["running"]}
