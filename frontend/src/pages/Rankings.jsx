import { useEffect, useRef, useState } from 'react'
import { ScoreRing } from '../components/ui'
import { ExplainList } from './AI'
import { ago, api, cr, getMarket, go, isDesktop, num, pct, scoreColor, signed, ticker } from '../util'

const SORTS = [
  ['overall', 'Overall score'], ['business', 'Business quality'], ['valuation', 'Cheapest (valuation)'],
  ['base_3y', 'Base return 3y'], ['base_5y', 'Base return 5y'], ['base_10y', 'Base return 10y'],
  ['profit_cagr_5', 'Profit growth 5y'], ['roce', 'ROCE / ROE'], ['market_cap', 'Market cap'],
]
const VERDICTS = ['High quality, fairly priced', 'High quality, but expensive', 'High quality, price data missing', 'Average — keep on watch', 'Good numbers, serious red flags', 'Weak — avoid for now', 'Loss-making — speculative', 'Not enough data']

export default function Rankings() {
  const [sort, setSort] = useState('overall')
  const [verdict, setVerdict] = useState('')
  const [q, setQ] = useState('')
  const [minCap, setMinCap] = useState(0)
  const [d, setD] = useState(null)
  const [scan, setScan] = useState(null)
  const poll = useRef()

  const mk = getMarket()
  const caps = mk === 'US' ? [[0, 'Any size'], [2000, 'Above $2 B'], [10000, 'Above $10 B'], [50000, 'Above $50 B'], [200000, 'Above $200 B']]
    : [[0, 'Any size'], [1000, 'Above ₹1,000 Cr'], [5000, 'Above ₹5,000 Cr'], [20000, 'Above ₹20,000 Cr'], [100000, 'Above ₹1 L Cr']]
  const load = () => {
    const p = new URLSearchParams({ sort, market: mk })
    if (verdict) p.set('verdict', verdict)
    if (q) p.set('q', q)
    if (minCap) p.set('min_mcap', minCap)
    api(`/api/rankings?${p}`).then((r) => { setD(r); setScan(r.scan) }).catch(() => setD({ rows: [] }))
  }
  useEffect(load, [sort, verdict, q, minCap])
  useEffect(() => {
    clearInterval(poll.current)
    if (scan?.running) poll.current = setInterval(async () => {
      const s = await api('/api/scan/status').catch(() => null)
      if (s) { setScan(s); if (!s.running || s.done % 10 === 0) load() }
    }, 4000)
    return () => clearInterval(poll.current)
  }, [scan?.running])

  const start = async (limit) => setScan(await api(`/api/scan/start?market=${mk}${limit ? `&limit=${limit}` : ''}`, { method: 'POST' }))
  const stop = async () => setScan(await api('/api/scan/stop', { method: 'POST' }))
  const rows = d?.rows || []

  return (
    <>
      <div className="card">
        <div className="row between wrapflex">
          <div>
            <h3 style={{ margin: 0 }}>{mk === 'US' ? '🇺🇸' : '🇮🇳'} Top Picks</h3>
            <div className="small muted">Every scanned company, ranked by the same rules.</div>
          </div>
          {scan?.running
            ? <button className="btn small" onClick={stop}>Stop scan</button>
            : <div className="row"><button className="btn small" onClick={() => start(30)}>Quick scan (30)</button><button className="btn primary small" onClick={() => start()}>Scan {mk === 'US' ? 'S&P 500' : 'NIFTY 500'}</button></div>}
        </div>
        {scan?.running && scan.market && scan.market !== mk && <div className="small t-warn" style={{ marginTop: 8 }}>A {scan.market === 'US' ? 'US' : 'Indian'} scan is running. Switch market to watch it.</div>}
        {scan?.running && scan.market === mk && (
          <>
            <div className="small" style={{ marginTop: 10 }}>Scanning {scan.current || '…'} — {scan.done}/{scan.total}{scan.failed ? ` · ${scan.failed} failed` : ''}</div>
            <div className="progress"><div style={{ width: `${scan.total ? (scan.done / scan.total) * 100 : 0}%` }} /></div>
            <div className="small muted" style={{ marginTop: 6 }}>A full scan takes 40–60 min (paced to stay polite to the data source). You can keep using the app.</div>
          </>
        )}
        {!scan?.running && scan?.finished_at && <div className="small muted" style={{ marginTop: 8 }}>Last scan finished {ago(scan.finished_at)} · {scan.done} companies · {scan.source}</div>}
      </div>

      <div className="card">
        <div className="grid2">
          <select value={sort} onChange={(e) => setSort(e.target.value)}>{SORTS.map(([k, l]) => <option key={k} value={k}>Sort: {l}</option>)}</select>
          <select value={minCap} onChange={(e) => setMinCap(+e.target.value)}>
            {caps.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </div>
        <input style={{ width: '100%', marginTop: 10 }} placeholder="Filter by name, symbol or sector" value={q} onChange={(e) => setQ(e.target.value)} />
        <div style={{ marginTop: 10 }}>
          <span className="chip" style={{ cursor: 'pointer', color: !verdict ? 'var(--accent)' : null }} onClick={() => setVerdict('')}>All</span>
          {VERDICTS.map((v) => <span key={v} className="chip" style={{ cursor: 'pointer', color: verdict === v ? 'var(--accent)' : null }} onClick={() => setVerdict(v)}>{v}</span>)}
        </div>
      </div>

      {isDesktop() && rows.length > 0 ? (
        <div className="card" style={{ padding: 0 }}>
          <div className="tbl-wrap" style={{ border: 0 }}>
            <table className="tbl rank-tbl">
              <thead><tr><th>#</th><th>Company</th><th>Score</th><th>Verdict</th><th>Mkt cap</th><th>P/E</th><th>ROCE</th><th>Profit 5y</th><th>Sales 5y</th><th>D/E</th><th>Base 3y</th><th>Base 5y</th><th>Base 10y</th><th>🚩</th></tr></thead>
              <tbody>{rows.map((r, i) => (
                <tr key={r.symbol} className="click" onClick={() => go(`stock/${r.symbol}`)}>
                  <td className="muted">{i + 1}</td>
                  <td style={{ minWidth: 220 }}><b>{r.name}</b><div className="small muted">{ticker(r.symbol)} · {r.sector || '—'}</div></td>
                  <td><b style={{ color: scoreColor(r.overall) }}>{r.overall ?? '—'}</b></td>
                  <td><span className={`badge sm t-${r.tone} bg-${r.tone}`}>{r.verdict}</span></td>
                  <td>{cr(r.market_cap)}</td><td>{num(r.pe, 1)}</td><td>{pct(r.roce)}</td>
                  <td>{pct(r.profit_cagr_5)}</td><td>{pct(r.sales_cagr_5)}</td><td>{num(r.debt_to_equity, 2)}</td>
                  <td>{signed(r.base_3y, 1, '%')}</td><td><b>{signed(r.base_5y, 1, '%')}</b></td><td>{signed(r.base_10y, 1, '%')}</td>
                  <td className={r.high_flags ? 't-bad' : 'muted'}>{r.high_flags || '–'}</td>
                </tr>))}
              </tbody>
            </table>
          </div>
        </div>
      ) : (
      <div className="card" style={{ padding: 0 }}>
        {rows.length === 0 ? (
          <div className="empty">{d ? 'No companies yet. Run a scan above, or open any stock — every stock you research is added here too.' : 'Loading…'}</div>
        ) : rows.map((r, i) => (
          <div key={r.symbol} className="rank-item" onClick={() => go(`stock/${r.symbol}`)}>
            <div className="rank-num">{i + 1}</div>
            <div className="ring-sm"><ScoreRing value={r.overall} size={44} /></div>
            <div className="grow">
              <div className="ellip"><b>{r.name}</b> <span className="small muted">{ticker(r.symbol)}</span></div>
              <div className="small muted ellip">{r.sector || '—'} · {cr(r.market_cap)} · P/E {num(r.pe, 1)}</div>
              <div className="small" style={{ marginTop: 3 }}>
                Base /yr: <b>{pct(r.base_3y)}</b> 3y · <b>{pct(r.base_5y)}</b> 5y · <b>{pct(r.base_10y)}</b> 10y
              </div>
              <div style={{ marginTop: 5 }}>
                <span className={`badge sm t-${r.tone} bg-${r.tone}`}>{r.verdict}</span>
                {r.high_flags > 0 && <span className="small t-bad"> · {r.high_flags} red flag{r.high_flags > 1 ? 's' : ''}</span>}
              </div>
            </div>
          </div>
        ))}
      </div>
      )}
      {rows.length > 0 && <div className="small muted" style={{ marginBottom: 12 }}>{rows.length} companies</div>}
      {rows.length > 0 && <ExplainList symbols={rows.map((r) => r.symbol)} title={`Top Picks sorted by ${sort}`} />}
      <p className="disclaimer">Rankings come from past numbers and stated assumptions. Treat the top of the list as a research shortlist, not a buy list.</p>
    </>
  )
}
