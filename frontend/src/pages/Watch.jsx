import { useEffect, useState } from 'react'
import { ScoreRing } from '../components/ui'
import { api, flag, go, pct, ticker, watchlist } from '../util'

export default function Watch() {
  const list = watchlist.all()
  const [rows, setRows] = useState({})
  useEffect(() => {
    api('/api/rankings').then((d) => setRows(Object.fromEntries((d.rows || []).map((r) => [r.symbol, r])))).catch(() => {})
  }, [])
  if (!list.length) return <div className="card empty">Your watchlist is empty.<br />Tap ☆ on any stock page to add it.</div>
  return (
    <>
      <div className="card" style={{ padding: 0 }}>
        {list.map((w) => {
          const r = rows[w.symbol]
          return (
            <div key={w.symbol} className="rank-item" onClick={() => go(`stock/${w.symbol}`)}>
              <div className="ring-sm"><ScoreRing value={r?.overall} size={44} /></div>
              <div className="grow">
                <div className="ellip">{flag(w.symbol)} <b>{w.name || ticker(w.symbol)}</b> <span className="small muted">{ticker(w.symbol)}</span></div>
                <div className="small muted">{r ? `Base 5y ${pct(r.base_5y)}/yr · 10y ${pct(r.base_10y)}/yr` : 'Open to load'}</div>
                {r && <span className={`badge sm t-${r.tone} bg-${r.tone}`} style={{ marginTop: 4 }}>{r.verdict}</span>}
              </div>
            </div>
          )
        })}
      </div>
      {list.length >= 2 && <button className="btn" onClick={() => go(`compare?s=${list.slice(0, 4).map((w) => w.symbol).join(',')}`)}>Compare watchlist (first 4)</button>}
    </>
  )
}
