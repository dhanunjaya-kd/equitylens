import { useEffect, useMemo, useState } from 'react'
import { api, getMarket, go, num, ok, signed } from '../util'

// Market dashboard: pulse, breadth, index pulse and sector rotation, each from saved prices (backend/app/dashboard.py).
const ZCOL = ['#dc2626', '#f97316', '#9ca3af', '#22c55e', '#15803d']
const tone = (v) => (!ok(v) ? 'var(--muted)' : v > 0 ? 'var(--good)' : v < 0 ? 'var(--bad)' : 'var(--muted)')

function Gauge({ value, cuts, colors, min = 0, max = 100, label, w = 260 }) {
  const cx = w / 2, cy = w / 2 + 4, r = w / 2 - 34
  const ang = (v) => Math.PI * (1 - (Math.max(min, Math.min(max, v)) - min) / (max - min))
  const pt = (v, rr = r) => [cx + rr * Math.cos(ang(v)), cy - rr * Math.sin(ang(v))]
  const arc = (a, b) => { const [x1, y1] = pt(a), [x2, y2] = pt(b); return `M${x1},${y1} A${r},${r} 0 0 1 ${x2},${y2}` }
  const edges = [min, ...cuts, max]
  const [nx, ny] = ok(value) ? pt(value, r - 18) : [cx, cy]
  return (
    <svg viewBox={`0 0 ${w} ${w / 2 + 24}`} className="dash-gauge" role="img" aria-label={label}>
      {edges.slice(0, -1).map((a, i) => <path key={i} d={arc(a + (i ? 0.6 : 0), edges[i + 1] - 0.6)} stroke={colors[i]} strokeWidth="16" fill="none" strokeLinecap="butt" opacity={ok(value) && value >= a && value < edges[i + 1] ? 1 : 0.35} />)}
      {edges.map((e, i) => { const [x, y] = pt(e, r + 16); return <text key={i} x={x} y={y + 4} textAnchor="middle" className="dash-tick">{e}</text> })}
      {ok(value) && <line x1={cx} y1={cy} x2={nx} y2={ny} stroke="var(--text)" strokeWidth="3" strokeLinecap="round" />}
      <circle cx={cx} cy={cy} r="7" fill="var(--card)" stroke="var(--text)" strokeWidth="3" />
    </svg>
  )
}

function Spark({ data, w = 160, h = 46, open, color }) {
  if (!data || data.length < 2) return <div className="small muted">No line</div>
  const lo = Math.min(...data, open ?? Infinity), hi = Math.max(...data, open ?? -Infinity)
  const X = (i) => (i / (data.length - 1)) * w
  const Y = (v) => 3 + (1 - (v - lo) / (hi - lo || 1)) * (h - 6)
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="dash-spark" preserveAspectRatio="none">
      {ok(open) && <line x1="0" x2={w} y1={Y(open)} y2={Y(open)} strokeDasharray="3 3" stroke="var(--muted)" strokeWidth="0.8" />}
      <polygon points={`0,${h} ${data.map((v, i) => `${X(i)},${Y(v)}`).join(' ')} ${w},${h}`} fill={color} opacity="0.12" />
      <polyline points={data.map((v, i) => `${X(i)},${Y(v)}`).join(' ')} fill="none" stroke={color} strokeWidth="1.6" />
      <circle cx={X(data.length - 1)} cy={Y(data[data.length - 1])} r="2.6" fill={color} />
    </svg>
  )
}

function Pulse({ p }) {
  if (!p || p.error) return <div className="card"><b>Market pulse</b><div className="small t-bad">{p?.error || 'Loading…'}</div></div>
  const cur = p.record?.zones?.[p.zone], any = p.record?.zones?._any
  const hist = p.history || []
  return (
    <div className="card dash-pulse">
      <div className="row between"><b>Market pulse</b><span className="small muted">{p.stocks} stocks · {p.session || '—'}</span></div>
      <Gauge value={p.score} cuts={[25, 45, 60, 75]} colors={ZCOL} label={`Market pulse ${p.score}`} />
      <div className="dash-zones small">{p.zones.map((z, i) => <span key={z.name} style={{ color: p.zone === z.name ? ZCOL[i] : undefined, fontWeight: p.zone === z.name ? 800 : 400 }}>{z.name}</span>)}</div>
      <div className="row" style={{ alignItems: 'baseline', gap: 8 }}><span className="dash-big">{ok(p.score) ? num(p.score, 0) : '—'}</span><span className="muted">of 100</span></div>
      <div className="dash-zone">{p.zone || 'Not enough data'}</div>
      <div style={{ marginTop: 8 }}>
        {p.weights.map((w) => {
          const v = p.parts[w.key]
          return (
            <div key={w.key} className="dash-part">
              <span>{w.label}</span>
              <div className="dash-bar"><i style={{ width: `${v ?? 0}%`, background: v >= 60 ? 'var(--good)' : v <= 40 ? 'var(--bad)' : '#9ca3af' }} /><em style={{ left: '50%' }} /></div>
              <b>{ok(v) ? num(v, 0) : '—'}</b><span className="muted">{Math.round(w.weight * 100)}%</span>
            </div>
          )
        })}
      </div>
      {cur?.n ? (
        <div className="small pat-rec" style={{ marginTop: 8 }}>
          Past days in <b>{p.zone}</b> ({p.record.from} to {p.record.to}): {p.record.bench} 20 sessions later rose {num(cur.up_r20, 0)}% of the time, median {signed(cur.median_r20, 1, '%')} · {num(cur.n, 0)} days. Any day: {num(any.up_r20, 0)}%, {signed(any.median_r20, 1, '%')}.
          {cur.n < 30 ? ' Few days: treat with care.' : ''}
        </div>
      ) : <div className="small muted" style={{ marginTop: 8 }}>The record of past days builds with the next price update.</div>}
      {hist.length > 10 && <div style={{ marginTop: 6 }}><div className="small muted">Last {hist.length} sessions</div><Spark data={hist.map((x) => x[1])} w={320} h={40} color="var(--accent)" /></div>}
      <div className="small muted" style={{ marginTop: 6 }}>Describes today from the stocks in the app's price list; it is not a forecast. Past record uses today's list of stocks (survivors only).</div>
    </div>
  )
}

function Breadth({ b }) {
  if (!b || b.error) return <div className="card"><b>Breadth</b><div className="small t-bad">{b?.error || 'Loading…'}</div></div>
  const max = Math.max(1, ...b.dist.map((x) => x.n))
  return (
    <div className="card dash-breadth">
      <div className="row between"><b>Breadth</b><span className="small muted">{b.day} · {num(b.total, 0)} stocks</span></div>
      <Gauge value={b.adv_share} cuts={[30, 45, 55, 70]} colors={ZCOL} label={`${b.adv_share}% of stocks rose`} />
      <div className="row between" style={{ marginTop: -6 }}>
        <div><div className="dash-big2 t-bad">{num(b.dec, 0)} <small>down ▼</small></div><div className="small muted">{num(b.dn5, 0)} down 5%+</div></div>
        <div style={{ textAlign: 'center' }} className="small muted">{num(b.unch, 0)} flat</div>
        <div style={{ textAlign: 'right' }}><div className="dash-big2 t-good">{num(b.adv, 0)} <small>up ▲</small></div><div className="small muted">{num(b.up5, 0)} up 5%+</div></div>
      </div>
      <div className="dash-net" style={{ color: tone(b.net) }}>{signed(b.net, 0)} <span>net advances</span></div>
      <div className="small" style={{ color: tone(b.net) }}>{b.adv > b.dec ? '▲ Advancers lead' : b.adv < b.dec ? '▼ Decliners lead' : 'Even'} · {num(b.adv_share, 0)}% of stocks that moved went up</div>
      <div className="dash-dist">{b.dist.map((x, i) => <div key={x.label} title={`${x.label}: ${x.n}`}><i style={{ height: `${(x.n / max) * 100}%`, background: i < 3 ? 'var(--bad)' : i === 3 ? '#9ca3af' : 'var(--good)' }} /><span>{x.label.replace(' or more', '').replace('%', '')}</span></div>)}</div>
      <div className="small muted">{b.source}</div>
    </div>
  )
}

function IndexPulse({ ix }) {
  if (!ix || ix.error) return <div className="card"><b>Index pulse</b><div className="small t-bad">{ix?.error || 'Loading…'}</div></div>
  return (
    <div className="card">
      <div className="row between"><b>Index pulse</b><span className="small muted">{ix.source}</span></div>
      <div className="dash-ix">
        {ix.items.map((i) => {
          const up = (i.change_pct ?? 0) >= 0, vix = i.kind === 'vix'
          const c = (vix ? !up : up) ? 'var(--good)' : 'var(--bad)'
          return (
            <div key={i.symbol} className="dash-ixc">
              <div className="row between"><span className="small muted">{i.name}</span>{i.mood && <span className="small muted">{i.mood.label}</span>}</div>
              {i.price == null ? <div className="small muted">Not available ({String(i.error || '').slice(0, 60)})</div> : (
                <>
                  <div className="dash-ixv">{num(i.price, 2)}</div>
                  <div className="small" style={{ color: c }}>{up ? '▲' : '▼'} {signed(i.change_pct, 2, '%')} · {signed(i.change, 2)} pts</div>
                  <Spark data={i.spark} open={i.prev_close} color={c} />
                  <div className="small muted">{ok(i.high) ? `H ${num(i.high, 0)}` : ''} {ok(i.low) ? `· L ${num(i.low, 0)}` : ''} {ok(i.prev_close) ? `· prev ${num(i.prev_close, 0)}` : ''}</div>
                </>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

const QC = { leading: '#16a34a', weakening: '#d97706', lagging: '#dc2626', improving: '#2563eb' }
function Rotation({ mk }) {
  const [frame, setFrame] = useState('daily')
  const [d, setD] = useState(null), [err, setErr] = useState(null)
  const [hov, setHov] = useState(null)
  useEffect(() => { setD(null); api(`/api/dashboard/rotation?market=${mk}&frame=${frame}`).then(setD).catch((e) => setErr(e.message)) }, [mk, frame])
  const g = useMemo(() => {
    if (!d?.sectors?.length) return null
    const xs = d.sectors.flatMap((s) => s.tail.map((p) => p[1])), ys = d.sectors.flatMap((s) => s.tail.map((p) => p[2]))
    const rx = Math.max(1.5, ...xs.map((x) => Math.abs(x - 100))) * 1.15, ry = Math.max(1.5, ...ys.map((y) => Math.abs(y - 100))) * 1.15
    return { rx, ry }
  }, [d])
  const W = 640, H = 420, P = 30
  const X = (v) => P + ((v - (100 - g.rx)) / (2 * g.rx)) * (W - 2 * P)
  const Y = (v) => P + (1 - (v - (100 - g.ry)) / (2 * g.ry)) * (H - 2 * P)
  return (
    <div className="card">
      <div className="row between wrapflex" style={{ gap: 8 }}>
        <b>Sector rotation <span className="small muted">vs {d?.benchmark || '…'}</span></b>
        <div className="seg">{[['daily', 'Daily'], ['weekly', 'Weekly']].map(([k, l]) => <button key={k} className={frame === k ? 'on' : ''} onClick={() => setFrame(k)}>{l}</button>)}</div>
      </div>
      {err && <div className="small t-bad">{err}</div>}
      {d?.headline && <h3 style={{ margin: '8px 0 2px' }}>{d.headline}</h3>}
      {d?.entered_leading?.length > 0 && <div className="small muted">{d.entered_leading.join(' and ')} joined the leaders in the last {d.params.tail} {frame === 'weekly' ? 'weeks' : 'sessions'}.</div>}
      {!d && !err && <div className="small muted">Loading sector candles…</div>}
      {g && (
        <svg viewBox={`0 0 ${W} ${H}`} className="dash-rrg" role="img" aria-label="Sector rotation chart">
          <rect x={X(100)} y={P} width={W - P - X(100)} height={Y(100) - P} fill={QC.leading} opacity="0.07" />
          <rect x={X(100)} y={Y(100)} width={W - P - X(100)} height={H - P - Y(100)} fill={QC.weakening} opacity="0.07" />
          <rect x={P} y={Y(100)} width={X(100) - P} height={H - P - Y(100)} fill={QC.lagging} opacity="0.07" />
          <rect x={P} y={P} width={X(100) - P} height={Y(100) - P} fill={QC.improving} opacity="0.07" />
          <line x1={X(100)} x2={X(100)} y1={P} y2={H - P} stroke="var(--line)" /><line x1={P} x2={W - P} y1={Y(100)} y2={Y(100)} stroke="var(--line)" />
          <text x={W - P - 4} y={P + 14} textAnchor="end" className="dash-q" fill={QC.leading}>Leading</text>
          <text x={W - P - 4} y={H - P - 6} textAnchor="end" className="dash-q" fill={QC.weakening}>Weakening</text>
          <text x={P + 4} y={H - P - 6} className="dash-q" fill={QC.lagging}>Lagging</text>
          <text x={P + 4} y={P + 14} className="dash-q" fill={QC.improving}>Improving</text>
          <text x={W / 2} y={H - 6} textAnchor="middle" className="dash-tick">RS-Ratio (strength vs {d.benchmark}) →</text>
          <text x={10} y={H / 2} transform={`rotate(-90 10 ${H / 2})`} textAnchor="middle" className="dash-tick">RS-Momentum →</text>
          {d.sectors.map((s) => {
            const c = QC[s.quadrant], last = s.tail[s.tail.length - 1], dim = hov && hov !== s.symbol
            return (
              <g key={s.symbol} opacity={dim ? 0.25 : 1} onMouseEnter={() => setHov(s.symbol)} onMouseLeave={() => setHov(null)} onClick={() => setHov(hov === s.symbol ? null : s.symbol)} style={{ cursor: 'pointer' }}>
                <polyline points={s.tail.map((p) => `${X(p[1])},${Y(p[2])}`).join(' ')} fill="none" stroke={c} strokeWidth="1.8" />
                {s.tail.slice(0, -1).map((p, i) => <circle key={i} cx={X(p[1])} cy={Y(p[2])} r="2" fill={c} opacity={0.4 + (0.6 * i) / s.tail.length} />)}
                <circle cx={X(last[1])} cy={Y(last[2])} r="5" fill={c} stroke="var(--card)" strokeWidth="1.5" />
                <text x={X(last[1]) + 8} y={Y(last[2]) + 4} className="dash-lab" fill={c}>{s.name}</text>
              </g>
            )
          })}
        </svg>
      )}
      {d?.sectors?.length > 0 && (
        <div className="tbl-wrap"><table className="tbl">
          <thead><tr><th style={{ textAlign: 'left' }}>Sector</th><th>Quadrant</th><th>RS-Ratio</th><th>RS-Mom</th><th>1D</th><th>1W</th></tr></thead>
          <tbody>{[...d.sectors].sort((a, b) => b.rs_ratio + b.rs_mom - (a.rs_ratio + a.rs_mom)).map((s) => (
            <tr key={s.symbol} onMouseEnter={() => setHov(s.symbol)} onMouseLeave={() => setHov(null)}><td style={{ textAlign: 'left' }}>{s.name}</td><td style={{ color: QC[s.quadrant], fontWeight: 700 }}>{s.quadrant}</td>
              <td>{num(s.rs_ratio, 1)}</td><td>{num(s.rs_mom, 1)} {s.speed > 0 ? '↑' : '↓'}</td><td style={{ color: tone(s.chg_1d) }}>{signed(s.chg_1d, 2, '%')}</td><td style={{ color: tone(s.chg_1w) }}>{signed(s.chg_1w, 2, '%')}</td></tr>))}
          </tbody></table></div>
      )}
      {d && <div className="small muted" style={{ marginTop: 6 }}>RS = sector ÷ {d.benchmark}. RS-Ratio = 100 × RS ÷ its {d.params.n}-{frame === 'weekly' ? 'week' : 'day'} average; RS-Momentum = 100 × RS-Ratio ÷ RS-Ratio {d.params.m} {frame === 'weekly' ? 'weeks' : 'sessions'} earlier. Tails show the last {d.params.tail} {frame === 'weekly' ? 'weeks' : 'sessions'}. A plain method in the spirit of relative rotation graphs. {d.source}.{d.errors?.length ? ` Not shown: ${d.errors.join('; ')}.` : ''}</div>}
    </div>
  )
}

export default function Dashboard() {
  const mk = getMarket()
  const [d, setD] = useState(null)
  const load = () => api(`/api/dashboard?market=${mk}`).then(setD).catch(() => {})
  useEffect(() => { setD(null); load(); const t = setInterval(() => { if (!document.hidden) load() }, 120000); return () => clearInterval(t) }, [mk]) // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className="dashboard">
      <div className="card"><div className="row between wrapflex"><h2 style={{ margin: 0 }}>📊 Market dashboard</h2><span className="small muted">{mk === 'US' ? '🇺🇸 US market' : '🇮🇳 Indian market'} · from saved prices · refreshes every 2 minutes</span></div></div>
      <div className="dash-grid">
        <Pulse p={d?.pulse} />
        <IndexPulse ix={d?.indices} />
      </div>
      <div className="dash-grid">
        <Breadth b={d?.breadth} />
        <Rotation mk={mk} />
      </div>
      <div className="small muted" style={{ textAlign: 'center', margin: 8 }}><button className="btn small" onClick={() => go('patterns')}>Chart patterns →</button> <button className="btn small" onClick={() => go('scanners')}>Scanners →</button></div>
    </div>
  )
}
