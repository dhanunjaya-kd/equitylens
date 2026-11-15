"""Film the EquityLens walkthrough video on YOUR laptop, with real companies and live data.

    1. Keep EquityLens running (start.bat) in one window.
    2. In another window, from the backend folder:
         venv\\Scripts\\activate
         pip install playwright imageio-ffmpeg
         python tools\\make_video.py
       (optional)  python tools\\make_video.py --india GRAVITA --us US:AAPL

It uses your installed Google Chrome (or Edge), so no browser download is needed.
Takes about 5-10 minutes the first time (it loads market data first).
Writes docs/equitylens_walkthrough.mp4 and updates the video inside the app.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
W, H, FPS = 1280, 720, 30


def log(msg: str) -> None:
    print(msg, flush=True)


_LOCAL = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # never send localhost through a proxy


def api(base: str, path: str, method: str = "GET", timeout: int = 180):
    req = urllib.request.Request(base + path, method=method, data=b"" if method == "POST" else None)
    with _LOCAL.open(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def warm_up(base: str, ind: str, us_sym: str) -> dict:
    """Load everything the video shows, so every scene has real data."""
    names = {}
    for sym in (ind, us_sym):
        log(f"  loading {sym} report ...")
        rep = api(base, f"/api/stock/{sym}")
        names[sym] = (rep.get("company") or {}).get("name") or sym
        api(base, f"/api/chart/{sym}")
        try:
            api(base, f"/api/flows/stock/{sym}", timeout=300)
        except Exception as e:  # noqa: BLE001
            log(f"  (smart money for {sym} skipped: {e})")
    for mk in ("IN", "US"):
        d = api(base, f"/api/movers?market={mk}")
        if not d.get("rows") or (d.get("status") or {}).get("running"):
            log(f"  loading Market Movers {mk} (first time takes a few minutes) ...")
            if not (d.get("status") or {}).get("running"):
                api(base, f"/api/movers/refresh?market={mk}", "POST")
            t0 = time.time()
            while time.time() - t0 < 900:
                time.sleep(10)
                d = api(base, f"/api/movers?market={mk}")
                st = d.get("status") or {}
                if not st.get("running"):
                    break
                log(f"    {st.get('done', '?')}/{st.get('total', '?')}")
    for path in ("/api/flows/delivery", "/api/flows/insiders?market=IN", "/api/flows/surveillance", "/api/fno",
                 "/api/calendar/earnings?market=IN", "/api/calendar/economy?market=IN",
                 "/api/calendar/earnings?market=US", "/api/calendar/economy?market=US"):
        try:
            log(f"  loading {path.split('?')[0]} ...")
            api(base, path, timeout=300)
        except Exception as e:  # noqa: BLE001
            log(f"  (skipped {path}: {e})")
    return names


def scenes(ind: str, us_sym: str, n: dict) -> list:
    ni, nu = n[ind], n[us_sym]
    U = us_sym.replace("US:", "")
    # (market, route, scroll-to, highlight, kicker, title, body, actions)
    return [
        ("IN", "TITLE", None, None, "", "How to read a company with EquityLens",
         f"A short tour with real data · 🇮🇳 {ni} & 🇺🇸 {nu}", []),
        ("IN", "", None, ".home-grid input", "START", "Search any company",
         "Type a name or symbol. Switch market with 🇮🇳 IND / 🇺🇸 US on the left.", []),
        ("IN", "", None, ".ix-strip", "MARKET AT A GLANCE", "The index card",
         "NIFTY 50, BANK NIFTY, SENSEX and INDIA VIX, live — tap a card for the day and 52-week range.", []),
        ("IN", f"stock/{ind}/overview", None, ".tab-body .card >> nth=0", "STEP 1", f"Read the verdict first · {ni}",
         "One line, a score out of 100. Business score = how good the company is; valuation score = how fair the price is.", []),
        ("IN", f"stock/{ind}/overview", "h3:has-text('Strengths & red flags')", "h3:has-text('Strengths & red flags') >> xpath=..", "STEP 2",
         "Strengths ✅ and red flags 🚩", "Written in plain English: debt, cash, pledging, promoter selling, dilution.", []),
        ("IN", f"stock/{ind}/financials", "h3:has-text('10-year story')", "h3:has-text('10-year story') >> xpath=..", "STEP 3",
         "Is the business growing?", "The 10-year story shows sales and profit year by year — look for steady growth, not one lucky year.", []),
        ("IN", f"stock/{ind}/quality", None, ".tab-body", "STEP 4", "Quality and safety",
         "ROCE = profit on every ₹100 invested (15%+ is good). Profit should turn into cash; debt should stay low.", []),
        ("IN", f"stock/{ind}/forensics", None, ".tab-body", "STEP 5", "A forensic check-up",
         "Piotroski, Altman Z and Beneish look for trouble in the accounts. Just read the colours and the one-line meaning.", []),
        ("IN", f"stock/{ind}/valuation", None, ".tab-body .card >> nth=0", "STEP 6", "Is the price fair?",
         "Fair-value range from 5 methods. A great company can still be a bad buy at the wrong price.", []),
        ("IN", f"stock/{ind}/future", None, ".tab-body .card >> nth=0", "STEP 7", "What could it be worth in 3, 5, 10 years?",
         "Bear, base and bull cases with every assumption visible — and what has to go right.", []),
        ("IN", f"stock/{ind}/money", None, ".tab-body", "STEP 8", "Who is really buying?",
         "Delivery % (shares actually kept), promoter and insider trades, bulk and block deals.", []),
        ("IN", f"stock/{ind}/chart", None, ".tab-body .card >> nth=0", "STEP 9", "Timing with the chart",
         "Above the 200-day average = uptrend. RSI above 70 = overheated. Support and resistance lines are drawn for you.", []),
        ("IN", f"stock/{ind}/ai", None, ".tab-body", "STEP 10", "Ask the AI analyst",
         "Research note, plain-English chat, guidance check and a bull-vs-bear debate — Claude, ChatGPT, Gemini or free Ollama.", []),
        ("US", f"stock/{us_sym}/overview", None, ".tab-body .card >> nth=0", "🇺🇸 US STOCKS", f"Same analysis for {nu}",
         "Built from official SEC filings, shown in dollars.", []),
        ("US", f"stock/{us_sym}/valuation", None, ".tab-body .card >> nth=0", "🇺🇸 US STOCKS", f"Is {U} fairly priced?",
         "The same fair-value range, P/E history and peer comparison for every US company.", []),
        ("US", f"stock/{us_sym}/money", None, ".tab-body", "🇺🇸 US STOCKS", "Insider trades (SEC Form 4)",
         "What the CEO, CFO and directors did with their own shares. Open-market buys matter most.", []),
        ("IN", "movers", None, ".movers-main .card >> nth=0", "EVERY DAY", "Market Movers",
         "Gainers, top buyers and sellers, 52-week highs, volume shockers — for 1 day to 1 year.", []),
        ("IN", "movers", None, ".movers-side .card >> nth=0", "EVERY DAY", "Market mood and sectors",
         "The fear ↔ greed gauge and the sector heatmap tell you what the whole market is doing.", []),
        ("IN", "movers", None, ".fno-tab", "F&O", "🎯 F&O stocks only",
         "One switch filters Movers, Calendar, Smart Money, Screener and Top Picks to F&O stocks.", ["CLICK:.fno-tab"]),
        ("IN", "calendar/results", None, ".movers-main", "CALENDAR", "Results this week",
         "Who reports when, your watchlist first, with the company's EquityLens score.", ["FNO_OFF"]),
        ("US", "calendar/results", None, ".movers-main", "CALENDAR", "US earnings with estimates",
         "Before open / after close, EPS estimate vs last year, then beat or miss.", []),
        ("IN", "calendar/economy", None, ".movers-main .card >> nth=1", "CALENDAR", "Economic events, explained",
         "RBI, CPI, GDP, Fed — official dates, countdowns, and tap any event to see why markets care.", ["CLICK:.ev-row >> nth=0"]),
        ("IN", "money/delivery", None, ".flow-main", "SMART MONEY", "Who is buying the market?",
         "Delivery buying, bulk deals, promoter trades and exchange surveillance red flags — official NSE data.", []),
        ("IN", "screener", None, ".sig-grid", "FIND IDEAS", "3 signature scans",
         "Quality breakout · Smart-money accumulation · Quality on sale. Or build your own rules on 55+ fields.", []),
        ("IN", "rankings", None, ".wrap .card >> nth=1", "FIND IDEAS", "Top Picks",
         "Scan the whole NIFTY 500 or S&P 500 and rank every company by the same rules.", []),
        ("IN", "guide", None, ".guide-cols", "STUCK?", "The beginner guide",
         "11 steps with good and warning signs, a 10-question checklist and a glossary — inside the app.", ["CLICK:.guide-head >> nth=1"]),
        ("IN", "END", None, None, "", "Research smarter, not harder",
         "EquityLens is a research aid, not investment advice.<br><br><span style='color:#2dd4bf'>github.com/dhanunjaya-kd/equitylens</span>", []),
    ]


CSS = """
#__cap{position:fixed;left:24px;right:24px;bottom:22px;z-index:99999;display:flex;gap:16px;align-items:center;
 padding:16px 22px;border-radius:18px;background:rgba(6,10,16,.92);border:1px solid rgba(45,212,191,.55);
 box-shadow:0 12px 40px rgba(0,0,0,.55);font-family:'Twemoji Country Flags',Inter,'Segoe UI',Roboto,sans-serif;color:#e6edf3}
#__cap .k{font-size:13px;font-weight:800;letter-spacing:.08em;color:#0b1016;background:#2dd4bf;padding:6px 11px;border-radius:9px;white-space:nowrap}
#__cap .t{font-size:24px;font-weight:800;line-height:1.15}
#__cap .b{font-size:17px;color:#b6c2cf;margin-top:4px;line-height:1.35}
.__spot{position:relative;z-index:9000;outline:3px solid #2dd4bf !important;outline-offset:4px;border-radius:14px;
 box-shadow:0 0 28px rgba(45,212,191,.55) !important}
"""
CARD = """<html><body style="margin:0;width:1280px;height:720px;display:flex;align-items:center;justify-content:center;
background:radial-gradient(circle at 30% 20%,#13303a,#0b1016 60%);font-family:'Twemoji Country Flags',Inter,'Segoe UI',Roboto,sans-serif;color:#e6edf3">
<div style="text-align:center;max-width:1000px">
<div style="font-size:30px;font-weight:800;margin-bottom:26px"><span style="color:#2dd4bf">Equity</span> Lens</div>
<div style="font-size:52px;font-weight:800;line-height:1.15">{t}</div>
<div style="font-size:24px;color:#9fb0c0;margin-top:22px">{b}</div></div></body></html>"""


def film(base: str, sc: list, out_dir: Path) -> list:
    from playwright.sync_api import sync_playwright
    meta = []
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
        ctx = br.new_context(viewport={"width": W, "height": H}, color_scheme="dark", device_scale_factor=1)
        pg = ctx.new_page()
        pg.goto(base + "/#/")
        pg.evaluate("localStorage.setItem('eql_theme','dark');localStorage.setItem('eql_fno','0')")
        for i, (mk, route, scroll, hi, k, t, b, acts) in enumerate(sc):
            log(f"  scene {i + 1}/{len(sc)}: {route or 'home'}")
            if route in ("TITLE", "END"):
                pg.set_content(CARD.format(t=t, b=b))
                pg.wait_for_timeout(500)
            else:
                pg.evaluate(f"localStorage.setItem('eql_market','{mk}')")
                if "FNO_OFF" in acts:
                    pg.evaluate("localStorage.setItem('eql_fno','0')")
                pg.goto(base + "/#/" + route)
                pg.reload()
                pg.wait_for_timeout(4000)
                for a in acts:
                    if a.startswith("CLICK:"):
                        try:
                            pg.click(a[6:], timeout=4000)
                            pg.wait_for_timeout(1500)
                        except Exception as e:  # noqa: BLE001
                            log(f"    (click skipped: {e.__class__.__name__})")
                pg.add_style_tag(content=CSS)
                if scroll:
                    try:
                        pg.locator(scroll).first.scroll_into_view_if_needed(timeout=3000)
                        pg.evaluate("window.scrollBy(0,-90)")
                    except Exception:  # noqa: BLE001
                        pass
                if hi:
                    try:
                        pg.locator(hi).first.evaluate(
                            "e=>{e.classList.add('__spot'); const r=e.getBoundingClientRect(); if(r.top<70||r.top>380) window.scrollBy(0, r.top-90)}",
                            timeout=3000)
                    except Exception:  # noqa: BLE001
                        pass
                pg.evaluate("""([k,t,b])=>{const d=document.createElement('div');d.id='__cap';
                  d.innerHTML=`<span class="k">${k}</span><div><div class="t">${t}</div><div class="b">${b}</div></div>`;document.body.appendChild(d)}""",
                            [k, t, b])
                pg.wait_for_timeout(600)
            f = out_dir / f"f{i:02d}.jpg"
            pg.screenshot(path=str(f), type="jpeg", quality=92)
            plain = (t + b).replace("<br>", "")
            dur = 5.5 if route in ("TITLE", "END") else max(4.5, 2.2 + len(plain) / 17)
            meta.append((f, round(dur, 2)))
        br.close()
    return meta


def encode(meta: list, out_dir: Path, target: Path) -> None:
    import imageio_ffmpeg
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    names = []
    for i, (img, d) in enumerate(meta):
        name, tmp = f"s{i:02d}.mp4", f"s{i:02d}.tmp.mp4"
        vf = f"scale={W}:{H},format=yuv420p,loop=-1:1,trim=duration={d},fade=t=in:st=0:d=0.35,fade=t=out:st={d - 0.35}:d=0.35"
        r = subprocess.run([ff, "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", img.name, "-vf", vf, "-r", str(FPS),
                            "-c:v", "libx264", "-crf", "20", "-preset", "veryfast", "-pix_fmt", "yuv420p", tmp], cwd=out_dir)
        if r.returncode:
            sys.exit(f"ffmpeg failed on scene {i + 1}")
        os.replace(out_dir / tmp, out_dir / name)
        names.append(name)
    (out_dir / "list.txt").write_text("".join(f"file '{n}'\n" for n in names))
    r = subprocess.run([ff, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", "list.txt", "-c", "copy",
                        "-movflags", "+faststart", "walk.tmp.mp4"], cwd=out_dir)
    if r.returncode:
        sys.exit("ffmpeg could not join the scenes")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(out_dir / "walk.tmp.mp4", target)


def main() -> None:
    ap = argparse.ArgumentParser(description="Film the EquityLens walkthrough with real companies")
    ap.add_argument("--india", default="GRAVITA")
    ap.add_argument("--us", default="US:AAPL")
    ap.add_argument("--url", default="http://localhost:8600")
    a = ap.parse_args()
    us_sym = a.us if a.us.upper().startswith("US:") else "US:" + a.us
    try:
        api(a.url, "/api/health")
    except Exception:  # noqa: BLE001
        sys.exit("EquityLens is not running. Start it first with start.bat, then run this again.")
    work = ROOT / "backend" / "data" / "video"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    log("1/3 Loading live data ...")
    names = warm_up(a.url, a.india.upper(), us_sym.upper())
    log("2/3 Filming the app ...")
    meta = film(a.url, scenes(a.india.upper(), us_sym.upper(), names), work)
    log("3/3 Making the video ...")
    target = ROOT / "docs" / "equitylens_walkthrough.mp4"
    encode(meta, work, target)
    for extra in (ROOT / "frontend" / "public" / "guide.mp4", ROOT / "backend" / "static" / "guide.mp4"):
        shutil.copyfile(target, extra)
    shutil.copyfile(meta[3][0], ROOT / "docs" / "screenshots" / "walkthrough_poster.jpg")
    total = sum(d for _, d in meta)
    log(f"\nDONE: {target}  ({int(total // 60)} min {int(total % 60)} s)")
    log("The in-app video (Beginner guide) is updated too. Send me the mp4 or push it to GitHub.")


if __name__ == "__main__":
    main()
