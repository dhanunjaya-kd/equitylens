import React, { useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import './styles.css'
import { BottomNav, MarketToggle, SearchBox } from './components/ui'
import { getMarket, go, marketCurrency, parseHash, setCurrency, setMarketLS } from './util'
import Home from './pages/Home'
import Stock from './pages/Stock'
import Rankings from './pages/Rankings'
import Watch from './pages/Watch'
import Compare from './pages/Compare'
import Screener from './pages/Screener'
import { Settings } from './pages/AI'

function App() {
  const [route, setRoute] = useState(parseHash())
  const [market, setMarket] = useState(getMarket())
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
  return (
    <>
      <header className="topbar">
        <div className="topbar-inner">
          <div className="brand" onClick={() => go('')} style={{ cursor: 'pointer' }}>
            <img src="/icon.svg" alt="" /><span className="bw">Equity<span>Lens</span></span>
          </div>
          <MarketToggle market={market} onChange={changeMarket} />
          {route.page !== 'home' ? <div className="grow"><SearchBox key={market} /></div> : <div className="grow" />}
          <button className="star" title="AI settings" onClick={() => go('settings')}>⚙️</button>
        </div>
      </header>
      <main className="wrap" key={market}>
        {route.page === 'home' && <Home />}
        {route.page === 'stock' && <Stock key={route.symbol} symbol={route.symbol} tab={route.tab} />}
        {route.page === 'rankings' && <Rankings />}
        {route.page === 'watch' && <Watch />}
        {route.page === 'screener' && <Screener />}
        {route.page === 'settings' && <Settings />}
        {route.page === 'compare' && <Compare symbols={route.symbols} />}
      </main>
      <BottomNav page={route.page === 'stock' ? '' : route.page} />
    </>
  )
}

createRoot(document.getElementById('root')).render(<App />)
