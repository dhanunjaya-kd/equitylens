import { useEffect, useState } from 'react'
import { api, go, me, watchlist } from '../util'

const KEY = 'eql_breaking_seen'
const seen = () => { try { return JSON.parse(localStorage.getItem(KEY) || '[]') } catch { return [] } }

// A red bar on every page while something serious is happening: a market-wide event two publishers report,
// a central-bank announcement, or a main index moving 2%+ today. Dismissed items stay dismissed.
export default function BreakingBar({ market }) {
  const [items, setItems] = useState([]), [hid, setHid] = useState(seen())
  useEffect(() => {
    const load = () => api(`/api/news/breaking?market=${market}`).then((d) => setItems(d.items || [])).catch(() => {})
    load()
    const t = setInterval(load, 3 * 60 * 1000)
    return () => clearInterval(t)
  }, [market])
  useEffect(() => {   // keep the Telegram alerts' watchlist in step with this device's watchlists (owner only)
    if (me() && me().role !== 'owner') return
    api('/api/alerts', { method: 'POST', body: JSON.stringify({ watch: watchlist.all().map((i) => i.symbol) }), headers: { 'Content-Type': 'application/json' } }).catch(() => {})
  }, [])
  const it = items.find((i) => !hid.includes(i.id))
  if (!it) return null
  const close = (e) => { e.stopPropagation(); const h = [...hid, it.id].slice(-100); setHid(h); try { localStorage.setItem(KEY, JSON.stringify(h)) } catch { /* ignore */ } }
  const open = () => (it.url ? window.open(it.url, '_blank', 'noopener') : go('news'))
  const t = new Date(it.time).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })
  return (
    <div className="brk" onClick={open} role="button">
      <span className="brk-pill">BREAKING</span>
      <span className="brk-title">{it.title}</span>
      <span className="brk-meta">{(it.sources || []).map((s) => s.name).slice(0, 2).join(', ')} · {t}{items.filter((i) => !hid.includes(i.id)).length > 1 ? ` · +${items.filter((i) => !hid.includes(i.id)).length - 1} more` : ''}</span>
      <button className="brk-x" onClick={close} aria-label="Dismiss">✕</button>
    </div>
  )
}
