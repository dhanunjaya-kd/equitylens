import { useEffect, useMemo, useRef, useState } from 'react'
import { CandlestickSeries, ColorType, CrosshairMode, HistogramSeries, LineSeries, LineStyle, createChart, createTextWatermark } from 'lightweight-charts'
import { api, getMarket, num, ok, signed } from '../util'
import { chime } from '../components/BreakingBar'

// Live terminal: a screen, no orders. NSE stocks, index options, stock F&O, US stocks.
// Every panel shows the time its source stamped. A figure that fails a check is left out with the reason.
// IND view: Indian symbols only; US view: US symbols only (each market keeps its own watchlist)
const DEFAULT_WATCH = {
  IN: ['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'RELIANCE', 'HDFCBANK', 'ICICIBANK', 'TCS', 'INFY', 'SBIN', 'BHARTIARTL'],
  US: ['US:SPX', 'US:NASDAQ', 'US:DOW', 'US:AAPL', 'US:NVDA', 'US:MSFT', 'US:AMZN', 'US:GOOGL', 'US:META', 'US:TSLA'],
}
const INDEX = ['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY', 'US:SPX', 'US:NASDAQ', 'US:DOW', 'US:RUSSELL', 'US:VIX']
const US_NAMES = { 'US:SPX': 'S&P 500', 'US:NASDAQ': 'Nasdaq Composite', 'US:DOW': 'Dow Jones', 'US:RUSSELL': 'Russell 2000', 'US:VIX': 'CBOE VIX' }
const loadJ = (k, d) => { try { const v = JSON.parse(localStorage.getItem(k)); return v ?? d } catch { return d } }
const saveJ = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)) } catch { /* ignore */ } }
const isUSs = (s) => s.startsWith('US:')
const isIdx = (s) => INDEX.includes(s)
const ist = () => new Date(new Date().toLocaleString('en-US', { timeZone: 'Asia/Kolkata' }))
const usOpen = () => { const d = new Date(new Date().toLocaleString('en-US', { timeZone: 'America/New_York' })); const m = d.getHours() * 60 + d.getMinutes(); return d.getDay() > 0 && d.getDay() < 6 && m >= 570 && m < 960 }
const nseOpen = () => { const d = ist(); const m = d.getHours() * 60 + d.getMinutes(); return d.getDay() > 0 && d.getDay() < 6 && m >= 555 && m <= 930 }
const tone = (v) => (!ok(v) ? 'var(--muted)' : v > 0 ? 'var(--good)' : v < 0 ? 'var(--bad)' : 'var(--muted)')
const px = (v, cur = '₹') => (ok(v) ? `${cur}${num(v, 2)}` : '—')
const big = (v) => (ok(v) ? (Math.abs(v) >= 1e7 ? `${num(v / 1e7, 2)} Cr` : Math.abs(v) >= 1e5 ? `${num(v / 1e5, 2)} L` : num(v)) : '—')

function usePoll(fn, ms, deps) {
  useEffect(() => {
    let alive = true
    const run = () => { if (alive && !document.hidden) fn() }
    run()
    const t = setInterval(run, ms)
    return () => { alive = false; clearInterval(t) }
  }, deps) // eslint-disable-line react-hooks/exhaustive-deps
}

// ---------------------------------------------------------------- indicators (worked out here from the candles)
const sma = (v, n) => v.map((_, i) => (i >= n - 1 ? v.slice(i - n + 1, i + 1).reduce((a, b) => a + b, 0) / n : null))
const ema = (v, n) => { const k = 2 / (n + 1); let e = null; return v.map((x, i) => { e = e === null ? x : x * k + e * (1 - k); return i >= n - 1 ? e : null }) }
function boll(v, n = 20, m = 2) {
  const mid = sma(v, n)
  return v.map((_, i) => { if (mid[i] === null) return [null, null, null]; const w = v.slice(i - n + 1, i + 1); const sd = Math.sqrt(w.reduce((a, b) => a + (b - mid[i]) ** 2, 0) / n); return [mid[i] + m * sd, mid[i], mid[i] - m * sd] })
}
function atr(b, n) { const tr = b.map((x, i) => (i ? Math.max(x.h - x.l, Math.abs(x.h - b[i - 1].c), Math.abs(x.l - b[i - 1].c)) : x.h - x.l)); let a = null; return tr.map((t, i) => { a = i < n ? (i === n - 1 ? tr.slice(0, n).reduce((p, q) => p + q, 0) / n : null) : (a * (n - 1) + t) / n; return a }) }
function supertrend(b, n = 10, m = 3) {
  const a = atr(b, n), out = []
  let up = null, dn = null, trend = 1
  b.forEach((x, i) => {
    if (a[i] === null) { out.push([null, 0]); return }
    const mid = (x.h + x.l) / 2, bu = mid - m * a[i], bd = mid + m * a[i]
    up = up === null || b[i - 1].c < up ? bu : Math.max(bu, up)
    dn = dn === null || b[i - 1].c > dn ? bd : Math.min(bd, dn)
    if (trend === 1 && x.c < up) trend = -1; else if (trend === -1 && x.c > dn) trend = 1
    out.push([trend === 1 ? up : dn, trend])
  })
  return out
}
function rsi(v, n = 14) { let g = 0, l = 0; return v.map((x, i) => { if (!i) return null; const d = x - v[i - 1]; if (i <= n) { g += Math.max(d, 0); l += Math.max(-d, 0); if (i < n) return null; g /= n; l /= n } else { g = (g * (n - 1) + Math.max(d, 0)) / n; l = (l * (n - 1) + Math.max(-d, 0)) / n } return l === 0 ? 100 : 100 - 100 / (1 + g / l) }) }
function macd(v) { const f = ema(v, 12), s = ema(v, 26); const m = v.map((_, i) => (f[i] !== null && s[i] !== null ? f[i] - s[i] : null)); const start = m.findIndex((x) => x !== null); const sig = start < 0 ? m.map(() => null) : [...m.slice(0, start).map(() => null), ...ema(m.slice(start), 9)]; return m.map((x, i) => [x, sig[i], x !== null && sig[i] !== null ? x - sig[i] : null]) }

const IND = [
  ['vol', 'Volume'], ['vwap', 'VWAP (intraday)'], ['ema9', 'EMA 9'], ['ema20', 'EMA 20'], ['ema50', 'EMA 50'], ['ema200', 'EMA 200'],
  ['sma20', 'SMA 20'], ['sma50', 'SMA 50'], ['bb', 'Bollinger Bands (20, 2)'], ['st', 'Supertrend (10, 3)'], ['rsi', 'RSI (14) · own pane'], ['macd', 'MACD (12, 26, 9) · own pane'],
]
const IND_COLOR = { vwap: '#ff9800', ema9: '#00bcd4', ema20: '#2962ff', ema50: '#e040fb', ema200: '#ffeb3b', sma20: '#26a69a', sma50: '#ef5350', bb: '#787b86' }

// ---------------------------------------------------------------- drawing tools (kept per symbol in this browser)
const TOOLS = [
  ['cursor', 'Crosshair', <path key="a" d="M12 3v18M3 12h18" />],
  ['trend', 'Trend line (2 clicks)', <><path key="a" d="M4 19L20 5" /><circle key="b" cx="4" cy="19" r="1.6" /><circle key="c" cx="20" cy="5" r="1.6" /></>],
  ['ray', 'Ray (2 clicks)', <><path key="a" d="M4 18L21 6" /><circle key="b" cx="4" cy="18" r="1.6" /></>],
  ['hline', 'Horizontal line (1 click)', <path key="a" d="M3 12h18" />],
  ['vline', 'Vertical line (1 click)', <path key="a" d="M12 3v18" />],
  ['rect', 'Rectangle (2 clicks)', <rect key="a" x="4" y="6" width="16" height="12" rx="1" />],
  ['fib', 'Fib retracement (2 clicks)', <><path key="a" d="M3 5h18M3 9.5h18M3 14h18M3 19h18" /></>],
  ['measure', 'Measure (2 clicks)', <><path key="a" d="M4 20L20 4M7 20l-3-3M20 7l-3-3" /></>],
]
const FIB = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1]
const DRAW_C = '#2962ff'

function drawShapes(ctx, w, h, chart, series, shapes, temp, dark) {
  ctx.clearRect(0, 0, w, h)
  const X = (t) => chart.timeScale().timeToCoordinate(t)
  const Y = (p) => series.priceToCoordinate(p)
  const txt = dark ? '#d1d4dc' : '#131722'
  const all = temp ? [...shapes, temp] : shapes
  ctx.lineWidth = 1.5
  ctx.font = '11px -apple-system, Segoe UI, sans-serif'
  for (const s of all) {
    const [a, b] = s.p
    const xa = a && X(a.t), ya = a && Y(a.v), xb = b && X(b.t), yb = b && Y(b.v)
    ctx.strokeStyle = DRAW_C; ctx.fillStyle = DRAW_C; ctx.setLineDash(s === temp ? [4, 3] : [])
    if (s.k === 'hline' && ya !== null) {
      ctx.beginPath(); ctx.moveTo(0, ya); ctx.lineTo(w, ya); ctx.stroke()
      ctx.fillText(num(a.v, 2), 6, ya - 4)
    } else if (s.k === 'vline' && xa !== null) {
      ctx.beginPath(); ctx.moveTo(xa, 0); ctx.lineTo(xa, h); ctx.stroke()
    } else if (b && xa !== null && xb !== null && ya !== null && yb !== null) {
      if (s.k === 'trend') { ctx.beginPath(); ctx.moveTo(xa, ya); ctx.lineTo(xb, yb); ctx.stroke() }
      if (s.k === 'ray') {
        const dx = xb - xa, dy = yb - ya, k = dx === 0 ? 0 : (w - xa) / dx
        ctx.beginPath(); ctx.moveTo(xa, ya); ctx.lineTo(dx === 0 ? xb : w, dx === 0 ? (dy > 0 ? h : 0) : ya + dy * k); ctx.stroke()
      }
      if (s.k === 'rect') { ctx.globalAlpha = 0.12; ctx.fillRect(Math.min(xa, xb), Math.min(ya, yb), Math.abs(xb - xa), Math.abs(yb - ya)); ctx.globalAlpha = 1; ctx.strokeRect(Math.min(xa, xb), Math.min(ya, yb), Math.abs(xb - xa), Math.abs(yb - ya)) }
      if (s.k === 'fib') {
        FIB.forEach((f) => {
          const p = b.v + (a.v - b.v) * f, y = Y(p)
          if (y === null) return
          ctx.globalAlpha = f === 0.5 || f === 0.618 ? 1 : 0.7
          ctx.beginPath(); ctx.moveTo(Math.min(xa, xb), y); ctx.lineTo(w, y); ctx.stroke()
          ctx.fillStyle = txt; ctx.fillText(`${f} (${num(p, 2)})`, Math.min(xa, xb) + 4, y - 3); ctx.fillStyle = DRAW_C
        })
        ctx.globalAlpha = 1
      }
      if (s.k === 'measure') {
        const up = b.v >= a.v
        ctx.globalAlpha = 0.16; ctx.fillStyle = up ? '#089981' : '#f23645'; ctx.fillRect(Math.min(xa, xb), Math.min(ya, yb), Math.abs(xb - xa), Math.abs(yb - ya)); ctx.globalAlpha = 1
        const lab = `${signed(b.v - a.v, 2)} (${signed(((b.v - a.v) / a.v) * 100, 2, '%')})${s.bars ? ` · ${s.bars} bars` : ''}`
        ctx.fillStyle = up ? '#089981' : '#f23645'
        const tw = ctx.measureText(lab).width + 10
        ctx.fillRect((xa + xb) / 2 - tw / 2, Math.min(ya, yb) - 20, tw, 17)
        ctx.fillStyle = '#fff'; ctx.fillText(lab, (xa + xb) / 2 - tw / 2 + 5, Math.min(ya, yb) - 8)
      }
    } else if (a && xa !== null && ya !== null && s === temp) {
      ctx.beginPath(); ctx.arc(xa, ya, 3, 0, 7); ctx.fill()
    }
  }
  ctx.setLineDash([])
}

// ---------------------------------------------------------------- chart (TradingView-style)
const UP = '#089981', DOWN = '#f23645'
const FRAME_LABEL = { '1m': '1m', '3m': '3m', '5m': '5m', '15m': '15m', '30m': '30m', '1h': '1h', '4h': '4h', '1D': 'D', '1W': 'W' }
const PERIOD = { '1m': 60, '3m': 180, '5m': 300, '15m': 900, '30m': 1800, '1h': 3600, '4h': 14400 }
const mmss = (s) => (s >= 3600 ? `${Math.floor(s / 3600)}:${String(Math.floor((s % 3600) / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}` : `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`)

function drawSessionPivots(view, data, seriesType) {
  const pivots = data.pivots
  const key = JSON.stringify([pivots, data.bars.at(-1)?.t])
  if (key === view.pivotKey) return
  view.pivotKey = key
  for (const series of view.pivotSeries || []) view.chart.removeSeries(series)
  view.pivotSeries = []
  if (!pivots) return
  const points = data.bars.map(bar => bar.t + data.offset)
    .filter(t => new Date(t * 1000).toISOString().slice(0, 10) === pivots.session)
  for (const [title, value] of Object.entries(pivots.levels)) {
    const series = view.chart.addSeries(seriesType, {
      title, color: title === 'PP' ? '#8775ca' : title.startsWith('R') ? '#d45454' : '#159681',
      lineWidth: 1, lineStyle: 2, priceLineVisible: false, lastValueVisible: true,
      pointMarkersVisible: points.length === 1, crosshairMarkerVisible: false,
    })
    series.setData(points.map(time => ({ time, value })))
    view.pivotSeries.push(series)
  }
}

function pivotCaption(data) {
  if (!('pivots' in data)) return ''
  const p = data.pivots
  return p ? ' · Classic pivots for ' + p.session + ' · prior session ' + p.basis +
    ' (H ' + p.high.toFixed(2) + ', L ' + p.low.toFixed(2) + ', C ' + p.close.toFixed(2) + ')'
    : ' · Daily pivot data unavailable'
}

export function Chart({ sym, frame, setFrame, name, live, ltp, onAlert, expanded, setExpanded }) {
  const box = useRef(), cv = useRef(), wrap = useRef()
  const ref = useRef(null)
  const [d, setD] = useState(null)
  const [err, setErr] = useState('')
  const [ind, setInd] = useState(() => ({ vol: true, vwap: true, ...loadJ('eql_term_ind', {}) }))
  const [line, setLine] = useState(() => loadJ('eql_term_line', false))
  const [menu, setMenu] = useState(false)
  const [leg, setLeg] = useState(null)
  const [tool, setTool] = useState('cursor')
  const [shapes, setShapesRaw] = useState(() => loadJ(`eql_draw_${sym}`, []))
  const [hideDraw, setHideDraw] = useState(false)
  const [temp, setTemp] = useState(null)
  const [lab, setLab] = useState(null)
  const dark = document.documentElement.dataset.theme !== 'light'
  const setShapes = (s) => { setShapesRaw(s); saveJ(`eql_draw_${sym}`, s) }
  useEffect(() => { setShapesRaw(loadJ(`eql_draw_${sym}`, [])); setTemp(null) }, [sym])
  const flip = (k) => { const o = { ...ind, [k]: !ind[k] }; setInd(o); saveJ('eql_term_ind', o) }
  useEffect(() => {
    let active = true
    const update = async () => {
      try {
        const next = await api(`/api/term/candles/${encodeURIComponent(sym)}?frame=${frame}`)
        if (active) { setD(next); setErr('') }
      } catch (error) { if (active) setErr(error.message) }
    }
    setD(null); setErr(''); setLeg(null); update()
    const timer = setInterval(() => { if (!document.hidden) update() }, ['1D','1W'].includes(frame) ? 300000 : 30000)
    return () => { active = false; clearInterval(timer) }
  }, [sym, frame])

  // build the chart
  useEffect(() => {
    if (!box.current) return undefined
    const bg = dark ? '#0f1216' : '#ffffff', txt = dark ? '#b2b5be' : '#131722', border = dark ? '#2a2e39' : '#e0e3eb'
    const chart = createChart(box.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: bg }, textColor: txt, fontSize: 12, attributionLogo: false,
        fontFamily: '-apple-system, BlinkMacSystemFont, "Trebuchet MS", Roboto, Ubuntu, sans-serif', panes: { separatorColor: border } },
      grid: { vertLines: { visible: false }, horzLines: { visible: false } },
      crosshair: { mode: CrosshairMode.Normal, vertLine: { color: dark ? '#758696' : '#9598a1', labelBackgroundColor: dark ? '#2a2e39' : '#131722' },
        horzLine: { color: dark ? '#758696' : '#9598a1', labelBackgroundColor: dark ? '#2a2e39' : '#131722' } },
      rightPriceScale: { borderColor: border, scaleMargins: { top: 0.08, bottom: 0.18 }, minimumWidth: 78 },
      timeScale: { borderColor: border, timeVisible: true, secondsVisible: false, rightOffset: 8, barSpacing: 7 },
    })
    createTextWatermark(chart.panes()[0], { horzAlign: 'center', vertAlign: 'center',
      lines: [{ text: sym.replace('US:', ''), color: dark ? 'rgba(178,181,190,0.07)' : 'rgba(19,23,34,0.06)', fontSize: 64, fontStyle: 'bold' }] })
    const main = line
      ? chart.addSeries(LineSeries, { color: '#2962ff', lineWidth: 2, lastValueVisible: false, priceLineStyle: LineStyle.Dotted })
      : chart.addSeries(CandlestickSeries, { upColor: UP, downColor: DOWN, borderUpColor: UP, borderDownColor: DOWN, wickUpColor: UP, wickDownColor: DOWN, lastValueVisible: false, priceLineStyle: LineStyle.Dotted })
    const L = (color, title, pane = 0, extra = {}) => chart.addSeries(LineSeries, { color, lineWidth: 1.5, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false, title, ...extra }, pane)
    const s = {}
    if (ind.vol) { s.vol = chart.addSeries(HistogramSeries, { priceScaleId: 'vol', priceFormat: { type: 'volume' }, lastValueVisible: false, priceLineVisible: false }); s.vol.priceScale().applyOptions({ scaleMargins: { top: 0.86, bottom: 0 } }) }
    ;['vwap', 'ema9', 'ema20', 'ema50', 'ema200', 'sma20', 'sma50'].forEach((k) => { if (ind[k]) s[k] = L(IND_COLOR[k], IND.find((x) => x[0] === k)[1].split(' (')[0]) })
    if (ind.bb) { s.bbu = L(IND_COLOR.bb, '', 0, { lineStyle: LineStyle.Dashed }); s.bbm = L(IND_COLOR.bb, 'BB'); s.bbl = L(IND_COLOR.bb, '', 0, { lineStyle: LineStyle.Dashed }) }
    if (ind.st) { s.stu = L(UP, 'ST', 0, { lineWidth: 2 }); s.std = L(DOWN, '', 0, { lineWidth: 2 }) }
    let pane = 1
    if (ind.rsi) {
      s.rsi = L('#7e57c2', 'RSI 14', pane, { lastValueVisible: true })
      ;[70, 30].forEach((p) => s.rsi.createPriceLine({ price: p, color: '#787b8688', lineStyle: LineStyle.Dashed, lineWidth: 1, axisLabelVisible: false }))
      pane++
    }
    if (ind.macd) {
      s.mh = chart.addSeries(HistogramSeries, { priceLineVisible: false, lastValueVisible: false }, pane)
      s.mm = L('#2962ff', 'MACD', pane); s.ms = L('#ff6d00', 'Signal', pane); pane++
    }
    ref.current = { chart, main, s, fitted: false }
    chart.subscribeCrosshairMove((p) => {
      const r = ref.current
      if (!r || !p || !p.time || !r.byTime) { setLeg(null); return }
      setLeg(r.byTime.get(p.time) || null)
    })
    return () => { chart.remove(); ref.current = null }
  }, [sym, frame, line, dark, ...IND.map(([k]) => ind[k])]) // eslint-disable-line react-hooks/exhaustive-deps

  // data
  useEffect(() => {
    const r = ref.current
    if (!r || !d || d.frame !== frame || d.symbol !== sym.toUpperCase()) return
    const off = d.offset || 0
    const bars = d.bars
    const T = (b) => b.t + off                                   // exchange local time on the axis
    const daily = ['1D', '1W'].includes(frame)
    r.main.setData(bars.map((b) => (line ? { time: T(b), value: b.c } : { time: T(b), open: b.o, high: b.h, low: b.l, close: b.c })))
    drawSessionPivots(r, d, LineSeries)
    const closes = bars.map((b) => b.c)
    const put = (se, vals) => { if (se) se.setData(bars.map((b, i) => (ok(vals[i]) ? { time: T(b), value: vals[i] } : { time: T(b) }))) }
    const s = r.s
    const hasVol = bars.some((b) => b.v > 0)
    if (s.vol) s.vol.setData(hasVol ? bars.map((b) => ({ time: T(b), value: b.v, color: b.c >= b.o ? 'rgba(8,153,129,0.45)' : 'rgba(242,54,69,0.45)' })) : [])
    put(s.vwap, daily ? [] : d.vwap)
    ;[['ema9', 9], ['ema20', 20], ['ema50', 50], ['ema200', 200]].forEach(([k, n]) => put(s[k], ema(closes, n)))
    ;[['sma20', 20], ['sma50', 50]].forEach(([k, n]) => put(s[k], sma(closes, n)))
    if (s.bbu) { const b = boll(closes); put(s.bbu, b.map((x) => x[0])); put(s.bbm, b.map((x) => x[1])); put(s.bbl, b.map((x) => x[2])) }
    if (s.stu) { const st = supertrend(bars); put(s.stu, st.map(([v, t]) => (t === 1 ? v : null))); put(s.std, st.map(([v, t]) => (t === -1 ? v : null))) }
    put(s.rsi, rsi(closes))
    if (s.mh) { const m = macd(closes); put(s.mm, m.map((x) => x[0])); put(s.ms, m.map((x) => x[1])); s.mh.setData(bars.map((b, i) => (ok(m[i][2]) ? { time: T(b), value: m[i][2], color: m[i][2] >= 0 ? 'rgba(8,153,129,0.6)' : 'rgba(242,54,69,0.6)' } : { time: T(b) }))) }
    const ps = r.chart.panes()
    if (ps.length > 1 && box.current) {
      const H = box.current.clientHeight - 30, extra = ps.length - 1
      ps[0].setHeight(Math.max(220, H - 120 * extra))
      ps.slice(1).forEach((p) => p.setHeight(120))
    }
    r.byTime = new Map(bars.map((b, i) => [T(b), { ...b, prev: i ? bars[i - 1].c : (d.prev ?? b.o), i }]))
    r.bars = bars; r.off = off
    if (!r.fitted) {
      const n = bars.length
      if (n > 160) r.chart.timeScale().setVisibleLogicalRange({ from: n - 150, to: n + 8 }); else r.chart.timeScale().fitContent()
      r.fitted = true
    }
  }, [d, frame, line, expanded, ...IND.map(([k]) => ind[k])]) // eslint-disable-line react-hooks/exhaustive-deps

  // live: NSE's last price moves the current candle (only while that candle's period is running)
  useEffect(() => {
    const r = ref.current
    if (!r || !r.bars?.length || !ok(ltp) || !live) return
    const b = r.bars[r.bars.length - 1], now = Date.now() / 1000, per = PERIOD[frame]
    if (!per || now < b.t || now > b.t + per) return
    const nb = { ...b, h: Math.max(b.h, ltp), l: Math.min(b.l, ltp), c: ltp }
    r.bars[r.bars.length - 1] = nb
    r.main.update(line ? { time: b.t + r.off, value: ltp } : { time: b.t + r.off, open: nb.o, high: nb.h, low: nb.l, close: nb.c })
  }, [ltp]) // eslint-disable-line react-hooks/exhaustive-deps

  // price label with the countdown to the candle close, and the drawings (redrawn every second and on every move)
  useEffect(() => {
    const tick = () => {
      const r = ref.current, c = cv.current
      if (!r || !c || !r.bars?.length) return
      const b = r.bars[r.bars.length - 1]
      const y = r.main.priceToCoordinate(b.c)
      const now = Math.floor(Date.now() / 1000)
      let left = null
      const per = PERIOD[frame]
      const local = (now + (r.off || 0)) % 86400, close = isUSs(sym) ? 57600 : 55800
      if (per && now >= b.t && now < b.t + per) left = Math.min(b.t + per, now - local + close) - now
      else if (frame === '1D' && local < close && local > close - 6.5 * 3600 && new Date((b.t + r.off) * 1000).getUTCDate() === new Date((now + r.off) * 1000).getUTCDate()) left = close - local
      const prev = r.bars.length > 1 ? r.bars[r.bars.length - 2].c : b.o
      setLab(y === null ? null : { y, w: r.chart.priceScale('right').width(), price: b.c, left: left !== null && left > 0 && live ? left : null, up: b.c >= (line ? prev : b.o) })
      const rect = box.current.getBoundingClientRect(), dpr = window.devicePixelRatio || 1
      const w = rect.width - r.chart.priceScale('right').width(), h = r.chart.panes()[0].getHeight()
      if (c.width !== Math.round(w * dpr) || c.height !== Math.round(h * dpr)) { c.width = Math.round(w * dpr); c.height = Math.round(h * dpr); c.style.width = `${w}px`; c.style.height = `${h}px` }
      const ctx = c.getContext('2d'); ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      drawShapes(ctx, w, h, r.chart, r.main, hideDraw ? [] : shapes, temp, dark)
    }
    tick()
    const t = setInterval(tick, 1000)
    const r = ref.current
    const onMove = () => tick()
    r?.chart.timeScale().subscribeVisibleLogicalRangeChange(onMove)
    r?.chart.subscribeCrosshairMove(onMove)
    return () => { clearInterval(t); try { r?.chart.timeScale().unsubscribeVisibleLogicalRangeChange(onMove); r?.chart.unsubscribeCrosshairMove(onMove) } catch { /* chart gone */ } }
  }, [d, shapes, temp, hideDraw, frame, line, live, dark, ...IND.map(([k]) => ind[k])]) // eslint-disable-line react-hooks/exhaustive-deps

  // drawing clicks: read straight from the mouse on the chart (state kept in refs so no click is lost between renders)
  const st = useRef({})
  st.current = { tool, temp, shapes }
  useEffect(() => {
    const el = box.current
    if (!el) return undefined
    const need = { trend: 2, ray: 2, rect: 2, fib: 2, measure: 2, hline: 1, vline: 1 }
    const at = (e) => {
      const r = ref.current
      if (!r) return null
      const rc = el.getBoundingClientRect(), x = e.clientX - rc.left, y = e.clientY - rc.top
      if (y > r.chart.panes()[0].getHeight() || x > rc.width - r.chart.priceScale('right').width()) return null
      const lg = r.chart.timeScale().coordinateToLogical(x)
      const v = r.main.coordinateToPrice(y)
      if (lg === null || v === null || !r.bars?.length) return null
      const i = Math.max(0, Math.min(r.bars.length - 1, Math.round(lg)))
      return { t: r.bars[i].t + (r.off || 0), v: +(+v).toFixed(2), i }
    }
    const down = (e) => {
      const { tool: tl, temp: tp, shapes: sh } = st.current
      if (tl === 'cursor' || e.button !== 0) return
      const pt = at(e)
      if (!pt) return
      e.preventDefault(); e.stopPropagation()
      if (need[tl] === 1) { setShapes([...sh, { k: tl, p: [{ t: pt.t, v: pt.v }] }]); setTool('cursor'); return }
      if (!tp) { setTemp({ k: tl, p: [{ t: pt.t, v: pt.v }], i0: pt.i }); return }
      setShapes([...sh, { k: tl, p: [tp.p[0], { t: pt.t, v: pt.v }], bars: Math.abs(pt.i - (tp.i0 ?? pt.i)) }]); setTemp(null); setTool('cursor')
    }
    const move = (e) => {
      const { temp: tp } = st.current
      if (!tp) return
      const pt = at(e)
      if (pt) setTemp({ ...tp, p: [tp.p[0], { t: pt.t, v: pt.v }] })
    }
    el.addEventListener('mousedown', down, true)
    el.addEventListener('mousemove', move)
    return () => { el.removeEventListener('mousedown', down, true); el.removeEventListener('mousemove', move) }
  }, [sym, frame]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { const k = (e) => { if (e.key === 'Escape') { setTemp(null); setTool('cursor') } }; window.addEventListener('keydown', k); return () => window.removeEventListener('keydown', k) }, [])

  const shot = () => {
    const c = ref.current?.chart.takeScreenshot(true)
    if (!c) return
    const a = document.createElement('a'); a.href = c.toDataURL('image/png'); a.download = `${sym.replace('US:', '')}_${frame}.png`; a.click()
  }
  const last = d?.bars?.length ? { ...d.bars[d.bars.length - 1], prev: d.bars.length > 1 ? d.bars[d.bars.length - 2].c : d.prev } : null
  const L = leg || last
  const ch = L && ok(L.prev) ? L.c - L.prev : null
  const exch = isUSs(sym) ? (isIdx(sym) ? 'US index' : 'US') : isIdx(sym) ? 'NSE index' : 'NSE'
  const f2 = (v) => (ok(v) ? num(v, 2) : '—')
  const active = IND.filter(([k]) => ind[k] && !['vol'].includes(k))
  return (
    <div className="tv" ref={wrap}>
      <div className="tv-bar">
        <div className="tv-frames">{Object.entries(FRAME_LABEL).map(([k, l]) => <button key={k} className={frame === k ? 'on' : ''} onClick={() => setFrame(k)}>{l}</button>)}</div>
        <span className="tv-sep" />
        <button className={`tv-btn ${!line ? 'on' : ''}`} onClick={() => { setLine(false); saveJ('eql_term_line', false) }} title="Candles">
          <svg viewBox="0 0 24 24" className="tv-ic"><path d="M7 4v16M17 4v16" /><rect x="5" y="8" width="4" height="7" /><rect x="15" y="6" width="4" height="9" /></svg></button>
        <button className={`tv-btn ${line ? 'on' : ''}`} onClick={() => { setLine(true); saveJ('eql_term_line', true) }} title="Line">
          <svg viewBox="0 0 24 24" className="tv-ic"><path d="M3 17l5-6 4 3 5-7 4 4" /></svg></button>
        <span className="tv-sep" />
        <div className="tv-menu-wrap">
          <button className={`tv-btn ${menu ? 'on' : ''}`} onClick={() => setMenu(!menu)}>
            <svg viewBox="0 0 24 24" className="tv-ic"><path d="M3 18l5-7 4 4 6-9M17 6h3v3" /></svg> Indicators{active.length ? ` · ${active.length}` : ''}</button>
          {menu && (
            <div className="tv-menu" onMouseLeave={() => setMenu(false)}>
              {IND.map(([k, l]) => (
                <label key={k}><input type="checkbox" checked={!!ind[k]} onChange={() => flip(k)} /><i style={{ background: IND_COLOR[k] || (k === 'st' ? UP : k === 'rsi' ? '#7e57c2' : k === 'macd' ? '#2962ff' : '#787b86') }} />{l}</label>
              ))}
              <div className="small muted" style={{ padding: '6px 10px 2px' }}>Worked out here from the candles shown.</div>
            </div>
          )}
        </div>
        <button hidden={!onAlert} className="tv-btn" onClick={onAlert} title="Price alert"><svg viewBox="0 0 24 24" className="tv-ic"><path d="M6 17h12l-1.5-2V11a4.5 4.5 0 0 0-9 0v4zM10 20h4" /></svg> Alert</button>
        <span className="grow" />
        <button className="tv-btn" title="Fit all candles" onClick={() => ref.current?.chart.timeScale().fitContent()}><svg viewBox="0 0 24 24" className="tv-ic"><path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5" /></svg></button>
        <button className="tv-btn" title="Save a picture of the chart" onClick={shot}><svg viewBox="0 0 24 24" className="tv-ic"><rect x="3" y="7" width="18" height="13" rx="2" /><circle cx="12" cy="13.5" r="3.5" /><path d="M8 7l2-3h4l2 3" /></svg></button>
        <button className={`tv-btn ${expanded ? 'on' : ''}`} title={expanded ? 'Normal size' : 'Bigger chart'} onClick={() => setExpanded(!expanded)}><svg viewBox="0 0 24 24" className="tv-ic">{expanded ? <path d="M9 4v5H4M15 4v5h5M9 20v-5H4M15 20v-5h5" /> : <path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5M9 9l-4-4M15 9l4-4M9 15l-4 4M15 15l4 4" />}</svg></button>
      </div>
      <div className="tv-body">
        <div className="tv-tools">
          {TOOLS.map(([k, label, icon]) => <button key={k} title={label} className={tool === k ? 'on' : ''} onClick={() => { setTool(k); setTemp(null) }}><svg viewBox="0 0 24 24">{icon}</svg></button>)}
          <span className="tv-tsep" />
          <button title="Undo last drawing" onClick={() => setShapes(shapes.slice(0, -1))} disabled={!shapes.length}><svg viewBox="0 0 24 24"><path d="M9 14L4 9l5-5M4 9h11a5 5 0 0 1 0 10h-3" /></svg></button>
          <button title={hideDraw ? 'Show drawings' : 'Hide drawings'} className={hideDraw ? 'on' : ''} onClick={() => setHideDraw(!hideDraw)}><svg viewBox="0 0 24 24"><path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6S2 12 2 12z" /><circle cx="12" cy="12" r="2.5" />{hideDraw && <path d="M4 4l16 16" />}</svg></button>
          <button title="Remove all drawings on this symbol" onClick={() => setShapes([])} disabled={!shapes.length}><svg viewBox="0 0 24 24"><path d="M5 7h14M10 7V4h4v3M7 7l1 13h8l1-13" /></svg></button>
        </div>
        <div className="tv-wrap" style={{ cursor: tool === 'cursor' ? 'default' : 'crosshair' }}>
          <div ref={box} className={`tv-chart ${expanded ? 'big' : ''}`} />
          <canvas ref={cv} className="tv-draw" />
          {lab && (
            <div className="tv-last" style={{ top: lab.y - (lab.left ? 17 : 10), width: lab.w, background: lab.up ? UP : DOWN }}>
              <b>{num(lab.price, 2)}</b>{lab.left ? <span>{mmss(lab.left)}</span> : null}
            </div>
          )}
          <div className="tv-legend">
            <div className="t1"><b>{US_NAMES[sym] || name || sym.replace('US:', '')}</b> · {FRAME_LABEL[frame]} · {exch}</div>
            {L && <div className="t2">O<span style={{ color: tone(L.c - L.o) }}>{f2(L.o)}</span> H<span style={{ color: tone(L.c - L.o) }}>{f2(L.h)}</span> L<span style={{ color: tone(L.c - L.o) }}>{f2(L.l)}</span> C<span style={{ color: tone(L.c - L.o) }}>{f2(L.c)}</span>
              {ok(ch) && <span style={{ color: tone(ch) }}> {signed(ch, 2)} ({signed((ch / L.prev) * 100, 2, '%')})</span>}
              {L.v > 0 && ind.vol && <span className="muted"> · Vol {big(L.v)}</span>}</div>}
            {active.length > 0 && <div className="t3">{active.map(([k, l]) => <span key={k} style={{ color: IND_COLOR[k] || 'var(--muted)' }}>{l.split(' ·')[0]}</span>)}</div>}
            {tool !== 'cursor' && <div className="t4">{temp ? 'Click the second point · Esc to cancel' : `${TOOLS.find((x) => x[0] === tool)[1]} · Esc to cancel`}</div>}
          </div>
        </div>
      </div>
      <div className="small muted term-src src-note">{err ? <span style={{ color: 'var(--bad)' }}>{err}</span> : d ? `${d.source} · ${d.yahoo}${pivotCaption(d)}${ind.vwap && !['1D', '1W'].includes(frame) ? ' · VWAP from these candles' : ''}` : 'Loading candles…'}</div>
      {err && <div className="small" style={{ color: 'var(--bad)', padding: '0 10px 8px' }}>{err}</div>}
    </div>
  )
}

// ---------------------------------------------------------------- stats strip above the chart (replaces the side panel)
function Stats({ sym, q, t, y }) {
  const cur = isUSs(sym) ? '$' : isIdx(sym) ? '' : '₹'
  const items = q ? [
    ['Open', px(q.open, cur)], ['High', px(q.high, cur)], ['Low', px(q.low, cur)], ['Prev close', px(q.prev, cur)], ['VWAP', px(q.vwap, cur)],
    ['Circuit', ok(q.lower_circuit) ? `${num(q.lower_circuit, 2)} – ${num(q.upper_circuit, 2)}` : '—'],
    ['52W range', ok(q.wk_low) ? `${num(q.wk_low, 2)} – ${num(q.wk_high, 2)}` : '—'],
    ['Volume', big(t?.volume)], ['Value', ok(t?.value_cr) ? `₹${num(t.value_cr, 2)} Cr` : '—'],
    ['Delivery', ok(t?.delivery_pct) ? `${num(t.delivery_pct, 1)}%` : '—'], ['P/E', ok(q.pe) ? num(q.pe, 1) : '—'],
  ] : y ? (() => {
    const today = y.bars.filter((b) => new Date((b.t + y.offset) * 1000).toISOString().slice(0, 10) === new Date((y.bars[y.bars.length - 1].t + y.offset) * 1000).toISOString().slice(0, 10))
    return [['Open', px(today[0]?.o, cur)], ['High', px(today.length ? Math.max(...today.map((b) => b.h)) : null, cur)], ['Low', px(today.length ? Math.min(...today.map((b) => b.l)) : null, cur)], ['Prev close', px(y.prev, cur)]]
  })() : []
  if (!items.length) return null
  return <div className="tv-stats">{items.map(([k, v]) => <div key={k}><span>{k}</span><b>{v}</b></div>)}</div>
}

function Depth({ t, q }) {
  const dep = t?.depth
  if (!dep) return <div className="small muted">{t ? 'NSE shows no order book now (market closed or pre-open).' : 'Market depth is shown for NSE stocks.'}</div>
  if (!dep.ok) return <div className="small" style={{ color: 'var(--warn)' }}>Left out: {dep.why}</div>
  const maxQ = Math.max(1, ...dep.bids.map((b) => b.qty || 0), ...dep.asks.map((a) => a.qty || 0))
  return (
    <div className="term-depth-wrap">
      <div className="term-depth">
        <div className="hd"><span>Bid qty</span><span>Bid</span><span>Ask</span><span>Ask qty</span></div>
        {Array.from({ length: Math.max(dep.bids.length, dep.asks.length) }).map((_, i) => {
          const b = dep.bids[i], a = dep.asks[i]
          return (
            <div key={i} className="ln">
              <span className="q b"><i style={{ width: `${((b?.qty || 0) / maxQ) * 100}%` }} />{b ? num(b.qty) : ''}</span>
              <span style={{ color: 'var(--good)' }}>{b ? num(b.price, 2) : ''}</span>
              <span style={{ color: 'var(--bad)' }}>{a ? num(a.price, 2) : ''}</span>
              <span className="q a"><i style={{ width: `${((a?.qty || 0) / maxQ) * 100}%` }} />{a ? num(a.qty) : ''}</span>
            </div>
          )
        })}
      </div>
      {ok(dep.total_buy) && ok(dep.total_sell) && (
        <div className="term-press">
          <div><i style={{ width: `${(dep.total_buy / (dep.total_buy + dep.total_sell)) * 100}%` }} /></div>
          <span className="small"><b style={{ color: 'var(--good)' }}>{big(dep.total_buy)}</b> pending to buy ({num((dep.total_buy / (dep.total_buy + dep.total_sell)) * 100, 1)}%) · <b style={{ color: 'var(--bad)' }}>{big(dep.total_sell)}</b> pending to sell</span>
        </div>
      )}
      <div className="small muted src-note" style={{ marginTop: 6 }}>NSE order book{q?.time ? ` · as of ${q.time}` : ''}</div>
    </div>
  )
}

// ---------------------------------------------------------------- bottom: option chain / futures
function Chain({ sym, live }) {
  const [d, setD] = useState(null)
  const [exp, setExp] = useState('')
  const [width, setWidth] = useState(10)
  usePoll(() => api(`/api/term/fno/${encodeURIComponent(sym)}${exp ? `?expiry=${encodeURIComponent(exp)}` : ''}`).then(setD).catch(() => {}), live ? 15000 : 120000, [sym, exp, live])
  if (!d) return <div className="small muted">Loading option chain…</div>
  const c = d.chain
  if (!c) return <div className="small" style={{ color: 'var(--bad)' }}>Option chain not available: {d.sources?.[0]?.error}</div>
  const i = c.rows.findIndex((r) => r.strike === c.atm)
  const rows = i < 0 ? c.rows : c.rows.slice(Math.max(0, i - width), i + width + 1)
  const maxOi = Math.max(1, ...rows.map((r) => Math.max(r.ce_oi || 0, r.pe_oi || 0)))
  const f = (v, d2 = 0) => (ok(v) ? num(v, d2) : '—')
  return (
    <div>
      <div className="row wrapflex" style={{ gap: 8, marginBottom: 8 }}>
        <select value={c.expiry || ''} onChange={(e) => setExp(e.target.value)}>{(c.expiries || []).map((e) => <option key={e} value={e}>{e}</option>)}</select>
        <select value={width} onChange={(e) => setWidth(+e.target.value)}>{[5, 10, 15, 25].map((w) => <option key={w} value={w}>±{w} strikes</option>)}</select>
        <span className="chip">Spot <b>{f(c.spot, 2)}</b></span>
        <span className="chip" title="put OI ÷ call OI, worked out from NSE's open interest">PCR <b>{f(c.pcr, 2)}</b></span>
        <span className="chip" title="strike where option buyers' total value is smallest, worked out from NSE's open interest">Max pain <b>{f(c.max_pain)}</b></span>
        <span className="chip">Call OI <b>{big(c.ce_oi)}</b></span><span className="chip">Put OI <b>{big(c.pe_oi)}</b></span>
        <span className="small muted">{c.time ? `as of ${c.time}` : ''}<span className="src-note"> · NSE</span></span>
      </div>
      <div className="tbl-wrap"><table className="tbl term-oc"><thead><tr>
        <th>Call OI</th><th>Chg OI</th><th>IV</th><th>Vol</th><th>LTP</th><th className="k">Strike</th><th>LTP</th><th>Vol</th><th>IV</th><th>Chg OI</th><th>Put OI</th>
      </tr></thead><tbody>
        {rows.map((r) => {
          const itmC = ok(c.spot) && r.strike < c.spot, itmP = ok(c.spot) && r.strike > c.spot
          return (
            <tr key={r.strike} className={r.strike === c.atm ? 'atm' : ''}>
              <td className={itmC ? 'itm' : ''}><div className="oi c"><i style={{ width: `${((r.ce_oi || 0) / maxOi) * 100}%` }} /><span>{big(r.ce_oi)}</span></div></td>
              <td className={itmC ? 'itm' : ''} style={{ color: tone(r.ce_oi_chg) }}>{big(r.ce_oi_chg)}</td>
              <td className={itmC ? 'itm' : ''}>{f(r.ce_iv, 1)}</td><td className={itmC ? 'itm' : ''}>{big(r.ce_vol)}</td>
              <td className={itmC ? 'itm' : ''}><b>{f(r.ce_ltp, 2)}</b></td>
              <td className="k"><b>{num(r.strike)}</b></td>
              <td className={itmP ? 'itm' : ''}><b>{f(r.pe_ltp, 2)}</b></td><td className={itmP ? 'itm' : ''}>{big(r.pe_vol)}</td>
              <td className={itmP ? 'itm' : ''}>{f(r.pe_iv, 1)}</td>
              <td className={itmP ? 'itm' : ''} style={{ color: tone(r.pe_oi_chg) }}>{big(r.pe_oi_chg)}</td>
              <td className={itmP ? 'itm' : ''}><div className="oi p"><i style={{ width: `${((r.pe_oi || 0) / maxOi) * 100}%` }} /><span>{big(r.pe_oi)}</span></div></td>
            </tr>
          )
        })}
      </tbody></table></div>
      <div className="small muted" style={{ marginTop: 6 }}>Shaded = in the money. OI = open interest (contracts as NSE reports them). PCR and max pain are worked out from NSE's open interest.</div>
      <Futures d={d.deriv} err={d.sources?.[1]?.error} />
    </div>
  )
}

function Futures({ d, err }) {
  if (!d) return <div className="small" style={{ color: 'var(--bad)', marginTop: 10 }}>Futures not available{err ? `: ${err}` : ''}</div>
  if (!d.futures.length) return null
  return (
    <div style={{ marginTop: 12 }}>
      <h3>Futures</h3>
      <div className="tbl-wrap"><table className="tbl"><thead><tr><th style={{ textAlign: 'left' }}>Expiry</th><th>Price</th><th>Change</th><th>Basis vs spot</th><th>OI</th><th>OI change</th><th>Contracts</th></tr></thead><tbody>
        {d.futures.map((f) => (
          <tr key={f.expiry}><td style={{ textAlign: 'left' }}>{f.expiry}</td><td><b>{px(f.ltp)}</b></td><td style={{ color: tone(f.change) }}>{signed(f.change, 2)} ({signed(f.pchange, 2, '%')})</td>
            <td style={{ color: tone(f.basis) }}>{signed(f.basis, 2)}</td><td>{big(f.oi)}</td><td style={{ color: tone(f.oi_change) }}>{big(f.oi_change)}</td><td>{big(f.volume)}</td></tr>
        ))}
      </tbody></table></div>
      <div className="small muted" style={{ marginTop: 4 }}>Basis = futures price − spot ({px(d.spot)}){d.time ? ` · as of ${d.time}` : ''}<span className="src-note"> · NSE</span></div>
    </div>
  )
}

// ---------------------------------------------------------------- alerts (this browser)
const LA = 'eql_term_alerts'
const loadA = () => { try { return JSON.parse(localStorage.getItem(LA)) || [] } catch { return [] } }
function Alerts({ sym, head, alerts, setAlerts }) {
  const [p, setP] = useState('')
  const add = (dir) => { const v = parseFloat(p); if (!v) return; const a = [...alerts, { id: Date.now(), sym, dir, price: v }]; setAlerts(a); setP('') }
  return (
    <div>
      <div className="row wrapflex" style={{ gap: 8 }}>
        <input type="number" placeholder={ok(head?.ltp) ? `e.g. ${num(head.ltp, 0)}` : 'price'} value={p} onChange={(e) => setP(e.target.value)} style={{ width: 140 }} />
        <button className="btn small" onClick={() => add('above')}>Alert when {sym} goes above</button>
        <button className="btn small" onClick={() => add('below')}>…goes below</button>
      </div>
      <div style={{ marginTop: 10 }}>
        {alerts.length === 0 ? <div className="small muted">No alerts. They sound on this device while the terminal is open, and show a desktop notification if allowed.</div>
          : alerts.map((a) => (
            <div key={a.id} className="term-r"><span>{a.sym} {a.dir} {num(a.price, 2)}{a.hit ? ` · hit ${a.hit}` : ''}</span><button className="chip" onClick={() => setAlerts(alerts.filter((x) => x.id !== a.id))}>remove</button></div>
          ))}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------- page
export default function Terminal() {
  const mk = getMarket() === 'US' ? 'US' : 'IN'
  const LS = `eql_term_watch_${mk}`
  const startList = () => {
    const own = loadJ(LS, null)
    if (own) return own
    const old = loadJ('eql_term_watch', null)                 // the single list from before: split by market
    const mine = (old || []).filter((s) => (mk === 'US') === isUSs(s))
    return mine.length ? mine : DEFAULT_WATCH[mk]
  }
  const [watch, setWatch] = useState(startList)
  const [sym, setSym] = useState(() => startList()[0])
  const [addErr, setAddErr] = useState('')
  const [frame, setFrameRaw] = useState(() => loadJ('eql_term_frame2', '5m'))
  const setFrame = (f) => { setFrameRaw(f); saveJ('eql_term_frame2', f) }
  const [tab, setTab] = useState('chain')
  const [nseq, setNseq] = useState(null)
  const [yq, setYq] = useState(null)
  const [wq, setWq] = useState({})
  const [add, setAdd] = useState('')
  const [expanded, setExpanded] = useState(false)
  const [alerts, setAlertsRaw] = useState(() => loadJ('eql_term_alerts', []))
  const setAlerts = (a) => { setAlertsRaw(a); saveJ('eql_term_alerts', a) }
  const nse = !isUSs(sym) && !isIdx(sym)
  const live = mk === 'US' ? usOpen() : nseOpen()
  useEffect(() => { saveJ(LS, watch) }, [watch])
  useEffect(() => { setNseq(null); setYq(null) }, [sym])
  usePoll(() => {
    if (nse) api(`/api/term/stock/${encodeURIComponent(sym)}`).then(setNseq).catch(() => {})
    api(`/api/term/candles/${encodeURIComponent(sym)}?frame=5m`).then(setYq).catch(() => {})
  }, live ? 3000 : 60000, [sym, live])
  usePoll(() => api(`/api/term/watch?symbols=${encodeURIComponent(watch.join(','))}`).then((x) => setWq(Object.fromEntries(x.rows.map((r) => [r.symbol, r])))).catch(() => {}), 15000, [watch.join(',')])
  const q = nseq?.quote
  const head = q ? { ltp: q.ltp, change: q.change, pchange: q.pchange, name: q.name, time: q.time, src: 'NSE', fno: q.fno }
    : yq ? { ltp: yq.price, change: yq.change, pchange: yq.pchange, name: yq.name, time: yq.time ? new Date(yq.time * 1000).toLocaleTimeString('en-IN') : null, src: 'Yahoo' } : null
  // price alerts: checked against every quote and watchlist update
  useEffect(() => {
    const prices = { ...Object.fromEntries(Object.entries(wq).map(([k, v]) => [k, v.price])), ...(head?.ltp ? { [sym]: head.ltp } : {}) }
    let changed = false
    const next = alerts.map((a) => {
      const p0 = prices[a.sym]
      if (a.hit || !ok(p0) || !((a.dir === 'above' && p0 >= a.price) || (a.dir === 'below' && p0 <= a.price))) return a
      changed = true
      try { chime() } catch { /* ignore */ }
      try { if (window.Notification && Notification.permission === 'granted') new Notification(`${a.sym} ${a.dir} ${a.price}`, { body: `Now ${p0}` }) } catch { /* ignore */ }
      return { ...a, hit: new Date().toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' }) }
    })
    if (changed) setAlerts(next)
  }, [wq, head?.ltp]) // eslint-disable-line react-hooks/exhaustive-deps
  const hasChain = isIdx(sym) || !!head?.fno
  const cur = isUSs(sym) ? '$' : isIdx(sym) ? '' : '₹'
  const addSym = () => {
    let s = add.trim().toUpperCase().replace(/\s+/g, '')
    if (!s) return
    if (mk === 'US') { if (!s.startsWith('US:')) s = `US:${s}` } else if (s.startsWith('US:')) { setAddErr('US symbols belong to the US view: switch to 🇺🇸 US at the top.'); return }
    setAddErr('')
    if (!watch.includes(s)) setWatch([...watch, s])
    setSym(s); setAdd('')
  }
  const tabs = [['chain', hasChain ? 'Option chain & futures' : null], ['depth', nse ? 'Market depth' : null], ['alerts', `Alerts${alerts.filter((a) => !a.hit).length ? ` · ${alerts.filter((a) => !a.hit).length}` : ''}`]].filter(([, l]) => l)
  const t = tabs.some(([k]) => k === tab) ? tab : tabs[0][0]
  const bottomRef = useRef()
  const goAlerts = () => { setTab('alerts'); setTimeout(() => bottomRef.current?.scrollIntoView({ behavior: 'smooth' }), 50) }
  return (
    <div className={`term ${expanded ? 'expanded' : ''}`}>
      <div className="term-top">
        <div className="row" style={{ gap: 10, alignItems: 'baseline', flexWrap: 'wrap' }}>
          <h2 style={{ margin: 0 }}>{sym.replace('US:', '')}</h2>
          <span className="muted small">{US_NAMES[sym] || head?.name || ''}</span>
          {head && ok(head.ltp) && <><b className="term-ltp">{cur}{num(head.ltp, 2)}</b><b style={{ color: tone(head.change) }}>{signed(head.change, 2)} ({signed(head.pchange, 2, '%')})</b></>}
          <span className={`ipo-cd ${live ? 'warm' : ''}`}>{mk === 'US' ? (live ? '🟢 US market open' : 'US market closed · last prices') : live ? '🟢 NSE open · live every 3 s' : 'NSE closed · last prices'}</span>
          {head?.time && <span className="small muted">as of {head.time}<span className="src-note"> ({head.src})</span></span>}
        </div>
      </div>
      <Stats sym={sym} q={q} t={nseq?.trade} y={!q ? yq : null} />
      <div className="term-grid">
        <div className="card term-watch">
          <div className="row" style={{ gap: 6, marginBottom: 8 }}>
            <input value={add} onChange={(e) => setAdd(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && addSym()} placeholder={mk === 'US' ? 'Add: MSFT, AMD…' : 'Add: TCS, NIFTY…'} style={{ flex: 1, minWidth: 0, padding: '7px 9px' }} />
            <button className="btn small" onClick={addSym}>+</button>
          </div>
          {addErr && <div className="small" style={{ color: 'var(--warn)', marginBottom: 6 }}>{addErr}</div>}
          {watch.map((w) => {
            const x = wq[w]
            return (
              <div key={w} className={`term-w ${w === sym ? 'on' : ''}`} onClick={() => setSym(w)}>
                <span className="s">{w.replace('US:', '')}{isIdx(w) && <small> IDX</small>}</span>
                <span className="p">{x?.price ? num(x.price, 2) : '—'}<small style={{ color: tone(x?.pchange) }}>{ok(x?.pchange) ? signed(x.pchange, 2, '%') : ''}</small></span>
                <button className="x" title="Remove" onClick={(e) => { e.stopPropagation(); setWatch(watch.filter((z) => z !== w)) }}>×</button>
              </div>
            )
          })}
          <div className="small muted src-note" style={{ marginTop: 6 }}>Watchlist prices: Yahoo, every 15 s</div>
        </div>
        <div className="card term-center">
          <Chart sym={sym} frame={frame} setFrame={setFrame} name={head?.name} live={live} ltp={q?.ltp} onAlert={goAlerts} expanded={expanded} setExpanded={setExpanded} />
        </div>
      </div>
      <div className="card" ref={bottomRef}>
        <div className="row" style={{ gap: 6, marginBottom: 10 }}>{tabs.map(([k, l]) => <button key={k} className={`tab ${t === k ? 'on' : ''}`} onClick={() => setTab(k)}>{l}</button>)}</div>
        {t === 'chain' && <Chain key={sym} sym={sym} live={live} />}
        {t === 'depth' && <Depth t={nseq?.trade} q={q} />}
        {t === 'alerts' && <Alerts sym={sym} head={head} alerts={alerts} setAlerts={setAlerts} />}
      </div>
    </div>
  )
}
