"""EquityLens API + web app (one process)."""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config, scraper, service, store, technicals, universe

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
store.init()

app = FastAPI(title="EquityLens", version="1.0.0")
app.add_middleware(GZipMiddleware, minimum_size=2000)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/api/health")
def health():
    return {"ok": True, "cached_companies": store.count_companies(), "scan": service.scan_status()}


@app.get("/api/search")
def search(q: str = Query(..., min_length=1)):
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
def rankings(sort: str = "overall", verdict: Optional[str] = None, min_mcap: float = 0, q: Optional[str] = None):
    rows = store.all_rankings()
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
def scan_start(limit: Optional[int] = None):
    return service.start_scan(limit)


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
