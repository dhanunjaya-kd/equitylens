import { useEffect, useMemo, useRef, useState } from 'react'
import { CandlestickSeries, ColorType, CrosshairMode, HistogramSeries, LineSeries, LineStyle, createChart, createSeriesMarkers, createTextWatermark } from 'lightweight-charts'
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api, getMarket, num, ok, saveLocal, signed } from '../util'
import { chime } from '../components/BreakingBar'
import { INDICATORS, BY_ID, calc as icalc } from '../indicators'
import IndicatorPicker, { addRecent } from '../components/IndicatorPicker'
import { TOOL, TOOL_GROUPS, drawShapes, hitTest } from '../components/drawing'

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
const loadDraw = (s) => {
  const all = loadJ('eql_term_draw', {})
  return all[s] ?? loadJ(`eql_draw_${s}`, [])
}
const saveDraw = (s, shapes) => {
  const all = { ...loadJ('eql_term_draw', {}), [s]: shapes }
  saveLocal('eql_term_draw', all)
}
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

const IND_KEY = (ind) => INDICATORS.filter((x) => ind[x.id]).map((x) => x.id).join(',')
const perYearOf = (frame, us) => ({ '1D': 252, '1W': 52 }[frame] || Math.round(252 * ((us ? 390 : 375) / ({ '1m': 1, '3m': 3, '5m': 5, '15m': 15, '30m': 30, '1h': 60, '4h': 240 }[frame] || 5))))

export function Chart({ sym, frame, setFrame, name, live, ltp, onAlert, expanded, setExpanded }) {
  const box = useRef(), cv = useRef(), wrap = useRef()
  const ref = useRef(null)
  const [d, setD] = useState(null)
  const [err, setErr] = useState('')
  const [ind, setInd] = useState(() => ({ vol: true, vwap: true, ...loadJ('eql_term_ind', {}) }))
  const [line, setLine] = useState(() => loadJ('eql_term_line', false))
  const [picker, setPicker] = useState(false)
  const [leg, setLeg] = useState(null)
  const [tool, setTool] = useState('cursor')
  const [fly, setFly] = useState(null)                        // open tool group
  const [lastOf, setLastOf] = useState(() => loadJ('eql_tool_last', {}))
  const [magnet, setMagnet] = useState(() => loadJ('eql_magnet', false))
  const [shapes, setShapesRaw] = useState(() => loadDraw(sym))
  const [hideDraw, setHideDraw] = useState(false)
  const [temp, setTemp] = useState(null)
  const [sel, setSel] = useState(-1)
  const [textAt, setTextAt] = useState(null)                  // { x, y, p } while typing a text drawing
  const [lab, setLab] = useState(null)
  const dark = document.documentElement.dataset.theme !== 'light'
  const daily = ['1D', '1W'].includes(frame)
  const setShapes = (s) => { setShapesRaw(s); saveDraw(sym, s) }
  useEffect(() => { setShapesRaw(loadDraw(sym)); setTemp(null); setSel(-1) }, [sym])
  const toggleInd = (k) => { const o = { ...ind, [k]: !ind[k] }; setInd(o); saveJ('eql_term_ind', o); if (o[k]) addRecent(k) }
  const pickTool = (k) => {
    setTool(k); setTemp(null); setFly(null); setSel(-1)
    if (k !== 'cursor') { const g = TOOL[k].group; const o = { ...lastOf, [g]: k }; setLastOf(o); saveJ('eql_tool_last', o) }
  }
  const ikey = IND_KEY(ind)
  useEffect(() => {
    let active = true
    const update = async () => {
      try {
        const next = await api(`/api/term/candles/${encodeURIComponent(sym)}?frame=${frame}`)
        if (active) { setD(next); setErr('') }
      } catch (error) { if (active) setErr(error.message) }
    }
    setD(null); setErr(''); setLeg(null); update()
    const timer = setInterval(() => { if (!document.hidden) update() }, daily ? 300000 : 30000)
    return () => { active = false; clearInterval(timer) }
  }, [sym, frame]) // eslint-disable-line react-hooks/exhaustive-deps

  // build the chart with one series per indicator line (price pane, or a pane of its own)
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
    const L = (ln, pane, own) => chart.addSeries(LineSeries, {
      color: ln.color, lineWidth: ln.width || 1.5, priceLineVisible: false, lastValueVisible: own, crosshairMarkerVisible: false, title: ln.label,
      lineStyle: ln.dash ? LineStyle.Dashed : LineStyle.Solid, ...(ln.dots ? { lineVisible: false, pointMarkersVisible: true, pointMarkersRadius: 1.6 } : {}),
    }, pane)
    const s = {}
    let pane = 1
    for (const x of INDICATORS) {
      if (!ind[x.id]) continue
      if (x.intraday && daily) continue
      if (x.special === 'vol') { s.vol = chart.addSeries(HistogramSeries, { priceScaleId: 'vol', priceFormat: { type: 'volume' }, lastValueVisible: false, priceLineVisible: false }); s.vol.priceScale().applyOptions({ scaleMargins: { top: 0.86, bottom: 0 } }); continue }
      if (x.special === 'swings') { s.swings = createSeriesMarkers(main, []); continue }
      const own = x.pane === 'own'
      const p = own ? pane++ : 0
      const se = { lines: {}, hist: null }
      if (x.hist) se.hist = chart.addSeries(HistogramSeries, { priceLineVisible: false, lastValueVisible: !x.lines.length, title: x.lines.length ? '' : x.short }, p)
      for (const ln of x.lines) se.lines[ln.k] = L(ln, p, own)
      const first = Object.values(se.lines)[0] || se.hist
      for (const lv of x.levels || []) first?.createPriceLine({ price: lv, color: '#787b8688', lineStyle: LineStyle.Dashed, lineWidth: 1, axisLabelVisible: false })
      s[x.id] = se
    }
    ref.current = { chart, main, s, fitted: false }
    chart.subscribeCrosshairMove((pt) => {
      const r = ref.current
      if (!r || !pt || !pt.time || !r.byTime) { setLeg(null); return }
      setLeg(r.byTime.get(pt.time) || null)
    })
    return () => { chart.remove(); ref.current = null }
  }, [sym, frame, line, dark, ikey]) // eslint-disable-line react-hooks/exhaustive-deps

  // data
  useEffect(() => {
    const r = ref.current
    if (!r || !d || d.frame !== frame || d.symbol !== sym.toUpperCase()) return
    const off = d.offset || 0
    const bars = d.bars
    const T = (b) => b.t + off                                   // exchange local time on the axis
    r.main.setData(bars.map((b) => (line ? { time: T(b), value: b.c } : { time: T(b), open: b.o, high: b.h, low: b.l, close: b.c })))
    drawSessionPivots(r, d, LineSeries)
    const put = (se, vals) => { if (se) se.setData(bars.map((b, i) => (ok(vals[i]) ? { time: T(b), value: vals[i] } : { time: T(b) }))) }
    const s = r.s
    const hasVol = bars.some((b) => b.v > 0)
    if (s.vol) s.vol.setData(hasVol ? bars.map((b) => ({ time: T(b), value: b.v, color: b.c >= b.o ? 'rgba(8,153,129,0.45)' : 'rgba(242,54,69,0.45)' })) : [])
    const ctx = { perYear: perYearOf(frame, isUSs(sym)), dayOf: (b) => new Date((b.t + off) * 1000).toISOString().slice(0, 10) }
    for (const x of INDICATORS) {
      const se = s[x.id]
      if (!se || x.special === 'vol') continue
      if (x.special === 'swings') {
        se.setMarkers(icalc.swings(bars).map((p) => ({ time: T(bars[p.i]), position: p.kind === 'H' ? 'aboveBar' : 'belowBar', color: p.kind === 'H' ? DOWN : UP, shape: p.kind === 'H' ? 'arrowDown' : 'arrowUp', size: 0.6 })))
        continue
      }
      if (x.special === 'vwap') { put(se.lines.v, daily ? [] : (d.vwap || [])); continue }
      if (x.special === 'zigzag') { const zz = icalc.zigzag(bars); se.lines.v.setData(zz.map((p) => ({ time: T(bars[p.i]), value: p.p }))); continue }
      const out = x.run(bars, ctx)
      for (const ln of x.lines) put(se.lines[ln.k], out[ln.k])
      if (se.hist) { const hv = out[x.hist]; se.hist.setData(bars.map((b, i) => (ok(hv[i]) ? { time: T(b), value: hv[i], color: x.id === 'rvol' ? (hv[i] >= 1 ? 'rgba(8,153,129,0.6)' : 'rgba(120,123,134,0.5)') : hv[i] >= 0 ? 'rgba(8,153,129,0.6)' : 'rgba(242,54,69,0.6)' } : { time: T(b) }))) }
    }
    const ps = r.chart.panes()
    if (ps.length > 1 && box.current) {
      const H = box.current.clientHeight - 30, extra = ps.length - 1, each = extra > 2 ? 95 : 120
      ps[0].setHeight(Math.max(200, H - each * extra))
      ps.slice(1).forEach((p) => p.setHeight(each))
    }
    r.byTime = new Map(bars.map((b, i) => [T(b), { ...b, prev: i ? bars[i - 1].c : (d.prev ?? b.o), i }]))
    r.bars = bars; r.off = off
    if (!r.fitted) {
      const n = bars.length
      if (n > 160) r.chart.timeScale().setVisibleLogicalRange({ from: n - 150, to: n + 8 }); else r.chart.timeScale().fitContent()
      r.fitted = true
    }
  }, [d, frame, line, expanded, ikey]) // eslint-disable-line react-hooks/exhaustive-deps

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

  // the chart does not pan or zoom while a drawing tool is in use (a finger drag draws instead)
  useEffect(() => {
    const r = ref.current
    if (r) r.chart.applyOptions({ handleScroll: tool === 'cursor', handleScale: tool === 'cursor' })
  }, [tool, d])

  // price label with the countdown to the candle close, and the drawings (redrawn every second and on every move)
  const redraw = useRef(() => {})
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
      drawShapes(ctx, w, h, r.chart, r.main, hideDraw ? [] : shapes, temp, dark, sel)
    }
    redraw.current = tick
    tick()
    const t = setInterval(tick, 1000)
    const r = ref.current
    const onMove = () => tick()
    r?.chart.timeScale().subscribeVisibleLogicalRangeChange(onMove)
    r?.chart.subscribeCrosshairMove(onMove)
    return () => { clearInterval(t); try { r?.chart.timeScale().unsubscribeVisibleLogicalRangeChange(onMove); r?.chart.unsubscribeCrosshairMove(onMove) } catch { /* chart gone */ } }
  }, [d, shapes, temp, hideDraw, frame, line, live, dark, ikey, sel]) // eslint-disable-line react-hooks/exhaustive-deps

  // drawing with mouse, pen or finger (pointer events), state kept in refs so no tap is lost between renders
  const st = useRef({})
  st.current = { tool, temp, shapes, magnet, sel, hideDraw }
  useEffect(() => {
    const el = box.current
    if (!el) return undefined
    const local = (e) => { const rc = el.getBoundingClientRect(); return [e.clientX - rc.left, e.clientY - rc.top, rc] }
    const at = (e) => {
      const r = ref.current
      if (!r || !r.bars?.length) return null
      const [x, y, rc] = local(e)
      if (y > r.chart.panes()[0].getHeight() || x > rc.width - r.chart.priceScale('right').width()) return null
      const lg = r.chart.timeScale().coordinateToLogical(x)
      let v = r.main.coordinateToPrice(y)
      if (lg === null || v === null) return null
      const i = Math.max(0, Math.min(r.bars.length - 1, Math.round(lg)))
      const f = Math.max(-0.5, Math.min(0.5, lg - i))
      if (st.current.magnet) { const b = r.bars[i]; v = [b.o, b.h, b.l, b.c].reduce((a, q) => (Math.abs(q - v) < Math.abs(a - v) ? q : a), b.c) }
      return { t: r.bars[i].t + (r.off || 0), f: +f.toFixed(3), v: +(+v).toFixed(2), i }
    }
    let drag = null
    const finish = (sh) => { setShapes(sh); setTemp(null); setTool('cursor') }
    const down = (e) => {
      const { tool: tl, temp: tp, shapes: sh } = st.current
      if (e.button !== undefined && e.button !== 0) return
      if (tl === 'cursor') {                                  // tap a drawing to select it
        const r = ref.current, c = cv.current
        if (!r || !c || st.current.hideDraw) return
        const [x, y, rc] = local(e)
        const i = hitTest(x, y, rc.width - r.chart.priceScale('right').width(), r.chart, r.main, sh, c.getContext('2d'))
        setSel(i)
        return
      }
      const pt = at(e)
      if (!pt) return
      e.preventDefault(); e.stopPropagation()
      const need = TOOL[tl].need
      const P = { t: pt.t, f: pt.f, v: pt.v }
      if (need === -1) { drag = { k: tl, p: [P] }; setTemp(drag); el.setPointerCapture?.(e.pointerId); return }
      if (tl === 'text') { const [x, y] = local(e); setTextAt({ x, y, p: P }); return }
      if (need === 1) { finish([...sh, { k: tl, p: [P] }]); return }
      if (need === 0) {                                       // path: tap point after point; tap the last point again (or Enter) to finish
        const fx = tp?.fixed || []
        if (fx.length >= 2) {
          const last = fx[fx.length - 1]
          if (last.t === P.t && Math.abs(last.v - P.v) / Math.max(1, Math.abs(P.v)) < 0.004) { finish([...sh, { k: 'path', p: fx }]); return }
        }
        setTemp({ k: 'path', fixed: [...fx, P], p: [...fx, P] }); return
      }
      if (!tp) { setTemp({ k: tl, fixed: [P], p: [P], i0: pt.i }); return }
      const pts = [...tp.fixed, P]
      if (pts.length >= need) finish([...sh, { k: tl, p: pts.slice(0, need), bars: Math.abs(pt.i - (tp.i0 ?? pt.i)) }])
      else setTemp({ ...tp, fixed: pts, p: pts })
    }
    const move = (e) => {
      const { temp: tp, tool: tl } = st.current
      if (drag) { const pt = at(e); if (pt) { drag = { ...drag, p: [...drag.p, { t: pt.t, f: pt.f, v: pt.v }] }; setTemp(drag) } e.preventDefault(); e.stopPropagation(); return }
      if (!tp || tl === 'cursor' || !tp.fixed) return
      const pt = at(e)
      if (pt) setTemp({ ...tp, p: [...tp.fixed, { t: pt.t, f: pt.f, v: pt.v }] })
    }
    const up = () => {
      if (!drag) return
      const done = drag; drag = null
      if (done.p.length > 1) finish([...st.current.shapes, done]); else { setTemp(null) }
    }
    el.addEventListener('pointerdown', down, true)
    el.addEventListener('pointermove', move, true)
    el.addEventListener('pointerup', up, true)
    el.addEventListener('pointercancel', up, true)
    return () => { el.removeEventListener('pointerdown', down, true); el.removeEventListener('pointermove', move, true); el.removeEventListener('pointerup', up, true); el.removeEventListener('pointercancel', up, true) }
  }, [sym, frame]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const k = (e) => {
      if (e.target.tagName === 'INPUT') return
      const { temp: tp, sel: sl, shapes: sh } = st.current
      if (e.key === 'Escape') { setTemp(null); setTool('cursor'); setSel(-1); setFly(null) }
      if (e.key === 'Enter' && tp?.k === 'path' && tp.fixed?.length >= 2) { setShapes([...sh, { k: 'path', p: tp.fixed }]); setTemp(null); setTool('cursor') }
      if ((e.key === 'Delete' || e.key === 'Backspace') && sl >= 0) { setShapes(sh.filter((_, i) => i !== sl)); setSel(-1) }
    }
    window.addEventListener('keydown', k); return () => window.removeEventListener('keydown', k)
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const shot = () => {
    const c = ref.current?.chart.takeScreenshot(true)
    if (!c) return
    const a = document.createElement('a'); a.href = c.toDataURL('image/png'); a.download = `${sym.replace('US:', '')}_${frame}.png`; a.click()
  }
  const last = d?.bars?.length ? { ...d.bars[d.bars.length - 1], prev: d.bars.length > 1 ? d.bars[d.bars.length - 2].c : d.prev } : null
  const Lg = leg || last
  const ch = Lg && ok(Lg.prev) ? Lg.c - Lg.prev : null
  const exch = isUSs(sym) ? (isIdx(sym) ? 'US index' : 'US') : isIdx(sym) ? 'NSE index' : 'NSE'
  const f2 = (v) => (ok(v) ? num(v, 2) : '—')
  const active = INDICATORS.filter((x) => ind[x.id] && x.id !== 'vol' && !(x.intraday && daily))
  const hint = tool === 'cursor' ? null : TOOL[tool].need === -1 ? `${TOOL[tool].label} · drag on the chart · Esc to cancel`
    : tool === 'path' ? `Path · tap each point; tap the last point again (or Enter) to finish · Esc to cancel`
      : temp ? `Tap point ${(temp.fixed?.length || 0) + 1} of ${TOOL[tool].need} · Esc to cancel` : `${TOOL[tool].label} · tap the chart · Esc to cancel`
  const commitText = (t) => { if (t && textAt) setShapes([...shapes, { k: 'text', p: [textAt.p], text: t }]); setTextAt(null); setTool('cursor') }
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
        <button className={`tv-btn ${picker ? 'on' : ''}`} onClick={() => setPicker(true)}>
          <svg viewBox="0 0 24 24" className="tv-ic"><path d="M3 18l5-7 4 4 6-9M17 6h3v3" /></svg> Indicators{active.length ? ` · ${active.length}` : ''}</button>
        <button hidden={!onAlert} className="tv-btn" onClick={onAlert} title="Price alert"><svg viewBox="0 0 24 24" className="tv-ic"><path d="M6 17h12l-1.5-2V11a4.5 4.5 0 0 0-9 0v4zM10 20h4" /></svg> Alert</button>
        <span className="grow" />
        <button className="tv-btn" title="Fit all candles" onClick={() => ref.current?.chart.timeScale().fitContent()}><svg viewBox="0 0 24 24" className="tv-ic"><path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5" /></svg></button>
        <button className="tv-btn" title="Save a picture of the chart" onClick={shot}><svg viewBox="0 0 24 24" className="tv-ic"><rect x="3" y="7" width="18" height="13" rx="2" /><circle cx="12" cy="13.5" r="3.5" /><path d="M8 7l2-3h4l2 3" /></svg></button>
        <button className={`tv-btn ${expanded ? 'on' : ''}`} title={expanded ? 'Normal size' : 'Bigger chart'} onClick={() => setExpanded(!expanded)}><svg viewBox="0 0 24 24" className="tv-ic">{expanded ? <path d="M9 4v5H4M15 4v5h5M9 20v-5H4M15 20v-5h5" /> : <path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5M9 9l-4-4M15 9l4-4M9 15l-4 4M15 15l4 4" />}</svg></button>
      </div>
      <div className="tv-body">
        <div className="tv-tools">
          <button title="Crosshair · tap a drawing to select it" className={tool === 'cursor' ? 'on' : ''} onClick={() => pickTool('cursor')}><svg viewBox="0 0 24 24"><path d="M12 3v18M3 12h18" /></svg></button>
          {TOOL_GROUPS.map((g) => {
            const cur = TOOL[lastOf[g.key]] || TOOL[g.tools[0][0]]
            const on = TOOL[tool]?.group === g.key
            return (
              <div key={g.key} className="tv-grp">
                <button title={`${g.label} · ${cur.label}`} className={on ? 'on' : ''} onClick={() => (g.tools.length === 1 ? pickTool(cur.k) : setFly(fly === g.key ? null : g.key))}>
                  <svg viewBox="0 0 24 24">{(on ? TOOL[tool] : cur).icon}</svg>{g.tools.length > 1 && <i className="tv-more" />}
                </button>
                {fly === g.key && (
                  <div className="tv-fly">
                    <div className="small muted" style={{ padding: '2px 8px 6px' }}>{g.label}</div>
                    {g.tools.map(([k, label, , icon]) => <button key={k} className={tool === k ? 'on' : ''} onClick={() => pickTool(k)}><svg viewBox="0 0 24 24">{icon}</svg><span>{label}</span></button>)}
                  </div>
                )}
              </div>
            )
          })}
          <span className="tv-tsep" />
          <button title={magnet ? 'Magnet on: points snap to the candle open, high, low or close' : 'Magnet off'} className={magnet ? 'on' : ''} onClick={() => { setMagnet(!magnet); saveJ('eql_magnet', !magnet) }}><svg viewBox="0 0 24 24"><path d="M6 4v8a6 6 0 0 0 12 0V4h-4v8a2 2 0 0 1-4 0V4zM6 8h4M14 8h4" /></svg></button>
          <button title="Undo last drawing" onClick={() => setShapes(shapes.slice(0, -1))} disabled={!shapes.length}><svg viewBox="0 0 24 24"><path d="M9 14L4 9l5-5M4 9h11a5 5 0 0 1 0 10h-3" /></svg></button>
          <button title={hideDraw ? 'Show drawings' : 'Hide drawings'} className={hideDraw ? 'on' : ''} onClick={() => setHideDraw(!hideDraw)}><svg viewBox="0 0 24 24"><path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6S2 12 2 12z" /><circle cx="12" cy="12" r="2.5" />{hideDraw && <path d="M4 4l16 16" />}</svg></button>
          <button title={sel >= 0 ? 'Delete the selected drawing' : 'Remove all drawings on this symbol'} className={sel >= 0 ? 'on' : ''} onClick={() => { if (sel >= 0) { setShapes(shapes.filter((_, i) => i !== sel)); setSel(-1) } else if (shapes.length && window.confirm?.('Remove every drawing on this symbol?') !== false) setShapes([]) }} disabled={!shapes.length}><svg viewBox="0 0 24 24"><path d="M5 7h14M10 7V4h4v3M7 7l1 13h8l1-13" /></svg></button>
        </div>
        <div className="tv-wrap" style={{ cursor: tool === 'cursor' ? 'default' : 'crosshair', touchAction: tool === 'cursor' ? 'auto' : 'none' }} onClick={() => fly && setFly(null)}>
          <div ref={box} className={`tv-chart ${expanded ? 'big' : ''}`} />
          <canvas ref={cv} className="tv-draw" />
          {textAt && (
            <input className="tv-textin" autoFocus placeholder="Type, then Enter" style={{ left: textAt.x, top: textAt.y - 14 }}
              onKeyDown={(e) => { if (e.key === 'Enter') commitText(e.currentTarget.value.trim()); if (e.key === 'Escape') { setTextAt(null); setTool('cursor') } }}
              onBlur={(e) => commitText(e.currentTarget.value.trim())} />
          )}
          {lab && (
            <div className="tv-last" style={{ top: lab.y - (lab.left ? 17 : 10), width: lab.w, background: lab.up ? UP : DOWN }}>
              <b>{num(lab.price, 2)}</b>{lab.left ? <span>{mmss(lab.left)}</span> : null}
            </div>
          )}
          <div className="tv-legend">
            <div className="t1"><b>{US_NAMES[sym] || name || sym.replace('US:', '')}</b> · {FRAME_LABEL[frame]} · {exch}</div>
            {Lg && <div className="t2">O<span style={{ color: tone(Lg.c - Lg.o) }}>{f2(Lg.o)}</span> H<span style={{ color: tone(Lg.c - Lg.o) }}>{f2(Lg.h)}</span> L<span style={{ color: tone(Lg.c - Lg.o) }}>{f2(Lg.l)}</span> C<span style={{ color: tone(Lg.c - Lg.o) }}>{f2(Lg.c)}</span>
              {ok(ch) && <span style={{ color: tone(ch) }}> {signed(ch, 2)} ({signed((ch / Lg.prev) * 100, 2, '%')})</span>}
              {Lg.v > 0 && ind.vol && <span className="muted"> · Vol {big(Lg.v)}</span>}</div>}
            {active.length > 0 && <div className="t3">{active.map((x) => <span key={x.id} className="tv-ichip" style={{ color: x.lines[0]?.color || 'var(--muted)' }}>{x.short}<button onClick={() => toggleInd(x.id)} title={`Remove ${x.name}`}>✕</button></span>)}</div>}
            {hint && <div className="t4">{hint}{tool === 'path' && temp?.fixed?.length >= 2 && <button className="tv-done" onClick={() => { setShapes([...shapes, { k: 'path', p: temp.fixed }]); setTemp(null); setTool('cursor') }}>Done</button>}</div>}
            {sel >= 0 && tool === 'cursor' && <div className="t4">Drawing selected · <button className="tv-done" onClick={() => { setShapes(shapes.filter((_, i) => i !== sel)); setSel(-1) }}>Delete it</button></div>}
          </div>
        </div>
      </div>
      {picker && <IndicatorPicker on={ind} onToggle={toggleInd} onClose={() => setPicker(false)} intraday={!daily} />}
      <div className="small muted term-src src-note">{err ? <span style={{ color: 'var(--bad)' }}>{err}</span> : d ? `${d.source} · ${d.yahoo}${pivotCaption(d)}${ind.vwap && !daily ? ' · VWAP from these candles' : ''}${ind.ichimoku ? ' · Ichimoku spans are not drawn beyond the last candle' : ''}` : 'Loading candles…'}</div>
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
        {ok(c.straddle) && <span className="chip ipo-on" title="ATM Call + ATM Put premium">ATM Straddle <b>{num(c.straddle, 2)}</b>{ok(c.expected_move_pct) ? ` · ±${num(c.expected_move_pct, 2)}%` : ''}</span>}
        <span className="chip">Call OI <b>{big(c.ce_oi)}</b></span><span className="chip">Put OI <b>{big(c.pe_oi)}</b></span>
        <span className="small muted">{c.time ? `as of ${c.time}` : ''}<span className="src-note"> · NSE</span></span>
      </div>
      <div className="term-oc-grid">
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
      {rows.length > 0 && (
        <div className="term-oc-charts">
          <div className="tile">
            <div className="k" style={{ marginBottom: 6 }}>OI Change by Strike (Call vs Put)</div>
            <ResponsiveContainer width="100%" height={180}>
              <BarChart data={rows.map((r) => ({ k: r.strike, call: r.ce_oi_chg || 0, put: r.pe_oi_chg || 0 }))}>
                <CartesianGrid stroke="var(--grid)" strokeDasharray="3 3" />
                <XAxis dataKey="k" stroke="var(--muted)" fontSize={10} />
                <YAxis stroke="var(--muted)" fontSize={10} width={42} />
                <Tooltip contentStyle={{ background: 'var(--card)', border: '1px solid var(--line)', borderRadius: 8, fontSize: 12 }} />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <Bar dataKey="put" name="Put OI Chg" fill="#22c55e" radius={[3, 3, 0, 0]} />
                <Bar dataKey="call" name="Call OI Chg" fill="#ef4444" radius={[3, 3, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <div className="tile" style={{ marginTop: 10 }}>
            <div className="k" style={{ marginBottom: 6 }}>Implied Volatility Skew (%)</div>
            <ResponsiveContainer width="100%" height={150}>
              <LineChart data={rows.filter((r) => ok(r.ce_iv) || ok(r.pe_iv)).map((r) => ({ k: r.strike, ce_iv: r.ce_iv, pe_iv: r.pe_iv }))}>
                <CartesianGrid stroke="var(--grid)" strokeDasharray="3 3" />
                <XAxis dataKey="k" stroke="var(--muted)" fontSize={10} />
                <YAxis stroke="var(--muted)" fontSize={10} width={34} />
                <Tooltip contentStyle={{ background: 'var(--card)', border: '1px solid var(--line)', borderRadius: 8, fontSize: 12 }} />
                <Line type="monotone" dataKey="ce_iv" name="Call IV" stroke="#2dd4bf" strokeWidth={2} dot={false} />
                <Line type="monotone" dataKey="pe_iv" name="Put IV" stroke="#38bdf8" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}
      </div>
      <div className="small muted" style={{ marginTop: 6 }}>Shaded = in the money. OI = open interest (contracts as NSE reports them). PCR, straddle and max pain are worked out from NSE's open interest.</div>
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
  const [tg, setTg] = useState(true)
  const add = async (dir) => {
    const v = parseFloat(p)
    if (!v) return
    const item = { id: Date.now(), sym, dir, price: v, telegram: tg }
    setAlerts([...alerts, item])
    setP('')
    try {
      const r = await api('/api/alerts/price', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ sym, dir, price: v, telegram: tg }) })
      if (r?.items) setAlerts(r.items)
    } catch { /* offline / member */ }
  }
  const drop = async (id) => {
    setAlerts(alerts.filter((x) => x.id !== id))
    try { await api(`/api/alerts/price/${id}`, { method: 'DELETE' }) } catch { /* ignore */ }
  }
  return (
    <div>
      <div className="row wrapflex" style={{ gap: 8 }}>
        <input type="number" placeholder={ok(head?.ltp) ? `e.g. ${num(head.ltp, 0)}` : 'price'} value={p} onChange={(e) => setP(e.target.value)} style={{ width: 140 }} />
        <button className="btn small" onClick={() => add('above')}>Alert when {sym} goes above</button>
        <button className="btn small" onClick={() => add('below')}>…goes below</button>
        <label className="row small muted" style={{ gap: 5, cursor: 'pointer' }}><input type="checkbox" checked={tg} onChange={(e) => setTg(e.target.checked)} /> Notify via Telegram even when closed</label>
      </div>
      <div style={{ marginTop: 10 }}>
        {alerts.length === 0 ? <div className="small muted">No alerts. Active price alerts sound here and dispatch via Telegram (when enabled in Settings).</div>
          : alerts.map((a) => (
            <div key={a.id} className="term-r"><span>{a.sym} {a.dir} {num(a.price, 2)}{a.telegram ? ' · 📨' : ''}{a.hit ? ` · hit ${a.hit}` : ''}</span><button className="chip" onClick={() => drop(a.id)}>remove</button></div>
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
    const synced = loadJ('eql_term_watch_v2', null)
    if (synced?.[mk]?.length) return synced[mk]
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
  const [sseOn, setSseOn] = useState(false)
  const [alerts, setAlertsRaw] = useState(() => loadJ('eql_term_alerts', []))
  const setAlerts = (a) => { setAlertsRaw(a); saveLocal('eql_term_alerts', a) }
  const nse = !isUSs(sym) && !isIdx(sym)
  const live = mk === 'US' ? usOpen() : nseOpen()
  useEffect(() => {
    saveJ(LS, watch)
    const all = loadJ('eql_term_watch_v2', {})
    saveLocal('eql_term_watch_v2', { ...all, [mk]: watch })
  }, [watch, mk, LS])
  useEffect(() => { api('/api/alerts/price').then((r) => { if (r?.items?.length) setAlerts(r.items) }).catch(() => {}) }, []) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { setNseq(null); setYq(null) }, [sym])
  useEffect(() => {
    let alive = true, es = null, timer = null
    const fetchOnce = () => {
      if (!alive || document.hidden) return
      if (nse) api(`/api/term/stock/${encodeURIComponent(sym)}`).then((x) => alive && setNseq(x)).catch(() => {})
      api(`/api/term/candles/${encodeURIComponent(sym)}?frame=5m`).then((x) => alive && setYq(x)).catch(() => {})
    }
    fetchOnce()
    if (live && typeof EventSource !== 'undefined') {
      try {
        es = new EventSource(`/api/stream/terminal/${encodeURIComponent(sym)}?frame=5m&nse=${nse}`)
        es.onopen = () => alive && setSseOn(true)
        es.onmessage = (e) => {
          if (!alive) return
          try {
            const p = JSON.parse(e.data)
            if (p.stock) setNseq(p.stock)
            if (p.candles) setYq(p.candles)
          } catch { /* ignore */ }
        }
        es.onerror = () => {
          if (!alive) return
          setSseOn(false)
          es?.close()
          if (!timer) timer = setInterval(fetchOnce, 3000)
        }
      } catch {
        timer = setInterval(fetchOnce, 3000)
      }
    } else {
      setSseOn(false)
      timer = setInterval(fetchOnce, live ? 3000 : 60000)
    }
    return () => { alive = false; setSseOn(false); es?.close(); clearInterval(timer) }
  }, [sym, live, nse])
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
          <span className={`ipo-cd ${live ? 'warm' : ''}`}>{sseOn ? '● Live Stream (SSE)' : mk === 'US' ? (live ? '🟢 US market open' : 'US market closed · last prices') : live ? '🟢 NSE open · live every 3 s' : 'NSE closed · last prices'}</span>
          {head?.time && <span className="small muted">as of {head.time}<span className="src-note"> ({head.src})</span></span>}
        </div>
        <button className="btn small" onClick={goAlerts}>🔔 Quick Alert</button>
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
