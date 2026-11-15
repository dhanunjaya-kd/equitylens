"""EquityLens API + web app (one process)."""
from __future__ import annotations

import logging
import time
from typing import Optional

import requests

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import ai, calendars, config, enrich, flows, indices, logos, movers, scraper, service, store, technicals, universe, us

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
store.init()

app = FastAPI(title="EquityLens", version="1.0.0")
app.add_middleware(GZipMiddleware, minimum_size=2000)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/api/health")
def health():
    return {"ok": True, "cached_companies": store.count_companies(), "scan": service.scan_status()}


@app.get("/api/search")
def search(q: str = Query(..., min_length=1), market: str = "IN"):
    if market.upper() == "US":
        try:
            return {"results": us.search(q), "source": "sec"}
        except us.USFetchError as e:
            raise HTTPException(502, str(e))
    try:
        res = scraper.search(q)
        if res:
            return {"results": res[:12], "source": "live"}
    except Exception as e:  # noqa: BLE001
        logging.warning("search failed, using local list: %s", e)
    return {"results": universe.local_search(q), "source": "local"}


@app.get("/api/stock/{symbol}")
def stock(symbol: str, refresh: bool = False):
    try:
        rep = service.build_report(symbol, refresh=refresh)
        rep["fno"] = enrich.fno_info(rep.get("symbol") or symbol)
        return rep
    except scraper.NotFound:
        raise HTTPException(404, f"'{symbol}' not found. Search by company name and pick from the list.")
    except us.USFetchError as e:
        raise HTTPException(404 if ("isn't a US-listed" in str(e) or "Not found" in str(e)) else 502, str(e))
    except scraper.FetchError as e:
        raise HTTPException(502, str(e))


@app.get("/api/chart/{symbol}")
def chart(symbol: str, interval: str = "1d", refresh: bool = False):
    if interval not in ("1d", "1wk"):
        raise HTTPException(400, "interval must be 1d or 1wk")
    try:
        return technicals.build(symbol, interval, refresh)
    except scraper.FetchError as e:
        raise HTTPException(502, str(e))


# ------------------------------------------------------------ AI
def _report_and_tech(symbol: str):
    try:
        rep = service.build_report(symbol)
    except (scraper.FetchError, us.USFetchError) as e:
        raise HTTPException(502, str(e))
    try:
        tech = technicals.build(rep["symbol"])
    except Exception:  # noqa: BLE001 - technicals are optional context
        tech = None
    return rep, tech


def _ai(fn, *args, **kw):
    try:
        return fn(*args, **kw)
    except ai.AIError as e:
        raise HTTPException(400, str(e))


@app.get("/api/ai/settings")
def ai_settings():
    return ai.public_settings()


@app.post("/api/ai/settings")
def ai_settings_save(body: dict = Body(...)):
    return ai.save_settings(body)


@app.get("/api/ai/gemini-models")
def ai_gemini_models():
    return {"models": _ai(ai.list_gemini_models)}


@app.post("/api/ai/test")
def ai_test():
    t = time.time()
    txt = _ai(ai.complete, "You are a connection test.", [{"role": "user", "content": "Reply with just: OK"}], 20)
    return {"ok": True, "reply": txt[:60], "model": ai.model_label(), "seconds": round(time.time() - t, 1)}


@app.post("/api/ai/note/{symbol}")
def ai_note(symbol: str, refresh: bool = False):
    rep, tech = _report_and_tech(symbol)
    return _ai(ai.research_note, rep, tech, refresh)


@app.post("/api/ai/chat/{symbol}")
def ai_chat(symbol: str, body: dict = Body(...)):
    rep, tech = _report_and_tech(symbol)
    return _ai(ai.chat, rep, tech, body.get("messages") or [])


@app.post("/api/ai/guidance/{symbol}")
def ai_guidance(symbol: str, refresh: bool = False):
    rep, _ = _report_and_tech(symbol)
    return _ai(ai.guidance_check, rep, refresh)


@app.post("/api/ai/debate/{symbol}")
def ai_debate(symbol: str, refresh: bool = False):
    rep, tech = _report_and_tech(symbol)
    return _ai(ai.debate, rep, tech, refresh)


@app.post("/api/ai/doc/{symbol}")
def ai_doc(symbol: str, body: dict = Body(...)):
    url = body.get("url") or ""
    if not url.startswith("http"):
        raise HTTPException(400, "Missing document link.")
    rep, _ = _report_and_tech(symbol)
    allowed = {it.get("url") for g in rep["company"].get("documents", []) for it in g["items"]} | {
        l["url"] for g in rep["company"].get("documents", []) for it in g["items"] for l in it.get("links", [])}
    if url not in allowed:
        raise HTTPException(400, "Only this stock's own report links can be read.")
    try:
        return _ai(ai.read_document, rep, url, body.get("title", ""))
    except requests.RequestException as e:
        raise HTTPException(502, f"Couldn't download the document: {e.__class__.__name__}")


@app.post("/api/ai/chart/{symbol}")
def ai_chart(symbol: str, interval: str = "1d"):
    rep, _ = _report_and_tech(symbol)
    try:
        tech = technicals.build(rep["symbol"], interval)
    except scraper.FetchError as e:
        raise HTTPException(502, str(e))
    return _ai(ai.explain_chart, rep, tech)


@app.post("/api/ai/picks")
def ai_picks(body: dict = Body(...)):
    syms = [s.upper() for s in body.get("symbols") or []][:15]
    rows = {r["symbol"]: r for r in store.all_rankings()}
    picked = [rows[s] for s in syms if s in rows]
    if not picked:
        raise HTTPException(400, "No scanned stocks to explain. Run a scan first.")
    return _ai(ai.explain_picks, picked, body.get("title") or "Top Picks")


@app.get("/api/movers")
def movers_get(market: str = "IN", tf: str = "1D"):
    return movers.get(market, tf)


@app.post("/api/movers/refresh")
def movers_refresh(market: str = "IN"):
    return movers.refresh(market.upper())


@app.post("/api/ai/movers")
def ai_movers(market: str = "IN", tf: str = "1D"):
    data = movers.get(market, tf)
    if not data["rows"]:
        raise HTTPException(400, "Movers are still loading. Try again in a minute.")
    return _ai(ai.explain_movers, data)


def _start(start: Optional[str]):
    from datetime import date, datetime
    if not start:
        return datetime.now(calendars.IST).date()
    try:
        return date.fromisoformat(start)
    except ValueError:
        raise HTTPException(400, "start must be YYYY-MM-DD")


@app.get("/api/calendar/earnings")
def cal_earnings(market: str = "US", start: Optional[str] = None, days: int = 7):
    return calendars.earnings(market, _start(start), days)


@app.get("/api/calendar/economy")
def cal_economy(market: str = "US", start: Optional[str] = None, days: int = 7):
    return calendars.economy(market, _start(start), days)


@app.get("/api/calendar/next/{symbol}")
def cal_next(symbol: str):
    return {"next": calendars.next_results(scraper.clean_symbol(symbol))}


@app.post("/api/ai/calendar")
def ai_calendar(market: str = "US", start: Optional[str] = None, days: int = 7, symbols: str = ""):
    s = _start(start)
    e, c = calendars.earnings(market, s, days), calendars.economy(market, s, days)
    watch = {x.strip().upper() for x in symbols.split(",") if x.strip()}
    return _ai(ai.explain_calendar, e, c, watch)


def _flow(fn, *a):
    try:
        return fn(*a)
    except flows.FlowError as e:
        raise HTTPException(503, str(e))


@app.get("/api/flows/stock/{symbol}")
def flows_stock(symbol: str):
    return flows.for_stock(scraper.clean_symbol(symbol))


@app.get("/api/flows/delivery")
def flows_delivery(only_index: bool = True, min_turnover: float = 5.0, fno: bool = False):
    d = _flow(flows.delivery)
    names = {u["symbol"]: u.get("name") for u in movers._universe("IN")}
    lots = enrich.fno()
    src = {**d, "rows": [r for r in d["rows"] if r["symbol"] in lots]} if fno else d
    lists = flows.delivery_lists(src, only_index and not fno, min_turnover)
    for rows in lists.values():
        for r in rows:
            r["name"] = names.get(r["symbol"]) or r["symbol"]
            r["fno"] = r["symbol"] in lots
    return {"date": d["date"], "days": d["days"], "lists": {k: v[:80] for k, v in lists.items()}, "source": d["source"]}


@app.get("/api/flows/deals")
def flows_deals():
    d = _flow(flows.deals)
    lots = enrich.fno()
    return {**d, "rows": [{**r, "fno": r["symbol"] in lots} for r in d["rows"]]}


@app.get("/api/flows/insiders")
def flows_insiders(market: str = "IN", days: int = 30, symbols: str = ""):
    if market.upper() == "US":
        syms = [scraper.clean_symbol(s) for s in symbols.split(",") if s.strip()]
        top = [r["symbol"] for r in sorted((r for r in store.all_rankings() if r.get("market") == "US"), key=lambda r: -(r.get("overall") or 0))[:15]]
        syms = list(dict.fromkeys([s for s in syms if s.startswith("US:")] + top))
        return flows.insiders_us_many(syms)
    d = _flow(flows.insiders_in, max(7, min(days, 90)))
    lots = enrich.fno()
    return {**d, "rows": [{**r, "fno": r["symbol"] in lots} for r in d["rows"]]}


@app.get("/api/flows/surveillance")
def flows_surveillance():
    d = _flow(flows.surveillance)
    names = {u["symbol"]: u.get("name") for u in movers._universe("IN")}
    lots = enrich.fno()
    rows = [{"symbol": s, "name": names.get(s) or s, "in_index": s in names, "fno": s in lots, "flags": f} for s, f in d["flags"].items()]
    rows.sort(key=lambda r: (not r["in_index"], -sum(x["severity"] == "high" for x in r["flags"])))
    return {"date": d["date"], "rows": rows, "source": d["source"]}


@app.get("/api/fno")
def fno_list():
    lots = enrich.fno()
    return {"count": len(lots), "lots": lots, "source": "NSE F&O market lots file"}


@app.get("/api/indices")
def indices_get(market: str = "IN"):
    return indices.get(market)


@app.get("/api/logo/{symbol}")
def logo(symbol: str, name: str = ""):
    data, media = logos.get(scraper.clean_symbol(symbol), name)
    return Response(content=data, media_type=media, headers={"Cache-Control": "public, max-age=604800"})


@app.get("/api/compare")
def compare(symbols: str):
    out = []
    for s in [x.strip() for x in symbols.split(",") if x.strip()][:4]:
        try:
            r = service.build_report(s)
            out.append({"symbol": r["symbol"], "name": r["company"]["name"], "analysis": r["analysis"]})
        except Exception as e:  # noqa: BLE001
            out.append({"symbol": s, "error": str(e)})
    return {"items": out}


@app.get("/api/rankings")
def rankings(sort: str = "overall", verdict: Optional[str] = None, min_mcap: float = 0, q: Optional[str] = None,
             market: Optional[str] = None):
    rows = store.all_rankings()
    if market:
        rows = enrich.join_all([r for r in rows if r.get("market", "IN") == market.upper()], market.upper())
    if verdict:
        rows = [r for r in rows if r.get("verdict") == verdict]
    if min_mcap:
        rows = [r for r in rows if (r.get("market_cap") or 0) >= min_mcap]
    if q:
        ql = q.lower()
        rows = [r for r in rows if ql in (r.get("symbol") or "").lower() or ql in (r.get("name") or "").lower()
                or ql in (r.get("sector") or "").lower()]
    rows.sort(key=lambda r: (r.get(sort) is None, -(r.get(sort) or 0)))
    return {"rows": rows, "count": len(rows), "scan": service.scan_status()}


@app.post("/api/scan/start")
def scan_start(limit: Optional[int] = None, market: str = "IN"):
    return service.start_scan(limit, market=market.upper())


@app.post("/api/scan/stop")
def scan_stop():
    return service.stop_scan()


@app.get("/api/scan/status")
def scan_status():
    return service.scan_status()


# ------------------------------------------------------------ web app
if (config.STATIC_DIR / "index.html").exists():
    app.mount("/assets", StaticFiles(directory=config.STATIC_DIR / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        f = config.STATIC_DIR / path
        if path and f.is_file():
            return FileResponse(f)
        return FileResponse(config.STATIC_DIR / "index.html")
else:
    @app.get("/")
    def no_ui():
        return JSONResponse({"message": "API running. Frontend not built: run `npm run build` in frontend/."})
