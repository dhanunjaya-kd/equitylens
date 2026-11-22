import { useEffect, useMemo, useState } from 'react'
import { api, go, signed } from '../util'
import { Logo } from '../components/ui'
import {
  C_CLIENT, C_DII, C_FII, C_IDX, C_PRO, Chart, Chips, Kpi, Legend, LinesChart, Progress, Spark, Tested, Unavailable,
  cr, dm, dmy, mon, n0, sgnCr, tone,
} from '../components/FlowCharts'

const TABS = [['flows', 'Money flows'], ['positions', 'F&O positions'], ['sectors', 'Sectors (FPI)'], ['stocks', 'Stocks']]
const lakh = (v) => (v === null || v === undefined ? '—' : `₹${(v / 1e5).toLocaleString('en-IN', { maximumFractionDigits: 2 })} L Cr`)
const nearClose = (by, iso) => {
  for (let k = 0; k < 6; k++) {
    const x = new Date(new Date(`${iso}T12:00:00`).getTime() - k * 864e5).toISOString().slice(0, 10)
    if (by[x] !== undefined) return by[x]
  }
  return null
}

// ---------------------------------------------------------------- money flows
function Flows({ d }) {
  const F = d.fpi, N = F.nsdl, M = F.mf, L = d.latest
  const [rng, setRng] = useState(66)
  const niftyBy = useMemo(() => Object.fromEntries(d.nifty || []), [d.nifty])
  const monthEnd = useMemo(() => {
    const out = {}
    for (const [dt, c] of d.nifty || []) out[dt.slice(0, 7)] = c
    return out
  }, [d.nifty])
  const rows = useMemo(() => (rng === 'M'
    ? N.months.map((m) => ({ date: m.month, net: m.exch, nifty: monthEnd[m.month] ?? null }))
    : N.rows.slice(-rng).map((r) => ({ date: r.date, net: r.net, nifty: niftyBy[r.date] ?? null }))), [N, rng, niftyBy, monthEnd])
  const cur = new Date().toISOString().slice(0, 7)
  const fpiMonth = N.months.length && N.months[N.months.length - 1].month === cur ? N.months[N.months.length - 1] : null
  const mfLast = M.months.length ? M.months[M.months.length - 1] : null
  const mfBy = Object.fromEntries(M.months.map((m) => [m.month, m]))
  const table = [...N.months].slice(-12).reverse().map((m) => {
    const prev = new Date(`${m.month}-15T12:00:00`); prev.setMonth(prev.getMonth() - 1)
    const pm = prev.toISOString().slice(0, 7)
    const chg = monthEnd[m.month] && monthEnd[pm] ? (monthEnd[m.month] / monthEnd[pm] - 1) * 100 : null
    return { ...m, mf: mfBy[m.month], nifty: chg }
  })
  const nse = d.cash || []
  const mfRows = M.days.slice(-66).map((r) => ({ date: r.date, net: r.net }))
  return (
    <>
      <Progress st={N.backfill} what="NSDL's confirmed daily FPI figures (about 5 years)" />
      <div className="fd-kpis">
        <Kpi k={`FII / FPI net · ${L ? dm(L.date) : '—'}`} v={sgnCr(L?.fii?.net)} c={tone(L?.fii?.net)} s={L?.fii ? `NSE, same evening · bought ${cr(L.fii.buy)} · sold ${cr(L.fii.sell)}` : 'NSE has not published yet'} />
        <Kpi k={`DII net · ${L ? dm(L.date) : '—'}`} v={sgnCr(L?.dii?.net)} c={tone(L?.dii?.net)} s={L?.dii ? `NSE, same evening · bought ${cr(L.dii.buy)} · sold ${cr(L.dii.sell)}` : 'NSE has not published yet'} />
        <Kpi k={`FPI this month · ${fpiMonth ? mon(fpiMonth.month) : mon(cur)}`} v={sgnCr(fpiMonth?.exch)} c={tone(fpiMonth?.exch)}
          s={fpiMonth ? `NSDL confirmed · ${fpiMonth.days} reporting day${fpiMonth.days === 1 ? '' : 's'} · with IPOs and other primary-market buying ${sgnCr(fpiMonth.equity)}` : 'no NSDL figures for this month yet'} />
        <Kpi k={`Mutual funds · ${mfLast ? mon(mfLast.month) : '—'}`} v={sgnCr(mfLast?.net)} c={tone(mfLast?.net)}
          s={mfLast ? `SEBI · ${mfLast.days} trading day${mfLast.days === 1 ? '' : 's'} up to ${dm(M.last)} (SEBI runs about 2 weeks behind)` : 'SEBI figures not saved yet'} />
      </div>

      <div className="card">
        <div className="row between" style={{ flexWrap: 'wrap', gap: 8 }}>
          <h3 style={{ margin: 0 }}>Foreign investors (FPI) · net buying of Indian shares</h3>
          <Chips opts={[['1M', 22], ['3M', 66], ['6M', 130], ['1Y', 260], ['5Y monthly', 'M']]} value={rng} onChange={setRng} />
        </div>
        <div className="small muted" style={{ margin: '4px 0 8px' }}>
          NSDL's confirmed figures (custodian-reported), equity bought minus sold on the stock exchanges, ₹ crore{rng === 'M' ? ', added up by month' : ', by NSDL reporting date (each date carries the previous trading day\'s trades)'}.
          {N.days ? ` ${N.days.toLocaleString('en-IN')} reporting days saved, from ${dm(N.first)} to ${dm(N.last)}.` : ''}
        </div>
        {rows.length > 0
          ? <><Chart rows={rows} bars={[{ key: 'net', color: C_FII, label: 'FPI net' }]} line={{ key: 'nifty', color: C_IDX }} lineLabel="NIFTY 50" barFmt={sgnCr} />
            <Legend items={[[C_FII, 'FPI net (NSDL)'], [C_IDX, 'NIFTY 50 close', true]]} /></>
          : <Unavailable>{F.errors.nsdl || F.errors.nsdl_archive || 'NSDL figures are being downloaded.'}</Unavailable>}
        {F.errors.nsdl_archive && rows.length > 0 && <div className="small" style={{ color: 'var(--warn)', marginTop: 6 }}>{F.errors.nsdl_archive}</div>}
      </div>

      {table.length > 0 && (
        <div className="card">
          <h3 style={{ marginTop: 0 }}>Month by month</h3>
          <div style={{ overflowX: 'auto' }}>
            <table className="pm-table fd-fit" style={{ minWidth: 600 }}>
              <thead><tr><th>Month</th><th>FPI, stock exchanges</th><th className="hide-sm">FPI, with IPOs and other primary</th><th>Mutual funds (SEBI)</th><th>NIFTY 50</th></tr></thead>
              <tbody>{table.map((m) => (
                <tr key={m.month}>
                  <td>{mon(m.month)}{m.month === cur ? <span className="small muted"> · so far</span> : null}</td>
                  <td style={{ color: tone(m.exch), fontWeight: 700 }}>{sgnCr(m.exch)}</td>
                  <td className="hide-sm" style={{ color: tone(m.equity) }}>{sgnCr(m.equity)}</td>
                  <td style={{ color: tone(m.mf?.net) }}>{m.mf ? sgnCr(m.mf.net) : <span className="muted">not published yet</span>}{m.mf && m.month === M.last?.slice(0, 7) ? <span className="small muted"> · to {dm(M.last)}</span> : null}</td>
                  <td style={{ color: tone(m.nifty) }}>{m.nifty === null ? '—' : signed(m.nifty, 1, '%')}</td>
                </tr>))}</tbody>
            </table>
          </div>
        </div>
      )}

      <div className="fd-two">
        <div className="card">
          <h3 style={{ marginTop: 0 }}>Same-evening NSE figures · FII and DII</h3>
          <div className="small muted" style={{ marginBottom: 8 }}>NSE's provisional figures come out after about 6 pm but only for that day, so EquityLens saves them each evening. {d.saved_days ? `${d.saved_days} day${d.saved_days === 1 ? '' : 's'} saved since ${dm(d.first_saved)}.` : 'Nothing saved yet.'} This is the only public source for daily DII figures.</div>
          {nse.length >= 5
            ? <><Chart rows={nse.slice(-66)} bars={[{ key: 'fii', color: C_FII, label: 'FII net' }, { key: 'dii', color: C_DII, label: 'DII net' }]} height={200} barFmt={sgnCr} />
              <Legend items={[[C_FII, 'FII / FPI net'], [C_DII, 'DII net']]} /></>
            : nse.length > 0 && (
              <table className="pm-table" style={{ minWidth: 0 }}>
                <thead><tr><th>Day</th><th>FII / FPI net</th><th>DII net</th></tr></thead>
                <tbody>{[...nse].reverse().map((r) => <tr key={r.date}><td>{dmy(r.date)}</td><td style={{ color: tone(r.fii), fontWeight: 700 }}>{sgnCr(r.fii)}</td><td style={{ color: tone(r.dii), fontWeight: 700 }}>{sgnCr(r.dii)}</td></tr>)}</tbody>
              </table>)}
          {nse.length >= 2 && (
            <div style={{ marginTop: 8 }}>
              {[['FII streak', d.streak.fii], ['DII streak', d.streak.dii]].map(([k, s]) => <div key={k} className="pmap-kv"><span className="muted">{k}</span><b>{s ? `${s.days} day${s.days > 1 ? 's' : ''} of net ${s.buying ? 'buying' : 'selling'}` : '—'}</b></div>)}
            </div>)}
        </div>
        <div className="card">
          <h3 style={{ marginTop: 0 }}>Mutual funds · the biggest part of DII</h3>
          <div className="small muted" style={{ marginBottom: 8 }}>SEBI's daily figures for mutual funds buying and selling shares on the exchanges, ₹ crore. SEBI publishes about two weeks late{M.last ? `; latest day: ${dm(M.last)}` : ''}.</div>
          {mfRows.length >= 2
            ? <><Chart rows={mfRows} bars={[{ key: 'net', color: C_DII, label: 'Mutual funds net' }]} height={170} barFmt={sgnCr} /><Legend items={[[C_DII, 'Mutual funds net (SEBI)']]} /></>
            : <Unavailable>{F.errors.mf || 'SEBI figures not saved yet.'}</Unavailable>}
          {M.backfill?.archive === false && <div className="small muted" style={{ marginTop: 6 }}>SEBI's older months could not be downloaded; days are added from the month SEBI shows each time it updates.</div>}
          {M.periods.length > 0 && (
            <div style={{ marginTop: 10 }}>
              <div className="small muted">Yearly totals (SEBI)</div>
              {M.periods.slice(0, 6).map((p) => <div key={p.period} className="pmap-kv"><span className="muted">{p.period}</span><b style={{ color: tone(p.net) }}>{sgnCr(p.net)}</b></div>)}
            </div>)}
        </div>
      </div>

      <Tested title="FPI net buying (NSDL)" test={d.tests.fpi_net} horizons={[['5', '5 sessions'], ['21', '21 sessions (about a month)']]}
        lag=" (the session after NSDL's reporting date)" lowLabel="Heavy FPI selling (bottom 10%)" highLabel="Heavy FPI buying (top 10%)"
        need={d.tests.fpi_days_needed} needWhat="reporting days" />
    </>
  )
}

// ---------------------------------------------------------------- F&O positions
function Positions({ d }) {
  const [rng, setRng] = useState(260)
  const P = d.positions.now || {}, ch = d.positions.change_1d || {}
  const share = P.FII?.fut_idx_share, wk = d.positions.change_1w?.FII?.fut_idx_share
  const ser = (d.positions.series || []).slice(-rng)
  const row = (label, key, fmt, chKey) => (
    <tr><td>{label}</td>{['FII', 'DII', 'Pro', 'Client'].map((w) => (
      <td key={w}><b style={{ color: key.endsWith('share') ? undefined : tone(P[w]?.[key]) }}>{P[w] ? fmt(P[w][key]) : '—'}</b>
        {chKey && ch[w]?.[chKey] !== null && ch[w]?.[chKey] !== undefined && <div className="small muted">{ch[w][chKey] === 0 ? 'no change' : `${n0(ch[w][chKey])} vs prev day`}</div>}</td>))}</tr>
  )
  const pct = (v) => (v === null || v === undefined ? '—' : `${v}%`)
  return (
    <>
      <Progress st={d.backfill} what="NSE's daily derivatives-positions files (about 5 years)" />
      <div className="card">
        <h3 style={{ marginTop: 0 }}>Who is long, who is short · {dmy(d.positions.date)}</h3>
        <div className="small muted" style={{ marginBottom: 8 }}>NSE participant-wise open interest (contracts). Client = individual and other non-institutional traders; Pro = brokers trading their own money. Every contract has a buyer and a seller, so the four groups' nets add up to zero.</div>
        {d.positions.date ? (
          <div style={{ overflowX: 'auto' }}>
            <table className="pm-table" style={{ minWidth: 520 }}>
              <thead><tr><th /><th>FII</th><th>DII</th><th>Pro</th><th>Client</th></tr></thead>
              <tbody>
                {row('Index futures, % long', 'fut_idx_share', pct)}
                {row('Index futures, net', 'fut_idx_net', n0, 'fut_idx_net')}
                {row('Index calls, net', 'idx_call_net', n0, 'idx_call_net')}
                {row('Index puts, net', 'idx_put_net', n0, 'idx_put_net')}
                {row('Stock futures, % long', 'fut_stk_share', pct)}
              </tbody>
            </table>
          </div>
        ) : <div className="empty">No positions file saved yet.</div>}
        {share !== undefined && share !== null && <div style={{ marginTop: 10 }}>FII index futures: <b>{share}% long</b>{wk !== null && wk !== undefined ? <span className="muted"> · {signed(wk, 1, ' pts')} vs a week ago</span> : null}</div>}
      </div>
      {ser.length > 1 && (
        <>
          <div className="row between" style={{ margin: '4px 0 10px', flexWrap: 'wrap', gap: 8 }}>
            <span className="small muted">{(d.positions.series || []).length.toLocaleString('en-IN')} trading days saved, from {dm(d.history_from)}</span>
            <Chips opts={[['3M', 66], ['1Y', 260], ['5Y', 1300]]} value={rng} onChange={setRng} />
          </div>
          <div className="fd-two eq">
            <div className="card">
              <h3 style={{ marginTop: 0 }}>FII index futures · % long</h3>
              <LinesChart rows={ser} lines={[{ key: 'fii_share', color: C_FII, label: 'FII % long' }]} zero={false} height={190} fmt={(v) => (v === null || v === undefined ? '—' : `${v}%`)} />
              <div className="small muted" style={{ marginTop: 6 }}>Long contracts ÷ (long + short). Below 50% = FIIs hold more shorts than longs.</div>
            </div>
            <div className="card">
              <h3 style={{ marginTop: 0 }}>Index futures · net by group</h3>
              <LinesChart rows={ser} lines={[{ key: 'fii_fut', color: C_FII, label: 'FII' }, { key: 'client_fut', color: C_CLIENT, label: 'Client' }, { key: 'pro_fut', color: C_PRO, label: 'Pro' }, { key: 'dii_fut', color: C_DII, label: 'DII' }]} height={190} fmt={n0} />
              <Legend items={[[C_FII, 'FII', true], [C_CLIENT, 'Client', true], [C_PRO, 'Pro', true], [C_DII, 'DII', true]]} />
            </div>
          </div>
          <div className="card">
            <h3 style={{ marginTop: 0 }}>FII index options · long minus short (contracts)</h3>
            <LinesChart rows={ser} lines={[{ key: 'fii_call', color: '#22c55e', label: 'Calls' }, { key: 'fii_put', color: '#ef4444', label: 'Puts' }]} height={190} fmt={n0} />
            <Legend items={[['#22c55e', 'Index calls, net', true], ['#ef4444', 'Index puts, net', true]]} />
            <div className="small muted" style={{ marginTop: 6 }}>Above zero = FIIs have bought more of these options than they have sold (written). Net long puts is often a hedge, not only a bet on a fall.</div>
          </div>
        </>
      )}
      <Tested title="FII index futures % long" test={d.tests.fii_futures_share} horizons={[['5', '5 sessions'], ['21', '21 sessions (about a month)']]}
        lag=" (the next session, since NSE publishes after the market shuts)" lowLabel="FIIs very short (bottom 10%)" highLabel="FIIs very long (top 10%)"
        need={d.tests.part_days_needed} needWhat="trading days of positions" />
    </>
  )
}

// ---------------------------------------------------------------- sectors
function Sectors({ d }) {
  const S = d.fpi.sectors
  const [sort, setSort] = useState('buy')
  if (!S) {
    return <><Progress st={d.fpi.sectors_backfill} what="NSDL's fortnightly sector reports (about 5 years)" /><div className="card"><Unavailable>{d.fpi.errors.sectors || 'Sector reports are being downloaded.'}</Unavailable></div></>
  }
  const n = Math.min(24, S.reports)
  const list = [...S.sectors].filter((s) => s.auc > 0 || s.net !== 0).sort((a, b) => (sort === 'buy' ? b.net - a.net : sort === 'sell' ? a.net - b.net : sort === 'year' ? b.net_1y - a.net_1y : b.auc - a.auc))
  const totRows = S.periods.map((p, i) => ({ date: p, net: S.total_hist[i] }))
  return (
    <>
      <Progress st={d.fpi.sectors_backfill} what="NSDL's fortnightly sector reports (about 5 years)" />
      <div className="fd-kpis">
        <Kpi k={`FPI net, ${dm(S.net_period[0])} – ${dm(S.net_period[1])}`} v={sgnCr(S.total.net)} c={tone(S.total.net)} s="equity, all sectors" />
        <Kpi k={`Fortnight before (${dm(S.prev_period[0])} – ${dm(S.prev_period[1])})`} v={sgnCr(S.total.net_prev)} c={tone(S.total.net_prev)} />
        <Kpi k={`FPI equity holdings · ${dm(S.end)}`} v={lakh(S.total.auc)} s="value at market prices" />
        <Kpi k={`Net, last ${n} fortnights`} v={sgnCr(S.total_hist.reduce((a, b) => a + (b || 0), 0))} c={tone(S.total_hist.reduce((a, b) => a + (b || 0), 0))} s={`${S.reports} reports saved since ${dm(S.first)}`} />
      </div>
      <div className="card">
        <h3 style={{ marginTop: 0 }}>FPI net buying, all sectors · by fortnight</h3>
        <Chart rows={totRows} bars={[{ key: 'net', color: C_FII, label: 'FPI net' }]} height={170} barFmt={sgnCr} />
      </div>
      <div className="card">
        <div className="row between" style={{ flexWrap: 'wrap', gap: 8, marginBottom: 6 }}>
          <h3 style={{ margin: 0 }}>Sector by sector</h3>
          <Chips opts={[['Most bought', 'buy'], ['Most sold', 'sell'], [`Last ${n} fortnights`, 'year'], ['Largest holdings', 'auc']]} value={sort} onChange={setSort} />
        </div>
        <div style={{ overflowX: 'auto' }}>
          <table className="pm-table fd-sect fd-fit" style={{ minWidth: 760 }}>
            <thead><tr><th>Sector</th><th>Net, latest fortnight</th><th className="hide-sm">Fortnight before</th><th>Last {n} fortnights</th><th className="hide-sm">Net, last {n}</th><th className="hide-sm">Holdings</th><th>Share of FPI holdings</th></tr></thead>
            <tbody>{list.map((s) => (
              <tr key={s.name}>
                <td>{s.name}</td>
                <td style={{ color: tone(s.net), fontWeight: 700 }}>{sgnCr(s.net)}</td>
                <td className="hide-sm" style={{ color: tone(s.net_prev) }}>{sgnCr(s.net_prev)}</td>
                <td><Spark vals={s.hist} w={84} /></td>
                <td className="hide-sm" style={{ color: tone(s.net_1y) }}>{sgnCr(s.net_1y)}</td>
                <td className="hide-sm">{lakh(s.auc)}</td>
                <td>{s.share.toFixed(1)}%</td>
              </tr>))}</tbody>
          </table>
        </div>
        <div className="small muted" style={{ marginTop: 6 }}>NSDL's fortnightly sector-wise FPI report (equity, ₹ crore), published for the 15th and the last day of each month. Net = bought minus sold in that fortnight. Holdings also rise and fall with share prices. The sectors are checked to add up to NSDL's Grand Total before they are used.</div>
      </div>
    </>
  )
}

// ---------------------------------------------------------------- stocks
function Stocks() {
  const [q, setQ] = useState(''), [who, setWho] = useState('fii'), [dir, setDir] = useState('up')
  const [s, setS] = useState(null), [err, setErr] = useState(null)
  const load = () => api(`/api/fiidii/stocks${q ? `?quarter=${encodeURIComponent(q)}` : ''}`).then(setS).catch((e) => setErr(e.message))
  useEffect(() => { load() }, [q]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!s?.building && !s?.updating) return undefined
    const t = setTimeout(load, 3000)
    return () => clearTimeout(t)
  }, [s]) // eslint-disable-line react-hooks/exhaustive-deps
  if (err) return <div className="card t-bad">⚠️ {err}</div>
  if (!s) return <div className="card empty">Loading…</div>
  if (s.building && s.scanned) return <div className="card empty">Reading the shareholding of {s.scanned.toLocaleString('en-IN')} scanned stocks… (first time only)</div>
  if (!s.scanned) return <div className="card"><Unavailable>This list uses the shareholding data from EquityLens's stock scan. Run a scan from Top Picks first.</Unavailable></div>
  const list = s[`${who}_${dir}`] || []
  const sm = s.summary[who]
  const W = who === 'fii' ? 'FIIs' : 'DIIs'
  return (
    <div className="card">
      <div className="row between" style={{ flexWrap: 'wrap', gap: 8 }}>
        <h3 style={{ margin: 0 }}>Stocks {W} {dir === 'up' ? 'added to' : 'cut'} · {s.quarter} vs {s.prev_quarter}</h3>
        <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
          <Chips opts={[['FII', 'fii'], ['DII', 'dii']]} value={who} onChange={setWho} />
          <Chips opts={[['Added', 'up'], ['Cut', 'down']]} value={dir} onChange={setDir} />
        </div>
      </div>
      <div className="small muted" style={{ margin: '6px 0 10px' }}>
        {W} raised their holding in <b>{sm.up}</b> and cut it in <b>{sm.down}</b> of {sm.n} stocks that have filed {s.quarter}. Change = percentage points of the company's shares, from its quarterly shareholding filing.
        {' '}Covers the {s.scanned.toLocaleString('en-IN')} stocks EquityLens has scanned{s.in_quarter < s.scanned ? `; ${s.in_quarter.toLocaleString('en-IN')} have filed ${s.quarter} so far` : ''}.
        {s.updating ? ' Updating with the latest scan…' : ''}
      </div>
      {s.quarters.length > 1 && <div style={{ marginBottom: 10 }}><Chips opts={s.quarters.slice(0, 4).map(([qq, c]) => [`${qq} (${c})`, qq])} value={s.quarter} onChange={setQ} /></div>}
      {list.length === 0 ? <div className="empty">None.</div> : (
        <div className="fd-stocks">
          {list.map((r) => {
            const now = r[who], chg = r[`${who}_chg`]
            return (
              <button key={r.symbol} className="fd-stock" onClick={() => go(`stock/${r.symbol}`)}>
                <Logo sym={r.symbol} name={r.name} size={30} />
                <span className="fd-stock-n"><b>{r.name || r.symbol}</b><span className="small muted">{r.symbol}{r.sector ? ` · ${r.sector}` : ''}</span></span>
                <span className="fd-stock-v"><b style={{ color: tone(chg) }}>{signed(chg, 2, ' pts')}</b><span className="small muted">now {now}%</span></span>
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}

function Sources({ d }) {
  const F = d.fpi, E = F.errors
  const rows = [
    ['NSE same-evening FII / DII', d.saved_days ? `${d.saved_days} day${d.saved_days === 1 ? '' : 's'} saved` : null, (d.error || '').startsWith('NSE cash') ? d.error : null],
    ['NSE derivatives positions', d.positions.days_saved ? `${d.positions.days_saved.toLocaleString('en-IN')} trading days` : null, (d.error || '').startsWith('NSE positions') ? d.error : null],
    ['NSDL confirmed FPI, daily', F.nsdl.days ? `${F.nsdl.days.toLocaleString('en-IN')} reporting days (${dm(F.nsdl.first)} – ${dm(F.nsdl.last)})` : null, E.nsdl || E.nsdl_archive],
    ['NSDL / CDSL sector reports', F.sectors ? `${F.sectors.reports} fortnights (from ${dm(F.sectors.first)})` : null, E.sectors],
    ['SEBI mutual fund trades', F.mf.days.length ? `${F.mf.days.length} days (to ${dm(F.mf.last)})` : null, E.mf || (F.mf.backfill?.archive === false ? 'older months not available from SEBI; building forward' : null)],
  ]
  return (
    <details className="card small fd-src">
      <summary><b>Data status</b> <span className="muted">· {rows.filter((r) => r[1]).length} of {rows.length} sources have data</span></summary>
      {rows.map(([k, v, e]) => (
        <div key={k} className="pmap-kv"><span>{v ? '✅' : '⏳'} {k}</span><span className="muted" style={{ textAlign: 'right' }}>{v || 'nothing saved yet'}{e ? <div style={{ color: 'var(--warn)' }}>{e}</div> : null}</span></div>
      ))}
    </details>
  )
}

export default function India({ d, tab }) {
  const t = TABS.some(([k]) => k === tab) ? tab : 'flows'
  return (
    <>
      <div className="list-chips fd-tabs" style={{ marginBottom: 12 }}>{TABS.map(([k, l]) => <button key={k} className={`tab ${t === k ? 'on' : ''}`} onClick={() => go(`fiidii/${k}`)}>{l}</button>)}</div>
      {t === 'flows' && <Flows d={d} />}
      {t === 'positions' && <Positions d={d} />}
      {t === 'sectors' && <Sectors d={d} />}
      {t === 'stocks' && <Stocks />}
      <Sources d={d} />
      <p className="disclaimer">Sources: NSE provisional FII/FPI and DII figures (₹ crore, published after about 6 pm, subject to custodian confirmation); NSDL confirmed daily FPI figures and fortnightly sector reports; SEBI mutual fund trading figures; NSE participant-wise open interest files; company shareholding filings (via the EquityLens scan); NIFTY 50 closes from Yahoo Finance. Figures that fail a check (bought − sold = net, sectors add up to the total) are left out, never estimated.{d.error ? ` Last problem: ${d.error}` : ''}</p>
    </>
  )
}
