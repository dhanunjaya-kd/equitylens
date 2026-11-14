# EquityLens — Fundamental Research Tool

Search any Indian stock and get a full research report: 10–12 years of financials, quality checks,
ownership trends, valuation vs history and peers, red flags, and a 3 / 5 / 10-year outlook with
bear / base / bull scenarios. A **Top Picks** page ranks the whole NIFTY 500 by the same rules.

No API keys, no logins, no paid data. Fundamentals come from the same public company pages you'd open in a
browser (screener.in); daily prices for the chart come from Yahoo Finance's public chart feed (falls back to
daily closes if that's unavailable). Everything is paced and cached.

## What's in a stock report
| Tab | What you see |
|---|---|
| Overview | Verdict, overall score, 3/5/10-year stance, scorecard, strengths & red flags, quick checks |
| Chart | Candlesticks (daily / weekly, 3M–10Y) with EMA 20/50/200, Bollinger, Supertrend, golden/death crosses, support & resistance, volume, RSI, MACD, ADX; technical-view summary + signal checklist |
| Future 3·5·10y | Bear / base / bull price and yearly return, reverse DCF, every assumption shown |
| Valuation Lab | Fair-value range from several methods, **interactive DCF with sliders**, sensitivity table, P/E bands, Graham number, EV/EBITDA, peers |
| Forensics | **Piotroski F-score** (9 tests), **Altman Z** (bankruptcy risk), **Beneish M** (earnings manipulation), **DuPont** ROE breakdown, accounting checks |
| Financials · Quality · Ownership · Price | 10–12 years of P&L / balance sheet / cash flow / ratios / quarters, ROCE, cash conversion, shareholding trend, 10-yr price |
| Reports | Annual reports, concall transcripts & presentations, announcements, credit ratings (links) |

**Screener:** 9 ready-made screens (quality compounders, value with quality, below fair value,
holding-company discount, debt-free growers, Piotroski 8+, promoters buying, cheap vs own history,
10-year compounders) plus your own rules on 45+ fields. Save screens on your phone.

## Run it (Windows)
1. Double-click `start.bat` (first run creates `backend/venv` and installs 5 small packages).
2. Your browser opens **http://localhost:8600**.
3. On your phone (same Tailscale network as the laptop): `http://<laptop-tailscale-ip>:8600`,
   then Share → *Add to Home Screen*.

Manual:
```
cd backend
py -3.11 -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python selftest.py      # run once: checks the live data source end to end
python run.py
```

## First things to do
| Step | Command / place | What it does |
|---|---|---|
| 1 | `python selftest.py` | Fetches RELIANCE, HDFCBANK, ITC live and prints what was parsed. |
| 2 | Search a stock in the app | Full report in ~5 s; cached for 24 h (↻ Refresh forces a new fetch). |
| 3 | Top Picks → **Quick scan (30)** | Ranks 30 stocks in ~3 min to see the page working. |
| 4 | Top Picks → **Scan NIFTY 500** or `python scan.py` | Full ranking, ~40–60 min. Re-run weekly or after results season. |

## What's inside
```
backend/
  app/scraper.py    fetches public pages (rate-limited, retries, consolidated → standalone fallback)
  app/parser.py     HTML → clean tables (P&L, balance sheet, cash flow, ratios, quarters, shareholding, peers)
  app/analysis.py   the research engine: metrics, 6 scores, red flags, 3/5/10y scenarios, reverse DCF, verdict
  app/service.py    fetch → cache → analyse; NIFTY 500 scan
  app/main.py       API + serves the web app
  static/           prebuilt web app (no npm needed to run)
  run.py  scan.py  selftest.py
  tests/            offline tests with sample company pages
frontend/           React source (only needed if you change the UI: npm install && npm run build)
```

## How the verdict works (all rule-based, all visible in the app)
- **Scores 0–100:** Growth, Quality (ROCE/ROE), Financial strength (debt, interest cover), Cash generation
  (operating cash ÷ profit), Ownership (promoter & institutional trends, pledging), Valuation (P/E, PEG,
  P/E vs own 10-yr median, P/B for lenders).
  Business score = first five; Overall = 80% business + 20% valuation.
- **Banks/NBFCs** are detected automatically: ROE replaces ROCE, the equity/assets ratio replaces debt/equity,
  and cash-flow scoring is skipped.
- **Future scenarios:** start from last-12-month EPS, grow it at a blend of 3/5/10-yr profit growth
  (capped at sales growth + 5 and at 25%), fade growth to 4/8/11% by year 10 (bear/base/bull), apply a P/E
  that starts at the 10-yr median and drifts toward 12–25. Returns include dividend yield.
- **Reverse DCF:** the profit growth the current price needs for a 12%/yr return over 10 years.
- **Verdicts:** High quality, fairly priced · High quality, but expensive · Average — keep on watch ·
  Good numbers, serious red flags · Weak — avoid for now · Loss-making — speculative.

Tune assumptions with environment variables: `EQL_REQUIRED_RETURN` (0.12), `EQL_FAIR_EXIT_PE` (20),
`EQL_SCAN_DELAY` (3 s), `EQL_CACHE_TTL_HOURS` (24), `EQL_PORT` (8600).

## Demo mode (no internet)
`set EQL_DEMO=1` then `python run.py`, and search **TESTCO** or **TESTBANK** (made-up sample companies).

## Limits
- Data comes from public pages, so if the site changes its layout the parser may need an update.
  `selftest.py` shows exactly which section broke.
- Scans are paced (~1 request/sec, 3 s between companies). Don't lower the delay much, or the source may block you.
- Everything is based on past numbers. It's a research aid, not investment advice.
