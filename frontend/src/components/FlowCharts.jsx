import { useState } from 'react'
import { signed } from '../util'
import { useWidth } from '../pages/Heatmap'

// ---------------------------------------------------------------- formatting
export const cr = (v) => (v === null || v === undefined ? '—' : `₹${v < 0 ? '−' : ''}${Math.abs(v).toLocaleString('en-IN', { maximumFractionDigits: 0 })} Cr`)
export const sgnCr = (v) => (v === null || v === undefined ? '—' : `${v > 0 ? '+' : v < 0 ? '−' : ''}₹${Math.abs(v).toLocaleString('en-IN', { maximumFractionDigits: 0 })} Cr`)
export const n0 = (v, loc = 'en-IN') => (v === null || v === undefined ? '—' : `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v).toLocaleString(loc, { maximumFractionDigits: 0 })}`)
export const us0 = (v) => n0(v, 'en-US')
export const int = (v) => Math.round(v).toLocaleString('en-US')
export const ord = (n) => { const m = n % 100; return `${n}${m >= 11 && m <= 13 ? 'th' : ({ 1: 'st', 2: 'nd', 3: 'rd' })[n % 10] || 'th'}` }
export const tone = (v) => (v === null || v === undefined || v === 0 ? undefined : v > 0 ? 'var(--good)' : 'var(--bad)')
export const dmy = (iso) => (iso ? new Date(`${iso}T12:00:00`).toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' }) : '—')
export const dm = (iso) => (iso ? new Date(`${iso}T12:00:00`).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' }) : '—')
export const mon = (ym) => (ym ? new Date(`${ym}-15T12:00:00`).toLocaleDateString('en-IN', { month: 'short', year: 'numeric' }) : '—')
const label = (k) => (k && k.length === 7 ? mon(k) : dmy(k))
export const C_FII = '#60a5fa', C_DII = '#a78bfa', C_IDX = '#fbbf24', C_CLIENT = '#22c55e', C_PRO = '#f97316'

export function Chips({ opts, value, onChange }) {
  return <div className="row" style={{ gap: 6, flexWrap: 'wrap' }}>{opts.map(([t, v]) => <button key={t} className={`hm-chip ${value === v ? 'on' : ''}`} onClick={() => onChange(v)}>{t}</button>)}</div>
}

function useTip(n, iw, padL) {
  const [tip, setTip] = useState(null)
  const onMove = (e) => {
    const r = e.currentTarget.getBoundingClientRect()
    const i = Math.floor(((e.clientX - r.left - padL) / iw) * n)
    if (i >= 0 && i < n) setTip({ i, x: e.clientX - r.left })
  }
  return [tip, setTip, onMove]
}

// ---------------------------------------------------------------- bars (around zero) + one line on its own scale
export function Chart({ rows, bars, line, height = 240, lineLabel, barFmt = (v) => v }) {
  const [ref, w] = useWidth()
  const pad = { l: 8, r: 8, t: 10, b: 22 }
  const W = Math.max(200, w), H = height
  const iw = W - pad.l - pad.r, ih = H - pad.t - pad.b
  const n = rows.length
  const [tip, setTip, onMove] = useTip(n, iw, pad.l)
  const maxAbs = Math.max(1, ...rows.flatMap((r) => bars.map((b) => Math.abs(r[b.key] ?? 0))))
  const lv = rows.map((r) => r[line?.key]).filter((v) => v !== null && v !== undefined)
  const lmin = Math.min(...lv), lmax = Math.max(...lv)
  const x = (i) => pad.l + (iw * (i + 0.5)) / Math.max(1, n)
  const y0 = pad.t + ih / 2
  const by = (v) => y0 - (v / maxAbs) * (ih / 2)
  const ly = (v) => pad.t + ih - ((v - lmin) / Math.max(1e-9, lmax - lmin)) * ih
  const slot = iw / Math.max(1, n)
  const bw = Math.min(28, Math.max(1.5, slot / (bars.length + 0.6)))
  const pts = line ? rows.map((r, i) => (r[line.key] === null || r[line.key] === undefined ? null : `${x(i).toFixed(1)},${ly(r[line.key]).toFixed(1)}`)).filter(Boolean).join(' ') : ''
  return (
    <div ref={ref} style={{ position: 'relative' }} onMouseLeave={() => setTip(null)}>
      {w > 0 && (
        <svg width={W} height={H} style={{ display: 'block' }} onMouseMove={onMove}>
          {bars.length > 0 && <line x1={pad.l} x2={W - pad.r} y1={y0} y2={y0} stroke="var(--line)" strokeDasharray="3 3" />}
          {rows.map((r, i) => bars.map((b, k) => {
            const v = r[b.key]
            if (v === null || v === undefined) return null
            const yy = by(v)
            return <rect key={`${i}${k}`} x={x(i) - (bars.length * bw) / 2 + k * bw} y={Math.min(yy, y0)} width={bw * 0.9} height={Math.max(1, Math.abs(y0 - yy))} fill={b.color} opacity={tip && tip.i !== i ? 0.55 : 0.95} />
          }))}
          {line && pts && <polyline points={pts} fill="none" stroke={line.color} strokeWidth="2" />}
          {n > 0 && <text x={pad.l} y={H - 6} fontSize="11" fill="var(--muted)">{label(rows[0].date)}</text>}
          {n > 1 && <text x={W - pad.r} y={H - 6} fontSize="11" fill="var(--muted)" textAnchor="end">{label(rows[n - 1].date)}</text>}
          {tip && <line x1={x(tip.i)} x2={x(tip.i)} y1={pad.t} y2={pad.t + ih} stroke="var(--muted)" strokeWidth="1" opacity=".5" />}
        </svg>
      )}
      {tip && rows[tip.i] && (
        <div className="fd-tip" style={{ left: Math.min(Math.max(0, tip.x + 10), W - 210) }}>
          <b>{label(rows[tip.i].date)}</b>
          {bars.map((b) => <div key={b.key}><span style={{ color: b.color }}>■</span> {b.label}: <b>{barFmt(rows[tip.i][b.key])}</b></div>)}
          {line && rows[tip.i][line.key] !== undefined && rows[tip.i][line.key] !== null && <div><span style={{ color: line.color }}>━</span> {lineLabel}: <b>{rows[tip.i][line.key].toLocaleString('en-IN', { maximumFractionDigits: 1 })}</b></div>}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------- several lines on one shared scale (with zero)
export function LinesChart({ rows, lines, height = 220, fmt = (v) => v, zero = true }) {
  const [ref, w] = useWidth()
  const pad = { l: 8, r: 8, t: 10, b: 22 }
  const W = Math.max(200, w), H = height
  const iw = W - pad.l - pad.r, ih = H - pad.t - pad.b
  const n = rows.length
  const [tip, setTip, onMove] = useTip(n, iw, pad.l)
  const vals = rows.flatMap((r) => lines.map((l) => r[l.key])).filter((v) => v !== null && v !== undefined)
  let lo = Math.min(...vals), hi = Math.max(...vals)
  if (zero) { lo = Math.min(lo, 0); hi = Math.max(hi, 0) }
  if (!(hi > lo)) { hi = lo + 1 }
  const x = (i) => pad.l + (iw * (i + 0.5)) / Math.max(1, n)
  const y = (v) => pad.t + ih - ((v - lo) / (hi - lo)) * ih
  return (
    <div ref={ref} style={{ position: 'relative' }} onMouseLeave={() => setTip(null)}>
      {w > 0 && n > 0 && (
        <svg width={W} height={H} style={{ display: 'block' }} onMouseMove={onMove}>
          {zero && <line x1={pad.l} x2={W - pad.r} y1={y(0)} y2={y(0)} stroke="var(--line)" strokeDasharray="3 3" />}
          {lines.map((l) => {
            const pts = rows.map((r, i) => (r[l.key] === null || r[l.key] === undefined ? null : `${x(i).toFixed(1)},${y(r[l.key]).toFixed(1)}`)).filter(Boolean).join(' ')
            return <polyline key={l.key} points={pts} fill="none" stroke={l.color} strokeWidth="2" />
          })}
          <text x={pad.l} y={H - 6} fontSize="11" fill="var(--muted)">{label(rows[0].date)}</text>
          {n > 1 && <text x={W - pad.r} y={H - 6} fontSize="11" fill="var(--muted)" textAnchor="end">{label(rows[n - 1].date)}</text>}
          {tip && <line x1={x(tip.i)} x2={x(tip.i)} y1={pad.t} y2={pad.t + ih} stroke="var(--muted)" strokeWidth="1" opacity=".5" />}
        </svg>
      )}
      {tip && rows[tip.i] && (
        <div className="fd-tip" style={{ left: Math.min(Math.max(0, tip.x + 10), W - 210) }}>
          <b>{label(rows[tip.i].date)}</b>
          {lines.map((l) => <div key={l.key}><span style={{ color: l.color }}>━</span> {l.label}: <b>{fmt(rows[tip.i][l.key])}</b></div>)}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------- tiny bars for a table row
export function Spark({ vals, w = 96, h = 26 }) {
  const v = vals.map((x) => x ?? 0)
  const m = Math.max(1, ...v.map(Math.abs))
  const bw = w / Math.max(1, v.length)
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" className="fd-spark" style={{ display: 'block' }}>
      <line x1="0" x2={w} y1={h / 2} y2={h / 2} stroke="var(--line)" />
      {v.map((x, i) => <rect key={i} x={i * bw + 0.5} width={Math.max(1, bw - 1)} y={x >= 0 ? h / 2 - (x / m) * (h / 2) : h / 2} height={Math.max(0.5, (Math.abs(x) / m) * (h / 2))} fill={x >= 0 ? 'var(--good)' : 'var(--bad)'} opacity=".85" />)}
    </svg>
  )
}

export function Legend({ items }) {
  return <div className="row small muted" style={{ gap: 14, flexWrap: 'wrap', marginTop: 6 }}>{items.map(([c, t, isLine]) => <span key={t}><span style={{ color: c }}>{isLine ? '━' : '■'}</span> {t}</span>)}</div>
}

// ---------------------------------------------------------------- tested record
const VERD = { better: ['var(--good)', 'clearly higher than usual'], worse: ['var(--bad)', 'clearly lower than usual'], same: ['var(--muted)', 'not clearly different from usual'] }
function RecordRow({ label: lb, r, base, horizon }) {
  if (!r) return null
  if (r.verdict === 'too_few') return <div className="fd-rec"><b>{lb}</b><span className="small" style={{ color: 'var(--warn)' }}>Only {r.n} case{r.n === 1 ? '' : 's'}: too few to judge (the rule needs 10).</span></div>
  const [c, t] = VERD[r.verdict]
  return (
    <div className="fd-rec">
      <b>{lb}</b>
      <span className="small">Index higher {horizon} later <b>{r.up_pct}%</b> of {r.n} times (likely {r.range[0]}–{r.range[1]}%, median {signed(r.median_pct, 2, '%')}) vs {base}% on every day → <b style={{ color: c }}>{t}</b></span>
    </div>
  )
}

export function Tested({ title, test, horizons, lowLabel, highLabel, need, needWhat, lag = '' }) {
  return (
    <div className="card">
      <h3 style={{ marginTop: 0 }}>Does it predict the index? <span className="small muted">· {title}</span></h3>
      <div className="small muted" style={{ marginBottom: 8 }}>A reading is extreme when it is in the bottom or top 10% of its own previous year (only earlier data). The count starts at the first close after the figures were public{lag}. Called higher or lower than usual only when the likely range (90%) of the hit rate is wholly above or below the every-day figure. Fixed before any result.</div>
      {!test && <div className="small" style={{ color: 'var(--warn)' }}>Not enough history yet{need ? `: needs ${need} more ${needWhat}` : ''}.</div>}
      {test && horizons.map(([h, hl]) => (
        <div key={h} style={{ marginBottom: 6 }}>
          <div className="small muted" style={{ marginTop: 6 }}>{hl}</div>
          <RecordRow label={lowLabel} r={test[h]?.low} base={test[h]?.base_up_pct} horizon={hl.toLowerCase()} />
          <RecordRow label={highLabel} r={test[h]?.high} base={test[h]?.base_up_pct} horizon={hl.toLowerCase()} />
        </div>
      ))}
    </div>
  )
}

export function Kpi({ k, v, s, c }) {
  return <div className="tile"><div className="k">{k}</div><div className="v" style={{ color: c, fontSize: 20 }}>{v}</div>{s && <div className="s">{s}</div>}</div>
}

export function Progress({ st, what }) {
  if (!st?.running) return null
  return (
    <div className="card small">
      Downloading {what}: {st.done.toLocaleString('en-IN')} of {st.total.toLocaleString('en-IN')} · one time only, in the background · this page fills in as it goes
      <div className="progress"><div style={{ width: `${st.total ? (st.done / st.total) * 100 : 0}%` }} /></div>
    </div>
  )
}

export function Unavailable({ children }) {
  return <div className="small" style={{ color: 'var(--warn)', padding: '6px 0' }}>{children}</div>
}
