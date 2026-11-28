import { useEffect, useState } from 'react'
import { ago, api, go } from '../util'
import { post } from './EntryCard'

const toScans = () => { go('settings'); setTimeout(() => document.getElementById('scans')?.scrollIntoView({ behavior: 'smooth' }), 500) }
const mins = (s) => (s == null ? null : s < 90 ? `~${Math.max(1, Math.round(s))} s left` : s < 5400 ? `~${Math.round(s / 60)} min left` : `~${Math.round(s / 3600)} h left`)

function Bar({ done, total }) {
  const p = total ? Math.min(100, Math.round((done / total) * 100)) : null
  return <div className="scan-bar"><i style={{ width: p == null ? '35%' : `${p}%` }} className={p == null ? 'indet' : ''} /></div>
}

function Status({ t }) {
  if (t.running) {
    const p = t.progress || {}
    return (
      <div>
        <Bar done={p.done} total={p.total} />
        <div className="small muted">{p.total ? `${p.done} / ${p.total}` : 'running'}{t.eta_s ? ` · ${mins(t.eta_s)}` : ''}</div>
      </div>
    )
  }
  if (t.queued) return <span className="small" style={{ color: 'var(--warn)' }}>⏳ in the queue</span>
  if (t.due) return <span className="small" style={{ color: t.enabled ? 'var(--warn)' : 'var(--muted)' }}>{t.why}{t.enabled ? '' : ' · runs when you press Run now'}</span>
  return <span className="small" style={{ color: 'var(--good)' }}>✓ {t.why}</span>
}

// Owner-only: every scan EquityLens runs, each with Auto / Manual, Run now, progress and last run; plus all of them together.
export default function Automation() {
  const [st, setSt] = useState(null)
  const [err, setErr] = useState('')
  const load = () => api('/api/automation').then((x) => { setSt(x); setErr('') }).catch((e) => setErr(e.message))
  useEffect(() => { load(); const t = setInterval(load, 5000); return () => clearInterval(t) }, [])
  const act = (url) => post(url).then(setSt).catch((e) => setErr(e.message))
  if (err) return <div className="card small muted">Scans: {err}</div>
  if (!st) return null
  const o = st.overall
  return (
    <div className="card" id="scans">
      <div className="row between wrapflex" style={{ gap: 8 }}>
        <h3 style={{ margin: 0 }}>🔄 Scans and background jobs</h3>
        <div className="ipo-seg">
          {[['auto', 'Auto: start when the app opens'], ['manual', 'Manual']].map(([k, l]) => <button key={k} className={st.mode === k ? 'on' : ''} onClick={() => act(`/api/automation/mode?value=${k}`)}>{l}</button>)}
        </div>
      </div>
      <p className="small muted" style={{ margin: '6px 0 10px' }}>
        {st.mode === 'auto'
          ? 'Auto: when the app opens, and every minute while it runs, each scan that is switched on and out of date starts by itself. Heavy scans run one at a time (the rest wait in the queue); light ones run alongside.'
          : 'Manual: nothing starts by itself, not even when you open a page. Press Run now on a scan, or Run all.'}
      </p>
      <div className="scan-all">
        <div className="grow" style={{ minWidth: 0 }}>
          <b>All scans together</b>
          <div className="small muted">
            {o.running ? `${o.running} running${o.names?.length ? `: ${o.names.join(', ')}` : ''}` : 'Nothing running'}
            {o.queued ? ` · ${o.queued} in the queue` : ''}{o.due ? ` · ${o.due} out of date` : ''}
          </div>
          {o.running > 0 && <><Bar done={o.done} total={o.total} /><div className="small muted">{o.pct != null ? `${o.pct}% of the running scans' items` : 'running'}</div></>}
        </div>
        <button className="btn primary small" onClick={() => act('/api/automation/run-all')}>▶ Run all</button>
      </div>
      <div className="tbl-wrap"><table className="tbl auto-tbl"><thead><tr>
        <th style={{ textAlign: 'left' }}>Scan</th><th>Auto</th><th style={{ textAlign: 'left', minWidth: 190 }}>Status</th><th style={{ textAlign: 'left' }}>Last run</th><th />
      </tr></thead><tbody>
        {st.tasks.map((t) => (
          <tr key={t.id}>
            <td style={{ textAlign: 'left', whiteSpace: 'normal' }}><b>{t.name}</b>{t.heavy && <span className="small muted"> · heavy</span>}<div className="small muted">{t.fills}</div></td>
            <td><input type="checkbox" checked={t.enabled} onChange={(e) => act(`/api/automation/${t.id}?on=${e.target.checked}`)} aria-label={`Run ${t.name} automatically`} /></td>
            <td style={{ textAlign: 'left', whiteSpace: 'normal' }}><Status t={t} /></td>
            <td style={{ textAlign: 'left' }} className="small">{t.last ? ago(t.last) : t.last_date || '—'}</td>
            <td><button className="btn small" disabled={t.running || t.queued} onClick={() => act(`/api/automation/run/${t.id}`)}>{t.running ? 'Running' : t.queued ? 'Queued' : 'Run now'}</button></td>
          </tr>
        ))}
      </tbody></table></div>
      <div className="small muted" style={{ marginTop: 10 }}>
        <b>Always on</b> (light, no switch): {st.always.map((a) => `${a.name} (${a.schedule}${a.last ? `, last ${ago(a.last)}` : ''})`).join(' · ')}
      </div>
    </div>
  )
}

// Top bar: a small spinning ring while scans run. Click -> Settings -> Scans.
export function ScanIndicator() {
  const [r, setR] = useState(null)
  useEffect(() => {
    let stop = false
    const load = () => api('/api/automation/running').then((x) => !stop && setR(x)).catch(() => !stop && setR(null))
    load()
    const t = setInterval(load, 8000)
    return () => { stop = true; clearInterval(t) }
  }, [])
  if (!r || !r.overall?.running) return null
  const o = r.overall
  return (
    <button className="scan-ind" title={r.running.map((x) => x.name).join('\n')} onClick={toScans}>
      <span className="scan-spin" />{o.running} scan{o.running > 1 ? 's' : ''} running{o.pct != null ? ` · ${o.pct}%` : ''}
    </button>
  )
}

// Home dashboard: what is running now (hidden when nothing runs).
export function RunningCard() {
  const [r, setR] = useState(null)
  useEffect(() => {
    let stop = false
    const load = () => api('/api/automation/running').then((x) => !stop && setR(x)).catch(() => !stop && setR(null))
    load()
    const t = setInterval(load, 8000)
    return () => { stop = true; clearInterval(t) }
  }, [])
  if (!r || (!r.running.length && !r.queued.length)) return null
  return (
    <div className="card running-card">
      <div className="row between"><b><span className="scan-spin" /> Running now</b><button className="btn small" onClick={toScans}>All scans</button></div>
      {r.running.map((x) => (
        <div key={x.id} style={{ marginTop: 8 }}>
          <div className="row between small"><span>{x.name}</span><span className="muted">{x.progress?.total ? `${x.progress.done} / ${x.progress.total}` : 'running'}{x.eta_s ? ` · ${mins(x.eta_s)}` : ''}</span></div>
          <Bar done={x.progress?.done} total={x.progress?.total} />
        </div>
      ))}
      {r.queued.length > 0 && <div className="small muted" style={{ marginTop: 8 }}>Next in the queue: {r.queued.join(', ')}</div>}
    </div>
  )
}
