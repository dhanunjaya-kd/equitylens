"""Writes docs/pipeline.svg, the animated "How EquityLens works" diagram:  python tools/make_pipeline_svg.py"""
import sys
from html import escape as e
W, H = 1240, 900
out = []
A = out.append
TEAL, AMBER, SKY, GREEN, PINK, VIOLET = "#2dd4bf", "#f59e0b", "#38bdf8", "#22c55e", "#f472b6", "#a78bfa"
A(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-label="How EquityLens works: public data, exchange and regulator files, news feeds and your broker are fetched, analysed and tested, stored and checked, then shown on laptop or phone and sent to Telegram">')
A('''<style>
  text { font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, Roboto, Helvetica, Arial, sans-serif; }
  .h { font-size: 13px; font-weight: 800; letter-spacing: .09em; fill: #8b9bab; }
  .title { font-size: 24px; font-weight: 800; fill: #e6edf3; }
  .sub { font-size: 14px; fill: #8b9bab; }
  .t { font-size: 16px; font-weight: 700; fill: #e6edf3; }
  .s { font-size: 12.5px; fill: #a9b6c3; }
  .k { font-size: 12.5px; fill: #c9d4de; }
  .num { font-size: 12px; font-weight: 800; fill: #0b1016; text-anchor: middle; }
  .tag { font-size: 10.5px; font-weight: 800; letter-spacing: .06em; }
  .foot { font-size: 13px; fill: #7d8b99; }
  .wire { fill: none; stroke-width: 2; }
  .flow { fill: none; stroke-width: 2.4; stroke-dasharray: 3 14; stroke-linecap: round; animation: flow 1.6s linear infinite; opacity: .9; }
  .glow { fill: none; stroke-width: 3; opacity: 0; animation: pulse 4.8s ease-in-out infinite; }
  .dot { filter: drop-shadow(0 0 4px currentColor); }
  .scan { animation: scan 2.4s ease-in-out infinite; transform-box: fill-box; transform-origin: left center; }
  .blink { animation: blink 2.4s ease-in-out infinite; }
  .ring { animation: ring 1.8s ease-out infinite; transform-box: fill-box; transform-origin: center; }
  @keyframes flow { to { stroke-dashoffset: -34; } }
  @keyframes pulse { 0%, 70%, 100% { opacity: 0; } 15%, 30% { opacity: .9; } }
  @keyframes scan { 0%, 100% { transform: scaleX(.35); } 50% { transform: scaleX(1); } }
  @keyframes blink { 0%, 100% { opacity: .35; } 50% { opacity: 1; } }
  @keyframes ring { 0% { opacity: .9; transform: scale(.6); } 100% { opacity: 0; transform: scale(1.8); } }
  @media (prefers-reduced-motion: reduce) { .flow, .glow, .scan, .blink, .ring { animation: none; } .dot { display: none; } }
</style>
<defs>
  <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#0f1a22"/><stop offset="1" stop-color="#0a0f15"/></linearGradient>
  <radialGradient id="spot" cx=".22" cy=".08" r=".7"><stop offset="0" stop-color="#2dd4bf" stop-opacity=".10"/><stop offset="1" stop-color="#2dd4bf" stop-opacity="0"/></radialGradient>
</defs>''')
A(f'<rect width="{W}" height="{H}" rx="22" fill="url(#bg)"/><rect width="{W}" height="{H}" rx="22" fill="url(#spot)"/>')
A(f'<rect x=".5" y=".5" width="{W-1}" height="{H-1}" rx="22" fill="none" stroke="#24313d"/>')
A('<text x="30" y="46" class="title">How EquityLens works</text>')
A('<text x="30" y="70" class="sub">Public data, exchange and regulator files, news feeds and your broker flow in; get analysed, tested and checked; then land on your laptop, phone and Telegram.</text>')
for x, c, t in ((30, TEAL, "FETCH"), (330, AMBER, "ANALYSE + TEST"), (660, SKY, "STORE + CHECK"), (960, GREEN, "YOUR SCREEN")):
    A(f'<text x="{x}" y="104" class="h"><tspan fill="{c}">●</tspan> {t}</text>')

n_dot = [0]
def wire(d, c, op=.55, dur=1.9):
    b = (n_dot[0] * 0.27) % 2.0
    n_dot[0] += 1
    A(f'<path d="{d}" class="wire" stroke="{c}" stroke-opacity="{op}"/><path d="{d}" class="flow" stroke="{c}" style="animation-duration:{dur}s"/>'
      f'<circle r="4.5" fill="{c}" style="color:{c}" class="dot"><animateMotion dur="{dur}s" begin="{b:.2f}s" repeatCount="indefinite" path="{d}"/></circle>')

def curve(x1, y1, x2, y2):
    m = (x1 + x2) / 2
    return f"M{x1},{y1} C{m},{y1} {m},{y2} {x2},{y2}"

def box(x, y, w, h, c, n, title, lines, fill_op=.10, tag=None, delay=0):
    A(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="14" fill="{c}" fill-opacity="{fill_op}" stroke="{c}" stroke-opacity=".75" stroke-width="1.6"/>')
    A(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="14" class="glow" stroke="{c}" style="animation-delay:{delay}s"/>')
    A(f'<circle cx="{x+22}" cy="{y+24}" r="10" fill="{c}"/><text x="{x+22}" y="{y+28.5}" class="num">{n}</text>')
    A(f'<text x="{x+40}" y="{y+29}" class="t">{e(title)}</text>')
    if tag:
        A(f'<rect x="{x+w-66}" y="{y+h-26}" width="56" height="17" rx="8.5" fill="{c}" fill-opacity=".16" stroke="{c}" stroke-opacity=".6"/>'
          f'<text x="{x+w-38}" y="{y+h-13.5}" class="tag" fill="{c}" text-anchor="middle">{tag}</text>')
    for i, l in enumerate(lines):
        A(f'<text x="{x+18}" y="{y+52+i*18}" class="s">{e(l)}</text>')

ROW0, RH, GAP = 120, 106, 16
rows = [ROW0 + i * (RH + GAP) for i in range(6)]
mid = [r + RH / 2 for r in rows]
FX, FW, AX, AW = 30, 250, 330, 262

fetch = [
    ("Fundamentals", ["10+ years of financials", "screener.in · SEC EDGAR", "shareholding · documents"]),
    ("Prices", ["daily prices and indices", "Yahoo Finance", "52-week, volume, returns"]),
    ("Exchange files", ["NSE bhavcopy · deals · insider", "F&O positions · surveillance", "company filings · SEC 8-K"]),
    ("Flows + regulators", ["NSE FII / DII · NSDL · CDSL", "SEBI mutual funds · CFTC", "RBI · Fed · MoSPI dates"]),
    ("News feeds", ["ET · Mint · The Hindu · BS", "Moneycontrol · BusinessLine", "CNBC · MarketWatch · Bloomberg"]),
    ("Your broker", ["Zerodha · Upstox · Fyers · Angel", "Dhan · Alpaca · CSV upload", "read-only holdings"]),
]
analyse = [
    ("Research engine", ["scores · red flags · forensics", "valuation · 3/5/10-year cases", "entry decision (backtested)"], None),
    ("Technicals + price map", ["chart outlook · major levels", "each level's real hold rate", "vs random price levels"], "TESTED"),
    ("Market tools", ["movers · heatmap by sector", "pre-market NIFTY call", "results + economy dates"], "TESTED"),
    ("Smart money + FII / DII", ["delivery · deals · insiders", "5-year flows · F&O positions", "sector flows · NIFTY test"], "TESTED"),
    ("News engine", ["noise + routine filings out", "stock tags · one story, all sources", "breaking: 2+ sources or 2% move"], None),
    ("Portfolio X-ray", ["score every holding", "risks · sector and index mix", "AI review (optional)"], None),
]
# fetch -> analyse (straight) and cross links
for i in range(6):
    wire(curve(FX + FW, mid[i], AX, mid[i]), TEAL, dur=1.8)
for a, b in ((1, 0), (2, 4), (3, 4)):
    wire(curve(FX + FW, mid[a] + (14 if b > a else -14), AX, mid[b] + (-18 if b > a else 18)), TEAL, op=.3, dur=2.3)

# server
SX, SY, SW, SH = 660, ROW0, 262, 5 * (RH + GAP) - GAP + 4
for i in range(6):
    ty = SY + 40 + i * 70
    wire(curve(AX + AW, mid[i], SX, ty), AMBER, dur=1.9)
for i, (t, l) in enumerate(fetch):
    box(FX, rows[i], FW, RH, TEAL, 1, t, l, delay=i * .25)
for i, (t, l, tag) in enumerate(analyse):
    box(AX, rows[i], AW, RH, AMBER, 2, t, l, tag=tag, delay=1 + i * .25)

A(f'<rect x="{SX}" y="{SY}" width="{SW}" height="{SH}" rx="14" fill="{SKY}" fill-opacity=".08" stroke="{SKY}" stroke-opacity=".75" stroke-width="1.6"/>')
A(f'<rect x="{SX}" y="{SY}" width="{SW}" height="{SH}" rx="14" class="glow" stroke="{SKY}" style="animation-delay:2.6s"/>')
A(f'<circle cx="{SX+22}" cy="{SY+24}" r="10" fill="{SKY}"/><text x="{SX+22}" y="{SY+28.5}" class="num">3</text>')
A(f'<text x="{SX+40}" y="{SY+29}" class="t">Local server</text>')
A(f'<text x="{SX+18}" y="{SY+52}" class="s">one Python process · laptop or cloud</text>')
# cylinder
cx, cy = SX + SW / 2, SY + 92
A(f'<g><path d="M{cx-78},{cy} v58 a78,14 0 0 0 156,0 v-58" fill="#0f2230" stroke="{SKY}" stroke-opacity=".7"/>'
  f'<ellipse cx="{cx}" cy="{cy}" rx="78" ry="14" fill="#13293a" stroke="{SKY}" stroke-opacity=".7"/>'
  f'<text x="{cx}" y="{cy+34}" class="t" text-anchor="middle" style="font-size:14px">SQLite store</text>'
  f'<text x="{cx}" y="{cy+52}" class="s" text-anchor="middle">reports · rankings · history</text></g>')
sec = [("BACKGROUND JOBS", SKY, ["one-time history downloads", "news + breaking every 5 min", "FII / DII each evening", "long backtests, with progress"]),
       ("EVIDENCE CHECKS", VIOLET, ["bought − sold = net, every row", "days add up to the month total", "sectors add up to the total", "no future data in any test", "verdict only when the 90% range", "  is clearly above / below usual"])]
y = cy + 92
for head, c, lines in sec:
    A(f'<text x="{SX+18}" y="{y}" class="tag" fill="{c}">● {head}</text>')
    for j, l in enumerate(lines):
        A(f'<text x="{SX+18}" y="{y+20+j*18}" class="k">{e(l)}</text>')
    y += 34 + len(lines) * 18
A(f'<text x="{SX+18}" y="{SY+SH-16}" class="s"><tspan fill="{SKY}">●</tspan> password · accounts · logs</text>')

# AI analyst below server
AIY = rows[5]
A(f'<path d="M{SX+SW/2-40},{SY+SH} V{AIY}" class="wire" stroke="{PINK}" stroke-opacity=".55"/>')
A(f'<path d="M{SX+SW/2+40},{AIY} V{SY+SH}" class="wire" stroke="{PINK}" stroke-opacity=".55"/>')
wire(f"M{SX+SW/2-40},{SY+SH} V{AIY}", PINK, dur=1.4)
wire(f"M{SX+SW/2+40},{AIY} V{SY+SH}", PINK, dur=1.4)
box(SX, AIY, SW, RH, PINK, 3, "AI analyst", ["Claude · ChatGPT · Gemini · Ollama", "research notes · chat · debate", "its numbers are checked"], fill_op=.10, delay=3.2)

# screen side
APX, APY, APW, APH = 960, ROW0 + 40, 250, 470
wire(curve(SX + SW, SY + 150, APX, APY + 60), GREEN, dur=1.7)
wire(curve(SX + SW, SY + 260, APX, APY + 160), GREEN, dur=1.7)
A(f'<rect x="{APX}" y="{APY}" width="{APW}" height="{APH}" rx="14" fill="{GREEN}" fill-opacity=".08" stroke="{GREEN}" stroke-opacity=".75" stroke-width="1.6"/>')
A(f'<rect x="{APX}" y="{APY}" width="{APW}" height="{APH}" rx="14" class="glow" stroke="{GREEN}" style="animation-delay:3.6s"/>')
A(f'<circle cx="{APX+22}" cy="{APY+24}" r="10" fill="{GREEN}"/><text x="{APX+22}" y="{APY+28.5}" class="num">4</text>')
A(f'<text x="{APX+40}" y="{APY+29}" class="t">EquityLens app</text>')
for j, l in enumerate(["verdicts · charts · price map", "movers · heatmap · calendar", "smart money · FII / DII", "news · breaking bar · portfolio"]):
    A(f'<text x="{APX+18}" y="{APY+52+j*18}" class="s">{e(l)}</text>')
# laptop + phone drawing
lx, ly = APX + 22, APY + 140
A(f'<rect x="{lx}" y="{ly}" width="150" height="96" rx="6" fill="#0d1620" stroke="#3b4a57"/>'
  f'<rect x="{lx+10}" y="{ly+10}" width="60" height="9" rx="3" fill="{GREEN}" opacity=".85" class="scan"/>'
  f'<rect x="{lx+10}" y="{ly+26}" width="130" height="7" rx="3" fill="#2a3a47"/>'
  f'<rect x="{lx+10}" y="{ly+39}" width="100" height="7" rx="3" fill="#2a3a47"/>'
  f'<rect x="{lx+10}" y="{ly+52}" width="40" height="30" rx="3" fill="{GREEN}" opacity=".35"/>'
  f'<rect x="{lx+55}" y="{ly+52}" width="40" height="30" rx="3" fill="#ef4444" opacity=".35"/>'
  f'<rect x="{lx+100}" y="{ly+52}" width="40" height="30" rx="3" fill="{GREEN}" opacity=".55"/>'
  f'<rect x="{lx-8}" y="{ly+96}" width="166" height="8" rx="4" fill="#3b4a57"/>')
px_, py_ = APX + 192, ly + 6
A(f'<rect x="{px_}" y="{py_}" width="40" height="80" rx="8" fill="#0d1620" stroke="#3b4a57"/>'
  f'<rect x="{px_+7}" y="{py_+10}" width="26" height="8" rx="3" fill="#ef4444" class="blink"/>'
  f'<circle cx="{px_+20}" cy="{py_+42}" r="10" fill="none" stroke="{GREEN}" stroke-width="3" stroke-dasharray="40 30" class="blink"/>')
for j, l in enumerate(["laptop: double-click EquityLens", "phone: scan the QR in Settings", "cloud: 24×7, with a password", "brokers are read-only: no orders", "first run downloads history by itself"]):
    A(f'<text x="{APX+18}" y="{APY+290+j*22}" class="s"><tspan fill="{GREEN}">●</tspan> {e(l)}</text>')

# Telegram
TGY = rows[5] - 14
TGH = RH + 14
wire(curve(SX + SW, SY + SH - 60, APX, TGY + 44), SKY, dur=1.6)
A(f'<rect x="{APX}" y="{TGY}" width="{APW}" height="{TGH}" rx="14" fill="{SKY}" fill-opacity=".10" stroke="{SKY}" stroke-opacity=".75" stroke-width="1.6"/>')
A(f'<circle cx="{APX+22}" cy="{TGY+24}" r="10" fill="{SKY}"/><text x="{APX+22}" y="{TGY+28.5}" class="num">5</text>')
A(f'<text x="{APX+40}" y="{TGY+29}" class="t">Telegram alerts</text>')
A(f'<circle cx="{APX+APW-24}" cy="{TGY+24}" r="6" fill="#ef4444"/><circle cx="{APX+APW-24}" cy="{TGY+24}" r="6" fill="none" stroke="#ef4444" class="ring"/>')
for j, l in enumerate(["breaking market news", "your watchlist stocks' filings", "RBI and Fed releases · each once"]):
    A(f'<text x="{APX+18}" y="{TGY+52+j*18}" class="s">{e(l)}</text>')

A(f'<text x="30" y="{H-24}" class="foot">Your keys, holdings and Telegram token stay on your computer (or your own server). Only the sources above, Telegram (if alerts are on) and your AI provider (if used) are contacted.</text>')
A('</svg>')
open(sys.argv[1] if len(sys.argv) > 1 else str(__import__("pathlib").Path(__file__).resolve().parents[2] / "docs" / "pipeline.svg"), "w", encoding="utf-8").write("\n".join(out))
print("ok", len("\n".join(out)))
