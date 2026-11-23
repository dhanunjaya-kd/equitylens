"""News: market-moving items only, for India and the US, from the sources themselves.

Kinds
  filing    the company's own exchange filing: NSE corporate announcements (India), SEC 8-K current filings (US, S&P 500)
  official  central banks: RBI press releases, Federal Reserve press releases (policy and markets items only)
  news      business publishers' public RSS feeds: headline, the publisher's own short summary, link to the article
            (articles are never copied)

What is kept (so the page is not filled with noise)
  * a filing only in a category that moves a stock: results, orders / deals / expansion, corporate actions,
    top-management changes, credit ratings. Routine filings (trading window, newspaper copies, lost share
    certificates, compliance certificates, AGM notices, analyst-meet schedules ...) are dropped.
  * a news item only when it names a listed company we track, or is about markets, the economy, central banks
    or a major global event, and is not a tip list, lifestyle or entertainment piece.
  * the same story from several publishers is shown once, with every source listed ("covered by 3").

What is measured, never guessed
  * each tagged stock's real price move today (the app's own daily prices)
  * for an order win with an amount in the filing: the amount as % of the company's market value
There is no "bullish / bearish" label: nothing would back it.
"""
from __future__ import annotations

import email.utils
import hashlib
import html as htmllib
import json
import re
import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests

from . import config, store

IST = timezone(timedelta(hours=5, minutes=30))
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36",
      "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, text/xml;q=0.8, */*;q=0.5"}
KEEP_DAYS = 7
REFRESH_S = 5 * 60
NSE_ANN = "https://www.nseindia.com/api/corporate-announcements?index=equities"
SEC_8K = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=8-K&company=&dateb=&owner=include&count=100&output=atom"

# (id, name, url, market, kind, markets_only)  markets_only: a markets-section feed, so market relevance is given
FEEDS = [
    ("et_mkts", "Economic Times · Markets", "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms", "IN", "news", True),
    ("mint_mkts", "Mint · Markets", "https://www.livemint.com/rss/markets", "IN", "news", True),
    ("hindu_mkts", "The Hindu · Markets", "https://www.thehindu.com/business/markets/feeder/default.rss", "IN", "news", True),
    ("bl_mkts", "BusinessLine · Markets", "https://www.thehindubusinessline.com/markets/feeder/default.rss", "IN", "news", True),
    ("bs_mkts", "Business Standard · Markets", "https://www.business-standard.com/rss/markets-106.rss", "IN", "news", True),
    ("mc_latest", "Moneycontrol · Latest", "https://www.moneycontrol.com/rss/latestnews.xml", "IN", "news", False),
    ("rbi", "Reserve Bank of India", "https://rbi.org.in/pressreleases_rss.xml", "IN", "official", False),
    ("cnbc_top", "CNBC · Top news", "https://www.cnbc.com/id/100003114/device/rss/rss.html", "US", "news", False),
    ("cnbc_mkt", "CNBC · Market Insider", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=20409666", "US", "news", True),
    ("cnbc_econ", "CNBC · Economy", "https://www.cnbc.com/id/20910258/device/rss/rss.html", "US", "news", False),
    ("cnbc_earn", "CNBC · Earnings", "https://www.cnbc.com/id/15839135/device/rss/rss.html", "US", "news", True),
    ("mw_top", "MarketWatch · Top stories", "https://feeds.content.dowjones.io/public/rss/mw_topstories", "US", "news", False),
    ("cnbc_world", "CNBC · World", "https://www.cnbc.com/id/100727362/device/rss/rss.html", "GLOBAL", "news", False),
    ("bbg_mkts", "Bloomberg · Markets", "https://feeds.bloomberg.com/markets/news.rss", "GLOBAL", "news", True),
    ("fed", "Federal Reserve", "https://www.federalreserve.gov/feeds/press_all.xml", "US", "official", False),
]
STATE = {"running": False, "last": 0.0, "feeds": {}}
_lock = threading.Lock()

# ---------------------------------------------------------------- classification
CATS = ["results", "orders", "actions", "management", "economy", "global", "markets", "company"]
CAT_LABEL = {"results": "Results", "orders": "Orders & deals", "actions": "Corporate actions", "management": "Management",
             "economy": "Economy & policy", "global": "Global", "markets": "Markets", "company": "Company news"}
R = lambda *w: re.compile(r"\b(" + "|".join(w) + r")", re.I)
RULES = [
    ("results", R(r"results?", r"earnings", r"net profit", r"profit (?:rises|falls|jumps|drops|up|down|surges|slumps)", r"revenue",
                  r"q[1-4] ?(?:fy)?\d*", r"quarterly", r"eps\b", r"guidance", r"net loss", r"beats estimates", r"misses estimates")),
    ("orders", R(r"orders?\b", r"contract", r"bags?\b", r"wins?\b", r"letter of (?:award|acceptance|intent)", r"lowest bidder", r"l1 bidder",
                 r"acqui", r"merger", r"deal\b", r"joint venture", r"\bjv\b", r"stake in", r"capex", r"expansion", r"new plant",
                 r"capacity", r"commission(?:s|ed|ing)", r"partnership", r"agreement")),
    ("actions", R(r"dividend", r"bonus", r"stock split", r"split\b", r"sub-division", r"buyback", r"buy-back", r"rights issue",
                  r"record date", r"delist", r"\bqip\b", r"\bipo\b", r"listing", r"block deal", r"bulk deal", r"stake sale", r"\bofs\b",
                  r"fund ?rais", r"preferential", r"credit rating", r"rating (?:upgrade|downgrade)")),
    ("management", R(r"\bceo\b", r"\bcfo\b", r"managing director", r"\bmd\b", r"chairman", r"chairperson", r"resign", r"steps down",
                     r"appoint", r"whole-time director")),
    ("economy", R(r"\brbi\b", r"repo rate", r"monetary policy", r"inflation", r"\bcpi\b", r"\bwpi\b", r"\bgdp\b", r"\biip\b", r"\bpmi\b",
                  r"fiscal", r"budget", r"gst collection", r"\bfed\b", r"federal reserve", r"\bfomc\b", r"powell", r"rate cut",
                  r"rate hike", r"interest rate", r"jobs report", r"payrolls", r"unemployment", r"jobless", r"retail sales",
                  r"treasury", r"bond yields?", r"yields?\b", r"forex reserves", r"current account", r"trade deficit", r"economy",
                  r"recession", r"consumer confidence", r"housing starts")),
    ("global", R(r"\bwar\b", r"sanction", r"tariff", r"\bopec", r"crude", r"oil prices?", r"brent", r"china", r"europe", r"\becb\b",
                 r"\bboj\b", r"bank of japan", r"bank of england", r"geopolit", r"ukraine", r"russia", r"israel", r"iran", r"middle east",
                 r"gaza", r"west asia", r"saudi", r"yemen", r"houthis?", r"red sea", r"hormuz", r"taiwan", r"north korea", r"pakistan",
                 r"refiner", r"\bg7\b", r"\bg20\b", r"\bimf\b", r"world bank", r"gold prices?", r"dollar index", r"trade war", r"election")),
    ("markets", R(r"sensex", r"nifty", r"\bdow\b", r"s&p 500", r"nasdaq", r"stock market", r"markets?\b", r"stocks?\b", r"shares?\b",
                  r"rupee", r"\bfiis?\b", r"\bfpis?\b", r"\bdiis?\b", r"\bvix\b", r"closing bell", r"opening bell", r"wall street",
                  r"equities", r"rally", r"sell-?off", r"bse\b", r"\bnse\b")),
]
NOISE = re.compile(r"horoscope|astrolog|zodiac|quiz|crossword|recipe|lifestyle|in pics|photos:|web ?stor|^video|^watch:|podcast|sponsored|"
                   r"partner content|brand ?connect|advertorial|how to (?:save|claim|file|apply|check)|credit card|personal loan|"
                   r"stocks? to buy|buy or sell|penny stocks?|multibagger|trading ideas|top picks|technical picks|stock picks|"
                   r"should you buy|stocks? recommendations?|lottery|\bipl\b|cricket|bollywood|celebrit|box office|movie|"
                   r"weather|live updates?:|live blog|\bmemes?\b|astro|vastu", re.I)
FILING_DROP = re.compile(r"trading window|newspaper|loss of share|duplicate share|certificate under|reg(?:ulation)?\.? ?74|"
                         r"compliance certificate|investor complaints?|statement of investor|closure of trading|change in registrar|"
                         r"esops?\b|esos\b|employee stock|analysts?/institutional|investor meet|analyst meet|annual general meeting|"
                         r"\bagm\b|e-voting|postal ballot|book closure|shareholders? meeting|copy of|intimation of loss|"
                         r"secretarial|reg(?:ulation)? ?40|transcript|audio recording|link of recording", re.I)
RBI_KEEP = re.compile(r"monetary policy|repo|policy rate|inflation|liquidity|forex|foreign exchange reserves|money supply|"
                      r"governor'?s statement|financial stability|sovereign gold bond|government securities auction|"
                      r"state government securities|market operations|\bomo\b|\bvrr|\bcrr\b|\bslr\b|rupee|external debt|"
                      r"balance of payments|current account|bank credit|sectoral deployment", re.I)
FED_KEEP = re.compile(r"\bfomc\b|monetary policy|federal funds|discount rate|interest on reserve|balance sheet|beige book|minutes|"
                      r"stress test|economic projections|statement", re.I)
SEC_ITEMS = {"2.02": ("results", "Results of operations"), "1.01": ("orders", "Material agreement"),
             "2.01": ("orders", "Acquisition or sale completed"), "1.02": ("orders", "Agreement terminated"),
             "5.02": ("management", "Director or officer change"), "2.05": ("company", "Restructuring costs"),
             "2.06": ("company", "Material impairment"), "3.01": ("actions", "Listing notice"), "1.03": ("company", "Bankruptcy"),
             "4.02": ("company", "Financials no longer reliable")}


def classify(text: str) -> Optional[str]:
    for cat, rx in RULES:
        if rx.search(text or ""):
            return cat
    return None


def clean(s: str, n: int = 320) -> str:
    s = htmllib.unescape(htmllib.unescape(re.sub(r"<[^>]+>", " ", s or "")))   # some feeds escape twice ("&amp;amp;")
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= n else s[: n - 1].rsplit(" ", 1)[0] + "…"


def _id(*parts) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:16]


def _when(s: str) -> Optional[datetime]:
    if not s:
        return None
    s = s.strip()
    try:
        d = email.utils.parsedate_to_datetime(s)
    except (TypeError, ValueError):
        d = None
    if d is None:
        for f in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%SZ", "%d-%b-%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
            try:
                d = datetime.strptime(s.replace("Z", "+0000") if f.endswith("%z") else s, f)
                break
            except ValueError:
                continue
    if d is None:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=IST)
    return d.astimezone(timezone.utc)


# ---------------------------------------------------------------- feeds
def parse_feed(text: str) -> list[dict]:
    """RSS 2.0 or Atom -> [{title, url, summary, time}] (time: UTC ISO)."""
    try:
        root = ET.fromstring(text.encode("utf-8") if isinstance(text, str) else text)
    except ET.ParseError:
        return []
    out = []
    strip = lambda t: t.split("}", 1)[-1]
    for el in root.iter():
        tag = strip(el.tag)
        if tag not in ("item", "entry"):
            continue
        f, imgs = {}, []
        for ch in el.iter():
            if ch is el:
                continue
            t = strip(ch.tag)
            if t == "link" and ch in list(el):
                f["link"] = ch.get("href") or (ch.text or "").strip() or f.get("link")
            elif t in ("content", "thumbnail") and ch.get("url"):
                if (ch.get("medium") or "image") == "image" and not (ch.get("type") or "image").startswith(("video", "audio")):
                    imgs.append((int(ch.get("width") or 0), ch.get("url")))
            elif t == "enclosure" and ch.get("url") and (ch.get("type") or "").startswith("image"):
                imgs.append((0, ch.get("url")))
            elif ch in list(el) and t not in f:
                f[t] = (ch.text or "").strip()
                if t == "encoded":
                    f["content"] = f.get("content") or f[t]
        title = clean(f.get("title", ""), 220)
        when = _when(f.get("pubDate") or f.get("published") or f.get("updated") or f.get("date") or "")
        raw = " ".join(f.get(k, "") for k in ("description", "summary", "content", "encoded"))
        for m in re.findall(r"<img[^>]+src=[\"']([^\"']+)", htmllib.unescape(raw)):
            imgs.append((0, m))
        image = pick_image(imgs)
        if title and when:
            out.append({"title": title, "url": f.get("link") or "", "summary": clean(f.get("description") or f.get("summary") or f.get("content") or ""),
                        "time": when.isoformat(), "image": image})
    return out


def pick_image(cands: list) -> Optional[str]:
    """The publisher's own picture for the item (largest offered); no tracking pixels, icons or logos."""
    ok = [(w, u.strip()) for w, u in cands if u and u.strip().startswith(("https://", "http://"))
          and not re.search(r"(1x1|pixel|spacer|blank\.gif|/logo|favicon|\.svg(\?|$)|feedburner|doubleclick)", u, re.I)]
    if not ok:
        return None
    ok.sort(key=lambda x: -x[0])
    u = ok[0][1]
    return "https://" + u[7:] if u.startswith("http://") else u


OG = [re.compile(p, re.I) for p in (
    r'<meta[^>]+property=["\']og:image(?::secure_url)?["\'][^>]+content=["\']([^"\']+)',
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
    r'<meta[^>]+name=["\']twitter:image(?::src)?["\'][^>]+content=["\']([^"\']+)',
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']twitter:image["\']')]


def og_image(page: str, base: str = "") -> Optional[str]:
    """The picture the publisher set for sharing the article (og:image / twitter:image)."""
    from urllib.parse import urljoin
    head = page[:400000]
    for rx in OG:
        m = rx.search(head)
        if m:
            return pick_image([(0, urljoin(base, htmllib.unescape(m.group(1).strip())))])
    return None


def fill_pictures(saved: dict, limit: int = 60) -> int:
    """Articles from the last two days without a picture: read the publisher's own share picture from the page."""
    cut = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
    todo = [v for v in saved.values() if v["kind"] == "news" and not v.get("image") and not v.get("og_tried")
            and v.get("url") and v["time"] >= cut]
    todo.sort(key=lambda v: v["time"], reverse=True)
    n = 0
    for v in todo[:limit]:
        v["og_tried"] = True
        try:
            r = requests.get(v["url"], headers={**UA, "Accept": "text/html,application/xhtml+xml"}, timeout=10, stream=True)
            page = r.raw.read(400000, decode_content=True).decode(r.encoding or "utf-8", "ignore") if r.status_code == 200 else ""
            r.close()
        except Exception:  # noqa: BLE001 - no picture is fine
            page = ""
        img = og_image(page, v["url"]) if page else None
        if img:
            v["image"] = img
            n += 1
        time.sleep(0.3)
    return n


def _fetch(url: str, headers: Optional[dict] = None) -> str:
    r = requests.get(url, headers=headers or UA, timeout=config.REQUEST_TIMEOUT)
    r.raise_for_status()
    return r.text


# ---------------------------------------------------------------- filings
def parse_nse_announcements(text: str) -> list[dict]:
    """NSE corporate-announcements JSON -> filings kept by category (routine ones dropped)."""
    try:
        j = json.loads(text)
    except (TypeError, ValueError):
        return []
    rows = j.get("data", j) if isinstance(j, dict) else j
    out = []
    for r in rows if isinstance(rows, list) else []:
        sym = str(r.get("symbol") or "").strip().upper()
        subj = clean(r.get("desc") or r.get("subject") or "", 160)
        body = clean(r.get("attchmntText") or r.get("text") or "", 600)
        when = _when(r.get("an_dt") or r.get("sort_date") or r.get("dt") or "")
        if not sym or not when or not (subj or body):
            continue
        both = f"{subj} {body}"
        if FILING_DROP.search(subj) or NOISE.search(both):
            continue
        cat = classify(subj) or classify(body)
        if cat in (None, "markets", "economy", "global"):
            continue
        if cat == "management" and not re.search(r"\b(ceo|cfo|managing director|md|chairman|chairperson|whole-time director)\b", both, re.I):
            continue
        name = clean(r.get("sm_name") or sym, 90)
        out.append({"id": _id("nse", sym, r.get("seq_id") or when.isoformat(), subj), "kind": "filing", "market": "IN",
                    "title": f"{name} — {subj or body[:160]}", "subject": subj, "summary": body,
                    "url": r.get("attchmntFile") or "", "time": when.isoformat(), "category": cat, "symbols": [sym],
                    "source": "NSE filing"})
    return out


def parse_sec_8k(text: str, cik_to_ticker: dict) -> list[dict]:
    """SEC current 8-K Atom feed -> S&P 500 companies' filings in a market-moving item."""
    out = []
    for e in parse_feed(text):
        m = re.match(r"8-K(?:/A)?\s*-\s*(.+?)\s*\((\d{10})\)", e["title"])
        if not m:
            continue
        cik = int(m.group(2))
        tick = cik_to_ticker.get(cik)
        if not tick:
            continue
        items = re.findall(r"Item (\d\.\d\d)", e["summary"])
        hit = [SEC_ITEMS[i] for i in items if i in SEC_ITEMS]
        if not hit:
            continue
        cat = hit[0][0]
        what = "; ".join(dict.fromkeys(h[1] for h in hit))
        name = m.group(1).title()
        out.append({"id": _id("sec", cik, e["url"]), "kind": "filing", "market": "US", "title": f"{name} — {what}",
                    "subject": f"8-K items {', '.join(items)}", "summary": f"Form 8-K filed with the SEC: {what}.", "url": e["url"],
                    "time": e["time"], "category": cat, "symbols": [f"US:{tick}"], "source": "SEC 8-K"})
    return out


# ---------------------------------------------------------------- stock tags
COMMON = {"target", "general", "progressive", "southern", "booking", "match", "block", "ball", "gap", "fox", "news", "live", "global",
          "first", "united", "american", "national", "public", "capital", "energy", "power", "indian", "india", "bank", "group",
          "state", "steel", "cement", "motors", "best", "home", "dollar", "general", "eastern", "western", "central", "pacific",
          "alliance", "realty", "finance", "infra", "tech", "life", "care", "trust", "union", "royal", "metro", "star", "apex",
          "south", "north", "west", "east", "southwest", "northeast", "new", "york", "great", "city", "world", "asia", "china",
          "japan", "korea", "europe", "the", "and", "of", "services", "industries", "investment", "investments", "insurance",
          "markets", "market", "exchange", "trade", "oil", "gas", "petroleum", "chemicals", "pharma", "foods", "hotels", "airlines",
          "railway", "railways", "ports", "infrastructure", "housing", "credit", "money", "fund", "funds", "data", "systems", "software",
          "health", "healthcare", "hospital", "hospitals", "auto", "automobile", "automobiles", "electric", "electricals", "cables",
          "textiles", "paper", "sugar", "agro", "media", "entertainment", "communications", "telecom", "network", "digital", "solar",
          "green", "renewable", "renewables", "water", "air", "sea", "land", "gold", "silver", "metal", "metals", "mining", "minerals"}
TAIL = {"limited", "ltd", "inc", "corp", "corporation", "company", "co", "plc", "the", "class", "a", "b", "c", "holdings", "group"}
CAPS_STOP = {"NIFTY", "SENSEX", "BSE", "NSE", "RBI", "SEBI", "GST", "IPO", "FII", "FPI", "DII", "GDP", "CPI", "WPI", "IIP", "PMI", "USA",
             "FOMC", "OPEC", "IMF", "ECB", "BOJ", "CEO", "CFO", "EPS", "QIP", "OFS", "ETF", "AI", "EV", "EVS", "FY", "LIVE", "NEWS",
             "INDIA", "US", "UK", "EU", "GOVT", "BANK", "NASDAQ", "NYSE", "DOW", "SEC", "FED", "IT", "PSU", "MSCI", "FTSE"}


def build_tagger(names: dict) -> callable:
    """names: {symbol: company name}. -> f(text) -> [symbols]. An alias that fits two companies is not used."""
    alias: dict = {}
    for sym, nm in names.items():
        words = re.findall(r"[A-Za-z0-9&']+", re.sub(r"\(.*?\)", "", nm or ""))
        while words and words[-1].lower() in TAIL:
            words.pop()
        if not words:
            continue
        cands = {" ".join(words)}
        if len(words) >= 2:
            cands.add(" ".join(words[:2]))
        if len(words[0]) >= 5 and words[0].lower() not in COMMON:
            cands.add(words[0])
        full = {" ".join(words)}
        if words[0].lower() == "the" and len(words) >= 3:       # "The Coca-Cola Company" is written "Coca-Cola"
            cands |= {" ".join(words[1:]), " ".join(words[1:3])}   # (never a lone word: "The Federal Bank" is not "Federal")
            full.add(" ".join(words[1:]))
        for a in cands:
            ws = a.lower().split()
            if len(a) < 4 or (all(w in COMMON for w in ws) and not (a in full and len(ws) >= 3)):
                continue                                          # "Central Bank", "South West": everyday words only
            alias.setdefault(a, set()).add(sym)
    alias = {a: next(iter(s)) for a, s in alias.items() if len(s) == 1}
    # "Take Two" also matches "Take-Two" (names are split on hyphens above, headlines often keep them)
    big = re.compile(r"(?<![A-Za-z0-9])(" + "|".join(re.escape(a).replace(r"\ ", "[ \\-\u2010\u2011]") for a in sorted(alias, key=len, reverse=True))
                     + r")(?![A-Za-z0-9])") if alias else None
    plain = {s.replace("US:", ""): s for s in names}

    def tag(text: str) -> list[str]:
        out = [alias[re.sub("[-\u2010\u2011]", " ", m)] for m in big.findall(text)] if big else []      # names as they are written
        for tok in re.findall(r"(?<![A-Za-z0-9])([A-Z][A-Z0-9&]{3,11})(?![A-Za-z0-9])", text):
            if tok in plain and tok not in CAPS_STOP:
                out.append(plain[tok])
        return list(dict.fromkeys(out))
    return tag


# ---------------------------------------------------------------- order size
AMT = re.compile(r"(?:rs\.?|inr|₹)\s*([\d,]+(?:\.\d+)?)\s*(crores?|cr\.?|lakhs?|lacs?|million|mn|billion|bn)?", re.I)


def order_crore(text: str) -> Optional[float]:
    """Largest rupee amount in the text, in crore. None when no amount with a clear unit."""
    best = None
    for num_s, unit in AMT.findall(text or ""):
        try:
            v = float(num_s.replace(",", ""))
        except ValueError:
            continue
        u = (unit or "").lower()
        if u.startswith("cr"):
            c = v
        elif u.startswith("la"):
            c = v / 100
        elif u in ("million", "mn"):
            c = v / 10
        elif u in ("billion", "bn"):
            c = v * 100
        elif v >= 1e5:
            c = v / 1e7                       # plain rupees, e.g. Rs. 27,02,56,350/-
        else:
            continue
        best = c if best is None else max(best, c)
    return round(best, 2) if best else None


# ---------------------------------------------------------------- clustering
STOPW = set("the a an of to in on for and or with at by from as is are was were be its it this that after over amid into up down "
            "says said new will may could how why what who news today live update stock stocks shares share market markets".split())


def _toks(t: str) -> set:
    return {w for w in re.findall(r"[a-z0-9]+", t.lower()) if len(w) > 2 and w not in STOPW}


def cluster(items: list[dict]) -> list[dict]:
    """Same story from several publishers -> one item (the earliest) with every source listed."""
    items = sorted(items, key=lambda x: x["time"])
    out: list[dict] = []
    for it in items:
        tk = _toks(it["title"])
        hit = None
        if it["kind"] == "news" and len(tk) >= 3:
            t0 = datetime.fromisoformat(it["time"])
            for o in reversed(out[-200:]):
                if o["kind"] != "news" or abs((datetime.fromisoformat(o["time"]) - t0).total_seconds()) > 36 * 3600:
                    continue
                ot = o["_tk"]
                if len(tk & ot) / max(1, len(tk | ot)) >= 0.5:
                    hit = o
                    break
        if hit:
            if all(s["name"] != it["source"] for s in hit["sources"]):
                hit["sources"].append({"name": it["source"], "url": it["url"]})
            hit["symbols"] = list(dict.fromkeys(hit["symbols"] + it["symbols"]))
            if it.get("market") and it["market"] not in hit["markets"]:
                hit["markets"].append(it["market"])
            if not hit.get("image") and it.get("image"):
                hit["image"], hit["image_by"] = it["image"], it["source"]
        else:
            out.append(dict(it, _tk=tk, sources=[{"name": it["source"], "url": it["url"]}], image_by=it["source"] if it.get("image") else None,
                            markets=[it["market"]] if it.get("market") else []))
    for o in out:
        o.pop("_tk", None)
    return out


# ---------------------------------------------------------------- refresh
def _names(market: str) -> dict:
    """{symbol: name} for the stocks the app tracks (NIFTY 500 / S&P 500)."""
    from . import movers
    hit = store.get_company(movers._key(market))
    rows = hit[1]["rows"] if hit else []
    names = {r["symbol"]: r.get("name") or "" for r in rows}
    if market == "US":
        try:
            from . import us
            tk = {f"US:{t['ticker']}": t["name"] for t in us.tickers()}
            names = {s: (n if n and n != s.replace("US:", "") else tk.get(s, "")) for s, n in names.items()}
        except Exception:  # noqa: BLE001
            pass
    return names


_tag_cache: dict = {}


def tagger(market: str):
    """The stock tagger for a market, rebuilt every 30 minutes (names come from the app's stock lists)."""
    hit = _tag_cache.get(market)
    if hit and time.time() - hit[0] < 1800:
        return hit[1]
    f = build_tagger(_names(market))
    _tag_cache[market] = (time.time(), f)
    return f


def _saved() -> dict:
    hit = store.get_company("NEWS::ITEMS")
    return hit[1] if hit else {}


def _keep(it: dict, markets_only: bool) -> Optional[str]:
    """The item's category, or None when it is not market news."""
    if NOISE.search(it["title"]):
        return None
    cat = classify(it["title"]) or classify(it.get("summary", ""))
    if it["symbols"]:
        return cat if cat not in (None, "markets") else "company"
    if cat in ("economy", "global", "markets"):
        return cat
    if markets_only and cat:
        return cat
    return None


def refresh() -> dict:
    if config.DEMO:
        return demo_fill()
    with _lock:
        if STATE["running"]:
            return STATE
        STATE["running"] = True
    try:
        saved = _saved()
        _tag_cache.clear()
        taggers = {m: tagger(m) for m in ("IN", "US")}
        fresh: list[dict] = []
        for fid, name, url, mkt, kind, mo in FEEDS:
            try:
                entries = parse_feed(_fetch(url))
                st = {"name": name, "ok": bool(entries), "count": len(entries), "error": None if entries else "no items read", "at": time.time()}
            except Exception as e:  # noqa: BLE001 - one source failing never stops the others
                entries, st = [], {"name": name, "ok": False, "count": 0, "error": e.__class__.__name__, "at": time.time()}
            STATE["feeds"][fid] = st
            for e in entries:
                if kind == "official":
                    keep = RBI_KEEP if fid == "rbi" else FED_KEEP
                    if not keep.search(e["title"]):
                        continue
                    fresh.append({"id": _id(fid, e["url"] or e["title"]), "kind": "official", "market": mkt, "title": e["title"],
                                  "summary": e["summary"], "url": e["url"], "time": e["time"], "category": "economy",
                                  "symbols": [], "source": name})
                    continue
                syms = []
                for m in (("IN", "US") if mkt == "GLOBAL" else (mkt,)):
                    syms += taggers[m](f"{e['title']} {e['summary'][:240]}")
                it = {"id": _id(fid, e["url"] or e["title"]), "kind": "news", "market": mkt, "title": e["title"], "summary": e["summary"],
                      "url": e["url"], "time": e["time"], "symbols": syms[:6], "source": name, "image": e.get("image")}
                cat = _keep(it, mo)
                if cat:
                    it["category"] = cat
                    fresh.append(it)
        try:
            from . import flows
            text = flows._nse_text(NSE_ANN)
            got = parse_nse_announcements(text or "")
            STATE["feeds"]["nse"] = {"name": "NSE company filings", "ok": text is not None, "count": len(got), "error": None, "at": time.time()}
            fresh += got
        except Exception as e:  # noqa: BLE001
            STATE["feeds"]["nse"] = {"name": "NSE company filings", "ok": False, "count": 0, "error": str(e)[:120], "at": time.time()}
        try:
            from . import us
            sp = set(_names("US"))
            c2t = {t["cik"]: t["ticker"] for t in us.tickers() if f"US:{t['ticker']}" in sp}
            got = parse_sec_8k(us.get_text(SEC_8K), c2t)
            STATE["feeds"]["sec"] = {"name": "SEC 8-K filings", "ok": True, "count": len(got), "error": None, "at": time.time()}
            fresh += got
        except Exception as e:  # noqa: BLE001
            STATE["feeds"]["sec"] = {"name": "SEC 8-K filings", "ok": False, "count": 0, "error": str(e)[:120], "at": time.time()}
        cut = (datetime.now(timezone.utc) - timedelta(days=KEEP_DAYS)).isoformat()
        for it in fresh:
            if it["time"] >= cut and it["id"] not in saved:
                saved[it["id"]] = it
            elif it["id"] in saved and it.get("image") and not saved[it["id"]].get("image"):
                saved[it["id"]]["image"] = it["image"]                 # items saved before pictures were read
        saved = {k: v for k, v in saved.items() if v["time"] >= cut}
        store.put_company("NEWS::ITEMS", saved)
        STATE["last"] = time.time()
        try:
            from . import alerts
            alerts.dispatch()
        except Exception as e:  # noqa: BLE001 - alerts never stop the news
            STATE["feeds"]["telegram"] = {"name": "Telegram alerts", "ok": False, "count": 0, "error": str(e)[:120], "at": time.time()}
        try:
            if fill_pictures(saved):
                store.put_company("NEWS::ITEMS", saved)
        except Exception:  # noqa: BLE001
            pass
    finally:
        STATE["running"] = False
    return STATE


def maybe_refresh() -> None:
    if not STATE["running"] and time.time() - STATE["last"] > REFRESH_S:
        threading.Thread(target=refresh, daemon=True).start()


def _loop():
    while True:
        try:
            refresh()
        except Exception:  # noqa: BLE001
            pass
        time.sleep(REFRESH_S)


def start_background() -> None:
    if config.DEMO:
        return
    threading.Thread(target=_loop, name="news", daemon=True).start()


# ---------------------------------------------------------------- breaking
SEVERE = re.compile(r"\b(wars?|attack(?:s|ed)?|missiles?|air ?strikes?|invasion|invades?|bomb(?:ing|ings|s)?|blasts?|explosions?|terror\w*|"
                    r"coup|martial law|assassinat\w*|earthquake|tsunami|nuclear|state of emergency|emergency (?:meeting|rate cut|cut|session)|"
                    r"government shutdown|defaults?|defaulted|collapses?|collapsed|crash(?:es|ed)?|plunge[sd]?|tumbles?|tumbled|"
                    r"circuit (?:breaker|filter)|trading halt|halted|sanctions?|evacuat\w*|hostages?|ceasefire|escalat\w*|retaliat\w*|"
                    r"surprise (?:rate|cut|hike)|meltdown|bloodbath|black (?:monday|friday))\b", re.I)
BREAK_HOURS = 6
INDEX_ALERT = 2.0          # % move of NIFTY 50 / SENSEX / S&P 500 / Nasdaq in a day


def breaking_from(items: list[dict], index_items: list[dict], now: Optional[datetime] = None) -> list[dict]:
    """Breaking = a serious market-wide event in the last 6 hours that at least two publishers report (or a central bank
    announces), plus any main index moving 2% or more today. Every item rests on its sources; nothing is guessed."""
    now = now or datetime.now(timezone.utc)
    cut = (now - timedelta(hours=BREAK_HOURS)).isoformat()
    out = [dict(i, breaking="event") for i in items if i["time"] >= cut and i["category"] in ("global", "economy", "markets")
           and SEVERE.search(i["title"]) and (len(i.get("sources") or []) >= 2 or i["kind"] == "official")]
    for x in index_items or []:
        p, t = x.get("change_pct"), x.get("time")
        if p is None or abs(p) < INDEX_ALERT or not t or x.get("kind") not in (None, "index") or "VIX" in str(x.get("name", "")).upper():
            continue
        when = datetime.fromtimestamp(t, timezone.utc)
        if when.isoformat() < cut:
            continue
        verb = "falls" if p < 0 else "jumps"
        out.append({"id": f"idx-{x['symbol']}-{when.date()}", "kind": "market", "market": x.get("market"), "category": "markets",
                    "title": f"{x['name']} {verb} {abs(p):.1f}% today", "breaking": "index",
                    "summary": f"{x['name']} at {x.get('price') or 0:,} ({'+' if p > 0 else ''}{x.get('change') or 0:,} points), by the latest index price.",
                    "url": "", "time": when.isoformat(), "symbols": [], "source": "Index prices",
                    "sources": [{"name": "Index prices", "url": ""}]})
    out.sort(key=lambda i: i["time"], reverse=True)
    return out


# A war, attack, disaster or oil shock moves markets everywhere: it is breaking for India AND the US, whichever
# publisher reports it. Other events (a rate cut, a crash, a shutdown) stay with the market whose publishers carry them.
WORLD = re.compile(r"\b(wars?|attack(?:s|ed)?|missiles?|air ?strikes?|strikes on|invasion|invades?|bomb(?:ing|ings|s)?|blasts?|"
                   r"explosions?|terror\w*|coup|martial law|assassinat\w*|earthquake|tsunami|nuclear|sanctions?|evacuat\w*|"
                   r"hostages?|ceasefire|escalat\w*|retaliat\w*|crude|oil|opec|refiner(?:y|ies)|strait of hormuz|red sea)\b", re.I)


def event_pool(market: str) -> list[dict]:
    """Every saved news story, one per story, with all its publishers from every feed; kept for this market when a
    feed for this market (or a world feed) carries it, or when it is a world event."""
    market = market.upper()
    every = cluster([dict(v) for v in _saved().values()])
    return [i for i in every if set(i.get("markets") or []) & {market, "GLOBAL"} or WORLD.search(i["title"])]


def breaking_now(market: str) -> list[dict]:
    market = market.upper()
    if config.DEMO and not _saved():
        demo_fill()
    items = event_pool(market)
    try:
        from . import indices
        idx = indices.get(market)["items"]
    except Exception:  # noqa: BLE001
        idx = []
    return breaking_from(items, idx)


# ---------------------------------------------------------------- payload
def _prices(market: str) -> dict:
    """{symbol: {d1, name, mcap}} from the app's own daily prices (and market value where known)."""
    try:
        from . import heatmap
        rows = heatmap.get(market, "1D")["rows"]
    except Exception:  # noqa: BLE001
        return {}
    return {r["symbol"]: {"d1": (r.get("ret") or {}).get("1D"), "name": r.get("name"), "mcap": r.get("mcap")} for r in rows}


def get(market: str) -> dict:
    market = market.upper()
    if not config.DEMO:
        maybe_refresh()
    elif not _saved():
        demo_fill()
    items = [dict(v) for v in _saved().values() if v["market"] in (market, "GLOBAL")]
    tg = tagger(market)
    for it in items:                       # news is tagged again with today's rules, so a fixed rule fixes old items too
        if it["kind"] == "news":
            it["symbols"] = tg(f"{it['title']} {it.get('summary', '')[:240]}")[:6]
    items = cluster(items)
    items.sort(key=lambda x: x["time"], reverse=True)
    px = _prices(market)
    for it in items:
        it["tags"] = [{"symbol": s, "d1": (px.get(s) or {}).get("d1"), "name": (px.get(s) or {}).get("name")} for s in it["symbols"]
                      if (s.startswith("US:") if market == "US" else not s.startswith("US:"))]
        it["covered"] = len(it["sources"])
        if it["category"] == "orders" and it["kind"] == "filing" and market == "IN":
            amt = order_crore(f"{it.get('subject', '')} {it.get('summary', '')}")
            mc = (px.get(it["symbols"][0]) or {}).get("mcap")
            if amt:
                it["order"] = {"crore": amt, "pct_mcap": round(100 * amt / mc, 2) if mc else None}
    day = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    recent = [i for i in items if i["time"] >= day]
    count: dict = {}
    for i in recent:
        for t in i["tags"]:
            count[t["symbol"]] = count.get(t["symbol"], 0) + 1
    mentioned = sorted(count.items(), key=lambda x: -x[1])[:10]
    movers = {}
    for i in recent:
        for t in i["tags"]:
            if t["d1"] is not None and abs(t["d1"]) >= 3 and t["symbol"] not in movers:
                movers[t["symbol"]] = {"symbol": t["symbol"], "name": t["name"], "d1": t["d1"], "title": i["title"], "id": i["id"]}
    ids = [f[0] for f in FEEDS if f[3] in (market, "GLOBAL")] + (["nse"] if market == "IN" else ["sec"])
    feeds = [dict(STATE["feeds"][k], id=k) for k in ids if k in STATE["feeds"]]
    try:
        from . import indices
        idx = [] if config.DEMO else indices.get(market)["items"]
    except Exception:  # noqa: BLE001
        idx = []
    return {"market": market, "items": items[:400], "count": len(items), "breaking": breaking_from(event_pool(market), idx)[:5],
            "top": sorted([i for i in recent if i["covered"] >= 2 or i["kind"] == "official"], key=lambda i: (-i["covered"], i["time"]))[:6],
            "mentioned": [{"symbol": s, "n": n, "d1": (px.get(s) or {}).get("d1"), "name": (px.get(s) or {}).get("name")} for s, n in mentioned],
            "movers": sorted(movers.values(), key=lambda x: -abs(x["d1"]))[:8],
            "cats": [{"key": c, "label": CAT_LABEL[c], "n": sum(1 for i in items if i["category"] == c)} for c in CATS],
            "feeds": feeds, "refreshed": STATE["last"] or None, "running": STATE["running"]}


# ---------------------------------------------------------------- demo (offline screenshots and tests only)
def demo_fill() -> dict:
    now = datetime.now(timezone.utc)
    t = lambda h: (now - timedelta(hours=h)).isoformat()
    demo = [
        {"kind": "filing", "market": "IN", "title": "Test Industries Ltd — Receipt of order worth Rs 1,250 crore from a state utility",
         "subject": "Award of Order / Receipt of Order", "summary": "Test Industries Ltd has received an order worth Rs 1,250 crore.",
         "url": "", "time": t(1), "category": "orders", "symbols": ["TESTCO"], "source": "NSE filing"},
        {"kind": "filing", "market": "IN", "title": "Test Bank Ltd — Financial results for the quarter ended September 30, 2026",
         "subject": "Financial Results", "summary": "Board approved the unaudited results.", "url": "", "time": t(3), "category": "results",
         "symbols": ["TESTBANK"], "source": "NSE filing"},
        {"kind": "official", "market": "IN", "title": "Monetary Policy Statement, 2026-27: Resolution of the Monetary Policy Committee",
         "summary": "", "url": "", "time": t(5), "category": "economy", "symbols": [], "source": "Reserve Bank of India"},
        {"kind": "news", "market": "IN", "title": "Sensex, Nifty end higher as banks gain; FPIs buy for third day", "summary": "Demo item.",
         "url": "", "time": t(2), "category": "markets", "symbols": [], "source": "Demo publisher A"},
        {"kind": "news", "market": "IN", "title": "Sensex, Nifty end higher as banks gain; FPIs buy for a third day", "summary": "Demo item.",
         "url": "", "time": t(2.2), "category": "markets", "symbols": [], "source": "Demo publisher B"},
        {"kind": "news", "market": "GLOBAL", "title": "Missile attack on Gulf oil terminal; crude jumps 6%", "summary": "Demo item.",
         "url": "", "time": t(0.5), "category": "global", "symbols": [], "source": "Demo publisher C"},
        {"kind": "news", "market": "GLOBAL", "title": "Missile attack on Gulf oil terminal, crude jumps 6 per cent", "summary": "Demo item.",
         "url": "", "time": t(0.6), "category": "global", "symbols": [], "source": "Demo publisher D"},
        {"kind": "news", "market": "GLOBAL", "title": "Oil prices climb as OPEC+ extends output cuts", "summary": "Demo item.",
         "url": "", "time": t(4), "category": "global", "symbols": [], "source": "Demo publisher C"},
        {"kind": "filing", "market": "US", "title": "Test Corp Us — Results of operations", "subject": "8-K items 2.02, 9.01",
         "summary": "Form 8-K filed with the SEC: Results of operations.", "url": "", "time": t(2), "category": "results",
         "symbols": ["US:TSTUS"], "source": "SEC 8-K"},
        {"kind": "official", "market": "US", "title": "Federal Reserve issues FOMC statement", "summary": "", "url": "", "time": t(6),
         "category": "economy", "symbols": [], "source": "Federal Reserve"},
    ]
    saved = {}
    for d in demo:
        d["id"] = _id(d["source"], d["title"])
        saved[d["id"]] = d
    store.put_company("NEWS::ITEMS", saved)
    STATE["last"] = time.time()
    STATE["feeds"] = {"nse": {"name": "NSE company filings", "ok": True, "count": 2, "error": None, "at": time.time()}}
    return STATE
