import { useEffect, useRef, useState } from 'react'
import { UNIVERSES, US_UNIVERSES, getUsUniv, setUsUnivLS, api, cur, getFno, getMarket, getUniv, go, logoUrl, ok, scoreColor, setFnoLS, setUnivLS, me } from '../util'

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

export function SearchBox({ autoFocus, shortcut }) {
  const [q, setQ] = useState('')
  const [res, setRes] = useState([])
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const t = useRef()
  const inp = useRef()
  useEffect(() => {
    if (!shortcut) return undefined
    const onKey = (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault(); inp.current?.focus(); inp.current?.select()
      } else if (e.key === '/' && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName || '')) {
        e.preventDefault(); inp.current?.focus()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [shortcut])
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
      <input ref={inp} autoFocus={autoFocus} value={q} placeholder={getMarket() === 'US' ? 'Search US stocks — ticker or name' : 'Search NSE/BSE stocks — name or symbol'}
        onChange={(e) => setQ(e.target.value)} onFocus={() => res.length && setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 200)}
        onKeyDown={(e) => { if (e.key === 'Enter') { if (res[0]) pick(res[0].symbol); else if (q.trim()) pick(q.trim().toUpperCase()) } }} />
      {shortcut && !q && <span className="kbd-hint">Ctrl+K</span>}
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
  rocket: <g fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"><path d="M12 15l-3-3c1.5-4 4.5-7 9-8-1 4.5-4 7.5-6 11z" /><path d="M9 12H5l2-3h4M12 15v4l3-2v-4" /><path d="M6.5 17.5c-1 .5-1.5 2-1.5 2s1.5-.5 2-1.5" /></g>,
  term: <g fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="4" width="18" height="14" rx="2" /><path d="M7 14l3-3 2 2 4-5M8 21h8" /></g>,
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
  pattern: <g fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"><path d="M3 17l4-8 4 6 4-9 6 11" /><path d="M3 20h18" /></g>,
  radar: <g fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="8.5" /><circle cx="12" cy="12" r="4.5" /><path d="M12 12l5.5-5.5" /></g>,
  cal: <g fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round"><rect x="3.5" y="5" width="17" height="15" rx="2.5" /><path d="M3.5 10h17M8 3v4M16 3v4" /><circle cx="8.5" cy="14.5" r=".6" fill="currentColor" /><circle cx="12" cy="14.5" r=".6" fill="currentColor" /></g>,
}

// Company logo (real logo when found, coloured initials otherwise; downloaded once by the backend)
export function Logo({ sym, name = '', size = 28 }) {
  const [bad, setBad] = useState(false)
  const ini = (String(name || sym).replace(/^US:/, '').match(/[A-Za-z0-9]+/g) || ['?']).filter((w) => !/^(ltd|limited|inc|corp|co|the|plc)$/i.test(w))
  if (bad) return <span className="logo logo-ini" style={{ width: size, height: size, fontSize: size * 0.38 }}>{((ini[0] || '?')[0] + (ini[1] ? ini[1][0] : (ini[0] || '').slice(1, 2))).toUpperCase()}</span>
  return <img className="logo" src={logoUrl(sym, name)} width={size} height={size} loading="lazy" alt="" onError={() => setBad(true)} style={{ width: size, height: size }} />
}

// Every page, for the side panel (desktop) and the "More" sheet (phone / tablet): one list, so both show the same pages
export function navItems(market) {
  return [['home', '', 'Search', I.search], ['premarket', 'premarket', 'Pre-market', I.sun], ['movers', 'movers', 'Market Movers', I.fire], ['scanners', 'scanners', 'Scanners', I.radar], ['patterns', 'patterns', 'Chart patterns', I.pattern], ['news', 'news', 'News', I.news], ['terminal', 'terminal', 'Terminal', I.term], ['ipo', 'ipo', 'IPO research', I.rocket], ['heatmap', 'heatmap', 'Heatmap', I.grid], ['calendar', 'calendar', 'Calendar', I.cal], ['money', 'money', 'Smart Money', I.money], ['fiidii', 'fiidii', 'FII / DII', I.bank], ['portfolio', 'portfolio', 'My Portfolio', I.brief], ['rankings', 'rankings', 'Top Picks', I.rank], ['screener', 'screener', 'Screener', I.filter],
    ['watch', 'watch', 'Watchlist', I.star], ['compare', 'compare', 'Compare', I.compare], ['guide', 'guide', 'Beginner guide', I.book]]
    .filter(([k]) => market !== 'US' || !IN_ONLY.includes(k))
    .map(([k, path, label, icon]) => [k, path, market === 'US' && k === 'fiidii' ? 'Institutions' : label, icon])
}
const MORE_ICON = <g fill="currentColor"><circle cx="5" cy="12" r="2" /><circle cx="12" cy="12" r="2" /><circle cx="19" cy="12" r="2" /></g>

export function BottomNav({ page }) {
  // Search lives in the top bar (logo = home); 5 favourite tabs + "More", which opens every page
  const [open, setOpen] = useState(false)
  const items = [['movers', 'movers', 'Movers', I.fire], ['calendar', 'calendar', 'Calendar', I.cal], ['money', 'money', 'Money', I.money], ['rankings', 'rankings', 'Top Picks', I.rank], ['portfolio', 'portfolio', 'Portfolio', I.brief]]
  const all = navItems(getMarket())
  const inMore = !items.some(([k]) => k === page) && all.some(([k]) => k === page)
  const nav = (path) => { setOpen(false); go(path) }
  useEffect(() => { if (!open) return undefined; const k = (e) => e.key === 'Escape' && setOpen(false); window.addEventListener('keydown', k); return () => window.removeEventListener('keydown', k) }, [open])
  return (
    <>
      {open && (
        <div className="more-sheet" onClick={() => setOpen(false)}>
          <div className="more-box" onClick={(e) => e.stopPropagation()}>
            <div className="row between" style={{ marginBottom: 10 }}><b>All pages</b><button className="btn small" onClick={() => setOpen(false)}>Close</button></div>
            <div className="more-grid">
              {all.map(([k, path, label, icon]) => (
                <button key={k} className={page === k ? 'on' : ''} onClick={() => nav(path)}><svg viewBox="0 0 24 24">{icon}</svg><span>{label}</span></button>
              ))}
              <button className={page === 'settings' ? 'on' : ''} onClick={() => nav('settings')}><span style={{ fontSize: 20 }}>⚙️</span><span>Settings</span></button>
            </div>
          </div>
        </div>
      )}
      <nav className="bottomnav">
        {items.map(([k, path, label, icon]) => (
          <button key={k} className={page === k ? 'on' : ''} onClick={() => nav(path)}>
            <svg viewBox="0 0 24 24">{icon}</svg>{label}
          </button>
        ))}
        <button className={open || inMore ? 'on' : ''} onClick={() => setOpen(!open)} aria-label="All pages">
          <svg viewBox="0 0 24 24">{MORE_ICON}</svg>More
        </button>
      </nav>
    </>
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
export function useUsUniv() {
  const [v, setV] = useState(getUsUniv())
  useEffect(() => { const on = () => setV(getUsUniv()); window.addEventListener('eql-us-univ', on); return () => window.removeEventListener('eql-us-univ', on) }, [])
  return [v, (x) => { setUsUnivLS(x); setV(x) }]
}
export function UsUniverseChips() {
  const [u, setU] = useUsUniv()
  if (getMarket() !== 'US') return null
  return <div className="univ">{US_UNIVERSES.map(([k, l]) => <button key={k} className={u === k ? 'on' : ''} onClick={() => setU(k)}>{l}</button>)}</div>
}
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

// Desktop top-right: theme, account, settings (moved out of the side panel)
export function TopActions({ page, theme, onTheme }) {
  const u = me()
  return (
    <div className="top-actions">
      <button className="top-ic" title={theme === 'dark' ? 'Light mode' : 'Dark mode'} aria-label={theme === 'dark' ? 'Light mode' : 'Dark mode'} onClick={onTheme}>
        <svg viewBox="0 0 24 24">{theme === 'dark'
          ? <g fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round"><circle cx="12" cy="12" r="4" /><path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4M5.3 18.7l1.4-1.4M17.3 6.7l1.4-1.4" /></g>
          : <path fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinejoin="round" d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z" />}</svg>
      </button>
      {u && <button className={`top-ic av ${page === 'account' ? 'on' : ''}`} title={u.name || u.email || 'My account'} aria-label="My account" onClick={() => go('account')}>{(u.name || u.email || '?').slice(0, 1).toUpperCase()}</button>}
      <button className={`top-ic ${page === 'settings' ? 'on' : ''}`} title="Settings" aria-label="Settings" onClick={() => go('settings')}>
        <svg viewBox="0 0 24 24"><g fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round"><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" /></g></svg>
      </button>
    </div>
  )
}

// Pages that exist for one market only: shown in place of the page when the other market is selected
export function MarketOnly({ market, what }) {
  return (
    <div className="card" style={{ textAlign: 'center', padding: '40px 20px' }}>
      <div style={{ fontSize: 34 }}>{market === 'IN' ? '🇮🇳' : '🇺🇸'}</div>
      <h3 style={{ margin: '8px 0 6px' }}>{what} is for the {market === 'IN' ? 'Indian' : 'US'} market</h3>
      <div className="muted small">You're in the {market === 'IN' ? 'US' : 'IND'} view, which shows {market === 'IN' ? 'US' : 'Indian'} data only. Switch to {market === 'IN' ? '🇮🇳 IND' : '🇺🇸 US'} at the top to open it.</div>
    </div>
  )
}

const IN_ONLY = ['premarket']

export function SideNav({ page, market, onMarket, theme, onTheme }) {
  const items = navItems(market)
  // Icons only until the mouse rests on the panel; then it opens over the page. The pin keeps it open (remembered).
  const [pinned, setPinned] = useState(() => { try { return localStorage.getItem('eql_nav_pin') === '1' } catch { return false } })
  const [hover, setHover] = useState(false)
  const timer = useRef(null)
  // The menu never covers the page: when it opens (pinned or on hover) the page column narrows beside it
  const wide = pinned || hover
  useEffect(() => { try { localStorage.setItem('eql_nav_pin', pinned ? '1' : '0') } catch { /* ignore */ } }, [pinned])
  useEffect(() => {
    document.body.classList.toggle('nav-wide', wide)
    const t = setTimeout(() => window.dispatchEvent(new Event('resize')), 220)   // charts re-measure the new page width
    return () => clearTimeout(t)
  }, [wide])
  useEffect(() => () => clearTimeout(timer.current), [])
  const enter = () => { clearTimeout(timer.current); timer.current = setTimeout(() => setHover(true), 220) }
  const leave = () => { clearTimeout(timer.current); timer.current = setTimeout(() => setHover(false), 200) }
  const nav = (path) => { go(path); if (!pinned) { clearTimeout(timer.current); setHover(false) } }
  const other = market === 'IN' ? 'US' : 'IN'
  return (
    <aside className={`sidenav ${wide ? 'wide' : 'slim'} ${pinned ? 'pinned' : ''}`} onMouseEnter={enter} onMouseLeave={leave}>
      <div className="brand side" onClick={() => nav('')} title="EquityLens"><img src="/icon.svg" alt="" /><i className="sn-label sn-brand">Equity<span>Lens</span></i></div>
      <button className={`sn-pin ${pinned ? 'on' : ''}`} onClick={() => setPinned(!pinned)} title={pinned ? 'Unpin: show icons only' : 'Pin: keep the menu open'} aria-label={pinned ? 'Unpin menu' : 'Pin menu open'}>
        <svg viewBox="0 0 24 24"><g fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M9 4h6l-1 5 3 3v2H7v-2l3-3z" /><path d="M12 14v6" /></g></svg>
      </button>
      <div className="sn-mkt"><MarketToggle market={market} onChange={onMarket} /></div>
      <button className="sn-mkt-mini" onClick={() => onMarket(other)} title={`${market === 'IN' ? 'Indian' : 'US'} market. Click for ${other === 'IN' ? 'Indian' : 'US'}`}>
        <span className="fl">{market === 'IN' ? '🇮🇳' : '🇺🇸'}</span>{market === 'IN' ? 'IN' : 'US'}
      </button>
      {items.map(([k, path, label, icon]) => (
        <button key={k} className={`sn ${page === k ? 'on' : ''}`} onClick={() => nav(path)} title={wide ? undefined : label} aria-label={label}>
          <svg viewBox="0 0 24 24">{icon}</svg><span className="sn-label">{label}</span>
        </button>
      ))}
      <div className="grow" />
      <div className="small muted sn-foot">Research aid, not investment advice.</div>
    </aside>
  )
}
