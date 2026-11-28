import { useEffect, useMemo, useRef, useState } from 'react'
import { BY_ID, CATS, INDICATORS, POPULAR } from '../indicators'

const loadJ = (k, d) => { try { return JSON.parse(localStorage.getItem(k)) ?? d } catch { return d } }
const saveJ = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)) } catch { /* ignore */ } }
export const addRecent = (id) => saveJ('eql_ind_recent', [id, ...loadJ('eql_ind_recent', []).filter((x) => x !== id)].slice(0, 12))

// Searchable list of every indicator, by group; favourites and recent are kept in this browser.
export default function IndicatorPicker({ on, onToggle, onClose, intraday }) {
  const [q, setQ] = useState('')
  const [list, setList] = useState('all')
  const [where, setWhere] = useState('')
  const [fav, setFav] = useState(() => loadJ('eql_ind_fav', []))
  const recent = loadJ('eql_ind_recent', [])
  const box = useRef()
  useEffect(() => { box.current?.focus() }, [])
  useEffect(() => { const k = (e) => e.key === 'Escape' && onClose(); window.addEventListener('keydown', k); return () => window.removeEventListener('keydown', k) }, [onClose])
  const star = (id) => { const f = fav.includes(id) ? fav.filter((x) => x !== id) : [...fav, id]; setFav(f); saveJ('eql_ind_fav', f) }
  const count = (c) => INDICATORS.filter((x) => x.cat === c).length
  const rows = useMemo(() => {
    let xs = INDICATORS
    if (list === 'fav') xs = fav.map((id) => BY_ID[id]).filter(Boolean)
    else if (list === 'recent') xs = recent.map((id) => BY_ID[id]).filter(Boolean)
    else if (list !== 'all') xs = xs.filter((x) => x.cat === list)
    if (where) xs = xs.filter((x) => x.pane === where)
    const s = q.trim().toLowerCase()
    if (s) xs = INDICATORS.filter((x) => `${x.name} ${x.short} ${x.cat}`.toLowerCase().includes(s))
    return xs
  }, [q, list, where, fav]) // eslint-disable-line react-hooks/exhaustive-deps
  const added = INDICATORS.filter((x) => on[x.id])
  const groups = list === 'all' && !q ? [['Popular', POPULAR.map((id) => BY_ID[id]).filter((x) => !where || x.pane === where)], ...CATS.map((c) => [c, rows.filter((x) => x.cat === c)])] : [[null, rows]]
  const row = (x) => (
    <div key={x.id} className={`ip-row ${on[x.id] ? 'on' : ''}`} onClick={() => onToggle(x.id)}>
      <button className={`ip-star ${fav.includes(x.id) ? 'on' : ''}`} title={fav.includes(x.id) ? 'Remove from favourites' : 'Add to favourites'} onClick={(e) => { e.stopPropagation(); star(x.id) }}>★</button>
      <span className="ip-name">{x.name}{x.intraday && !intraday ? <small> · intraday frames only</small> : null}</span>
      <span className="ip-where">{x.pane === 'price' ? 'On price' : 'Own pane'}</span>
      <span className="ip-check">{on[x.id] ? '✓' : '+'}</span>
    </div>
  )
  return (
    <div className="ip-back" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="ip" role="dialog" aria-label="Indicators">
        <div className="ip-head">
          <b>Indicators</b> <span className="small muted">{added.length} on chart</span>
          <span className="grow" />
          <button className="ip-x" onClick={onClose} aria-label="Close">✕</button>
        </div>
        <input ref={box} className="ip-search" placeholder="Search indicators" value={q} onChange={(e) => setQ(e.target.value)} />
        <div className="ip-body">
          <div className="ip-side">
            <div className="small muted ip-lab">Your lists</div>
            <button className={list === 'fav' ? 'on' : ''} onClick={() => setList('fav')}>★ Favourites <span>{fav.length}</span></button>
            <button className={list === 'recent' ? 'on' : ''} onClick={() => setList('recent')}>↺ Recent <span>{recent.length}</span></button>
            <div className="small muted ip-lab">Built in</div>
            <button className={list === 'all' ? 'on' : ''} onClick={() => setList('all')}>All indicators <span>{INDICATORS.length}</span></button>
            {CATS.map((c) => <button key={c} className={list === c ? 'on' : ''} onClick={() => setList(c)}>{c} <span>{count(c)}</span></button>)}
          </div>
          <div className="ip-list">
            <div className="row between ip-listhead">
              <b>{q ? `Results for “${q}”` : list === 'fav' ? 'Favourites' : list === 'recent' ? 'Recent' : list === 'all' ? 'All indicators' : list}</b>
              <div className="seg">{[['', 'All'], ['price', 'On price'], ['own', 'Own pane']].map(([k, l]) => <button key={k} className={where === k ? 'on' : ''} onClick={() => setWhere(k)}>{l}</button>)}</div>
            </div>
            {groups.map(([title, xs]) => (xs.length ? (
              <div key={title || 'x'}>
                {title && <div className="ip-group">{title}</div>}
                {xs.map(row)}
              </div>
            ) : null))}
            {!rows.length && <div className="small muted" style={{ padding: 12 }}>{list === 'fav' ? 'Tap ★ next to an indicator to keep it here.' : list === 'recent' ? 'Indicators you add appear here.' : 'No indicator matches.'}</div>}
          </div>
          <div className="ip-added">
            <div className="row between"><b>Added to chart</b><span className="small muted">{added.length}</span></div>
            {!added.length && <div className="small muted" style={{ marginTop: 6 }}>No indicators added</div>}
            {added.map((x) => <div key={x.id} className="ip-chip"><span>{x.short}</span><button onClick={() => onToggle(x.id)} aria-label={`Remove ${x.name}`}>✕</button></div>)}
            <div className="small muted" style={{ marginTop: 10 }}>Worked out from the candles on the chart, with standard settings. Values are checked against an independent library in the app's tests.</div>
          </div>
        </div>
      </div>
    </div>
  )
}
