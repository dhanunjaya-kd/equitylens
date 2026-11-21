import { useEffect, useRef, useState } from 'react'
import { MAX_LISTS, isDesktop, watchlist } from '../util'

// The star on a stock page: pick which watchlists the stock is in (one stock can be in several), or make a new list.
export default function WatchPicker({ symbol, name, price }) {
  const [open, setOpen] = useState(false), [, bump] = useState(0), [making, setMaking] = useState(false), [newName, setNewName] = useState('')
  const box = useRef(null)
  useEffect(() => {
    const on = () => bump((x) => x + 1)
    window.addEventListener('eql-watch', on)
    window.addEventListener('eql-data', on)
    return () => { window.removeEventListener('eql-watch', on); window.removeEventListener('eql-data', on) }
  }, [])
  useEffect(() => {
    if (!open || !isDesktop()) return undefined
    const close = (e) => { if (box.current && !box.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [open])
  const lists = watchlist.lists()
  const inIds = new Set(watchlist.listsWith(symbol))
  const flip = (id) => (inIds.has(id) ? watchlist.drop(id, symbol) : watchlist.add(id, symbol, name, price))
  const make = () => {
    const id = watchlist.create(newName || 'New list')
    if (id) watchlist.add(id, symbol, name, price)
    setNewName(''); setMaking(false)
  }
  const label = symbol.replace(/^US:/, '')
  const body = (
    <>
      <div style={{ fontWeight: 700, marginBottom: 6 }}>Add {label} to…</div>
      {lists.map((l) => (
        <label key={l.id} className="wp-row">
          <input type="checkbox" checked={inIds.has(l.id)} onChange={() => flip(l.id)} />
          <span className="grow">{l.name}</span><span className="small muted">{l.items.length}</span>
        </label>
      ))}
      {making ? (
        <div className="row" style={{ gap: 6, marginTop: 8 }}>
          <input autoFocus className="input" placeholder="List name, e.g. Long term" value={newName} maxLength={40}
            onChange={(e) => setNewName(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') make(); if (e.key === 'Escape') setMaking(false) }} style={{ flex: 1 }} />
          <button className="btn small primary" onClick={make}>Add</button>
        </div>
      ) : lists.length < MAX_LISTS
        ? <button className="wp-new" onClick={() => setMaking(true)}>＋ New list…</button>
        : <div className="small muted" style={{ marginTop: 8 }}>10 lists is the limit; delete one in Watchlists to make another.</div>}
    </>
  )
  const on = inIds.size > 0
  return (
    <span ref={box} style={{ position: 'relative', display: 'inline-block' }}>
      <button className={`star ${on ? 'on' : ''}`} title={on ? `In ${inIds.size} list${inIds.size > 1 ? 's' : ''}` : 'Add to a watchlist'} onClick={() => setOpen(!open)}>{on ? '★' : '☆'}</button>
      {open && (isDesktop()
        ? <div className="wp-pop">{body}</div>
        : (
          <div className="hm-sheet-bg" onClick={() => setOpen(false)}>
            <div className="hm-sheet" onClick={(e) => e.stopPropagation()}><div className="hm-grip" />{body}
              <button className="btn" style={{ width: '100%', marginTop: 10 }} onClick={() => setOpen(false)}>Done</button>
            </div>
          </div>
        ))}
    </span>
  )
}
