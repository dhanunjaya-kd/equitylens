import { useEffect, useMemo, useRef, useState } from 'react'
import {
  CandlestickSeries, ColorType, CrosshairMode, HistogramSeries, LineSeries, LineStyle, createChart, createSeriesMarkers,
} from 'lightweight-charts'
import { Badge, Loading, Tile } from '../components/ui'
import { api, cssVar, isDesktop, num, ok, pct, rs, signed } from '../util'
import { Md } from './AI'

const COL = {
  up: '#22c55e', down: '#ef4444', ema20: '#38bdf8', ema50: '#f59e0b', ema200: '#e879f9', bb: '#64748b',
  st_up: '#22c55e', st_dn: '#ef4444', rsi: '#a78bfa', macd: '#38bdf8', sig: '#f59e0b', adx: 'var(--text)', pdi: '#22c55e', mdi: '#ef4444',
  grid: '#1a2531', text: '#8b98a5',
}
const OVERLAYS = [['cone', 'Future range'], ['ema20', 'EMA 20'], ['ema50', 'EMA 50'], ['ema200', 'EMA 200'], ['bb', 'Bollinger'], ['st', 'Supertrend'], ['levels', 'Support/Resistance'], ['cross', 'Crosses']]
const PANES = [['vol', 'Volume'], ['rsi', 'RSI'], ['macd', 'MACD'], ['adx', 'ADX']]
const RANGES = { '1d': [['3M', 63], ['6M', 126], ['1Y', 252], ['3Y', 756], ['5Y', 1300]], '1wk': [['1Y', 52], ['3Y', 156], ['5Y', 260], ['10Y', 530]] }
const load = (k, d) => { try { return JSON.parse(localStorage.getItem(k)) ?? d } catch { return d } }
const save = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)) } catch { /* ignore */ } }

export default function StockChart({ symbol }) {
  const [interval, setInterval_] = useState('1d')
  const [data, setData] = useState(null)
  const [err, setErr] = useState(null)
  const [over, setOver] = useState(() => load('eql_over2', { cone: true, ema20: true, ema50: true, ema200: true, bb: false, st: false, levels: true, cross: true }))
  const [panes, setPanes] = useState(() => load('eql_panes', { vol: true, rsi: true, macd: true, adx: false }))
  const [range, setRange] = useState('1Y')
  const [legend, setLegend] = useState(null)
  const box = useRef()

  useEffect(() => {
    setData(null); setErr(null)
    api(`/api/chart/${encodeURIComponent(symbol)}?interval=${interval}`).then(setData).catch((e) => setErr(e.message))
  }, [symbol, interval])
  useEffect(() => save('eql_over2', over), [over])
  useEffect(() => save('eql_panes', panes), [panes])

  const rows = useMemo(() => {
    if (!data) return null
    const mk = (key) => data.t.map((t, i) => (data[key][i] === null ? { time: t } : { time: t, value: data[key][i] }))
    return { mk }
  }, [data])

  useEffect(() => {
    if (!data || !box.current) return
    const d = data
    const line = cssVar('--line'), card = cssVar('--card'), muted = cssVar('--muted'), text = cssVar('--text')
    const chart = createChart(box.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: card }, textColor: muted, fontSize: 11, attributionLogo: false,
        panes: { separatorColor: line, separatorHoverColor: '#2dd4bf33' } },
      grid: { vertLines: { color: cssVar('--grid') }, horzLines: { color: cssVar('--grid') } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: line },
      timeScale: { borderColor: line, rightOffset: 4 },
    })
    const L = (pane, color, key, extra = {}) => {
      const s = chart.addSeries(LineSeries, { color, lineWidth: 1.5, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false, ...extra }, pane)
      s.setData(rows.mk(key)); return s
    }

    // ---- main pane
    let main
    if (d.ohlc) {
      main = chart.addSeries(CandlestickSeries, { upColor: COL.up, downColor: COL.down, borderVisible: false, wickUpColor: COL.up, wickDownColor: COL.down }, 0)
      main.setData(d.t.map((t, i) => ({ time: t, open: d.o[i], high: d.h[i], low: d.l[i], close: d.c[i] })))
    } else {
      main = chart.addSeries(LineSeries, { color: '#2dd4bf', lineWidth: 2 }, 0)
      main.setData(d.t.map((t, i) => ({ time: t, value: d.c[i] })))
    }
    if (over.ema20) L(0, COL.ema20, 'ema20')
    if (over.ema50) L(0, COL.ema50, 'ema50')
    if (over.ema200) L(0, COL.ema200, 'ema200', { lineWidth: 2 })
    if (over.bb) { L(0, COL.bb, 'bb_up', { lineStyle: LineStyle.Dashed }); L(0, COL.bb, 'bb_lo', { lineStyle: LineStyle.Dashed }) }
    if (over.st && d.ohlc) {
      const up = chart.addSeries(LineSeries, { color: COL.st_up, lineWidth: 2, priceLineVisible: false, lastValueVisible: false }, 0)
      const dn = chart.addSeries(LineSeries, { color: COL.st_dn, lineWidth: 2, priceLineVisible: false, lastValueVisible: false }, 0)
      up.setData(d.t.map((t, i) => (d.st_trend[i] === 1 && d.st[i] !== null ? { time: t, value: d.st[i] } : { time: t })))
      dn.setData(d.t.map((t, i) => (d.st_trend[i] === -1 && d.st[i] !== null ? { time: t, value: d.st[i] } : { time: t })))
    }
    if (over.cone && d.outlook?.cone_points?.length) {
      const last = { time: d.t[d.t.length - 1], value: d.c[d.c.length - 1] }
      const opt = { lineWidth: 1.5, lineStyle: LineStyle.Dashed, priceLineVisible: false, lastValueVisible: true, crosshairMarkerVisible: false }
      chart.addSeries(LineSeries, { ...opt, color: '#22c55e', title: '80% high' }, 0).setData([last, ...d.outlook.cone_points.map((p) => ({ time: p.t, value: p.hi }))])
      chart.addSeries(LineSeries, { ...opt, color: '#ef4444', title: '80% low' }, 0).setData([last, ...d.outlook.cone_points.map((p) => ({ time: p.t, value: p.lo }))])
    }
    if (over.levels) {
      d.levels.resistance.forEach((p) => main.createPriceLine({ price: p, color: '#ef444499', lineStyle: LineStyle.Dotted, lineWidth: 1, axisLabelVisible: true, title: 'R' }))
      d.levels.support.forEach((p) => main.createPriceLine({ price: p, color: '#22c55e99', lineStyle: LineStyle.Dotted, lineWidth: 1, axisLabelVisible: true, title: 'S' }))
    }
    if (over.cross && d.markers.length) {
      createSeriesMarkers(main, d.markers.map((m) => ({
        time: m.t, position: m.kind === 'golden' ? 'belowBar' : 'aboveBar', color: m.kind === 'golden' ? '#fbbf24' : '#f472b6',
        shape: m.kind === 'golden' ? 'arrowUp' : 'arrowDown', text: m.kind === 'golden' ? 'GC' : 'DC',
      })))
    }
    if (panes.vol) {
      const vol = chart.addSeries(HistogramSeries, { priceScaleId: 'vol', priceFormat: { type: 'volume' }, lastValueVisible: false, priceLineVisible: false }, 0)
      vol.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } })
      main.priceScale().applyOptions({ scaleMargins: { top: 0.06, bottom: 0.22 } })
      vol.setData(d.t.map((t, i) => ({ time: t, value: d.v[i], color: d.c[i] >= (d.o[i] ?? d.c[i - 1] ?? 0) ? '#22c55e55' : '#ef444455' })))
    }
    // ---- lower panes
    let pane = 1
    const used = []
    if (panes.rsi) {
      const r = L(pane, COL.rsi, 'rsi', { lineWidth: 1.5, lastValueVisible: true })
      ;[[70, '#ef4444aa'], [50, '#64748b77'], [30, '#22c55eaa']].forEach(([p, c]) => r.createPriceLine({ price: p, color: c, lineStyle: LineStyle.Dashed, lineWidth: 1, axisLabelVisible: false }))
      used.push(pane++)
    }
    if (panes.macd) {
      const h = chart.addSeries(HistogramSeries, { priceLineVisible: false, lastValueVisible: false }, pane)
      h.setData(d.t.map((t, i) => (d.macd_hist[i] === null ? { time: t } : {
        time: t, value: d.macd_hist[i],
        color: d.macd_hist[i] >= 0 ? (d.macd_hist[i] >= (d.macd_hist[i - 1] ?? 0) ? '#22c55e' : '#22c55e77') : (d.macd_hist[i] <= (d.macd_hist[i - 1] ?? 0) ? '#ef4444' : '#ef444477'),
      })))
      L(pane, COL.macd, 'macd'); L(pane, COL.sig, 'macd_signal')
      used.push(pane++)
    }
    if (panes.adx && d.ohlc) {
      const a = L(pane, text, 'adx', { lineWidth: 2, lastValueVisible: true })
      L(pane, COL.pdi, 'pdi'); L(pane, COL.mdi, 'mdi')
      a.createPriceLine({ price: 25, color: '#64748b', lineStyle: LineStyle.Dashed, lineWidth: 1, axisLabelVisible: false })
      used.push(pane++)
    }
    const ps = chart.panes()
    if (ps[0]) ps[0].setStretchFactor(3.2)
    used.forEach((p) => ps[p] && ps[p].setStretchFactor(1))

    // ---- visible range
    const n = (RANGES[interval].find((r) => r[0] === range) || RANGES[interval][2])[1]
    const from = d.t[Math.max(d.t.length - n, 0)]
    const to = over.cone && d.outlook?.cone_points?.length ? d.outlook.cone_points[Math.min(d.outlook.cone_points.length - 1, Math.round(n / 3))].t : d.t[d.t.length - 1]
    chart.timeScale().setVisibleRange({ from, to })

    // ---- legend on hover
    const idx = Object.fromEntries(d.t.map((t, i) => [t, i]))
    const show = (i) => setLegend({ i })
    show(d.t.length - 1)
    chart.subscribeCrosshairMove((p) => {
      if (!p || !p.time) { show(d.t.length - 1); return }
      const key = typeof p.time === 'string' ? p.time : `${p.time.year}-${String(p.time.month).padStart(2, '0')}-${String(p.time.day).padStart(2, '0')}`
      if (idx[key] !== undefined) show(idx[key])
    })
    return () => chart.remove()
  }, [data, rows, over, panes, range, interval])

  if (err) return <div className="card empty">Chart unavailable: {err}</div>
  if (!data) return <Loading text="Loading price history…" />
  const s = data.summary, st = data.stats
  const i = legend?.i ?? data.t.length - 1
  const extra = 3.2 + ['rsi', 'macd', 'adx'].filter((k) => panes[k] && (k !== 'adx' || data.ohlc)).length
  const height = Math.round(((isDesktop() ? 520 : 330) / 3.2) * extra)

  return (
    <>
      <div className="card">
        <div className="row between">
          <div><div className="small muted">Technical view ({interval === '1d' ? 'daily' : 'weekly'})</div>
            <Badge tone={s.tone}>{s.label}</Badge></div>
          <div className="small" style={{ textAlign: 'right' }}><span className="t-good">{s.bullish} bullish</span> · <span className="t-bad">{s.bearish} bearish</span></div>
        </div>
        <div className="grid3" style={{ marginTop: 10 }}>
          <Tile k="Last close" v={rs(st.last, 2)} s={`${signed(st.change_1d, 2, '%')} · ${st.date}`} color={st.change_1d >= 0 ? 'var(--good)' : 'var(--bad)'} />
          <Tile k="1M · 6M · 1Y" v={<span style={{ fontSize: 14 }}>{signed(st.ret_1m, 0, '%')} · {signed(st.ret_6m, 0, '%')} · {signed(st.ret_1y, 0, '%')}</span>} />
          <Tile k="ATR (volatility)" v={pct(st.atr_pct, 1)} s={st.atr ? `≈ ${rs(st.atr, 1)} a day` : 'needs OHLC'} />
        </div>
      </div>

      <div className="card" style={{ padding: 10 }}>
        <div className="row between wrapflex" style={{ gap: 6, marginBottom: 8 }}>
          <div className="row" style={{ gap: 4 }}>
            {[['1d', 'Daily'], ['1wk', 'Weekly']].map(([k, l]) => (
              <button key={k} className={`tab ${interval === k ? 'on' : ''}`} style={{ padding: '6px 11px' }}
                onClick={() => { setInterval_(k); setRange(k === '1d' ? '1Y' : '5Y') }}>{l}</button>))}
          </div>
          <div className="row" style={{ gap: 4 }}>
            {RANGES[interval].map(([l]) => <button key={l} className={`tab ${range === l ? 'on' : ''}`} style={{ padding: '6px 9px' }} onClick={() => setRange(l)}>{l}</button>)}
          </div>
        </div>
        <Legend d={data} i={i} over={over} panes={panes} />
        <div ref={box} style={{ height, width: '100%', borderRadius: 10, overflow: 'hidden' }} />
        <div style={{ marginTop: 8 }}>
          {OVERLAYS.map(([k, l]) => (k === 'st' && !data.ohlc) ? null : (
            <span key={k} className="chip" style={{ cursor: 'pointer', color: over[k] ? 'var(--accent)' : null, borderColor: over[k] ? 'var(--accent)' : null }}
              onClick={() => setOver({ ...over, [k]: !over[k] })}>{over[k] ? '✓ ' : ''}{l}</span>))}
          {PANES.map(([k, l]) => (k === 'adx' && !data.ohlc) ? null : (
            <span key={k} className="chip" style={{ cursor: 'pointer', color: panes[k] ? 'var(--accent)' : null, borderColor: panes[k] ? 'var(--accent)' : null }}
              onClick={() => setPanes({ ...panes, [k]: !panes[k] })}>{panes[k] ? '✓ ' : ''}{l}</span>))}
        </div>
        <div className="small muted">Source: {data.source}{!data.ohlc && ' — closes only, so candles, Supertrend and ADX are off'}. Tap a chip to show/hide.</div>
      </div>

      <div className="flow">
      {data.outlook && <ChartOutlook o={data.outlook} symbol={symbol} interval={interval} last={st.last} />}

      <div className="grid-auto in-flow">
        <div className="card">
          <h3>Signal checklist</h3>
          <ul className="list">
            {s.checks.map((c) => (
              <li key={c.name}><span className={`ic ${c.state === 1 ? 't-good' : c.state === -1 ? 't-bad' : 't-neutral'}`}>{c.state === 1 ? '▲' : c.state === -1 ? '▼' : '•'}</span>
                <b>{c.name}</b><div className="small muted">{c.detail}</div></li>
            ))}
          </ul>
        </div>
        <div className="card">
          <h3>Key levels</h3>
          <div className="grid2">
            <div><h4 style={{ marginTop: 0 }}>Resistance</h4>{data.levels.resistance.length ? data.levels.resistance.map((p) => <div key={p} className="t-bad"><b>{rs(p, 1)}</b> <span className="small muted">{signed((p / st.last - 1) * 100, 1, '%')}</span></div>) : <div className="small muted">At highs</div>}</div>
            <div><h4 style={{ marginTop: 0 }}>Support</h4>{data.levels.support.length ? data.levels.support.map((p) => <div key={p} className="t-good"><b>{rs(p, 1)}</b> <span className="small muted">{signed((p / st.last - 1) * 100, 1, '%')}</span></div>) : <div className="small muted">At lows</div>}</div>
          </div>
          <div className="small muted" style={{ marginTop: 8 }}>52-week range {rs(st.low_52w)} – {rs(st.high_52w)}. Levels are recent swing highs and lows.</div>
          <h4>What the indicators mean</h4>
          <ul className="list small">
            <li><span className="ic" style={{ color: COL.ema200 }}>■</span><b>EMA 20/50/200:</b> short, medium and long-term trend. Price above a rising 200 EMA = long-term uptrend.</li>
            <li><span className="ic" style={{ color: '#fbbf24' }}>▲</span><b>Golden / death cross:</b> 50 EMA crossing above (GC) or below (DC) the 200 EMA.</li>
            <li><span className="ic" style={{ color: COL.rsi }}>■</span><b>RSI:</b> momentum 0–100. Above 70 stretched, below 30 washed out, above 50 bullish.</li>
            <li><span className="ic" style={{ color: COL.macd }}>■</span><b>MACD:</b> blue above orange = momentum turning up; growing green bars = strengthening.</li>
            <li><span className="ic" style={{ color: COL.adx }}>■</span><b>ADX:</b> trend strength. Above 25 = trending; green +DI vs red −DI shows who's winning.</li>
            <li><span className="ic" style={{ color: COL.st_up }}>■</span><b>Supertrend:</b> green line under price = buy mode, red above = sell mode.</li>
            <li><span className="ic" style={{ color: COL.bb }}>■</span><b>Bollinger:</b> 2 standard deviations around the 20-day average; squeezes often come before big moves.</li>
          </ul>
        </div>
      </div>
      </div>
      <p className="disclaimer">Technical signals describe price behaviour, not business value. For long-term investing, use them for timing entries, alongside the fundamentals.</p>
    </>
  )
}

function Legend({ d, i, over, panes }) {
  const v = (k) => (d[k] && ok(d[k][i]) ? d[k][i] : null)
  const chg = i > 0 ? (d.c[i] / d.c[i - 1] - 1) * 100 : null
  return (
    <div className="small" style={{ display: 'flex', flexWrap: 'wrap', gap: '2px 10px', marginBottom: 6, minHeight: 34 }}>
      <span className="muted">{d.t[i]}</span>
      {d.ohlc ? <span>O {num(v('o'), 1)} H {num(v('h'), 1)} L {num(v('l'), 1)} C <b>{num(v('c'), 1)}</b></span> : <span>Close <b>{num(v('c'), 1)}</b></span>}
      <span style={{ color: chg >= 0 ? 'var(--good)' : 'var(--bad)' }}>{signed(chg, 2, '%')}</span>
      {over.ema20 && <span style={{ color: COL.ema20 }}>EMA20 {num(v('ema20'), 1)}</span>}
      {over.ema50 && <span style={{ color: COL.ema50 }}>EMA50 {num(v('ema50'), 1)}</span>}
      {over.ema200 && <span style={{ color: COL.ema200 }}>EMA200 {num(v('ema200'), 1)}</span>}
      {panes.rsi && <span style={{ color: COL.rsi }}>RSI {num(v('rsi'), 1)}</span>}
      {panes.macd && <span style={{ color: COL.macd }}>MACD {num(v('macd'), 2)}</span>}
      {panes.adx && d.ohlc && <span>ADX {num(v('adx'), 1)}</span>}
    </div>
  )
}

// ====================================================================== future of the chart
function ChartOutlook({ o, symbol, interval, last }) {
  const [ai, setAi] = useState(null), [busy, setBusy] = useState(false), [err, setErr] = useState(null)
  const explain = async () => {
    setBusy(true); setErr(null)
    try { setAi(await api(`/api/ai/chart/${encodeURIComponent(symbol)}?interval=${interval}`, { method: 'POST' })) } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }
  const icon = { bull: '🟢', range: '🟡', bear: '🔴' }
  return (
    <>
      <div className="card">
        <h3>🔭 What the chart says about the coming months</h3>
        <ul className="list">
          {o.story.map((t, i) => <li key={i}><span className="ic" style={{ color: 'var(--accent)' }}>›</span>{t}</li>)}
        </ul>
      </div>

      <div className="card">
        <h3>🎯 If / then levels</h3>
        {o.scenarios.map((sc) => (
          <div key={sc.kind} className={`scen-card ${sc.kind}`}>
            <div><b>{icon[sc.kind]} {sc.title}</b></div>
            <div className="small" style={{ marginTop: 3, lineHeight: 1.45 }}>{sc.text}</div>
          </div>
        ))}
        <div className="small muted" style={{ marginTop: 8 }}>Conditions, not predictions: the chart only tells you which level decides the next move.</div>
      </div>

      {o.cone?.length > 0 && (
        <div className="card">
          <h3>📐 Likely price range (from its own volatility)</h3>
          <p className="small muted" style={{ marginTop: -4 }}>Annual volatility {o.volatility_annual}%. Assumes no direction: the dashed green/red lines on the chart show the 80% range.</p>
          {o.cone.map((c) => <RangeRow key={c.horizon} label={c.horizon} lo={c.low80} hi={c.high80} lo68={c.low68} hi68={c.high68} now={last} />)}
          <div className="small muted" style={{ marginTop: 6 }}>Dark band ≈ 2 in 3 chance · light band ≈ 4 in 5 chance, if volatility stays like the last year.</div>
        </div>
      )}

      {o.analogs && (
        <div className="card">
          <h3>📜 What happened after the same setup before</h3>
          <div style={{ marginBottom: 6 }}>{o.setup.map((x) => <span key={x} className="chip">{x}</span>)}</div>
          <div className="tbl-wrap">
            <table className="tbl">
              <thead><tr><th>After</th><th>Times</th><th>Went up</th><th>Median</th><th>Bad · Good (10–90%)</th><th>Any day: up</th></tr></thead>
              <tbody>{o.analogs.map((a) => (
                <tr key={a.horizon}>
                  <td><b>{a.horizon}</b></td><td>{a.count}</td>
                  <td style={{ color: a.pct_up >= a.all_pct_up ? 'var(--good)' : 'var(--bad)', fontWeight: 700 }}>{a.pct_up}%</td>
                  <td style={{ color: a.median >= 0 ? 'var(--good)' : 'var(--bad)' }}>{signed(a.median, 1, '%')}</td>
                  <td>{signed(a.p10, 0, '%')} · {signed(a.p90, 0, '%')}</td>
                  <td className="muted">{a.all_pct_up}%</td>
                </tr>))}
              </tbody>
            </table>
          </div>
          <div className="small muted" style={{ marginTop: 6 }}>Every past day this stock had the same trend and momentum setup ({o.setup_used.join(', ')}), and where it was later. Green = better than an average day. Past patterns can fail.</div>
        </div>
      )}

      <div className="card">
        <div className="row between"><h3 style={{ margin: 0 }}>✨ Explain this chart with AI</h3>
          <button className="btn small primary" disabled={busy} onClick={explain}>{ai ? '↻ Again' : 'Explain'}</button></div>
        {busy && <div className="small muted" style={{ marginTop: 8 }}>Reading the chart…</div>}
        {err && <div className="small t-bad" style={{ marginTop: 8 }}>⚠️ {err}</div>}
        {ai && <><Md text={ai.text} /><div className="small muted">{ai.model}</div></>}
      </div>
    </>
  )
}

function RangeRow({ label, lo, hi, lo68, hi68, now }) {
  const min = lo * 0.97, max = hi * 1.03
  const p = (v) => `${((v - min) / (max - min)) * 100}%`
  return (
    <div style={{ margin: '12px 0 18px' }}>
      <div className="row between small"><b>{label}</b><span className="muted">{rs(lo)} – {rs(hi)}</span></div>
      <div style={{ position: 'relative', height: 14, marginTop: 6 }}>
        <div style={{ position: 'absolute', inset: '4px 0', background: 'var(--card2)', borderRadius: 99 }} />
        <div style={{ position: 'absolute', top: 4, bottom: 4, left: p(lo), width: `calc(${p(hi)} - ${p(lo)})`, background: '#2dd4bf33', borderRadius: 99 }} />
        <div style={{ position: 'absolute', top: 2, bottom: 2, left: p(lo68), width: `calc(${p(hi68)} - ${p(lo68)})`, background: '#2dd4bf88', borderRadius: 99 }} />
        <div style={{ position: 'absolute', top: -2, bottom: -2, left: p(now), width: 3, background: 'var(--text)', transform: 'translateX(-50%)' }} />
      </div>
      <div className="row between small muted" style={{ marginTop: 2 }}><span>{signed((lo / now - 1) * 100, 0, '%')}</span><span>now {rs(now)}</span><span>{signed((hi / now - 1) * 100, 0, '%')}</span></div>
    </div>
  )
}
