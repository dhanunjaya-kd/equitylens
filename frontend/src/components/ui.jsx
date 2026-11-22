import { useEffect, useRef, useState } from 'react'
import { UNIVERSES, api, cur, getFno, getMarket, getUniv, go, logoUrl, ok, scoreColor, setFnoLS, setUnivLS, me } from '../util'

export function ScoreRing({ value, size = 84, label }) {
  const r = 34, c = 2 * Math.PI * r
  const v = ok(value) ? Math.max(0, Math.min(100, value)) : 0
  const col = scoreColor(value)
  return (
    <svg viewBox="0 0 84 84" width={size} height={size} role="img" aria-label={`${label || 'Score'} ${ok(value) ? value : 'n/a'}`}>
      <circle cx="42" cy="42" r={r} fill="none" stroke="var(--card2)" strokeWidth="8" />
      <circle cx="42" cy="42" r={r} fill="none" stroke={col} strokeWidth="8" strokeLinecap="round"
        strokeDasharray={`${(v / 100) * c} ${c}`} transform="rotate(-90 42 42)" />
      <text x="42" y={label ? 42 : 48} textAnchor="middle" fill="var(--text)" fontSize="20" fontWeight="800">{ok(value) ? Math.round(value) : '—'}</text>
      {label && <text x="42" y="57" textAnchor="middle" fill="var(--muted)" fontSize="9">{label}</text>}
    </svg>
  )
}

export function ScoreBar({ label, value, hint }) {
  return (
    <div className="scorebar">
      <div className="top"><span>{label}</span><b style={{ color: scoreColor(value) }}>{ok(value) ? Math.round(value) : 'n/a'}</b></div>
      <div className="track"><div className="fill" style={{ width: `${ok(value) ? value : 0}%`, background: scoreColor(value) }} /></div>
      {hint && <div className="small muted" style={{ marginTop: 3 }}>{hint}</div>}
    </div>
  )
}

export const Badge = ({ tone = 'neutral', children }) => <span className={`badge t-${tone} bg-${tone}`}>{children}</span>

export const Tile = ({ k, v, s, color }) => (
  <div className="tile"><div className="k">{k}</div><div className="v" style={color ? { color } : null}>{v}</div>{s && <div className="s">{s}</div>}</div>
)

export function Loading({ text = 'Loading…' }) {
  return <div className="empty"><div className="spinner" />{text}</div>
}

export function SearchBox({ autoFocus }) {
  const [q, setQ] = useState('')
  const [res, setRes] = useState([])
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const t = useRef()
  useEffect(() => {
    clearTimeout(t.current)
    if (q.trim().length < 2) { setRes([]); return }
    t.current = setTimeout(async () => {
      setBusy(true)
      try { const d = await api(`/api/search?q=${encodeURIComponent(q)}&market=${getMarket()}`); setRes(d.results || []); setOpen(true) }
      catch { setRes([]) } finally { setBusy(false) }
    }, 300)
  }, [q])
  const pick = (s) => { setOpen(false); setQ(''); go(`stock/${encodeURIComponent(s)}`) }
  return (
    <div className="search-box">
      <input autoFocus={autoFocus} value={q} placeholder={getMarket() === 'US' ? 'Search US stocks — ticker or name' : 'Search NSE/BSE stocks — name or symbol'}
        onChange={(e) => setQ(e.target.value)} onFocus={() => res.length && setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 200)}
        onKeyDown={(e) => { if (e.key === 'Enter') { if (res[0]) pick(res[0].symbol); else if (q.trim()) pick(q.trim().toUpperCase()) } }} />
      {open && (res.length > 0 || busy) && (
        <div className="suggest">
          {busy && !res.length && <div className="muted">Searching…</div>}
          {res.map((r) => (
            <div key={r.symbol + r.name} onMouseDown={() => pick(r.symbol)} className="sg-row">
              <Logo sym={r.symbol} name={r.name} size={24} />
              <b>{r.name}</b> <span className="muted small">{r.symbol.replace(/^US:/, '')}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

/** Financial table: {columns, rows:{label:[...]}} */
export function DataTable({ table, last = 0, pctRows = true }) {
  if (!table || !table.columns?.length) return <div className="muted small">No data.</div>
  let cols = table.columns.map((c, i) => [c, i])
  if (last) cols = cols.slice(-last)
  const fmtCell = (label, v) => {
    if (v === null || v === undefined) return ''
    if (pctRows && /%/.test(label)) return `${v}%`
    return Math.abs(v) >= 1000 ? new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 }).format(v) : (+v).toLocaleString('en-IN', { maximumFractionDigits: 2 })
  }
  return (
    <div className="tbl-wrap">
      <table className="tbl">
        <thead><tr><th></th>{cols.map(([c]) => <th key={c}>{c}</th>)}</tr></thead>
        <tbody>
          {Object.entries(table.rows).map(([label, vals]) => (
            <tr key={label}><td>{label.replace(' in Rs', ` (${cur()})`)}</td>{cols.map(([c, i]) => <td key={c}>{fmtCell(label, vals[i])}</td>)}</tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

const I = {
  sun: <g fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round"><path d="M4 18h16M7 18a5 5 0 0 1 10 0M12 8V5M5.6 11.6 3.8 9.8M18.4 11.6l1.8-1.8" /></g>,
  search: <path d="M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zm9 16-4.3-4.3" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />,
  rank: <path d="M5 20V10m7 10V4m7 16v-7" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />,
  star: <path d="m12 3 2.8 5.7 6.2.9-4.5 4.4 1 6.2L12 17.3 6.5 20.2l1-6.2L3 9.6l6.2-.9z" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />,
  grid: <g fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinejoin="round"><rect x="3.5" y="3.5" width="10" height="10" rx="1.5" /><rect x="15" y="3.5" width="5.5" height="6" rx="1.5" /><rect x="15" y="11" width="5.5" height="9.5" rx="1.5" /><rect x="3.5" y="15" width="10" height="5.5" rx="1.5" /></g>,
  fire: <path d="M12 3c1 3.5 4.5 5 4.5 9.5A4.5 4.5 0 0 1 12 17a4.5 4.5 0 0 1-4.5-4.5c0-2 1-3.2 2-4 .2 1.6 1 2.6 2 3 0-3 0-5.5.5-8.5zM6 21h12" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" />,
  filter: <path d="M4 5h16l-6 7.5V19l-4 1.5v-8z" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinejoin="round" />,
  compare: <path d="M8 4v16M16 4v16M4 8h8M12 16h8" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />,
  news: <g fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"><rect x="3.5" y="4.5" width="14" height="15" rx="1.5" /><path d="M17.5 8.5h3v9.5a1.5 1.5 0 0 1-3 0zM6.5 8h8M6.5 11.5h8M6.5 15h5" /></g>,
  bank: <g fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"><path d="M3.5 9.5 12 4.5l8.5 5" /><path d="M5.5 10v7.5M10 10v7.5M14 10v7.5M18.5 10v7.5" /><path d="M3.5 20h17" /></g>,
  money: <g fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="8.5" /><path d="m15.5 8.5-2.2 4.8-4.8 2.2 2.2-4.8z" /></g>,
  book: <g fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"><path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v15H6.5A2.5 2.5 0 0 0 4 20.5z" /><path d="M4 20.5A2.5 2.5 0 0 0 6.5 23H20v-5" /></g>,
  brief: <g fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="7" width="18" height="13" rx="2.5" /><path d="M8.5 7V5.5A1.5 1.5 0 0 1 10 4h4a1.5 1.5 0 0 1 1.5 1.5V7M3 12.5h18" /></g>,
  cal: <g fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round"><rect x="3.5" y="5" width="17" height="15" rx="2.5" /><path d="M3.5 10h17M8 3v4M16 3v4" /><circle cx="8.5" cy="14.5" r=".6" fill="currentColor" /><circle cx="12" cy="14.5" r=".6" fill="currentColor" /></g>,
}

// Company logo (real logo when found, coloured initials otherwise; downloaded once by the backend)
export function Logo({ sym, name = '', size = 28 }) {
  const [bad, setBad] = useState(false)
  const ini = (String(name || sym).replace(/^US:/, '').match(/[A-Za-z0-9]+/g) || ['?']).filter((w) => !/^(ltd|limited|inc|corp|co|the|plc)$/i.test(w))
  if (bad) return <span className="logo logo-ini" style={{ width: size, height: size, fontSize: size * 0.38 }}>{((ini[0] || '?')[0] + (ini[1] ? ini[1][0] : (ini[0] || '').slice(1, 2))).toUpperCase()}</span>
  return <img className="logo" src={logoUrl(sym, name)} width={size} height={size} loading="lazy" alt="" onError={() => setBad(true)} style={{ width: size, height: size }} />
}

export function BottomNav({ page }) {
  // Search lives in the top bar (logo = home), so the bar keeps 6 tabs
  const items = [['movers', 'movers', 'Movers', I.fire], ['calendar', 'calendar', 'Calendar', I.cal], ['money', 'money', 'Money', I.money], ['rankings', 'rankings', 'Top Picks', I.rank], ['screener', 'screener', 'Screener', I.filter], ['portfolio', 'portfolio', 'Portfolio', I.brief]]
  return (
    <nav className="bottomnav">
      {items.map(([k, path, label, icon]) => (
        <button key={k} className={page === k ? 'on' : ''} onClick={() => go(path)}>
          <svg viewBox="0 0 24 24">{icon}</svg>{label}
        </button>
      ))}
    </nav>
  )
}

// F&O-only switch: shown for the Indian market; every list listens to the same setting
export function useFno() {
  const [v, setV] = useState(getFno())
  useEffect(() => { const on = () => setV(getFno()); window.addEventListener('eql-fno', on); return () => window.removeEventListener('eql-fno', on) }, [])
  return [v, (x) => setFnoLS(x)]
}
export function FnoToggle({ count }) {
  const [fno, setFno] = useFno()
  if (getMarket() !== 'IN') return null
  return (
    <button className={`tab fno-tab ${fno ? 'on' : ''}`} title="Show only stocks that have futures & options on NSE" onClick={() => setFno(!fno)}>
      🎯 F&O stocks only{ok(count) ? ` · ${count}` : ''}
    </button>
  )
}
export function useUniv() {
  const [v, setV] = useState(getUniv())
  useEffect(() => { const on = () => setV(getUniv()); window.addEventListener('eql-univ', on); return () => window.removeEventListener('eql-univ', on) }, [])
  return [v, (x) => setUnivLS(x)]
}
// NIFTY 50 · NIFTY 100 · NIFTY 500 · All NSE (India only)
export function UniverseChips({ counts }) {
  const [u, setU] = useUniv()
  if (getMarket() !== 'IN') return null
  return (
    <div className="univ">
      {UNIVERSES.map(([k, l]) => (
        <button key={k} className={u === k ? 'on' : ''} onClick={() => setU(k)}>{l}{counts?.[k] ? <span className="cnt">{counts[k]}</span> : null}</button>
      ))}
    </div>
  )
}
export const FnoBadge = ({ lot }) => <span className="fno-badge" title={lot ? `F&O stock · lot size ${lot}` : 'F&O stock'}>F&O</span>

export function MarketToggle({ market, onChange }) {
  return (
    <div className="mkt">
      {[['IN', '🇮🇳', 'IND'], ['US', '🇺🇸', 'US']].map(([k, f, l]) => (
        <button key={k} className={market === k ? 'on' : ''} onClick={() => onChange(k)} aria-label={`${l} stocks`}>
          <span className="fl">{f}</span>{l}
        </button>
      ))}
    </div>
  )
}

export function SideNav({ page, market, onMarket, theme, onTheme }) {
  const items = [['home', '', 'Search', I.search], ['premarket', 'premarket', 'Pre-market', I.sun], ['movers', 'movers', 'Market Movers', I.fire], ['news', 'news', 'News', I.news], ['heatmap', 'heatmap', 'Heatmap', I.grid], ['calendar', 'calendar', 'Calendar', I.cal], ['money', 'money', 'Smart Money', I.money], ['fiidii', 'fiidii', 'FII / DII', I.bank], ['portfolio', 'portfolio', 'My Portfolio', I.brief], ['rankings', 'rankings', 'Top Picks', I.rank], ['screener', 'screener', 'Screener', I.filter],
    ['watch', 'watch', 'Watchlist', I.star], ['compare', 'compare', 'Compare', I.compare], ['guide', 'guide', 'Beginner guide', I.book]]
  return (
    <aside className="sidenav">
      <div className="brand side" onClick={() => go('')}><img src="/icon.svg" alt="" />Equity<span>Lens</span></div>
      <div style={{ margin: '4px 6px 18px' }}><MarketToggle market={market} onChange={onMarket} /></div>
      {items.map(([k, path, label, icon]) => (
        <button key={k} className={`sn ${page === k ? 'on' : ''}`} onClick={() => go(path)}><svg viewBox="0 0 24 24">{icon}</svg>{label}</button>
      ))}
      <div className="grow" />
      <button className="sn" onClick={onTheme}><span style={{ width: 22, textAlign: 'center' }}>{theme === 'dark' ? '☀️' : '🌙'}</span>{theme === 'dark' ? 'Light mode' : 'Dark mode'}</button>
      {me() && <button className={`sn ${page === 'account' ? 'on' : ''}`} onClick={() => go('account')}><span className="avatar sm" aria-hidden="true">{(me().name || me().email || '?').slice(0, 1).toUpperCase()}</span>{me().name || 'My account'}</button>}
      <button className={`sn ${page === 'settings' ? 'on' : ''}`} onClick={() => go('settings')}><span style={{ width: 22, textAlign: 'center' }}>⚙️</span>Settings</button>
      <div className="small muted" style={{ padding: '10px 12px 0', lineHeight: 1.5 }}>Research aid, not investment advice.</div>
    </aside>
  )
}
