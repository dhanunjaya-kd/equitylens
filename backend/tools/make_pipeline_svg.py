"""Draw docs/pipeline.svg: the animated "How it works" diagram in the README.

    python tools/make_pipeline_svg.py

Plain SVG + CSS/SMIL animation, so GitHub plays it inside the README (no JavaScript).
"""
from pathlib import Path

OUT = Path(__file__).resolve().parents[2] / "docs" / "pipeline.svg"
W, H = 1240, 690
FONT = "'Segoe UI', -apple-system, BlinkMacSystemFont, Roboto, Helvetica, Arial, sans-serif"
C = {"src": "#2dd4bf", "eng": "#f59e0b", "srv": "#38bdf8", "ai": "#f472b6", "app": "#22c55e"}

# column x, width
X1, W1 = 30, 230
X2, W2 = 330, 250
X3, W3 = 660, 220
X4, W4 = 960, 250
ROWS = [118, 252, 386, 520]          # node tops
NH = 100                             # node height


def esc(t: str) -> str:
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def node(x, y, w, h, color, title, lines, step, delay):
    out = [f'<g class="node">',
           f'<rect class="glow" x="{x - 3}" y="{y - 3}" width="{w + 6}" height="{h + 6}" rx="17" stroke="{color}" style="animation-delay:{delay}s"/>',
           f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="14" fill="#0e161d"/>',
           f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="14" fill="{color}" fill-opacity=".10" stroke="{color}" stroke-opacity=".75" stroke-width="1.5"/>',
           f'<circle cx="{x + 24}" cy="{y + 25}" r="11" fill="{color}"/>',
           f'<text x="{x + 24}" y="{y + 29.5}" class="num">{step}</text>',
           f'<text x="{x + 44}" y="{y + 30}" class="t">{esc(title)}</text>']
    for i, ln in enumerate(lines):
        out.append(f'<text x="{x + 18}" y="{y + 56 + i * 19}" class="s">{esc(ln)}</text>')
    out.append("</g>")
    return "\n".join(out)


def edge(d, color, dur, begin, faint=False):
    op = ".35" if faint else ".55"
    return (f'<path d="{d}" class="wire" stroke="{color}" stroke-opacity="{op}"/>'
            f'<path d="{d}" class="flow" stroke="{color}" style="animation-duration:{dur}s"/>'
            f'<circle r="4.5" fill="{color}" style="color:{color}" class="dot"><animateMotion dur="{dur}s" begin="{begin}s" repeatCount="indefinite" path="{d}"/></circle>')


def main():
    p = []
    p.append(f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-label="How EquityLens works: free public data and your broker are fetched, analysed, cached and explained, then shown on laptop or phone">
<style>
  text {{ font-family: {FONT}; }}
  .h {{ font-size: 13px; font-weight: 800; letter-spacing: .09em; fill: #8b9bab; }}
  .title {{ font-size: 24px; font-weight: 800; fill: #e6edf3; }}
  .sub {{ font-size: 14px; fill: #8b9bab; }}
  .t {{ font-size: 16.5px; font-weight: 700; fill: #e6edf3; }}
  .s {{ font-size: 13px; fill: #a9b6c3; }}
  .num {{ font-size: 12.5px; font-weight: 800; fill: #0b1016; text-anchor: middle; }}
  .foot {{ font-size: 13px; fill: #7d8b99; }}
  .wire {{ fill: none; stroke-width: 2; }}
  .flow {{ fill: none; stroke-width: 2.4; stroke-dasharray: 3 14; stroke-linecap: round; animation: flow 1.6s linear infinite; opacity: .9; }}
  .glow {{ fill: none; stroke-width: 3; opacity: 0; animation: pulse 4.8s ease-in-out infinite; }}
  .dot {{ filter: drop-shadow(0 0 4px currentColor); }}
  .scan {{ animation: scan 2.4s ease-in-out infinite; }}
  .blink {{ animation: blink 2.4s ease-in-out infinite; }}
  @keyframes flow {{ to {{ stroke-dashoffset: -34; }} }}
  @keyframes pulse {{ 0%, 70%, 100% {{ opacity: 0; }} 15%, 30% {{ opacity: .9; }} }}
  @keyframes scan {{ 0%, 100% {{ transform: scaleX(.35); }} 50% {{ transform: scaleX(1); }} }}
  @keyframes blink {{ 0%, 100% {{ opacity: .35; }} 50% {{ opacity: 1; }} }}
  @media (prefers-reduced-motion: reduce) {{ .flow, .glow, .scan, .blink {{ animation: none; }} .dot {{ display: none; }} }}
</style>
<defs>
  <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#0f1a22"/><stop offset="1" stop-color="#0a0f15"/></linearGradient>
  <radialGradient id="spot" cx=".22" cy=".1" r=".7"><stop offset="0" stop-color="#2dd4bf" stop-opacity=".10"/><stop offset="1" stop-color="#2dd4bf" stop-opacity="0"/></radialGradient>
</defs>
<rect width="{W}" height="{H}" rx="22" fill="url(#bg)"/>
<rect width="{W}" height="{H}" rx="22" fill="url(#spot)"/>
<rect x=".5" y=".5" width="{W - 1}" height="{H - 1}" rx="22" fill="none" stroke="#24313d"/>
<text x="30" y="46" class="title">How EquityLens works</text>
<text x="30" y="70" class="sub">Free public data and your broker flow in, get analysed, cached and explained, then land on your laptop or phone.</text>
''')
    # column headers
    for x, w, label, col in ((X1, W1, "FETCH", C["src"]), (X2, W2, "ANALYSE", C["eng"]),
                             (X3, W3, "STORE + EXPLAIN", C["srv"]), (X4, W4, "YOUR SCREEN", C["app"])):
        p.append(f'<text x="{x}" y="104" class="h"><tspan fill="{col}">●</tspan> {label}</text>')

    mid = [r + NH / 2 for r in ROWS]
    # ---- edges (drawn first, under the nodes)
    e = []
    # sources -> engines, row by row
    for i, r in enumerate(mid):
        e.append(edge(f"M{X1 + W1},{r} C{X1 + W1 + 35},{r} {X2 - 35},{r} {X2},{r}", C["src"], 1.8, i * 0.35))
    # prices also feed the research engine (valuation)
    e.append(edge(f"M{X1 + W1},{mid[1] - 18} C{X1 + W1 + 40},{mid[1] - 18} {X2 - 45},{mid[0] + 22} {X2},{mid[0] + 22}", C["src"], 2.2, 0.9, True))
    # engines -> server (cache)
    srv_top, srv_h = ROWS[0], ROWS[2] + NH - ROWS[0]
    targets = [srv_top + 50, srv_top + 140, srv_top + 230, srv_top + srv_h - 40]
    for i, r in enumerate(mid):
        t = targets[i]
        e.append(edge(f"M{X2 + W2},{r} C{X2 + W2 + 40},{r} {X3 - 40},{t} {X3},{t}", C["eng"], 1.9, 0.5 + i * 0.3))
    # server <-> AI
    ai_top = ROWS[3]
    e.append(edge(f"M{X3 + 80},{srv_top + srv_h} L{X3 + 80},{ai_top}", C["ai"], 1.2, 0.2))
    e.append(edge(f"M{X3 + W3 - 80},{ai_top} L{X3 + W3 - 80},{srv_top + srv_h}", C["ai"], 1.2, 0.8))
    # server -> app
    app_top, app_h = ROWS[0] + 40, 360
    e.append(edge(f"M{X3 + W3},{srv_top + srv_h / 2 - 20} C{X3 + W3 + 40},{srv_top + srv_h / 2 - 20} {X4 - 40},{app_top + 120} {X4},{app_top + 120}", C["app"], 1.5, 0))
    e.append(edge(f"M{X3 + W3},{srv_top + srv_h / 2 + 30} C{X3 + W3 + 40},{srv_top + srv_h / 2 + 30} {X4 - 40},{app_top + 200} {X4},{app_top + 200}", C["app"], 1.5, 0.75))
    p.extend(e)

    # ---- nodes, glowing left to right
    src = [("Fundamentals", ["10+ years of financials", "screener.in · SEC EDGAR"]),
           ("Prices", ["daily prices and indices", "Yahoo Finance"]),
           ("Market data", ["NSE files · Nasdaq · Form 4", "RBI · MoSPI · Fed dates"]),
           ("Your broker", ["Zerodha · Upstox · Fyers · Angel", "Dhan · Alpaca · CSV upload"])]
    eng = [("Research engine", ["scores · red flags · forensics", "valuation · 3/5/10-year cases"]),
           ("Technicals + movers", ["indicators · chart outlook", "market mood · sector heatmap"]),
           ("Smart money + calendar", ["delivery · deals · insiders", "results · economic events"]),
           ("Portfolio X-ray", ["score every holding", "risks · sector and index mix"])]
    for i, (t, ls) in enumerate(src):
        p.append(node(X1, ROWS[i], W1, NH, C["src"], t, ls, "1", i * 0.15))
    for i, (t, ls) in enumerate(eng):
        p.append(node(X2, ROWS[i], W2, NH, C["eng"], t, ls, "2", 1.2 + i * 0.15))

    # server (tall) with a cache cylinder inside
    p.append(node(X3, srv_top, W3, srv_h, C["srv"], "Local server", ["one Python process", "laptop or cloud"], "3", 2.4))
    cx, cy = X3 + W3 / 2, srv_top + 205
    p.append(f'''<g>
  <ellipse cx="{cx}" cy="{cy}" rx="62" ry="13" fill="#1b2a36" stroke="{C["srv"]}" stroke-opacity=".7"/>
  <path d="M{cx - 62},{cy} v62 a62,13 0 0 0 124,0 v-62" fill="#15222c" stroke="{C["srv"]}" stroke-opacity=".7"/>
  <ellipse cx="{cx}" cy="{cy}" rx="62" ry="13" fill="#1f3140" stroke="{C["srv"]}" stroke-opacity=".7"/>
  <text x="{cx}" y="{cy + 34}" class="s" text-anchor="middle" fill="#e6edf3" style="fill:#e6edf3;font-weight:700">SQLite cache</text>
  <text x="{cx}" y="{cy + 53}" class="s" text-anchor="middle">reports · rankings</text>
</g>
<text x="{X3 + 18}" y="{srv_top + srv_h - 18}" class="s"><tspan fill="{C["srv"]}">●</tspan> password · logs</text>''')
    p.append(node(X3, ai_top, W3, NH, C["ai"], "AI analyst", ["Claude · ChatGPT", "Gemini · Ollama (free)"], "3", 2.7))

    # app with laptop + phone
    p.append(node(X4, app_top, W4, app_h, C["app"], "EquityLens app", ["verdicts · charts · movers", "calendar · smart money · portfolio"], "4", 3.6))
    lx, ly = X4 + 26, app_top + 132
    p.append(f'''<g>
  <rect x="{lx}" y="{ly}" width="140" height="88" rx="7" fill="#0b1016" stroke="#3a4a58" stroke-width="2"/>
  <rect x="{lx + 8}" y="{ly + 8}" width="28" height="72" rx="3" fill="#13202a"/>
  <rect x="{lx + 44}" y="{ly + 10}" width="86" height="16" rx="4" fill="{C["app"]}" fill-opacity=".25"/>
  <rect x="{lx + 44}" y="{ly + 32}" width="86" height="8" rx="3" fill="#2a3946"/>
  <g class="scan" style="transform-origin:{lx + 44}px 0">
    <rect x="{lx + 44}" y="{ly + 46}" width="86" height="8" rx="3" fill="{C["src"]}" fill-opacity=".7"/></g>
  <rect x="{lx + 44}" y="{ly + 60}" width="60" height="8" rx="3" fill="#2a3946"/>
  <path d="M{lx - 12},{ly + 94} h164 l-10,9 h-144 z" fill="#2a3946"/>
  <rect x="{lx + 176}" y="{ly - 6}" width="44" height="88" rx="9" fill="#0b1016" stroke="#3a4a58" stroke-width="2"/>
  <rect x="{lx + 182}" y="{ly + 6}" width="32" height="12" rx="3" fill="{C["app"]}" fill-opacity=".25"/>
  <circle cx="{lx + 198}" cy="{ly + 38}" r="11" fill="none" stroke="{C["app"]}" stroke-width="3" stroke-dasharray="52 70" class="blink"/>
  <rect x="{lx + 182}" y="{ly + 56}" width="32" height="6" rx="3" fill="#2a3946"/>
  <rect x="{lx + 182}" y="{ly + 66}" width="22" height="6" rx="3" fill="#2a3946"/>
</g>
<text x="{X4 + 18}" y="{app_top + 268}" class="s"><tspan fill="{C["app"]}">●</tspan> laptop: double-click EquityLens</text>
<text x="{X4 + 18}" y="{app_top + 290}" class="s"><tspan fill="{C["app"]}">●</tspan> phone: scan the QR in Settings</text>
<text x="{X4 + 18}" y="{app_top + 312}" class="s"><tspan fill="{C["app"]}">●</tspan> cloud: on 24×7, with a password</text>
<text x="{X4 + 18}" y="{app_top + 334}" class="s"><tspan fill="{C["app"]}">●</tspan> brokers are read-only: no orders</text>''')

    p.append(f'<text x="30" y="{H - 22}" class="foot">Your keys and holdings stay on your own computer (or your own server). Only the data sources above, and your AI provider if you use one, are contacted.</text>')
    p.append("</svg>")
    OUT.write_text("\n".join(p), encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
