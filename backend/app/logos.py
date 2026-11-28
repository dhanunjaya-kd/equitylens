"""Company logos for 🇮🇳 and 🇺🇸 stocks, no keys.

Order tried (first real image wins, saved to data/logos/ so each logo is downloaded once):
  1. Financial Modeling Prep public logo images  financialmodelingprep.com/image-stock/{AAPL | RELIANCE.NS}.png
  2. The company's own website icon (website from the company page / SEC record) via Google's favicon service
  3. A coloured initials badge drawn here (never a broken image)
"""
from __future__ import annotations

import hashlib
import re
import threading
import time
from html import escape
from typing import Optional
from urllib.parse import urlparse

import requests

from . import config, store

DIR = config.DATA_DIR / "logos"
_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"}
RETRY_MISS_DAYS = 14
PALETTE = ["#0ea5e9", "#14b8a6", "#22c55e", "#84cc16", "#f59e0b", "#f97316", "#ef4444", "#ec4899", "#a855f7", "#6366f1"]
_STOP = {"ltd", "limited", "inc", "inc.", "corp", "corporation", "co", "company", "plc", "the", "of", "and", "&", "india", "holdings", "group"}


def _safe(sym: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", sym.upper())


def initials(sym: str, name: str = "") -> str:
    words = [w for w in re.findall(r"[A-Za-z0-9]+", name or "") if w.lower() not in _STOP]
    if len(words) >= 2:
        return (words[0][0] + words[1][0]).upper()
    base = (words[0] if words else sym.replace("US:", ""))
    return base[:2].upper()


def monogram(sym: str, name: str = "") -> bytes:
    col = PALETTE[int(hashlib.md5(sym.encode()).hexdigest(), 16) % len(PALETTE)]
    txt = escape(initials(sym, name))
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="14" fill="{col}"/>'
            f'<text x="32" y="41" text-anchor="middle" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="{24 if len(txt) > 1 else 28}" '
            f'font-weight="800" fill="#fff">{txt}</text></svg>').encode()


def _is_image(r: requests.Response, min_bytes: int = 300) -> bool:
    ct = r.headers.get("Content-Type", "")
    return r.status_code == 200 and ct.startswith("image/") and len(r.content) >= min_bytes


def _ext(r: requests.Response) -> str:
    ct = r.headers.get("Content-Type", "")
    return "svg" if "svg" in ct else "jpg" if "jpeg" in ct else "ico" if "icon" in ct else "png"


def _website(sym: str) -> Optional[str]:
    hit = store.get_company(sym)
    site = ((hit[1].get("company") or {}).get("website") if hit else None) or ""
    host = urlparse(site if "://" in site else "https://" + site).hostname if site else None
    return host.removeprefix("www.") if host else None


def _download(sym: str) -> Optional[tuple[bytes, str]]:
    t = sym[3:] if sym.startswith("US:") else f"{sym}.NS"
    tries = [f"https://financialmodelingprep.com/image-stock/{t}.png"]
    if not sym.startswith("US:"):
        tries.append(f"https://financialmodelingprep.com/image-stock/{sym}.BO.png")
    for url in tries:
        try:
            r = requests.get(url, headers=_UA, timeout=10)
            if _is_image(r):
                return r.content, _ext(r)
        except requests.RequestException:
            pass
    host = _website(sym)
    if host:
        try:
            r = requests.get("https://www.google.com/s2/favicons", params={"domain": host, "sz": 128}, headers=_UA, timeout=10)
            if _is_image(r, 600):         # Google's default globe is tiny; real icons are bigger
                return r.content, _ext(r)
        except requests.RequestException:
            pass
    return None


MEDIA = {"png": "image/png", "jpg": "image/jpeg", "svg": "image/svg+xml", "ico": "image/x-icon"}


_queue: list = []
_queued: set = set()
_qlock = threading.Lock()
_workers = [0]


def _fetch_one(sym: str) -> None:
    base = _safe(sym)
    got = _download(sym)
    if got:
        data, ext = got
        (DIR / f"{base}.{ext}").write_bytes(data)
        (DIR / f"{base}.miss").unlink(missing_ok=True)
    else:
        (DIR / f"{base}.miss").write_text(str(time.time()))


def _worker() -> None:
    while True:
        with _qlock:
            if not _queue:
                _workers[0] -= 1
                return
            sym = _queue.pop(0)
        try:
            _fetch_one(sym)
        except Exception:  # noqa: BLE001
            pass
        finally:
            with _qlock:
                _queued.discard(sym)


def _later(sym: str) -> None:
    """Download in the background (4 at a time). A page never waits for a logo."""
    with _qlock:
        if sym in _queued:
            return
        _queued.add(sym)
        _queue.append(sym)
        start = _workers[0] < 4
        if start:
            _workers[0] += 1
    if start:
        threading.Thread(target=_worker, daemon=True).start()


def lookup(sym: str, name: str = "") -> tuple[bytes, str, bool]:
    """(image, media type, final). Not final = initials shown while the real logo downloads."""
    sym = sym.upper()
    DIR.mkdir(parents=True, exist_ok=True)
    base = _safe(sym)
    for ext in ("png", "jpg", "svg", "ico"):
        f = DIR / f"{base}.{ext}"
        if f.exists():
            return f.read_bytes(), MEDIA[ext], True
    miss = DIR / f"{base}.miss"
    if config.DEMO or (miss.exists() and time.time() - miss.stat().st_mtime < RETRY_MISS_DAYS * 86400):
        return monogram(sym, name), MEDIA["svg"], True
    _later(sym)
    return monogram(sym, name), MEDIA["svg"], False


def get(sym: str, name: str = "") -> tuple[bytes, str]:
    data, media, _ = lookup(sym, name)
    return data, media
