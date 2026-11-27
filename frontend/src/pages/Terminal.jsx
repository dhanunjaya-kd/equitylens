import { useEffect, useMemo, useRef, useState } from 'react'
import { CandlestickSeries, ColorType, CrosshairMode, HistogramSeries, LineSeries, createChart } from 'lightweight-charts'
import { api, cssVar, num, ok, signed } from '../util'
import { chime } from '../components/BreakingBar'

// Live terminal: a screen, no orders. NSE stocks, index options, stock F&O, US stocks.
// Every panel shows the time its source stamped. A figure that fails a check is left out with the reason.
const LS = 'eql_term_watch'
const DEFAULT_WATCH = ['NIFTY', 'BANKNIFTY', 'RELIANCE', 'HDFCBANK', 'ICICIBANK', 'TCS', 'INFY', 'SBIN', 'US:AAPL', 'US:NVDA']
const INDEX = ['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY']
const FRAMES = ['1m', '5m', '15m', '1h', '1D']
const loadW = () => { try { return JSON.parse(localStorage.getItem(LS)) || DEFAULT_WATCH } catch { return DEFAULT_WATCH } }
const saveW = (w) => { try { localStorage.setItem(LS, JSON.stringify(w)) } catch { /* ignore */ } }
const isUSs = (s) => s.startsWith('US:')
const isIdx = (s) => INDEX.includes(s)
const ist = () => new Date(new Date().toLocaleString('en-US', { timeZone: 'Asia/Kolkata' }))
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

// ---------------------------------------------------------------- chart
function Chart({ sym, frame }) {
  const box = useRef()
  const chartRef = useRef(null)
  const [d, setD] = useState(null)
  const [err, setErr] = useState('')
  usePoll(() => api(`/api/term/candles/${encodeURIComponent(sym)}?frame=${frame}`).then((x) => { setD(x); setErr('') }).catch((e) => setErr(e.message)),
    frame === '1D' ? 300000 : 30000, [sym, frame])
  useEffect(() => {
    if (!box.current) return undefined
    const line = cssVar('--line'), card = cssVar('--card'), muted = cssVar('--muted')
    const chart = createChart(box.current, {
      autoSize: true, layout: { background: { type: ColorType.Solid, color: card }, textColor: muted, fontSize: 11, attributionLogo: false },
      grid: { vertLines: { color: cssVar('--grid') }, horzLines: { color: cssVar('--grid') } }, crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: line }, timeScale: { borderColor: line, timeVisible: true, secondsVisible: false, rightOffset: 3 },
    })
    const c = chart.addSeries(CandlestickSeries, { upColor: '#22c55e', downColor: '#ef4444', borderVisible: false, wickUpColor: '#22c55e', wickDownColor: '#ef4444' })
    const v = chart.addSeries(HistogramSeries, { priceScaleId: 'vol', priceFormat: { type: 'volume' }, lastValueVisible: false, priceLineVisible: false })
    v.priceScale().applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } })
    c.priceScale().applyOptions({ scaleMargins: { top: 0.06, bottom: 0.22 } })
    const w = chart.addSeries(LineSeries, { color: '#f59e0b', lineWidth: 1.5, priceLineVisible: false, lastValueVisible: true, title: 'VWAP', crosshairMarkerVisible: false })
    chartRef.current = { chart, c, v, w, fitted: false }
    return () => { chart.remove(); chartRef.current = null }
  }, [sym, frame])
  useEffect(() => {
    const r = chartRef.current
    if (!r || !d) return
    const off = d.offset || 0
    const t = (b) => b.t + off                                    // show exchange local time on the axis
    r.c.setData(d.bars.map((b) => ({ time: t(b), open: b.o, high: b.h, low: b.l, close: b.c })))
    r.v.setData(d.bars.map((b) => ({ time: t(b), value: b.v, color: b.c >= b.o ? '#22c55e55' : '#ef444455' })))
    r.w.setData(frame === '1D' ? [] : d.bars.map((b, i) => (ok(d.vwap[i]) ? { time: t(b), value: d.vwap[i] } : { time: t(b) })))
    if (!r.fitted) { r.chart.timeScale().fitContent(); r.fitted = true }
  }, [d, frame])
  return (
    <div className="term-chart-wrap">
      <div ref={box} className="term-chart" />
      <div className="small muted term-src">{err ? <span style={{ color: 'var(--bad)' }}>{err}</span> : d ? `${d.source} · ${d.yahoo}${frame !== '1D' ? ' · VWAP from these candles' : ''}` : 'Loading candles…'}</div>
    </div>
  )
}

// ---------------------------------------------------------------- right panel: quote + depth
function Row({ k, v, c }) { return <div className="term-r"><span>{k}</span><b style={c ? { color: c } : null}>{v}</b></div> }

function QuotePanel({ sym, live, onHead }) {
  const [d, setD] = useState(null)
  const nse = !isUSs(sym) && !isIdx(sym)
  usePoll(() => {
    if (nse) api(`/api/term/stock/${encodeURIComponent(sym)}`).then((x) => { setD(x); if (x.quote) onHead({ ltp: x.quote.ltp, change: x.quote.change, pchange: x.quote.pchange, name: x.quote.name, time: x.quote.time, src: 'NSE', fno: x.quote.fno }) }).catch(() => {})
    else api(`/api/term/candles/${encodeURIComponent(sym)}?frame=5m`).then((x) => { setD({ yq: x }); onHead({ ltp: x.price, change: x.change, pchange: x.pchange, name: x.name, time: x.time ? new Date(x.time * 1000).toLocaleTimeString('en-IN') : null, src: 'Yahoo', cur: x.currency }) }).catch(() => {})
  }, live ? 3000 : 60000, [sym, live])
  if (!d) return <div className="card term-panel small muted">Loading quote…</div>
  if (!nse) {
    const y = d.yq
    const bars = y?.bars || []
    const hi = bars.length ? Math.max(...bars.map((b) => b.h)) : null, lo = bars.length ? Math.min(...bars.map((b) => b.l)) : null
    const cur = y?.currency === 'USD' ? '$' : y?.currency === 'INR' ? '₹' : ''
    return (
      <div className="card term-panel">
        <h3>Quote</h3>
        <Row k="Price" v={px(y?.price, cur)} /><Row k="Previous close" v={px(y?.prev, cur)} />
        <Row k="Day high / low (from candles)" v={`${px(hi, cur)} / ${px(lo, cur)}`} />
        <div className="small muted" style={{ marginTop: 8 }}>{isIdx(sym) ? 'Index level from Yahoo. Futures and option chain below come from NSE.' : 'US prices from Yahoo. Market depth is not available from a free source for US stocks.'}</div>
      </div>
    )
  }
  const q = d.quote, t = d.trade
  const dep = t?.depth
  const maxQ = dep ? Math.max(1, ...dep.bids.map((b) => b.qty || 0), ...dep.asks.map((a) => a.qty || 0)) : 1
  return (
    <div className="card term-panel">
      <h3>Quote</h3>
      {q ? (
        <>
          <Row k="Open" v={px(q.open)} /><Row k="Day high / low" v={`${px(q.high)} / ${px(q.low)}`} />
          <Row k="Previous close" v={px(q.prev)} /><Row k="VWAP (NSE)" v={px(q.vwap)} />
          <Row k="Circuit band" v={ok(q.lower_circuit) ? `${px(q.lower_circuit)} – ${px(q.upper_circuit)}` : '—'} />
          <Row k="52-week high / low" v={`${px(q.wk_high)} / ${px(q.wk_low)}`} />
          {t && <><Row k="Volume" v={big(t.volume)} /><Row k="Traded value" v={ok(t.value_cr) ? `₹${num(t.value_cr, 2)} Cr` : '—'} />
            <Row k="Delivery %" v={ok(t.delivery_pct) ? `${num(t.delivery_pct, 1)}%` : '—'} /></>}
          {q.change_check && <div className="small" style={{ color: 'var(--warn)' }}>{q.change_check}</div>}
        </>
      ) : <div className="small" style={{ color: 'var(--bad)' }}>{d.sources?.[0]?.error}</div>}
      <h3 style={{ marginTop: 12 }}>Market depth</h3>
      {!dep ? <div className="small muted">{t ? 'NSE shows no order book now (market closed or pre-open).' : d.sources?.[1]?.error}</div> : !dep.ok ? <div className="small" style={{ color: 'var(--warn)' }}>Left out: {dep.why}</div> : (
        <>
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
              <span className="small"><b style={{ color: 'var(--good)' }}>{big(dep.total_buy)}</b> to buy · <b style={{ color: 'var(--bad)' }}>{big(dep.total_sell)}</b> to sell (total pending)</span>
            </div>
          )}
        </>
      )}
      <div className="small muted" style={{ marginTop: 8 }}>NSE{q?.time ? ` · as of ${q.time}` : ''}</div>
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
        <span className="small muted">NSE{c.time ? ` · ${c.time}` : ''}</span>
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
      <div className="small muted" style={{ marginTop: 4 }}>Basis = futures price − spot ({px(d.spot)}). NSE{d.time ? ` · ${d.time}` : ''}</div>
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
  const [watch, setWatch] = useState(loadW)
  const [sym, setSym] = useState(() => loadW()[0] || 'NIFTY')
  const [frame, setFrame] = useState('5m')
  const [tab, setTab] = useState('chain')
  const [head, setHead] = useState(null)
  const [wq, setWq] = useState({})
  const [add, setAdd] = useState('')
  const [alerts, setAlertsRaw] = useState(loadA)
  const setAlerts = (a) => { setAlertsRaw(a); try { localStorage.setItem(LA, JSON.stringify(a)) } catch { /* ignore */ } }
  const live = isUSs(sym) ? true : nseOpen()
  useEffect(() => { saveW(watch) }, [watch])
  useEffect(() => { setHead(null) }, [sym])
  usePoll(() => api(`/api/term/watch?symbols=${encodeURIComponent(watch.join(','))}`).then((x) => setWq(Object.fromEntries(x.rows.map((r) => [r.symbol, r])))).catch(() => {}), 15000, [watch.join(',')])
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
  }, [wq, head]) // eslint-disable-line react-hooks/exhaustive-deps
  const hasChain = isIdx(sym) || !!head?.fno
  const cur = isUSs(sym) ? '$' : isIdx(sym) ? '' : '₹'
  const addSym = () => { const s = add.trim().toUpperCase(); if (s && !watch.includes(s)) setWatch([...watch, s]); if (s) setSym(s); setAdd('') }
  const tabs = [['chain', isUSs(sym) ? null : 'Option chain & futures'], ['alerts', `Alerts${alerts.filter((a) => !a.hit).length ? ` · ${alerts.filter((a) => !a.hit).length}` : ''}`]].filter(([, l]) => l)
  const t = tabs.some(([k]) => k === tab) ? tab : tabs[0][0]
  return (
    <div className="term">
      <div className="term-top">
        <div className="row" style={{ gap: 10, alignItems: 'baseline', flexWrap: 'wrap' }}>
          <h2 style={{ margin: 0 }}>{sym.replace('US:', '')}</h2>
          <span className="muted small">{head?.name || ''}</span>
          {head && <><b className="term-ltp">{cur}{num(head.ltp, 2)}</b><b style={{ color: tone(head.change) }}>{signed(head.change, 2)} ({signed(head.pchange, 2, '%')})</b></>}
          <span className={`ipo-cd ${live ? 'warm' : ''}`}>{isUSs(sym) ? 'US · Yahoo' : nseOpen() ? '🟢 NSE open · live every 3 s' : 'NSE closed · last prices'}</span>
          {head?.time && <span className="small muted">as of {head.time} ({head.src})</span>}
        </div>
        <div className="ipo-seg">{FRAMES.map((f) => <button key={f} className={frame === f ? 'on' : ''} onClick={() => setFrame(f)}>{f}</button>)}</div>
      </div>
      <div className="term-grid">
        <div className="card term-watch">
          <div className="row" style={{ gap: 6, marginBottom: 8 }}>
            <input value={add} onChange={(e) => setAdd(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && addSym()} placeholder="Add: TCS, NIFTY, US:MSFT" style={{ flex: 1, minWidth: 0, padding: '7px 9px' }} />
            <button className="btn small" onClick={addSym}>+</button>
          </div>
          {watch.map((w) => {
            const q = wq[w]
            return (
              <div key={w} className={`term-w ${w === sym ? 'on' : ''}`} onClick={() => setSym(w)}>
                <span className="s">{w.replace('US:', '')}{isUSs(w) && <small> US</small>}{isIdx(w) && <small> IDX</small>}</span>
                <span className="p">{q?.price ? num(q.price, 2) : '—'}<small style={{ color: tone(q?.pchange) }}>{ok(q?.pchange) ? signed(q.pchange, 2, '%') : ''}</small></span>
                <button className="x" title="Remove" onClick={(e) => { e.stopPropagation(); setWatch(watch.filter((x) => x !== w)) }}>×</button>
              </div>
            )
          })}
          <div className="small muted" style={{ marginTop: 6 }}>Watchlist prices: Yahoo, every 15 s</div>
        </div>
        <div className="card term-center"><Chart sym={sym} frame={frame} /></div>
        <QuotePanel sym={sym} live={live} onHead={setHead} />
      </div>
      <div className="card">
        <div className="row" style={{ gap: 6, marginBottom: 10 }}>{tabs.map(([k, l]) => <button key={k} className={`tab ${t === k ? 'on' : ''}`} onClick={() => setTab(k)}>{l}</button>)}</div>
        {t === 'chain' && (hasChain ? <Chain key={sym} sym={sym} live={live} /> : <div className="small muted">{head ? `${sym} is not in NSE's F&O list, so it has no futures or options.` : 'Loading…'}</div>)}
        {t === 'alerts' && <Alerts sym={sym} head={head} alerts={alerts} setAlerts={setAlerts} />}
      </div>
    </div>
  )
}
