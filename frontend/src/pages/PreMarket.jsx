import { useEffect, useState } from 'react'
import { api, ago, go, num, signed } from '../util'
import { Badge, Loading } from '../components/ui'
import { Md, useAISettings } from './AI'

// Pre-market (India): overnight board, the NIFTY opening call and its real track record.
const post = (path) => api(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
const IMPACT = { positive: ['good', 'Positive for NIFTY'], negative: ['bad', 'Negative for NIFTY'], neutral: ['neutral', 'Neutral'] }
const LEAN = { up: 'good', down: 'bad', flat: 'neutral', na: 'neutral' }
const pctOf = (v) => (v == null ? '—' : `${v}%`)
const dayName = (iso) => { try { return new Date(`${iso}T00:00:00`).toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric', month: 'short' }) } catch { return iso } }
const priceTxt = (p) => (p == null ? '—' : p < 10 ? (+p).toFixed(4) : num(p, p < 1000 ? 2 : 0))

function ScoreBar({ score }) {
  const left = score == null ? 50 : 50 + score / 2
  return (
    <div style={{ margin: '14px 0 4px' }}>
      <div role="img" aria-label={`Overnight score ${score ?? 'not available'} on a scale from minus 100 to plus 100`}
        style={{ position: 'relative', height: 10, borderRadius: 5, background: 'linear-gradient(90deg, var(--bad), var(--line) 50%, var(--good))' }}>
        {score != null && <span style={{ position: 'absolute', left: `calc(${left}% - 2px)`, top: -5, width: 4, height: 20, borderRadius: 2, background: 'var(--text)' }} />}
        <span style={{ position: 'absolute', left: '60%', top: 0, bottom: 0, width: 1, background: 'var(--muted)', opacity: 0.6 }} title="+20: gap-up line" />
        <span style={{ position: 'absolute', left: '40%', top: 0, bottom: 0, width: 1, background: 'var(--muted)', opacity: 0.6 }} title="−20: gap-down line" />
      </div>
      <div className="row between small muted" style={{ marginTop: 6 }}><span>−100 negative</span><span>score {score == null ? '—' : signed(score, 0)}</span><span>positive +100</span></div>
    </div>
  )
}

function CallCard({ d }) {
  const t = d.track, a = t?.all
  const top = [...d.factors].sort((x, y) => Math.abs(y.contrib) - Math.abs(x.contrib))
  return (
    <section className="card" aria-label="NIFTY opening call">
      <div className="row" style={{ gap: 10, flexWrap: 'wrap' }}>
        <h3 style={{ margin: 0 }}>NIFTY opening call · {dayName(d.day)}</h3>
        <Badge tone={LEAN[d.call]}>{d.lean}</Badge>
        {d.frozen && <span className="small muted">saved for the record at {d.built.slice(11)} IST</span>}
      </div>
      <div style={{ fontSize: 28, fontWeight: 800, margin: '10px 0 0', letterSpacing: '-0.02em' }}>{d.label}</div>
      {d.after_open && <div className="small t-warn" style={{ marginTop: 4 }}>The market is already open: this score was rebuilt after 09:15 for reference. The call that counts was saved at 09:14 (see Live calls below).</div>}
      <ScoreBar score={d.score} />
      <div className="small muted">Main call: {d.check_0845?.proven && d.check_0845?.score != null ? 'the 08:45 check (it passed its test)' : 'the overnight score below (the 08:45 check hasn’t passed its test)'}</div>
      <div className="small muted" style={{ marginBottom: 6 }}>What moves the score (each market's last session before 09:15 IST, scaled by its own normal daily move)</div>
      {top.map((f) => (
        <div key={f.name} className="row" style={{ gap: 10, padding: '6px 0', borderTop: '1px solid var(--line)', alignItems: 'baseline' }}>
          <b style={{ width: 22, textAlign: 'center', color: f.contrib > 0 ? 'var(--good)' : f.contrib < 0 ? 'var(--bad)' : 'var(--muted)' }}>{f.contrib > 0 ? '+' : f.contrib < 0 ? '−' : '·'}</b>
          <span className="grow"><b>{f.name}</b> {f.ret == null ? 'not available' : `${signed(f.ret, 2)}%`} <span className="muted small">{f.date ? `on ${dayName(f.date)}` : ''} · {f.why}</span></span>
          <span className="small muted" style={{ whiteSpace: 'nowrap' }}>counts {f.contrib == null ? '—' : signed(f.contrib, 1)}</span>
        </div>
      ))}
      <Check0845 d={d} />
      <div className="grid3 pm-hits" style={{ marginTop: 12 }}>
        <div className="tile">
          <div className="k">Open-direction calls right (backtest)</div>
          <div className="v">{a ? pctOf(a.gap_hit) : '—'}</div>
          <div className="s">{a ? `Past data: ${num(a.up_calls + a.down_calls)} calls on every NIFTY day ${t.from?.slice(0, 4)}–${t.to?.slice(0, 4)} · always guessing the common side: ${pctOf(a.gap_naive)}` : 'Backtest not run yet'}</div>
          {t && <Periods t={t} />}
        </div>
        <div className="tile">
          <div className="k">Live calls checked</div>
          <div className="v">{d.live?.checked ? `${d.live.right} of ${d.live.checked}` : '—'}</div>
          <div className="s">{d.live?.checked ? 'Frozen at 09:14, checked against the real open' : 'Builds up from the first morning the app runs before 09:15'}</div>
        </div>
        <div className="tile">
          <div className="k">Day direction (open → close)</div>
          <div className="v" style={{ fontSize: 15 }}>{t ? (t.day_passed ? `${pctOf(a.day_hit)} right` : 'No tested edge') : '—'}</div>
          <div className="s">{t ? (t.day_passed ? 'Passed the same test' : `${pctOf(a?.day_hit)} vs ${pctOf(a?.day_naive)} by always guessing: the call is about the open, not the day`) : ''}</div>
        </div>
      </div>
      <p className="small" style={{ margin: '12px 0 0', color: 'var(--warn)', lineHeight: 1.5 }}>GIFT Nifty: {d.gift.note}</p>
    </section>
  )
}

// The overnight call's backtest, period by period, with the rule it had to pass (fixed before the backtest was run).
function Periods({ t }) {
  const rows = [['2016–20', t.first_half], [`2021–${t.to?.slice(2, 4)}`, t.second_half]]
  const ok = (h) => h?.gap_hit != null && h.gap_hit > 55 && h.gap_hit - h.gap_naive >= 5
  const short = rows.filter(([, h]) => !ok(h)).map(([k]) => k)
  return (
    <>
      {rows.map(([k, h]) => (
        <div key={k} className="s">{ok(h) ? '✓' : '✗'} {k}: right {pctOf(h?.gap_hit)} vs {pctOf(h?.gap_naive)} by guessing ({num((h?.up_calls || 0) + (h?.down_calls || 0))} calls)</div>
      ))}
      <div className="s" style={{ color: t.gap_passed ? 'var(--good)' : 'var(--warn)', fontWeight: 600 }}>
        {t.gap_passed ? 'Proven on past data: 5+ points better than guessing in both periods'
          : `Not proven on past data: it had to be 5+ points better than guessing in both periods; ${short.join(' and ')} fell short`}
      </div>
    </>
  )
}

function Check0845({ d }) {
  const c = d.check_0845, t2 = d.track2
  if (!c) return null
  const a = t2?.all
  const status = c.proven ? ['var(--good)', 'Passed its test: this is the main call now']
    : t2 ? ['var(--warn)', `Not proven on past data · tested on ${num(t2.days)} days (${t2.from?.slice(0, 7)} to ${t2.to?.slice(0, 7)}, all the hourly history free sources keep): `
      + `right ${pctOf(a?.v2?.gap_hit)} vs the overnight call ${pctOf(a?.v1?.gap_hit)} vs always guessing ${pctOf(a?.v2?.gap_naive)}. `
      + `It had to beat the overnight call by 5+ points in both halves; it beat it by ${a?.v2?.gap_hit != null && a?.v1?.gap_hit != null ? (a.v2.gap_hit - a.v1.gap_hit).toFixed(1) : '—'}, so the overnight call stays the main call.`]
    : ['var(--muted)', 'Being tested on the last two years of hourly prices']
  return (
    <div className="tile" style={{ marginTop: 12 }}>
      <div className="row between" style={{ gap: 8, flexWrap: 'wrap' }}>
        <div className="k">08:45 check: overnight call + US futures since the close + Asia now</div>
        {c.score != null && <Badge tone={LEAN[c.call]}>{c.label} · {signed(c.score, 0)}</Badge>}
      </div>
      {c.score == null && <div className="s">Not available yet: needs US futures after the close and Asia's first hour (from {c.available_from}).</div>}
      {c.factors.map((f) => (
        <div key={f.name} className="s" style={{ marginTop: 4 }}>
          <b style={{ color: f.contrib > 0 ? 'var(--good)' : f.contrib < 0 ? 'var(--bad)' : 'var(--muted)' }}>{f.contrib > 0 ? '+' : f.contrib < 0 ? '−' : '·'}</b>{' '}
          {f.name}: {f.ret == null ? 'not yet' : `${signed(f.ret, 2)}%`} <span className="muted">· counts {signed(f.contrib, 1)} (×{f.w})</span>
        </div>
      ))}
      <div className="s" style={{ marginTop: 6, color: status[0], fontWeight: 600 }}>{status[1]}</div>
    </div>
  )
}

function Evening({ e }) {
  if (!e) return null
  return (
    <section className="card" aria-label="Evening preview" style={{ borderColor: 'var(--accent)' }}>
      <div className="row" style={{ gap: 10, flexWrap: 'wrap' }}>
        <h3 style={{ margin: 0 }}>🌙 Evening preview for {dayName(e.day)}</h3>
        <Badge tone={LEAN[e.call]}>{e.lean}</Badge>
        <span className="small muted">{e.built} IST</span>
      </div>
      <div style={{ fontSize: 22, fontWeight: 800, margin: '8px 0 4px' }}>{e.label} <span className="small muted">score {e.score == null ? '—' : signed(e.score, 0)}</span></div>
      <div className="small muted">{e.factors.map((f) => `${f.name} ${f.ret == null ? '—' : `${signed(f.ret, 2)}%`}`).join(' · ')}</div>
      <div className="small t-warn" style={{ marginTop: 6 }}>{e.note}</div>
    </section>
  )
}

function DayMap({ m }) {
  if (!m) return null
  const L = m.levels, rh = m.range_history
  const lv = [['Prev high', L.prev_high], ['Prev low', L.prev_low], ['Prev close', L.prev_close], ['Pivot', L.pivot], ['CPR', `${num(L.cpr_bottom, 0)}–${num(L.cpr_top, 0)}`], ['R1', L.r1], ['S1', L.s1], ['R2', L.r2], ['S2', L.s2]]
  return (
    <section className="card" aria-label="Day map">
      <h3>🗺️ Day map · {dayName(m.day)}</h3>
      <div className="small muted" style={{ marginTop: -4, marginBottom: 10 }}>Levels and odds from NIFTY's own history; not a forecast of the day's direction.</div>
      <div className="grid3 pm-hits">
        <div className="tile">
          <div className="k">Expected range today</div>
          <div className="v">±{m.expected_move_pct}%</div>
          <div className="s">≈ {num(m.range_low, 0)} – {num(m.range_high, 0)} · from India VIX {m.vix} ({dayName(m.vix_day)})</div>
          {rh?.days > 0 && <div className="s">Since {m.since.slice(0, 4)}, NIFTY stayed inside this range all day on {rh.stayed_inside_pct}% of days and closed inside it on {rh.closed_inside_pct}%.</div>}
        </div>
        <div className="tile" style={{ gridColumn: 'span 2' }}>
          <div className="k">Key levels from {dayName(m.prev_day)} · CPR width {L.cpr_width_pct}% {L.cpr_width_pct < 0.2 ? '(narrow: often a trending day)' : L.cpr_width_pct > 0.5 ? '(wide: often a range day)' : ''}</div>
          <div className="pm-levels">{lv.map(([k, v]) => <div key={k}><span className="small muted">{k}</span><b>{typeof v === 'number' ? num(v, 0) : v}</b></div>)}</div>
        </div>
      </div>
      <h4 style={{ marginTop: 14 }}>What NIFTY did after each size of opening gap (since {m.since.slice(0, 4)})</h4>
      <div style={{ overflowX: 'auto' }}>
        <table className="pm-table">
          <thead><tr><th>Opening gap</th><th>Days</th><th>Gap filled the same day</th><th>Closed above the open</th><th>Avg open → close</th></tr></thead>
          <tbody>{m.gaps.map((g, i) => (
            <tr key={g.label} style={i === m.actual_bucket ? { background: 'var(--card2)', fontWeight: 700 } : undefined}>
              <td>{g.label}{i === m.actual_bucket ? ` ← today (${signed(m.actual_gap_pct, 2)}%)` : ''}</td><td>{num(g.days)}</td>
              <td>{g.gap_filled_pct == null ? '—' : `${g.gap_filled_pct}%`}</td><td>{pctOf(g.closed_above_open_pct)}</td>
              <td className={g.avg_open_to_close_pct > 0 ? 't-good' : g.avg_open_to_close_pct < 0 ? 't-bad' : ''}>{g.avg_open_to_close_pct == null ? '—' : `${signed(g.avg_open_to_close_pct, 2)}%`}</td></tr>
          ))}</tbody>
        </table>
      </div>
      <p className="small muted">{m.actual_bucket == null ? 'At 09:15 today’s opening gap is marked in this table. ' : ''}Gap filled = NIFTY traded back to the previous close the same day. Averages are history, not a promise.</p>
    </section>
  )
}

function Board({ d }) {
  const groups = [...d.groups, ...(d.flows?.length ? [{ name: 'Flows (yesterday)', items: d.flows.map((f) => ({ ...f, price: null, flow: true })) }] : [])]
  return (
    <section className="card" aria-label="Overnight markets">
      <h3>Overnight markets</h3>
      <div className="small muted" style={{ marginTop: -4, marginBottom: 10 }}>What each move means for NIFTY<span className="src-note"> · free Yahoo and NSE data</span> · read at {d.built.slice(11)} IST</div>
      {groups.map((g) => (
        <div key={g.name} style={{ marginBottom: 12 }}>
          <h4>{g.name}</h4>
          <div className="pm-tiles">
            {g.items.map((i) => {
              const im = IMPACT[i.impact] || IMPACT.neutral
              return (
                <div key={i.name} className="tile" style={i.flow ? { cursor: 'pointer' } : undefined} onClick={i.flow ? () => go('fiidii') : undefined}>
                  <div className="k">{i.name}</div>
                  {i.flow
                    ? <div className="v" style={{ color: i.net >= 0 ? 'var(--good)' : 'var(--bad)' }}>{i.net >= 0 ? '+' : '−'}₹{num(Math.abs(i.net), 0)} cr</div>
                    : <div className="row" style={{ gap: 8, alignItems: 'baseline' }}>
                        <span className="v">{priceTxt(i.price)}</span>
                        <span style={{ fontWeight: 600, fontSize: 13, color: i.change_pct > 0 ? 'var(--good)' : i.change_pct < 0 ? 'var(--bad)' : 'var(--muted)' }}>{i.change_pct == null ? '' : `${i.change_pct > 0 ? '▲' : i.change_pct < 0 ? '▼' : ''} ${Math.abs(i.change_pct).toFixed(2)}%`}</span>
                      </div>}
                  <div style={{ marginTop: 4 }}><Badge tone={im[0]}>{im[1]}</Badge></div>
                  <div className="s" style={{ lineHeight: 1.4 }}>{i.error ? 'Not available right now' : i.flow ? `${i.date} · ${i.why} · tap for the full FII / DII page` : i.why}</div>
                </div>
              )
            })}
          </div>
        </div>
      ))}
      {d.notes?.length > 0 && <div className="small t-warn">{d.notes.join(' · ')}</div>}
    </section>
  )
}

function Today({ d }) {
  if (!d.today?.length) return null
  return (
    <section className="card" aria-label="Today">
      <h3>Today · {dayName(d.day)}</h3>
      {d.today.map((t, i) => (
        <div key={i} className="row" style={{ gap: 12, padding: '7px 0', borderTop: i ? '1px solid var(--line)' : 0, alignItems: 'baseline' }}>
          <b style={{ minWidth: 64, color: 'var(--accent)' }}>{t.time}</b>
          <span className="grow" style={{ lineHeight: 1.45 }}>{t.text}</span>
        </div>
      ))}
      <button className="btn small" style={{ marginTop: 8 }} onClick={() => go('calendar')}>Open the calendar</button>
    </section>
  )
}

function Brief({ d }) {
  const settings = useAISettings()
  const [r, setR] = useState(null), [busy, setBusy] = useState(false), [err, setErr] = useState(null)
  const run = async (refresh) => {
    setBusy(true); setErr(null)
    try { setR(await post(`/api/ai/premarket?market=IN${refresh ? '&refresh=1' : ''}`)) } catch (x) { setErr(x.message) } finally { setBusy(false) }
  }
  useEffect(() => { if (settings?.ready) run(false) }, [settings?.ready, d.built]) // eslint-disable-line react-hooks/exhaustive-deps
  const n = r?.numbers
  return (
    <section className="card" aria-label="AI pre-market brief">
      <div className="row between" style={{ gap: 8, flexWrap: 'wrap' }}>
        <h3 style={{ margin: 0 }}>✦ AI pre-market brief</h3>
        <div className="row" style={{ gap: 8 }}>
          {n?.checked > 0 && <span className="small" style={{ color: n.found === n.checked ? 'var(--good)' : 'var(--warn)' }}>Numbers checked: {n.found} of {n.checked} found in this morning's data</span>}
          {r && <button className="btn small" disabled={busy} onClick={() => run(true)}>↻ Redo</button>}
        </div>
      </div>
      {settings && !settings.ready && <p className="small muted">Add an AI key in Settings to get a written brief every morning. <button className="btn small" onClick={() => go('settings')}>⚙️ Settings</button></p>}
      {busy && <Loading text="Writing this morning's brief… (20–40 s)" />}
      {err && <div className="small t-bad">⚠️ {err}</div>}
      {r && <Md text={r.text} />}
      {n?.not_found?.length > 0 && <div className="small t-warn">⚠ not found in the data: {n.not_found.join(', ')}</div>}
      {r && <div className="small muted">{r.model} · {ago(r.created)} · written only from the figures on this page; it can't see news yet.</div>}
    </section>
  )
}

function Track({ d, onRun, running }) {
  const t = d.track
  const rows = t ? [['2016 → now', t.all], ['2016–20', t.first_half], ['2021 on', t.second_half]] : []
  return (
    <section className="card" aria-label="How the morning call has done">
      <h3>How the morning call has done</h3>
      {!t && <p className="small muted">The backtest hasn't run yet. It takes under a minute. <button className="btn small" disabled={running} onClick={onRun}>{running ? 'Running…' : 'Run it now'}</button></p>}
      {t && (
        <div style={{ overflowX: 'auto' }}>
          <table className="pm-table">
            <thead><tr><th>Backtest</th><th>NIFTY days</th><th>Up / down calls</th><th>Open direction right</th><th>Always guessing</th><th>Day direction right</th></tr></thead>
            <tbody>{rows.map(([k, s]) => (
              <tr key={k}><td>{k}</td><td>{num(s.days)}</td><td>{num(s.up_calls)} / {num(s.down_calls)}</td><td><b>{pctOf(s.gap_hit)}</b></td><td>{pctOf(s.gap_naive)}</td><td>{pctOf(s.day_hit)} <span className="muted">vs {pctOf(s.day_naive)}</span></td></tr>
            ))}</tbody>
          </table>
          <p className="small muted" style={{ lineHeight: 1.5 }}>Rules fixed before the run: {t.rules.factors.map((f) => `${f.name} ×${f.w}`).join(' · ')}; score ≥ +{t.rules.up} gap-up, ≤ {t.rules.down} gap-down. Pass test: {t.rules.pass_rule} Days left out: {Object.entries(t.skipped).filter(([, v]) => v).map(([k, v]) => `${v} ${k}`).join(', ') || 'none'}. Tested {t.built}.</p>
        </div>
      )}
      {d.track2?.days > 0 && (
        <>
          <h4>08:45 check vs the overnight call ({d.track2.from} to {d.track2.to}, {num(d.track2.days)} days of hourly data)</h4>
          <div style={{ overflowX: 'auto' }}>
            <table className="pm-table">
              <thead><tr><th>Window</th><th>Overnight call right</th><th>08:45 check right</th><th>Always guessing</th><th>Up / down calls (08:45)</th></tr></thead>
              <tbody>{[['All', d.track2.all], ['Before 2026', d.track2.first_half], ['2026', d.track2.second_half]].map(([k, s]) => (
                <tr key={k}><td>{k}</td><td>{pctOf(s.v1.gap_hit)}</td><td><b>{pctOf(s.v2.gap_hit)}</b></td><td>{pctOf(s.v2.gap_naive)}</td><td>{num(s.v2.up_calls)} / {num(s.v2.down_calls)}</td></tr>
              ))}</tbody>
            </table>
          </div>
          <p className="small muted">{d.track2.pass_rule} Result: <b className={d.track2.passed ? 't-good' : 't-warn'}>{d.track2.passed ? 'passed: it is the main call' : 'not passed: shown as a check only'}</b>. Tested {d.track2.built}.</p>
        </>
      )}
      <h4>Live calls</h4>
      {!d.live?.rows?.length && <p className="small muted">Each morning's call is saved at 09:14 and checked here after the open. Nothing is edited afterwards.</p>}
      {d.live?.rows?.length > 0 && (
        <div style={{ overflowX: 'auto' }}>
          <table className="pm-table">
            <thead><tr><th>Day</th><th>Call at 09:14</th><th>Score</th><th>Actual open</th><th>Open → close</th><th>Right?</th><th>08:45 check right?</th></tr></thead>
            <tbody>{d.live.rows.map((r) => (
              <tr key={r.day}><td>{dayName(r.day)}</td><td>{r.label}</td><td>{signed(r.score, 0)}</td>
                <td>{r.gap == null ? 'not yet' : `${signed(r.gap, 2)}%`}</td><td>{r.move == null ? '—' : `${signed(r.move, 2)}%`}</td>
                <td className={r.right == null ? 'muted' : r.right ? 't-good' : 't-bad'}>{r.right == null ? (r.call === 'flat' ? 'no call' : '—') : r.right ? 'Yes' : 'No'}</td>
                <td className={r.right2 == null ? 'muted' : r.right2 ? 't-good' : 't-bad'}>{r.right2 == null ? (r.call2 === 'flat' ? 'no call' : '—') : r.right2 ? 'Yes' : 'No'}</td></tr>
            ))}</tbody>
          </table>
        </div>
      )}
      <p className="small muted">Research aid, not investment advice. Hit rates are history, not a promise.</p>
    </section>
  )
}

export default function PreMarket() {
  const [d, setD] = useState(null), [err, setErr] = useState(null), [busy, setBusy] = useState(false), [running, setRunning] = useState(false)
  const load = async (refresh) => {
    setBusy(true); setErr(null)
    try { setD(await api(`/api/premarket?market=IN${refresh ? '&refresh=1' : ''}`)) } catch (x) { setErr(x.message) } finally { setBusy(false) }
  }
  useEffect(() => { load(false) }, [])
  const runBacktest = async () => {
    setRunning(true)
    try { await post('/api/premarket/backtest'); for (let i = 0; i < 40; i++) { await new Promise((r) => setTimeout(r, 4000)); const x = await api('/api/premarket?market=IN&refresh=1'); setD(x); if (x.track) break } }
    catch (x) { setErr(x.message) } finally { setRunning(false) }
  }
  return (
    <div className="pm">
      <div className="row between" style={{ gap: 10, flexWrap: 'wrap', margin: '6px 0 12px' }}>
        <div>
          <h2 style={{ margin: 0 }}>🌅 Pre-market</h2>
          <div className="small muted">{d ? `India · for the ${dayName(d.day)} session · built ${d.built.slice(11)} IST · rebuilt every 10 minutes from 08:20 until the 09:15 open` : 'India'}</div>
        </div>
        <div className="row" style={{ gap: 8 }}>
          <span className="tab on">🇮🇳 India</span>
          <span className="tab" title="Coming next" style={{ opacity: 0.55 }}>🇺🇸 US · next</span>
          <button className="btn small" disabled={busy} onClick={() => load(true)}>{busy ? 'Refreshing…' : '↻ Refresh'}</button>
        </div>
      </div>
      {err && <div className="card t-bad">⚠️ {err}</div>}
      {!d && !err && <Loading text="Reading overnight markets…" />}
      {d && (
        <>
          <div className="pm-top">
            <div>
              <Evening e={d.evening} />
              <CallCard d={d} />
            </div>
            <Today d={d} />
          </div>
          <DayMap m={d.day_map} />
          <Board d={d} />
          <Brief d={d} />
          <div className="card small muted">Coming next on this page: verified global news (a story counts only when 2+ independent sources report it) and stocks in focus from overnight filings, results, deals and US-listed shares.</div>
          <Track d={d} onRun={runBacktest} running={running} />
        </>
      )}
    </div>
  )
}
