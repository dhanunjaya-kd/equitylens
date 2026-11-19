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
      <div className="small muted" style={{ marginBottom: 6 }}>What moves the score (each market's last session before 09:15 IST, scaled by its own normal daily move)</div>
      {top.map((f) => (
        <div key={f.name} className="row" style={{ gap: 10, padding: '6px 0', borderTop: '1px solid var(--line)', alignItems: 'baseline' }}>
          <b style={{ width: 22, textAlign: 'center', color: f.contrib > 0 ? 'var(--good)' : f.contrib < 0 ? 'var(--bad)' : 'var(--muted)' }}>{f.contrib > 0 ? '+' : f.contrib < 0 ? '−' : '·'}</b>
          <span className="grow"><b>{f.name}</b> {f.ret == null ? 'not available' : `${signed(f.ret, 2)}%`} <span className="muted small">{f.date ? `on ${dayName(f.date)}` : ''} · {f.why}</span></span>
          <span className="small muted" style={{ whiteSpace: 'nowrap' }}>counts {f.contrib == null ? '—' : signed(f.contrib, 1)}</span>
        </div>
      ))}
      <div className="grid3 pm-hits" style={{ marginTop: 12 }}>
        <div className="tile">
          <div className="k">Open-direction calls right (backtest)</div>
          <div className="v">{a ? pctOf(a.gap_hit) : '—'}</div>
          <div className="s">{a ? `${num(a.up_calls + a.down_calls)} calls, ${t.from?.slice(0, 4)}–${t.to?.slice(0, 4)} · always guessing the common side: ${pctOf(a.gap_naive)}` : 'Backtest not run yet'}</div>
          {t && <div className="s" style={{ color: t.gap_passed ? 'var(--good)' : 'var(--warn)', fontWeight: 600 }}>{t.gap_passed ? 'Passed the test set before the backtest' : 'No proven edge (failed the test set before the backtest)'}</div>}
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

function Board({ d }) {
  const groups = [...d.groups, ...(d.flows?.length ? [{ name: 'Flows (yesterday)', items: d.flows.map((f) => ({ ...f, price: null, flow: true })) }] : [])]
  return (
    <section className="card" aria-label="Overnight markets">
      <h3>Overnight markets</h3>
      <div className="small muted" style={{ marginTop: -4, marginBottom: 10 }}>What each move means for NIFTY · free Yahoo and NSE data · read at {d.built.slice(11)} IST</div>
      {groups.map((g) => (
        <div key={g.name} style={{ marginBottom: 12 }}>
          <h4>{g.name}</h4>
          <div className="pm-tiles">
            {g.items.map((i) => {
              const im = IMPACT[i.impact] || IMPACT.neutral
              return (
                <div key={i.name} className="tile">
                  <div className="k">{i.name}</div>
                  {i.flow
                    ? <div className="v" style={{ color: i.net >= 0 ? 'var(--good)' : 'var(--bad)' }}>{i.net >= 0 ? '+' : '−'}₹{num(Math.abs(i.net), 0)} cr</div>
                    : <div className="row" style={{ gap: 8, alignItems: 'baseline' }}>
                        <span className="v">{priceTxt(i.price)}</span>
                        <span style={{ fontWeight: 600, fontSize: 13, color: i.change_pct > 0 ? 'var(--good)' : i.change_pct < 0 ? 'var(--bad)' : 'var(--muted)' }}>{i.change_pct == null ? '' : `${i.change_pct > 0 ? '▲' : i.change_pct < 0 ? '▼' : ''} ${Math.abs(i.change_pct).toFixed(2)}%`}</span>
                      </div>}
                  <div style={{ marginTop: 4 }}><Badge tone={im[0]}>{im[1]}</Badge></div>
                  <div className="s" style={{ lineHeight: 1.4 }}>{i.error ? 'Not available right now' : i.flow ? `${i.date} · ${i.why}` : i.why}</div>
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
      <h4>Live calls</h4>
      {!d.live?.rows?.length && <p className="small muted">Each morning's call is saved at 09:14 and checked here after the open. Nothing is edited afterwards.</p>}
      {d.live?.rows?.length > 0 && (
        <div style={{ overflowX: 'auto' }}>
          <table className="pm-table">
            <thead><tr><th>Day</th><th>Call at 09:14</th><th>Score</th><th>Actual open</th><th>Open → close</th><th>Right?</th></tr></thead>
            <tbody>{d.live.rows.map((r) => (
              <tr key={r.day}><td>{dayName(r.day)}</td><td>{r.label}</td><td>{signed(r.score, 0)}</td>
                <td>{r.gap == null ? 'not yet' : `${signed(r.gap, 2)}%`}</td><td>{r.move == null ? '—' : `${signed(r.move, 2)}%`}</td>
                <td className={r.right == null ? 'muted' : r.right ? 't-good' : 't-bad'}>{r.right == null ? (r.call === 'flat' ? 'no call' : '—') : r.right ? 'Yes' : 'No'}</td></tr>
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
            <CallCard d={d} />
            <Today d={d} />
          </div>
          <Board d={d} />
          <Brief d={d} />
          <div className="card small muted">Coming next on this page: verified global news (a story counts only when 2+ independent sources report it) and stocks in focus from overnight filings, results, deals and US-listed shares.</div>
          <Track d={d} onRun={runBacktest} running={running} />
        </>
      )}
    </div>
  )
}
