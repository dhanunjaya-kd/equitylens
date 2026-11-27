import { useEffect, useState } from 'react'
import { Loading } from '../components/ui'
import { api, cr, getMarket, go, num, ok, pct, recent, scoreColor, ticker, x } from '../util'

const ROWS = [
  ['Verdict', (a) => a.verdict.label],
  ['Overall score', (a) => a.scores.overall, 'score'],
  ['Business score', (a) => a.scores.business, 'score'],
  ['Valuation score', (a) => a.scores.valuation, 'score'],
  ['Market cap', (a) => cr(a.metrics.market_cap)],
  ['P/E', (a) => num(a.metrics.pe, 1)],
  ['PEG', (a) => num(a.metrics.peg, 2)],
  ['Sales growth 5y', (a) => pct(a.metrics.sales_cagr_5)],
  ['Profit growth 5y', (a) => pct(a.metrics.profit_cagr_5)],
  ['Profit growth 10y', (a) => pct(a.metrics.profit_cagr_10)],
  ['ROCE / ROE 5y', (a) => pct(a.metrics.is_financial ? a.metrics.roe_avg_5 : a.metrics.roce_avg_5)],
  ['Debt / equity', (a) => (a.metrics.is_financial ? 'n/a (lender)' : x(a.metrics.debt_to_equity))],
  ['Cash conversion 5y', (a) => (ok(a.metrics.cfo_to_pat_5) ? `${Math.round(a.metrics.cfo_to_pat_5 * 100)}%` : '—')],
  ['Promoter holding', (a) => pct(a.metrics.promoter_latest), null, 'IN'],
  ['Red flags (high)', (a) => a.flags.filter((f) => f.severity === 'high').length],
  ['Base return 3y', (a) => (a.projection.available ? pct(a.projection.horizons['3'].base.cagr) : '—')],
  ['Base return 5y', (a) => (a.projection.available ? pct(a.projection.horizons['5'].base.cagr) : '—')],
  ['Base return 10y', (a) => (a.projection.available ? pct(a.projection.horizons['10'].base.cagr) : '—')],
]

export default function Compare({ symbols }) {
  const [input, setInput] = useState(symbols.join(', '))
  const [d, setD] = useState(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    if (!symbols.length) return
    setBusy(true)
    api(`/api/compare?symbols=${encodeURIComponent(symbols.join(','))}`).then(setD).catch(() => setD({ items: [] })).finally(() => setBusy(false))
  }, [symbols.join(',')])
  const items = (d?.items || []).filter((i) => !i.error)
  const mk = getMarket()
  // in the US view a bare ticker means a US stock (AAPL -> US:AAPL); Indian symbols stay as typed
  const norm = (txt) => txt.replace(/\s/g, '').toUpperCase().split(',').filter(Boolean).map((t) => (mk === 'US' && !t.includes(':') ? `US:${t}` : t)).slice(0, 4).join(',')
  const goCmp = (txt) => go(`compare?s=${norm(txt)}`)
  const [picks, setPicks] = useState([])
  useEffect(() => { if (!symbols.length) api(`/api/rankings?sort=overall&market=${mk}`).then((r) => setPicks((r.rows || []).slice(0, 4).map((x) => x.symbol))).catch(() => {}) }, [mk, symbols.length])
  const mine = recent.all().map((r) => r.symbol).filter((sym) => (mk === 'US') === sym.startsWith('US:')).slice(0, 4)
  const allUS = items.length > 0 && items.every((i) => i.symbol.startsWith('US:'))
  return (
    <>
      <div className="card">
        <h3>Compare up to 4 stocks</h3>
        <div className="row">
          <input className="grow" value={input} placeholder={mk === 'US' ? 'e.g. AAPL, MSFT, NVDA' : 'e.g. TCS, INFY, HCLTECH'} onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && goCmp(input)} />
          <button className="btn primary" onClick={() => goCmp(input)}>Go</button>
        </div>
        <div className="small muted" style={{ marginTop: 6 }}>{mk === 'US' ? 'Comma-separated US tickers (AAPL, MSFT). Values in US dollars.' : 'Comma-separated NSE symbols (TCS, INFY). To add a US stock, type US: first (US:AAPL).'}</div>
        {!symbols.length && (picks.length > 0 || mine.length > 1) && (
          <div className="row wrapflex" style={{ gap: 6, marginTop: 10 }}>
            {picks.length > 1 && <button className="chip" onClick={() => go(`compare?s=${picks.join(',')}`)}>🏆 Top {picks.length} picks: {picks.map(ticker).join(', ')}</button>}
            {mine.length > 1 && <button className="chip" onClick={() => go(`compare?s=${mine.join(',')}`)}>🕘 Your recent: {mine.map(ticker).join(', ')}</button>}
          </div>
        )}
      </div>
      {busy && <Loading text="Researching all of them…" />}
      {!busy && items.length > 0 && (
        <div className="card">
          <div className="tbl-wrap">
            <table className="tbl">
              <thead><tr><th></th>{items.map((i) => <th key={i.symbol} style={{ cursor: 'pointer', color: 'var(--accent)' }} onClick={() => go(`stock/${i.symbol}`)}>{i.symbol}</th>)}</tr></thead>
              <tbody>
                {ROWS.filter((r) => !(allUS && r[3] === 'IN')).map(([label, f, kind]) => (
                  <tr key={label}><td>{label}</td>{items.map((i) => {
                    const v = f(i.analysis)
                    return <td key={i.symbol} style={kind === 'score' ? { color: scoreColor(v), fontWeight: 700 } : null}>{kind === 'score' ? (ok(v) ? Math.round(v) : '—') : v}</td>
                  })}</tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
      {d?.items?.filter((i) => i.error).map((i) => <div key={i.symbol} className="small t-bad">{i.symbol}: {i.error}</div>)}
    </>
  )
}
