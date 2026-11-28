import { useEffect, useMemo, useState } from 'react'
import { FnoBadge, Logo, UniverseChips, UsUniverseChips, useFno, useUniv, useUsUniv } from '../components/ui'
import { api, getMarket, go, num, ok, signed, ticker } from '../util'

// Chart patterns, gaps and candlesticks found on each stock's real candles (backend/app/patterns.py).
// Every drawing below uses the actual swing points the rules were checked on.

const STATUS = { forming: ['Forming', ''], breakout: ['', ''], failed: ['Back inside', 'bad'] }

function MiniChart({ p, w = 300, h = 130 }) {
  const { bars, pivots, lines } = p.draw
  const n = bars.length
  const ys = bars.flatMap((b) => [b[1], b[2]]).concat([p.level, p.target, p.stop])
  const lo = Math.min(...ys), hi = Math.max(...ys)
  const padR = 52
  const X = (i) => 4 + (i / Math.max(1, n - 1)) * (w - padR - 8)
  const Y = (v) => 6 + (1 - (v - lo) / (hi - lo || 1)) * (h - 12)
  const cw = Math.max(1, Math.min(6, ((w - padR) / n) * 0.6))
  const lvl = (v, cls, label) => (
    <g className={cls}>
      <line x1={X(Math.max(0, pivots[pivots.length - 1][0]))} x2={w - padR} y1={Y(v)} y2={Y(v)} strokeDasharray="4 3" />
      <rect x={w - padR + 2} y={Y(v) - 8} width={padR - 4} height={16} rx="4" />
      <text x={w - padR / 2} y={Y(v) + 4} textAnchor="middle">{label}</text>
    </g>
  )
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="pat-chart" role="img" aria-label={`${p.name} drawn on the swing points`}>
      {bars.map((b, i) => {
        const up = b[3] >= b[0]
        return (
          <g key={i} className={up ? 'cu' : 'cd'}>
            <line x1={X(i)} x2={X(i)} y1={Y(b[1])} y2={Y(b[2])} />
            <rect x={X(i) - cw / 2} width={cw} y={Y(Math.max(b[0], b[3]))} height={Math.max(1, Math.abs(Y(b[0]) - Y(b[3])))} />
          </g>
        )
      })}
      {lines.map((l, i) => <line key={i} className="pat-line" x1={X(l[0])} y1={Y(l[1])} x2={X(l[2])} y2={Y(l[3])} />)}
      <polyline className="pat-zig" points={pivots.map((q) => `${X(q[0])},${Y(q[1])}`).join(' ')} />
      {pivots.map((q, i) => <circle key={i} className="pat-piv" cx={X(q[0])} cy={Y(q[1])} r="2.6" />)}
      {lvl(p.target, 'pl-t', num(p.target, p.target < 100 ? 2 : 0))}
      {lvl(p.level, 'pl-b', num(p.level, p.level < 100 ? 2 : 0))}
      {lvl(p.stop, 'pl-s', num(p.stop, p.stop < 100 ? 2 : 0))}
    </svg>
  )
}

function CandleStrip({ bars, w = 150, h = 60 }) {
  const lo = Math.min(...bars.map((b) => b[2])), hi = Math.max(...bars.map((b) => b[1]))
  const n = bars.length
  const X = (i) => 6 + (i / Math.max(1, n - 1)) * (w - 12)
  const Y = (v) => 4 + (1 - (v - lo) / (hi - lo || 1)) * (h - 8)
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="pat-chart small-strip">
      {bars.map((b, i) => (
        <g key={i} className={`${b[3] >= b[0] ? 'cu' : 'cd'} ${i >= n - 3 ? '' : 'dim'}`}>
          <line x1={X(i)} x2={X(i)} y1={Y(b[1])} y2={Y(b[2])} />
          <rect x={X(i) - 3} width={6} y={Y(Math.max(b[0], b[3]))} height={Math.max(1, Math.abs(Y(b[0]) - Y(b[3])))} />
        </g>
      ))}
    </svg>
  )
}

const pct = (x) => (x == null ? '—' : `${num(x, 0)}%`)

function RecordLine({ rec, p, base }) {
  const r = rec?.patterns?.[`${p.tf}:${p.type}:${p.dir}`]
  if (!r || !r.n) return <div className="small muted">Tested record: no finished past breakouts of this kind yet.</div>
  return (
    <div className="small pat-rec" title={`Every past ${p.dir === 'up' ? 'upside' : 'downside'} breakout of a ${p.name.toLowerCase()} (${p.tf === 'W' ? 'weekly' : 'daily'}) in this list's ${rec.from?.slice(0, 4)}–${rec.to?.slice(0, 4)} history, followed for ${p.tf === 'W' ? 26 : 60} ${p.tf === 'W' ? 'weeks' : 'sessions'}.`}>
      Past breakouts like this: <b className="t-good">target first {pct(r.target_first)}</b> · <b className="t-bad">stop first {pct(r.stop_first)}</b>
      {r.neither ? ` · neither ${pct(r.neither)}` : ''} · {num(r.n, 0)} cases{r.n < 30 ? ' (few: treat with care)' : ''}
      {ok(r.median_r20) && <> · median 20 bars later {signed(r.median_r20, 1, '%')}{base?.median_r20 != null ? ` (any day ${signed(p.dir === 'up' ? base.median_r20 : -base.median_r20, 1, '%')})` : ''}</>}
    </div>
  )
}

function PatternCard({ r, p, d, open, onLearn }) {
  const mk = getMarket()
  const st = p.status === 'breakout' ? (p.confirmed ? ['Confirmed', 'good'] : ['Marginal', 'warn']) : STATUS[p.status]
  const tfL = p.tf === 'W' ? '1W' : '1D'
  const cndl = p.tf === 'W' ? 'weekly candle' : 'daily candle'
  return (
    <div className="card pat-card">
      <div className="row between">
        <span className="co" style={{ cursor: 'pointer' }} onClick={() => go(`stock/${r.symbol}`)}><Logo sym={r.symbol} name={r.name} size={28} />
          <span className="nm"><b>{ticker(r.symbol)}</b>{r.fno && <FnoBadge />}<small>{r.name}</small></span></span>
        <div style={{ textAlign: 'right' }}><b>{mk === 'US' ? '$' : '₹'}{num(r.close, 2)}</b><div className="small muted">{r.date ? `Last, ${new Date(r.date + 'T12:00:00').toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })}` : ''}</div></div>
      </div>
      <div className="row between pat-title">
        <span><b>{p.name}</b> <span className="small muted">· {p.tf === 'W' ? 'weekly' : 'daily'}</span></span>
        <span className={`pat-dir ${p.dir === 'up' ? 't-good' : 't-bad'}`}>{p.dir === 'up' ? '▲ up' : '▼ down'}</span>
      </div>
      <div className="pat-chart-wrap"><span className="pat-tf">{tfL}</span><MiniChart p={p} /></div>
      <div className="pat-levels small">
        <span>{p.status === 'forming' ? (p.dir === 'up' ? 'Breakout above' : 'Breakdown below') : (p.dir === 'up' ? 'Breakout' : 'Breakdown')}</span><b>{num(p.level, 2)}</b>
        <span>Target</span><b className="t-good">{num(p.target, 2)}</b>
        <span>Stop</span><b className="t-bad">{num(p.stop, 2)}</b>
      </div>
      <div className="row between small" style={{ marginTop: 6 }}>
        <span>{st[0] && <span className={`chip-s ${st[1]}`}>{st[0]}</span>} {p.status === 'forming'
          ? <span className="muted">{ok(p.pct_from_level) ? `${num(Math.abs(p.pct_from_level), 1)}% to the ${p.dir === 'up' ? 'breakout' : 'breakdown'}` : ''}</span>
          : <span className="muted">{p.bars_ago === 0 ? `Broke ${p.dir === 'up' ? 'out' : 'down'} on the newest candle` : `Broke ${p.dir === 'up' ? 'out' : 'down'} ${p.bars_ago} ${cndl}${p.bars_ago > 1 ? 's' : ''} ago`}{p.vol_x ? ` · volume ${num(p.vol_x, 1)}x` : ''}</span>}</span>
        <span className="muted">R:R 1:{p.rr ?? '—'}</span>
      </div>
      <div className="row between small" style={{ marginTop: 4 }}>
        <span className="muted">{p.shape === 'textbook' ? 'Textbook shape' : p.shape === 'strong' ? 'Strong shape' : 'Loose shape'}</span>
        {p.status !== 'forming' && ok(p.pct_from_level) && <span className={p.pct_from_level * (p.dir === 'up' ? 1 : -1) >= 0 ? 't-good' : 't-bad'}>{num(Math.abs(p.pct_from_level), 1)}% {(p.pct_from_level >= 0) === (p.dir === 'up') ? 'beyond' : 'back inside'} the line</span>}
      </div>
      <RecordLine rec={d.record} p={p} base={d.record?.base} />
      {open && (
        <div className="small pat-learn">
          <div><b>Why it qualifies:</b> {p.why.join(' · ')}</div>
          <div style={{ marginTop: 4 }}><b>The rule:</b> {d.rules[p.type]}</div>
          <div className="muted" style={{ marginTop: 4 }}>Swing points from {p.start} · pattern known on {p.formed}{p.broke ? ` · broke ${p.dir === 'up' ? 'out' : 'down'} ${p.broke}` : ''}. Breakout means a {p.tf === 'W' ? 'weekly' : 'daily'} close beyond the line; Confirmed means that candle traded at least {p.tf === 'W' ? '1.3' : '1.5'}x its average volume.</div>
        </div>
      )}
      <div className="row pat-actions">
        <button className="btn small" onClick={onLearn}>{open ? 'Hide' : 'Learn this pattern'}</button>
        <button className="btn small" onClick={() => go(`stock/${r.symbol}/chart`)}>Open on chart</button>
      </div>
    </div>
  )
}

const SORTS = [['near', 'Nearest the line'], ['new', 'Newest'], ['rr', 'Best R:R'], ['record', 'Best past record']]

export default function Patterns() {
  const mk = getMarket()
  const [univ] = useUniv()
  const [uu] = useUsUniv()
  const [fno] = useFno()
  const [d, setD] = useState(null), [err, setErr] = useState(null)
  const [tab, setTab] = useState('classic')
  const [view, setView] = useState('breakout')
  const [tf, setTf] = useState('')
  const [dir, setDir] = useState('')
  const [type, setType] = useState('')
  const [sort, setSort] = useState('near')
  const [confOnly, setConfOnly] = useState(false)
  const [open, setOpen] = useState({})
  const [limit, setLimit] = useState(30)
  const which = mk === 'IN' ? univ : uu
  const load = () => api(`/api/patterns?market=${mk}&universe=${which}`).then((x) => { setD(x); setErr(null) }).catch((e) => setErr(e.message))
  useEffect(() => { setD(null); load() }, [mk, which])
  useEffect(() => { if (!d?.status?.running) return undefined; const t = setTimeout(load, 10000); return () => clearTimeout(t) }, [d])
  useEffect(() => setLimit(30), [tab, view, tf, dir, type, sort, confOnly, which])

  const rows = useMemo(() => (d?.rows || []).filter((r) => !(fno && mk === 'IN') || r.fno), [d, fno, mk])
  const items = useMemo(() => {
    const out = []
    for (const r of rows) for (const p of r.patterns || []) {
      if (view === 'forming' && p.status !== 'forming') continue
      if (view === 'breakout' && p.status !== 'breakout') continue
      if (tf && p.tf !== tf) continue
      if (dir && p.dir !== dir) continue
      if (type && p.type !== type) continue
      if (confOnly && !p.confirmed) continue
      out.push({ r, p })
    }
    const recOf = (p) => d?.record?.patterns?.[`${p.tf}:${p.type}:${p.dir}`]?.target_first ?? -1
    const key = {
      near: (x) => Math.abs(x.p.pct_from_level ?? 99) + (x.p.status === 'forming' ? 0 : -100 + (x.p.bars_ago || 0)),
      new: (x) => -(Date.parse(x.p.broke || x.p.formed) || 0),
      rr: (x) => -(x.p.rr ?? -1),
      record: (x) => -recOf(x.p),
    }[sort]
    return out.sort((a, b) => key(a) - key(b))
  }, [rows, view, tf, dir, type, sort, confOnly, d])
  const counts = useMemo(() => {
    const c = { forming: 0, breakout: 0, all: 0, confirmed: 0 }
    for (const r of rows) for (const p of r.patterns || []) {
      c.all++
      if (p.status === 'forming') c.forming++
      if (p.status === 'breakout') { c.breakout++; if (p.confirmed) c.confirmed++ }
    }
    return c
  }, [rows])
  const types = useMemo(() => [...new Set(rows.flatMap((r) => (r.patterns || []).map((p) => p.type)))].sort(), [rows])
  const list = mk === 'US' ? ({ SP500: 'S&P 500', NDX: 'Nasdaq-100', ALL: 'S&P 500 + Nasdaq-100' }[which] || 'S&P 500') : ({ N50: 'NIFTY 50', N100: 'NIFTY 100', N500: 'NIFTY 500', ALL: 'All NSE' }[which] || 'NIFTY 500')
  const rec = d?.record

  return (
    <div className="patterns">
      <div className="card">
        <div className="row between wrapflex" style={{ gap: 8 }}>
          <div>
            <h2 style={{ margin: '2px 0' }}>📐 Chart patterns</h2>
            <div className="small muted">{list} · found on each stock's real daily and weekly candles by written rules · nothing is drawn unless every rule passes</div>
          </div>
          {d?.status?.running && <div className="small">Loading prices {d.status.done}/{d.status.total}…</div>}
        </div>
        <div style={{ marginTop: 10 }}>{mk === 'IN' ? <UniverseChips /> : <UsUniverseChips />}</div>
        <div className="tabs" style={{ marginTop: 10 }}>
          {[['classic', 'Classic'], ['gaps', 'Gaps'], ['candles', 'Candlesticks']].map(([k, l]) => <button key={k} className={`tab ${tab === k ? 'on' : ''}`} onClick={() => setTab(k)}>{l}</button>)}
        </div>
      </div>
      {err && <div className="card t-bad">⚠️ {err}</div>}
      {!d && !err && <div className="card empty">Loading patterns…</div>}
      {d && !d.updated && <div className="card empty">Patterns are found during the price update{d.status?.running ? ` (running: ${d.status.done}/${d.status.total})` : ''}. They appear here when it finishes.</div>}

      {d?.updated && tab === 'classic' && (
        <>
          <div className="card" style={{ paddingBottom: 10 }}>
            <div className="row wrapflex" style={{ gap: 6 }}>
              <div className="seg">
                {[['forming', `Forming now ${counts.forming}`], ['breakout', `Breaking out ${counts.breakout}`], ['all', `All ${counts.all}`]].map(([k, l]) => <button key={k} className={view === k ? 'on' : ''} onClick={() => setView(k)}>{l}</button>)}
              </div>
              <div className="seg">{[['', 'D + W'], ['D', 'Daily'], ['W', 'Weekly']].map(([k, l]) => <button key={k} className={tf === k ? 'on' : ''} onClick={() => setTf(k)}>{l}</button>)}</div>
              <div className="seg">{[['', 'Both ways'], ['up', '▲ Up'], ['down', '▼ Down']].map(([k, l]) => <button key={k} className={dir === k ? 'on' : ''} onClick={() => setDir(k)}>{l}</button>)}</div>
              {view !== 'forming' && <button className={`tab ${confOnly ? 'on' : ''}`} onClick={() => setConfOnly(!confOnly)}>✓ Confirmed only {counts.confirmed}</button>}
              <select value={type} onChange={(e) => setType(e.target.value)}><option value="">Every pattern</option>{types.map((t) => <option key={t} value={t}>{d.names[t]}</option>)}</select>
              <select value={sort} onChange={(e) => setSort(e.target.value)}>{SORTS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
            </div>
            <div className="small muted" style={{ marginTop: 8 }}>
              {items.length} {items.length === 1 ? 'pattern' : 'patterns'} · Breaking out = a close beyond the line in the last {d.cfg.D.recent} daily / {d.cfg.W.recent} weekly candles · Confirmed = that candle had {d.cfg.D.vol_x}x (daily) / {d.cfg.W.vol_x}x (weekly) its average volume, Marginal = less.
              {rec && <> Tested record: {num(rec.stocks, 0)} stocks, {rec.from} to {rec.to}; any-day median 20 bars later {signed(rec.base.median_r20, 1, '%')}.</>}
            </div>
          </div>
          {!items.length && <div className="card empty">No pattern meets every rule here right now. That is an answer too: the app does not show shapes that only nearly qualify.</div>}
          <div className="pat-grid">
            {items.slice(0, limit).map(({ r, p }) => {
              const k = `${r.symbol}:${p.tf}:${p.type}`
              return <PatternCard key={k} r={r} p={p} d={d} open={!!open[k]} onLearn={() => setOpen({ ...open, [k]: !open[k] })} />
            })}
          </div>
          {items.length > limit && <div style={{ textAlign: 'center', margin: 10 }}><button className="btn" onClick={() => setLimit(limit + 30)}>Show more ({items.length - limit} left)</button></div>}
          <PatternRecordTable d={d} />
        </>
      )}
      {d?.updated && tab === 'gaps' && <Gaps d={d} rows={rows} />}
      {d?.updated && tab === 'candles' && <Candles d={d} rows={rows} />}
    </div>
  )
}

function PatternRecordTable({ d }) {
  const rec = d.record
  if (!rec) return null
  const rows = Object.entries(rec.patterns).filter(([, r]) => r.n).sort((a, b) => b[1].n - a[1].n)
  return (
    <details className="card">
      <summary><b>Tested record of every pattern</b> <span className="small muted">· {rec.from} to {rec.to}, {num(rec.stocks, 0)} stocks</span></summary>
      <div className="small muted" style={{ margin: '6px 0' }}>Each past breakout followed for 60 sessions (26 weeks): did price touch the target or the stop first? The pattern was found with the candles up to the breakout only (tested: running the detector on history cut at any day finds exactly the same breakouts).</div>
      <div className="tbl-wrap"><table className="tbl">
        <thead><tr><th style={{ textAlign: 'left' }}>Pattern</th><th>Frame</th><th>Way</th><th>Cases</th><th>Target first</th><th>Stop first</th><th>Neither</th><th>Median 20 bars</th></tr></thead>
        <tbody>{rows.map(([k, r]) => { const [tf, t, dr] = k.split(':'); return (
          <tr key={k}><td style={{ textAlign: 'left' }}>{d.names[t]}</td><td>{tf === 'W' ? 'Weekly' : 'Daily'}</td><td>{dr === 'up' ? '▲' : '▼'}</td><td>{num(r.n, 0)}</td>
            <td className="t-good">{pct(r.target_first)}</td><td className="t-bad">{pct(r.stop_first)}</td><td>{pct(r.neither)}</td><td>{ok(r.median_r20) ? signed(r.median_r20, 1, '%') : '—'}</td></tr>) })}</tbody>
      </table></div>
      <div className="small muted">Median 20 bars is signed in the pattern's direction (a fall after a breakdown counts as +). Any day: {signed(rec.base.median_r20, 1, '%')}, up {pct(rec.base.up_r20)} of the time.</div>
    </details>
  )
}

function Gaps({ d, rows }) {
  const [dirF, setDirF] = useState('')
  const [unfilled, setUnfilled] = useState(true)
  const items = useMemo(() => rows.flatMap((r) => (r.gaps || []).map((g) => ({ r, g })))
    .filter(({ g }) => (!dirF || g.dir === dirF) && (!unfilled || !g.filled))
    .sort((a, b) => a.g.days_ago - b.g.days_ago || b.g.size - a.g.size), [rows, dirF, unfilled])
  const rec = d.record?.gaps || {}
  return (
    <>
      <div className="card" style={{ paddingBottom: 10 }}>
        <div className="row wrapflex" style={{ gap: 6 }}>
          <div className="seg">{[['', 'Both'], ['up', '▲ Gap up'], ['down', '▼ Gap down']].map(([k, l]) => <button key={k} className={dirF === k ? 'on' : ''} onClick={() => setDirF(k)}>{l}</button>)}</div>
          <button className={`tab ${unfilled ? 'on' : ''}`} onClick={() => setUnfilled(!unfilled)}>Still open only</button>
        </div>
        <div className="small muted" style={{ marginTop: 8 }}>A gap = the day opened beyond the whole range of the day before, by at least 1%. Filled = price later traded back to the previous day's high (gap up) or low (gap down). Last 10 sessions.</div>
      </div>
      {!items.length && <div className="card empty">No gaps like that in the last 10 sessions.</div>}
      <div className="pat-grid">
        {items.slice(0, 90).map(({ r, g }) => {
          const k = rec[`${g.dir}:${g.bucket}`]
          return (
            <div key={`${r.symbol}${g.t}`} className="card pat-card">
              <div className="row between"><span className="co" style={{ cursor: 'pointer' }} onClick={() => go(`stock/${r.symbol}/chart`)}><Logo sym={r.symbol} name={r.name} size={26} /><span className="nm"><b>{ticker(r.symbol)}</b>{r.fno && <FnoBadge />}<small>{r.name}</small></span></span>
                <b className={g.dir === 'up' ? 't-good' : 't-bad'}>{g.dir === 'up' ? '▲' : '▼'} {num(g.size, 1)}% gap</b></div>
              <div className="pat-levels small" style={{ marginTop: 8 }}>
                <span>Day</span><b>{g.t}{g.days_ago === 0 ? ' (latest)' : ` (${g.days_ago} ago)`}</b>
                <span>Gap edge</span><b>{num(g.edge, 2)}</b>
                <span>Opened · closed</span><b>{num(g.open, 2)} · {num(g.close_day, 2)}</b>
                <span>Volume that day</span><b>{g.vol_x ? `${num(g.vol_x, 1)}x average` : '—'}</b>
                <span>Status</span><b className={g.filled ? 'muted' : ''}>{g.filled ? `Filled ${g.filled_on}` : `Open · now ${num(g.close, 2)}`}</b>
              </div>
              {k?.n ? <div className="small pat-rec">Past {g.bucket === 'big' ? '3%+' : '1–3%'} gaps {g.dir}: filled within 5 sessions {pct(k.filled_5)}, within 20 {pct(k.filled_20)} · {num(k.n, 0)} cases · median 20 sessions {signed(k.median_r20, 1, '%')}</div> : null}
            </div>
          )
        })}
      </div>
    </>
  )
}

function Candles({ d, rows }) {
  const [dirF, setDirF] = useState('')
  const [only, setOnly] = useState('')
  const items = useMemo(() => rows.flatMap((r) => (r.candles || []).map((c) => ({ r, c })))
    .filter(({ c }) => (!dirF || c.dir === dirF) && (!only || c.type === only))
    .sort((a, b) => a.c.days_ago - b.c.days_ago), [rows, dirF, only])
  const rec = d.record?.candles || {}
  const base = d.record?.base || {}
  const meta = d.candles
  return (
    <>
      <div className="card" style={{ paddingBottom: 10 }}>
        <div className="row wrapflex" style={{ gap: 6 }}>
          <div className="seg">{[['', 'Both'], ['up', '▲ Bullish'], ['down', '▼ Bearish']].map(([k, l]) => <button key={k} className={dirF === k ? 'on' : ''} onClick={() => setDirF(k)}>{l}</button>)}</div>
          <select value={only} onChange={(e) => setOnly(e.target.value)}><option value="">Every candlestick pattern</option>{Object.entries(meta).map(([k, m]) => <option key={k} value={k}>{m.name}</option>)}</select>
        </div>
        <div className="small muted" style={{ marginTop: 8 }}>On the last 3 daily candles. Each card shows how that candle pattern actually did in this list's history: how often price moved its way 10 sessions later, against any day ({pct(base.up_r10)} up after 10 sessions). Candle patterns alone are weak signals: the record shows how weak.</div>
      </div>
      {!items.length && <div className="card empty">No candlestick pattern on the last 3 candles here.</div>}
      <div className="pat-grid">
        {items.slice(0, 90).map(({ r, c }) => {
          const k = rec[c.type]
          const anyDay = c.dir === 'up' ? base.up_r10 : (base.up_r10 != null ? 100 - base.up_r10 : null)
          return (
            <div key={`${r.symbol}${c.type}${c.t}`} className="card pat-card">
              <div className="row between"><span className="co" style={{ cursor: 'pointer' }} onClick={() => go(`stock/${r.symbol}/chart`)}><Logo sym={r.symbol} name={r.name} size={26} /><span className="nm"><b>{ticker(r.symbol)}</b>{r.fno && <FnoBadge />}<small>{r.name}</small></span></span>
                <span className={c.dir === 'up' ? 't-good' : 't-bad'}>{c.dir === 'up' ? '▲' : '▼'} <b>{c.name}</b></span></div>
              <div className="row" style={{ gap: 10, alignItems: 'center', marginTop: 6 }}>
                <CandleStrip bars={c.draw} />
                <div className="small">{c.days_ago === 0 ? 'Latest candle' : `${c.days_ago} candle${c.days_ago > 1 ? 's' : ''} ago`} ({c.t})<br />Now {num(c.close, 2)}</div>
              </div>
              <div className="small muted" style={{ marginTop: 6 }}>{meta[c.type]?.rule}</div>
              {k?.n ? <div className="small pat-rec">Past cases: moved its way after 10 sessions <b>{pct(k.win10)}</b> (any day {pct(anyDay)}) · median {signed(k.median_r10, 1, '%')} · {num(k.n, 0)} cases</div> : null}
            </div>
          )
        })}
      </div>
    </>
  )
}
