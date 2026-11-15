import { useEffect, useMemo, useState } from 'react'
import { FnoBadge, FnoToggle, Logo, UniverseChips, useFno, useUniv } from '../components/ui'
import { api, getMarket, go, inUniv, isDesktop, num, ok, signed, univLabel, watchlist } from '../util'
import { Md } from './AI'

// ---------- dates (all in the viewer's own time zone)
const pad = (n) => String(n).padStart(2, '0')
const iso = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
const parse = (s) => { const [y, m, d] = s.split('-').map(Number); return new Date(y, m - 1, d, 12) }
const addDays = (s, n) => { const d = parse(s); d.setDate(d.getDate() + n); return iso(d) }
const monday = (s) => { const d = parse(s); const k = (d.getDay() + 6) % 7; d.setDate(d.getDate() - k); return iso(d) }
const todayIso = () => iso(new Date())
// on Saturday/Sunday the useful week is the coming one
const defaultWeek = () => { const d = new Date().getDay(); return d === 6 || d === 0 ? monday(addDays(todayIso(), 2)) : monday(todayIso()) }
const dayName = (s, o = { weekday: 'short', day: 'numeric', month: 'short' }) => parse(s).toLocaleDateString('en-IN', o)
const diffDays = (s) => Math.round((parse(s) - parse(todayIso())) / 86400000)
const rel = (s) => { const n = diffDays(s); return n === 0 ? 'Today' : n === 1 ? 'Tomorrow' : n === -1 ? 'Yesterday' : n > 0 ? `in ${n} days` : `${-n} days ago` }
const localDay = (at) => (at ? iso(new Date(at)) : null)
const localTime = (at) => (at ? new Date(at).toLocaleTimeString('en-IN', { hour: 'numeric', minute: '2-digit' }) : 'All day')
const etTime = (at) => (at ? new Date(at).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', timeZone: 'America/New_York' }) + ' ET' : '')
const myZone = (() => { try { return new Intl.DateTimeFormat('en', { timeZoneName: 'short' }).formatToParts(new Date()).find((p) => p.type === 'timeZoneName')?.value || '' } catch { return '' } })()
const countdown = (at, date) => {
  const ms = new Date(at || `${date}T00:00:00`) - Date.now()
  if (ms < 0) return 'done'
  const d = Math.floor(ms / 86400000), h = Math.floor((ms % 86400000) / 3600000)
  return d > 0 ? `in ${d}d ${h}h` : `in ${h}h ${Math.floor((ms % 3600000) / 60000)}m`
}

// ---------- add to your phone / Google / Outlook calendar (.ics file)
function addToCalendar({ title, date, at, details, url }) {
  const stamp = (d) => d.toISOString().replace(/[-:]/g, '').replace(/\.\d{3}/, '')
  const esc = (t) => String(t || '').replace(/[\\;,]/g, (m) => '\\' + m).replace(/\n/g, '\\n')
  const lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//EquityLens//Calendar//EN', 'BEGIN:VEVENT',
    `UID:${Date.now()}-${Math.random().toString(36).slice(2)}@equitylens`, `DTSTAMP:${stamp(new Date())}`]
  if (at) {
    const s = new Date(at)
    lines.push(`DTSTART:${stamp(s)}`, `DTEND:${stamp(new Date(s.getTime() + 30 * 60000))}`, 'BEGIN:VALARM', 'TRIGGER:-PT30M', 'ACTION:DISPLAY', `DESCRIPTION:${esc(title)}`, 'END:VALARM')
  } else {
    lines.push(`DTSTART;VALUE=DATE:${date.replace(/-/g, '')}`, `DTEND;VALUE=DATE:${addDays(date, 1).replace(/-/g, '')}`)
  }
  lines.push(`SUMMARY:${esc(title)}`, `DESCRIPTION:${esc(details)}`, ...(url ? [`URL:${url}`] : []), 'END:VEVENT', 'END:VCALENDAR')
  const a = document.createElement('a')
  a.href = URL.createObjectURL(new Blob([lines.join('\r\n')], { type: 'text/calendar' }))
  a.download = `${title.replace(/[^\w]+/g, '_').slice(0, 40)}.ics`
  document.body.appendChild(a); a.click(); a.remove()
}
const CalBtn = (p) => <button className="cal-add" title="Add to my calendar" onClick={(e) => { e.stopPropagation(); addToCalendar(p) }}>＋📅</button>

const TIMING = { BMO: ['☀️', 'Before open'], AMC: ['🌙', 'After close'], TBD: ['🕓', 'Time not given'] }
const IN_TYPES = ['Results', 'Dividend', 'Bonus', 'Stock split', 'Buyback', 'Fund raising', 'Rights issue', 'Merger / scheme', 'Board meeting']
const TYPE_EMOJI = { Results: '📊', Dividend: '💸', Bonus: '🎁', 'Stock split': '✂️', Buyback: '🔁', 'Fund raising': '🏦', 'Rights issue': '🧾', 'Merger / scheme': '🤝', Delisting: '🚪', 'Board meeting': '🗓️' }
const Stars = ({ n }) => <span className="stars" title={['', 'Low', 'Medium', 'High'][n] + ' impact'}>{'★'.repeat(n)}<span className="off">{'★'.repeat(3 - n)}</span></span>

function DayStrip({ start, perDay, sel, onSel }) {
  return (
    <div className="daystrip">
      {[0, 1, 2, 3, 4, 5, 6].map((i) => {
        const d = addDays(start, i), n = perDay?.[d] || 0
        return (
          <button key={d} className={`dd ${sel === d ? 'on' : ''} ${d === todayIso() ? 'today' : ''}`} onClick={() => onSel(sel === d ? null : d)}>
            <span className="dw">{dayName(d, { weekday: 'short' })}</span><span className="dn">{parse(d).getDate()}</span>
            <span className="dc">{n ? n : '·'}</span>
          </button>
        )
      })}
    </div>
  )
}

// ======================================================================= results
function ResultRow({ r, mk, starred }) {
  const us = mk === 'US'
  const growth = us && ok(r.eps_estimate) && ok(r.eps_last_year) && r.eps_last_year !== 0 ? ((r.eps_estimate - r.eps_last_year) / Math.abs(r.eps_last_year)) * 100 : null
  const reported = us ? ok(r.eps_actual) : r.date < todayIso()
  const beat = ok(r.surprise_pct) ? (r.surprise_pct > 1 ? 'good' : r.surprise_pct < -1 ? 'bad' : 'neutral') : null
  const title = `${r.name} ${us ? 'earnings' : r.type.toLowerCase()}`
  const details = us ? `EPS estimate ${ok(r.eps_estimate) ? '$' + r.eps_estimate : 'n/a'} · ${TIMING[r.timing]?.[1] || ''} · via EquityLens` : `${r.purpose}${r.detail ? ' — ' + r.detail : ''} · via EquityLens`
  return (
    <div className="mv-row cal-row" onClick={() => go(`stock/${r.symbol}`)}>
      <Logo sym={r.symbol} name={r.name} size={34} />
      <div className="grow" style={{ minWidth: 0 }}>
        <div className="ellip"><b>{r.name}</b> <span className="small muted">{r.ticker}</span>{r.fno && <FnoBadge />}{starred && <span className="tagc warnc">★ watchlist</span>}</div>
        <div className="small muted ellip">
          {us ? <>{TIMING[r.timing]?.[0]} {TIMING[r.timing]?.[1]}{r.fiscal_quarter ? ` · qtr ${r.fiscal_quarter}` : ''}{ok(r.market_cap) ? ` · $${num(r.market_cap / 1000, 1)}B` : ''}</>
            : <>{TYPE_EMOJI[r.type] || '🗓️'} {r.purpose}{ok(r.market_cap) ? ` · ₹${num(r.market_cap, 0)} Cr` : ''}</>}
        </div>
        {r.fund && <span className={`badge sm t-${r.fund.tone} bg-${r.fund.tone}`} style={{ marginTop: 3 }}>{r.fund.overall ?? '—'} · {r.fund.verdict}</span>}
      </div>
      <div className="cal-num">
        {us && !reported && <><div className="small muted">EPS est.</div><b>{ok(r.eps_estimate) ? `$${num(r.eps_estimate, 2)}` : '—'}</b>
          {ok(growth) && <div className={`small ${growth >= 0 ? 't-good' : 't-bad'}`}>{signed(growth, 0, '%')} y/y</div>}</>}
        {us && reported && <><div className="small muted">EPS ${num(r.eps_actual, 2)}</div>{beat && <span className={`badge sm t-${beat} bg-${beat}`}>{r.surprise_pct > 1 ? 'Beat' : r.surprise_pct < -1 ? 'Miss' : 'In line'} {signed(r.surprise_pct, 1, '%')}</span>}</>}
        {ok(r.reaction) && <div className={`small ${r.reaction >= 0 ? 't-good' : 't-bad'}`} title="Price move: session after the results vs session before">{r.reaction >= 0 ? '📈' : '📉'} {signed(r.reaction, 1, '%')}</div>}
        {!us && !ok(r.reaction) && <div className="small muted">{reported ? 'announced' : rel(r.date)}</div>}
      </div>
      <CalBtn title={title} date={r.date} details={details} />
    </div>
  )
}

function Results({ mk, start, sel }) {
  const [d, setD] = useState(null), [err, setErr] = useState(null)
  const [onlyIdx, setOnlyIdx] = useState(true), [onlyWatch, setOnlyWatch] = useState(false), [onlyScanned, setOnlyScanned] = useState(false)
  const [timing, setTiming] = useState(''), [types, setTypes] = useState(['Results']), [q, setQ] = useState('')
  const [fno] = useFno()
  const [univ] = useUniv()
  useEffect(() => { setD(null); setErr(null); api(`/api/calendar/earnings?market=${mk}&start=${start}&days=7`).then(setD).catch((e) => setErr(e.message)) }, [mk, start])
  const watch = useMemo(() => new Set(watchlist.all().map((w) => w.symbol)), [])
  const rows = useMemo(() => (d?.rows || []).filter((r) => (!sel || r.date === sel)
    && (mk === 'US' || types.length === 0 || types.includes(r.type))
    && (mk === 'IN' ? (inUniv(r, univ) || watch.has(r.symbol)) : (!onlyIdx || r.in_index || watch.has(r.symbol))) && (!onlyWatch || watch.has(r.symbol)) && (!onlyScanned || r.fund)
    && (!timing || r.timing === timing) && (!fno || r.fno) && (!q || (r.name + ' ' + r.ticker).toLowerCase().includes(q.toLowerCase()))), [d, sel, types, onlyIdx, onlyWatch, onlyScanned, timing, q, mk, fno, univ])
  const mine = (d?.rows || []).filter((r) => watch.has(r.symbol) && (mk === 'US' || r.type === 'Results'))
  const days = useMemo(() => { const g = {}; rows.forEach((r) => { (g[r.date] = g[r.date] || []).push(r) }); Object.values(g).forEach((l) => l.sort((a, b) => (watch.has(b.symbol) - watch.has(a.symbol)))); return g }, [rows])
  // scorecard of what already reported this week
  const rep = (d?.rows || []).filter((r) => (r.in_index || r.fund) && (mk === 'US' ? ok(r.surprise_pct) : r.type === 'Results' && r.date < todayIso()))
  const beats = rep.filter((r) => r.surprise_pct > 1).length
  const reacts = rep.filter((r) => ok(r.reaction)).map((r) => r.reaction)
  const avg = (a) => (a.length ? a.reduce((x, y) => x + y, 0) / a.length : null)

  return (
    <>
      {mine.length > 0 && (
        <div className="card cal-mine">
          <h3>⭐ Your watchlist this week</h3>
          {mine.map((r) => <span key={r.symbol + r.date} className="chip chip-logo" style={{ cursor: 'pointer' }} onClick={() => go(`stock/${r.symbol}`)}><Logo sym={r.symbol} name={r.name} size={18} />{r.ticker} · {dayName(r.date)} {r.timing && r.timing !== 'TBD' ? TIMING[r.timing][0] : ''}</span>)}
        </div>
      )}
      {rep.length > 0 && (
        <div className="card">
          <h3>🧾 Reported so far {mk === 'US' ? '(index & scanned stocks)' : '(NIFTY 500 & scanned)'}</h3>
          <div className="grid3">
            <div className="tile"><div className="k">Reported</div><div className="v">{rep.length}</div></div>
            {mk === 'US' ? <div className="tile"><div className="k">Beat estimates</div><div className="v">{Math.round((beats / rep.length) * 100)}%</div></div>
              : <div className="tile"><div className="k">Rose after results</div><div className="v">{reacts.length ? `${reacts.filter((x) => x > 0).length}/${reacts.length}` : '—'}</div></div>}
            <div className="tile"><div className="k">Avg price reaction</div><div className={`v ${avg(reacts) >= 0 ? 't-good' : 't-bad'}`}>{reacts.length ? signed(avg(reacts), 1, '%') : '—'}</div></div>
          </div>
          <div className="small muted" style={{ marginTop: 6 }}>Price reaction = close of the session after the announcement vs the session before (from Market Movers prices).</div>
        </div>
      )}
      <div className="card" style={{ paddingBottom: 8 }}>
        {mk === 'IN' && (
          <div className="list-chips" style={{ marginBottom: 8 }}>
            <button className={`tab ${types.length === 0 ? 'on' : ''}`} onClick={() => setTypes([])}>All events</button>
            {IN_TYPES.map((t) => <button key={t} className={`tab ${types.includes(t) ? 'on' : ''}`} onClick={() => setTypes(types.includes(t) ? types.filter((x) => x !== t) : [...types, t])}>{TYPE_EMOJI[t]} {t}</button>)}
          </div>
        )}
        <div className="row wrapflex" style={{ gap: 6 }}>
          {mk === 'US' ? <button className={`tab ${onlyIdx ? 'on' : ''}`} onClick={() => setOnlyIdx(!onlyIdx)}>🏛️ S&P 500 only</button> : <UniverseChips />}
          <button className={`tab ${onlyWatch ? 'on' : ''}`} onClick={() => setOnlyWatch(!onlyWatch)}>⭐ Watchlist</button>
          <button className={`tab ${onlyScanned ? 'on' : ''}`} onClick={() => setOnlyScanned(!onlyScanned)}>🏆 Scanned ({d?.scanned || 0})</button>
          <FnoToggle />
          {mk === 'US' && ['BMO', 'AMC'].map((t) => <button key={t} className={`tab ${timing === t ? 'on' : ''}`} onClick={() => setTiming(timing === t ? '' : t)}>{TIMING[t][0]} {TIMING[t][1]}</button>)}
        </div>
        <input className="cal-q" placeholder="Find a company…" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      {err && <div className="card t-bad">⚠️ {err}</div>}
      {!d && !err && <div className="card empty">Loading the {mk === 'US' ? 'earnings' : 'results'} calendar…</div>}
      {d?.notes?.length > 0 && <div className="card small t-warn">⚠️ {d.notes.join(' · ')}</div>}
      {d && rows.length === 0 && <div className="card empty">Nothing matches for {sel ? dayName(sel) : 'this week'}{mk === 'US' ? (onlyIdx ? ' in the S&P 500 — turn off "S&P 500 only" to see every company' : '') : (univ !== 'ALL' ? ` in the ${univLabel(univ)} — pick "All NSE" to see every company` : '')}.</div>}
      {Object.entries(days).map(([day, list]) => (
        <div key={day} className="card" style={{ padding: 0 }}>
          <div className={`cal-day ${day === todayIso() ? 'today' : ''}`}><b>{dayName(day, { weekday: 'long', day: 'numeric', month: 'short' })}</b><span className="small muted">{rel(day)} · {list.length}</span></div>
          {list.slice(0, 120).map((r) => <ResultRow key={r.symbol + r.type + r.date} r={r} mk={mk} starred={watch.has(r.symbol)} />)}
          {list.length > 120 && <div className="small muted" style={{ padding: 10 }}>+{list.length - 120} more — use the search box or filters.</div>}
        </div>
      ))}
      {d && <div className="small muted src">Source: {d.source}. Dates are set by the companies and can change.</div>}
    </>
  )
}

// ======================================================================= economy
function EconRow({ e, mk }) {
  const [open, setOpen] = useState(false)
  const tone = e.vs_forecast === 'above' ? 'ok' : e.vs_forecast === 'below' ? 'warn' : 'neutral'
  return (
    <div className={`ev-row ${e.importance === 3 ? 'hi' : ''}`} onClick={() => setOpen(!open)}>
      <div className="ev-time"><b>{localTime(e.at)}</b>{e.at && localDay(e.at) !== e.date && <div className="small t-warn">{localDay(e.at) > e.date ? 'next day' : 'prev. day'}</div>}{mk === 'US' && e.at && <div className="small muted">{etTime(e.at)}</div>}</div>
      <div className="grow" style={{ minWidth: 0 }}>
        <div><b>{e.event}</b> <Stars n={e.importance} />{e.official && <span className="tagc offc">📌 official date</span>}</div>
        <div className="ev-vals">
          {e.actual ? <span className={`badge sm t-${tone} bg-${tone}`}>Actual {e.actual}</span> : <span className="small muted">{e.date < todayIso() ? 'no print' : 'not out yet'}</span>}
          <span className="small">Forecast <b>{e.forecast || '—'}</b></span>
          <span className="small">Previous <b>{e.previous || '—'}</b></span>
          {e.vs_forecast && <span className={`small t-${tone}`}>{e.vs_forecast === 'in line' ? '= in line' : `${e.vs_forecast === 'above' ? '▲' : '▼'} ${e.vs_forecast} forecast`}</span>}
        </div>
        {open && (
          <div className="ev-more small">
            {e.what && <div><b>What it is:</b> {e.what}</div>}
            {e.why && <div><b>Why markets care:</b> {e.why}</div>}
            {e.note && <div className="muted">🕓 {e.note}</div>}
            {!e.what && e.about_source && <div className="muted">{e.about_source}</div>}
            {(e.official_source || (e.official && e.source)) && <a href={e.official_source || e.source} target="_blank" rel="noreferrer" onClick={(x) => x.stopPropagation()}>Official schedule ↗</a>}
          </div>
        )}
      </div>
      <CalBtn title={`${mk === 'US' ? '🇺🇸' : '🇮🇳'} ${e.event}`} date={e.date} at={e.at} details={`${e.what || ''} Forecast ${e.forecast || '—'}, previous ${e.previous || '—'}. via EquityLens`} url={e.official_source || (e.official ? e.source : undefined)} />
    </div>
  )
}

function Economy({ mk, start, sel, onBig }) {
  const [d, setD] = useState(null), [err, setErr] = useState(null), [imp, setImp] = useState(2)
  useEffect(() => { setD(null); setErr(null); api(`/api/calendar/economy?market=${mk}&start=${start}&days=7`).then((x) => { setD(x); onBig(x.next_big) }).catch((e) => setErr(e.message)) }, [mk, start])
  const ev = (d?.events || []).filter((e) => e.importance >= imp && (!sel || e.date === sel))
  const days = useMemo(() => { const g = {}; ev.forEach((e) => { (g[e.date] = g[e.date] || []).push(e) }); return g }, [ev])
  return (
    <>
      <div className="card" style={{ paddingBottom: 10 }}>
        <div className="row wrapflex between" style={{ gap: 6 }}>
          <div className="row" style={{ gap: 6 }}>
            {[[3, '★★★ High'], [2, '★★ Medium+'], [1, 'All']].map(([k, l]) => <button key={k} className={`tab ${imp === k ? 'on' : ''}`} onClick={() => setImp(k)}>{l}</button>)}
          </div>
          <span className="small muted">Times in your time zone{myZone ? ` (${myZone})` : ''}. Tap an event for what it means.</span>
        </div>
      </div>
      {err && <div className="card t-bad">⚠️ {err}</div>}
      {!d && !err && <div className="card empty">Loading economic events…</div>}
      {d?.notes?.length > 0 && <div className="card small t-warn">⚠️ Live feed: {d.notes.join(' · ')} — official dates are still shown.</div>}
      {d && ev.length === 0 && <div className="card empty">No {imp === 3 ? 'high-impact ' : imp === 2 ? 'medium or high impact ' : ''}events {sel ? `on ${dayName(sel)}` : 'this week'}.</div>}
      {Object.entries(days).map(([day, list]) => (
        <div key={day} className="card" style={{ padding: 0 }}>
          <div className={`cal-day ${day === todayIso() ? 'today' : ''}`}><b>{dayName(day, { weekday: 'long', day: 'numeric', month: 'short' })}</b><span className="small muted">{rel(day)} · {list.length}</span></div>
          {list.map((e, i) => <EconRow key={e.event + i} e={e} mk={mk} />)}
        </div>
      ))}
      {d && <div className="small muted src">Source: {d.source}. "Forecast" is the economists' consensus.</div>}
    </>
  )
}

function NextBig({ big, mk }) {
  if (!big?.length) return null
  return (
    <div className="card">
      <h3>⏳ Next big {mk === 'US' ? '🇺🇸 US' : '🇮🇳 India'} events</h3>
      <div className="big-list">
        {big.map((b) => (
          <div key={b.event + b.date} className="big-card">
            <div className="row between"><b className="small">{b.event}</b><CalBtn title={`${mk === 'US' ? '🇺🇸' : '🇮🇳'} ${b.event}`} date={b.date} at={b.at} details={`${b.what || ''} ${b.note || ''} via EquityLens`} url={b.source} /></div>
            <div className="big-cd">{countdown(b.at, b.date)}</div>
            <div className="small muted">{dayName(localDay(b.at) || b.date, { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' })} · {localTime(b.at)}{mk === 'US' && b.at ? ` (${etTime(b.at)})` : ''}</div>
            {b.why && <div className="small" style={{ marginTop: 4 }}>{b.why}</div>}
          </div>
        ))}
      </div>
    </div>
  )
}

// ======================================================================= page
export default function Calendar({ tab = 'results' }) {
  const mk = getMarket()
  const [start, setStart] = useState(defaultWeek())
  const [sel, setSel] = useState(null)
  const [big, setBig] = useState(null)
  const [perDay, setPerDay] = useState(null)
  const [ai, setAi] = useState(null), [aiBusy, setAiBusy] = useState(false), [aiErr, setAiErr] = useState(null)
  const econ = tab === 'economy'
  useEffect(() => { setSel(null); setAi(null) }, [start, mk])
  useEffect(() => { api(`/api/calendar/economy?market=${mk}&days=1`).then((x) => setBig(x.next_big)).catch(() => {}) }, [mk])
  useEffect(() => {
    setPerDay(null)
    api(`/api/calendar/${econ ? 'economy' : 'earnings'}?market=${mk}&start=${start}&days=7`).then((x) => {
      if (econ) { const c = {}; x.events.filter((e) => e.importance >= 2).forEach((e) => { c[e.date] = (c[e.date] || 0) + 1 }); setPerDay(c) } else setPerDay(x.per_day)
    }).catch(() => {})
  }, [mk, start, econ])
  const brief = async () => {
    setAiBusy(true); setAiErr(null)
    const syms = watchlist.all().map((w) => w.symbol).join(',')
    try { setAi(await api(`/api/ai/calendar?market=${mk}&start=${start}&days=7&symbols=${encodeURIComponent(syms)}`, { method: 'POST' })) } catch (e) { setAiErr(e.message) } finally { setAiBusy(false) }
  }
  const thisWeek = start === defaultWeek()
  const wk = `${dayName(start, { day: 'numeric', month: 'short' })} – ${dayName(addDays(start, 6), { day: 'numeric', month: 'short' })}`

  return (
    <div className="movers">
      <div className="card">
        <div className="row between wrapflex">
          <div><h3 style={{ margin: 0 }}>{mk === 'US' ? '🇺🇸' : '🇮🇳'} Calendar</h3>
            <div className="small muted">{mk === 'US' ? 'US earnings & US economy' : 'Indian results, corporate actions & Indian economy'}</div></div>
          <div className="row" style={{ gap: 6 }}>
            <button className="btn small" onClick={() => setStart(addDays(start, -7))}>‹</button>
            <button className={`btn small ${thisWeek ? 'primary' : ''}`} onClick={() => setStart(defaultWeek())}>{thisWeek ? ([0, 6].includes(new Date().getDay()) ? 'Coming week' : 'This week') : wk}</button>
            <button className="btn small" onClick={() => setStart(addDays(start, 7))}>›</button>
          </div>
        </div>
        <div className="row" style={{ gap: 6, marginTop: 12 }}>
          <button className={`tab grow ${!econ ? 'on' : ''}`} onClick={() => go('calendar/results')}>💼 {mk === 'US' ? 'Earnings' : 'Results & events'}</button>
          <button className={`tab grow ${econ ? 'on' : ''}`} onClick={() => go('calendar/economy')}>🌐 Economy</button>
        </div>
        <DayStrip start={start} perDay={perDay} sel={sel} onSel={setSel} />
        <div className="small muted">{wk}{sel ? ` · showing ${dayName(sel)} only (tap again for the whole week)` : ' · tap a day to filter'}</div>
      </div>

      <div className="movers-grid">
        <div className="movers-side">
          {isDesktop() && <NextBig big={big} mk={mk} />}
          <div className="card">
            <div className="row between"><h3 style={{ margin: 0 }}>✨ Brief me on this week</h3><button className="btn small primary" disabled={aiBusy} onClick={brief}>{ai ? '↻ Again' : 'Brief me'}</button></div>
            {aiBusy && <div className="small muted" style={{ marginTop: 8 }}>Reading the calendar…</div>}
            {aiErr && <div className="small t-bad" style={{ marginTop: 8 }}>⚠️ {aiErr}</div>}
            {ai ? <><Md text={ai.text} /><div className="small muted">{ai.model}</div></> : !aiBusy && <p className="small muted" style={{ marginBottom: 0 }}>AI briefing: which economic numbers matter, which results to watch (your watchlist first) and what a surprise would usually mean.</p>}
          </div>
        </div>
        <div className="movers-main">
          {!isDesktop() && econ && <NextBig big={big} mk={mk} />}
          {econ ? <Economy mk={mk} start={start} sel={sel} onBig={() => {}} /> : <Results mk={mk} start={start} sel={sel} />}
        </div>
      </div>
    </div>
  )
}
