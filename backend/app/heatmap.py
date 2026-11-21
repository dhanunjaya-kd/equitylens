"""Heatmap: every stock as a box grouped by its sector, sized by market cap, coloured by % change.

Built only from data EquityLens already has: the daily prices pulled for Market Movers (returns, 52-week
high, 200-day average, relative volume, traded value) and the EquityLens scan (market cap, score).
Nothing is estimated: a stock without a market cap is flagged, never given a guessed size.
"""
from __future__ import annotations

from typing import Optional

from . import movers, pricemap, technicals
from .sectors import UNKNOWN

TFS = list(movers.TF)
# S&P 500 sectors (GICS) -> the official Select Sector SPDR fund for that sector
US_SECTOR_FUND = {
    "Information Technology": ("XLK", "Technology Select Sector SPDR"),
    "Financials": ("XLF", "Financial Select Sector SPDR"),
    "Health Care": ("XLV", "Health Care Select Sector SPDR"),
    "Consumer Discretionary": ("XLY", "Consumer Discretionary Select Sector SPDR"),
    "Consumer Staples": ("XLP", "Consumer Staples Select Sector SPDR"),
    "Energy": ("XLE", "Energy Select Sector SPDR"),
    "Industrials": ("XLI", "Industrial Select Sector SPDR"),
    "Materials": ("XLB", "Materials Select Sector SPDR"),
    "Utilities": ("XLU", "Utilities Select Sector SPDR"),
    "Real Estate": ("XLRE", "Real Estate Select Sector SPDR"),
    "Communication Services": ("XLC", "Communication Services Select Sector SPDR"),
}


def slim(r: dict, tf: str, shares: Optional[dict] = None) -> dict:
    """mcap: the EquityLens scan's market cap, else NSE issued shares x last close (both real); else None."""
    f = r.get("fund") or {}
    mcap, src = f.get("market_cap"), ("scan" if f.get("market_cap") else None)
    n = (shares or {}).get(r["symbol"])
    if not mcap and n and r.get("price"):
        mcap, src = round(n * r["price"] / 1e7, 0), "nse_shares"
    return {"symbol": r["symbol"], "name": r["name"], "sector": r["sector"], "price": r["price"], "date": r.get("date"),
            "ret": r["ret"], "from_hi": r.get("from_hi"), "above50": r.get("above50"), "above200": r.get("above200"),
            "rvol": r.get("rvol"), "value": (r.get("turnover") or {}).get(tf), "mcap": mcap, "mcap_src": src,
            "score": f.get("overall"), "verdict": f.get("verdict"), "tone": f.get("tone"), "fno": r.get("fno")}


def get(market: str, tf: str = "1D", which: str = "") -> dict:
    d = movers.get(market, tf, which)
    tf = d["tf"]
    sh = {}
    if d["market"] == "IN":
        from . import sectors as nse_sectors
        sh = nse_sectors.shares()
    rows = [slim(r, tf, sh) for r in d["rows"]]
    by: dict[str, list] = {}
    for r in rows:
        by.setdefault(r["sector"], []).append(r)
    sectors = []
    for name, rs in by.items():
        vals = [r["ret"].get(tf) for r in rs if r["ret"].get(tf) is not None]
        sectors.append({"sector": name, "count": len(rs), "priced": len(vals),
                        "avg": round(sum(vals) / len(vals), 2) if vals else None,
                        "up": sum(1 for x in vals if x > 0), "down": sum(1 for x in vals if x < 0),
                        "mcap": sum(r["mcap"] or 0 for r in rs), "no_mcap": sum(1 for r in rs if not r["mcap"]),
                        "value": sum(r["value"] or 0 for r in rs)})
    sectors.sort(key=lambda s: (s["sector"] == UNKNOWN, -(s["mcap"] or s["value"] or s["count"])))
    fill = None
    if d["market"] == "IN":
        from . import sectors as nse_sectors
        unknown = [r["symbol"] for r in rows if r["sector"] == UNKNOWN]
        by_size = [r["symbol"] for r in sorted(rows, key=lambda r: -(r["value"] or 0))]   # biggest names first
        nse_sectors.start_fill(by_size)
        fill = dict(nse_sectors.status(), unknown=len(unknown))
    return {"market": d["market"], "tf": tf, "rows": rows, "sectors": sectors, "updated": d["updated"],
            "session": d["session"], "live": d["live"], "status": d["status"], "universe": d["universe"],
            "count": len(rows), "no_mcap": sum(1 for r in rows if not r["mcap"]), "scanned": d["scanned"],
            "sector_fill": fill}


def sector_index(market: str, sector: str) -> Optional[dict]:
    """The closest sector index (India) or the sector's SPDR fund (US), with its fall from the 52-week high."""
    if sector == UNKNOWN:
        return {"index": None, "note": "These stocks have no NSE sector yet."}
    if market == "US":
        m = US_SECTOR_FUND.get(sector)
        st = {"ticker": m[0], "name": m[1]} if m else None
    else:
        st = pricemap.sector_ticker("IN", [sector])
    if not st:
        return {"index": None, "note": f"No sector index matches “{sector}”."}
    out = {"ticker": st["ticker"], "name": st["name"]}
    try:
        bars = pricemap._sector_bars(st["ticker"])
    except Exception as e:  # noqa: BLE001
        return {"index": dict(out, error=f"could not load {st['ticker']}: {e}")}
    if not bars or len(bars) <= pricemap.LOOK:
        return {"index": dict(out, error=f"no price history for {st['ticker']}")}
    c = [b["c"] for b in bars]
    fall = -pricemap.drawdowns(c)[-1] * 100
    s50, s200 = technicals.sma(c, 50)[-1], technicals.sma(c, 200)[-1]
    ret = {tf: (round((c[-1] / c[-1 - k] - 1) * 100, 2) if len(c) > k else None) for tf, k in movers.TF.items()}
    out.update({"last_date": bars[-1]["t"], "fall_pct": round(fall, 1), "stage": pricemap.stage(fall),
                "above50": c[-1] > s50 if s50 else None, "above200": c[-1] > s200 if s200 else None, "ret": ret})
    return {"index": out}
