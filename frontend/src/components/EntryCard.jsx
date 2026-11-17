import { rs } from '../util'
import { Badge } from './ui'

const TONE = { ENTER: 'good', PARTS: 'ok', WAIT: 'warn', AVOID: 'bad', NA: 'neutral' }
const SHORT = { ENTER: 'Enter now', PARTS: 'Enter in parts', WAIT: 'Wait', AVOID: 'Avoid', NA: 'No call' }
const pctTxt = (v) => (v == null ? '—' : `${v > 0 ? '+' : ''}${v}%`)

function PriceBar({ e }) {
  const ed = e.levels?.value_edges
  const pts = [e.price, e.exit_if, ...(e.zone || []), ...(e.plan || []).map((p) => p.price), ed?.cheap, ed?.fair, ed?.full].filter((x) => x > 0)
  const lo = Math.min(...pts) * 0.97, hi = Math.max(...pts) * 1.03
  const X = (v) => `${((v - lo) / (hi - lo)) * 100}%`
  const mark = (v, label, color, top) => {
    if (!(v > 0)) return null
    const f = (v - lo) / (hi - lo)                        // keep labels inside the bar at both ends
    const shift = f < 0.12 ? '0%' : f > 0.88 ? '-100%' : '-50%'
    return <div key={label + top} style={{ position: 'absolute', left: X(v), top, transform: `translateX(${shift})`, fontSize: 11, color, whiteSpace: 'nowrap' }}>{label}</div>
  }
  return (
    <div style={{ position: 'relative', height: 64, margin: '16px 4px 6px' }} aria-label="Price compared with the buy levels">
      <div style={{ position: 'absolute', top: 26, left: 0, right: 0, height: 8, borderRadius: 4, background: 'var(--card2)', border: '1px solid var(--line)' }} />
      {ed && ed.cheap > 0 && ed.full > 0 && (
        <div style={{ position: 'absolute', top: 26, height: 8, left: X(Math.min(ed.cheap, ed.full)), width: `calc(${X(Math.max(ed.cheap, ed.full))} - ${X(Math.min(ed.cheap, ed.full))})`, background: 'rgba(56,189,248,.18)' }} title="Fair range from its own P/E history" />
      )}
      {e.zone && <div style={{ position: 'absolute', top: 24, height: 12, left: X(e.zone[0]), width: `calc(${X(e.zone[1])} - ${X(e.zone[0])})`, background: 'rgba(34,197,94,.35)', border: '1px solid var(--good)', borderRadius: 3 }} />}
      {(e.plan || []).map((p, k) => <div key={k} style={{ position: 'absolute', top: 22, left: X(p.price), width: 2, height: 16, background: 'var(--good)' }} />)}
      <div style={{ position: 'absolute', top: 20, left: X(e.exit_if), width: 2, height: 20, background: 'var(--bad)' }} />
      <div style={{ position: 'absolute', top: 16, left: X(e.price), width: 3, height: 28, background: 'var(--text)', borderRadius: 2 }} />
      {mark(e.price, `Now ${rs(e.price)}`, 'var(--text)', 0)}
      {e.zone && mark((e.zone[0] + e.zone[1]) / 2, 'Buy zone', 'var(--good)', 46)}
      {e.plan && (Math.abs(e.plan[1].price - e.plan[2].price) / (hi - lo) < 0.12
        ? mark((e.plan[1].price + e.plan[2].price) / 2, 'Parts 2–3', 'var(--good)', 46)
        : e.plan.slice(1).map((p, k) => mark(p.price, `Part ${k + 2}`, 'var(--good)', 46)))}
      {mark(e.exit_if, 'Exit if below', 'var(--bad)', 46)}
    </div>
  )
}

function Track({ t, verdict }) {
  if (!t) return <div className="small muted">Track record appears after running <code>python tools\entry_backtest.py</code> once.</div>
  const b = t.by_verdict?.[verdict === 'AVOID' ? 'WAIT' : verdict]
  if (!b?.all?.r12) return null
  const a = b.all
  return (
    <div className="small muted" style={{ lineHeight: 1.6 }}>
      <b style={{ color: 'var(--text)' }}>Track record of "{SHORT[verdict === 'AVOID' ? 'WAIT' : verdict]}"</b> on NIFTY 500 since 2016 ({a.n.toLocaleString('en-IN')} calls):
      {' '}12-month return avg {pctTxt(a.r12.avg)}, {pctTxt(a.x12?.avg)} vs NIFTY, beat NIFTY {a.beat_nifty}% of the time, worst 10% {pctTxt(a.r12.worst10)}.
      {verdict === 'WAIT' && b.zone_hit_rate != null && ` Price reached the buy zone within 6 months ${b.zone_hit_rate}% of the time; bought in the zone ${pctTxt(b.r12_if_bought_in_zone)} vs bought immediately ${pctTxt(b.r12_if_bought_now)}.`}
      {verdict === 'PARTS' && b.r12_plan != null && ` The 3-part plan returned ${pctTxt(b.r12_plan)} vs ${pctTxt(b.r12_all_at_once)} buying all at once.`}
      {' '}Past results, not a promise. Tested {t.built}.
    </div>
  )
}

export default function EntryCard({ e }) {
  if (!e) return null
  const c = e.checks || {}
  const rows = [
    ['Business', c.business], ['Price vs value', c.value], ['Trend and timing', c.timing], ['Events', c.events],
  ]
  return (
    <div className="card">
      <div className="row between" style={{ alignItems: 'flex-start', gap: 12 }}>
        <div className="grow">
          <div className="small muted">Entry decision · for a 1–3 year holding</div>
          <h3 style={{ margin: '4px 0 0', fontSize: 20 }}>{e.label}</h3>
        </div>
        <div style={{ textAlign: 'right' }}>
          <Badge tone={TONE[e.verdict]}>{SHORT[e.verdict]}</Badge>
          {e.conviction != null && <div className="small muted" style={{ marginTop: 6 }}>Conviction {e.conviction}/100</div>}
        </div>
      </div>
      {e.reasons?.map((r) => <p key={r} style={{ margin: '8px 0 0', lineHeight: 1.45 }}>{r}</p>)}
      {e.verdict !== 'NA' && <PriceBar e={e} />}
      <div className="grid2" style={{ marginTop: 6 }}>
        {rows.map(([k, x]) => x && (
          <div key={k} className="tile">
            <div className="k">{k}</div>
            <div style={{ fontSize: 13.5, marginTop: 3, color: x.ok === true ? 'var(--good)' : x.ok === false ? 'var(--warn)' : 'var(--muted)' }}>
              {x.ok === true ? '✓ ' : x.ok === false ? '! ' : ''}{x.text}
            </div>
          </div>
        ))}
      </div>
      <div style={{ marginTop: 12, display: 'flex', flexWrap: 'wrap', gap: '10px 24px' }}>
        {e.plan && (
          <div><div className="small muted">Entry plan in 3 parts</div>
            <b>{e.plan.map((p) => `${p.pct}% at ${rs(p.price)}`).join(' · ')}</b></div>
        )}
        {e.zone && (
          <div><div className="small muted">Buy zone</div><b>{rs(e.zone[0])} – {rs(e.zone[1])}</b></div>
        )}
        {e.verdict !== 'AVOID' && e.verdict !== 'NA' && (
          <div><div className="small muted">Exit if</div><b>weekly close below {rs(e.exit_if)}</b>
            <div className="small muted">or a new serious red flag</div></div>
        )}
      </div>
      <div style={{ borderTop: '1px solid var(--line)', marginTop: 12, paddingTop: 10 }}>
        <Track t={e.track} verdict={e.verdict} />
        <div className="small muted" style={{ marginTop: 6 }}>Research aid, not investment advice. Based on prices up to {e.date}.</div>
      </div>
    </div>
  )
}
