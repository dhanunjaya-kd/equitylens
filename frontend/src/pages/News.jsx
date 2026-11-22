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
    <div className="card nw-item">
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
      {(it.tags.length > 0 || it.covered > 1) && (
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
    <div className={`card nw-card ${it.url ? 'link' : ''} ${noPic ? 'noimg' : ''}`} onClick={open}>
      {!noPic && <div style={{ position: 'relative' }}><Pic it={it} onFail={() => setNoPic(true)} />{badge}</div>}
      <div className="nw-card-body">
        {noPic && badge}
        <div className="nw-card-title">{it.title}</div>
        {noPic && it.summary && it.summary !== it.title && <div className="nw-card-sum">{it.summary}</div>}
        {it.order && <div className="small" style={{ marginTop: 4 }}>Order <b>{cr(it.order.crore)}</b>{it.order.pct_mcap !== null && it.order.pct_mcap !== undefined ? <> · <b>{it.order.pct_mcap < 0.1 ? '<0.1' : it.order.pct_mcap.toFixed(1)}%</b> of market value</> : null}</div>}
        <div className="row" style={{ gap: 6, flexWrap: 'wrap', marginTop: 'auto', paddingTop: 8, alignItems: 'center' }}>
          {it.tags.slice(0, 3).map((t) => <Tag key={t.symbol} t={t} />)}
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
        <div className="muted" style={{ marginTop: 8, lineHeight: 1.5 }}>Headlines and short summaries come from each publisher's own feed; open an item to read it on their site. Price moves are today's, from the app's daily prices. No buy / sell labels: nothing would back them.</div>
      </div>
    </>
  )
}

export default function News() {
  const mk = getMarket()
  const [d, setD] = useState(null), [err, setErr] = useState(null)
  const [cat, setCat] = useState('all'), [kind, setKind] = useState('all'), [mine, setMine] = useState(false), [q, setQ] = useState('')
  const [view, setView] = useState(() => { try { return localStorage.getItem('eql_news_view') || 'cards' } catch { return 'cards' } })
  const pickView = (v) => { setView(v); try { localStorage.setItem('eql_news_view', v) } catch { /* ignore */ } }
  const load = () => api(`/api/news?market=${mk}`).then(setD).catch((e) => setErr(e.message))
  useEffect(() => { setD(null); load(); const t = setInterval(load, 5 * 60 * 1000); return () => clearInterval(t) }, [mk]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!d?.running) return undefined
    const t = setTimeout(load, 8000)
    return () => clearTimeout(t)
  }, [d]) // eslint-disable-line react-hooks/exhaustive-deps
  const wl = useMemo(() => new Set(watchlist.all().map((i) => i.symbol)), [d])
  const labels = useMemo(() => Object.fromEntries((d?.cats || []).map((c) => [c.key, c.label])), [d])
  const items = useMemo(() => {
    if (!d) return []
    const ql = q.trim().toLowerCase()
    return d.items.map((i) => ({ ...i, catLabel: labels[i.category] || i.category }))
      .filter((i) => (cat === 'all' || i.category === cat) && (kind === 'all' || i.kind === kind)
        && (!mine || i.symbols.some((s) => wl.has(s)))
        && (!ql || `${i.title} ${i.summary} ${i.symbols.join(' ')}`.toLowerCase().includes(ql)))
  }, [d, cat, kind, mine, q, wl, labels])
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
            <div className="list-chips" style={{ flexWrap: 'nowrap', overflowX: 'auto' }}>
              <button className={`tab ${cat === 'all' ? 'on' : ''}`} onClick={() => setCat('all')}>All</button>
              {d.cats.filter((c) => c.n > 0).map((c) => <button key={c.key} className={`tab ${cat === c.key ? 'on' : ''}`} onClick={() => setCat(c.key)}>{c.label} <span className="muted">{c.n}</span></button>)}
            </div>
            <div className="row" style={{ gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
              <select className="input" value={kind} onChange={(e) => setKind(e.target.value)}>{KINDS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
              <button className={`hm-chip ${mine ? 'on' : ''}`} onClick={() => setMine(!mine)} title={wl.size ? '' : 'Add stocks to a watchlist first'}>⭐ My watchlists</button>
              <input className="input" placeholder="Search news" value={q} onChange={(e) => setQ(e.target.value)} style={{ minWidth: 160 }} />
              <div className="row" style={{ gap: 4 }}>{[['cards', '▦ Cards'], ['list', '☰ List']].map(([v, l]) => <button key={v} className={`hm-chip ${view === v ? 'on' : ''}`} onClick={() => pickView(v)}>{l}</button>)}</div>
            </div>
          </div>
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
