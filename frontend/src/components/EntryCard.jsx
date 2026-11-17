import { rs } from '../util'
import { Badge } from './ui'

const TONE = { ENTER: 'good', WAIT: 'warn', AVOID: 'bad', NA: 'neutral' }
const SHORT = { ENTER: 'Enter now', WAIT: 'Wait', AVOID: 'Avoid', NA: 'No call' }
const RULE_NAME = { enter: 'Enter (not falling)', enter_stretched: 'Enter (stretched)', wait_falling: 'Wait (falling)' }
const pctTxt = (v) => (v == null ? '—' : `${v > 0 ? '+' : ''}${v}%`)
const avg = (b, k = 'p12') => b?.[k]?.avg

function PriceBar({ e }) {
  const ed = e.levels?.value_edges
  const s200 = e.levels?.sma200
  const pts = [e.price, s200, ed?.cheap, ed?.full].filter((x) => x > 0)
  const lo = Math.min(...pts) * 0.97, hi = Math.max(...pts) * 1.03
  const X = (v) => `${((v - lo) / (hi - lo)) * 100}%`
  const mark = (v, label, color, top) => {
    if (!(v > 0)) return null
    const f = (v - lo) / (hi - lo)                        // keep labels inside the bar at both ends
    const shift = f < 0.12 ? '0%' : f > 0.88 ? '-100%' : '-50%'
    return <div key={label + top} style={{ position: 'absolute', left: X(v), top, transform: `translateX(${shift})`, fontSize: 11, color, whiteSpace: 'nowrap' }}>{label}</div>
  }
  const trendColor = e.verdict === 'WAIT' ? 'var(--warn)' : 'var(--muted)'
  return (
    <div style={{ position: 'relative', height: 64, margin: '16px 4px 6px' }} aria-label="Price compared with its 200-day average and its usual P/E range">
      <div style={{ position: 'absolute', top: 26, left: 0, right: 0, height: 8, borderRadius: 4, background: 'var(--card2)', border: '1px solid var(--line)' }} />
      {ed && ed.cheap > 0 && ed.full > 0 && (
        <div style={{ position: 'absolute', top: 26, height: 8, left: X(Math.min(ed.cheap, ed.full)), width: `calc(${X(Math.max(ed.cheap, ed.full))} - ${X(Math.min(ed.cheap, ed.full))})`, background: 'rgba(56,189,248,.18)' }} title="Usual range from its own P/E history (information only)" />
      )}
      {s200 > 0 && <div style={{ position: 'absolute', top: 20, left: X(s200), width: 2, height: 20, background: trendColor }} />}
      <div style={{ position: 'absolute', top: 16, left: X(e.price), width: 3, height: 28, background: 'var(--text)', borderRadius: 2 }} />
      {mark(e.price, `Now ${rs(e.price)}`, 'var(--text)', 0)}
      {mark(s200, `200-day avg ${rs(s200)}`, trendColor, 46)}
    </div>
  )
}

function Track({ t, e }) {
  const run = <code>python tools\entry_backtest.py</code>
  if (!t || t.rules_version !== e.rules_version) {
    return <div className="small muted">The track record for these rules appears after running {run} once.</div>
  }
  const b = t.by_rule?.[e.rule]
  const st = e.checks?.value?.state && t.by_state?.[e.checks.value.state]
  const rules = Object.values(t.by_rule || {})
  const passed = rules.filter((r) => r.passed === true).length
  const where = t.universe_label || 'NIFTY 500 stocks'
  const g = e.group && b?.groups?.[e.group]
  const gName = t.groups?.[e.group]
  return (
    <div className="small muted" style={{ lineHeight: 1.6 }}>
      {e.rule === 'avoid_business'
        ? <div>The business check is <b>not backtested</b>: past business scores aren't available without hindsight.</div>
        : b?.p12 && (
          <div>
            <b style={{ color: 'var(--text)' }}>Track record of this rule — {RULE_NAME[e.rule]}</b>, {where} since 2016
            {' '}({b.n.toLocaleString('en-IN')} monthly calls): 12 months {pctTxt(avg(b))} vs peers
            {' '}(2016–20 {pctTxt(avg(b.first_half))}, 2021 on {pctTxt(avg(b.second_half))})
            {b.months_beat_pct != null && `, beat peers in ${b.months_beat_pct}% of months`};
            {' '}24 months {pctTxt(avg(b, 'p24'))} vs peers. The rule claims these stocks {b.expect}.
            {e.rule === 'wait_falling' && b.wait_test && ` Waiting for the close above the 200-day average, measured to the same end date: ${pctTxt(b.wait_test.r12_waited)} vs ${pctTxt(b.wait_test.r12_bought_now)} buying now (the trend turned within 12 months ${b.wait_test.turned_pct}% of the time).`}
          </div>
        )}
      {g?.p12 && gName && t.universe === 'ALL' && (
        <div>This stock is {e.group === 'N500' ? 'in the NIFTY 500' : 'outside the NIFTY 500'}. Among those stocks ({g.n.toLocaleString('en-IN')} calls),
          {' '}this rule did {pctTxt(avg(g))} vs peers in the same group over 12 months (2016–20 {pctTxt(avg(g.first_half))}, 2021 on {pctTxt(avg(g.second_half))}).
          {g.claim_held === false && ' The claim did not hold for this group.'}</div>
      )}
      {st?.p12 && (
        <div>Stocks in the "{e.checks.value.state}" value state: {pctTxt(avg(st))} vs peers over 12 months, {pctTxt(avg(st, 'p24'))} over 24 months
          {t.value_test?.passed === false ? ' — value did not pass its test, so it does not change the verdict.' : '.'}</div>
      )}
      <div>Engine: {passed} of {rules.length} tested rules passed the test set before the run (same result in both halves and in most months).
        {' '}"vs peers" = return minus the average of all tested stocks in the same month. Calls on illiquid stocks (under ₹1 crore a day) left out. Stocks delisted since 2016 are missing. Results warning not tested. Past results, not a promise. Tested {t.built}.</div>
    </div>
  )
}

function Edge({ t, e }) {
  if (!t || t.rules_version !== e.rules_version || e.rule === 'avoid_business') return null
  const p = t.by_rule?.[e.rule]?.passed
  if (p === true) return <div className="small" style={{ marginTop: 6, color: 'var(--good)' }}>This rule passed the test set before the backtest.</div>
  if (p === false) return <div className="small" style={{ marginTop: 6, color: 'var(--warn)' }}>No proven edge yet: this rule failed the test set before the backtest.</div>
  if (t.by_rule?.[e.rule]) return <div className="small muted" style={{ marginTop: 6 }}>Not enough data yet to test this rule.</div>
  return null
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
          <Edge t={e.track} e={e} />
        </div>
        <Badge tone={TONE[e.verdict]}>{SHORT[e.verdict]}</Badge>
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
        {e.trigger && (
          <div><div className="small muted">Buy trigger</div><b>a close above {rs(e.trigger)}</b>
            <div className="small muted">its 200-day average; this level moves every day</div></div>
        )}
        {e.verdict === 'ENTER' && e.review_if && (
          <div><div className="small muted">Review if</div><b>it closes below a falling 200-day average (now {rs(e.review_if.below)})</b>
            <div className="small muted">or a new serious red flag · not backtested as an exit</div></div>
        )}
      </div>
      <div style={{ borderTop: '1px solid var(--line)', marginTop: 12, paddingTop: 10 }}>
        <Track t={e.track} e={e} />
        <div className="small muted" style={{ marginTop: 6 }}>Research aid, not investment advice. Based on prices up to {e.date}.</div>
      </div>
    </div>
  )
}
