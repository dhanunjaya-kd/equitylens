"""Extra live fields joined onto every list (rankings / screener, movers, calendar, smart money).

* F&O membership + lot size  — NSE market-lots file (nsearchives.nseindia.com/content/fo/fo_mktlots.csv)
* Trend & momentum            — from the Market Movers price cache
* Delivery, insiders, surveillance — from the Smart Money caches
Everything here reads caches only (except the weekly F&O download), so joining is instant.
"""
from __future__ import annotations

import csv
import io
import time
from typing import Optional

from . import config, store

FNO_URL = "https://nsearchives.nseindia.com/content/fo/fo_mktlots.csv"
INDEX_SYMBOLS = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50", "SENSEX", "BANKEX"}
_mem: dict = {}


def parse_fno(text: str) -> dict:
    out = {}
    for r in csv.reader(io.StringIO(text.lstrip("﻿"))):
        if len(r) < 2:
            continue
        sym = r[1].strip().upper()
        if not sym or sym == "SYMBOL" or sym in INDEX_SYMBOLS or "NIFTY" in sym:
            continue
        lot = None
        for c in r[2:]:
            c = c.strip().replace(",", "")
            if c.isdigit():
                lot = int(c)
                break
        out[sym] = lot
    return out


def fno() -> dict:
    """{symbol: lot size} for every NSE stock with futures & options. Refreshed weekly."""
    if _mem.get("t", 0) > time.time() - 3600 and "fno" in _mem:
        return _mem["fno"]
    hit = store.get_company("FNO::list")
    if hit and time.time() - hit[0] < 7 * 86400:
        _mem.update(t=time.time(), fno=hit[1]["lots"])
        return hit[1]["lots"]
    try:
        if config.DEMO:
            from . import movers
            syms = [u["symbol"] for u in movers._universe("IN")]
            lots = {s: 250 * (1 + i % 6) for i, s in enumerate(syms) if i % 3 == 0}
        else:
            from . import flows
            text = flows._nse_text(FNO_URL)
            lots = parse_fno(text) if text else {}
        if lots:
            store.put_company("FNO::list", {"lots": lots})
    except Exception:  # noqa: BLE001 - keep the old list if NSE is unreachable
        lots = hit[1]["lots"] if hit else {}
    _mem.update(t=time.time(), fno=lots)
    return lots


def fno_info(sym: str) -> Optional[dict]:
    if sym.startswith("US:"):
        return None
    lots = fno()
    return {"lot": lots[sym]} if sym in lots else None


def _cache(key: str):
    hit = store.get_company(key)
    return hit[1] if hit else None


def live_maps(market: str) -> dict:
    """Read every live cache once; reuse for a whole list."""
    mv = _cache(f"MOVERS::{market}") or {}
    out = {"mv": {r["symbol"]: r for r in mv.get("rows", [])}, "fno": fno() if market == "IN" else {}}
    if market == "IN":
        dl = _cache("DELIVERY::IN") or {}
        out["dl"] = {r["symbol"]: r for r in dl.get("rows", [])}
        sv = _cache("SURV::IN") or {}
        out["sv"] = sv.get("flags", {})
        pit = _cache("PIT::IN::30") or _cache("PIT::IN::90") or {}
        ins: dict = {}
        for r in pit.get("rows", []):
            if r.get("market") and r["side"] in ("BUY", "SELL"):
                d = ins.setdefault(r["symbol"], {"net": 0.0, "prom_buy": False})
                d["net"] += (r.get("value") or 0) * (1 if r["side"] == "BUY" else -1)
                d["prom_buy"] |= bool(r.get("promoter") and r["side"] == "BUY")
        out["ins"] = ins
    else:
        out["ins"] = {}
        for k in store.keys_like("FORM4::US:%"):
            d = _cache(k) or {}
            s = d.get("summary")
            if s:
                out["ins"][d["symbol"]] = {"net": s.get("net_value") or 0.0, "prom_buy": bool(s.get("cluster"))}
    return out


def join(row: dict, maps: dict) -> dict:
    sym = row["symbol"]
    m = maps["mv"].get(sym)
    if m:
        ret = m.get("ret") or {}
        row.update(ret_1w=ret.get("1W"), ret_1m=ret.get("1M"), ret_3m=ret.get("3M"), ret_1y=ret.get("1Y"),
                   above50=bool(m.get("above50")), above200=bool(m.get("above200")), near_high=m.get("from_hi"),
                   rvol=m.get("rvol"), new_high=bool(m.get("new_high")))
    if maps["fno"]:
        row["fno"] = sym in maps["fno"]
        row["lot"] = maps["fno"].get(sym)
    d = maps.get("dl", {}).get(sym)
    if d:
        row.update(dp=d.get("dp"), deliv_x=d.get("dq_x"))
    if "sv" in maps:
        flags = maps["sv"].get(sym) or []
        row["surveillance"] = bool(flags)
        row["surv_labels"] = [f["label"] for f in flags] or None
    i = maps["ins"].get(sym)
    row["insider_net"] = round(i["net"], 2) if i else None
    row["insider_buying"] = bool(i and (i["net"] > 0 or i["prom_buy"]))
    return row


def join_all(rows: list[dict], market: str) -> list[dict]:
    maps = live_maps(market)
    return [join(r, maps) for r in rows]
