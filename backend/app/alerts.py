"""Telegram alerts: breaking news, your watchlist stocks' filings and central-bank releases, sent to your own chat.

Setup (once): create a bot with @BotFather in Telegram and paste its token in Settings; send your bot any message;
press "Find my chat". The token stays on this computer (in EquityLens's own database) and is only sent to Telegram.
Each item is sent once. Nothing older than the moment alerts were switched on is sent, so turning them on never
floods the chat with old news.
"""
from __future__ import annotations

import html
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests

from . import config, store, vault

KEY, SENT, PRICE_KEY = "ALERTS::SETTINGS", "ALERTS::SENT", "ALERTS::PRICE"
API = "https://api.telegram.org/bot{token}/{method}"
IST = timezone(timedelta(hours=5, minutes=30))
MAX_PER_RUN = 8
DEFAULTS = {"on": False, "token": "", "chat_id": "", "chat_name": "", "breaking": True, "filings": True, "central": True,
            "top": False, "entry_flips": True, "high_low_52w": True, "price_targets": True,
            "markets": ["IN", "US"], "watch": [], "since": None, "last_sent": None, "last_error": None, "sent_count": 0}


def settings() -> dict:
    hit = store.get_company(KEY)
    out = {**DEFAULTS, **(hit[1] if hit else {})}
    if out.get("token"):
        out["token"] = vault.decrypt(out["token"])
    return out


def public(s: Optional[dict] = None) -> dict:
    s = s or settings()
    t = s.get("token") or ""
    return {**{k: v for k, v in s.items() if k != "token"}, "has_token": bool(t), "token_hint": f"…{t[-4:]}" if len(t) > 8 else ""}


def save(patch: dict) -> dict:
    s = settings()
    for k in ("on", "breaking", "filings", "central", "top", "entry_flips", "high_low_52w", "price_targets"):
        if k in patch:
            s[k] = bool(patch[k])
    for k in ("token", "chat_id", "chat_name"):
        if k in patch and patch[k] is not None:
            s[k] = str(patch[k]).strip()
    if "markets" in patch:
        s["markets"] = [m for m in ("IN", "US") if m in (patch["markets"] or [])]
    if "watch" in patch:
        s["watch"] = sorted({str(x).upper() for x in (patch["watch"] or []) if x})[:2000]
    if patch.get("on") and not s.get("since"):
        s["since"] = datetime.now(timezone.utc).isoformat()
    if patch.get("on") is False:
        s["since"] = None
    stored = dict(s)
    if stored.get("token"):
        stored["token"] = vault.encrypt(stored["token"])
    store.put_company(KEY, stored)
    return public(s)


def _call(token: str, method: str, **data) -> dict:
    r = requests.post(API.format(token=token, method=method), json=data, timeout=config.REQUEST_TIMEOUT)
    j = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    if not j.get("ok"):
        raise RuntimeError(j.get("description") or f"HTTP {r.status_code}")
    return j


def find_chat(token: Optional[str] = None) -> dict:
    """The chat that last wrote to the bot (send the bot any message first)."""
    s = settings()
    token = (token or s["token"]).strip()
    if not token:
        raise RuntimeError("Paste the bot token first")
    upd = _call(token, "getUpdates").get("result") or []
    for u in reversed(upd):
        m = u.get("message") or u.get("channel_post") or u.get("my_chat_member") or {}
        c = m.get("chat") or {}
        if c.get("id"):
            name = c.get("title") or " ".join(x for x in (c.get("first_name"), c.get("last_name")) if x) or c.get("username") or str(c["id"])
            return save({"token": token, "chat_id": str(c["id"]), "chat_name": name})
    raise RuntimeError("No message found: open your bot in Telegram, press Start or send it any message, then try again")


def send(text: str, s: Optional[dict] = None) -> None:
    s = s or settings()
    if not s["token"] or not s["chat_id"]:
        raise RuntimeError("Bot token and chat are not set")
    _call(s["token"], "sendMessage", chat_id=s["chat_id"], text=text[:4000], parse_mode="HTML", disable_web_page_preview=False)


def test() -> dict:
    s = settings()
    send("✅ <b>EquityLens alerts are connected.</b>\nBreaking market news, your watchlist stocks' filings and RBI / Fed releases will arrive here.", s)
    return {"ok": True}


# ---------------------------------------------------------------- messages
def _t(iso: str, market: str) -> str:
    d = datetime.fromisoformat(iso)
    if market == "US":
        return d.astimezone(timezone(timedelta(hours=-5))).strftime("%d %b, %I:%M %p ET")
    return d.astimezone(IST).strftime("%d %b, %I:%M %p IST")


def message(it: dict, why: str, market: str) -> str:
    e = html.escape
    head = {"breaking": "🔴 <b>BREAKING</b>", "filing": "📄 <b>Company filing</b>", "central": "🏛 <b>Central bank</b>",
            "top": "📰 <b>Top story</b>"}[why]
    lines = [head, f"<b>{e(it['title'])}</b>"]
    if it.get("summary") and it["summary"] != it["title"]:
        lines.append(e(it["summary"][:300]))
    if it.get("order"):
        o = it["order"]
        lines.append(f"Order ₹{o['crore']:,.0f} Cr" + (f" · {o['pct_mcap']:.1f}% of market value" if o.get("pct_mcap") is not None else ""))
    tags = [f"{t['symbol'].replace('US:', '')} {'+' if (t.get('d1') or 0) > 0 else ''}{t['d1']:.2f}% today" for t in it.get("tags", []) if t.get("d1") is not None]
    if tags:
        lines.append(" · ".join(tags[:4]))
    src = ", ".join(x["name"] for x in it.get("sources", [])[:3]) or it.get("source", "")
    lines.append(f"<i>{e(src)} · {_t(it['time'], market)}</i>")
    if it.get("url"):
        lines.append(f'<a href="{e(it["url"])}">Open</a>')
    return "\n".join(lines)


def candidates(s: dict, pages: dict) -> list[tuple[str, dict, str]]:
    """[(why, item, market)] newest last, only items after alerts were switched on."""
    since = s.get("since") or datetime.now(timezone.utc).isoformat()
    watch = set(s.get("watch") or [])
    out, seen = [], set()
    for mk, d in pages.items():
        picks = []
        if s["breaking"]:
            picks += [("breaking", i) for i in d.get("breaking", [])]
        for i in d.get("items", []):
            if s["filings"] and i["kind"] == "filing" and watch & set(i["symbols"]):
                picks.append(("filing", i))
            elif s["central"] and i["kind"] == "official":
                picks.append(("central", i))
            elif s["top"] and i.get("covered", 1) >= 3:
                picks.append(("top", i))
        for why, i in picks:
            if i["time"] >= since and i["id"] not in seen:
                seen.add(i["id"])
                out.append((why, i, mk))
    out.sort(key=lambda x: x[1]["time"])
    return out


def dispatch(pages: Optional[dict] = None) -> int:
    s = settings()
    if not s["on"] or not s["token"] or not s["chat_id"]:
        return 0
    if pages is None:
        from . import news
        pages = {mk: news.get(mk) for mk in s["markets"]}
    hit = store.get_company(SENT)
    sent = hit[1] if hit else {}
    n = 0
    for why, it, mk in candidates(s, pages):
        if it["id"] in sent or n >= MAX_PER_RUN:
            continue
        try:
            send(message(it, why, mk), s)
            sent[it["id"]] = time.time()
            n += 1
            s.update(last_sent=time.time(), last_error=None, sent_count=s.get("sent_count", 0) + 1)
        except Exception as e:  # noqa: BLE001
            s["last_error"] = str(e)[:200]
            break
        time.sleep(0.4)
    cut = time.time() - 8 * 86400
    store.put_company(SENT, {k: v for k, v in sent.items() if v >= cut})
    stored = dict(s)
    if stored.get("token"):
        stored["token"] = vault.encrypt(stored["token"])
    store.put_company(KEY, stored)
    return n


# ------------------------------------------------------------------ server-side price, 52W, and entry-flip alerts
def price_alerts_list() -> list[dict]:
    hit = store.get_company(PRICE_KEY)
    return list(hit[1].get("items") or []) if hit else []


def price_alert_add(sym: str, direction: str, price: float, telegram: bool = True) -> list[dict]:
    items = price_alerts_list()
    sym = (sym or "").strip().upper()
    if not sym or direction not in ("above", "below") or not price or price <= 0:
        raise ValueError("Invalid price alert")
    aid = f"{int(time.time() * 1000)}"
    items.append({"id": aid, "sym": sym, "dir": direction, "price": round(float(price), 2),
                  "telegram": bool(telegram), "hit": None, "created": time.time()})
    items = items[-200:]
    store.put_company(PRICE_KEY, {"items": items})
    return items


def price_alert_remove(aid: str) -> list[dict]:
    items = [x for x in price_alerts_list() if str(x.get("id")) != str(aid)]
    store.put_company(PRICE_KEY, {"items": items})
    return items


def check_price_alerts(prices: Optional[dict[str, float]] = None) -> int:
    """Evaluate server-side price targets, 52-week highs/lows, and entry flips; send Telegram when active."""
    s = settings()
    items = price_alerts_list()
    sent_hit = store.get_company(SENT)
    sent = dict(sent_hit[1]) if sent_hit else {}
    watch = set(s.get("watch") or [])
    n = 0

    # 1. Price targets
    if prices is None:
        prices = {}
        for mk in ("IN", "US"):
            mv = store.get_company(f"MOVERS::v2::{mk}")
            for r in ((mv[1] if mv else {}).get("rows") or []):
                sp = (r.get("spark") or [None])[-1]
                if sp is not None:
                    prices[r["symbol"]] = sp
    changed = False
    for a in items:
        if a.get("hit"):
            continue
        p0 = prices.get(a["sym"])
        if p0 is None:
            continue
        if (a["dir"] == "above" and p0 >= a["price"]) or (a["dir"] == "below" and p0 <= a["price"]):
            a["hit"] = datetime.now(IST).strftime("%d %b %H:%M IST")
            changed = True
            if s["on"] and s.get("price_targets", True) and a.get("telegram", True) and s["token"] and s["chat_id"]:
                try:
                    cur = "$" if a["sym"].startswith("US:") else "₹"
                    send(f"🎯 <b>Price Alert: {html.escape(a['sym'].replace('US:', ''))}</b>\n"
                         f"Crossed {a['dir']} {cur}{a['price']:,.2f} (now {cur}{p0:,.2f})", s)
                    n += 1
                except Exception:  # noqa: BLE001
                    pass
    if changed:
        store.put_company(PRICE_KEY, {"items": items})

    if not (s["on"] and s["token"] and s["chat_id"]):
        return n

    # 2. Watchlist entry flips (Avoid -> Enter)
    if s.get("entry_flips", True) and watch:
        drift = (store.get_company("DRIFT::HISTORY") or (0, {}))[1]
        for sym, d in drift.items():
            if sym not in watch or d.get("entry") != "ENTER" or d.get("prev_entry") != "AVOID":
                continue
            eid = f"FLIP::{sym}::{int(d.get('entry_at') or 0)}"
            if eid in sent:
                continue
            try:
                send(f"🟢 <b>Entry Flip: {html.escape(d.get('name') or sym)}</b>\n"
                     f"Entry decision turned <b>Avoid → Enter</b>.", s)
                sent[eid] = time.time()
                n += 1
            except Exception:  # noqa: BLE001
                break

    # 3. Watchlist 52-week high/low breakouts
    if s.get("high_low_52w", True) and watch:
        today_str = datetime.now(IST).date().isoformat()
        for mk in s.get("markets", ["IN", "US"]):
            mv = (store.get_company(f"MOVERS::v2::{mk}") or (0, {}))[1]
            for r in mv.get("rows") or []:
                sym = r.get("symbol")
                if sym not in watch or not (r.get("new_high") or r.get("new_low")):
                    continue
                hid = f"52W::{sym}::{today_str}::{'H' if r.get('new_high') else 'L'}"
                if hid in sent:
                    continue
                try:
                    kind = "New 52-week HIGH 📈" if r.get("new_high") else "New 52-week LOW 📉"
                    send(f"<b>{kind}: {html.escape(r.get('name') or sym)}</b>\n"
                         f"1D move: {(r.get('ret') or {}).get('1D', 0):+.2f}%", s)
                    sent[hid] = time.time()
                    n += 1
                except Exception:  # noqa: BLE001
                    break

    cut = time.time() - 8 * 86400
    store.put_company(SENT, {k: v for k, v in sent.items() if v >= cut})
    return n
