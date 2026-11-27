import { useEffect, useState } from 'react'
import { ago, api } from '../util'
import { post } from './EntryCard'

// Owner-only: everything EquityLens does by itself, with its schedule, last run and an on/off switch where it has one.
export default function Automation() {
  const [st, setSt] = useState(null)
  const [err, setErr] = useState('')
  const load = () => api('/api/automation').then((x) => { setSt(x); setErr('') }).catch((e) => setErr(e.message))
  useEffect(() => { load(); const t = setInterval(load, 30000); return () => clearInterval(t) }, [])
  const flip = (id, on) => post(`/api/automation/${id}?on=${on}`).then(setSt).catch((e) => setErr(e.message))
  if (err) return <div className="card small muted">Automation: {err}</div>
  if (!st) return null
  return (
    <div className="card">
      <h3 style={{ marginTop: 0 }}>🔁 Automation</h3>
      <p className="small muted" style={{ marginTop: 0 }}>What EquityLens does by itself while it is running. Times are India time. Switch off anything you don't want.</p>
      <div className="tbl-wrap"><table className="tbl auto-tbl"><thead><tr>
        <th style={{ textAlign: 'left' }}>Task</th><th style={{ textAlign: 'left' }}>When</th><th style={{ textAlign: 'left' }}>Last run</th><th>Status</th><th>On</th>
      </tr></thead><tbody>
        {st.tasks.map((t) => {
          const state = t.running ? <span className="ipo-cd warm">running{t.progress?.total ? ` ${t.progress.done}/${t.progress.total}` : ''}</span>
            : t.failed ? <span className="ipo-cd hot">last run failed</span>
              : t.enabled === false ? <span className="ipo-cd">off</span>
                : <span className="ipo-cd" style={{ color: 'var(--good)' }}>{t.next ? `next: ${t.next}` : 'on'}</span>
          return (
            <tr key={t.id}>
              <td style={{ textAlign: 'left', whiteSpace: 'normal' }}><b>{t.name}</b>{t.why && <div className="small muted">{t.why}</div>}</td>
              <td style={{ textAlign: 'left', whiteSpace: 'normal' }} className="small">{t.schedule}</td>
              <td style={{ textAlign: 'left' }} className="small">{t.last ? ago(t.last) : t.last_date || '—'}</td>
              <td>{state}</td>
              <td>{t.enabled === null ? <span className="small muted">always</span>
                : <input type="checkbox" checked={t.enabled} onChange={(e) => flip(t.id, e.target.checked)} aria-label={`Run ${t.name} automatically`} />}</td>
            </tr>
          )
        })}
      </tbody></table></div>
    </div>
  )
}
