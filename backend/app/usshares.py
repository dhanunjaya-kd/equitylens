"""Shares outstanding for US companies, from their own SEC filings (one request per quarter for all companies).

SEC's XBRL "frames" give, for every filer, the cover-page figure dei:EntityCommonStockSharesOutstanding for a
calendar quarter. The newest of the last 8 quarters is kept per company. Market cap = those shares x last close.
Skipped on purpose (no market cap rather than a wrong one):
  * companies that report shares only per share class (they are not in the frames), and
  * any company with more than one ticker in the list (e.g. two share classes), so it is never counted twice.
"""
from __future__ import annotations

import datetime as dt
import time
from typing import Optional

from . import config, store, us

FRAME_URL = "https://data.sec.gov/api/xbrl/frames/dei/EntityCommonStockSharesOutstanding/shares/CY{y}Q{q}I.json"
KEY = "SHARES::US"
TTL = 7 * 86400
QUARTERS = 8
STATE = {"error": None, "fetched": None, "running": False}


def quarters(today: dt.date, n: int = QUARTERS) -> list[tuple[int, int]]:
    """The n most recent calendar quarters, newest first (the current one included)."""
    y, q = today.year, (today.month - 1) // 3 + 1
    out = []
    for _ in range(n):
        out.append((y, q))
        q -= 1
        if q == 0:
            y, q = y - 1, 4
    return out


def parse_frames(frames: list[dict]) -> dict:
    """{cik: {"n": shares, "end": date}} keeping the newest figure per company."""
    best: dict = {}
    for fr in frames:
        for p in (fr or {}).get("data") or []:
            try:
                cik, val, end = int(p["cik"]), float(p["val"]), str(p.get("end") or "")
            except (KeyError, TypeError, ValueError):
                continue
            if val > 0 and (cik not in best or end > best[cik]["end"]):
                best[cik] = {"n": val, "end": end}
    return best


def _saved_best() -> Optional[dict]:
    hit = store.get_company(KEY)
    return ({int(k): v for k, v in hit[1]["best"].items()}, hit[0]) if hit else None


def _fetch() -> None:
    try:
        frames = []
        for y, q in quarters(dt.date.today()):
            try:
                frames.append(us._get_json(FRAME_URL.format(y=y, q=q)))
            except Exception as e:  # noqa: BLE001 - a quarter not published yet, or SEC unreachable
                STATE["error"] = str(e)
        best = parse_frames(frames)
        if best:
            store.put_company(KEY, {"best": {str(k): v for k, v in best.items()}})
            STATE.update(error=None, fetched=time.time())
    finally:
        STATE["running"] = False


def by_ticker(symbols: list[str]) -> dict:
    """{'US:XYZ': shares} for the given symbols. Fetches from SEC in the background when missing or a week old;
    returns what is saved meanwhile (empty the first time)."""
    if config.DEMO:
        return {}
    saved = _saved_best()
    if (not saved or time.time() - saved[1] > TTL) and not STATE["running"]:
        import threading
        STATE["running"] = True
        threading.Thread(target=_fetch, daemon=True).start()
    if not saved:
        return {}
    best = saved[0]
    cik_of = {t["ticker"]: t["cik"] for t in us.tickers()}
    wanted = {s: cik_of.get(s.replace("US:", "").replace(".", "-").upper()) or cik_of.get(s.replace("US:", "").upper()) for s in symbols}
    count: dict = {}
    for c in wanted.values():
        if c:
            count[c] = count.get(c, 0) + 1
    return {s: best[c]["n"] for s, c in wanted.items() if c and count[c] == 1 and c in best}


def status() -> dict:
    return dict(STATE)
