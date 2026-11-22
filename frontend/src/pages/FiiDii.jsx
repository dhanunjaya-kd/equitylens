import { useEffect, useMemo, useState } from 'react'
import { api, getMarket, go, signed } from '../util'
import { C_IDX, Chart, Kpi, Legend, Progress, Tested, dmy, int, ord, tone, us0 } from '../components/FlowCharts'
import India from './FiiDiiIndia'

// ---------------------------------------------------------------- US
const GROUPS = ['asset_mgr', 'lev_funds', 'dealer', 'other', 'nonrep']
const GC = { asset_mgr: '#60a5fa', lev_funds: '#f97316', dealer: '#a78bfa', other: '#94a3b8', nonrep: '#22c55e' }
function USView({ d }) {
  const [code, setCode] = useState('13874A'), [rng, setRng] = useState(156)
  const m = d.markets?.[code]
  const idx = useMemo(() => Object.fromEntries(d.index?.[code] || []), [d.index, code])
  if (!m || !m.latest) {
    return <><Progress st={d.backfill} what="CFTC's weekly reports (about 8 years)" /><div className="card empty">No CFTC report saved yet.{d.error ? ` ${d.error}` : ''}</div></>
  }
  const near = (iso) => { for (let k = 0; k < 6; k++) { const x = new Date(new Date(`${iso}T12:00:00`).getTime() + k * 864e5).toISOString().slice(0, 10); if (idx[x]) return idx[x] } return null }
  const rows = m.series.slice(-rng).map((r) => ({ ...r, idx: near(r.date) }))
  const L = m.latest, P = m.prev
  const pub = new Date(new Date(`${L.date}T12:00:00`).getTime() + 3 * 864e5).toISOString().slice(0, 10)
  return (
    <>
      <Progress st={d.backfill} what="CFTC's weekly reports (about 8 years)" />
      <div className="row" style={{ gap: 6, marginBottom: 10 }}>{Object.entries(d.markets).sort(([a], [b]) => (a === '13874A' ? -1 : b === '13874A' ? 1 : 0)).map(([c, mm]) => <button key={c} className={`hm-chip ${code === c ? 'on' : ''}`} onClick={() => setCode(c)}>{mm.name}</button>)}</div>
      <div className="fd-kpis">
        {['asset_mgr', 'lev_funds', 'dealer'].map((g) => (
          <Kpi key={g} k={`${d.labels[g]} · net, % of open interest`} v={signed(L[g].net_pct, 1, '%')} c={tone(L[g].net_pct)}
            s={`${us0(L[g].net)} contracts${P ? ` · ${signed(L[g].net_pct - P[g].net_pct, 1, ' pts')} vs last week` : ''} · ${ord(m.percentile_3y[g])} percentile of 3 years`} />
        ))}
        <Kpi k="Report" v={dmy(L.date)} s={`positions on Tuesday, published ${dmy(pub)} · ${m.weeks} weeks saved`} />
      </div>
      <div className="card">
        <div className="row between" style={{ flexWrap: 'wrap', gap: 8 }}>
          <h3 style={{ margin: 0 }}>Net position as % of open interest · weekly</h3>
          <div className="row" style={{ gap: 6 }}>{[['1Y', 52], ['3Y', 156], ['8Y', 420]].map(([t, n]) => <button key={t} className={`hm-chip ${rng === n ? 'on' : ''}`} onClick={() => setRng(n)}>{t}</button>)}</div>
        </div>
        <Chart rows={rows} bars={[{ key: 'asset_mgr', color: GC.asset_mgr, label: 'Asset managers' }, { key: 'lev_funds', color: GC.lev_funds, label: 'Leveraged funds' }]}
          line={{ key: 'idx', color: C_IDX }} lineLabel={code === '13874A' ? 'S&P 500' : 'Nasdaq-100'} barFmt={(v) => signed(v, 1, '%')} />
        <Legend items={[[GC.asset_mgr, 'Asset managers / institutions'], [GC.lev_funds, 'Leveraged funds (hedge funds)'], [C_IDX, code === '13874A' ? 'S&P 500' : 'Nasdaq-100', true]]} />
      </div>
      <div className="card">
        <h3 style={{ marginTop: 0 }}>Who holds what · {m.name}</h3>
        <div style={{ overflowX: 'auto' }}>
          <table className="pm-table" style={{ minWidth: 640 }}>
            <thead><tr><th>Group</th><th>Long</th><th>Short</th><th>Net</th><th>Net % of OI</th><th>vs last week</th><th>3-year percentile</th></tr></thead>
            <tbody>{GROUPS.map((g) => (
              <tr key={g}><td><span style={{ color: GC[g] }}>■</span> {d.labels[g]}</td><td>{int(L[g].long)}</td><td>{int(L[g].short)}</td>
                <td style={{ color: tone(L[g].net), fontWeight: 700 }}>{us0(L[g].net)}</td><td>{signed(L[g].net_pct, 1, '%')}</td>
                <td>{P ? signed(L[g].net_pct - P[g].net_pct, 1, ' pts') : '—'}</td><td>{ord(m.percentile_3y[g])}</td></tr>))}</tbody>
          </table>
        </div>
        <div className="small muted" style={{ marginTop: 6 }}>Open interest {int(L.oi)} contracts. Percentile: where this week sits among the last 3 years of weeks (low = the least long or most short they have been, 100th = the most long). Every contract has a long and a short side. Dealers are mostly banks hedging what they sell to clients.</div>
      </div>
      <Tested title={`asset managers' net (${m.name})`} test={m.tests.asset_mgr} horizons={[['20', '20 sessions (about 4 weeks)']]} lag=" (the trading day after the Friday release)" lowLabel="Asset managers least long (bottom 10%)" highLabel="Asset managers most long (top 10%)" />
      <Tested title={`leveraged funds' net (${m.name})`} test={m.tests.lev_funds} horizons={[['20', '20 sessions (about 4 weeks)']]} lag=" (the trading day after the Friday release)" lowLabel="Leveraged funds most short (bottom 10%)" highLabel="Leveraged funds least short / long (top 10%)" />
      <p className="disclaimer">Source: CFTC Commitments of Traders, Traders in Financial Futures (futures only), released each Friday for the previous Tuesday. Index: Yahoo Finance daily closes; the test starts at the close of the first trading day after the Friday release. {d.not_included}{d.error ? ` Last problem: ${d.error}` : ''}</p>
    </>
  )
}

export default function FiiDii({ tab }) {
  const mk = getMarket()
  const [d, setD] = useState(null), [err, setErr] = useState(null)
  const load = () => api(`/api/fiidii?market=${mk}`).then(setD).catch((e) => setErr(e.message))
  useEffect(() => { setD(null); load() }, [mk]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!d?.backfill?.running) return undefined
    const t = setInterval(load, 15000)
    return () => clearInterval(t)
  }, [d?.backfill?.running]) // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className="fd">
      <div className="row" style={{ alignItems: 'baseline', gap: 10, flexWrap: 'wrap', marginBottom: 10 }}>
        <h2 style={{ margin: 0 }}>🏦 {mk === 'US' ? 'Big money in US index futures' : 'FII / DII activity'}</h2>
        <span className="small muted">{mk === 'US' ? 'CFTC weekly positions of funds, banks and hedge funds' : 'Foreign and domestic institutions: cash market and derivatives'}</span>
        <button className="btn small" style={{ marginLeft: 'auto' }} onClick={() => go('smart')}>🧭 Smart Money</button>
      </div>
      {err && <div className="card t-bad">⚠️ {err}</div>}
      {!d && !err && <div className="card empty">Loading…</div>}
      {d && (mk === 'US' ? <USView d={d} /> : <India d={d} tab={tab} />)}
    </div>
  )
}
