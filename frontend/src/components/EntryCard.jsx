import { useEffect, useRef, useState } from 'react'
import { api, ago, go, rs } from '../util'
import { Badge } from './ui'
import { Md, useAISettings } from '../pages/AI'

const TONE = { ENTER: 'good', WAIT: 'warn', AVOID: 'bad', NA: 'neutral' }
const SHORT = { ENTER: 'Enter now', WAIT: 'Wait', AVOID: 'Avoid', NA: 'No call' }
const RULE_NAME = { enter: 'Enter (not falling)', enter_stretched: 'Enter (strong trend)', avoid_falling: 'Avoid (falling)' }
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
  const trendColor = e.rule === 'avoid_falling' ? 'var(--warn)' : 'var(--muted)'
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
  const wt = g?.wait_test || b?.wait_test
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
            {e.rule === 'avoid_falling' && wt && ` Had you waited for the close back above the 200-day average and bought then, to the same end date: ${pctTxt(wt.r12_waited)} vs ${pctTxt(wt.r12_bought_now)} buying at once; waiting won ${wt.waiting_won_pct}% of the time.`}
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

// Expensive vs its own P/E history: a caution backed by the backtest (it never changes the verdict).
function ValueCaution({ t, e }) {
  if (!e.checks?.value?.caution) return null
  const fresh = t && t.rules_version === e.rules_version
  const st = fresh && ((t.universe === 'ALL' && e.group && t.by_state_groups?.[e.group]?.Expensive) || t.by_state?.Expensive)
  const inGroup = fresh && t.universe === 'ALL' && e.group && t.by_state_groups?.[e.group]?.Expensive
  let text = 'Caution: expensive vs its own P/E history.'
  if (fresh && t.value_test?.passed && st?.p24) {
    text += ` Stocks this expensive ${inGroup ? `(${e.group === 'N500' ? 'in the NIFTY 500' : 'outside the NIFTY 500'}) ` : ''}did ${pctTxt(avg(st, 'p24'))} vs peers over 2 years`
      + (st.p36 ? ` and ${pctTxt(avg(st, 'p36'))} over 3 years` : '') + '. It does not change the verdict.'
  } else if (fresh && t.value_test?.passed === false) {
    text += ' The latest backtest did not confirm that expensive stocks lag, so treat this as information only.'
  }
  return <p className="small" style={{ margin: '8px 0 0', lineHeight: 1.45, color: 'var(--warn)' }}>{text}</p>
}

function Edge({ t, e }) {
  if (!t || t.rules_version !== e.rules_version || e.rule === 'avoid_business') return null
  const p = t.by_rule?.[e.rule]?.passed
  if (p === true) return <div className="small" style={{ marginTop: 6, color: 'var(--good)' }}>This rule passed the test set before the backtest.</div>
  if (p === false) return <div className="small" style={{ marginTop: 6, color: 'var(--warn)' }}>No proven edge on past data: this rule failed the test that was fixed before the backtest was run.</div>
  if (t.by_rule?.[e.rule]) return <div className="small muted" style={{ marginTop: 6 }}>Not enough data yet to test this rule.</div>
  return null
}

// ------------------------------------------------------------------ AI research on the entry
export const post = (path, body) => api(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) })
const STANCE = { agrees: ['good', 'Agrees with the engine'], partly: ['ok', 'Partly agrees'], disagrees: ['warn', 'Disagrees · verdict unchanged'] }
const SRC = { quarters: 'Quarters', profit_loss: 'P&L', balance_sheet: 'Balance sheet', cash_flow: 'Cash flow', valuation: 'Valuation', forensics: 'Forensics',
  peers: 'Peers', shareholding: 'Shareholding', technicals: 'Technicals', track_record: 'Track record', entry: 'Entry card' }
export const CONF = { high: 'var(--good)', medium: 'var(--text)', low: 'var(--warn)' }

export function Busy({ text }) {
  return <div className="row small muted" style={{ padding: '10px 0' }}><div className="spinner" style={{ width: 18, height: 18, margin: 0, borderWidth: 2 }} />{text}</div>
}
export function Unverified({ list }) {
  return list?.length ? <div className="small" style={{ color: 'var(--warn)', marginTop: 2 }}>⚠ not found in EquityLens data: {list.join(', ')}</div> : null
}

function Points({ title, items, color }) {
  return (
    <div className="tile">
      <div className="k" style={{ color }}>{title}</div>
      {!items?.length && <div className="small muted" style={{ marginTop: 4 }}>Nothing strong enough in the data.</div>}
      {items?.map((x, i) => (
        <div key={i} style={{ marginTop: 8 }}>
          <div style={{ fontSize: 13.5, fontWeight: 600 }}>{x.point} {x.source && <span className="chip" style={{ fontSize: 10.5, padding: '1px 6px', marginLeft: 4 }}>{SRC[x.source] || x.source}</span>}</div>
          <div className="small muted" style={{ lineHeight: 1.45 }}>{x.evidence}</div>
          <Unverified list={x.unverified} />
        </div>
      ))}
    </div>
  )
}

const ASK = ['What would make this an Enter?', 'Is the business getting better or worse?', 'How did this rule do for stocks like this?', 'What do the results need to show?']

function EntryAsk({ sym }) {
  const [msgs, setMsgs] = useState([]), [q, setQ] = useState(''), [busy, setBusy] = useState(false), [err, setErr] = useState(null)
  const end = useRef()
  useEffect(() => { setMsgs([]); setErr(null) }, [sym])
  useEffect(() => { if (msgs.length) end.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }) }, [msgs, busy])
  const ask = async (text) => {
    const t = (text ?? q).trim()
    if (!t || busy) return
    const next = [...msgs, { role: 'user', content: t }]
    setMsgs(next); setQ(''); setBusy(true); setErr(null)
    try { const r = await post(`/api/ai/chat/${encodeURIComponent(sym)}`, { messages: next, focus: 'entry' }); setMsgs([...next, { role: 'assistant', content: r.text }]) }
    catch (x) { setErr(x.message) } finally { setBusy(false) }
  }
  return (
    <div style={{ marginTop: 12 }}>
      {msgs.length === 0 && <div>{ASK.map((s) => <span key={s} className="chip" style={{ cursor: 'pointer' }} onClick={() => ask(s)}>{s}</span>)}</div>}
      {msgs.map((m, i) => <div key={i} className={`bubble ${m.role}`}>{m.role === 'assistant' ? <Md text={m.content} /> : m.content}</div>)}
      {busy && <Busy text="Thinking…" />}
      <div ref={end} />
      {err && <div className="small t-bad" style={{ marginTop: 6 }}>⚠️ {err}</div>}
      <div className="row" style={{ marginTop: 8 }}>
        <input className="grow" aria-label="Ask about this entry" value={q} placeholder="Ask about this entry…" onChange={(x) => setQ(x.target.value)} onKeyDown={(x) => x.key === 'Enter' && ask()} />
        <button className="btn primary" disabled={busy || !q.trim()} onClick={() => ask()}>Ask</button>
      </div>
    </div>
  )
}

function EntryAI({ sym, e }) {
  const settings = useAISettings()
  const [r, setR] = useState(null), [busy, setBusy] = useState(false), [err, setErr] = useState(null)
  const run = async (refresh) => {
    setBusy(true); setErr(null)
    try { setR(await post(`/api/ai/entry/${encodeURIComponent(sym)}${refresh ? '?refresh=1' : ''}`)) } catch (x) { setErr(x.message) } finally { setBusy(false) }
  }
  useEffect(() => { setR(null); if (settings?.ready) run(false) }, [settings?.ready, sym, e.date, e.rule]) // eslint-disable-line react-hooks/exhaustive-deps
  const st = r?.structured && (STANCE[r.verdict_check?.stance] || STANCE.partly)
  return (
    <section aria-label="AI research on this entry" style={{ borderTop: '1px solid var(--line)', marginTop: 12, paddingTop: 12 }}>
      <div className="row between" style={{ gap: 8, flexWrap: 'wrap' }}>
        <h4 style={{ margin: 0, fontSize: 15 }}>✦ AI research on this entry</h4>
        <div className="row" style={{ gap: 8 }}>
          {st && <Badge tone={st[0]}>{st[1]}</Badge>}
          {r && <button className="btn small" disabled={busy} onClick={() => run(true)}>↻ Redo</button>}
        </div>
      </div>
      {settings && !settings.ready && (
        <p className="small muted" style={{ marginBottom: 0 }}>Add an AI key in Settings to get AI research on every entry. <button className="btn small" onClick={() => go('settings')}>⚙️ Settings</button></p>
      )}
      {busy && <Busy text="Researching: the rule's track record, last 8 quarters, value, ownership and timing… (20–60 s)" />}
      {err && <div className="small t-bad" style={{ marginTop: 6 }}>⚠️ {err}</div>}
      {r && !r.structured && <Md text={r.text} />}
      {r?.structured && (
        <>
          <p style={{ fontWeight: 600, margin: '10px 0 4px', lineHeight: 1.45 }}>{r.headline}</p>
          <p className="small" style={{ margin: 0, lineHeight: 1.5 }}>{r.verdict_check.why}</p>
          <Unverified list={r.unverified_top} />
          <div className="grid2" style={{ marginTop: 10 }}>
            <Points title="Why it could work" items={r.thesis} color="var(--good)" />
            <Points title="What could go wrong" items={r.risks} color="var(--bad)" />
          </div>
          {r.what_changes_it?.length > 0 && (
            <div className="tile" style={{ marginTop: 10 }}>
              <div className="k">What would change the call</div>
              {r.what_changes_it.map((x, i) => (
                <div key={i} style={{ marginTop: 8, fontSize: 13.5, lineHeight: 1.45 }}>
                  <b>{x.trigger}</b>: {x.level} <span className="muted">→ {x.effect}</span>
                  <Unverified list={x.unverified} />
                </div>
              ))}
            </div>
          )}
          {r.watch?.length > 0 && (
            <div className="tile" style={{ marginTop: 10, overflowX: 'auto' }}>
              <div className="k">Watch next</div>
              <table style={{ width: '100%', fontSize: 13, marginTop: 6, borderCollapse: 'collapse' }}>
                <thead><tr className="small muted" style={{ textAlign: 'left' }}><th style={{ fontWeight: 500, padding: '4px 8px 4px 0' }}>What</th><th style={{ fontWeight: 500, padding: '4px 8px' }}>Now</th><th style={{ fontWeight: 500, padding: '4px 0 4px 8px' }}>Why it matters</th></tr></thead>
                <tbody>{r.watch.map((x, i) => (
                  <tr key={i} style={{ borderTop: '1px solid var(--line)', verticalAlign: 'top' }}>
                    <td style={{ padding: '6px 8px 6px 0', fontWeight: 600 }}>{x.item}</td>
                    <td style={{ padding: '6px 8px', whiteSpace: 'nowrap' }}>{x.now}<Unverified list={x.unverified} /></td>
                    <td className="muted" style={{ padding: '6px 0 6px 8px' }}>{x.why}</td>
                  </tr>))}
                </tbody>
              </table>
            </div>
          )}
          <div className="small" style={{ marginTop: 10, display: 'flex', flexWrap: 'wrap', gap: '4px 18px', lineHeight: 1.5 }}>
            <span>Confidence: <b style={{ color: CONF[r.confidence?.level] || 'var(--text)' }}>{r.confidence?.level}</b> <span className="muted">· {r.confidence?.why}</span></span>
            {r.numbers?.checked > 0 && (
              <span style={{ color: r.numbers.found === r.numbers.checked ? 'var(--good)' : 'var(--warn)' }}>
                Numbers checked: {r.numbers.found} of {r.numbers.checked} found in EquityLens data
              </span>
            )}
          </div>
          {r.confidence?.data_gaps?.length > 0 && <div className="small muted">Not in the data: {r.confidence.data_gaps.join('; ')}</div>}
          <div className="small muted" style={{ marginTop: 4 }}>{r.model} · {ago(r.created)} · AI view; the verdict above comes from the tested rules and does not change.</div>
        </>
      )}
      {settings?.ready && <EntryAsk sym={sym} />}
    </section>
  )
}

export default function EntryCard({ e, sym }) {
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
      <ValueCaution t={e.track} e={e} />
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
        {e.rule === 'avoid_falling' && e.review_if && (
          <div><div className="small muted">What changes it</div><b>no longer below a falling 200-day average (now {rs(e.review_if.below)})</b>
            <div className="small muted">then this turns to Enter by itself · not a buy level</div></div>
        )}
        {e.verdict === 'ENTER' && e.review_if && (
          <div><div className="small muted">Review if</div><b>it closes below a falling 200-day average (now {rs(e.review_if.below)})</b>
            <div className="small muted">or a new serious red flag · not backtested as an exit</div></div>
        )}
      </div>
      {sym && e.verdict !== 'NA' && <EntryAI sym={sym} e={e} />}
      <div style={{ borderTop: '1px solid var(--line)', marginTop: 12, paddingTop: 10 }}>
        <Track t={e.track} e={e} />
        <div className="small muted" style={{ marginTop: 6 }}>Research aid, not investment advice. Based on prices up to {e.date}.</div>
      </div>
    </div>
  )
}
