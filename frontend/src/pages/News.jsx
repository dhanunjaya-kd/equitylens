import { useEffect, useMemo, useState } from 'react'
import { ago, api, getMarket, go, signed, watchlist } from '../util'
import { Logo } from '../components/ui'

const KIND = { filing: ['Company filing', '#22c55e'], official: ['Central bank', '#fbbf24'], news: ['News', '#60a5fa'] }
const KINDS = [['all', 'Everything'], ['filing', 'Company filings'], ['official', 'Central banks'], ['news', 'News']]
const secs = (iso) => new Date(iso).getTime() / 1000
const when = (iso) => {
  const d = new Date(iso)
  const today = new Date().toDateString() === d.toDateString()
  return today ? `Today ${d.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })}` : ago(secs(iso))
}
const cr = (v) => `₹${v.toLocaleString('en-IN', { maximumFractionDigits: v < 10 ? 2 : 0 })} Cr`
const pc = (v) => (v === null || v === undefined ? '' : signed(v, 2, '%'))
const TONE = { positive: 'var(--good)', negative: 'var(--bad)', inline: 'var(--muted)' }
const TONE_LABEL = [['all', 'All'], ['positive', 'Positive'], ['negative', 'Negative'], ['inline', 'In line with NIFTY'], ['none', 'Not measured']]
const hhmm = (s) => new Date(s * 1000).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })

const Ico = ({ d, size = 16 }) => (
  <svg viewBox="0 0 24 24" width={size} height={size} aria-hidden="true" style={{ display: 'block' }}>
    <g fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">{d}</g>
  </svg>
)
const I_SEARCH = <><circle cx="11" cy="11" r="7" /><path d="M20 20l-3.5-3.5" /></>
const I_CARDS = <><rect x="4" y="4" width="7" height="7" rx="1.5" /><rect x="13" y="4" width="7" height="7" rx="1.5" /><rect x="4" y="13" width="7" height="7" rx="1.5" /><rect x="13" y="13" width="7" height="7" rx="1.5" /></>
const I_LIST = <><path d="M9 6h11M9 12h11M9 18h11" /><circle cx="4.5" cy="6" r=".6" /><circle cx="4.5" cy="12" r=".6" /><circle cx="4.5" cy="18" r=".6" /></>
const I_STAR = <path d="M12 3.5l2.6 5.3 5.9.9-4.3 4.1 1 5.8L12 16.9l-5.2 2.7 1-5.8L3.5 9.7l5.9-.9z" />
const I_X = <path d="M6 6l12 12M18 6L6 18" />

// What backs the colour: the stock's real move since the item came out, against NIFTY 50 over the same minutes
function Reaction({ r }) {
  const sym = r.symbol.replace('US:', '')
  if (r.state !== 'ok') {
    const why = { waiting: 'not traded since this news', old: 'older than the 5-day price window', noprice: 'no price data' }[r.state] || ''
    return <span className="nw-ev muted" title={why}>{sym} · {why}</span>
  }
  const c = r.tone ? TONE[r.tone] : 'var(--muted)'
  const tip = `${sym} ${pc(r.stock)} from ${hhmm(r.since)} to ${hhmm(r.to)}; NIFTY 50 ${r.index === null ? 'n/a' : pc(r.index)} over the same minutes`
  return (
    <button className="nw-ev" style={{ borderColor: c }} title={tip} onClick={(e) => { e.stopPropagation(); go(`stock/${r.symbol}`) }}>
      <b>{sym}</b> <b style={{ color: c }}>{pc(r.stock)}</b> since news{r.index !== null && <span className="muted"> · NIFTY {pc(r.index)}</span>}
    </button>
  )
}

function CommodityLine({ g }) {
  const mv = g.move
  return (
    <>
      {mv && mv.change_pct !== null && mv.change_pct !== undefined && (
        <span className="nw-ev"><b>{mv.name}</b> <b style={{ color: mv.change_pct > 0 ? 'var(--good)' : mv.change_pct < 0 ? 'var(--bad)' : undefined }}>{pc(mv.change_pct)}</b> today</span>
      )}
      {g.india && (
        <span className="nw-ev" style={{ borderColor: TONE[g.india.impact] || 'var(--line)' }} title={g.india.why}>
          For India: <b style={{ color: TONE[g.india.impact] }}>{g.india.impact === 'neutral' ? `no clear effect (move under ${g.india.band}%)` : g.india.impact}</b>
        </span>
      )}
    </>
  )
}

function Evidence({ it, compact }) {
  if (it.react) {
    const rows = compact ? it.react.rows.slice(0, 2) : it.react.rows
    return <div className="nw-evs">{rows.map((r) => <Reaction key={r.symbol} r={r} />)}</div>
  }
  if (it.comm) {
    const st = it.comm.stocks.slice(0, compact ? 3 : 6)
    return (
      <div className="nw-evs">
        <CommodityLine g={it.comm} />
        {st.map((t) => <Tag key={t.symbol} t={t} />)}
      </div>
    )
  }
  return null
}

function Tag({ t }) {
  const c = t.d1 === null || t.d1 === undefined ? 'var(--muted)' : t.d1 > 0 ? 'var(--good)' : t.d1 < 0 ? 'var(--bad)' : 'var(--muted)'
  return (
    <button className="nw-tag" onClick={(e) => { e.stopPropagation(); go(`stock/${t.symbol}`) }} title={t.name || t.symbol}>
      {t.symbol.replace('US:', '')} {t.d1 !== null && t.d1 !== undefined && <b style={{ color: c }}>{signed(t.d1, 2, '%')}</b>}
    </button>
  )
}

function Item({ it }) {
  const [open, setOpen] = useState(false)
  const [k, kc] = KIND[it.kind]
  const first = it.sources[0]
  return (
    <div className={`card nw-item ${it.react?.tone ? `tone-${it.react.tone}` : ''}`}>
      <div className="nw-meta">
        <span style={{ color: kc, fontWeight: 600 }}>{k}</span>
        <span className="muted">· {it.catLabel} · {first.name}{it.covered > 1 && <button className="nw-more" onClick={() => setOpen(!open)}> +{it.covered - 1} more</button>}</span>
        <span className="muted" style={{ marginLeft: 'auto', whiteSpace: 'nowrap' }}>{when(it.time)}</span>
      </div>
      {it.url ? <a className="nw-title" href={it.url} target="_blank" rel="noreferrer">{it.title}</a> : <div className="nw-title">{it.title}</div>}
      {it.summary && it.summary !== it.title && <div className="nw-sum">{it.summary}</div>}
      {it.order && (
        <div className="small" style={{ marginTop: 6 }}>
          Order size <b>{cr(it.order.crore)}</b>{it.order.pct_mcap !== null && it.order.pct_mcap !== undefined ? <> · about <b>{it.order.pct_mcap < 0.1 ? '<0.1' : it.order.pct_mcap.toFixed(1)}%</b> of the company's market value</> : null}
        </div>
      )}
      <Evidence it={it} />
      {!it.react && (it.tags.length > 0 || it.covered > 1) && (
        <div className="row" style={{ gap: 6, flexWrap: 'wrap', marginTop: 8, alignItems: 'center' }}>
          {it.tags.map((t) => <Tag key={t.symbol} t={t} />)}
          {it.covered > 1 && <span className="small muted" style={{ marginLeft: 'auto' }}>covered by {it.covered} sources</span>}
        </div>
      )}
      {open && <div className="nw-srcs">{it.sources.map((s) => <a key={s.name} href={s.url} target="_blank" rel="noreferrer">{s.name} ↗</a>)}</div>}
    </div>
  )
}

// ---------------------------------------------------------------- pictures: only the publisher's own; none is drawn
function Pic({ it, big, onFail }) {
  const [bad, setBad] = useState(false)
  if (!it.image || bad) return null
  return (
    <div className={`nw-pic ${big ? 'big' : ''}`}>
      <img src={it.image} alt="" loading="lazy" referrerPolicy="no-referrer" onError={() => { setBad(true); if (onFail) onFail() }} />
      {it.image_by && <span className="nw-credit">Picture: {it.image_by}</span>}
    </div>
  )
}

function Card({ it }) {
  const [k, kc] = KIND[it.kind]
  const [noPic, setNoPic] = useState(!it.image)
  const open = () => it.url && window.open(it.url, '_blank', 'noopener')
  const badge = <span className={noPic ? 'nw-badge-inline' : 'nw-badge'}><b style={{ color: kc }}>{k}</b> · {it.catLabel}</span>
  return (
    <div className={`card nw-card ${it.url ? 'link' : ''} ${noPic ? 'noimg' : ''} ${it.react?.tone ? `tone-${it.react.tone}` : ''}`} onClick={open}>
      {!noPic && <div style={{ position: 'relative' }}><Pic it={it} onFail={() => setNoPic(true)} />{badge}</div>}
      <div className="nw-card-body">
        {noPic && badge}
        <div className="nw-card-title">{it.title}</div>
        {noPic && it.summary && it.summary !== it.title && <div className="nw-card-sum">{it.summary}</div>}
        {it.order && <div className="small" style={{ marginTop: 4 }}>Order <b>{cr(it.order.crore)}</b>{it.order.pct_mcap !== null && it.order.pct_mcap !== undefined ? <> · <b>{it.order.pct_mcap < 0.1 ? '<0.1' : it.order.pct_mcap.toFixed(1)}%</b> of market value</> : null}</div>}
        <div className="row" style={{ gap: 6, flexWrap: 'wrap', marginTop: 'auto', paddingTop: 8, alignItems: 'center' }}>
          {it.react || it.comm ? <Evidence it={it} compact /> : it.tags.slice(0, 3).map((t) => <Tag key={t.symbol} t={t} />)}
        </div>
        <div className="nw-card-foot"><span className="nw-ell">{it.sources[0].name}{it.covered > 1 ? ` +${it.covered - 1}` : ''}</span><span>{when(it.time)}</span></div>
      </div>
    </div>
  )
}

function Hero({ it }) {
  const [k, kc] = KIND[it.kind]
  return (
    <div className={`card nw-hero ${it.image ? '' : 'noimg'}`} onClick={() => it.url && window.open(it.url, '_blank', 'noopener')} style={{ cursor: it.url ? 'pointer' : 'default' }}>
      <div className="nw-hero-text">
        <div className="nw-meta"><b style={{ color: '#fbbf24' }}>TOP STORY</b><span className="muted">· <span style={{ color: kc }}>{k}</span> · {it.catLabel} · {it.sources.map((x) => x.name).join(', ')} · {when(it.time)}</span></div>
        <div className="nw-hero-title">{it.title}</div>
        {it.summary && it.summary !== it.title && <div className="nw-hero-sum">{it.summary}</div>}
        <div className="row" style={{ gap: 6, flexWrap: 'wrap', marginTop: 10 }}>
          {it.tags.map((t) => <Tag key={t.symbol} t={t} />)}
          {it.covered > 1 && <span className="small muted">covered by {it.covered} sources</span>}
        </div>
      </div>
      {it.image && <div className="nw-hero-pic"><Pic it={it} big /></div>}
    </div>
  )
}

function Side({ d }) {
  const [srcOpen, setSrcOpen] = useState(false)
  const ok = d.feeds.filter((f) => f.ok).length
  return (
    <>
      <div className="card">
        <h3 style={{ marginTop: 0 }}>Most in the news · 24 h</h3>
        {d.mentioned.length === 0 ? <div className="small muted">No company named in the last 24 hours yet.</div>
          : d.mentioned.map((m) => (
            <button key={m.symbol} className="nw-row" onClick={() => go(`stock/${m.symbol}`)}>
              <Logo sym={m.symbol} name={m.name} size={24} /><span className="grow" style={{ textAlign: 'left' }}><b>{m.symbol.replace('US:', '')}</b> <span className="small muted">{m.n} item{m.n > 1 ? 's' : ''}</span></span>
              {m.d1 !== null && m.d1 !== undefined && <b style={{ color: m.d1 > 0 ? 'var(--good)' : m.d1 < 0 ? 'var(--bad)' : undefined }}>{signed(m.d1, 2, '%')}</b>}
            </button>))}
      </div>
      <div className="card">
        <h3 style={{ marginTop: 0 }}>Moved 3%+ with news today</h3>
        {d.movers.length === 0 ? <div className="small muted">None so far.</div>
          : d.movers.map((m) => (
            <button key={m.symbol} className="nw-row" onClick={() => go(`stock/${m.symbol}`)}>
              <Logo sym={m.symbol} name={m.name} size={24} />
              <span className="grow" style={{ textAlign: 'left', minWidth: 0 }}><b>{m.symbol.replace('US:', '')}</b><div className="small muted nw-ell">{m.title}</div></span>
              <b style={{ color: m.d1 > 0 ? 'var(--good)' : 'var(--bad)' }}>{signed(m.d1, 2, '%')}</b>
            </button>))}
      </div>
      <div className="card small">
        <button className="nw-more" style={{ padding: 0 }} onClick={() => setSrcOpen(!srcOpen)}><b>Sources</b> · {ok} of {d.feeds.length} answering {srcOpen ? '▴' : '▾'}</button>
        {srcOpen && d.feeds.map((f) => (
          <div key={f.id} className="pmap-kv"><span>{f.ok ? '✅' : '⚠️'} {f.name}</span><span className="muted">{f.ok ? `${f.count} read` : f.error || 'no answer'}</span></div>))}
        <div className="muted" style={{ marginTop: 8, lineHeight: 1.5 }}>Headlines and short summaries come from each publisher's own feed; open an item to read it on their site. Price moves are today's, from the app's daily prices. Positive / negative in the F&O stocks view come from each stock's real move since the news, never from the headline.</div>
      </div>
    </>
  )
}

export default function News() {
  const mk = getMarket()
  const [d, setD] = useState(null), [err, setErr] = useState(null)
  const [cat, setCat] = useState('all'), [kind, setKind] = useState('all'), [mine, setMine] = useState(false), [q, setQ] = useState('')
  const [sub, setSub] = useState('all'), [qOpen, setQOpen] = useState(false)
  const [fnoV, setFnoV] = useState(null), [commV, setCommV] = useState(null)
  const pick = (c) => { setCat(c); setSub('all') }
  const [view, setView] = useState(() => { try { return localStorage.getItem('eql_news_view') || 'cards' } catch { return 'cards' } })
  const pickView = (v) => { setView(v); try { localStorage.setItem('eql_news_view', v) } catch { /* ignore */ } }
  const load = () => api(`/api/news?market=${mk}`).then(setD).catch((e) => setErr(e.message))
  useEffect(() => { setD(null); load(); const t = setInterval(load, 5 * 60 * 1000); return () => clearInterval(t) }, [mk]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!d?.running) return undefined
    const t = setTimeout(load, 8000)
    return () => clearTimeout(t)
  }, [d]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {                         // measured extras, asked for only while their chip is open
    if (cat !== 'v:fno' && cat !== 'v:commodities') return undefined
    const which = cat === 'v:fno' ? 'fno' : 'commodities'
    const set = which === 'fno' ? setFnoV : setCommV
    const get = () => api(`/api/news/view?market=${mk}&view=${which}`).then(set).catch(() => set({ error: 'Prices could not be read just now.' }))
    get()
    const t = setInterval(get, 2 * 60 * 1000)
    return () => clearInterval(t)
  }, [cat, mk])
  useEffect(() => { setCat('all'); setSub('all'); setFnoV(null); setCommV(null) }, [mk])
  const wl = useMemo(() => new Set(watchlist.all().map((i) => i.symbol)), [d])
  const groups = useMemo(() => Object.fromEntries((commV?.groups || []).map((g) => [g.key, g])), [commV])
  const labels = useMemo(() => Object.fromEntries((d?.cats || []).map((c) => [c.key, c.label])), [d])
  const items = useMemo(() => {
    if (!d) return []
    const ql = q.trim().toLowerCase()
    const toneOf = (i) => fnoV?.reactions?.[i.id]?.tone || 'none'
    const inCat = (i) => {
      if (cat === 'all') return true
      if (cat === 'v:commodities') return !!i.commodity && (sub === 'all' || i.commodity === sub)
      if (cat === 'v:fno') return (i.fno || []).length > 0 && (sub === 'all' || toneOf(i) === sub)
      return i.category === cat
    }
    return d.items.map((i) => ({
      ...i, catLabel: labels[i.category] || i.category,
      react: cat === 'v:fno' ? fnoV?.reactions?.[i.id] : undefined,
      comm: cat === 'v:commodities' && i.commodity ? groups[i.commodity] : undefined,
    }))
      .filter((i) => inCat(i) && (kind === 'all' || i.kind === kind)
        && (!mine || i.symbols.some((s) => wl.has(s)))
        && (!ql || `${i.title} ${i.summary} ${i.symbols.join(' ')}`.toLowerCase().includes(ql)))
  }, [d, cat, sub, kind, mine, q, wl, labels, fnoV, groups])
  const toneCount = useMemo(() => {
    const n = {}
    for (const i of d?.items || []) if ((i.fno || []).length) { const t = fnoV?.reactions?.[i.id]?.tone || 'none'; n[t] = (n[t] || 0) + 1; n.all = (n.all || 0) + 1 }
    return n
  }, [d, fnoV])
  const top = useMemo(() => (d?.top || []).map((i) => ({ ...i, catLabel: labels[i.category] || i.category })), [d, labels])
  return (
    <div className="nw">
      <div className="row" style={{ alignItems: 'baseline', gap: 10, flexWrap: 'wrap', marginBottom: 10 }}>
        <h2 style={{ margin: 0 }}>📰 {mk === 'US' ? 'US market news' : 'Market news'}</h2>
        <span className="small muted">{mk === 'US' ? 'Company filings, the Fed and US business news, plus major global events' : 'Company filings, RBI and Indian business news, plus major global events'}
          {d?.refreshed ? ` · updated ${ago(d.refreshed)}` : ''}{d?.running ? ' · checking for new items…' : ''}</span>
      </div>
      {err && <div className="card t-bad">⚠️ {err}</div>}
      {!d && !err && <div className="card empty">Loading…</div>}
      {d && (
        <>
          {d.breaking?.length > 0 && cat === 'all' && kind === 'all' && !mine && !q && (
            <div className="card nw-break">
              <div className="nw-meta"><b style={{ color: '#ef4444' }}>🔴 BREAKING</b><span className="muted">· serious market-wide events reported by two or more sources, central-bank announcements, and index moves of 2%+ today</span></div>
              {d.breaking.map((b) => (
                <a key={b.id} className="nw-break-row" href={b.url || undefined} target="_blank" rel="noreferrer">
                  <b>{b.title}</b><span className="small muted">{b.sources.map((x) => x.name).slice(0, 3).join(', ')} · {when(b.time)}</span>
                </a>))}
            </div>
          )}
          {top.length > 0 && cat === 'all' && kind === 'all' && !mine && !q && (
            <>
              <Hero it={top.find((i) => i.image) || top[0]} />
              {top.length > 1 && (
                <>
                  <h4 style={{ margin: '4px 0 8px' }}>Top stories · covered by the most sources</h4>
                  <div className="nw-cards nw-cards-top">{top.filter((i) => i !== (top.find((x) => x.image) || top[0])).map((i) => <Card key={i.id} it={i} />)}</div>
                </>
              )}
            </>
          )}
          <div className="nw-filters">
            <div className="list-chips nw-cats">
              <button className={`tab ${cat === 'all' ? 'on' : ''}`} onClick={() => pick('all')}>All</button>
              {d.cats.filter((c) => c.n > 0).map((c) => <button key={c.key} className={`tab ${cat === c.key ? 'on' : ''}`} onClick={() => pick(c.key)}>{c.label} <span className="muted">{c.n}</span></button>)}
              {(d.views || []).map((v) => <button key={v.key} className={`tab nw-view ${cat === `v:${v.key}` ? 'on' : ''}`} onClick={() => pick(`v:${v.key}`)}>{v.label} <span className="muted">{v.n}</span></button>)}
            </div>
            <div className="nw-ctrls">
              <select className="input" value={kind} onChange={(e) => setKind(e.target.value)}>{KINDS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
              <button className={`nw-ib ${mine ? 'on' : ''}`} onClick={() => setMine(!mine)} title={wl.size ? 'My watchlists only' : 'My watchlists only (add stocks to a watchlist first)'} aria-label="My watchlists only"><Ico d={I_STAR} /></button>
              <button className={`nw-ib ${q ? 'on' : ''}`} onClick={() => setQOpen(true)} title="Search news" aria-label="Search news"><Ico d={I_SEARCH} /></button>
              {(qOpen || q) && (
                <span className="nw-qwrap"><Ico d={I_SEARCH} size={14} /><input autoFocus className="nw-q" placeholder="Search news" value={q} onChange={(e) => setQ(e.target.value)} onBlur={() => !q && setQOpen(false)} onKeyDown={(e) => e.key === 'Escape' && (setQ(''), setQOpen(false))} />
                  <button className="nw-qx" onMouseDown={(e) => e.preventDefault()} onClick={() => { setQ(''); setQOpen(false) }} aria-label="Clear search"><Ico d={I_X} size={13} /></button></span>
              )}
              <span className="nw-seg">
                <button className={`nw-ib ${view === 'cards' ? 'on' : ''}`} onClick={() => pickView('cards')} title="Cards" aria-label="Cards"><Ico d={I_CARDS} /></button>
                <button className={`nw-ib ${view === 'list' ? 'on' : ''}`} onClick={() => pickView('list')} title="List" aria-label="List"><Ico d={I_LIST} /></button>
              </span>
            </div>
          </div>
          {cat === 'v:commodities' && (
            <div className="nw-sub">
              <button className={`hm-chip ${sub === 'all' ? 'on' : ''}`} onClick={() => setSub('all')}>All</button>
              {(d.commodities || []).filter((c) => c.n > 0).map((c) => {
                const mv = groups[c.key]?.move
                return (
                  <button key={c.key} className={`hm-chip ${sub === c.key ? 'on' : ''}`} onClick={() => setSub(c.key)}>
                    {c.label} <span className="muted">{c.n}</span>
                    {mv && mv.change_pct !== null && mv.change_pct !== undefined && <b style={{ marginLeft: 6, color: sub === c.key ? undefined : mv.change_pct > 0 ? 'var(--good)' : mv.change_pct < 0 ? 'var(--bad)' : undefined }}>{pc(mv.change_pct)}</b>}
                  </button>
                )
              })}
              <span className="small muted nw-sub-note">{commV ? 'Moves are each benchmark future today (Brent, gold, silver, copper, US natural gas).' : 'Reading today\'s commodity prices…'}</span>
            </div>
          )}
          {cat === 'v:fno' && (
            <div className="nw-sub">
              {TONE_LABEL.filter(([k]) => k === 'all' || toneCount[k]).map(([k, l]) => (
                <button key={k} className={`hm-chip ${sub === k ? 'on' : ''}`} onClick={() => setSub(k)}>
                  {k !== 'all' && k !== 'none' && <span className="nw-dot" style={{ background: TONE[k] }} />}{l} <span className="muted">{fnoV ? toneCount[k] || 0 : ''}</span>
                </button>))}
              <span className="small muted nw-sub-note">{!fnoV ? 'Measuring each stock\'s move since its news…' : fnoV.error || `Positive / negative = the stock moved ${fnoV.band} point or more ahead of / behind NIFTY 50 since the news (5-minute prices).`}</span>
            </div>
          )}
          <div className="nw-grid">
            <div>
              {items.length === 0
                ? <div className="card empty">{mine && !wl.size ? 'Your watchlists are empty: add stocks with ☆ to see their news here.' : d.count === 0 ? 'The first items arrive within a few minutes of starting the app.' : 'Nothing matches these filters.'}</div>
                : view === 'cards'
                  ? <div className="nw-cards">{items.slice(0, 150).map((i) => <Card key={i.id} it={i} />)}</div>
                  : items.slice(0, 150).map((i) => <Item key={i.id} it={i} />)}
              {items.length > 150 && <div className="small muted" style={{ textAlign: 'center' }}>Showing the newest 150 of {items.length}. Use the filters to narrow down.</div>}
            </div>
            <div className="nw-side"><Side d={d} /></div>
          </div>
        </>
      )}
    </div>
  )
}
