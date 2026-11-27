import { useEffect, useState } from 'react'
import { Logo, SearchBox, ScoreRing } from '../components/ui'
import { api, flag, getMarket, go, pct, recent, ticker, watchlist, signed, num, ok } from '../util'

// 'Today' strip: the day's key facts from data the app already keeps; refreshes itself (every minute in market hours).
const istNow = () => new Date(new Date().toLocaleString('en-US', { timeZone: 'Asia/Kolkata' }))
const marketOpen = () => { const d = istNow(); const m = d.getHours() * 60 + d.getMinutes(); return d.getDay() > 0 && d.getDay() < 6 && m >= 555 && m <= 930 }
const crore = (v) => (ok(v) ? `${v < 0 ? '−' : '+'}₹${num(Math.abs(v))} Cr` : '—')
const tone = (v) => (!ok(v) ? 'var(--muted)' : v > 0 ? 'var(--good)' : v < 0 ? 'var(--bad)' : 'var(--muted)')

function TodayTile({ icon, k, children, onClick }) {
  return <div className={`today-tile ${onClick ? 'link' : ''}`} onClick={onClick}><div className="k">{icon} {k}</div><div className="b">{children}</div></div>
}

function TodayStrip({ mk }) {
  const [d, setD] = useState(null)
  const [moves, setMoves] = useState(null)
  const [at, setAt] = useState(null)
  const syms = watchlist.all().map((w) => w.symbol).filter((s) => (mk === 'US' ? s.startsWith('US:') : !s.startsWith('US:')))
  const load = () => {
    api(`/api/today?market=${mk}&symbols=${encodeURIComponent(syms.join(','))}`).then((x) => { setD(x); setAt(new Date()) }).catch(() => {})
    if (syms.length) api(`/api/watch/quotes?symbols=${encodeURIComponent(syms.slice(0, 40).join(','))}`).then((x) => setMoves(x.rows.filter((r) => ok(r.ret?.['1D'])))).catch(() => {})
  }
  useEffect(() => {
    load()
    const t = setInterval(load, marketOpen() ? 60000 : 600000)
    return () => clearInterval(t)
  }, [mk]) // eslint-disable-line react-hooks/exhaustive-deps
  if (!d) return null
  const up = (moves || []).slice().sort((a, b) => b.ret['1D'] - a.ret['1D'])
  const pm = d.premarket, fd = d.fiidii, ip = d.ipo, rs = d.results
  return (
    <div className="today">
      <div className="row between" style={{ marginBottom: 6 }}>
        <b>📅 Today</b>
        <span className="small muted">{marketOpen() ? '🟢 market open · updates every minute' : 'updates every 10 minutes'}{at ? ` · ${at.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })}` : ''}</span>
      </div>
      <div className="today-grid">
        {mk !== 'US' && (
          <TodayTile icon="🌅" k="NIFTY opening call" onClick={() => go('premarket')}>
            {pm ? <b style={{ color: pm.call === 'up' ? 'var(--good)' : pm.call === 'down' ? 'var(--bad)' : 'var(--muted)' }}>{pm.label}</b> : <span className="muted">No call frozen for today yet</span>}
            {pm?.built && <div className="small muted">made {pm.built}</div>}
          </TodayTile>
        )}
        {mk !== 'US' && fd && (
          <TodayTile icon="🏦" k={`FII / DII · ${new Date(fd.date + 'T12:00:00').toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })}`} onClick={() => go('fiidii')}>
            <div>FII <b style={{ color: tone(fd.fii) }}>{crore(fd.fii)}</b></div><div>DII <b style={{ color: tone(fd.dii) }}>{crore(fd.dii)}</b></div>
          </TodayTile>
        )}
        {mk !== 'US' && ip && (
          <TodayTile icon="🚀" k="IPOs" onClick={() => go('ipo')}>
            <div><b>{ip.open}</b> open ({ip.open_main} mainboard)</div>
            {ip.closing_today.length > 0 ? <div className="small" style={{ color: 'var(--warn)' }}>Closing today: {ip.closing_today.map((x) => `${x.symbol}${ok(x.times) ? ` ${num(x.times, 2)}x` : ''}`).join(', ')}</div>
              : ip.opening_next[0] ? <div className="small muted">Next: {ip.opening_next[0].symbol} opens {new Date(ip.opening_next[0].start + 'T12:00:00').toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })}</div> : null}
          </TodayTile>
        )}
        {mk !== 'US' && rs && (
          <TodayTile icon="📊" k="Results today" onClick={() => go('calendar')}>
            <div><b>{rs.count}</b> {rs.count === 1 ? 'company' : 'companies'}</div>
            {rs.mine.length > 0 ? <div className="small" style={{ color: 'var(--accent)' }}>★ yours: {rs.mine.join(', ')}</div>
              : rs.top.length > 0 ? <div className="small muted">{rs.top.slice(0, 3).map((x) => x.symbol).join(', ')}</div> : null}
          </TodayTile>
        )}
        {up.length > 0 && (
          <TodayTile icon="⭐" k="Watchlist today" onClick={() => go('watch')}>
            {[up[0], up.length > 1 ? up[up.length - 1] : null].filter(Boolean).map((r) => (
              <div key={r.symbol} className="row between"><span>{ticker(r.symbol)}</span><b style={{ color: tone(r.ret['1D']) }}>{signed(r.ret['1D'], 1, '%')}</b></div>
            ))}
            <div className="small muted">{up.filter((r) => r.ret['1D'] > 0).length} up · {up.filter((r) => r.ret['1D'] < 0).length} down</div>
          </TodayTile>
        )}
        <TodayTile icon="🔴" k="Breaking" onClick={() => go('news')}>
          {d.breaking?.length ? d.breaking.slice(0, 2).map((b, i) => <div key={i} className="small today-news">{b.title}</div>) : <span className="muted small">Nothing market-wide right now</span>}
        </TodayTile>
      </div>
    </div>
  )
}

export default function Home() {
  const [top, setTop] = useState([])
  const mk = getMarket()
  useEffect(() => { api(`/api/rankings?sort=overall&market=${mk}`).then((d) => setTop((d.rows || []).slice(0, 5))).catch(() => {}) }, [mk])
  const rec = recent.all(), watch = watchlist.all()
  return (
    <>
    <TodayStrip mk={mk} />
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
    </>
  )
}
