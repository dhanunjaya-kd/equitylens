import { useEffect, useState } from 'react'
import JobRunner from './JobRunner'
import { api } from '../util'
import { post } from './EntryCard'

function Auto({ name, st, onChange }) {
  const a = st?.checks?.[name]
  if (!a) return null
  return (
    <label className="small" style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 6, cursor: 'pointer' }}>
      <input type="checkbox" checked={a.enabled} onChange={(e) => post(`/api/jobs/auto/${name}?on=${e.target.checked}`).then(onChange)} />
      <span>🔁 Run by itself after each month end{a.enabled ? <span className="muted"> · {a.due ? `due: ${a.why} · starts ${a.next}` : `${a.why} · next: ${a.next}`}</span> : null}</span>
    </label>
  )
}

// Owner-only: the long checks behind the evidence shown on stock pages. They run by themselves after each month end
// (their results can only change then), outside market hours, one at a time. Repeat runs reuse every month whose
// outcome can no longer change, so they take minutes; the first run is the long one.
export default function DataChecks() {
  const [auto, setAuto] = useState(null)
  const load = () => api('/api/jobs/auto').then(setAuto).catch(() => {})
  useEffect(() => { load() }, [])
  return (
    <div className="card">
      <h3 style={{ marginTop: 0 }}>Data checks</h3>
      <p className="small muted" style={{ marginTop: 0 }}>
        These checks test EquityLens's rules on all NSE stocks, so the evidence shown on each stock page is measured, not assumed.
        They run by themselves after each month end, outside market hours. Each run keeps the months whose outcome can no longer
        change and works out only the newest ones, on all CPU cores, so repeat runs are much shorter than the first.
      </p>
      <div style={{ marginBottom: 12 }}>
        <b>Support and resistance zones</b>
        <div className="small muted" style={{ margin: '2px 0 6px' }}>Do zones really hold more often than random prices, and does a zone's own record predict its next test? Shown on every Price map.</div>
        <JobRunner name="levels" what="All NSE stocks" howLong="first run the longest; repeat runs much shorter" onDone={load} />
        <Auto name="levels" st={auto} onChange={setAuto} />
      </div>
      <div>
        <b>Entry decision and value record</b>
        <div className="small muted" style={{ margin: '2px 0 6px' }}>The track record behind the entry card and the value floor on the Price map.</div>
        <JobRunner name="entry" what="All NSE stocks" howLong="first run the longest (downloads P/E history); repeat runs much shorter" onDone={load} />
        <Auto name="entry" st={auto} onChange={setAuto} />
      </div>
    </div>
  )
}
