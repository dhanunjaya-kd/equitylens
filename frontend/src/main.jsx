import React, { useEffect, useState } from 'react'
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
import './styles.css'
import { polyfillCountryFlagEmojis } from 'country-flag-emoji-polyfill'
import flagFont from 'country-flag-emoji-polyfill/dist/TwemojiCountryFlags.woff2?url'
import { BottomNav, MarketToggle, SearchBox, SideNav } from './components/ui'
import { applyTheme, getMarket, getTheme, go, isDesktop, isUS, marketCurrency, parseHash, setCurrency, setMarketLS, me } from './util'
import Home from './pages/Home'
import Stock from './pages/Stock'
import Rankings from './pages/Rankings'
import Watch from './pages/Watch'
import Compare from './pages/Compare'
import Screener from './pages/Screener'
import Movers from './pages/Movers'
import Heatmap from './pages/Heatmap'
import PreMarket from './pages/PreMarket'
import Account from './pages/Account'
import Calendar from './pages/Calendar'
import IndexStrip from './components/IndexStrip'
import SmartMoney from './pages/SmartMoney'
import FiiDii from './pages/FiiDii'
import Guide from './pages/Guide'
import Portfolio from './pages/Portfolio'
import { Settings } from './pages/AI'
import { Gate } from './components/Access'

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
          {route.page !== 'home' || desk ? <div className="grow"><SearchBox key={market} /></div> : <div className="grow" />}
          {!desk && <button className="theme-btn" title="Light / dark theme" onClick={flipTheme}>{theme === 'dark' ? '☀️' : '🌙'}</button>}
          {!desk && me() && <button className="avatar-btn" title="My account" aria-label="My account" onClick={() => go('account')}>{(me().name || me().email || '?').slice(0, 1).toUpperCase()}</button>}
          {!desk && <button className="star" title="Settings" onClick={() => go('settings')}>⚙️</button>}
          {desk && <div className="small muted" style={{ whiteSpace: 'nowrap' }}>{market === 'US' ? '🇺🇸 US market · $' : '🇮🇳 Indian market · ₹'}</div>}
        </div>
      </header>
      <main className="wrap" key={market + theme}>
        {route.page !== 'settings' && <IndexStrip market={route.page === 'stock' ? (isUS(route.symbol) ? 'US' : 'IN') : market} />}
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
        {route.page === 'guide' && <Guide />}
        {route.page === 'portfolio' && <Portfolio />}
        {route.page === 'settings' && <Settings />}
        {route.page === 'compare' && <Compare symbols={route.symbols} />}
      </main>
      </div>
      {!desk && <BottomNav page={navPage} />}
    </div>
  )
}

createRoot(document.getElementById('root')).render(<Gate><App /></Gate>)
