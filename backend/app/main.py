"""EquityLens API + web app (one process)."""
from __future__ import annotations

import logging
import time
from typing import Optional

import requests

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import ai, config, movers, scraper, service, store, technicals, universe, us

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
        return service.build_report(symbol, refresh=refresh)
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
        rows = [r for r in rows if r.get("market", "IN") == market.upper()]
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
