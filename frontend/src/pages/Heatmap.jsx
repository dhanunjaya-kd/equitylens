import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { ago, api, cr, getMarket, go, rs, signed } from '../util'
import { Logo } from '../components/ui'

const TFS = ['1D', '1W', '1M', '3M', '1Y']
const SCALE = { '1D': 3, '1W': 6, '1M': 10, '3M': 20, '1Y': 40 }       // colour is full at ±this %
const SIZES = [['mcap', 'Market cap'], ['value', 'Traded value'], ['equal', 'Equal']]
const PHONE = 760

// ---------------------------------------------------------------- layout (squarified treemap)
export function squarify(items, x, y, w, h) {
  const out = []
  const total = items.reduce((a, b) => a + b.v, 0)
  if (!items.length || total <= 0 || w <= 0 || h <= 0) return out
  const scale = (w * h) / total
  let rest = items.map((r) => ({ ...r, a: r.v * scale }))
  const worst = (row, side) => {
    const s = row.reduce((a, b) => a + b.a, 0)
    let mx = 0, mn = Infinity
    row.forEach((r) => { mx = Math.max(mx, r.a); mn = Math.min(mn, r.a) })
    return Math.max((side * side * mx) / (s * s), (s * s) / (side * side * mn))
  }
  while (rest.length) {
    const side = Math.min(w, h)
    const row = [rest[0]]
    let i = 1
    while (i < rest.length && worst([...row, rest[i]], side) <= worst(row, side)) { row.push(rest[i]); i++ }
    const s = row.reduce((a, b) => a + b.a, 0)
    if (w >= h) {
      const cw = s / h
      let cy = y
      row.forEach((r) => { const ch = r.a / cw; out.push({ ...r, x, y: cy, w: cw, h: ch }); cy += ch })
      x += cw; w -= cw
    } else {
      const ch = s / w
      let cx = x
      row.forEach((r) => { const cw = r.a / ch; out.push({ ...r, x: cx, y, w: cw, h: ch }); cx += cw })
      y += ch; h -= ch
    }
    rest = rest.slice(i)
  }
  return out
}

// Box weight: market cap, traded value or equal. A stock with no market cap gets the smallest market cap
// on the map (never a guessed one) and is counted under the map.
export function weights(rows, size) {
  if (size === 'equal') return rows.map(() => 1)
  if (size === 'value') return rows.map((r) => Math.max(r.value || 0, 0.0001))
  const have = rows.map((r) => r.mcap).filter((x) => x > 0)
  const floor = have.length ? Math.min(...have) : 1
  return rows.map((r) => (r.mcap > 0 ? r.mcap : floor))
}

export function colour(v, tf) {
  if (v === null || v === undefined) return '#1f2937'
  const t = Math.min(1, Math.abs(v) / SCALE[tf])
  const mix = (a, b) => Math.round(a + (b - a) * t)
  const [r, g, b] = v >= 0 ? [mix(42, 22), mix(52, 163), mix(65, 74)] : [mix(42, 220), mix(52, 38), mix(65, 38)]
  return `rgb(${r},${g},${b})`
}

function useWidth() {
  const ref = useRef(null)
  const [w, setW] = useState(0)
  useLayoutEffect(() => {
    if (!ref.current) return undefined
    const ro = new ResizeObserver(([e]) => setW(Math.floor(e.contentRect.width)))
    ro.observe(ref.current)
    return () => ro.disconnect()
  }, [])
  return [ref, w]
}

const sym = (s) => String(s).replace(/^US:/, '')

// ---------------------------------------------------------------- one box
function Tile({ t, tf, onPick, onHover }) {
  const v = t.r.ret?.[tf]
  const s = sym(t.r.symbol)
  const showLogo = t.w >= 74 && t.h >= 74
  const showSym = t.w >= 30 && t.h >= 16
  const showPct = t.w >= 40 && t.h >= (showLogo ? 70 : 32)
  const fs = Math.max(9, Math.min(showLogo ? 16 : 13, (t.w - 8) / (s.length * 0.62)))
  return (
    <div className="hm-tile" style={{ left: t.x, top: t.y, width: t.w, height: t.h, background: colour(v, tf) }}
      onClick={(e) => { e.stopPropagation(); onPick(t.r, e) }} onMouseEnter={(e) => onHover?.(t.r, e)} onMouseLeave={() => onHover?.(null)} title={`${t.r.name} · ${signed(v, 2, '%')}`}>
      {showLogo && <Logo sym={t.r.symbol} name={t.r.name} size={Math.min(36, Math.max(24, Math.min(t.w, t.h) / 4))} />}
      {showSym && <div className="hm-sym" style={{ fontSize: fs }}>{s}</div>}
      {showPct && <div className="hm-pct" style={{ fontSize: Math.max(9, fs - 2) }}>{v === null || v === undefined ? 'no price' : signed(v, 2, '%')}</div>}
    </div>
  )
}

// ---------------------------------------------------------------- details: card (web) / sheet (phone)
function Details({ r, tf, phone, onClose, pos }) {
  if (!r) return null
  const body = (
    <>
      <div className="row" style={{ gap: 10, alignItems: 'center' }}>
        <Logo sym={r.symbol} name={r.name} size={40} />
        <div style={{ minWidth: 0 }}>
          <div style={{ fontWeight: 700 }}>{r.name}</div>
          <div className="small muted">{sym(r.symbol)} · {r.sector} · {rs(r.price, 2)}</div>
        </div>
      </div>
      <div className="hm-rets">
        {TFS.map((k) => <div key={k} style={k === tf ? { color: 'var(--accent)' } : undefined}><div className="muted">{k}</div><b style={{ color: (r.ret?.[k] ?? 0) >= 0 ? 'var(--good)' : 'var(--bad)' }}>{signed(r.ret?.[k], 1, '%')}</b></div>)}
      </div>
      <div className="small" style={{ marginTop: 8, lineHeight: 1.5 }}>
        Market cap {r.mcap ? <>{cr(r.mcap)}{r.mcap_src === 'nse_shares' ? <span className="muted"> (NSE issued shares × last close)</span> : null}</> : <span className="muted">not known yet</span>}
        {r.from_hi !== null && r.from_hi !== undefined && <> · {Math.abs(r.from_hi).toFixed(1)}% below its 52-week high</>}
        {r.above200 !== null && r.above200 !== undefined && <> · {r.above200 ? 'above' : 'below'} its 200-day</>}
        {r.score !== null && r.score !== undefined && <> · EquityLens score {Math.round(r.score)}</>}
      </div>
      <div className="row" style={{ gap: 8, marginTop: 10 }}>
        <button className="btn small primary" onClick={() => go(`stock/${r.symbol}`)}>Open stock</button>
        <button className="btn small" onClick={() => go(`stock/${r.symbol}/pricemap`)}>📍 Price map</button>
        {!phone && <button className="btn small" onClick={onClose}>✕</button>}
      </div>
    </>
  )
  if (phone) {
    return (
      <div className="hm-sheet-bg" onClick={onClose}>
        <div className="hm-sheet" onClick={(e) => e.stopPropagation()}><div className="hm-grip" />{body}</div>
      </div>
    )
  }
  return <div className="hm-card" style={{ left: pos?.x ?? 20, top: pos?.y ?? 20 }} onClick={(e) => e.stopPropagation()}>{body}</div>
}

function Preview({ r, tf, pos }) {
  if (!r || !pos) return null
  return (
    <div className="hm-card hm-preview" style={{ left: pos.x, top: pos.y }}>
      <div className="row" style={{ gap: 8, alignItems: 'center' }}><Logo sym={r.symbol} name={r.name} size={26} /><b>{r.name}</b></div>
      <div className="small" style={{ marginTop: 4 }}>{tf}: <b>{signed(r.ret?.[tf], 2, '%')}</b>{r.mcap ? ` · ${cr(r.mcap)}` : ''} · click for details</div>
    </div>
  )
}

// ---------------------------------------------------------------- the whole map (web)
function MapWeb({ rows, sectors, tf, size, width }) {
  const [pick, setPick] = useState(null), [hover, setHover] = useState(null)
  const wrap = useRef(null)
  const H = Math.max(480, Math.min(780, Math.round(width * 0.58)))
  const layout = useMemo(() => {
    if (!width) return { secs: [], tiles: [] }
    const ws = weights(rows, size)
    const wOf = new Map(rows.map((r, i) => [r.symbol, ws[i]]))
    const groups = sectors.map((s) => {
      const rs = rows.filter((r) => r.sector === s.sector).map((r) => ({ r, v: wOf.get(r.symbol) })).sort((a, b) => b.v - a.v)
      return { s, rs, v: rs.reduce((a, b) => a + b.v, 0) }
    }).filter((g) => g.v > 0).sort((a, b) => b.v - a.v)
    const boxes = squarify(groups, 0, 0, width, H)
    const secs = [], tiles = []
    boxes.forEach((b) => {
      const head = b.h > 40 && b.w > 60 ? 18 : 0
      secs.push({ ...b, head })
      squarify(b.rs, b.x, b.y + head, b.w, b.h - head).forEach((t) => tiles.push(t))
    })
    return { secs, tiles }
  }, [rows, sectors, size, width, H])
  const at = (e) => {
    const box = wrap.current?.getBoundingClientRect()
    if (!box) return null
    const x = Math.min(e.clientX - box.left + 12, width - 300)
    const y = Math.min(e.clientY - box.top + 12, H - 210)
    return { x: Math.max(4, x), y: Math.max(4, y) }
  }
  return (
    <div ref={wrap} className="hm-map" style={{ height: H }} onClick={() => setPick(null)}>
      {layout.tiles.map((t) => <Tile key={t.r.symbol} t={t} tf={tf} onPick={(r, e) => { setHover(null); setPick({ r, pos: at(e) }) }} onHover={(r, e) => setHover(r && !pick ? { r, pos: at(e) } : null)} />)}
      {layout.secs.filter((s) => s.head).map((s) => (
        <button key={s.s.sector} className="hm-head" style={{ left: s.x, top: s.y, width: s.w }} onClick={(e) => { e.stopPropagation(); go(`heatmap/${encodeURIComponent(s.s.sector)}`) }}>
          {s.s.sector} · {signed(s.s.avg, 2, '%')} · {s.s.up} of {s.s.priced} up
        </button>
      ))}
      {hover && <Preview r={hover.r} tf={tf} pos={hover.pos} />}
      {pick && <Details r={pick.r} tf={tf} pos={pick.pos} onClose={() => setPick(null)} />}
    </div>
  )
}

// ---------------------------------------------------------------- one card per sector (phone)
const PER_SECTOR = 8
function MapPhone({ rows, sectors, tf, size, width }) {
  const [pick, setPick] = useState(null)
  const ws = useMemo(() => { const w = weights(rows, size); return new Map(rows.map((r, i) => [r.symbol, w[i]])) }, [rows, size])
  const groups = useMemo(() => sectors.map((s) => {
    const rs = rows.filter((r) => r.sector === s.sector).map((r) => ({ r, v: ws.get(r.symbol) })).sort((a, b) => b.v - a.v)
    return { s, rs, v: rs.reduce((a, b) => a + b.v, 0) }
  }).filter((g) => g.v > 0).sort((a, b) => b.v - a.v), [rows, sectors, ws])
  const inner = Math.max(200, width - 14)
  return (
    <>
      {groups.map((g, gi) => {
        const h = gi < 3 ? 190 : gi < 8 ? 160 : 130
        const top = g.rs.slice(0, PER_SECTOR)
        const tiles = squarify(top, 0, 0, inner, h)
        return (
          <div key={g.s.sector} className="hm-pcard">
            <button className="hm-phead" onClick={() => go(`heatmap/${encodeURIComponent(g.s.sector)}`)}>
              <b>{g.s.sector}</b><span className="small muted">{signed(g.s.avg, 2, '%')} · {g.s.up}/{g.s.priced} up ›</span>
            </button>
            <div className="hm-map" style={{ height: h, margin: '0 6px' }}>
              {tiles.map((t) => <Tile key={t.r.symbol} t={t} tf={tf} onPick={(r) => setPick(r)} />)}
            </div>
            <div className="small muted" style={{ padding: '6px 12px 9px' }}>{g.rs.length > PER_SECTOR ? `Biggest ${PER_SECTOR} shown · tap the sector for all ${g.rs.length}` : `${g.rs.length} stock${g.rs.length === 1 ? '' : 's'}`}</div>
          </div>
        )
      })}
      <Details r={pick} tf={tf} phone onClose={() => setPick(null)} />
    </>
  )
}

// ---------------------------------------------------------------- controls
function Chips({ list, value, onPick, label }) {
  return (
    <div className="row" style={{ gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
      {label && <span className="small muted">{label}</span>}
      {list.map(([k, t]) => <button key={k} className={`hm-chip ${value === k ? 'on' : ''}`} onClick={() => onPick(k)}>{t}</button>)}
    </div>
  )
}

function Legend({ tf }) {
  return (
    <div className="row" style={{ gap: 6, alignItems: 'center' }}>
      <span className="small muted">−{SCALE[tf]}%</span>
      <div className="hm-legend" style={{ background: `linear-gradient(90deg, ${colour(-SCALE[tf], tf)}, ${colour(-SCALE[tf] / 2, tf)}, ${colour(0, tf)}, ${colour(SCALE[tf] / 2, tf)}, ${colour(SCALE[tf], tf)})` }} />
      <span className="small muted">+{SCALE[tf]}%</span>
    </div>
  )
}

// ---------------------------------------------------------------- sector view
const SORTS = [['ret', '% change'], ['mcap', 'Market cap'], ['from_hi', 'From 52-week high'], ['score', 'EquityLens score']]

function SectorView({ name, d, tf, size, phone, width }) {
  const [idx, setIdx] = useState(null), [sort, setSort] = useState('ret'), [pick, setPick] = useState(null)
  const mk = getMarket()
  useEffect(() => { setIdx(null); api(`/api/heatmap/sector?market=${mk}&sector=${encodeURIComponent(name)}`).then(setIdx).catch(() => setIdx({ index: null, note: 'Could not load the sector index.' })) }, [name, mk])
  const rows = d.rows.filter((r) => r.sector === name)
  const sec = d.sectors.find((s) => s.sector === name)
  if (!rows.length) return <div className="card">No stocks in “{name}” for this list. <button className="btn small" onClick={() => go('heatmap')}>← All sectors</button></div>
  const key = (r) => (sort === 'ret' ? r.ret?.[tf] : sort === 'mcap' ? r.mcap : sort === 'from_hi' ? r.from_hi : r.score)
  const sorted = [...rows].sort((a, b) => (key(b) ?? -Infinity) - (key(a) ?? -Infinity))
  const priced = rows.filter((r) => r.ret?.[tf] !== null && r.ret?.[tf] !== undefined)
  const best = priced.length ? priced.reduce((a, b) => (b.ret[tf] > a.ret[tf] ? b : a)) : null
  const worst = priced.length ? priced.reduce((a, b) => (b.ret[tf] < a.ret[tf] ? b : a)) : null
  const ix = idx?.index
  const ws = weights(rows, size)
  const H = phone ? 240 : 340
  const tiles = width ? squarify(rows.map((r, i) => ({ r, v: ws[i] })).sort((a, b) => b.v - a.v), 0, 0, width, H) : []
  const above50 = rows.filter((r) => r.above50).length
  return (
    <>
      <div className="card">
        <button className="btn small" onClick={() => go('heatmap')}>← All sectors</button>
        <h2 style={{ margin: '10px 0 2px' }}>{name}</h2>
        <div className="small muted">{rows.length} stocks · {tf} · average {signed(sec?.avg, 2, '%')} · {sec?.up} up, {sec?.down} down</div>
        <div className="hm-kpis">
          <div className="tile"><div className="k">Best ({tf})</div><div className="v" style={{ fontSize: 16 }}>{best ? <>{sym(best.symbol)} <span style={{ color: 'var(--good)' }}>{signed(best.ret[tf], 2, '%')}</span></> : '—'}</div></div>
          <div className="tile"><div className="k">Worst ({tf})</div><div className="v" style={{ fontSize: 16 }}>{worst ? <>{sym(worst.symbol)} <span style={{ color: 'var(--bad)' }}>{signed(worst.ret[tf], 2, '%')}</span></> : '—'}</div></div>
          <div className="tile"><div className="k">Above their 50-day</div><div className="v" style={{ fontSize: 16 }}>{above50} of {rows.length}</div></div>
          <div className="tile"><div className="k">{ix?.name || 'Sector index'}</div><div className="v" style={{ fontSize: 16 }}>
            {!idx ? '…' : ix && !ix.error ? <>{ix.ret?.[tf] !== undefined ? <span style={{ color: (ix.ret[tf] ?? 0) >= 0 ? 'var(--good)' : 'var(--bad)' }}>{signed(ix.ret[tf], 2, '%')}</span> : null} · −{ix.fall_pct}% from high</> : <span className="small muted">{ix?.error || idx?.note}</span>}
          </div></div>
        </div>
      </div>
      <div className="hm-map" style={{ height: H, marginBottom: 12 }} onClick={() => setPick(null)}>
        {tiles.map((t) => <Tile key={t.r.symbol} t={t} tf={tf} onPick={(r) => setPick(r)} />)}
      </div>
      <div className="card">
        <Chips list={SORTS} value={sort} onPick={setSort} label="Sort by" />
        {phone ? (
          <div style={{ marginTop: 10, display: 'flex', flexDirection: 'column', gap: 8 }}>
            {sorted.map((r) => (
              <div key={r.symbol} className="hm-prow" onClick={() => go(`stock/${r.symbol}`)}>
                <Logo sym={r.symbol} name={r.name} size={36} />
                <div style={{ flex: 1, minWidth: 0 }}><b>{sym(r.symbol)}</b><div className="small muted hm-ell">{r.name} · {r.mcap ? cr(r.mcap) : 'mcap —'} · {signed(r.from_hi, 1, '%')} from high</div></div>
                <div style={{ textAlign: 'right' }}><b style={{ color: (r.ret?.[tf] ?? 0) >= 0 ? 'var(--good)' : 'var(--bad)' }}>{signed(r.ret?.[tf], 2, '%')}</b><div className="small muted">{r.score !== null && r.score !== undefined ? `score ${Math.round(r.score)}` : ''}</div></div>
              </div>
            ))}
          </div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table className="pm-table" style={{ marginTop: 10, minWidth: 760 }}>
              <thead><tr><th>Stock</th><th>{tf} change</th><th>Market cap</th><th>From 52-week high</th><th>200-day avg</th><th>Rel. volume</th><th>Score</th></tr></thead>
              <tbody>{sorted.map((r) => (
                <tr key={r.symbol} style={{ cursor: 'pointer' }} onClick={() => go(`stock/${r.symbol}`)}>
                  <td><span className="row" style={{ gap: 10, alignItems: 'center' }}><Logo sym={r.symbol} name={r.name} size={28} /><span><b>{sym(r.symbol)}</b> <span className="small muted">{r.name}</span></span></span></td>
                  <td style={{ color: (r.ret?.[tf] ?? 0) >= 0 ? 'var(--good)' : 'var(--bad)', fontWeight: 700 }}>{signed(r.ret?.[tf], 2, '%')}</td>
                  <td>{r.mcap ? cr(r.mcap) : <span className="muted">—</span>}</td>
                  <td>{signed(r.from_hi, 1, '%')}</td>
                  <td>{r.above200 ? 'above ✓' : 'below ✕'}</td>
                  <td>{r.rvol ? `${r.rvol}×` : '—'}</td>
                  <td>{r.score !== null && r.score !== undefined ? Math.round(r.score) : '—'}</td>
                </tr>))}</tbody>
            </table>
          </div>
        )}
        <div className="small muted" style={{ marginTop: 8 }}>{mk === 'US' ? 'Sectors are the S&P 500 sector groups; the sector fund is that sector’s Select Sector SPDR.' : 'Sectors are NSE’s own industry groups; the index is the closest NSE sector index.'} Tap a stock to open it.</div>
      </div>
      <Details r={pick} tf={tf} phone={phone} pos={{ x: 20, y: 20 }} onClose={() => setPick(null)} />
    </>
  )
}

// ---------------------------------------------------------------- page
export default function Heatmap({ sector }) {
  const mk = getMarket()
  const saved = (() => { try { return JSON.parse(localStorage.getItem('eql_heatmap') || '{}') } catch { return {} } })()
  const [tf, setTf] = useState(TFS.includes(saved.tf) ? saved.tf : '1D')
  const [size, setSize] = useState(SIZES.some((x) => x[0] === saved.size) ? saved.size : 'mcap')
  const [univ, setUniv] = useState(saved.univ === 'ALL' ? 'ALL' : 'N500')
  const [more, setMore] = useState(false)
  useEffect(() => { try { localStorage.setItem('eql_heatmap', JSON.stringify({ tf, size, univ })) } catch { /* private mode */ } }, [tf, size, univ])
  const [d, setD] = useState(null)
  const [ref, width] = useWidth()
  const poll = useRef(null)
  const load = () => api(`/api/heatmap?market=${mk}&tf=${tf}${mk === 'IN' ? `&universe=${univ}` : ''}`).then(setD).catch(() => setD({ rows: [], sectors: [], status: {} }))
  useEffect(() => { load() }, [mk, tf, univ]) // eslint-disable-line react-hooks/exhaustive-deps
  const filling = !!d?.sector_fill?.running
  useEffect(() => {
    clearInterval(poll.current)
    if (d?.status?.running) poll.current = setInterval(load, 4000)
    else if (filling) poll.current = setInterval(load, 20000)
    return () => clearInterval(poll.current)
  }, [d?.status?.running, filling]) // eslint-disable-line react-hooks/exhaustive-deps
  const phone = width > 0 && width < PHONE
  const st = d?.status || {}
  const noMcapAll = d && d.rows.length > 0 && d.no_mcap === d.rows.length
  const list = mk === 'US' ? 'S&P 500' : univ === 'ALL' && d?.universe === 'ALL' ? 'All NSE stocks' : 'NIFTY 500'
  return (
    <div className="page" ref={ref}>
      <div className="card" style={{ marginBottom: 12 }}>
        <div className="row between" style={{ gap: 10, flexWrap: 'wrap', alignItems: 'baseline' }}>
          <div>
            <h2 style={{ margin: 0 }}>🗺️ Heatmap</h2>
            <div className="small muted">{list} · {d?.rows?.length || 0} stocks{d?.session ? ` · ${d.live ? 'live session' : 'close of'} ${new Date(d.session + 'T12:00:00').toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric', month: 'short' })}` : ''}{d?.updated ? ` · updated ${ago(d.updated)}` : ''} · Yahoo, may be delayed</div>
          </div>
          <Legend tf={tf} />
        </div>
        {phone ? (
          <>
            <div className="row" style={{ gap: 6, marginTop: 10, flexWrap: 'wrap' }}>
              {TFS.map((k) => <button key={k} className={`hm-chip ${tf === k ? 'on' : ''}`} onClick={() => setTf(k)}>{k}</button>)}
              <button className={`hm-chip ${more ? 'on' : ''}`} onClick={() => setMore(!more)}>⚙ {SIZES.find((x) => x[0] === size)[1]}{mk === 'IN' ? ` · ${univ === 'ALL' ? 'All NSE' : 'NIFTY 500'}` : ''}</button>
            </div>
            {more && (
              <div className="hm-controls">
                {mk === 'IN' && <Chips list={[['N500', 'NIFTY 500'], ['ALL', 'All NSE']]} value={univ} onPick={setUniv} label="Stocks" />}
                <Chips list={SIZES} value={size} onPick={setSize} label="Box size" />
              </div>
            )}
          </>
        ) : (
          <div className="hm-controls">
            {mk === 'IN' && <Chips list={[['N500', 'NIFTY 500'], ['ALL', 'All NSE']]} value={univ} onPick={setUniv} label="Stocks" />}
            <Chips list={TFS.map((k) => [k, k])} value={tf} onPick={setTf} label="Period" />
            <Chips list={SIZES} value={size} onPick={setSize} label="Box size" />
          </div>
        )}
        {mk === 'IN' && univ === 'ALL' && d && d.universe !== 'ALL' && !st.running && (
          <div className="small" style={{ marginTop: 8 }}>Prices are loaded for the NIFTY 500 only. <button className="btn small primary" onClick={async () => { await api('/api/movers/refresh?market=IN&universe=ALL', { method: 'POST' }); load() }}>Load all NSE stocks</button> <span className="muted">(about 10–15 min in the background)</span></div>
        )}
        {st.running && <><div className="small" style={{ marginTop: 8 }}>Loading prices {st.done}/{st.total}…</div><div className="progress"><div style={{ width: `${st.total ? (st.done / st.total) * 100 : 0}%` }} /></div></>}
        {filling && (
          <>
            <div className="small" style={{ marginTop: 8 }}>Getting each stock's NSE sector and issued shares (for market cap): {d.sector_fill.done.toLocaleString('en-IN')} of {d.sector_fill.total.toLocaleString('en-IN')} · one time only, about {Math.max(1, Math.round((d.sector_fill.total - d.sector_fill.done) / 60))} min left in the background · the map fills in as it goes</div>
            <div className="progress"><div style={{ width: `${d.sector_fill.total ? (d.sector_fill.done / d.sector_fill.total) * 100 : 0}%` }} /></div>
          </>
        )}
        {size === 'mcap' && d?.no_mcap > 0 && !noMcapAll && <div className="small muted" style={{ marginTop: 8 }}>{d.no_mcap.toLocaleString('en-IN')} stock{d.no_mcap === 1 ? '' : 's'} with no market cap yet: shown at the smallest size, not a guessed one.</div>}
        {size === 'mcap' && noMcapAll && <div className="small" style={{ marginTop: 8, color: 'var(--warn)' }}>No market caps yet{filling ? ' (being fetched from NSE)' : ''}, so every box is the same size for now. <b>Box size → Traded value</b> works straight away.</div>}
        {d?.sector_fill?.unknown > 0 && !filling && <div className="small muted" style={{ marginTop: 4 }}>{d.sector_fill.unknown} stock{d.sector_fill.unknown === 1 ? '' : 's'} NSE gives no sector for are grouped as "Sector not known yet".</div>}
      </div>
      {!d && <div className="card empty">Loading…</div>}
      {d && !d.rows.length && <div className="card empty">{st.running ? 'Fetching prices for the whole list. The first load takes 1–3 minutes, after that it’s instant.' : 'No prices yet.'}</div>}
      {d && d.rows.length > 0 && width > 0 && (sector
        ? <SectorView name={sector} d={d} tf={tf} size={size} phone={phone} width={width} />
        : phone ? <MapPhone rows={d.rows} sectors={d.sectors} tf={tf} size={size} width={width} />
          : <MapWeb rows={d.rows} sectors={d.sectors} tf={tf} size={size} width={width} />)}
      <p className="disclaimer">Box size = {SIZES.find((x) => x[0] === size)[1].toLowerCase()} · colour = % change over {tf} (full colour at ±{SCALE[tf]}%) · grey = no price. Prices: Yahoo Finance via Market Movers; sectors: NSE's own classification; market cap: the EquityLens scan, or NSE issued shares × last close; score: the EquityLens scan; logos: the company's own logo, or its initials when none is found.</p>
    </div>
  )
}
