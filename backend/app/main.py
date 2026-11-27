"""EquityLens API + web app (one process)."""
from __future__ import annotations

import hmac
import secrets
import re
import logging
import os
import threading
import time
from typing import Optional

import requests

from urllib.parse import quote

from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from . import universe as universe_mod
from . import access, accounts, ai, brokers, calendars, config, enrich, flows, portfolio, premarket, indices, logos, movers, scraper, service, store, technicals, universe, us

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
store.init()
accounts.init()
log = logging.getLogger("equitylens")

app = FastAPI(title="EquityLens", version="1.0.0")
app.add_middleware(GZipMiddleware, minimum_size=2000)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
def _background_jobs():
    premarket.start_background()      # builds the pre-market page before the open; refreshes its backtest weekly
    from . import fiidii
    fiidii.start_background()         # saves FII/DII cash figures every evening; fills positions history once
    from . import news
    news.start_background()           # filings, central banks and publishers' feeds every 10 minutes
    from . import jobs
    jobs.start_background()           # data checks run by themselves after each month end, outside market hours


@app.middleware("http")
async def password_gate(request: Request, call_next):
    """Accounts on (any account exists): every /api call needs a signed-in person, and members can't open the
    owner's private pages. Before that: EQL_PASSWORD, when set, guards every /api call (cloud)."""
    path = request.url.path
    if accounts.enabled():
        u = accounts.user_from_token(request.cookies.get(accounts.COOKIE))
        tok = accounts.set_current(u)
        try:
            if not u and not access.is_open(path):
                return JSONResponse({"detail": "Please sign in", "login": True, "accounts": True}, status_code=401)
            if u and not accounts.is_owner(u) and path.startswith(accounts.OWNER_ONLY):
                return JSONResponse({"detail": "Only the owner of this EquityLens can open this."}, status_code=403)
            return await call_next(request)
        finally:
            accounts._current.reset(tok)
    if access.password() and not access.is_open(path) and not access.check(request.cookies.get(access.COOKIE)):
        return JSONResponse({"detail": "Please sign in", "login": True}, status_code=401)
    return await call_next(request)


def _https(request: Request) -> bool:
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"


def _signed_in(u: dict, request: Request, body: Optional[dict] = None, redirect: Optional[str] = None):
    token = accounts.new_session(u["id"], request.headers.get("user-agent", ""))
    r = RedirectResponse(redirect, status_code=303) if redirect else JSONResponse(body or {"ok": True, "user": accounts.public_user(u)})
    r.set_cookie(accounts.COOKIE, token, max_age=accounts.SESSION_DAYS * 86400, httponly=True, samesite="lax", secure=_https(request))
    return r


def _acc(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except accounts.AccountError as e:
        raise HTTPException(e.status, str(e)) from e


def _owner() -> dict:
    u = accounts.current()
    if not u:
        raise HTTPException(401, "Please sign in")
    if not accounts.is_owner(u):
        raise HTTPException(403, "Only the owner of this EquityLens can do this.")
    return u


def _me() -> dict:
    u = accounts.current()
    if not u:
        raise HTTPException(400, "Sign-in isn't turned on in this EquityLens.")
    return u


@app.get("/api/auth")
def auth_status(request: Request):
    if accounts.enabled():
        u = accounts.current()
        return {"required": True, "ok": bool(u), "accounts": True, "user": accounts.public_user(u),
                "github": accounts.public_github()["enabled"]}
    local = access.is_local(request.client.host if request.client else None, request.headers)
    pw_ok = access.check(request.cookies.get(access.COOKIE))
    return {"required": bool(access.password()), "ok": pw_ok, "accounts": False, "user": None, "github": False,
            "can_setup": local or (bool(access.password()) and pw_ok)}


@app.post("/api/auth/setup")
def auth_setup(request: Request, body: dict = Body(...)):
    """Create the owner account (turns sign-in on). Only from this computer, or after the EQL_PASSWORD sign-in."""
    local = access.is_local(request.client.host if request.client else None, request.headers)
    if not (local or (access.password() and access.check(request.cookies.get(access.COOKIE)))):
        raise HTTPException(403, "Turn on sign-in from the computer running EquityLens.")
    u = _acc(accounts.setup_owner, body.get("email"), body.get("name"), body.get("password"))
    log.info("sign-in turned on; owner %s", u["email"])
    return _signed_in(u, request)


@app.post("/api/auth/login")
def auth_login(request: Request, body: dict = Body(...)):
    if not accounts.enabled():
        raise HTTPException(400, "Sign-in isn't turned on yet.")
    ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (request.client.host if request.client else "")
    return _signed_in(_acc(accounts.login, body.get("email"), body.get("password"), ip), request)


@app.post("/api/auth/register")
def auth_register(request: Request, body: dict = Body(...)):
    if not accounts.enabled():
        raise HTTPException(400, "Sign-in isn't turned on yet.")
    return _signed_in(_acc(accounts.register, body.get("email"), body.get("name"), body.get("password")), request)


@app.post("/api/auth/logout")
def auth_logout(request: Request):
    accounts.end_session(request.cookies.get(accounts.COOKIE))
    r = JSONResponse({"ok": True})
    r.delete_cookie(accounts.COOKIE)
    r.delete_cookie(access.COOKIE)
    return r


@app.post("/api/auth/password")
def auth_password(body: dict = Body(...)):
    _acc(accounts.change_password, _me(), body.get("old", ""), body.get("new", ""))
    return {"ok": True}


def _callback_url(request: Request) -> str:
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    return f"{proto}://{host}/api/auth/github/callback"


@app.get("/api/auth/github/start")
def auth_github_start(request: Request):
    gh = accounts.github_settings()
    if not accounts.public_github()["enabled"]:
        raise HTTPException(400, "GitHub sign-in isn't set up. The owner adds it in Settings → Accounts.")
    state = secrets.token_urlsafe(24)
    from urllib.parse import urlencode
    url = "https://github.com/login/oauth/authorize?" + urlencode({"client_id": gh["client_id"], "redirect_uri": _callback_url(request),
                                                                  "scope": "read:user user:email", "state": state, "allow_signup": "false"})
    r = RedirectResponse(url, status_code=303)
    r.set_cookie("eql_gh_state", state, max_age=600, httponly=True, samesite="lax", secure=_https(request))
    return r


@app.get("/api/auth/github/callback")
def auth_github_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    from urllib.parse import quote as _q
    expected = request.cookies.get("eql_gh_state") or ""
    if error or not code or not state or not hmac.compare_digest(state, expected):
        return RedirectResponse("/#/signin?error=" + _q(error or "GitHub sign-in was cancelled or expired. Try again."), status_code=303)
    try:
        gh = accounts.github_user(code, _callback_url(request))
        u = accounts.github_login(gh, signed_in=accounts.current())
    except accounts.AccountError as e:
        return RedirectResponse("/#/signin?error=" + _q(str(e)), status_code=303)
    except Exception as e:  # noqa: BLE001 - GitHub unreachable
        log.warning("GitHub sign-in failed: %s", e)
        return RedirectResponse("/#/signin?error=" + _q("Couldn't reach GitHub. Try again."), status_code=303)
    r = _signed_in(u, request, redirect="/#/account" if accounts.current() else "/")
    r.delete_cookie("eql_gh_state")
    return r


@app.get("/api/auth/github/config")
def auth_github_config_get(request: Request):
    _owner()
    return accounts.public_github() | {"callback_url": _callback_url(request)}


@app.post("/api/auth/github/config")
def auth_github_config_save(request: Request, body: dict = Body(...)):
    _owner()
    return accounts.save_github_settings(body.get("client_id", ""), body.get("client_secret")) | {"callback_url": _callback_url(request)}


@app.get("/api/auth/people")
def auth_people():
    _owner()
    return accounts.people()


@app.post("/api/auth/invites")
def auth_invite(body: dict = Body(...)):
    u = _owner()
    return _acc(accounts.invite, body.get("who", ""), u["id"])


@app.delete("/api/auth/invites/{who}")
def auth_uninvite(who: str):
    _owner()
    accounts.remove_invite(who)
    return {"ok": True}


@app.delete("/api/auth/users/{uid}")
def auth_remove_user(uid: int):
    _acc(accounts.remove_user, uid, _owner())
    return {"ok": True}


@app.get("/api/me/data")
def me_data():
    return accounts.get_data(_me()["id"])


@app.put("/api/me/data/{key}")
def me_data_put(key: str, body=Body(...)):
    _acc(accounts.put_data, _me()["id"], key, body)
    return {"ok": True}


@app.get("/api/me/export")
def me_export():
    return accounts.export(_me())


@app.post("/api/login")
def login(request: Request, body: dict = Body(...)):
    if not access.password():
        return {"ok": True}
    if not hmac.compare_digest(str(body.get("password", "")), access.password()):
        time.sleep(1.5)                                   # slows down guessing
        raise HTTPException(401, "Wrong password")
    r = JSONResponse({"ok": True})
    https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    r.set_cookie(access.COOKIE, access.token(), max_age=90 * 86400, httponly=True, samesite="lax", secure=https)
    return r


@app.post("/api/logout")
def logout(request: Request):
    return auth_logout(request)


@app.post("/api/shutdown")
def shutdown(request: Request):
    """Used by "Stop EquityLens.vbs". Only from this computer."""
    if not access.is_local(request.client.host if request.client else None, request.headers):
        raise HTTPException(403, "Only from this computer")
    log.info("shutdown requested")
    threading.Timer(0.4, lambda: os._exit(0)).start()
    return {"ok": True}


@app.get("/api/network")
def network(request: Request):
    return access.network_info(request.headers.get("host", ""))


@app.get("/api/logs")
def logs(lines: int = 300):
    return access.tail_logs(lines)


def ui_build() -> str | None:
    """Name of the JavaScript bundle the current index.html points to (changes with every build)."""
    try:
        m = re.search(r"assets/(index-[\w-]+\.js)", (config.STATIC_DIR / "index.html").read_text(encoding="utf-8"))
        return m.group(1) if m else None
    except OSError:
        return None


@app.get("/api/health")
def health():
    return {"ok": True, "ui": ui_build(), "cached_companies": store.count_companies(), "scan": service.scan_status()}


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
    return _ai(ai.chat, rep, tech, body.get("messages") or [], str(body.get("focus") or ""))


@app.get("/api/premarket")
def premarket_get(market: str = "IN", refresh: bool = False):
    try:
        return premarket.build(market, refresh)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Pre-market data not available: {e}") from e


@app.post("/api/premarket/backtest")
def premarket_backtest():
    from . import nextday

    def run():
        premarket.backtest()
        nextday.backtest2()
    threading.Thread(target=run, daemon=True).start()
    return {"started": True}


@app.post("/api/ai/premarket")
def ai_premarket(market: str = "IN", refresh: bool = False):
    return _ai(ai.premarket_brief, premarket.build(market), refresh)


@app.get("/api/jobs/auto")
def jobs_auto():
    from . import jobs
    return jobs.auto_status()


@app.post("/api/jobs/auto/{name}")
def jobs_auto_set(name: str, on: bool = True):
    from . import jobs
    try:
        return jobs.set_auto(name, on)
    except KeyError:
        raise HTTPException(404, "No such job")


@app.get("/api/jobs/{name}")
def job_status(name: str):
    from . import jobs
    try:
        return jobs.status(name)
    except KeyError:
        raise HTTPException(404, "No such job")


@app.post("/api/jobs/{name}/start")
def job_start(name: str):
    from . import jobs
    try:
        return jobs.start(name)
    except KeyError:
        raise HTTPException(404, "No such job")


@app.get("/api/pricemap/{symbol}")
def pricemap_get(symbol: str, refresh: bool = False):
    from . import pricemap
    try:
        rep = service.build_report(symbol)
        bars, src, ohlc = technicals.get_bars(rep["symbol"])
    except scraper.NotFound:
        raise HTTPException(404, f"'{symbol}' not found.")
    except (scraper.FetchError, us.USFetchError) as e:
        raise HTTPException(502, str(e))
    try:
        out = pricemap.build(rep, bars, refresh)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return {**out, "price_source": src, "real_ohlc": ohlc}


@app.post("/api/ai/pricemap/{symbol}")
def ai_pricemap(symbol: str, refresh: bool = False):
    pm = pricemap_get(symbol)
    rep, _ = _report_and_tech(symbol)
    return _ai(ai.pricemap_research, rep, pm, refresh)


@app.post("/api/ai/entry/{symbol}")
def ai_entry(symbol: str, refresh: bool = False):
    rep, tech = _report_and_tech(symbol)
    return _ai(ai.entry_research, rep, tech, refresh)


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
def movers_get(market: str = "IN", tf: str = "1D", universe: str = ""):
    return movers.get(market, tf, universe.upper())


@app.get("/api/fiidii")
def fiidii_get(market: str = "IN"):
    from . import fiidii
    if config.DEMO and not fiidii.cash_history():
        fiidii.demo_fill()
    return fiidii.us() if market.upper() == "US" else fiidii.india()


@app.get("/api/ipo")
def ipo_get(market: str = "IN", refresh: bool = False):
    from . import ipo
    if market.upper() != "IN":
        return {"open": [], "upcoming": [], "listed": [], "drhp": [], "sources": [], "not_yet": "US IPOs come in a later phase"}
    return ipo.india(refresh)


@app.get("/api/ipo/detail/{symbol}")
def ipo_detail(symbol: str, series: str = "EQ", refresh: bool = False):
    from . import ipo
    try:
        return ipo.detail(symbol, series, refresh)
    except ipo.IpoError as e:
        raise HTTPException(400, str(e))


@app.get("/api/news")
def news_get(market: str = "IN"):
    from . import news
    return news.get(market)


@app.get("/api/news/breaking")
def news_breaking(market: str = "IN"):
    from . import news
    return {"items": news.breaking_now(market)[:5]}


@app.get("/api/alerts")
def alerts_get():
    from . import alerts
    return alerts.public()


@app.post("/api/alerts")
def alerts_save(body: dict = Body(...)):
    from . import alerts
    return alerts.save(body or {})


@app.post("/api/alerts/find-chat")
def alerts_find(body: dict = Body(default={})):
    from . import alerts
    try:
        return alerts.find_chat((body or {}).get("token"))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, str(e))


@app.post("/api/alerts/test")
def alerts_test():
    from . import alerts
    try:
        return alerts.test()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, str(e))


@app.get("/api/fiidii/stocks")
def fiidii_stocks(quarter: Optional[str] = None):
    from . import instholdings
    return instholdings.get(quarter)


@app.get("/api/watch/quotes")
def watch_quotes(symbols: str = ""):
    """Last close, 1D/1W/1M change and distance from the 52-week high for each stock in a watchlist (daily bars,
    the same cached prices as the stock pages)."""
    from concurrent.futures import ThreadPoolExecutor
    syms = [s.strip().upper() for s in symbols.split(",") if s.strip()][:150]

    def one(sym):
        try:
            bars, src, _ = technicals.get_bars(sym)
        except Exception as e:  # noqa: BLE001 - one stock failing must not hide the rest
            return {"symbol": sym, "error": str(e)[:120]}
        if not bars:
            return {"symbol": sym, "error": "no prices"}
        c = [b["c"] for b in bars]
        ret = lambda k: round((c[-1] / c[-1 - k] - 1) * 100, 2) if len(c) > k else None
        hi = max(b["h"] for b in bars[-252:])
        return {"symbol": sym, "price": round(c[-1], 2), "date": bars[-1]["t"], "ret": {"1D": ret(1), "1W": ret(5), "1M": ret(21)},
                "from_hi": round((c[-1] / hi - 1) * 100, 1) if hi else None, "source": src}
    with ThreadPoolExecutor(max_workers=6) as ex:
        return {"rows": list(ex.map(one, syms))}


@app.get("/api/heatmap")
def heatmap_get(market: str = "IN", tf: str = "1D", universe: str = ""):
    from . import heatmap
    return heatmap.get(market.upper(), tf, universe.upper())


@app.get("/api/heatmap/sector")
def heatmap_sector(sector: str, market: str = "IN"):
    from . import heatmap
    return heatmap.sector_index(market.upper(), sector)


@app.post("/api/movers/refresh")
def movers_refresh(market: str = "IN", universe: str = ""):
    return movers.refresh(market.upper(), which=universe.upper() if universe.upper() in ("N500", "ALL") else "")


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
def flows_delivery(only_index: bool = True, min_turnover: float = 5.0, fno: bool = False, universe: str = ""):
    d = _flow(flows.delivery)
    names = {u["symbol"]: u.get("name") for u in universe_mod.index_list("ALL")}
    names.update({u["symbol"]: u.get("name") for u in movers._universe("IN") if u.get("name")})
    lots = enrich.fno()
    member = universe_mod.membership()
    u = universe.upper() or ("N500" if only_index else "ALL")
    rows = [r for r in d["rows"] if (not fno or r["symbol"] in lots) and (u == "ALL" or u in member.get(r["symbol"], []))]
    lists = flows.delivery_lists({**d, "rows": rows}, False, min_turnover)
    for rows in lists.values():
        for r in rows:
            r["name"] = names.get(r["symbol"]) or r["symbol"]
            r["fno"] = r["symbol"] in lots
            r["idx"] = member.get(r["symbol"], [])
    return {"date": d["date"], "days": d["days"], "lists": {k: v[:80] for k, v in lists.items()}, "source": d["source"]}


@app.get("/api/flows/deals")
def flows_deals():
    d = _flow(flows.deals)
    lots = enrich.fno()
    member = universe_mod.membership()
    return {**d, "rows": [{**r, "fno": r["symbol"] in lots, "idx": member.get(r["symbol"], [])} for r in d["rows"]]}


@app.get("/api/flows/insiders")
def flows_insiders(market: str = "IN", days: int = 30, symbols: str = ""):
    if market.upper() == "US":
        syms = [scraper.clean_symbol(s) for s in symbols.split(",") if s.strip()]
        top = [r["symbol"] for r in sorted((r for r in store.all_rankings() if r.get("market") == "US"), key=lambda r: -(r.get("overall") or 0))[:15]]
        syms = list(dict.fromkeys([s for s in syms if s.startswith("US:")] + top))
        return flows.insiders_us_many(syms)
    d = _flow(flows.insiders_in, max(7, min(days, 90)))
    lots = enrich.fno()
    member = universe_mod.membership()
    return {**d, "rows": [{**r, "fno": r["symbol"] in lots, "idx": member.get(r["symbol"], [])} for r in d["rows"]]}


@app.get("/api/flows/surveillance")
def flows_surveillance():
    d = _flow(flows.surveillance)
    names = {u["symbol"]: u.get("name") for u in movers._universe("IN")}
    lots = enrich.fno()
    member = universe_mod.membership()
    rows = [{"symbol": s, "name": names.get(s) or s, "in_index": s in names, "fno": s in lots, "idx": member.get(s, []), "flags": f}
            for s, f in d["flags"].items()]
    rows.sort(key=lambda r: (not r["in_index"], -sum(x["severity"] == "high" for x in r["flags"])))
    return {"date": d["date"], "rows": rows, "source": d["source"]}


@app.get("/api/fno")
def fno_list():
    lots = enrich.fno()
    return {"count": len(lots), "lots": lots, "source": "NSE F&O market lots file"}


# ---------------------------------------------------------------- brokers (read-only) + portfolio
def _base(request: Request) -> str:
    return str(request.base_url).rstrip("/")


def _brk(fn, *a):
    try:
        return fn(*a)
    except brokers.BrokerError as e:
        raise HTTPException(400, str(e))


@app.get("/api/brokers")
def brokers_list(request: Request):
    return {"brokers": brokers.status(_base(request))}


@app.post("/api/brokers/{bid}/config")
def brokers_config(bid: str, body: dict = Body(...)):
    _brk(brokers.configure, bid, body)
    return {"ok": True}


@app.post("/api/brokers/{bid}/connect")
def brokers_connect(bid: str, request: Request):
    b = brokers.BROKERS.get(bid)
    if not b:
        raise HTTPException(404, "Unknown broker")
    if b["auth"] in ("oauth", "paste"):
        if config.DEMO:                                   # no real login in demo mode
            _brk(brokers.callback, bid, {}, _base(request))
            return {**_brk(brokers.sync, bid), "connected": True}
        return {"url": _brk(brokers.login_url, bid, _base(request))}
    _brk(brokers.direct_login, bid)
    return {**_brk(brokers.sync, bid), "connected": True}


@app.get("/api/broker/{bid}/callback")
def brokers_callback(bid: str, request: Request):
    try:
        brokers.callback(bid, dict(request.query_params), _base(request))
        brokers.sync(bid)
        return RedirectResponse(f"/#/portfolio?connected={bid}")
    except (brokers.BrokerError, KeyError, ValueError) as e:
        return RedirectResponse("/#/portfolio?error=" + quote(str(e)[:300]))


@app.post("/api/brokers/schwab/paste")
def brokers_schwab_paste(request: Request, body: dict = Body(...)):
    _brk(brokers.schwab_paste, body.get("url", ""), _base(request))
    return _brk(brokers.sync, "schwab")


@app.post("/api/brokers/{bid}/sync")
def brokers_sync(bid: str):
    return _brk(brokers.sync, bid)


@app.delete("/api/brokers/{bid}")
def brokers_forget(bid: str):
    brokers.forget(bid)
    return {"ok": True}


@app.post("/api/portfolio/upload")
def portfolio_upload(body: dict = Body(...)):
    import base64 as b64
    try:
        data = b64.b64decode(body.get("data", ""))
    except ValueError:
        raise HTTPException(400, "Could not read the file")
    if len(data) > 5_000_000:
        raise HTTPException(400, "File too large (max 5 MB)")
    return _brk(brokers.import_file, data, body.get("filename", "holdings.csv"), (body.get("market") or "IN").upper())


@app.get("/api/portfolio")
def portfolio_get(market: str = "IN"):
    return portfolio.xray(market)


@app.post("/api/portfolio/score")
def portfolio_score(market: str = "IN"):
    x = portfolio.xray(market)
    syms = (x["summary"] or {}).get("unscored") or []
    if not syms:
        return {"started": False, "message": "Every holding is already scored"}
    return {"started": True, "count": len(syms), "scan": service.start_scan(market=market.upper(), symbols=syms)}


@app.post("/api/ai/portfolio")
def ai_portfolio(market: str = "IN"):
    x = portfolio.xray(market)
    if not x["rows"]:
        raise HTTPException(400, "No holdings yet")
    return _ai(ai.explain_portfolio, x)


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
def scan_start(limit: Optional[int] = None, market: str = "IN", universe: str = "N500"):
    which = universe.upper() if universe.upper() in universe_mod.LABELS else "N500"
    return service.start_scan(limit, market=market.upper(), which=which)


@app.get("/api/universe")
def universe_info():
    """Sizes of NIFTY 50 / 100 / 500 / All NSE and which index each stock belongs to."""
    lists = {k: universe_mod.index_list(k) for k in ("N50", "N100", "N500")}
    return {"counts": {**{k: len(v) for k, v in lists.items()}, "ALL": len(universe_mod.index_list("ALL"))},
            "labels": universe_mod.LABELS, "member": universe_mod.membership()}


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
        # never let the app window keep an old index.html: it would keep loading an old build
        return FileResponse(config.STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache, no-store, must-revalidate"})
else:
    @app.get("/")
    def no_ui():
        return JSONResponse({"message": "API running. Frontend not built: run `npm run build` in frontend/."})
