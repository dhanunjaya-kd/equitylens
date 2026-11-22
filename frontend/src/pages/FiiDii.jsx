import { useEffect, useMemo, useState } from 'react'
import { api, getMarket, go, signed } from '../util'
import { useWidth } from './Heatmap'

const cr = (v) => (v === null || v === undefined ? '—' : `₹${v < 0 ? '−' : ''}${Math.abs(v).toLocaleString('en-IN', { maximumFractionDigits: 0 })} Cr`)
const sgnCr = (v) => (v === null || v === undefined ? '—' : `${v > 0 ? '+' : v < 0 ? '−' : ''}₹${Math.abs(v).toLocaleString('en-IN', { maximumFractionDigits: 0 })} Cr`)
const n0 = (v, loc = 'en-IN') => (v === null || v === undefined ? '—' : `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v).toLocaleString(loc, { maximumFractionDigits: 0 })}`)
const us0 = (v) => n0(v, 'en-US')
const int = (v) => Math.round(v).toLocaleString('en-US')
const ord = (n) => { const m = n % 100; return `${n}${m >= 11 && m <= 13 ? 'th' : ({ 1: 'st', 2: 'nd', 3: 'rd' })[n % 10] || 'th'}` }
const tone = (v) => (v === null || v === undefined || v === 0 ? undefined : v > 0 ? 'var(--good)' : 'var(--bad)')
const dmy = (iso) => (iso ? new Date(`${iso}T12:00:00`).toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' }) : '—')
const RANGES = [['1M', 22], ['3M', 66], ['6M', 130], ['1Y', 260]]
const C_FII = '#60a5fa', C_DII = '#a78bfa', C_IDX = '#fbbf24'

// ---------------------------------------------------------------- a small bars + line chart (SVG)
function Chart({ rows, bars, line, height = 240, lineLabel, barFmt = (v) => v }) {
  const [ref, w] = useWidth()
  const [tip, setTip] = useState(null)
  const pad = { l: 8, r: 8, t: 10, b: 22 }
  const W = Math.max(200, w), H = height
  const iw = W - pad.l - pad.r, ih = H - pad.t - pad.b
  const n = rows.length
  const maxAbs = Math.max(1, ...rows.flatMap((r) => bars.map((b) => Math.abs(r[b.key] ?? 0))))
  const lv = rows.map((r) => r[line?.key]).filter((v) => v !== null && v !== undefined)
  const lmin = Math.min(...lv), lmax = Math.max(...lv)
  const x = (i) => pad.l + (iw * (i + 0.5)) / Math.max(1, n)
  const y0 = pad.t + ih / 2
  const by = (v) => y0 - (v / maxAbs) * (ih / 2)
  const ly = (v) => pad.t + ih - ((v - lmin) / Math.max(1e-9, lmax - lmin)) * ih
  const bw = Math.max(1.5, (iw / Math.max(1, n)) / (bars.length + 0.6))
  const pts = line ? rows.map((r, i) => (r[line.key] === null || r[line.key] === undefined ? null : `${x(i).toFixed(1)},${ly(r[line.key]).toFixed(1)}`)).filter(Boolean).join(' ') : ''
  return (
    <div ref={ref} style={{ position: 'relative' }} onMouseLeave={() => setTip(null)}>
      {w > 0 && (
        <svg width={W} height={H} style={{ display: 'block' }}
          onMouseMove={(e) => { const r = e.currentTarget.getBoundingClientRect(); const i = Math.floor(((e.clientX - r.left - pad.l) / iw) * n); if (i >= 0 && i < n) setTip({ i, x: e.clientX - r.left }) }}>
          {bars.length > 0 && <line x1={pad.l} x2={W - pad.r} y1={y0} y2={y0} stroke="var(--line)" strokeDasharray="3 3" />}
          {rows.map((r, i) => bars.map((b, k) => {
            const v = r[b.key]
            if (v === null || v === undefined) return null
            const yy = by(v)
            return <rect key={`${i}${k}`} x={x(i) - (bars.length * bw) / 2 + k * bw} y={Math.min(yy, y0)} width={bw * 0.9} height={Math.max(1, Math.abs(y0 - yy))} fill={b.color} opacity={tip && tip.i !== i ? 0.55 : 0.95} />
          }))}
          {line && pts && <polyline points={pts} fill="none" stroke={line.color} strokeWidth="2" />}
          {n > 0 && <text x={pad.l} y={H - 6} fontSize="11" fill="var(--muted)">{rows[0].date}</text>}
          {n > 1 && <text x={W - pad.r} y={H - 6} fontSize="11" fill="var(--muted)" textAnchor="end">{rows[n - 1].date}</text>}
          {tip && <line x1={x(tip.i)} x2={x(tip.i)} y1={pad.t} y2={pad.t + ih} stroke="var(--muted)" strokeWidth="1" opacity=".5" />}
        </svg>
      )}
      {tip && rows[tip.i] && (
        <div className="fd-tip" style={{ left: Math.min(Math.max(0, tip.x + 10), W - 200) }}>
          <b>{dmy(rows[tip.i].date)}</b>
          {bars.map((b) => <div key={b.key}><span style={{ color: b.color }}>■</span> {b.label}: <b>{barFmt(rows[tip.i][b.key])}</b></div>)}
          {line && rows[tip.i][line.key] !== undefined && <div><span style={{ color: line.color }}>━</span> {lineLabel}: <b>{rows[tip.i][line.key]?.toLocaleString('en-IN', { maximumFractionDigits: 1 })}</b></div>}
        </div>
      )}
    </div>
  )
}

function Legend({ items }) {
  return <div className="row small muted" style={{ gap: 14, flexWrap: 'wrap', marginTop: 6 }}>{items.map(([c, t, isLine]) => <span key={t}><span style={{ color: c }}>{isLine ? '━' : '■'}</span> {t}</span>)}</div>
}

// ---------------------------------------------------------------- tested record
const VERD = { better: ['var(--good)', 'clearly higher than usual'], worse: ['var(--bad)', 'clearly lower than usual'], same: ['var(--muted)', 'not clearly different from usual'] }
function RecordRow({ label, r, base, horizon }) {
  if (!r) return null
  if (r.verdict === 'too_few') return <div className="fd-rec"><b>{label}</b><span className="small" style={{ color: 'var(--warn)' }}>Only {r.n} cases: too few to judge (the rule needs 10).</span></div>
  const [c, t] = VERD[r.verdict]
  return (
    <div className="fd-rec">
      <b>{label}</b>
      <span className="small">Index higher {horizon} later <b>{r.up_pct}%</b> of {r.n} times (likely {r.range[0]}–{r.range[1]}%, median {signed(r.median_pct, 2, '%')}) vs {base}% on every day → <b style={{ color: c }}>{t}</b></span>
    </div>
  )
}

function Tested({ title, test, horizons, lowLabel, highLabel, need, needWhat, lag = '' }) {
  return (
    <div className="card">
      <h3 style={{ marginTop: 0 }}>Does it predict the index? <span className="small muted">· {title}</span></h3>
      <div className="small muted" style={{ marginBottom: 8 }}>A reading is extreme when it is in the bottom or top 10% of its own previous year (only earlier data). The count starts at the first close after the figures were public{lag}. Called higher or lower than usual only when the likely range (90%) of the hit rate is wholly above or below the every-day figure. Fixed before any result.</div>
      {!test && <div className="small" style={{ color: 'var(--warn)' }}>Not enough history yet{need ? `: needs ${need} more ${needWhat}` : ''}.</div>}
      {test && horizons.map(([h, hl]) => (
        <div key={h} style={{ marginBottom: 6 }}>
          <div className="small muted" style={{ marginTop: 6 }}>{hl}</div>
          <RecordRow label={lowLabel} r={test[h]?.low} base={test[h]?.base_up_pct} horizon={hl.toLowerCase()} />
          <RecordRow label={highLabel} r={test[h]?.high} base={test[h]?.base_up_pct} horizon={hl.toLowerCase()} />
        </div>
      ))}
    </div>
  )
}

function Kpi({ k, v, s, c }) {
  return <div className="tile"><div className="k">{k}</div><div className="v" style={{ color: c, fontSize: 20 }}>{v}</div>{s && <div className="s">{s}</div>}</div>
}

function Progress({ st, what }) {
  if (!st?.running) return null
  return (
    <div className="card small">
      Downloading {what}: {st.done.toLocaleString('en-IN')} of {st.total.toLocaleString('en-IN')} · one time only, in the background · this page fills in as it goes
      <div className="progress"><div style={{ width: `${st.total ? (st.done / st.total) * 100 : 0}%` }} /></div>
    </div>
  )
}

// ---------------------------------------------------------------- India
function India({ d }) {
  const [rng, setRng] = useState(66)
  const L = d.latest
  const niftyBy = useMemo(() => Object.fromEntries(d.nifty || []), [d.nifty])
  const cashRows = useMemo(() => d.cash.slice(-rng).map((r) => ({ ...r, nifty: niftyBy[r.date] ?? null })), [d.cash, rng, niftyBy])
  const shareRows = useMemo(() => (d.positions.fii_share_series || []).slice(-rng).map(([date, v]) => ({ date, share: v, nifty: niftyBy[date] ?? null })), [d.positions, rng, niftyBy])
  const P = d.positions.now || {}, ch = d.positions.change_1d || {}
  const share = P.FII?.fut_idx_share, wk = d.positions.change_1w?.FII?.fut_idx_share
  const row = (label, key, fmt, chKey) => (
    <tr><td>{label}</td>{['FII', 'DII', 'Pro', 'Client'].map((w) => (
      <td key={w}><b style={{ color: key.endsWith('share') ? undefined : tone(P[w]?.[key]) }}>{P[w] ? fmt(P[w][key]) : '—'}</b>
        {chKey && ch[w]?.[chKey] !== null && ch[w]?.[chKey] !== undefined && <div className="small muted">{ch[w][chKey] === 0 ? 'no change' : `${n0(ch[w][chKey])} vs prev day`}</div>}</td>))}</tr>
  )
  return (
    <>
      <Progress st={d.backfill} what="NSE's daily derivatives-positions files (about 5 years)" />
      <div className="fd-kpis">
        <Kpi k={`FII / FPI net · ${L ? dmy(L.date) : '—'}`} v={sgnCr(L?.fii?.net)} c={tone(L?.fii?.net)} s={L?.fii ? `bought ${cr(L.fii.buy)} · sold ${cr(L.fii.sell)}` : 'not published yet'} />
        <Kpi k={`DII net · ${L ? dmy(L.date) : '—'}`} v={sgnCr(L?.dii?.net)} c={tone(L?.dii?.net)} s={L?.dii ? `bought ${cr(L.dii.buy)} · sold ${cr(L.dii.sell)}` : 'not published yet'} />
        <Kpi k="FII this month" v={sgnCr(d.month.fii?.sum)} c={tone(d.month.fii?.sum)} s={d.month.fii ? `${d.month.fii.days - d.month.fii.buy_days} selling days of ${d.month.fii.days} saved` : 'no saved days this month yet'} />
        <Kpi k="DII this month" v={sgnCr(d.month.dii?.sum)} c={tone(d.month.dii?.sum)} s={d.month.dii ? `${d.month.dii.buy_days} buying days of ${d.month.dii.days} saved` : 'no saved days this month yet'} />
      </div>
      <div className="card">
        <div className="row between" style={{ flexWrap: 'wrap', gap: 8 }}>
          <h3 style={{ margin: 0 }}>Daily net buying / selling (cash market)</h3>
          <div className="row" style={{ gap: 6 }}>{RANGES.map(([t, n]) => <button key={t} className={`hm-chip ${rng === n ? 'on' : ''}`} onClick={() => setRng(n)}>{t}</button>)}</div>
        </div>
        <div className="small muted" style={{ margin: '4px 0 8px' }}>
          {d.saved_days ? `${d.saved_days} trading day${d.saved_days === 1 ? '' : 's'} saved since ${dmy(d.first_saved)}.` : 'Nothing saved yet.'} NSE publishes only the latest day, so EquityLens saves it every evening; days before {d.first_saved ? dmy(d.first_saved) : 'today'} are not shown rather than estimated.
        </div>
        {cashRows.length > 0 ? <><Chart rows={cashRows} bars={[{ key: 'fii', color: C_FII, label: 'FII net' }, { key: 'dii', color: C_DII, label: 'DII net' }]} line={{ key: 'nifty', color: C_IDX }} lineLabel="NIFTY 50" barFmt={sgnCr} />
          <Legend items={[[C_FII, 'FII / FPI net'], [C_DII, 'DII net'], [C_IDX, 'NIFTY 50 close', true]]} /></> : <div className="empty">The first day appears after NSE publishes this evening's figures.</div>}
      </div>
      <div className="fd-two">
        <div className="card">
          <h3 style={{ marginTop: 0 }}>Derivatives positions · who is long, who is short</h3>
          <div className="small muted" style={{ marginBottom: 8 }}>NSE participant-wise open interest, end of {dmy(d.positions.date)} (contracts). Every contract has a buyer and a seller, so the four groups' nets add up to zero.</div>
          {d.positions.date ? (
            <div style={{ overflowX: 'auto' }}>
              <table className="pm-table" style={{ minWidth: 520 }}>
                <thead><tr><th /><th>FII</th><th>DII</th><th>Pro</th><th>Client</th></tr></thead>
                <tbody>
                  {row('Index futures, % long', 'fut_idx_share', (v) => (v === null || v === undefined ? '—' : `${v}%`))}
                  {row('Index futures, net', 'fut_idx_net', n0, 'fut_idx_net')}
                  {row('Index calls, net', 'idx_call_net', n0, 'idx_call_net')}
                  {row('Index puts, net', 'idx_put_net', n0, 'idx_put_net')}
                  {row('Stock futures, % long', 'fut_stk_share', (v) => (v === null || v === undefined ? '—' : `${v}%`))}
                </tbody>
              </table>
            </div>
          ) : <div className="empty">No positions file saved yet.</div>}
          {share !== undefined && share !== null && <div style={{ marginTop: 10 }}>FII index futures: <b>{share}% long</b>{wk !== null && wk !== undefined ? <span className="muted"> · {signed(wk, 1, ' pts')} vs a week ago</span> : null}</div>}
          {shareRows.length > 1 && <><Chart rows={shareRows} bars={[]} line={{ key: 'share', color: C_FII }} lineLabel="FII % long" height={150} />
            <Legend items={[[C_FII, `FII index futures % long (${shareRows.length} days)`, true]]} /></>}
        </div>
        <div className="card">
          <h3 style={{ marginTop: 0 }}>Streaks and totals</h3>
          {[['FII streak', d.streak.fii ? `${d.streak.fii.days} day${d.streak.fii.days > 1 ? 's' : ''} of net ${d.streak.fii.buying ? 'buying' : 'selling'}` : '—'],
            ['DII streak', d.streak.dii ? `${d.streak.dii.days} day${d.streak.dii.days > 1 ? 's' : ''} of net ${d.streak.dii.buying ? 'buying' : 'selling'}` : '—'],
            [`FII net, last ${d.last5.days || 0} saved days`, sgnCr(d.last5.fii)], [`DII net, last ${d.last5.days || 0} saved days`, sgnCr(d.last5.dii)]].map(([k, v]) => <div key={k} className="pmap-kv"><span className="muted">{k}</span><b>{v}</b></div>)}
          <div className="small muted" style={{ marginTop: 8 }}>Streaks and totals count only the days saved since {d.first_saved ? dmy(d.first_saved) : 'today'}.</div>
        </div>
      </div>
      <Tested title="FII index futures % long (NSE positions)" test={d.tests.fii_futures_share} horizons={[['5', '5 sessions'], ['21', '21 sessions (about a month)']]}
        lag=" (the next session, since NSE publishes after the market shuts)" lowLabel="FIIs very short (bottom 10%)" highLabel="FIIs very long (top 10%)" need={d.tests.part_days_needed} needWhat="trading days of positions" />
      <Tested title="FII cash net (saved days)" test={d.tests.fii_cash} horizons={[['5', '5 sessions'], ['21', '21 sessions (about a month)']]}
        lag=" (the next session, since NSE publishes after the market shuts)" lowLabel="Heavy FII selling (bottom 10%)" highLabel="Heavy FII buying (top 10%)" need={d.tests.cash_days_needed} needWhat="saved trading days (a year of history is needed)" />
      <p className="disclaimer">Cash: NSE's provisional FII/FPI and DII figures (₹ crore), published after about 6 pm on trading days and subject to custodian confirmation. Derivatives: NSE participant-wise open interest files. NIFTY: Yahoo Finance daily closes. History of this page: {d.history_from ? `positions from ${dmy(d.history_from)}` : 'positions not downloaded yet'}.{d.error ? ` Last problem: ${d.error}` : ''}</p>
    </>
  )
}

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

export default function FiiDii() {
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
      {d && (mk === 'US' ? <USView d={d} /> : <India d={d} />)}
    </div>
  )
}
