import React, { Suspense, lazy, useEffect, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'

// If the app was updated while this window stayed open, load the new version.
const LOADED = (new URL(import.meta.url).pathname.split('/').pop() || '')
if (/^index-[\w-]+\.js$/.test(LOADED)) {
  const check = () => fetch('/api/health', { cache: 'no-store' }).then((r) => r.json())
    .then((h) => { if (h.ui && h.ui !== LOADED) window.location.reload() }).catch(() => {})
  setInterval(check, 60000)
  window.addEventListener('focus', check)
  document.addEventListener('visibilitychange', () => { if (!document.hidden) check() })
}
if ('serviceWorker' in navigator && import.meta.env.PROD) {
  navigator.serviceWorker.register('/sw.js').catch(() => {})
}
import './styles.css'
import { polyfillCountryFlagEmojis } from 'country-flag-emoji-polyfill'
import flagFont from 'country-flag-emoji-polyfill/dist/TwemojiCountryFlags.woff2?url'
import { BottomNav, Loading, MarketToggle, SearchBox, SideNav, TopActions } from './components/ui'
import { applyTheme, canGoBack, getMarket, getTheme, go, goBack, isDesktop, isUS, marketCurrency, parseHash, routeKey, setCurrency, setMarketLS, syncNavIdx, me } from './util'
import IndexStrip from './components/IndexStrip'
import BreakingBar from './components/BreakingBar'
import { Gate } from './components/Access'
import { ScanIndicator } from './components/Automation'

const Home = lazy(() => import('./pages/Home'))
const Stock = lazy(() => import('./pages/Stock'))
const Rankings = lazy(() => import('./pages/Rankings'))
const Watch = lazy(() => import('./pages/Watch'))
const Compare = lazy(() => import('./pages/Compare'))
const Screener = lazy(() => import('./pages/Screener'))
const Movers = lazy(() => import('./pages/Movers'))
const Heatmap = lazy(() => import('./pages/Heatmap'))
const PreMarket = lazy(() => import('./pages/PreMarket'))
const Account = lazy(() => import('./pages/Account'))
const Calendar = lazy(() => import('./pages/Calendar'))
const SmartMoney = lazy(() => import('./pages/SmartMoney'))
const FiiDii = lazy(() => import('./pages/FiiDii'))
const News = lazy(() => import('./pages/News'))
const IPO = lazy(() => import('./pages/IPO'))
const Terminal = lazy(() => import('./pages/Terminal'))
const Scanners = lazy(() => import('./pages/Scanners'))
const Patterns = lazy(() => import('./pages/Patterns'))
const Guide = lazy(() => import('./pages/Guide'))
const Portfolio = lazy(() => import('./pages/Portfolio'))
const Settings = lazy(() => import('./pages/AI').then((m) => ({ default: m.Settings })))

// Windows has no flag emoji: load a small bundled flag font so the flags show instead of 'IN' / 'US'
polyfillCountryFlagEmojis('Twemoji Country Flags', flagFont)

const KEEP = 4                                              // pages kept open for Back
const NO_KEEP = new Set(['terminal', 'settings', 'account'])  // live or private pages always start fresh

function renderPage(r) {
  return (
    r.page === 'home' ? <Home /> :
    r.page === 'stock' ? <Stock key={r.symbol} symbol={r.symbol} tab={r.tab} /> :
    r.page === 'rankings' ? <Rankings /> :
    r.page === 'watch' ? <Watch /> :
    r.page === 'screener' ? <Screener /> :
    r.page === 'movers' ? <Movers /> :
    r.page === 'heatmap' ? <Heatmap sector={r.sector} /> :
    r.page === 'premarket' ? <PreMarket /> :
    r.page === 'account' ? <Account /> :
    r.page === 'calendar' ? <Calendar tab={r.tab} /> :
    r.page === 'money' ? <SmartMoney tab={r.tab} /> :
    r.page === 'fiidii' ? <FiiDii tab={r.tab} /> :
    r.page === 'news' ? <News /> :
    r.page === 'ipo' ? <IPO tab={r.tab} /> :
    r.page === 'terminal' ? <Terminal /> :
    r.page === 'scanners' ? <Scanners /> :
    r.page === 'patterns' ? <Patterns /> :
    r.page === 'guide' ? <Guide /> :
    r.page === 'portfolio' ? <Portfolio /> :
    r.page === 'settings' ? <Settings /> :
    r.page === 'compare' ? <Compare symbols={r.symbols} /> :
    null
  )
}

function App() {
  const [route, setRoute] = useState(parseHash())
  const [market, setMarket] = useState(getMarket())
  const [desk, setDesk] = useState(isDesktop())
  const [theme, setTheme] = useState(getTheme())
  useEffect(() => { applyTheme(theme) }, [theme])
  const flipTheme = () => setTheme(theme === 'dark' ? 'light' : 'dark')
  useEffect(() => {
    const mq = window.matchMedia('(min-width: 1100px)')
    const on = () => setDesk(mq.matches)
    mq.addEventListener('change', on)
    return () => mq.removeEventListener('change', on)
  }, [])
  const changeMarket = (m) => {
    setMarketLS(m); setMarket(m); setCurrency(marketCurrency(m))
    if (route.page === 'stock' || route.page === 'compare') go('')
  }
  if (route.page !== 'stock') setCurrency(marketCurrency(market))
  // The last few pages stay open (hidden) so Back returns to the same list, filters and scroll position
  const [alive, setAlive] = useState(() => [{ key: routeKey(route), route }])
  const scrolls = useRef({})
  const aliveKeys = useRef([])
  aliveKeys.current = alive.map((p) => p.key)
  const curKey = useRef(routeKey(route))
  const [back, setBack] = useState(false)
  useEffect(() => {
    syncNavIdx(); setBack(canGoBack())
    const on = () => {
      syncNavIdx(); setBack(canGoBack())
      const r = parseHash(), k = routeKey(r), was = curKey.current
      if (k === was) { setRoute(r); setAlive((a) => a.map((p) => (p.key === k ? { key: k, route: r } : p))); return }
      scrolls.current[was] = window.scrollY
      curKey.current = k
      const kept = aliveKeys.current.includes(k)
      setAlive((a) => {
        const rest = a.filter((p) => p.key !== k && !NO_KEEP.has(p.route.page))
        return [...rest.slice(-(KEEP - 1)), { key: k, route: r }]
      })
      setRoute(r)
      requestAnimationFrame(() => {
        window.scrollTo(0, kept ? (scrolls.current[k] || 0) : 0)
        window.dispatchEvent(new Event('resize'))        // charts on a page shown again re-measure
      })
    }
    window.addEventListener('hashchange', on)
    return () => window.removeEventListener('hashchange', on)
  }, [])
  const navPage = route.page === 'stock' ? '' : route.page
  return (
    <div className={desk ? 'shell desk' : 'shell'}>
      {desk && <SideNav page={navPage} market={market} onMarket={changeMarket} theme={theme} onTheme={flipTheme} />}
      <div className="content">
      <header className="topbar">
        <div className="topbar-inner">
          {route.page !== 'home' && <button className="back-btn" title={back ? 'Back' : 'Home'} aria-label="Back" onClick={goBack}>
            <svg viewBox="0 0 24 24" width="20" height="20"><path d="M15 5l-7 7 7 7" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" /></svg>
          </button>}
          {!desk && <div className="brand" onClick={() => go('')} style={{ cursor: 'pointer' }}>
            <img src="/icon.svg" alt="" /><span className="bw">Equity<span>Lens</span></span>
          </div>}
          {!desk && <MarketToggle market={market} onChange={changeMarket} />}
          {route.page !== 'home' || desk ? <div className="grow"><SearchBox key={market} shortcut={desk} /></div> : <div className="grow" />}
          {!desk && <ScanIndicator />}
          {!desk && <button className="theme-btn" title="Light / dark theme" onClick={flipTheme}>{theme === 'dark' ? '☀️' : '🌙'}</button>}
          {!desk && me() && <button className="avatar-btn" title="My account" aria-label="My account" onClick={() => go('account')}>{(me().name || me().email || '?').slice(0, 1).toUpperCase()}</button>}
          {!desk && <button className="star" title="Settings" onClick={() => go('settings')}>⚙️</button>}
          {desk && <div className="small muted" style={{ whiteSpace: 'nowrap' }}>{market === 'US' ? '🇺🇸 US market · $' : '🇮🇳 Indian market · ₹'}</div>}
          {desk && <ScanIndicator />}
          {desk && <TopActions page={route.page} theme={theme} onTheme={flipTheme} />}
        </div>
      </header>
      <main className={route.page === 'terminal' ? 'wrap wrap-wide' : 'wrap'} key={market + theme}>
        <BreakingBar market={route.page === 'stock' ? (isUS(route.symbol) ? 'US' : 'IN') : market} />
        {route.page !== 'settings' && <IndexStrip market={route.page === 'stock' ? (isUS(route.symbol) ? 'US' : 'IN') : market} />}
        {alive.map((p) => (
          <div key={p.key} className="page-slot" style={p.key === routeKey(route) ? undefined : { display: 'none' }}>
            <Suspense fallback={<Loading text="Loading page…" />}>{renderPage(p.route)}</Suspense>
          </div>
        ))}
      </main>
      </div>
      {!desk && <BottomNav page={navPage} />}
    </div>
  )
}

createRoot(document.getElementById('root')).render(<Gate><App /></Gate>)
