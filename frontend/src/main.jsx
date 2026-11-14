import React, { useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import './styles.css'
import { BottomNav, SearchBox } from './components/ui'
import { go, parseHash } from './util'
import Home from './pages/Home'
import Stock from './pages/Stock'
import Rankings from './pages/Rankings'
import Watch from './pages/Watch'
import Compare from './pages/Compare'
import Screener from './pages/Screener'
import { Settings } from './pages/AI'

function App() {
  const [route, setRoute] = useState(parseHash())
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
            <img src="/icon.svg" alt="" />Equity<span>Lens</span>
          </div>
          {route.page !== 'home' ? <div className="grow"><SearchBox /></div> : <div className="grow" />}
          <button className="star" title="AI settings" onClick={() => go('settings')}>⚙️</button>
        </div>
      </header>
      <main className="wrap">
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
