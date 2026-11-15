"""Take every README screenshot on YOUR laptop, with real companies and live data.

    1. Start EquityLens (EquityLens.vbs or start.bat).
    2. In PowerShell, from the backend folder:
         python tools\\make_screenshots.py
       (optional)  python tools\\make_screenshots.py --india GRAVITA --us US:AAPL --ai

Desktop shots (1440 x 900) go to docs/screenshots/desktop, phone shots (390 x 844 at 2x)
to docs/screenshots, with the same file names the README already uses.
Pages with your own data (portfolio, broker keys, network address) are never captured.
--ai also clicks "Write note" on the AI tab (uses your AI key once).
Needs:  pip install playwright   (uses your installed Chrome or Edge)
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_video import ROOT, api, log, warm_up  # noqa: E402

D, M = "desktop", "phone"


def shots(ind: str, us: str) -> list:
    """(device, file, market, route, scroll-to heading, options)"""
    s = f"stock/{ind}"
    u = f"stock/{us}"
    return [
        # ---- desktop (README "Desktop" table)
        (D, "home", "IN", "", None, {}),
        (D, "overview", "IN", f"{s}/overview", None, {}),
        (D, "chart", "IN", f"{s}/chart", None, {}),
        (D, "chart_outlook", "IN", f"{s}/chart", "What the chart says", {}),
        (D, "valuation", "IN", f"{s}/valuation", None, {}),
        (D, "forensics", "IN", f"{s}/forensics", None, {}),
        (D, "money_stock", "IN", f"{s}/money", None, {}),
        (D, "ai", "IN", f"{s}/ai", None, {"ai": True}),
        (D, "us_stock", "US", f"{u}/overview", None, {}),
        (D, "movers", "IN", "movers", None, {}),
        (D, "movers_fno", "IN", "movers", None, {"fno": True}),
        (D, "movers_light", "IN", "movers", None, {"light": True}),
        (D, "calendar", "US", "calendar/results", None, {}),
        (D, "calendar_economy", "IN", "calendar/economy", None, {}),
        (D, "rankings", "IN", "rankings", None, {}),
        (D, "screener", "IN", "screener", None, {}),
        (D, "guide", "IN", "guide", None, {}),
        # ---- phone (README "Phone" table + the rest of docs/screenshots)
        (M, "overview", "IN", f"{s}/overview", None, {}),
        (M, "light_overview", "IN", f"{s}/overview", None, {"light": True}),
        (M, "quarter", "IN", f"{s}/overview", "Latest quarter", {}),
        (M, "timeline", "IN", f"{s}/financials", "The 10-year story", {}),
        (M, "chart", "IN", f"{s}/chart", None, {}),
        (M, "chart_outlook", "IN", f"{s}/chart", "What the chart says", {}),
        (M, "future", "IN", f"{s}/future", None, {}),
        (M, "valuation", "IN", f"{s}/valuation", None, {}),
        (M, "peers", "IN", f"{s}/valuation", "Where it ranks among peers", {}),
        (M, "forensics", "IN", f"{s}/forensics", None, {}),
        (M, "money_stock", "IN", f"{s}/money", None, {}),
        (M, "ai", "IN", f"{s}/ai", None, {"ai": True}),
        (M, "guidance", "IN", f"{s}/ai", "Management guidance check", {}),
        (M, "us_stock", "US", f"{u}/overview", None, {}),
        (M, "us_search", "US", "", None, {"type": us.replace("US:", "")}),
        (M, "indices", "IN", "", None, {}),
        (M, "movers", "IN", "movers", None, {}),
        (M, "movers_filters", "IN", "movers", None, {"fno": True}),
        (M, "us_movers", "US", "movers", None, {}),
        (M, "money_delivery", "IN", "money/delivery", None, {}),
        (M, "money_insiders", "IN", "money/insiders", None, {}),
        (M, "calendar_us", "US", "calendar/results", None, {}),
        (M, "calendar_economy_in", "IN", "calendar/economy", None, {}),
        (M, "calendar_economy_us", "US", "calendar/economy", None, {}),
        (M, "screener", "IN", "screener", None, {}),
        (M, "guide", "IN", "guide", None, {}),
    ]


def settle(pg) -> None:
    pg.wait_for_timeout(3000)
    try:                                   # nothing on screen may still say "Loading…"
        pg.wait_for_function("() => !/Loading/.test(document.querySelector('main')?.innerText || '')", timeout=45000)
    except Exception:  # noqa: BLE001
        log("    (still loading after 45 s, captured as is)")
    pg.wait_for_timeout(1000)


def shoot(base: str, todo: list, out: Path, ai: bool) -> int:
    from playwright.sync_api import sync_playwright
    done = 0
    with sync_playwright() as p:
        br = None
        for ch in ("chrome", "msedge", None):
            try:
                br = p.chromium.launch(channel=ch) if ch else p.chromium.launch()
                log(f"  using {ch or 'playwright chromium'}")
                break
            except Exception:  # noqa: BLE001
                continue
        if br is None:
            sys.exit("Could not start Chrome or Edge. Install Google Chrome, or run:  python -m playwright install chromium")
        ctx = {
            D: br.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=1, color_scheme="dark"),
            M: br.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True,
                              color_scheme="dark"),
        }
        pages = {k: c.new_page() for k, c in ctx.items()}
        for i, (dev, name, mk, route, scroll, o) in enumerate(todo):
            pg = pages[dev]
            log(f"  {i + 1}/{len(todo)} {dev:7s} {name}")
            try:
                pg.goto(base + "/#/")
                pg.evaluate("""([mk, th, fno]) => { localStorage.setItem('eql_market', mk); localStorage.setItem('eql_theme', th);
                    localStorage.setItem('eql_fno', fno); localStorage.setItem('eql_univ', 'N500') }""",
                            [mk, "light" if o.get("light") else "dark", "1" if o.get("fno") else "0"])
                pg.goto(base + "/#/" + route)
                pg.reload()
                settle(pg)
                if o.get("ai") and ai:
                    try:
                        pg.click("button:has-text('Write note')", timeout=4000)
                        pg.wait_for_function("() => !/Writing|Thinking|Reading/.test(document.querySelector('main')?.innerText || '')",
                                             timeout=120000)
                    except Exception:  # noqa: BLE001
                        log("    (AI note skipped)")
                if o.get("type"):
                    box = pg.locator("input").first
                    box.click()
                    box.fill(o["type"])
                    pg.wait_for_timeout(3000)
                top = 150 if dev == D else 120              # room for the sticky top bar
                if scroll:
                    try:
                        h = pg.locator(f"h3:has-text('{scroll}')").first
                        h.wait_for(timeout=4000)
                        h.evaluate(f"e => window.scrollTo(0, e.getBoundingClientRect().top + window.scrollY - {top})")
                    except Exception:  # noqa: BLE001
                        log(f"    ('{scroll}' not found, captured the top of the page)")
                elif dev == M and route.startswith("stock/") and not route.endswith("/overview"):
                    # on a phone the company header fills the screen: start the shot at the tab bar instead
                    pg.evaluate("""() => { const t = document.querySelector('.tabs');
                        if (t) window.scrollTo(0, t.getBoundingClientRect().top + window.scrollY - 64) }""")
                else:
                    pg.evaluate("window.scrollTo(0, 0)")
                pg.wait_for_timeout(700)
                folder = out / "desktop" if dev == D else out
                folder.mkdir(parents=True, exist_ok=True)
                pg.screenshot(path=str(folder / f"{name}.png"))
                done += 1
            except Exception as e:  # noqa: BLE001
                log(f"    (failed: {e.__class__.__name__}: {str(e)[:120]})")
        br.close()
    return done


def main() -> None:
    ap = argparse.ArgumentParser(description="Take the README screenshots with real companies and live data")
    ap.add_argument("--india", default="GRAVITA")
    ap.add_argument("--us", default="US:AAPL")
    ap.add_argument("--url", default="http://localhost:8600")
    ap.add_argument("--out", default=str(ROOT / "docs" / "screenshots"))
    ap.add_argument("--ai", action="store_true", help="also write an AI research note on the AI tab (uses your AI key)")
    ap.add_argument("--only", default="", help="comma-separated file names, e.g. overview,movers")
    a = ap.parse_args()
    ind = a.india.upper()
    us = a.us.upper() if a.us.upper().startswith("US:") else "US:" + a.us.upper()
    try:
        api(a.url, "/api/health")
    except Exception:  # noqa: BLE001
        sys.exit("EquityLens is not running. Start it first (EquityLens.vbs or start.bat), then run this again.")
    t0 = time.time()
    log("1/2 Loading live data ...")
    warm_up(a.url, ind, us)
    todo = shots(ind, us)
    if a.only:
        keep = {x.strip() for x in a.only.split(",")}
        todo = [t for t in todo if t[1] in keep]
    log(f"2/2 Taking {len(todo)} screenshots ...")
    n = shoot(a.url, todo, Path(a.out), a.ai)
    log(f"\nDONE: {n}/{len(todo)} screenshots in {a.out}  ({int(time.time() - t0)} s)")
    log("Check a few in File Explorer, then push them to GitHub:")
    log('  cd ..')
    log('  git add docs/screenshots')
    log('  git commit -m "Screenshots with live data"')
    log('  git push')


if __name__ == "__main__":
    main()
