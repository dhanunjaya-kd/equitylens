import { useEffect, useMemo, useState } from 'react'
import MoneyFlow from './MoneyFlow'
import { FnoBadge, FnoToggle, Logo, UniverseChips, useFno, useUniv } from '../components/ui'
import { api, getMarket, go, inUniv, num, ok, signed, watchlist } from '../util'

const fmtDate = (s) => (s ? new Date(s + 'T12:00:00').toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: '2-digit' }) : '—')
const cr = (v) => (ok(v) ? `${v < 0 ? '-' : ''}₹${num(Math.abs(v), Math.abs(v) < 10 ? 2 : 0)} Cr` : '—')
const usd = (v) => (ok(v) ? `${v < 0 ? '-' : ''}$${num(Math.abs(v), Math.abs(v) < 10 ? 2 : 1)}M` : '—')
const SideTag = ({ s }) => <span className={`tagc ${s === 'BUY' ? 'good' : s === 'SELL' ? 'bad' : 'warnc'}`} style={{ marginLeft: 0 }}>{s === 'BUY' ? '🟢 BUY' : s === 'SELL' ? '🔴 SELL' : s === 'PLEDGE' ? '🔒 PLEDGE' : s}</span>

// ---------------------------------------------------------------- small pieces reused on the stock page
export function SurveillanceBanner({ flags }) {
  if (!flags?.length) return null
  const high = flags.some((f) => f.severity === 'high')
  return (
    <div className={`card surv ${high ? 'surv-high' : ''}`}>
      <b>🚨 NSE surveillance</b>
      <div className="surv-tags">{flags.map((f) => <span key={f.measure} className={`tagc ${f.severity === 'high' ? 'bad' : 'warnc'}`}>{f.label}</span>)}</div>
      <div className="small muted">The exchange watches this stock more closely (higher margins, price bands or trade-for-trade). Usually a sign of excess speculation, weak finances or pledged shares.</div>
    </div>
  )
}

function DeliveryBars({ series }) {
  if (!series?.length) return null
  const max = 100
  return (
    <div className="dbars">
      {series.map((s) => (
        <div key={s.date} className="dbar" title={`${s.date}: ${s.dp}% delivery`}>
          <div className="dfill" style={{ height: `${((s.dp || 0) / max) * 100}%`, background: s.dp >= 60 ? 'var(--good)' : s.dp >= 40 ? 'var(--ok)' : 'var(--neutral)' }} />
          <span>{new Date(s.date + 'T12:00:00').getDate()}</span>
        </div>
      ))}
    </div>
  )
}

function InsiderTable({ rows, us, showCo }) {
  if (!rows?.length) return <div className="small muted">No insider trades in this period.</div>
  return (
    <div className="ins-list">
      {rows.slice(0, 80).map((r, i) => (
        <div key={i} className={`ins-row ${r.market ? '' : 'dim'}`} onClick={() => showCo && go(`stock/${r.symbol}/money`)}>
          {showCo && <Logo sym={r.symbol} name={r.name} size={28} />}
          <div className="grow" style={{ minWidth: 0 }}>
            {showCo && <div className="ellip"><b>{r.name}</b> <span className="small muted">{String(r.symbol).replace('US:', '')}</span>{r.fno && <FnoBadge />}</div>}
            <div className={showCo ? 'small ellip' : 'ellip'}><SideTag s={r.side} /> <b>{r.person || '—'}</b> <span className="muted">· {us ? r.role : r.category}{r.promoter ? ' 👑' : ''}</span></div>
            <div className="small muted">{fmtDate(r.date)} · {us ? r.type : (r.mode || r.type)}{ok(r.qty) ? ` · ${num(r.qty)} sh` : ''}{ok(r.price) ? ` @ ${us ? '$' : '₹'}${num(r.price, 2)}` : ''}{!us && ok(r.after_pct) ? ` · holds ${r.after_pct}% after` : ''}</div>
          </div>
          <div className={`ins-val ${r.side === 'BUY' ? 't-good' : r.side === 'SELL' ? 't-bad' : ''}`}>{us ? usd(r.value) : cr(r.value)}</div>
        </div>
      ))}
    </div>
  )
}

function Summary({ s, us }) {
  if (!s) return null
  return (
    <div className="grid3" style={{ marginBottom: 10 }}>
      <div className="tile"><div className="k">Open-market buys</div><div className="v t-good">{s.buys} · {us ? usd(s.buy_value) : cr(s.buy_value)}</div></div>
      <div className="tile"><div className="k">Open-market sells</div><div className="v t-bad">{s.sells} · {us ? usd(s.sell_value) : cr(s.sell_value)}</div></div>
      <div className="tile"><div className="k">Net</div><div className={`v ${s.net_value >= 0 ? 't-good' : 't-bad'}`}>{us ? usd(s.net_value) : cr(s.net_value)}</div></div>
    </div>
  )
}

// ---------------------------------------------------------------- stock page tab
export function StockMoney({ data }) {
  const d = data
  if (!d) return <div className="card empty">Loading insider trades, delivery and deals…</div>
  const us = d.symbol.startsWith('US:')
  const del = d.delivery
  const err = d.errors || {}
  return (
    <div className="flow-cols">
      {!us && (
        <div className="card">
          <h3>📦 Delivery (last {del?.series?.length || 0} sessions)</h3>
          {err.delivery && <div className="small t-warn">⚠️ {err.delivery}</div>}
          {del ? (
            <>
              <div className="grid3">
                <div className="tile"><div className="k">Delivery today</div><div className="v">{num(del.today.dp, 1)}%</div></div>
                <div className="tile"><div className="k">10-day average</div><div className="v">{ok(del.avg_dp) ? `${del.avg_dp}%` : '—'}</div></div>
                <div className="tile"><div className="k">Delivery qty vs avg</div><div className={`v ${del.dq_x >= 1.5 ? 't-good' : ''}`}>{ok(del.dq_x) ? `${del.dq_x}×` : '—'}</div></div>
              </div>
              <DeliveryBars series={del.series} />
              <div className="small muted">Delivery % = share of traded quantity actually taken into demat (not intraday). High delivery on up-days = real buying; on down-days = real selling.</div>
            </>
          ) : !err.delivery && <div className="small muted">No delivery data for this stock.</div>}
        </div>
      )}
      <div className="card">
        <h3>👔 Insider trades {us ? '(SEC Form 4, last 6 months)' : '(promoters, directors, KMP · last 90 days)'}</h3>
        {err.insiders && <div className="small t-warn">⚠️ {err.insiders}</div>}
        <Summary s={d.insiders?.summary} us={us} />
        {d.insiders?.summary?.cluster && <div className="small t-good" style={{ marginBottom: 8 }}>✅ Cluster buying: 2+ insiders bought in the last 30 days — historically one of the stronger insider signals.</div>}
        <InsiderTable rows={d.insiders?.rows} us={us} />
        <div className="small muted" style={{ marginTop: 6 }}>Faded rows are not open-market trades (awards, option exercises, tax withholding, gifts) and say little about the insider's view.</div>
      </div>
      {!us && (
        <div className="card">
          <h3>🤝 Bulk & block deals</h3>
          {err.deals && <div className="small t-warn">⚠️ {err.deals}</div>}
          {d.deals?.length ? d.deals.map((x, i) => (
            <div key={i} className="ins-row">
              <div className="grow"><div className="ellip"><SideTag s={x.side} /> <b>{x.client}</b></div>
                <div className="small muted">{fmtDate(x.date)} · {x.kind} deal · {num(x.qty)} sh @ ₹{num(x.price, 2)}</div></div>
              <div className={`ins-val ${x.side === 'BUY' ? 't-good' : 't-bad'}`}>{cr(x.value)}</div>
            </div>
          )) : <div className="small muted">No bulk or block deals seen yet. EquityLens keeps every day's deals from the first time you open Smart Money, so history builds up over time.</div>}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------- market page
const IN_TABS = [['flow', '💰 Money flow'], ['delivery', '📦 Delivery'], ['deals', '🤝 Bulk & block'], ['insiders', '👔 Insider trades'], ['surv', '🚨 Surveillance']]

function Delivery() {
  const [d, setD] = useState(null), [err, setErr] = useState(null), [list, setList] = useState('buying')
  const [fno] = useFno()
  const [univ] = useUniv()
  useEffect(() => { setD(null); setErr(null); api(`/api/flows/delivery?universe=${univ}&fno=${fno}`).then(setD).catch((e) => setErr(e.message)) }, [univ, fno])
  const L = [['buying', '🟢 Delivery buying', 'Price up, delivery ≥ 50% and delivery quantity ≥ 1.5× its 10-day average'],
    ['selling', '🔴 Delivery selling', 'Price down with the same heavy delivery — real holders exiting'],
    ['highest', '🏦 Highest delivery %', 'Biggest share of volume taken into demat today'],
    ['value', '💰 Delivery value', 'Most money actually taken into delivery (₹ Cr)']]
  const rows = d?.lists?.[list] || []
  return (
    <>
      <div className="card" style={{ paddingBottom: 8 }}>
        <div className="list-chips">{L.map(([k, l]) => <button key={k} className={`tab ${list === k ? 'on' : ''}`} onClick={() => setList(k)}>{l} {d && <span className="cnt">{d.lists[k].length}</span>}</button>)}</div>
        <div className="small muted" style={{ marginTop: 6 }}>{L.find((x) => x[0] === list)[2]}{d ? ` · session ${fmtDate(d.date)}` : ''}.</div>
      </div>
      {err && <div className="card t-bad">⚠️ {err}</div>}
      {!d && !err && <div className="card empty">Downloading NSE delivery files (first time ~15 s)…</div>}
      {d && (
        <div className="card" style={{ padding: 0 }}>
          {rows.length === 0 && <div className="empty">Nothing qualifies today.</div>}
          {rows.map((r, i) => (
            <div key={r.symbol} className="mv-row" onClick={() => go(`stock/${r.symbol}/money`)}>
              <div className="rank-num">{i + 1}</div>
              <Logo sym={r.symbol} name={r.name} size={30} />
              <div className="grow" style={{ minWidth: 0 }}>
                <div className="ellip"><b>{r.name}</b> <span className="small muted">{r.symbol}</span>{r.fno && <FnoBadge />}</div>
                <div className="small muted ellip">Delivery {num(r.dp, 1)}% (avg {ok(r.avg_dp) ? r.avg_dp + '%' : '—'}) · {ok(r.dq_x) ? `${r.dq_x}× usual qty` : ''} · {cr(r.deliv_value)} delivered</div>
              </div>
              <div className="cal-num"><b>₹{num(r.close, 2)}</b><div className={`small ${r.ret >= 0 ? 't-good' : 't-bad'}`}>{signed(r.ret, 2, '%')}</div></div>
            </div>
          ))}
        </div>
      )}
      {d && <div className="small muted src">Source: {d.source}. Published by NSE after market close (~6 PM).</div>}
    </>
  )
}

function Deals() {
  const [d, setD] = useState(null), [err, setErr] = useState(null), [side, setSide] = useState('')
  useEffect(() => { api('/api/flows/deals').then(setD).catch((e) => setErr(e.message)) }, [])
  const [fno] = useFno()
  const [univ] = useUniv()
  const rows = (d?.rows || []).filter((r) => (!side || r.side === side) && (!fno || r.fno) && inUniv(r, univ))
  return (
    <>
      <div className="card" style={{ paddingBottom: 10 }}>
        <div className="row wrapflex" style={{ gap: 6 }}>{[['', 'All'], ['BUY', '🟢 Buys'], ['SELL', '🔴 Sells']].map(([k, l]) => <button key={k} className={`tab ${side === k ? 'on' : ''}`} onClick={() => setSide(k)}>{l}</button>)}</div>
        <div className="small muted" style={{ marginTop: 6 }}>Bulk deal = one client trades more than 0.5% of a company's shares in a day. Block deal = a large trade done in the special block window.{d?.date ? ` Session ${fmtDate(d.date)}.` : ''}</div>
      </div>
      {err && <div className="card t-bad">⚠️ {err}</div>}
      {!d && !err && <div className="card empty">Loading deals…</div>}
      {d && (
        <div className="card" style={{ padding: 0 }}>
          {rows.length === 0 && <div className="empty">No deals.</div>}
          {rows.map((r, i) => (
            <div key={i} className="ins-row" onClick={() => go(`stock/${r.symbol}/money`)}>
              <Logo sym={r.symbol} name={r.name} size={28} />
              <div className="grow" style={{ minWidth: 0 }}>
                <div className="ellip"><b>{r.name}</b> <span className="small muted">{r.symbol} · {r.kind}</span>{r.fno && <FnoBadge />}</div>
                <div className="small ellip"><SideTag s={r.side} /> {r.client}</div>
                <div className="small muted">{num(r.qty)} sh @ ₹{num(r.price, 2)}</div>
              </div>
              <div className={`ins-val ${r.side === 'BUY' ? 't-good' : 't-bad'}`}>{cr(r.value)}</div>
            </div>
          ))}
        </div>
      )}
      {d && <div className="small muted src">Source: {d.source}.</div>}
    </>
  )
}

function Insiders({ mk }) {
  const [d, setD] = useState(null), [err, setErr] = useState(null)
  const [onlyMarket, setOnlyMarket] = useState(true), [onlyProm, setOnlyProm] = useState(false), [side, setSide] = useState('')
  useEffect(() => {
    setD(null); setErr(null)
    const syms = watchlist.all().map((w) => w.symbol).join(',')
    api(mk === 'US' ? `/api/flows/insiders?market=US&symbols=${encodeURIComponent(syms)}` : '/api/flows/insiders?market=IN&days=30').then(setD).catch((e) => setErr(e.message))
  }, [mk])
  const [fno] = useFno()
  const [univ] = useUniv()
  const rows = useMemo(() => (d?.rows || []).filter((r) => (!onlyMarket || r.market || r.side === 'PLEDGE') && (!onlyProm || r.promoter) && (!side || r.side === side) && (mk === 'US' || ((!fno || r.fno) && inUniv(r, univ)))), [d, onlyMarket, onlyProm, side, fno, univ])
  const byCo = useMemo(() => {
    const g = {}
    rows.filter((r) => r.side === 'BUY' && r.market).forEach((r) => { const k = r.symbol; g[k] = g[k] || { symbol: k, name: r.name, value: 0, people: new Set() }; g[k].value += r.value || 0; g[k].people.add(r.person) })
    return Object.values(g).filter((x) => x.people.size >= 2).sort((a, b) => b.value - a.value)
  }, [rows])
  return (
    <>
      <div className="card" style={{ paddingBottom: 10 }}>
        <div className="row wrapflex" style={{ gap: 6 }}>
          {[['', 'All'], ['BUY', '🟢 Buys'], ['SELL', '🔴 Sells'], ...(mk === 'IN' ? [['PLEDGE', '🔒 Pledges']] : [])].map(([k, l]) => <button key={k} className={`tab ${side === k ? 'on' : ''}`} onClick={() => setSide(k)}>{l}</button>)}
          <button className={`tab ${onlyMarket ? 'on' : ''}`} onClick={() => setOnlyMarket(!onlyMarket)}>🏪 Open-market only</button>
          {mk === 'IN' && <button className={`tab ${onlyProm ? 'on' : ''}`} onClick={() => setOnlyProm(!onlyProm)}>👑 Promoters only</button>}
        </div>
        <div className="small muted" style={{ marginTop: 6 }}>
          {mk === 'US' ? 'Form 4 filings for your watchlist and your 15 highest-scored US stocks (last 6 months). Insiders sell for many reasons; they usually buy for one.'
            : 'Every insider disclosure on NSE in the last 30 days. Promoters buying from the open market is one of the cleanest signals of confidence.'}
        </div>
      </div>
      {byCo.length > 0 && (
        <div className="card">
          <h3>✅ Cluster buying (2+ insiders)</h3>
          {byCo.map((c) => <span key={c.symbol} className="chip chip-logo" style={{ cursor: 'pointer' }} onClick={() => go(`stock/${c.symbol}/money`)}><Logo sym={c.symbol} name={c.name} size={18} />{c.name} · {c.people.size} insiders · {mk === 'US' ? usd(c.value) : cr(c.value)}</span>)}
        </div>
      )}
      {err && <div className="card t-bad">⚠️ {err}</div>}
      {!d && !err && <div className="card empty">Loading insider trades{mk === 'US' ? ' from SEC (first time can take a minute)' : ''}…</div>}
      {d && <div className="card" style={{ padding: 0 }}><InsiderTable rows={rows} us={mk === 'US'} showCo /></div>}
      {d && <div className="small muted src">Source: {d.source}.</div>}
    </>
  )
}

function Surveillance() {
  const [d, setD] = useState(null), [err, setErr] = useState(null)
  useEffect(() => { api('/api/flows/surveillance').then(setD).catch((e) => setErr(e.message)) }, [])
  const [fno] = useFno()
  const [univ] = useUniv()
  const rows = (d?.rows || []).filter((r) => inUniv(r, univ) && (!fno || r.fno))
  return (
    <>
      <div className="card" style={{ paddingBottom: 10 }}>
        <div className="small muted">Stocks under NSE surveillance: GSM / ASM / ESM stages, insolvency, defaults, high pledge, loss-making, BZ series… Being on this list is a reason for extra care, not automatically a sell.{d?.date ? ` File of ${fmtDate(d.date)}.` : ''}</div>
      </div>
      {err && <div className="card t-bad">⚠️ {err}</div>}
      {!d && !err && <div className="card empty">Loading NSE surveillance file…</div>}
      {d && (
        <div className="card" style={{ padding: 0 }}>
          {rows.length === 0 && <div className="empty">{univ === 'ALL' ? 'No stocks flagged.' : 'No stocks flagged in this list. Pick "All NSE" to see every flagged company.'}</div>}
          {rows.slice(0, 300).map((r) => (
            <div key={r.symbol} className="ins-row" onClick={() => go(`stock/${r.symbol}`)}>
              <Logo sym={r.symbol} name={r.name} size={28} />
              <div className="grow" style={{ minWidth: 0 }}>
                <div className="ellip"><b>{r.name}</b> <span className="small muted">{r.symbol}</span>{r.fno && <FnoBadge />}</div>
                <div className="surv-tags">{r.flags.map((f) => <span key={f.measure} className={`tagc ${f.severity === 'high' ? 'bad' : 'warnc'}`}>{f.label}</span>)}</div>
              </div>
            </div>
          ))}
        </div>
      )}
      {d && <div className="small muted src">Source: {d.source}.</div>}
    </>
  )
}

export default function SmartMoney({ tab }) {
  const mk = getMarket()
  const US_TABS = [['flow', '💰 Money flow'], ['insiders', '👔 Insider trades']]
  const t = mk === 'US' ? (tab === 'insiders' ? 'insiders' : 'flow') : (tab || 'flow')
  const tabs = mk === 'US' ? US_TABS : IN_TABS
  return (
    <div className="movers">
      <div className="card">
        <div className="row between" style={{ gap: 8 }}>
          <h3 style={{ margin: 0 }}>{mk === 'US' ? '🇺🇸' : '🇮🇳'} Smart Money</h3>
          <button className="btn small" onClick={() => go('fiidii')}>🏦 {mk === 'US' ? 'Big money in futures' : 'FII / DII'}</button>
        </div>
        <div className="small muted">{mk === 'US' ? 'Where money is flowing, and what company insiders are doing with their own shares (SEC Form 4).' : 'Where money is flowing and who is really buying: delivery, big-investor deals, insider trades and exchange red flags. Official NSE data.'}</div>
        <div className="list-chips" style={{ marginTop: 10 }}>{tabs.map(([k, l]) => <button key={k} className={`tab ${t === k ? 'on' : ''}`} onClick={() => go(`money/${k}`)}>{l}</button>)}</div>
        {mk === 'IN' && t !== 'flow' && <div className="row wrapflex" style={{ gap: 8, marginTop: 10 }}><UniverseChips /><FnoToggle /></div>}
      </div>
      {t === 'flow' && <MoneyFlow />}
      <div className="flow-main">
        {t === 'delivery' && <Delivery />}
        {t === 'deals' && <Deals />}
        {t === 'insiders' && <Insiders mk={mk} />}
        {t === 'surv' && <Surveillance />}
      </div>
    </div>
  )
}
