import { useState } from 'react'
import { Bar, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { cr, num, ok, pct, rs, signed } from '../util'
import { Md } from './AI'

const find = (t, ...names) => {
  if (!t?.rows) return null
  for (const n of names) for (const [k, v] of Object.entries(t.rows)) if (k.toLowerCase().startsWith(n.toLowerCase())) return v
  return null
}

export function KeyRatios({ d }) {
  const m = d.analysis.metrics, fin = m.is_financial
  const items = [
    ['Market cap', cr(m.market_cap)], ['Current price', rs(m.price, 2)], ['High / Low', `${num(m.high_52w)} / ${num(m.low_52w)}`],
    ['Stock P/E', num(m.pe, 1)], ['Book value', rs(m.book_value)], ['Dividend yield', pct(m.dividend_yield, 2)],
    [fin ? 'ROE (5y)' : 'ROCE', pct(fin ? m.roe_avg_5 : m.roce_latest)], ['ROE', pct(m.roe_latest)], ['Face value', rs(m.face_value, 2)],
  ]
  return (
    <div className="card">
      <h3>📋 Key ratios</h3>
      <div className="ratio-grid">
        {items.map(([k, v]) => <div key={k}><div className="small muted">{k}</div><div className="rv">{v}</div></div>)}
      </div>
    </div>
  )
}

export function LatestQuarter({ d }) {
  const q = d.company.tables.quarters
  if (!q?.columns?.length) return null
  const L = q.columns.length - 1
  const rows = [
    ['Sales', find(q, 'Sales', 'Revenue')], ['Operating profit', find(q, 'Operating Profit', 'Financing Profit')],
    ['Net profit', find(q, 'Net Profit')], ['EPS (₹)', find(q, 'EPS')],
  ].filter(([, v]) => v)
  const opm = find(q, 'OPM', 'Financing Margin')
  const ch = (v, i) => (v && ok(v[L]) && ok(v[i]) && v[i] !== 0 ? ((v[L] - v[i]) / Math.abs(v[i])) * 100 : null)
  const Delta = ({ x }) => (ok(x) && x !== null ? <span className={x >= 0 ? 'delta-up' : 'delta-dn'}>{x >= 0 ? '▲' : '▼'} {Math.abs(x).toFixed(1)}%</span> : <span className="muted">—</span>)
  const sales = find(q, 'Sales', 'Revenue'), np = find(q, 'Net Profit')
  const chart = q.columns.map((c, i) => ({ p: c.replace(/^(\w{3}) (\d{2})(\d{2})$/, "$1'$3"), Sales: sales?.[i], 'Net profit': np?.[i], OPM: opm?.[i] })).slice(-8)
  return (
    <div className="card">
      <div className="row between"><h3 style={{ margin: 0 }}>🗓️ Latest quarter · {q.columns[L]}</h3></div>
      <div className="tbl-wrap" style={{ marginTop: 10 }}>
        <table className="tbl">
          <thead><tr><th></th><th>{q.columns[L]}</th><th>YoY</th><th>QoQ</th></tr></thead>
          <tbody>
            {rows.map(([label, v]) => (
              <tr key={label}><td>{label}</td><td><b>{label.startsWith('EPS') ? num(v[L], 2) : num(v[L])}</b></td><td><Delta x={L >= 4 ? ch(v, L - 4) : null} /></td><td><Delta x={ch(v, L - 1)} /></td></tr>
            ))}
            {opm && <tr><td>Operating margin</td><td><b>{pct(opm[L], 0)}</b></td>
              <td>{L >= 4 && ok(opm[L - 4]) ? <span className={opm[L] >= opm[L - 4] ? 'delta-up' : 'delta-dn'}>{signed(opm[L] - opm[L - 4], 0, ' pts')}</span> : '—'}</td>
              <td>{ok(opm[L - 1]) ? <span className={opm[L] >= opm[L - 1] ? 'delta-up' : 'delta-dn'}>{signed(opm[L] - opm[L - 1], 0, ' pts')}</span> : '—'}</td></tr>}
          </tbody>
        </table>
      </div>
      <div style={{ height: 180, marginTop: 10 }}>
        <ResponsiveContainer>
          <ComposedChart data={chart} margin={{ top: 6, right: 0, left: -10, bottom: 0 }}>
            <CartesianGrid stroke="#223040" vertical={false} />
            <XAxis dataKey="p" stroke="#8b98a5" fontSize={10} tickLine={false} />
            <YAxis yAxisId="l" stroke="#8b98a5" fontSize={10} tickLine={false} tickFormatter={(v) => num(v)} />
            <YAxis yAxisId="r" orientation="right" stroke="#8b98a5" fontSize={10} tickLine={false} tickFormatter={(v) => `${v}%`} hide={!opm} />
            <Tooltip contentStyle={{ background: '#121a23', border: '1px solid #223040', borderRadius: 10, fontSize: 12 }} />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            <Bar yAxisId="l" dataKey="Sales" fill="#38bdf8" radius={[3, 3, 0, 0]} />
            <Bar yAxisId="l" dataKey="Net profit" fill="#2dd4bf" radius={[3, 3, 0, 0]} />
            {opm && <Line yAxisId="r" dataKey="OPM" stroke="#f59e0b" strokeWidth={2} dot={{ r: 2 }} />}
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <div className="small muted">YoY = vs same quarter last year (removes seasonal effects) · QoQ = vs previous quarter. Last 8 quarters, ₹ crore.</div>
    </div>
  )
}

export function KeyPoints({ d }) {
  const [open, setOpen] = useState(false)
  const md = d.company.key_points_md || d.company.key_points
  if (!md) return null
  return (
    <div className="card">
      <h3>🗝️ Key points from the company</h3>
      <div className={`kp ${open ? 'open' : ''}`}><Md text={md} /></div>
      <button className="btn small" style={{ marginTop: 8 }} onClick={() => setOpen(!open)}>{open ? 'Show less' : 'Read more'}</button>
      <div className="small muted" style={{ marginTop: 6 }}>Business segments, capacity, capex and targets as summarised on the source page.</div>
    </div>
  )
}

export function StoryTimeline({ d }) {
  const tl = (d.analysis.timeline || []).filter((t) => ok(t.sales) || ok(t.profit))
  if (tl.length < 3) return null
  const maxS = Math.max(...tl.map((t) => t.sales || 0)), maxP = Math.max(...tl.map((t) => Math.abs(t.profit || 0)))
  const col = { up: 'var(--good)', down: 'var(--bad)', warn: 'var(--warn)' }
  return (
    <div className="card">
      <h3>📖 The 10-year story</h3>
      <p className="small muted" style={{ marginTop: -4 }}>Each year's sales and profit, with the big changes called out automatically.</p>
      <div className="timeline">
        {tl.slice().reverse().map((t) => (
          <div key={t.year} className="tl-row">
            <div className="tl-year">{t.year.replace('Mar ', "FY")}</div>
            <div className={`tl-dot ${t.events.length ? 'on' : ''}`} style={{ background: t.events.length ? col[t.events[0].kind] : null }} />
            <div className="tl-body">
              <div className="tl-bars">
                <div className="bar s" style={{ width: `${Math.max(2, ((t.sales || 0) / maxS) * 100)}%` }} />
                <div className={`bar p ${(t.profit || 0) < 0 ? 'neg' : ''}`} style={{ width: `${Math.max(2, (Math.abs(t.profit || 0) / maxP) * 100)}%` }} />
              </div>
              <div className="small muted">Sales ₹{num(t.sales)} Cr · Profit ₹{num(t.profit)} Cr{ok(t.opm) ? ` · OPM ${t.opm}%` : ''}</div>
              {t.events.map((e, i) => <div key={i} className="small" style={{ color: col[e.kind], fontWeight: 600 }}>{e.kind === 'up' ? '▲' : e.kind === 'down' ? '▼' : '●'} {e.text}</div>)}
            </div>
          </div>
        ))}
      </div>
      <div className="small muted"><span style={{ color: '#38bdf8' }}>■</span> sales <span style={{ color: '#2dd4bf', marginLeft: 8 }}>■</span> profit (scaled to the best year)</div>
    </div>
  )
}

const PEER_METRICS = [
  ['ROCE %', 'ROCE', true], ['P/E', 'P/E (lower = cheaper)', false], ['Qtr Sales Var %', 'Latest qtr sales growth', true],
  ['Qtr Profit Var %', 'Latest qtr profit growth', true], ['Div Yld %', 'Dividend yield', true], ['Mar Cap Rs.Cr.', 'Size (market cap)', true],
]

export function PeerRank({ d }) {
  const peers = d.peers
  if (!peers?.rows?.length || peers.rows.length < 3) return null
  const me = peers.rows.find((r) => r.symbol === d.symbol) || peers.rows.find((r) => (r.name || '').toLowerCase().startsWith((d.company.name || '').toLowerCase().split(' ')[0]))
  if (!me) return null
  const items = PEER_METRICS.map(([key, label, higher]) => {
    const vals = peers.rows.map((r) => r[key]).filter((v) => ok(v) && v !== null && (key !== 'P/E' || v > 0))
    const v = me[key]
    if (!ok(v) || v === null || vals.length < 3 || (key === 'P/E' && v <= 0)) return null
    const better = vals.filter((x) => (higher ? x < v : x > v)).length
    const rank = vals.filter((x) => (higher ? x > v : x < v)).length + 1
    return { label, v, rank, n: vals.length, pct: Math.round((better / (vals.length - 1 || 1)) * 100), median: peers.median?.[key] }
  }).filter(Boolean)
  if (!items.length) return null
  return (
    <div className="card">
      <h3>🏁 Where it ranks among peers</h3>
      <p className="small muted" style={{ marginTop: -4 }}>Out of {peers.rows.length} listed peers. A longer bar means better than more peers.</p>
      {items.map((it) => (
        <div key={it.label} style={{ margin: '10px 0' }}>
          <div className="row between small"><span>{it.label}</span><span><b>{num(it.v, 1)}</b> <span className="muted">· #{it.rank} of {it.n}{ok(it.median) && it.median !== null ? ` · median ${num(it.median, 1)}` : ''}</span></span></div>
          <div className="track" style={{ height: 8, background: 'var(--card2)', borderRadius: 99, marginTop: 4, overflow: 'hidden' }}>
            <div style={{ width: `${Math.max(it.pct, 3)}%`, height: '100%', borderRadius: 99, background: it.pct >= 66 ? 'var(--good)' : it.pct >= 33 ? 'var(--warn)' : 'var(--bad)' }} />
          </div>
        </div>
      ))}
      <div className="small muted">Peers are as grouped by the source and may include companies in adjacent businesses.</div>
    </div>
  )
}
