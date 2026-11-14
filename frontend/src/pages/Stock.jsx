import { useEffect, useState } from 'react'
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, ComposedChart, Legend, Line, LineChart,
  ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { Badge, DataTable, Loading, ScoreBar, ScoreRing, Tile } from '../components/ui'
import { Documents, Forensics, ValuationLab } from './StockAdvanced'
import StockChart from './StockChart'
import { StockAI } from './AI'
import { KeyPoints, KeyRatios, LatestQuarter, StoryTimeline } from './OverviewExtra'
import { ago, api, cr, cur, flag, go, isUS, num, ok, pct, recent, rs, scoreColor, setCurrency, signed, ticker, unitLabel, unitWords, watchlist, x } from '../util'

const TABS = [
  ['overview', 'Overview'], ['ai', '✨ AI'], ['chart', 'Chart'], ['future', 'Future 3·5·10y'], ['valuation', 'Valuation Lab'], ['forensics', 'Forensics'],
  ['financials', 'Financials'], ['quality', 'Quality'], ['ownership', 'Ownership'], ['price', 'Price'], ['documents', 'Reports'],
]
const C = { a: '#2dd4bf', b: '#38bdf8', c: '#a78bfa', d: '#f59e0b', e: '#f472b6', good: '#22c55e', bad: '#ef4444', grid: '#223040', muted: '#8b98a5' }
const axis = { stroke: C.muted, fontSize: 11, tickLine: false }
const tip = { contentStyle: { background: '#121a23', border: '1px solid #223040', borderRadius: 10, fontSize: 12 }, labelStyle: { color: '#e6edf3' } }

// ---- table helpers
const findRow = (t, ...names) => {
  if (!t) return null
  for (const n of names) for (const [k, v] of Object.entries(t.rows)) if (k.toLowerCase().startsWith(n.toLowerCase())) return v
  return null
}
function series(t, defs, annualOnly = true) {
  if (!t || !t.columns) return []
  const rows = defs.map(([key, ...names]) => [key, findRow(t, ...names)])
  return t.columns.map((col, i) => {
    if (annualOnly && /ttm/i.test(col)) return null
    const o = { p: col.replace(/^(\w{3}) (\d{2})(\d{2})$/, "$1 '$3") }
    rows.forEach(([key, vals]) => { o[key] = vals ? vals[i] : null })
    return o
  }).filter(Boolean)
}

export default function Stock({ symbol, tab }) {
  const [d, setD] = useState(null)
  const [err, setErr] = useState(null)
  const [busy, setBusy] = useState(false)
  const [star, setStar] = useState(watchlist.has(symbol))

  const load = async (refresh = false) => {
    setBusy(true); setErr(null)
    try {
      const r = await api(`/api/stock/${encodeURIComponent(symbol)}${refresh ? '?refresh=1' : ''}`)
      setCurrency(r.currency); setD(r); recent.add(r.symbol, r.company.name)
    } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }
  useEffect(() => { load() }, [symbol])

  if (err && !d) return <div className="card empty"><div style={{ fontSize: 30 }}>⚠️</div><p>{err}</p><button className="btn" onClick={() => load()}>Try again</button></div>
  if (!d) return <Loading text={`Researching ${symbol}… (first load takes a few seconds)`} />

  const { company: c, analysis: a } = d
  const m = a.metrics
  const setTab = (t) => go(`stock/${symbol}/${t}`)

  return (
    <>
      <div className="card">
        <div className="row between" style={{ alignItems: 'flex-start' }}>
          <div className="grow">
            <h2 className="h-name">{c.name}</h2>
            <div className="small muted" style={{ margin: '4px 0 8px' }}>
              {flag(d.symbol)} {isUS(d.symbol) ? `US: ${ticker(d.symbol)} · SEC filings` : [c.nse_symbol && `NSE: ${c.nse_symbol}`, c.bse_code && `BSE: ${c.bse_code}`].filter(Boolean).join(' · ')}
              {d.view === 'standalone' && ' · standalone numbers'}
            </div>
            <div>{(c.sector_path || []).map((s) => <span key={s} className="chip">{s}</span>)}</div>
          </div>
          <button className={`star ${star ? 'on' : ''}`} onClick={() => { watchlist.toggle(d.symbol, c.name); setStar(!star) }}>{star ? '★' : '☆'}</button>
        </div>
        <div className="row wrapflex" style={{ gap: 18, marginTop: 6 }}>
          <div><div className="price">{rs(m.price, 2)}</div>
            <div className="small muted">52w {rs(m.low_52w)} – {rs(m.high_52w)} · {signed(m.off_high_pct, 1, '%')} from high</div></div>
          <div><div className="small muted">Market cap</div><b>{cr(m.market_cap)}</b></div>
          <div><div className="small muted">P/E</div><b>{num(m.pe, 1)}</b></div>
        </div>
        <div className="row between small muted" style={{ marginTop: 10 }}>
          <span>Data {ago(d.fetched_at)} · <a href={d.source} target="_blank" rel="noreferrer">source</a></span>
          <button className="btn small" disabled={busy} onClick={() => load(true)}>{busy ? 'Refreshing…' : '↻ Refresh'}</button>
        </div>
      </div>

      <div className="tabs">
        {TABS.map(([k, label]) => <button key={k} className={`tab ${tab === k ? 'on' : ''}`} onClick={() => setTab(k)}>{label}</button>)}
      </div>

      {tab === 'overview' && <Overview d={d} />}
      {tab === 'ai' && <StockAI d={d} />}
      {tab === 'chart' && <StockChart symbol={d.symbol} />}
      {tab === 'future' && <Future d={d} />}
      {tab === 'financials' && <Financials d={d} />}
      {tab === 'quality' && <Quality d={d} />}
      {tab === 'ownership' && <Ownership d={d} />}
      {tab === 'valuation' && <ValuationLab d={d} />}
      {tab === 'forensics' && <Forensics d={d} />}
      {tab === 'documents' && <Documents d={d} />}
      {tab === 'price' && <Price d={d} />}
      {d.extras_errors?.length > 0 && <div className="small muted" style={{ marginTop: 8 }}>Some optional parts couldn't load: {d.extras_errors.join('; ')}</div>}
    </>
  )
}

// ================================================================ OVERVIEW
function Overview({ d }) {
  const { company: c, analysis: a } = d
  const s = a.scores, m = a.metrics, fin = m.is_financial
  return (
    <>
      <div className="card">
        <div className="row" style={{ gap: 14 }}>
          <ScoreRing value={s.overall} label="OVERALL" size={92} />
          <div className="grow">
            <Badge tone={a.verdict.tone}>{a.verdict.label}</Badge>
            <p style={{ margin: '8px 0 0', lineHeight: 1.45 }}>{a.verdict.summary}</p>
          </div>
        </div>
        <div className="grid2" style={{ marginTop: 12 }}>
          <Tile k="Business score" v={ok(s.business) ? Math.round(s.business) : '—'} color={scoreColor(s.business)} s="quality of the company" />
          <Tile k="Valuation score" v={ok(s.valuation) ? Math.round(s.valuation) : '—'} color={scoreColor(s.valuation)} s="how attractive the price is" />
        </div>
      </div>

      <KeyRatios d={d} />
      <LatestQuarter d={d} />

      <div className="card">
        <h3>Outlook by holding period</h3>
        <div className="grid3">
          {['3', '5', '10'].map((n) => (
            <div key={n} className="hz">
              <div className="n">{n} years</div>
              <div className={`st t-${a.horizons[n].tone}`}>{a.horizons[n].stance}</div>
              <div className="small muted">{a.projection.available ? `base ${pct(a.projection.horizons[n].base.cagr)}/yr` : '—'}</div>
            </div>
          ))}
        </div>
        <ul className="list" style={{ marginTop: 10 }}>
          {a.narrative.map((t, i) => <li key={i}><span className="ic" style={{ color: 'var(--accent)' }}>›</span>{t}</li>)}
        </ul>
        <button className="btn small" style={{ marginTop: 8 }} onClick={() => go(`stock/${d.symbol}/future`)}>See 3/5/10-year scenarios →</button>
      </div>

      <div className="grid-auto">
        <div className="card">
          <h3>Scorecard</h3>
          <ScoreBar label="Growth" value={s.growth} hint={`Sales ${pct(m.sales_cagr_5)} · Profit ${pct(m.profit_cagr_5)} /yr (5y)`} />
          <ScoreBar label="Quality" value={s.quality} hint={fin ? `ROE ~${pct(m.roe_avg_5)} (5y avg)` : `ROCE ~${pct(m.roce_avg_5)} (5y avg)`} />
          <ScoreBar label="Financial strength" value={s.strength} hint={fin ? `Equity / assets ${pct(m.equity_to_assets)}` : `Debt/Equity ${x(m.debt_to_equity)} · Interest cover ${ok(m.interest_coverage) && m.interest_coverage < 999 ? x(m.interest_coverage, 1) : 'no debt'}`} />
          <ScoreBar label="Cash generation" value={s.cash} hint={fin ? 'Not used for banks/NBFCs' : `Operating cash = ${ok(m.cfo_to_pat_5) ? Math.round(m.cfo_to_pat_5 * 100) + '%' : '—'} of profit (5y)`} />
          <ScoreBar label="Ownership" value={s.ownership} hint={`Promoters ${pct(m.promoter_latest)} (${signed(m.promoter_change_8q, 1, ' pts')} in 2y)`} />
          <ScoreBar label="Valuation" value={s.valuation} hint={`P/E ${num(m.pe, 1)} · PEG ${num(m.peg, 2)}${a.median_pe ? ` · median P/E ${num(a.median_pe, 1)}` : ''}`} />
        </div>
        <div className="card">
          <h3>Strengths & red flags</h3>
          <ul className="list">
            {a.strengths.map((t, i) => <li key={'s' + i}><span className="ic t-good">✓</span>{t}</li>)}
            {a.flags.map((f, i) => (
              <li key={'f' + i}><span className={`ic ${f.severity === 'high' ? 't-bad' : f.severity === 'medium' ? 't-warn' : 't-neutral'}`}>{f.severity === 'info' ? 'i' : '!'}</span>{f.text}</li>
            ))}
            {!a.strengths.length && !a.flags.length && <li className="muted">Nothing stands out either way.</li>}
          </ul>
        </div>
      </div>

      <QuickChecks d={d} />
      <div style={{ marginTop: 12 }}><KeyPoints d={d} /></div>

      <div className="card" style={{ marginTop: 12 }}>
        <h3>About the company</h3>
        <p style={{ margin: 0, lineHeight: 1.5 }}>{c.about || <span className="muted">No description available.</span>}</p>
        {c.website && <p className="small" style={{ marginBottom: 0 }}><a href={c.website} target="_blank" rel="noreferrer">{c.website}</a></p>}
        {(c.pros?.length > 0 || c.cons?.length > 0) && <>
          <h4>Source's own pros & cons</h4>
          <ul className="list">
            {c.pros.map((t, i) => <li key={'p' + i}><span className="ic t-good">+</span>{t}</li>)}
            {c.cons.map((t, i) => <li key={'c' + i}><span className="ic t-bad">−</span>{t}</li>)}
          </ul>
        </>}
      </div>
      <p className="disclaimer">Scores and outlook are rule-based on past numbers. They're a starting point for research, not investment advice.</p>
    </>
  )
}

function QuickChecks({ d }) {
  const fx = d.analysis.forensics, v = d.analysis.valuation
  if (!fx && !v) return null
  const p = fx?.piotroski, al = fx?.altman, b = fx?.beneish, fv = v?.fair_value
  return (
    <div className="card" style={{ marginTop: 12 }}>
      <div className="row between"><h3 style={{ margin: 0 }}>Quick checks</h3>
        <button className="btn small" onClick={() => go(`stock/${d.symbol}/forensics`)}>Details →</button></div>
      <div className="grid2" style={{ marginTop: 10 }}>
        <Tile k="Fair value (middle)" v={fv ? rs(fv.mid) : '—'} s={fv ? `${signed(fv.upside, 0, '%')} vs price` : ''} color={fv ? (fv.upside >= 15 ? 'var(--good)' : fv.upside < -10 ? 'var(--bad)' : 'var(--warn)') : null} />
        <Tile k="Piotroski F" v={p?.available ? `${p.score_9}/9` : 'n/a'} s={p?.zone} color={p?.available ? `var(--${p.tone})` : null} />
        <Tile k="Altman Z" v={al?.available ? num(al.z, 1) : 'n/a'} s={al?.available ? al.zone : 'not for lenders'} color={al?.available ? `var(--${al.tone})` : null} />
        <Tile k="Beneish M" v={b?.available ? num(b.m, 2) : 'n/a'} s={b?.available ? b.zone : 'not for lenders'} color={b?.available ? `var(--${b.tone})` : null} />
      </div>
    </div>
  )
}

// ================================================================ FUTURE
function Future({ d }) {
  const p = d.analysis.projection, m = d.analysis.metrics, hz = d.analysis.horizons
  if (!p.available) return <div className="card empty">{p.reason}</div>
  const as = p.assumptions
  const chart = ['3', '5', '10'].map((n) => ({ h: `${n} yrs`, Bear: p.horizons[n].bear.price, Base: p.horizons[n].base.price, Bull: p.horizons[n].bull.price }))
  const rd = p.reverse_dcf
  return (
    <>
      <div className="card">
        <h3>Where the price could be (per share)</h3>
        <div className="small muted" style={{ marginTop: -6, marginBottom: 6 }}>Dashed line = today's price {rs(m.price)}</div>
        <div style={{ height: 230 }}>
          <ResponsiveContainer>
            <BarChart data={chart} margin={{ top: 10, right: 6, left: -8, bottom: 0 }}>
              <CartesianGrid stroke={C.grid} vertical={false} />
              <XAxis dataKey="h" {...axis} />
              <YAxis {...axis} tickFormatter={(v) => num(v)} />
              <Tooltip {...tip} formatter={(v) => rs(v)} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <ReferenceLine y={m.price} stroke="#e6edf3" strokeDasharray="4 4" />
              <Bar dataKey="Bear" fill={C.bad} radius={[4, 4, 0, 0]} />
              <Bar dataKey="Base" fill={C.a} radius={[4, 4, 0, 0]} />
              <Bar dataKey="Bull" fill={C.good} radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className="tbl-wrap" style={{ marginTop: 10 }}>
          <table className="tbl scen">
            <thead><tr><th>Years</th><th>Bear</th><th>Base</th><th>Bull</th></tr></thead>
            <tbody>
              {['3', '5', '10'].map((n) => (
                <tr key={n}>
                  <td><b>{n}y</b><div className={`small t-${hz[n].tone}`}>{hz[n].stance}</div></td>
                  {['bear', 'base', 'bull'].map((k) => (
                    <td key={k}>{rs(p.horizons[n][k].price)}<div className="small">{pct(p.horizons[n][k].cagr)}/yr</div><div className="small muted">{x(p.horizons[n][k].multiple, 1)}</div></td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="small muted" style={{ marginBottom: 0 }}>Return figures include the current dividend yield ({pct(as.dividend_yield, 2)}).</p>
      </div>

      <div className="card">
        <h3>What has to go right</h3>
        <p style={{ marginTop: 0, lineHeight: 1.5 }}>
          To earn <b>{pct(rd.required_return, 0)}/yr</b> for 10 years (ending at a P/E of {rd.exit_pe}), profits need to grow about
          <b> {pct(rd.implied_growth)}/yr</b>. The company delivered <b>{pct(rd.delivered_growth_5y)}</b> over 5 years
          {ok(rd.delivered_growth_10y) && <> and <b>{pct(rd.delivered_growth_10y)}</b> over 10 years</>}.
        </p>
        <div className={`badge ${ok(rd.delivered_growth_5y) && rd.delivered_growth_5y >= rd.implied_growth ? 't-good bg-good' : 't-warn bg-warn'}`}>
          {ok(rd.delivered_growth_5y) && rd.delivered_growth_5y >= rd.implied_growth ? 'Track record already beats what the price needs' : 'Price needs more growth than the track record shows'}
        </div>
      </div>

      <div className="card">
        <h3>Assumptions (fully visible)</h3>
        <div className="tbl-wrap">
          <table className="tbl">
            <thead><tr><th>Scenario</th><th>Growth yr 1</th><th>Growth yr 10</th><th>P/E ×</th></tr></thead>
            <tbody>
              <tr><td>Bear</td><td>{pct(as.bear.start_growth)}</td><td>{pct(as.bear.end_growth)}</td><td>0.75×</td></tr>
              <tr><td>Base</td><td>{pct(as.base.start_growth)}</td><td>{pct(as.base.end_growth)}</td><td>1.00×</td></tr>
              <tr><td>Bull</td><td>{pct(as.bull.start_growth)}</td><td>{pct(as.bull.end_growth)}</td><td>1.15×</td></tr>
            </tbody>
          </table>
        </div>
        <ul className="list small" style={{ marginTop: 8 }}>
          <li><span className="ic">•</span>Starting EPS {rs(as.eps_start, 2)} (last 12 months). Historical profit growth used: {pct(as.history_profit_growth)} (blend of 3/5/10y, capped at sales growth + 5 and at 25%).</li>
          <li><span className="ic">•</span>Growth fades in a straight line from year 1 to year 10. Fast growth rarely lasts.</li>
          <li><span className="ic">•</span>Starting P/E {num(as.pe_base, 1)} ({as.pe_base_source}), drifting towards {num(as.pe_long_run, 1)} by year 10.</li>
        </ul>
        <p className="disclaimer">Nobody can predict prices. These scenarios show what the numbers imply <i>if</i> the assumptions hold. Debt, management, competition and the economy can change everything.</p>
      </div>
    </>
  )
}

// ================================================================ FINANCIALS
function Financials({ d }) {
  const t = d.company.tables, fin = d.analysis.metrics.is_financial
  const [view, setView] = useState('profit_loss')
  const pl = series(t.profit_loss, [['Sales', 'Sales', 'Revenue'], ['Net Profit', 'Net Profit'], ['OPM', 'OPM', 'Financing Margin'], ['EPS', 'EPS']])
  const q = series(t.quarters, [['Sales', 'Sales', 'Revenue'], ['Net Profit', 'Net Profit']], false)
  return (
    <>
      <StoryTimeline d={d} />
      <div className="card">
        <h3>Sales & net profit ({unitLabel()}, yearly)</h3>
        <div style={{ height: 230 }}>
          <ResponsiveContainer>
            <ComposedChart data={pl} margin={{ top: 6, right: 0, left: -6, bottom: 0 }}>
              <CartesianGrid stroke={C.grid} vertical={false} />
              <XAxis dataKey="p" {...axis} interval="preserveStartEnd" />
              <YAxis yAxisId="l" {...axis} tickFormatter={(v) => num(v)} />
              <YAxis yAxisId="r" orientation="right" {...axis} tickFormatter={(v) => `${v}%`} hide={fin} />
              <Tooltip {...tip} formatter={(v, n) => (n === 'OPM' ? `${v}%` : num(v))} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Bar yAxisId="l" dataKey="Sales" fill={C.b} radius={[3, 3, 0, 0]} />
              <Bar yAxisId="l" dataKey="Net Profit" fill={C.a} radius={[3, 3, 0, 0]} />
              {!fin && <Line yAxisId="r" dataKey="OPM" stroke={C.d} dot={false} strokeWidth={2} />}
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      </div>
      <div className="grid-auto">
        <div className="card">
          <h3>EPS ({cur()} per share)</h3>
          <div style={{ height: 170 }}>
            <ResponsiveContainer>
              <AreaChart data={pl} margin={{ top: 6, right: 4, left: -14, bottom: 0 }}>
                <CartesianGrid stroke={C.grid} vertical={false} />
                <XAxis dataKey="p" {...axis} interval="preserveStartEnd" /><YAxis {...axis} />
                <Tooltip {...tip} /><Area dataKey="EPS" stroke={C.c} fill={C.c} fillOpacity={0.2} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>
        <div className="card">
          <h3>Last quarters ({unitLabel()})</h3>
          <div style={{ height: 170 }}>
            <ResponsiveContainer>
              <BarChart data={q} margin={{ top: 6, right: 4, left: -6, bottom: 0 }}>
                <CartesianGrid stroke={C.grid} vertical={false} />
                <XAxis dataKey="p" {...axis} interval="preserveStartEnd" /><YAxis {...axis} tickFormatter={(v) => num(v)} />
                <Tooltip {...tip} formatter={(v) => num(v)} />
                <Bar dataKey="Sales" fill={C.b} /><Bar dataKey="Net Profit" fill={C.a} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>
      <div className="card" style={{ marginTop: 12 }}>
        <div className="row wrapflex" style={{ gap: 6, marginBottom: 10 }}>
          {[['profit_loss', 'Profit & Loss'], ['balance_sheet', 'Balance Sheet'], ['cash_flow', 'Cash Flow'], ['quarters', 'Quarterly'], ['ratios', 'Ratios']].map(([k, l]) => (
            <button key={k} className={`tab ${view === k ? 'on' : ''}`} onClick={() => setView(k)}>{l}</button>
          ))}
        </div>
        <DataTable table={t[view]} />
        <div className="small muted" style={{ marginTop: 6 }}>{unitWords()} unless marked. Scroll sideways for older years.</div>
      </div>
    </>
  )
}

// ================================================================ QUALITY
function Quality({ d }) {
  const t = d.company.tables, a = d.analysis, m = a.metrics, fin = m.is_financial
  const ret = series(t.ratios, [['ROCE', 'ROCE'], ['ROE', 'ROE']])
  const cash = series(t.cash_flow, [['Operating cash', 'Cash from Operating']]).map((r) => {
    const npRow = series(t.profit_loss, [['Net Profit', 'Net Profit']]).find((x) => x.p === r.p)
    return { ...r, 'Net Profit': npRow ? npRow['Net Profit'] : null }
  })
  const fcf = (m.fcf_series || []).map((v, i) => ({ p: (t.cash_flow.columns[i] || '').replace(/^(\w{3}) (\d{2})(\d{2})$/, "$1 '$3"), FCF: v }))
  const wc = series(t.ratios, [['Debtor days', 'Debtor Days'], ['Inventory days', 'Inventory Days'], ['Working capital days', 'Working Capital Days']])
  return (
    <>
      <div className="grid2" style={{ marginBottom: 12 }}>
        <Tile k={fin ? 'ROE (5y avg)' : 'ROCE (5y avg)'} v={pct(fin ? m.roe_avg_5 : m.roce_avg_5)} s={`latest ${pct(fin ? m.roe_latest : m.roce_latest)}`} />
        <Tile k={fin ? 'Equity / assets' : 'Debt / equity'} v={fin ? pct(m.equity_to_assets) : x(m.debt_to_equity)} s={fin ? 'capital cushion' : `borrowings ${cr(m.borrowings)}`} />
        <Tile k="Operating margin" v={pct(m.opm_latest)} s={`5y avg ${pct(m.opm_avg_5)}`} />
        <Tile k={fin ? 'Profit growth (10y)' : 'Cash conversion (5y)'} v={fin ? pct(m.profit_cagr_10) : (ok(m.cfo_to_pat_5) ? `${Math.round(m.cfo_to_pat_5 * 100)}%` : '—')} s={fin ? '' : 'operating cash ÷ profit'} />
        {!fin && <Tile k="Interest coverage" v={ok(m.interest_coverage) ? (m.interest_coverage >= 999 ? 'No debt' : x(m.interest_coverage, 1)) : '—'} s="(PBT + interest) ÷ interest" />}
        <Tile k="Profit grew" v={`${m.profit_up_years}/${m.profit_years_checked} yrs`} s="years with higher profit" />
      </div>
      {ret.some((r) => ok(r.ROCE) || ok(r.ROE)) && (
        <div className="card">
          <h3>Return on capital (%)</h3>
          <div style={{ height: 190 }}>
            <ResponsiveContainer>
              <LineChart data={ret} margin={{ top: 6, right: 6, left: -14, bottom: 0 }}>
                <CartesianGrid stroke={C.grid} vertical={false} />
                <XAxis dataKey="p" {...axis} interval="preserveStartEnd" /><YAxis {...axis} />
                <Tooltip {...tip} formatter={(v) => `${v}%`} /><Legend wrapperStyle={{ fontSize: 12 }} />
                <ReferenceLine y={15} stroke={C.muted} strokeDasharray="3 3" />
                <Line dataKey="ROCE" stroke={C.a} strokeWidth={2} dot={false} connectNulls />
                <Line dataKey="ROE" stroke={C.c} strokeWidth={2} dot={false} connectNulls />
              </LineChart>
            </ResponsiveContainer>
          </div>
          <div className="small muted">Dashed line = 15%, a common bar for a good business.</div>
        </div>
      )}
      {!fin && (
        <div className="grid-auto">
          <div className="card">
            <h3>Profit vs operating cash ({unitLabel()})</h3>
            <div style={{ height: 190 }}>
              <ResponsiveContainer>
                <BarChart data={cash} margin={{ top: 6, right: 4, left: -6, bottom: 0 }}>
                  <CartesianGrid stroke={C.grid} vertical={false} />
                  <XAxis dataKey="p" {...axis} interval="preserveStartEnd" /><YAxis {...axis} tickFormatter={(v) => num(v)} />
                  <Tooltip {...tip} formatter={(v) => num(v)} /><Legend wrapperStyle={{ fontSize: 12 }} />
                  <Bar dataKey="Net Profit" fill={C.c} /><Bar dataKey="Operating cash" fill={C.a} />
                </BarChart>
              </ResponsiveContainer>
            </div>
            <div className="small muted">Healthy companies turn most of their profit into cash.</div>
          </div>
          <div className="card">
            <h3>Cash left after investing ({unitLabel()})</h3>
            <div style={{ height: 190 }}>
              <ResponsiveContainer>
                <BarChart data={fcf} margin={{ top: 6, right: 4, left: -6, bottom: 0 }}>
                  <CartesianGrid stroke={C.grid} vertical={false} />
                  <XAxis dataKey="p" {...axis} interval="preserveStartEnd" /><YAxis {...axis} tickFormatter={(v) => num(v)} />
                  <Tooltip {...tip} formatter={(v) => num(v)} /><ReferenceLine y={0} stroke={C.muted} />
                  <Bar dataKey="FCF" fill={C.good} />
                </BarChart>
              </ResponsiveContainer>
            </div>
            <div className="small muted">Operating cash + investing cash (a simple free-cash-flow proxy).</div>
          </div>
        </div>
      )}
      {wc.length > 0 && wc.some((r) => ok(r['Debtor days'])) && (
        <div className="card" style={{ marginTop: 12 }}>
          <h3>Working capital (days)</h3>
          <div style={{ height: 180 }}>
            <ResponsiveContainer>
              <LineChart data={wc} margin={{ top: 6, right: 6, left: -14, bottom: 0 }}>
                <CartesianGrid stroke={C.grid} vertical={false} />
                <XAxis dataKey="p" {...axis} interval="preserveStartEnd" /><YAxis {...axis} />
                <Tooltip {...tip} /><Legend wrapperStyle={{ fontSize: 12 }} />
                <Line dataKey="Debtor days" stroke={C.d} dot={false} connectNulls />
                <Line dataKey="Inventory days" stroke={C.b} dot={false} connectNulls />
                <Line dataKey="Working capital days" stroke={C.e} dot={false} connectNulls />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}
    </>
  )
}

// ================================================================ OWNERSHIP
function Ownership({ d }) {
  const t = d.company.tables, m = d.analysis.metrics
  if (isUS(d.symbol)) return (
    <div className="card empty">🇺🇸 Promoter / FII / DII shareholding is an Indian disclosure.<br />US companies don't report it the same way, so the ownership score is left out for US stocks.</div>
  )
  const data = series(t.shareholding_quarterly, [['Promoters', 'Promoter'], ['FIIs', 'FII'], ['DIIs', 'DII'], ['Public', 'Public'], ['Govt', 'Government']], false)
  return (
    <>
      <div className="grid2" style={{ marginBottom: 12 }}>
        <Tile k="Promoters" v={pct(m.promoter_latest)} s={`${signed(m.promoter_change_8q, 1, ' pts')} in ~2y`} color={ok(m.promoter_change_8q) && m.promoter_change_8q < -2 ? 'var(--bad)' : null} />
        <Tile k="FII + DII" v={pct((m.fii_latest || 0) + (m.dii_latest || 0))} s={`${signed(m.institutional_change_8q, 1, ' pts')} in ~2y`} />
        <Tile k="FIIs" v={pct(m.fii_latest)} />
        <Tile k="DIIs (mutual funds, insurers)" v={pct(m.dii_latest)} />
      </div>
      <div className="card">
        <h3>Shareholding trend (%)</h3>
        <div style={{ height: 230 }}>
          <ResponsiveContainer>
            <LineChart data={data} margin={{ top: 6, right: 6, left: -14, bottom: 0 }}>
              <CartesianGrid stroke={C.grid} vertical={false} />
              <XAxis dataKey="p" {...axis} interval="preserveStartEnd" /><YAxis {...axis} />
              <Tooltip {...tip} formatter={(v) => `${v}%`} /><Legend wrapperStyle={{ fontSize: 12 }} />
              <Line dataKey="Promoters" stroke={C.a} strokeWidth={2} dot={false} connectNulls />
              <Line dataKey="FIIs" stroke={C.b} strokeWidth={2} dot={false} connectNulls />
              <Line dataKey="DIIs" stroke={C.c} strokeWidth={2} dot={false} connectNulls />
              <Line dataKey="Public" stroke={C.d} strokeWidth={2} dot={false} connectNulls />
            </LineChart>
          </ResponsiveContainer>
        </div>
        <ul className="list small" style={{ marginTop: 8 }}>
          <li><span className="ic">•</span>Promoters buying or holding steady is a confidence signal. Steady selling is worth a closer look.</li>
          <li><span className="ic">•</span>Rising FII/DII share usually means more institutional research and money behind the stock.</li>
        </ul>
      </div>
      <div className="card"><h3>Quarterly table</h3><DataTable table={t.shareholding_quarterly} pctRows={false} /></div>
    </>
  )
}

// ================================================================ PRICE
function Price({ d }) {
  const pc = d.price_chart || {}, m = d.analysis.metrics
  const dma = pc.DMA200 || pc['200 DMA'] || []
  const dmaMap = Object.fromEntries(dma.map(([dt, v]) => [dt, v]))
  const data = (pc.Price || []).map(([dt, v]) => ({ d: dt, Price: v, DMA200: dmaMap[dt] ?? null }))
  return (
    <>
      <div className="grid3" style={{ marginBottom: 12 }}>
        <Tile k="Price CAGR 5y" v={pct(m.price_cagr_5)} />
        <Tile k="Price CAGR 10y" v={pct(m.price_cagr_10)} />
        <Tile k="From 52w high" v={signed(m.off_high_pct, 1, '%')} />
      </div>
      <div className="card">
        <h3>10-year price</h3>
        {data.length === 0 ? <div className="muted small">Price history not available.</div> : (
          <div style={{ height: 260 }}>
            <ResponsiveContainer>
              <LineChart data={data} margin={{ top: 6, right: 6, left: -6, bottom: 0 }}>
                <CartesianGrid stroke={C.grid} vertical={false} />
                <XAxis dataKey="d" {...axis} minTickGap={50} tickFormatter={(v) => v.slice(0, 4)} />
                <YAxis {...axis} domain={['auto', 'auto']} tickFormatter={(v) => num(v)} />
                <Tooltip {...tip} formatter={(v) => rs(v, 1)} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Line dataKey="Price" stroke={C.a} dot={false} strokeWidth={1.8} />
                <Line dataKey="DMA200" name="200-day avg" stroke={C.d} dot={false} strokeWidth={1.2} connectNulls />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
        <div className="small muted">Price above its 200-day average usually means a long-term uptrend.</div>
      </div>
    </>
  )
}
