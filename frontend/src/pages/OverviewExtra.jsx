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
