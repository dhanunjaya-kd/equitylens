import { useEffect, useMemo, useState } from 'react'
import { ago, api, go, num, ok, signed } from '../util'

// IPO research (India). Every figure is the source's own; a figure that fails its check is left out with the reason.
const fmtDate = (s) => (s ? new Date(s + 'T12:00:00').toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: '2-digit' }) : '—')
const daysTo = (s, today) => (s && today ? Math.round((new Date(s + 'T12:00:00') - new Date(today + 'T12:00:00')) / 864e5) : null)
const band = (x) => {
  if (ok(x.band_low) && ok(x.band_high)) return x.band_low === x.band_high ? `₹${num(x.band_low, 2)}` : `₹${num(x.band_low, 2)} – ${num(x.band_high, 2)}`
  return x.price_text || '—'
}
const times = (v) => (ok(v) ? `${num(v, 2)}x` : '—')
const move = (v) => (ok(v) ? <b style={{ color: v > 0 ? 'var(--good)' : v < 0 ? 'var(--bad)' : 'var(--muted)' }}>{signed(v, 1, '%')}</b> : <span className="muted">—</span>)
const SmeTag = ({ on }) => (on ? <span className="tagc warnc" style={{ marginLeft: 6 }}>SME</span> : null)

function CategoryBars({ rows }) {
  const shown = rows.filter((r) => ok(r.times))
  const max = Math.max(1, ...shown.map((r) => r.times))
  return (
    <div>
      {rows.map((r) => (
        <div key={r.category} style={{ marginBottom: 8 }}>
          <div className="row between small"><span style={{ fontWeight: r.total ? 700 : 400 }}>{r.category}</span><b>{times(r.times)}</b></div>
          {ok(r.times)
            ? <div style={{ height: 8, borderRadius: 4, background: 'var(--card2)', overflow: 'hidden' }}><div style={{ width: `${Math.min(100, (r.times / max) * 100)}%`, height: '100%', background: r.times >= 1 ? 'var(--good)' : 'var(--warn)' }} /></div>
            : <div className="small muted">{r.check}</div>}
          {ok(r.shares_offered) && <div className="small muted">{num(r.shares_bid)} shares bid for {num(r.shares_offered)} offered</div>}
        </div>
      ))}
    </div>
  )
}

function Detail({ x }) {
  const [d, setD] = useState(null)
  const [err, setErr] = useState('')
  useEffect(() => {
    api(`/api/ipo/detail/${encodeURIComponent(x.symbol)}?series=${encodeURIComponent(x.series || 'EQ')}`).then(setD).catch((e) => setErr(e.message))
  }, [x.symbol, x.series])
  if (err) return <div className="small" style={{ color: 'var(--bad)' }}>{err}</div>
  if (!d) return <div className="small muted">Loading NSE's figures…</div>
  return (
    <div className="grid-auto" style={{ marginTop: 10 }}>
      <div className="card">
        <h3>Bids by investor category</h3>
        {d.categories.length ? <CategoryBars rows={d.categories} /> : <div className="small muted">NSE has not published category bids for this issue.</div>}
        <div className="small muted" style={{ marginTop: 6 }}>NSE bid book{d.updated ? ` · updated ${d.updated}` : ''}. Times is shown only when it agrees with bids ÷ shares offered.</div>
      </div>
      <div className="card">
        <h3>Issue facts, as NSE lists them</h3>
        {d.facts.length ? (
          <table className="tbl" style={{ fontSize: 12.5 }}><tbody>
            {d.facts.map((f, i) => <tr key={i}><td style={{ textAlign: 'left', color: 'var(--muted)', whiteSpace: 'normal' }}>{f.k}</td><td style={{ whiteSpace: 'normal' }}>{f.v}</td></tr>)}
          </tbody></table>
        ) : <div className="small muted">NSE gave no issue facts for this symbol.</div>}
        {d.docs.length > 0 && <div style={{ marginTop: 8 }}>{d.docs.map((doc) => <a key={doc.url} className="chip" href={doc.url} target="_blank" rel="noreferrer">📄 {doc.title} ↗</a>)}</div>}
      </div>
      <Sources rows={d.sources} compact />
    </div>
  )
}

function OpenTable({ rows, today }) {
  const [open, setOpen] = useState(null)
  if (!rows.length) return <div className="card small muted">No issue is open for bidding on NSE right now.</div>
  return rows.map((x) => {
    const left = daysTo(x.end, today)
    const key = `${x.symbol}-${x.series}`
    return (
      <div key={key} className="card" style={{ cursor: x.symbol ? 'pointer' : 'default' }} onClick={() => x.symbol && setOpen(open === key ? null : key)}>
        <div className="row between wrapflex">
          <div><b>{x.company}</b><SmeTag on={x.sme} /><div className="small muted">{x.symbol || 'no symbol yet'} · {fmtDate(x.start)} → {fmtDate(x.end)}{left !== null ? ` · ${left > 0 ? `closes in ${left} day${left === 1 ? '' : 's'}` : left === 0 ? 'closes today' : 'closed'}` : ''}</div></div>
          <div className="row" style={{ gap: 16 }}>
            <div className="small" style={{ textAlign: 'right' }}><div className="muted">Price band</div><b>{band(x)}</b></div>
            <div className="small" style={{ textAlign: 'right' }} title={x.times_check}><div className="muted">Subscribed (all)</div><b>{times(x.times)}</b></div>
          </div>
        </div>
        {!ok(x.times) && <div className="small muted" style={{ marginTop: 4 }}>Subscription: {x.times_check}</div>}
        {x.size_text && <div className="small muted">Issue size (NSE's figure, unit as NSE gives it): {x.size_text}</div>}
        {open === key && <div onClick={(e) => e.stopPropagation()}><Detail x={x} /></div>}
      </div>
    )
  })
}

function UpcomingTable({ rows, today }) {
  if (!rows.length) return <div className="card small muted">NSE lists no upcoming issue right now.</div>
  return (
    <div className="tbl-wrap"><table className="tbl"><thead><tr><th style={{ textAlign: 'left' }}>Company</th><th>Opens</th><th>Closes</th><th>Price band</th></tr></thead><tbody>
      {rows.map((x) => {
        const d = daysTo(x.start, today)
        return (
          <tr key={`${x.symbol}-${x.company}`}>
            <td style={{ textAlign: 'left' }}>{x.company}<SmeTag on={x.sme} /></td>
            <td>{fmtDate(x.start)}{d !== null && d > 0 ? <span className="muted"> · in {d}d</span> : null}</td>
            <td>{fmtDate(x.end)}</td><td>{band(x)}</td>
          </tr>
        )
      })}
    </tbody></table></div>
  )
}

function ListedTable({ rows }) {
  if (!rows.length) return <div className="card small muted">No IPO listed on NSE in the last 120 days.</div>
  return (
    <>
      <div className="tbl-wrap"><table className="tbl"><thead><tr><th style={{ textAlign: 'left' }}>Company</th><th>Listed</th><th>Issue price</th><th>Listing-day open</th><th>Listing-day close</th><th>Now</th><th>Sessions</th></tr></thead><tbody>
        {rows.map((x) => (
          <tr key={`${x.symbol}-${x.listing}`} style={{ cursor: x.symbol ? 'pointer' : 'default' }} onClick={() => x.symbol && go(`stock/${x.symbol}`)}>
            <td style={{ textAlign: 'left' }}>{x.company}<SmeTag on={x.sme} />{x.perf_note && <div className="small muted" style={{ whiteSpace: 'normal' }}>{x.perf_note}</div>}</td>
            <td>{fmtDate(x.listing)}</td><td>{band(x)}</td>
            <td>{move(x.perf?.open_vs_issue)}</td><td>{move(x.perf?.close_vs_issue)}</td><td>{move(x.perf?.now_vs_issue)}</td>
            <td>{x.perf ? x.perf.sessions : '—'}</td>
          </tr>
        ))}
      </tbody></table></div>
      <div className="small muted" style={{ marginTop: 6 }}>Moves are against the final issue price NSE lists, from daily prices. Tap a company for its full stock report.</div>
    </>
  )
}

function DrhpTable({ rows }) {
  if (!rows.length) return <div className="card small muted">SEBI's list could not be read.</div>
  return (
    <>
      <div className="tbl-wrap"><table className="tbl"><thead><tr><th style={{ textAlign: 'left' }}>Filed</th><th style={{ textAlign: 'left' }}>Company</th><th style={{ textAlign: 'left' }}>Filing</th></tr></thead><tbody>
        {rows.map((x) => (
          <tr key={x.url}><td style={{ textAlign: 'left' }}>{fmtDate(x.date)}</td><td style={{ textAlign: 'left', whiteSpace: 'normal' }}>{x.company}<SmeTag on={x.sme} /></td>
            <td style={{ textAlign: 'left', whiteSpace: 'normal' }}><a href={x.url} target="_blank" rel="noreferrer">{x.title} ↗</a></td></tr>
        ))}
      </tbody></table></div>
      <div className="small muted" style={{ marginTop: 6 }}>Companies that have filed a draft offer document with SEBI. Filing is not approval, and many never list.</div>
    </>
  )
}

function Sources({ rows, compact }) {
  if (!rows?.length) return null
  return (
    <div className="card">
      <h3>{compact ? 'Sources for this issue' : 'Source check'}</h3>
      {!compact && <div className="small muted" style={{ marginBottom: 8 }}>Each source's latest answer is saved in data/ipo_raw. A source that stops carrying a field it should carry is shown here, and nothing is filled in for it.</div>}
      {rows.map((s) => (
        <div key={s.id} className="small" style={{ padding: '6px 0', borderTop: '1px solid var(--line)' }}>
          <div className="row between">
            <span>{s.ok ? '🟢' : s.stale ? '🟡' : '🔴'} <b>{s.name}</b></span>
            <span className="muted">{s.fetched ? ago(s.fetched) : ''}{ok(s.rows) ? ` · ${s.rows} rows` : ''}</span>
          </div>
          {s.missing?.length > 0 && <div style={{ color: 'var(--warn)' }}>Fields not found: {s.missing.join(', ')}</div>}
          {s.stale && <div style={{ color: 'var(--warn)' }}>Showing the last good copy. Latest try: {s.error}</div>}
          {!s.ok && !s.stale && s.error && <div style={{ color: 'var(--bad)' }}>{s.error}</div>}
          <a className="muted" href={s.url} target="_blank" rel="noreferrer" style={{ wordBreak: 'break-all' }}>{s.url}</a>
        </div>
      ))}
    </div>
  )
}

const TABS = [['open', 'Open now'], ['upcoming', 'Upcoming'], ['listed', 'Recently listed'], ['drhp', 'Filed with SEBI']]
const BOARDS = [['main', 'Mainboard'], ['sme', 'SME'], ['all', 'All']]

export default function IPO({ tab }) {
  const [page, setPage] = useState(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [board, setBoard] = useState('main')
  const t = TABS.some(([k]) => k === tab) ? tab : 'open'
  const load = (refresh) => {
    setBusy(true)
    api(`/api/ipo?market=IN${refresh ? '&refresh=1' : ''}`).then((p) => { setPage(p); setErr('') }).catch((e) => setErr(e.message)).finally(() => setBusy(false))
  }
  useEffect(() => { load(false) }, [])
  const pick = useMemo(() => (rows) => (rows || []).filter((x) => board === 'all' || (board === 'sme' ? x.sme : !x.sme)), [board])

  return (
    <div className="wrap">
      <div className="row between wrapflex" style={{ marginBottom: 8 }}>
        <div><h2 style={{ margin: '4px 0' }}>🚀 IPO research</h2><div className="small muted">🇮🇳 NSE issues and SEBI filings. Figures are the sources' own; anything that fails a check is left out.</div></div>
        <button className="btn small" disabled={busy} onClick={() => load(true)}>{busy ? 'Refreshing…' : '↻ Refresh'}</button>
      </div>
      {err && <div className="card" style={{ color: 'var(--bad)' }}>{err}</div>}
      {page?.demo && <div className="card small muted">Demo mode: IPO data comes only from live sources, so this page is empty here.</div>}
      <div className="tabs">
        {TABS.map(([k, label]) => <button key={k} className={`tab ${t === k ? 'on' : ''}`} onClick={() => go(`ipo/${k}`)}>{label}{page ? ` · ${pick(page[k]).length}` : ''}</button>)}
      </div>
      <div className="row" style={{ gap: 6, marginBottom: 10 }}>
        {BOARDS.map(([k, label]) => <button key={k} className={`chip ${board === k ? 'on' : ''}`} style={board === k ? { color: 'var(--accent)', borderColor: 'var(--accent)' } : null} onClick={() => setBoard(k)}>{label}</button>)}
      </div>
      {!page && !err && <div className="card small muted">Reading NSE and SEBI…</div>}
      {page && t === 'open' && <OpenTable rows={pick(page.open)} today={page.today} />}
      {page && t === 'upcoming' && <UpcomingTable rows={pick(page.upcoming)} today={page.today} />}
      {page && t === 'listed' && <ListedTable rows={pick(page.listed)} />}
      {page && t === 'drhp' && <DrhpTable rows={pick(page.drhp)} />}
      {page && <div style={{ marginTop: 12 }}><Sources rows={page.sources} /></div>}
    </div>
  )
}
