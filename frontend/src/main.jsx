import React, { Suspense, lazy, useEffect, useState } from 'react'
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
import { applyTheme, getMarket, getTheme, go, isDesktop, isUS, marketCurrency, parseHash, setCurrency, setMarketLS, me } from './util'
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
const Guide = lazy(() => import('./pages/Guide'))
const Portfolio = lazy(() => import('./pages/Portfolio'))
const Settings = lazy(() => import('./pages/AI').then((m) => ({ default: m.Settings })))

// Windows has no flag emoji: load a small bundled flag font so the flags show instead of 'IN' / 'US'
polyfillCountryFlagEmojis('Twemoji Country Flags', flagFont)

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
  useEffect(() => {
    const on = () => { setRoute(parseHash()); window.scrollTo(0, 0) }
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
        <Suspense fallback={<Loading text="Loading page…" />}>
          {route.page === 'home' && <Home />}
          {route.page === 'stock' && <Stock key={route.symbol} symbol={route.symbol} tab={route.tab} />}
          {route.page === 'rankings' && <Rankings />}
          {route.page === 'watch' && <Watch />}
          {route.page === 'screener' && <Screener />}
          {route.page === 'movers' && <Movers />}
          {route.page === 'heatmap' && <Heatmap sector={route.sector} />}
          {route.page === 'premarket' && <PreMarket />}
          {route.page === 'account' && <Account />}
          {route.page === 'calendar' && <Calendar tab={route.tab} />}
          {route.page === 'money' && <SmartMoney tab={route.tab} />}
          {route.page === 'fiidii' && <FiiDii tab={route.tab} />}
          {route.page === 'news' && <News />}
          {route.page === 'ipo' && <IPO tab={route.tab} />}
          {route.page === 'terminal' && <Terminal />}
          {route.page === 'scanners' && <Scanners />}
          {route.page === 'guide' && <Guide />}
          {route.page === 'portfolio' && <Portfolio />}
          {route.page === 'settings' && <Settings />}
          {route.page === 'compare' && <Compare symbols={route.symbols} />}
        </Suspense>
      </main>
      </div>
      {!desk && <BottomNav page={navPage} />}
    </div>
  )
}

createRoot(document.getElementById('root')).render(<Gate><App /></Gate>)
