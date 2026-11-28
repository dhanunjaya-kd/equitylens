import { useEffect, useMemo, useState } from 'react'
import { ago, api, getMarket, go, num, ok, signed } from '../util'

// IPO research (India) as a dashboard. Every number is NSE's / SEBI's own, or plain arithmetic on two of their
// figures (labelled). A figure that fails its check is left out and the reason is shown.
const fmtDate = (s) => (s ? new Date(s + 'T12:00:00').toLocaleDateString('en-IN', { day: 'numeric', month: 'short' }) : '—')
const fmtDateY = (s) => (s ? new Date(s + 'T12:00:00').toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: '2-digit' }) : '—')
const daysTo = (s, today) => (s && today ? Math.round((new Date(s + 'T12:00:00') - new Date(today + 'T12:00:00')) / 864e5) : null)
const band = (x) => (ok(x.band_low) && ok(x.band_high) ? (x.band_low === x.band_high ? `₹${num(x.band_low, 2)}` : `₹${num(x.band_low, 2)}–${num(x.band_high, 2)}`) : '—')
const crore = (v) => (ok(v) ? `₹${num(v, v < 100 ? 2 : 0)} Cr` : '—')
const lakh = (v) => (ok(v) ? (v >= 1e7 ? `${num(v / 1e7, 2)} Cr` : v >= 1e5 ? `${num(v / 1e5, 2)} L` : num(v)) : '—')
const rupees = (v) => (ok(v) ? `₹${num(v)}` : '—')
const tone = (v) => (!ok(v) ? 'var(--muted)' : v > 0 ? 'var(--good)' : v < 0 ? 'var(--bad)' : 'var(--muted)')
const Pct = ({ v }) => (ok(v) ? <b style={{ color: tone(v) }}>{signed(v, 1, '%')}</b> : <span className="muted">—</span>)

function Board({ sme }) { return <span className={`ipo-board ${sme ? 'sme' : 'main'}`}>{sme ? 'SME' : 'Mainboard'}</span> }
function Initials({ name }) {
  const w = String(name).replace(/\b(limited|ltd|india|private|pvt)\b/gi, '').match(/[A-Za-z0-9]+/g) || ['?']
  return <span className="ipo-ini">{((w[0] || '?')[0] + (w[1] ? w[1][0] : (w[0] || '').slice(1, 2))).toUpperCase()}</span>
}
function Countdown({ d, verb }) {
  if (d === null) return null
  const cls = d <= 0 ? 'hot' : d <= 2 ? 'warm' : ''
  const txt = d < 0 ? 'closed' : d === 0 ? `${verb} today` : `${verb} in ${d}d`
  return <span className={`ipo-cd ${cls}`}>{txt}</span>
}
function KPI({ k, v, s, c }) {
  return <div className="ipo-kpi"><div className="k">{k}</div><div className="v" style={c ? { color: c } : null}>{v}</div>{s && <div className="s">{s}</div>}</div>
}
function Times({ v, big }) {
  if (!ok(v)) return <span className="muted">—</span>
  const c = v >= 1 ? 'var(--good)' : 'var(--warn)'
  return <b style={{ color: c, fontSize: big ? 22 : 15 }}>{num(v, 2)}x</b>
}
const Check = ({ okk, children }) => <div className={`ipo-check ${okk ? 'pass' : 'fail'}`}>{okk ? '✓' : '!'} {children}</div>

// ---------------------------------------------------------------- one issue: dashboard
function CategoryTable({ cats, total }) {
  const [all, setAll] = useState(false)
  const rows = cats.rows.filter((r) => all || r.level === 0)
  const max = Math.max(1, ...cats.rows.filter((r) => !r.total && r.level === 0).map((r) => r.shares_bid || 0))
  const anyTimes = cats.rows.some((r) => ok(r.times))
  return (
    <div className="card ipo-panel">
      <div className="row between"><h3>Subscription by investor category</h3><button className="chip" onClick={() => setAll(!all)}>{all ? 'Main categories only' : 'Show sub-categories'}</button></div>
      <div className="tbl-wrap"><table className="tbl ipo-tbl"><thead><tr>
        <th style={{ textAlign: 'left' }}>Category</th><th>Shares bid</th><th style={{ width: '26%' }}>Share of all bids</th>{anyTimes && <th>Times</th>}<th>Applications</th>
      </tr></thead><tbody>
        {rows.map((r) => {
          const share = ok(r.shares_bid) && total ? (r.shares_bid / total) * 100 : null
          return (
            <tr key={r.sr} className={r.total ? 'tot' : `lv${r.level}`}>
              <td style={{ textAlign: 'left', whiteSpace: 'normal' }} title={r.check}>{r.category}</td>
              <td>{lakh(r.shares_bid)}</td>
              <td>{!r.total && ok(share) ? <div className="ipo-bar"><i style={{ width: `${(r.shares_bid / max) * 100}%` }} /><span>{num(share, 1)}%</span></div> : r.total ? '100%' : '—'}</td>
              {anyTimes && <td title={r.check}>{ok(r.times) ? <Times v={r.times} /> : <span className="muted">—</span>}</td>}
              <td>{ok(r.applications) ? num(r.applications) : '—'}</td>
            </tr>
          )
        })}
      </tbody></table></div>
      <Check okk={cats.adds_up}>{cats.check}</Check>
      {!anyTimes && <div className="small muted">The shares reserved per category are not published for this issue, so category times can't be checked and aren't shown. Share of bids is each category's bids ÷ total bids.</div>}
    </div>
  )
}

function DemandChart({ d }) {
  if (!d) return <div className="card ipo-panel"><h3>Bids by price</h3><div className="small muted">NSE has not published bids by price for this issue.</div></div>
  if (!d.ok) return <div className="card ipo-panel"><h3>Bids by price</h3><Check okk={false}>{d.note}</Check></div>
  const levels = d.levels.filter((l) => l.pct >= 0.1 || l.price === d.top_price)
  const hidden = d.levels.length - levels.length
  return (
    <div className="card ipo-panel">
      <h3>Bids by price</h3>
      <div className="ipo-big"><b>{num(d.at_top, 1)}%</b> of all shares bid are at the upper price <b>₹{num(d.top_price)}</b></div>
      <div style={{ marginTop: 10 }}>
        {[...levels].reverse().map((l) => (
          <div key={l.price} className="ipo-hrow">
            <span className="p">₹{num(l.price)}</span>
            <div className="ipo-bar wide"><i style={{ width: `${Math.max(l.pct, 0.5)}%`, background: l.price === d.top_price ? 'var(--accent)' : 'var(--ok)' }} /><span>{num(l.pct, 1)}% · {lakh(l.shares)}</span></div>
          </div>
        ))}
      </div>
      {hidden > 0 && <div className="small muted">{hidden} price level{hidden > 1 ? 's' : ''} under 0.1% of bids not drawn.</div>}
      <Check okk>bids at every price add up to NSE's total bids</Check>
      <div className="small muted"><span className="src-note">NSE + BSE bid book · </span>{d.time}</div>
    </div>
  )
}

function IssueDashboard({ x }) {
  const [d, setD] = useState(null)
  const [err, setErr] = useState('')
  const [more, setMore] = useState(false)
  useEffect(() => {
    api(`/api/ipo/detail/${encodeURIComponent(x.symbol)}?series=${encodeURIComponent(x.series || 'EQ')}`).then(setD).catch((e) => setErr(e.message))
  }, [x.symbol, x.series])
  if (err) return <div className="small" style={{ color: 'var(--bad)', padding: 10 }}>{err}</div>
  if (!d) return <div className="small muted" style={{ padding: 10 }}>Loading NSE's figures…</div>
  if (!d.ok) return <div className="small" style={{ color: 'var(--bad)', padding: 10 }}>NSE issue details not available: {d.sources?.[0]?.error}</div>
  const c = d.composition || {}
  return (
    <div className="ipo-dash" onClick={(e) => e.stopPropagation()}>
      <div className="ipo-kpis">
        <KPI k="Price band" v={band(d)} s={d.facts.find((f) => f.k === 'Issue Type')?.v} />
        <KPI k="Minimum (1 lot)" v={rupees(d.lot_value)} s={ok(d.lot) ? `${num(d.lot)} shares × upper price` : null} />
        <KPI k="Issue size" v={crore(d.size_cr)} s={ok(d.issue_shares) ? `${lakh(d.issue_shares)} shares × upper price${c.ok && ok(c.market_maker) ? ` · incl. ${lakh(c.market_maker)} market-maker` : ''}` : d.size_check} />
        <KPI k="Fresh issue / OFS" v={c.ok ? `${num(c.fresh_pct, 0)}% / ${num(100 - c.fresh_pct, 0)}%` : '—'} s={c.ok ? (c.fresh_pct === 100 ? 'all money goes to the company' : `${lakh(c.ofs)} shares sold by existing holders`) : c.note} />
        <KPI k="Subscribed (all)" v={<Times v={d.times} big />} s={ok(d.total_bids) ? `${lakh(d.total_bids)} shares bid` : d.times_check} />
        <KPI k="Applications" v={ok(d.applications) ? num(d.applications) : '—'} s="across all categories" />
      </div>
      <div className="ipo-grid2">
        <CategoryTable cats={d.categories} total={d.total_bids} />
        <DemandChart d={d.demand} />
      </div>
      <div className="ipo-grid2">
        <div className="card ipo-panel">
          <h3>Key facts</h3>
          <div className="ipo-facts">
            {d.facts.filter((f) => !['Symbol', 'Categories', 'Sub-Categories applicable for UPI', 'Address of the Registrar', 'Contact person name number and Email id'].includes(f.k) || more)
              .map((f) => <div key={f.k}><span>{f.k}</span><b>{f.v}</b></div>)}
          </div>
          <button className="chip" style={{ marginTop: 8 }} onClick={() => setMore(!more)}>{more ? 'Fewer details' : 'All NSE details'}</button>
          {more && d.long_facts.map((f) => <div key={f.k} className="small" style={{ marginTop: 8 }}><b>{f.k}</b><div className="muted">{f.v}</div></div>)}
        </div>
        <div className="card ipo-panel">
          <h3>Documents</h3>
          {d.docs.length ? <div className="ipo-docs">{d.docs.map((doc) => <a key={doc.url} href={doc.url} target="_blank" rel="noreferrer">📄 {doc.title}<span>↗</span></a>)}</div> : <div className="small muted">NSE lists no documents for this issue.</div>}
          <div className="small muted" style={{ marginTop: 10 }}>The offer document (RHP) holds the company's financials, where the money goes and its listed peers. Reading it into this page is the next phase.</div>
          <div className="small muted src-note" style={{ marginTop: 10 }}>Source: <a href={d.sources[0].url} target="_blank" rel="noreferrer">NSE issue details</a>{d.updated ? ` · ${d.updated}` : ''}{d.fetched ? ` · fetched ${ago(d.fetched)}` : ''}</div>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------- tabs
function IssueList({ rows, today, upcoming }) {
  const [open, setOpen] = useState(rows.length === 1 ? `${rows[0].symbol}` : null)
  if (!rows.length) return <div className="card small muted">{upcoming ? 'NSE lists no upcoming issue for this board right now.' : 'No issue is open for bidding on this board right now.'}</div>
  return (
    <div className="card ipo-list">
      <div className="ipo-row head"><span>Company</span><span>Price band</span><span>Issue size</span><span>{upcoming ? 'Opens' : 'Closes'}</span><span>{upcoming ? 'Closes' : 'Subscribed'}</span></div>
      {rows.map((x) => {
        const k = `${x.symbol}`
        const isOpen = open === k
        return (
          <div key={k + x.company} className={`ipo-item ${isOpen ? 'on' : ''}`}>
            <div className="ipo-row" onClick={() => x.symbol && setOpen(isOpen ? null : k)}>
              <span className="co"><Initials name={x.company} /><span className="nm"><b>{x.company}</b><small>{x.symbol || 'no symbol yet'} · <Board sme={x.sme} /></small></span></span>
              <span data-l="Price band">{band(x)}</span>
              <span data-l="Issue size">{crore(x.size_cr)}</span>
              <span data-l={upcoming ? 'Opens' : 'Closes'}>{fmtDate(upcoming ? x.start : x.end)} <Countdown d={daysTo(upcoming ? x.start : x.end, today)} verb={upcoming ? 'opens' : 'closes'} /></span>
              <span data-l={upcoming ? 'Closes' : 'Subscribed'}>{upcoming ? fmtDate(x.end) : <Times v={x.times} />}</span>
              <span className="chev">{x.symbol ? (isOpen ? '▲' : '▼') : ''}</span>
            </div>
            {isOpen && <IssueDashboard x={x} />}
          </div>
        )
      })}
    </div>
  )
}

function ListedTab({ rows, stats, board }) {
  const [sort, setSort] = useState('date')
  const sorted = useMemo(() => {
    const r = [...rows]
    if (sort === 'best') r.sort((a, b) => (b.perf?.close_vs_issue ?? -1e9) - (a.perf?.close_vs_issue ?? -1e9))
    if (sort === 'worst') r.sort((a, b) => (a.perf?.close_vs_issue ?? 1e9) - (b.perf?.close_vs_issue ?? 1e9))
    if (sort === 'now') r.sort((a, b) => (b.perf?.now_vs_issue ?? -1e9) - (a.perf?.now_vs_issue ?? -1e9))
    return r
  }, [rows, sort])
  const sets = board === 'all' ? [['Mainboard', stats.main], ['SME', stats.sme]] : [[board === 'sme' ? 'SME' : 'Mainboard', board === 'sme' ? stats.sme : stats.main]]
  const maxAbs = Math.max(10, ...rows.map((x) => Math.abs(x.perf?.close_vs_issue || 0)), ...rows.map((x) => Math.abs(x.perf?.now_vs_issue || 0)))
  const Bar = ({ v }) => (ok(v) ? (
    <div className="ipo-div2"><b style={{ color: tone(v) }}>{signed(v, 1, '%')}</b><span className="trk"><i style={{ [v >= 0 ? 'left' : 'right']: '50%', width: `${(Math.abs(v) / maxAbs) * 50}%`, background: tone(v) }} /></span></div>
  ) : <span className="muted">—</span>)
  return (
    <>
      {sets.map(([label, s]) => (
        <div key={label} className="ipo-kpis" style={{ marginBottom: 10 }}>
          <KPI k={`${label} listings measured`} v={s.n || 0} s="last 120 days, with prices" />
          <KPI k="Closed above issue price on day 1" v={s.n ? `${s.above_listing} of ${s.n}` : '—'} s={s.n ? `${num((s.above_listing / s.n) * 100, 0)}%` : null} />
          <KPI k="Median listing-day close" v={s.n ? <Pct v={s.median_listing} /> : '—'} s="vs issue price" />
          <KPI k="Above issue price now" v={s.n ? `${s.above_now} of ${s.n}` : '—'} s={s.n ? `median ${signed(s.median_now, 1, '%')}` : null} />
        </div>
      ))}
      <div className="row" style={{ gap: 6, margin: '4px 0 8px', flexWrap: 'wrap' }}>
        {[['date', 'Latest first'], ['best', 'Best listing day'], ['worst', 'Worst listing day'], ['now', 'Best since listing']].map(([k, l]) => <button key={k} className={`chip ${sort === k ? 'ipo-on' : ''}`} onClick={() => setSort(k)}>{l}</button>)}
      </div>
      {!rows.length ? <div className="card small muted">No IPO on this board listed on NSE in the last 120 days.</div> : (
        <div className="tbl-wrap"><table className="tbl ipo-tbl"><thead><tr>
          <th style={{ textAlign: 'left' }}>Company</th><th>Listed</th><th>Issue price</th><th>Day-1 open</th><th style={{ width: '20%' }}>Day-1 close</th><th style={{ width: '20%' }}>Now</th><th>Range since</th>
        </tr></thead><tbody>
          {sorted.map((x) => (
            <tr key={`${x.symbol}-${x.listing}`} style={{ cursor: x.symbol ? 'pointer' : 'default' }} onClick={() => x.symbol && go(`stock/${x.symbol}`)}>
              <td style={{ textAlign: 'left', whiteSpace: 'normal' }}><b>{x.company}</b> <Board sme={x.sme} />{x.perf_note && <div className="small muted">{x.perf_note}</div>}</td>
              <td>{fmtDateY(x.listing)}</td>
              <td>{ok(x.final_price) ? `₹${num(x.final_price, 2)}` : band(x)}</td>
              <td><Pct v={x.perf?.open_vs_issue} /></td>
              <td><Bar v={x.perf?.close_vs_issue} /></td>
              <td><Bar v={x.perf?.now_vs_issue} /></td>
              <td className="small">{x.perf ? <><span style={{ color: tone(x.perf.low_vs_issue) }}>{signed(x.perf.low_vs_issue, 0, '%')}</span> to <span style={{ color: tone(x.perf.high_vs_issue) }}>{signed(x.perf.high_vs_issue, 0, '%')}</span></> : '—'}</td>
            </tr>
          ))}
        </tbody></table></div>
      )}
      <div className="small muted" style={{ marginTop: 6 }}>All moves are against the final issue price NSE lists, from daily prices. Range since = lowest and highest price since listing. Tap a company for its full stock report.</div>
    </>
  )
}

function DrhpTab({ rows }) {
  if (!rows.length) return <div className="card small muted">No SEBI filings to show.</div>
  return (
    <>
      <div className="tbl-wrap"><table className="tbl ipo-tbl"><thead><tr><th style={{ textAlign: 'left' }}>Filed</th><th style={{ textAlign: 'left' }}>Company</th><th style={{ textAlign: 'left' }}>Filing</th><th style={{ textAlign: 'left' }}>Documents</th></tr></thead><tbody>
        {rows.map((x) => (
          <tr key={x.url}>
            <td style={{ textAlign: 'left' }}>{fmtDateY(x.date)}</td>
            <td style={{ textAlign: 'left', whiteSpace: 'normal' }}><b>{x.company}</b>{x.sme && <> <Board sme /></>}</td>
            <td style={{ textAlign: 'left' }}><span className={`ipo-kind ${x.kind === 'DRHP' ? 'new' : ''}`}>{x.kind === 'DRHP' ? 'New draft (DRHP)' : x.kind}</span></td>
            <td style={{ textAlign: 'left' }}><a href={x.url} target="_blank" rel="noreferrer">SEBI page ↗</a>{x.abridged && <> · <a href={x.abridged} target="_blank" rel="noreferrer">Abridged prospectus ↗</a></>}</td>
          </tr>
        ))}
      </tbody></table></div>
      <div className="small muted" style={{ marginTop: 6 }}>Latest filings on SEBI's draft offer documents page. Filing is not approval, and many companies never list.</div>
    </>
  )
}

function Sources({ rows }) {
  const [open, setOpen] = useState(false)
  if (!rows?.length) return null
  const good = rows.filter((s) => s.ok).length
  const bad = rows.some((s) => !s.ok || s.missing?.length)
  return (
    <div className="card ipo-src src-note">
      <button className="ipo-src-btn" onClick={() => setOpen(!open)}>
        <span>{bad ? '🟡' : '🟢'} Data sources: {good} of {rows.length} working</span><span className="muted small">{open ? 'hide' : 'details'}</span>
      </button>
      {open && rows.map((s) => (
        <div key={s.id} className="small ipo-src-row">
          <span>{s.ok ? '🟢' : s.stale ? '🟡' : '🔴'} <b>{s.name}</b> <span className="muted">{ok(s.count) ? `· ${num(s.count)} rows` : ''}{s.fetched ? ` · ${ago(s.fetched)}` : ''}</span></span>
          {s.missing?.length > 0 && <span style={{ color: 'var(--warn)' }}>Fields not found: {s.missing.join(', ')}</span>}
          {s.stale && <span style={{ color: 'var(--warn)' }}>Showing the last good copy. Latest try: {s.error}</span>}
          {!s.ok && !s.stale && s.error && <span style={{ color: 'var(--bad)' }}>{s.error}</span>}
          <a className="muted" href={s.url} target="_blank" rel="noreferrer">{s.url}</a>
        </div>
      ))}
    </div>
  )
}

const TABS = [['open', 'Open now'], ['upcoming', 'Upcoming'], ['listed', 'Recently listed'], ['history', 'Last 2 years'], ['lockins', 'Lock-in calendar'], ['drhp', 'Filed with SEBI']]
const BOARDS = [['all', 'All'], ['main', 'Mainboard'], ['sme', 'SME']]

function IPOPage({ tab }) {
  const [page, setPage] = useState(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [board, setBoard] = useState('all')
  const t = TABS.some(([k]) => k === tab) ? tab : 'open'
  const load = (refresh) => {
    setBusy(true)
    api(`/api/ipo?market=IN${refresh ? '&refresh=1' : ''}`).then((p) => { setPage(p); setErr('') }).catch((e) => setErr(e.message)).finally(() => setBusy(false))
  }
  useEffect(() => { load(false) }, [])
  const pick = (rows) => (rows || []).filter((x) => board === 'all' || (board === 'sme' ? x.sme : !x.sme))
  const today = page?.today
  const openRows = pick(page?.open)
  const in7 = pick(page?.upcoming).filter((x) => { const d = daysTo(x.start, today); return d !== null && d <= 7 }).length
  const closing = openRows.filter((x) => daysTo(x.end, today) === 0).length
  const filed30 = (page?.drhp || []).filter((x) => x.kind === 'DRHP' && daysTo(x.date, today) >= -30).length

  return (
    <div className="wrap ipo">
      <div className="row between wrapflex" style={{ marginBottom: 10 }}>
        <div><h2 style={{ margin: '4px 0' }}>🚀 IPO research</h2><div className="small muted">🇮🇳 Live<span className="src-note"> from NSE and SEBI</span> · every figure checked before it is shown</div></div>
        <button className="btn small" disabled={busy} onClick={() => load(true)}>{busy ? 'Refreshing…' : '↻ Refresh'}</button>
      </div>
      {err && <div className="card" style={{ color: 'var(--bad)' }}>{err}</div>}
      {page?.demo && <div className="card small muted">Demo mode: IPO data comes only from live sources, so this page is empty here.</div>}
      {page && (
        <div className="ipo-kpis top">
          <KPI k="Open for bidding" v={openRows.length} s={`${openRows.filter((x) => !x.sme).length} mainboard · ${openRows.filter((x) => x.sme).length} SME`} />
          <KPI k="Closing today" v={closing} c={closing ? 'var(--warn)' : null} s={closing ? openRows.filter((x) => daysTo(x.end, today) === 0).map((x) => x.symbol).join(', ') : 'none'} />
          <KPI k="Opening within 7 days" v={in7} s={`${pick(page.upcoming).length} announced`} />
          <KPI k="Listed in last 120 days" v={pick(page.listed).length} s={page.stats?.main?.n ? `mainboard: ${page.stats.main.above_listing} of ${page.stats.main.n} closed day 1 above issue price` : null} />
          <KPI k="New SEBI drafts (30 days)" v={filed30} s="companies preparing to list" />
        </div>
      )}
      <div className="row between wrapflex ipo-bar-top">
        <div className="tabs" style={{ position: 'static', padding: 0 }}>
          {TABS.map(([k, label]) => <button key={k} className={`tab ${t === k ? 'on' : ''}`} onClick={() => go(`ipo/${k}`)}>{label}{page && page[k] ? ` · ${(k === 'drhp' ? page.drhp : pick(page[k])).length}` : ''}</button>)}
        </div>
        {t !== 'drhp' && <div className="ipo-seg">{BOARDS.map(([k, label]) => <button key={k} className={board === k ? 'on' : ''} onClick={() => setBoard(k)}>{label}</button>)}</div>}
      </div>
      {!page && !err && <div className="card small muted">Reading NSE and SEBI…</div>}
      {page && t === 'open' && <IssueList rows={openRows} today={today} />}
      {page && t === 'upcoming' && <IssueList rows={pick(page.upcoming)} today={today} upcoming />}
      {page && t === 'listed' && <ListedTab rows={pick(page.listed)} stats={page.stats || {}} board={board} />}
      {page && t === 'drhp' && <DrhpTab rows={page.drhp} />}
      {t === 'history' && <IpoHistory market="IN" board={board} />}
      {t === 'lockins' && <LockinCalendar board={board} />}
      {page && <div style={{ marginTop: 14 }}><Sources rows={page.sources} /></div>}
    </div>
  )
}

// ------------------------------------------------------------------ listings of the last 2 years · IPO base · lock-ins
const RANGES = [['3m', '3 months', 92], ['6m', '6 months', 183], ['1y', '1 year', 365], ['2y', '2 years', 730]]
const BASE_TONE = { breakout: 'var(--good)', tight: '#a78bfa', near_high: 'var(--good)', pullback: 'var(--warn)', deep: 'var(--bad)', below_issue: 'var(--bad)', too_new: 'var(--muted)' }

function useHistory(market) {
  const [h, setH] = useState(null)
  const [err, setErr] = useState('')
  const load = () => api(`/api/ipo/history?market=${market}`).then((x) => { setH(x); setErr('') }).catch((e) => setErr(e.message))
  useEffect(() => { load() }, [market])
  useEffect(() => { if (!h?.status?.running) return undefined; const t = setTimeout(load, 8000); return () => clearTimeout(t) }, [h])
  return [h, err]
}

function HistoryProgress({ h }) {
  if (!h?.status?.running) return null
  return <div className="card small">Building the 2-year list from daily prices: {h.status.done}/{h.status.total || '…'} listings{h.rows?.length ? ' (showing the last saved list meanwhile)' : ''}. It refreshes itself.</div>
}

export function IpoHistory({ market, board = 'all' }) {
  const [h, err] = useHistory(market)
  const [range, setRange] = useState('3m')
  const [base, setBase] = useState('')
  const [sort, setSort] = useState(['listing', -1])
  const today = h?.today
  const days = (RANGES.find((r) => r[0] === range) || RANGES[0])[2]
  const rows = useMemo(() => {
    let r = (h?.rows || []).filter((x) => daysTo(x.listing, today) >= -days)
    if (board !== 'all') r = r.filter((x) => (board === 'sme' ? x.sme : !x.sme))
    if (base) r = r.filter((x) => x.base?.key === base)
    const val = (x, k) => (k === 'listing' ? x.listing : k === 'from_high' ? x.base?.from_high : k === 'adr' ? x.base?.adr : x.perf?.[k])
    const [k, dir] = sort
    return [...r].sort((a, b) => { const va = val(a, k), vb = val(b, k); if (va == null) return 1; if (vb == null) return -1; return (va > vb ? 1 : va < vb ? -1 : 0) * dir })
  }, [h, days, board, base, sort, today])
  const m = rows.filter((x) => x.perf)
  const med = (k) => { const v = m.map((x) => x.perf[k]).filter(ok).sort((a, b) => a - b); return v.length ? v[v.length >> 1] : null }
  const counts = {}
  for (const x of (h?.rows || []).filter((y) => daysTo(y.listing, today) >= -days)) if (x.base) counts[x.base.key] = (counts[x.base.key] || 0) + 1
  const money = market === 'US' ? (x) => usSize(x.value_m) : (x) => crore(x.size_cr)
  const px = market === 'US' ? (v) => usd(v) : (v) => rupees(v)
  const th = (k, l) => <th onClick={() => setSort([k, sort[0] === k ? -sort[1] : -1])} style={{ cursor: 'pointer' }}>{l}{sort[0] === k ? (sort[1] < 0 ? ' ▾' : ' ▴') : ''}</th>
  if (err) return <div className="card" style={{ color: 'var(--bad)' }}>{err}</div>
  if (!h) return <div className="card small muted">Loading listings…</div>
  return (
    <>
      <HistoryProgress h={h} />
      <div className="ipo-kpis" style={{ marginBottom: 10 }}>
        <KPI k={`Listed in the last ${(RANGES.find((r) => r[0] === range) || RANGES[0])[1]}`} v={rows.length} s={`${m.length} measured with daily prices`} />
        <KPI k="Above issue price now" v={m.length ? `${m.filter((x) => x.perf.now_vs_issue > 0).length} of ${m.length}` : '—'} s={m.length ? `median ${signed(med('now_vs_issue'), 1, '%')}` : null} />
        <KPI k="Median day-1 close" v={m.length ? <Pct v={med('close_vs_issue')} /> : '—'} s="vs issue price" />
        <KPI k="Breaking out of IPO base" v={counts.breakout || 0} s={`${counts.tight || 0} forming a base`} />
      </div>
      <div className="row wrapflex" style={{ gap: 6, marginBottom: 8 }}>
        {RANGES.map(([k, l]) => <button key={k} className={`chip ${range === k ? 'ipo-on' : ''}`} onClick={() => setRange(k)}>{l}</button>)}
        <span className="small muted" style={{ marginLeft: 8 }}>IPO base</span>
        <button className={`chip ${!base ? 'ipo-on' : ''}`} onClick={() => setBase('')}>All</button>
        {Object.entries(h.base_rules || {}).map(([k, r]) => <button key={k} title={r.rule} className={`chip ${base === k ? 'ipo-on' : ''}`} onClick={() => setBase(base === k ? '' : k)}>{r.label} · {counts[k] || 0}</button>)}
      </div>
      <div className="tbl-wrap"><table className="tbl ipo-tbl"><thead><tr>
        <th style={{ textAlign: 'left' }}>Company</th>{th('listing', 'Listed')}<th>Issue price</th><th>Size</th>{th('close_vs_issue', 'Day-1 close')}{th('now_vs_issue', 'Now vs issue')}{th('from_high', 'From high')}<th>IPO base</th>{th('adr', 'ADR')}{market === 'IN' && <th>Next lock-in</th>}
      </tr></thead><tbody>
        {rows.map((x) => {
          const nxt = (x.lockins || []).find((l) => !l.past)
          const sym = market === 'US' ? (x.symbol ? `US:${x.symbol}` : null) : x.symbol
          return (
            <tr key={`${x.symbol}-${x.listing}`} style={{ cursor: sym ? 'pointer' : 'default' }} onClick={() => sym && go(`stock/${sym}`)}>
              <td style={{ textAlign: 'left', whiteSpace: 'normal' }}><span className="co"><Initials name={x.company} /><span className="nm"><b>{x.company}</b><small>{x.symbol || '—'}{market === 'IN' ? <> · <Board sme={x.sme} /></> : x.exchange ? ` · ${x.exchange}` : ''}</small></span></span>{x.note && <div className="small muted">{x.note}</div>}</td>
              <td>{fmtDateY(x.listing)}</td><td>{px(x.final_price)}</td><td>{money(x)}</td>
              <td><Pct v={x.perf?.close_vs_issue} /></td><td><Pct v={x.perf?.now_vs_issue} /></td>
              <td><Pct v={x.base?.from_high} /></td>
              <td>{x.base ? <b style={{ color: BASE_TONE[x.base.key] }} title={h.base_rules?.[x.base.key]?.rule}>{x.base.label}</b> : '—'}</td>
              <td>{ok(x.base?.adr) ? `${num(x.base.adr, 1)}%` : '—'}</td>
              {market === 'IN' && <td className="small">{nxt ? <>{fmtDateY(nxt.date)}<div className="muted">{nxt.who === 'anchor' ? `anchor ${nxt.days} days` : nxt.who === 'pre' ? 'pre-IPO, 6 months' : 'promoters, 18 months'}</div></> : '—'}</td>}
            </tr>
          )
        })}
      </tbody></table></div>
      <div className="small muted" style={{ marginTop: 6, lineHeight: 1.6 }}>
        Moves are against the issue price from daily prices (first trading day on or after the listing date). From high = last close vs the highest price since listing. ADR = average daily range of the last 20 sessions.
        {Object.values(h.base_rules || {}).map((r) => <div key={r.label}><b>{r.label}:</b> {r.rule}</div>)}
      </div>
    </>
  )
}

export function LockinCalendar({ board = 'all' }) {
  const [h, err] = useHistory('IN')
  const today = h?.today
  const ev = useMemo(() => {
    const out = []
    for (const x of h?.rows || []) {
      if (board !== 'all' && (board === 'sme' ? !x.sme : x.sme)) continue
      for (const l of x.lockins || []) { const d = daysTo(l.date, today); if (d !== null && d >= -7 && d <= 120) out.push({ ...l, x, d }) }
    }
    return out.sort((a, b) => a.date.localeCompare(b.date))
  }, [h, board, today])
  if (err) return <div className="card" style={{ color: 'var(--bad)' }}>{err}</div>
  if (!h) return <div className="card small muted">Loading listings…</div>
  return (
    <>
      <HistoryProgress h={h} />
      <div className="card small">{h.lockin_note}</div>
      {!ev.length ? <div className="card small muted">No lock-in ends in the next 120 days for listings of the last 2 years.</div> : (
        <div className="tbl-wrap"><table className="tbl ipo-tbl"><thead><tr><th style={{ textAlign: 'left' }}>Date</th><th style={{ textAlign: 'left' }}>Company</th><th style={{ textAlign: 'left' }}>Who can sell</th><th>Now vs issue</th><th>From high</th></tr></thead>
          <tbody>{ev.map((e) => (
            <tr key={`${e.x.symbol}-${e.date}-${e.who}-${e.days}`} onClick={() => e.x.symbol && go(`stock/${e.x.symbol}`)} style={{ cursor: 'pointer', opacity: e.d < 0 ? 0.6 : 1 }}>
              <td style={{ textAlign: 'left' }}><b>{fmtDateY(e.date)}</b><div className="small muted">{e.d < 0 ? `${-e.d} days ago` : e.d === 0 ? 'today' : `in ${e.d} days`}</div></td>
              <td style={{ textAlign: 'left', whiteSpace: 'normal' }}><b>{e.x.company}</b> <span className="small muted">{e.x.symbol}</span> <Board sme={e.x.sme} /></td>
              <td style={{ textAlign: 'left', whiteSpace: 'normal' }} className="small">{e.what}</td>
              <td><Pct v={e.x.perf?.now_vs_issue} /></td><td><Pct v={e.x.base?.from_high} /></td>
            </tr>
          ))}</tbody></table></div>
      )}
    </>
  )
}

// ------------------------------------------------------------------ 🇺🇸 US IPOs (Nasdaq IPO calendar)
const usd = (v, d = 2) => (ok(v) ? `$${num(v, d)}` : '—')
const usBand = (x) => (ok(x.band_low) && ok(x.band_high) ? (x.band_low === x.band_high ? usd(x.band_low) : `${usd(x.band_low)}–${num(x.band_high, 2)}`) : '—')
const usSize = (v) => (ok(v) ? (v >= 1000 ? `$${num(v / 1000, 2)} B` : `$${num(v, v < 10 ? 2 : 0)} M`) : '—')
const shares = (v) => (ok(v) ? (v >= 1e6 ? `${num(v / 1e6, 2)} M` : num(v)) : '—')

function UsName({ x }) {
  return <span className="co"><Initials name={x.company} /><span className="nm"><b>{x.company}</b><small>{x.symbol || 'no ticker yet'}{x.exchange ? ` · ${x.exchange}` : ''}</small></span></span>
}

function UsUpcoming({ rows, today }) {
  if (!rows.length) return <div className="card small muted">Nasdaq's calendar lists no IPO expected to price right now.</div>
  return (
    <div className="tbl-wrap"><table className="tbl ipo-tbl"><thead><tr>
      <th style={{ textAlign: 'left' }}>Company</th><th>Expected pricing</th><th>Price range</th><th>Shares offered</th><th>Deal size</th>
    </tr></thead><tbody>
      {rows.map((x) => (
        <tr key={x.deal || x.company}>
          <td style={{ textAlign: 'left', whiteSpace: 'normal' }}><UsName x={x} /></td>
          <td>{fmtDate(x.expected)} <Countdown d={daysTo(x.expected, today)} verb="prices" /></td>
          <td>{usBand(x)}</td><td>{shares(x.shares)}</td><td>{usSize(x.value_m)}</td>
        </tr>
      ))}
    </tbody></table></div>
  )
}

function UsPriced({ rows, stats }) {
  const [sort, setSort] = useState('date')
  const sorted = useMemo(() => {
    const r = [...rows]
    if (sort === 'best') r.sort((a, b) => (b.perf?.close_vs_issue ?? -1e9) - (a.perf?.close_vs_issue ?? -1e9))
    if (sort === 'worst') r.sort((a, b) => (a.perf?.close_vs_issue ?? 1e9) - (b.perf?.close_vs_issue ?? 1e9))
    if (sort === 'now') r.sort((a, b) => (b.perf?.now_vs_issue ?? -1e9) - (a.perf?.now_vs_issue ?? -1e9))
    if (sort === 'size') r.sort((a, b) => (b.value_m ?? -1) - (a.value_m ?? -1))
    return r
  }, [rows, sort])
  const s = stats?.main || { n: 0 }
  const raised = rows.reduce((a, x) => a + (x.value_m || 0), 0)
  return (
    <>
      <div className="ipo-kpis" style={{ marginBottom: 10 }}>
        <KPI k="Priced in last 120 days" v={rows.length} s={raised ? `${usSize(raised)} raised (deals with a checked size)` : null} />
        <KPI k="Measured with prices" v={s.n || 0} s="first trading day found" />
        <KPI k="Closed above IPO price on day 1" v={s.n ? `${s.above_listing} of ${s.n}` : '—'} s={s.n ? `${num((s.above_listing / s.n) * 100, 0)}%` : null} />
        <KPI k="Median day-1 close" v={s.n ? <Pct v={s.median_listing} /> : '—'} s="vs IPO price" />
        <KPI k="Above IPO price now" v={s.n ? `${s.above_now} of ${s.n}` : '—'} s={s.n ? `median ${signed(s.median_now, 1, '%')}` : null} />
      </div>
      <div className="row" style={{ gap: 6, margin: '4px 0 8px', flexWrap: 'wrap' }}>
        {[['date', 'Latest first'], ['size', 'Biggest deals'], ['best', 'Best day 1'], ['worst', 'Worst day 1'], ['now', 'Best since IPO']].map(([k, l]) => <button key={k} className={`chip ${sort === k ? 'ipo-on' : ''}`} onClick={() => setSort(k)}>{l}</button>)}
      </div>
      {!rows.length ? <div className="card small muted">No IPO priced in the last 120 days on Nasdaq's calendar.</div> : (
        <div className="tbl-wrap"><table className="tbl ipo-tbl"><thead><tr>
          <th style={{ textAlign: 'left' }}>Company</th><th>Priced</th><th>IPO price</th><th>Deal size</th><th>Day-1 open</th><th>Day-1 close</th><th>Now</th><th>Range since</th>
        </tr></thead><tbody>
          {sorted.map((x) => (
            <tr key={x.deal || `${x.symbol}-${x.priced}`} style={{ cursor: x.symbol ? 'pointer' : 'default' }} onClick={() => x.symbol && go(`stock/${x.symbol}`)}>
              <td style={{ textAlign: 'left', whiteSpace: 'normal' }}><UsName x={x} />{x.perf_note && <div className="small muted">{x.perf_note}</div>}</td>
              <td>{fmtDateY(x.priced)}</td>
              <td>{ok(x.final_price) ? usd(x.final_price) : usBand(x)}</td>
              <td>{usSize(x.value_m)}{x.value_note && <div className="small muted">{x.value_note}</div>}</td>
              <td><Pct v={x.perf?.open_vs_issue} /></td>
              <td><Pct v={x.perf?.close_vs_issue} /></td>
              <td><Pct v={x.perf?.now_vs_issue} /></td>
              <td className="small">{x.perf ? <><span style={{ color: tone(x.perf.low_vs_issue) }}>{signed(x.perf.low_vs_issue, 0, '%')}</span> to <span style={{ color: tone(x.perf.high_vs_issue) }}>{signed(x.perf.high_vs_issue, 0, '%')}</span></> : '—'}</td>
            </tr>
          ))}
        </tbody></table></div>
      )}
      <div className="small muted" style={{ marginTop: 6 }}>Moves are against the IPO price on Nasdaq's calendar, from daily prices. Day 1 = first trading day on or after the pricing date. Tap a company for its stock report.</div>
    </>
  )
}

function UsFiled({ rows, withdrawn }) {
  if (!rows.length) return <div className="card small muted">{withdrawn ? 'No withdrawn IPOs in this window.' : 'No new SEC filings in this window.'}</div>
  return (
    <>
      <div className="tbl-wrap"><table className="tbl ipo-tbl"><thead><tr>
        <th style={{ textAlign: 'left' }}>Company</th><th>Filed</th>{withdrawn && <th>Withdrawn</th>}<th>Shares</th><th>Deal size</th>
      </tr></thead><tbody>
        {rows.map((x) => (
          <tr key={x.deal || x.company}>
            <td style={{ textAlign: 'left', whiteSpace: 'normal' }}><UsName x={x} /></td>
            <td>{fmtDateY(x.filed)}</td>{withdrawn && <td>{fmtDateY(x.withdrawn)}</td>}
            <td>{shares(x.shares)}</td><td>{usSize(x.value_m)}</td>
          </tr>
        ))}
      </tbody></table></div>
      <div className="small muted" style={{ marginTop: 6 }}>{withdrawn ? 'Companies that pulled their IPO plans.' : 'Companies that filed an IPO registration with the SEC. Filing is not approval, and the size is the proposed amount.'}</div>
    </>
  )
}

const US_TABS = [['upcoming', 'Upcoming'], ['priced', 'Recently priced'], ['history', 'Last 2 years'], ['filed', 'Filed with SEC'], ['withdrawn', 'Withdrawn']]

function UsIPOPage({ tab }) {
  const [page, setPage] = useState(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const t = US_TABS.some(([k]) => k === tab) ? tab : 'upcoming'
  const load = (refresh) => {
    setBusy(true)
    api(`/api/ipo?market=US${refresh ? '&refresh=1' : ''}`).then((p) => { setPage(p); setErr('') }).catch((e) => setErr(e.message)).finally(() => setBusy(false))
  }
  useEffect(() => { load(false) }, [])
  const today = page?.today
  const wk = (page?.upcoming || []).filter((x) => { const d = daysTo(x.expected, today); return d !== null && d >= 0 && d <= 7 }).length
  const filed30 = (page?.filed || []).filter((x) => daysTo(x.filed, today) >= -30).length
  return (
    <div className="wrap ipo">
      <div className="row between wrapflex" style={{ marginBottom: 10 }}>
        <div><h2 style={{ margin: '4px 0' }}>🚀 IPO research</h2><div className="small muted">🇺🇸 Live<span className="src-note"> from Nasdaq's IPO calendar</span> · deal sizes checked against shares × price</div></div>
        <button className="btn small" disabled={busy} onClick={() => load(true)}>{busy ? 'Refreshing…' : '↻ Refresh'}</button>
      </div>
      {err && <div className="card" style={{ color: 'var(--bad)' }}>{err}</div>}
      {page?.demo && <div className="card small muted">Demo mode: IPO data comes only from live sources, so this page is empty here.</div>}
      {page && (
        <div className="ipo-kpis top">
          <KPI k="Expected to price" v={(page.upcoming || []).length} s={`${wk} within 7 days`} />
          <KPI k="Priced in last 120 days" v={(page.priced || []).length} s={page.stats?.main?.n ? `${page.stats.main.above_listing} of ${page.stats.main.n} closed day 1 above IPO price` : null} />
          <KPI k="New SEC filings (30 days)" v={filed30} s="companies preparing to list" />
          <KPI k="Withdrawn" v={(page.withdrawn || []).length} s="in the last few months" />
        </div>
      )}
      <div className="row between wrapflex ipo-bar-top">
        <div className="tabs" style={{ position: 'static', padding: 0 }}>
          {US_TABS.map(([k, label]) => <button key={k} className={`tab ${t === k ? 'on' : ''}`} onClick={() => go(`ipo/${k}`)}>{label}{page && page[k] ? ` · ${page[k].length}` : ''}</button>)}
        </div>
      </div>
      {!page && !err && <div className="card small muted">Reading Nasdaq's IPO calendar…</div>}
      {page && t === 'upcoming' && <UsUpcoming rows={page.upcoming || []} today={today} />}
      {page && t === 'priced' && <UsPriced rows={page.priced || []} stats={page.stats} />}
      {page && t === 'filed' && <UsFiled rows={page.filed || []} />}
      {page && t === 'withdrawn' && <UsFiled rows={page.withdrawn || []} withdrawn />}
      {t === 'history' && <IpoHistory market="US" />}
      {page && <div style={{ marginTop: 14 }}><Sources rows={page.sources} /></div>}
    </div>
  )
}

export default function IPO({ tab }) {
  return getMarket() === 'US' ? <UsIPOPage tab={tab} /> : <IPOPage tab={tab} />
}
