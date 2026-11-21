import { useEffect, useMemo, useRef, useState } from 'react'
import { Logo, ScoreRing } from '../components/ui'
import { MAX_LISTS, api, flag, go, isUS, signed, ticker, watchlist } from '../util'
import { Tile, squarify, useWidth } from './Heatmap'

const PERIODS = [['1D', '1D'], ['1W', '1W'], ['1M', '1M'], ['since', 'Since added']]
const tone = (v) => (v === null || v === undefined ? undefined : v >= 0 ? 'var(--good)' : 'var(--bad)')
const money = (sym, v) => (v === null || v === undefined ? '—' : `${isUS(sym) ? '$' : '₹'}${(+v).toLocaleString('en-IN', { maximumFractionDigits: 2, minimumFractionDigits: 2 })}`)
const since = (it, q) => (it.price && q?.price ? +(((q.price / it.price) - 1) * 100).toFixed(2) : null)

function useWatch() {
  const [, bump] = useState(0)
  useEffect(() => {
    const on = () => bump((x) => x + 1)
    window.addEventListener('eql-watch', on)
    window.addEventListener('eql-data', on)
    return () => { window.removeEventListener('eql-watch', on); window.removeEventListener('eql-data', on) }
  }, [])
  return watchlist.data()
}

function csv(list, quotes, ranks) {
  const head = ['symbol', 'name', 'price', 'change_1d_pct', 'change_1w_pct', 'change_1m_pct', 'from_52w_high_pct', 'added_on', 'added_price', 'since_added_pct', 'score', 'verdict']
  const esc = (v) => (v === null || v === undefined ? '' : /[",\n]/.test(String(v)) ? `"${String(v).replace(/"/g, '""')}"` : String(v))
  const lines = list.items.map((it) => {
    const q = quotes[it.symbol] || {}, r = ranks[it.symbol] || {}
    return [ticker(it.symbol), it.name, q.price, q.ret?.['1D'], q.ret?.['1W'], q.ret?.['1M'], q.from_hi, it.added, it.price, since(it, q), r.overall !== undefined ? Math.round(r.overall) : '', r.verdict].map(esc).join(',')
  })
  const blob = new Blob([[head.join(','), ...lines].join('\n')], { type: 'text/csv' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = `${list.name.replace(/[^\w-]+/g, '_')}.csv`
  a.click()
  setTimeout(() => URL.revokeObjectURL(a.href), 2000)
}

// ---------------------------------------------------------------- one stock: move / copy / remove menu
function ItemMenu({ list, it, lists, onClose }) {
  const others = lists.filter((l) => l.id !== list.id)
  return (
    <div className="wl-menu" onClick={(e) => e.stopPropagation()}>
      {others.length > 0 && <div className="small muted" style={{ padding: '2px 8px 4px' }}>Move to</div>}
      {others.map((l) => <button key={`m${l.id}`} onClick={() => { watchlist.moveTo(list.id, l.id, it.symbol); onClose() }}>{l.name}</button>)}
      {others.length > 0 && <div className="small muted" style={{ padding: '6px 8px 4px' }}>Copy to</div>}
      {others.map((l) => <button key={`c${l.id}`} onClick={() => { watchlist.moveTo(list.id, l.id, it.symbol, true); onClose() }}>{l.name}</button>)}
      <button style={{ color: 'var(--bad)' }} onClick={() => { watchlist.drop(list.id, it.symbol); onClose() }}>Remove from “{list.name}”</button>
    </div>
  )
}

// ---------------------------------------------------------------- phone card with swipe-left actions
function PhoneCard({ list, it, q, r, period, lists, picking, picked, onPick }) {
  const [dx, setDx] = useState(0), [menu, setMenu] = useState(false)
  const start = useRef(null)
  const v = period === 'since' ? since(it, q) : q?.ret?.[period]
  return (
    <div className="wl-swipe">
      <div className="wl-actions" style={{ visibility: dx < 0 ? 'visible' : 'hidden' }}>
        <button onClick={() => setMenu(true)}>⇄ Move</button>
        <button className="bad" onClick={() => watchlist.drop(list.id, it.symbol)}>✕ Remove</button>
      </div>
      <div className="hm-prow wl-card" style={{ transform: `translateX(${dx}px)` }}
        onTouchStart={(e) => { start.current = e.touches[0].clientX - dx }}
        onTouchMove={(e) => { const x = e.touches[0].clientX - start.current; setDx(Math.max(-170, Math.min(0, x))) }}
        onTouchEnd={() => setDx(dx < -70 ? -170 : 0)}
        onClick={() => (picking ? onPick(it.symbol) : dx ? setDx(0) : go(`stock/${it.symbol}`))}>
        {picking && <input type="checkbox" readOnly checked={picked} />}
        <Logo sym={it.symbol} name={it.name} size={38} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div><b>{flag(it.symbol)} {ticker(it.symbol)}</b></div>
          <div className="small muted hm-ell">{it.name}{r?.overall !== undefined ? ` · score ${Math.round(r.overall)}` : ''}</div>
        </div>
        <div style={{ textAlign: 'right' }}>
          <div style={{ fontWeight: 700 }}>{q?.error ? '—' : money(it.symbol, q?.price)}</div>
          <div className="small" style={{ fontWeight: 700, color: tone(v) }}>{v === null || v === undefined ? (period === 'since' ? 'no add price' : '—') : signed(v, 2, '%')}</div>
        </div>
      </div>
      {menu && <div className="hm-sheet-bg" onClick={() => setMenu(false)}><div className="hm-sheet" onClick={(e) => e.stopPropagation()}><div className="hm-grip" /><b>{ticker(it.symbol)}</b><ItemMenu list={list} it={it} lists={lists} onClose={() => { setMenu(false); setDx(0) }} /></div></div>}
    </div>
  )
}

export default function Watch() {
  const d = useWatch()
  const lists = d.lists
  const list = lists.find((l) => l.id === d.active) || lists[0]
  const [quotes, setQuotes] = useState({}), [ranks, setRanks] = useState({}), [loading, setLoading] = useState(false)
  const [naming, setNaming] = useState(null), [nameVal, setNameVal] = useState('')     // 'new' | 'rename'
  const [confirmDel, setConfirmDel] = useState(false), [menuFor, setMenuFor] = useState(null)
  const [picking, setPicking] = useState(false), [picked, setPicked] = useState([])
  const [view, setView] = useState('list'), [period, setPeriod] = useState('1D')
  const [drag, setDrag] = useState(null)
  const [mapRef, mapW] = useWidth()
  const [phone, setPhone] = useState(() => typeof window !== 'undefined' && window.innerWidth < 760)
  useEffect(() => { const on = () => setPhone(window.innerWidth < 760); window.addEventListener('resize', on); return () => window.removeEventListener('resize', on) }, [])
  useEffect(() => { api('/api/rankings').then((x) => setRanks(Object.fromEntries((x.rows || []).map((r) => [r.symbol, r])))).catch(() => {}) }, [])
  const syms = list.items.map((i) => i.symbol).join(',')
  useEffect(() => {
    setPicking(false); setPicked([]); setConfirmDel(false); setMenuFor(null)
    const need = list.items.map((i) => i.symbol).filter((s) => !quotes[s])
    if (!need.length) return
    setLoading(true)
    api(`/api/watch/quotes?symbols=${encodeURIComponent(need.join(','))}`)
      .then((x) => setQuotes((old) => ({ ...old, ...Object.fromEntries((x.rows || []).map((r) => [r.symbol, r])) })))
      .catch(() => {}).finally(() => setLoading(false))
  }, [syms]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { const close = () => setMenuFor(null); document.addEventListener('click', close); return () => document.removeEventListener('click', close) }, [])

  const saveName = () => {
    if (naming === 'new') watchlist.create(nameVal || 'New list')
    else if (naming === 'rename') watchlist.rename(list.id, nameVal)
    setNaming(null); setNameVal('')
  }
  const nIN = list.items.filter((i) => !isUS(i.symbol)).length, nUS = list.items.length - nIN
  const tiles = useMemo(() => (view === 'map' && list.items.length && mapW ? squarify(list.items.map((it) => ({ r: { symbol: it.symbol, name: it.name, ret: quotes[it.symbol]?.ret || {} }, v: 1 })), 0, 0, mapW, phone ? 360 : 460) : []), [view, list.items, quotes, phone, mapW])
  const togglePick = (s) => setPicked((p) => (p.includes(s) ? p.filter((x) => x !== s) : p.length < 4 ? [...p, s] : p))

  return (
    <div className="wl">
      <div className="row" style={{ alignItems: 'baseline', gap: 10, flexWrap: 'wrap', marginBottom: 10 }}>
        <h2 style={{ margin: 0 }}>⭐ Watchlists</h2>
        <span className="small muted">{lists.length} of {MAX_LISTS} lists · prices: last close, Yahoo, may be delayed</span>
      </div>

      <div className="wl-tabs">
        {lists.map((l) => <button key={l.id} className={`wl-tab ${l.id === list.id ? 'on' : ''}`} onClick={() => watchlist.setActive(l.id)}>{l.name} <span>{l.items.length}</span></button>)}
        {lists.length < MAX_LISTS && naming !== 'new' && <button className="wl-tab wl-add" onClick={() => { setNaming('new'); setNameVal('') }}>＋ New list</button>}
        {naming === 'new' && (
          <span className="row" style={{ gap: 6 }}>
            <input autoFocus className="input" placeholder="Name it, e.g. Long term" maxLength={40} value={nameVal} onChange={(e) => setNameVal(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') saveName(); if (e.key === 'Escape') setNaming(null) }} />
            <button className="btn small primary" onClick={saveName}>Create</button><button className="btn small" onClick={() => setNaming(null)}>Cancel</button>
          </span>
        )}
      </div>

      <div className="card" style={{ padding: 0, overflow: 'visible' }}>
        <div className="wl-head">
          {naming === 'rename' ? (
            <span className="row" style={{ gap: 6 }}>
              <input autoFocus className="input" maxLength={40} value={nameVal} onChange={(e) => setNameVal(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') saveName(); if (e.key === 'Escape') setNaming(null) }} />
              <button className="btn small primary" onClick={saveName}>Save</button><button className="btn small" onClick={() => setNaming(null)}>Cancel</button>
            </span>
          ) : <><b style={{ fontSize: 16 }}>{list.name}</b><span className="small muted">{list.items.length} stock{list.items.length === 1 ? '' : 's'}{list.items.length ? ` · 🇮🇳 ${nIN} · 🇺🇸 ${nUS}` : ''}{loading ? ' · loading prices…' : ''}</span></>}
          <span className="wl-btns">
            <button className="btn small" onClick={() => { setNaming('rename'); setNameVal(list.name) }}>✎ Rename</button>
            {list.items.length >= 2 && (picking
              ? <><button className="btn small primary" disabled={picked.length < 2} onClick={() => go(`compare?s=${picked.join(',')}`)}>⚖️ Compare {picked.length}</button><button className="btn small" onClick={() => { setPicking(false); setPicked([]) }}>Cancel</button></>
              : <button className="btn small" onClick={() => setPicking(true)}>⚖️ Compare (pick up to 4)</button>)}
            {list.items.length > 0 && <button className="btn small" onClick={() => setView(view === 'map' ? 'list' : 'map')}>{view === 'map' ? '☰ As list' : '🗺️ As heatmap'}</button>}
            {list.items.length > 0 && <button className="btn small" onClick={() => csv(list, quotes, ranks)}>⬇ CSV</button>}
            {confirmDel
              ? <><span className="small">Delete “{list.name}”?</span><button className="btn small" style={{ color: 'var(--bad)' }} onClick={() => { watchlist.remove(list.id); setConfirmDel(false) }}>Yes, delete</button><button className="btn small" onClick={() => setConfirmDel(false)}>No</button></>
              : <button className="btn small" style={{ color: 'var(--bad)' }} onClick={() => setConfirmDel(true)}>🗑 Delete list</button>}
          </span>
        </div>

        {(phone || view === 'map') && list.items.length > 0 && (
          <div className="row" style={{ gap: 6, padding: '10px 14px 0', flexWrap: 'wrap' }}>
            {(view === 'map' ? PERIODS.slice(0, 3) : PERIODS).map(([k, t]) => <button key={k} className={`hm-chip ${period === k ? 'on' : ''}`} onClick={() => setPeriod(k)}>{t}</button>)}
          </div>
        )}

        {!list.items.length && <div className="empty" style={{ padding: 24 }}>“{list.name}” is empty. Tap ☆ on any stock page and tick this list.</div>}

        {list.items.length > 0 && view === 'map' && (
          <div ref={mapRef} className="hm-map" style={{ height: phone ? 360 : 460, margin: 12, width: 'auto' }}>
            {tiles.map((t) => <Tile key={t.r.symbol} t={t} tf={period === 'since' ? '1D' : period} onPick={(r) => go(`stock/${r.symbol}`)} />)}
          </div>
        )}

        {list.items.length > 0 && view === 'list' && !phone && (
          <div style={{ overflowX: 'auto' }}>
            <table className="pm-table wl-table">
              <thead><tr>{picking && <th />}<th>Stock</th><th>Price</th><th>1D</th><th>1W</th><th>1M</th><th>From 52w high</th><th>Since added</th><th>Score</th><th /></tr></thead>
              <tbody>
                {list.items.map((it, i) => {
                  const q = quotes[it.symbol], r = ranks[it.symbol], sa = since(it, q)
                  return (
                    <tr key={it.symbol} draggable={!picking} className={drag === i ? 'wl-drag' : ''}
                      onDragStart={() => setDrag(i)} onDragOver={(e) => e.preventDefault()} onDrop={() => { watchlist.reorder(list.id, drag, i); setDrag(null) }} onDragEnd={() => setDrag(null)}
                      onClick={() => (picking ? togglePick(it.symbol) : go(`stock/${it.symbol}`))} style={{ cursor: 'pointer' }}>
                      {picking && <td><input type="checkbox" readOnly checked={picked.includes(it.symbol)} /></td>}
                      <td><span className="row" style={{ gap: 10, alignItems: 'center' }}><span className="wl-grip" title="Drag to reorder">⋮⋮</span><Logo sym={it.symbol} name={it.name} size={30} /><span><b>{ticker(it.symbol)}</b> <span className="small muted">{flag(it.symbol)} {it.name}</span></span></span></td>
                      <td>{q?.error ? <span className="small muted" title={q.error}>no price</span> : money(it.symbol, q?.price)}</td>
                      {['1D', '1W', '1M'].map((k) => <td key={k} style={{ color: tone(q?.ret?.[k]), fontWeight: k === '1D' ? 700 : 400 }}>{signed(q?.ret?.[k], 2, '%')}</td>)}
                      <td>{signed(q?.from_hi, 1, '%')}</td>
                      <td>{sa === null ? <span className="muted" title="Added before prices were saved with the list">—</span> : <><span style={{ color: tone(sa), fontWeight: 600 }}>{signed(sa, 2, '%')}</span> <span className="small muted">since {it.added} at {money(it.symbol, it.price)}</span></>}</td>
                      <td>{r ? <span className="row" style={{ gap: 6, alignItems: 'center' }}><ScoreRing value={r.overall} size={30} /><span className={`badge sm t-${r.tone} bg-${r.tone}`}>{r.verdict}</span></span> : <span className="small muted">open to score</span>}</td>
                      <td style={{ position: 'relative' }} onClick={(e) => e.stopPropagation()}>
                        <button className="btn small" title="Move, copy or remove" onClick={(e) => { e.stopPropagation(); setMenuFor(menuFor === it.symbol ? null : it.symbol) }}>⇄</button>
                        <button className="btn small" title={`Remove from ${list.name}`} style={{ marginLeft: 4 }} onClick={() => watchlist.drop(list.id, it.symbol)}>✕</button>
                        {menuFor === it.symbol && <ItemMenu list={list} it={it} lists={lists} onClose={() => setMenuFor(null)} />}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}

        {list.items.length > 0 && view === 'list' && phone && (
          <div style={{ padding: 10, display: 'flex', flexDirection: 'column', gap: 8 }}>
            {list.items.map((it) => <PhoneCard key={it.symbol} list={list} it={it} q={quotes[it.symbol]} r={ranks[it.symbol]} period={period} lists={lists} picking={picking} picked={picked.includes(it.symbol)} onPick={togglePick} />)}
            <div className="small muted" style={{ padding: '2px 4px' }}>Tap a stock to open it · swipe left to move or remove</div>
          </div>
        )}
      </div>
      <p className="disclaimer">“Since added” uses the price saved when you added the stock to this list (stocks added before this update show —). Prices are daily closes from Yahoo Finance and may be delayed. Calendar and Smart Money use the stocks from all your lists.</p>
    </div>
  )
}
