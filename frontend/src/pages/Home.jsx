import { useEffect, useState } from 'react'
import { Logo, SearchBox, ScoreRing } from '../components/ui'
import { api, flag, getMarket, go, pct, recent, ticker, watchlist } from '../util'

export default function Home() {
  const [top, setTop] = useState([])
  const mk = getMarket()
  useEffect(() => { api(`/api/rankings?sort=overall&market=${mk}`).then((d) => setTop((d.rows || []).slice(0, 5))).catch(() => {}) }, [mk])
  const rec = recent.all(), watch = watchlist.all()
  return (
    <div className="home-grid">
      <div>
      <div style={{ padding: '18px 2px 6px' }}>
        <h1 style={{ margin: '0 0 6px', fontSize: 24 }}>{mk === 'US' ? '🇺🇸 Research any US stock' : '🇮🇳 Research any Indian stock'}</h1>
        <div className="muted" style={{ marginBottom: 14 }}>
          {mk === 'US'
            ? 'NYSE & Nasdaq companies from official SEC filings: 10+ years of financials, forensics, valuation, chart outlook and a 3 / 5 / 10-year view.'
            : 'NSE & BSE companies: 10+ years of financials, forensics, valuation, chart outlook and a 3 / 5 / 10-year view.'}
        </div>
        <SearchBox autoFocus />
      </div>

      {mk !== 'US' && (
        <div className="card guide-cta" onClick={() => go('premarket')}>
          <span style={{ fontSize: 30 }}>🌅</span>
          <div className="grow"><b>Pre-market: how is NIFTY likely to open?</b>
            <div className="small muted">Overnight US, Asia, crude, gold, Bitcoin, rupee and FII flows, the opening call and its real track record.</div></div>
          <span className="btn small primary">Open →</span>
        </div>
      )}

      <div className="card guide-cta" onClick={() => go('guide')}>
        <span style={{ fontSize: 30 }}>📘</span>
        <div className="grow"><b>New to stocks? Learn to read a company in 10 minutes</b>
          <div className="small muted">11 simple steps, a 10-question checklist, a glossary and a walkthrough video.</div></div>
        <span className="btn small primary">Start →</span>
      </div>

      {rec.length > 0 && (
        <div className="card" style={{ marginTop: 14 }}>
          <h3>Recent</h3>
          {rec.map((r) => <span key={r.symbol} className="chip chip-logo" style={{ cursor: 'pointer' }} onClick={() => go(`stock/${r.symbol}`)}><Logo sym={r.symbol} name={r.name} size={18} />{flag(r.symbol)} {ticker(r.symbol)}</span>)}
        </div>
      )}
      {watch.length > 0 && (
        <div className="card">
          <h3>Watchlist</h3>
          {watch.map((r) => <span key={r.symbol} className="chip chip-logo" style={{ cursor: 'pointer' }} onClick={() => go(`stock/${r.symbol}`)}><Logo sym={r.symbol} name={r.name} size={18} /><span style={{ color: '#f59e0b' }}>★</span> {flag(r.symbol)} {ticker(r.symbol)}</span>)}
        </div>
      )}

      </div>
      <div className="home-right">
      <div className="card" style={{ marginTop: rec.length ? 0 : 14, padding: 0 }}>
        <div className="row between" style={{ padding: '14px 14px 4px' }}>
          <h3 style={{ margin: 0 }}>Top picks by score</h3>
          <button className="btn small" onClick={() => go('rankings')}>See all</button>
        </div>
        {top.length === 0 ? (
          <div className="muted small" style={{ padding: '6px 14px 14px' }}>
            No scan yet. Open <a href="#/rankings">Top Picks</a> and run a scan to rank the whole {mk === 'US' ? 'S&P 500' : 'NIFTY 500'}.
          </div>
        ) : top.map((r, i) => (
          <div key={r.symbol} className="rank-item" onClick={() => go(`stock/${r.symbol}`)}>
            <div className="rank-num">{i + 1}</div>
            <div className="ring-sm"><ScoreRing value={r.overall} size={44} /></div>
            <div className="grow">
              <div className="ellip"><Logo sym={r.symbol} name={r.name} size={20} /><b>{r.name}</b></div>
              <div className="small muted ellip">{r.sector} · base 5y {pct(r.base_5y)}/yr</div>
              <span className={`badge sm t-${r.tone} bg-${r.tone}`} style={{ marginTop: 4 }}>{r.verdict}</span>
            </div>
          </div>
        ))}
      </div>

      <div className="card">
        <h3>How it works</h3>
        <ul className="list">
          <li><span className="ic" style={{ color: 'var(--accent)' }}>1</span>Pulls the company's public financials: 10–12 years of P&L, balance sheet, cash flow, quarterly results, shareholding and peers.</li>
          <li><span className="ic" style={{ color: 'var(--accent)' }}>2</span>Scores growth, quality, balance-sheet strength, cash generation, ownership and valuation (0–100), and flags risks.</li>
          <li><span className="ic" style={{ color: 'var(--accent)' }}>3</span>Projects earnings and price for 3, 5 and 10 years under bear / base / bull assumptions you can see.</li>
        </ul>
        <p className="disclaimer">Model output from past numbers. It's a research aid, not investment advice — read the red flags and the company's own reports before investing.</p>
      </div>
      </div>
    </div>
  )
}
