import { useEffect, useRef, useState } from 'react'
import { api, ago } from '../util'
import { post } from './EntryCard'

export default function JobRunner({ name, what, howLong, onDone, compact }) {
  const [st, setSt] = useState(null), [denied, setDenied] = useState(false), [busy, setBusy] = useState(false)
  const wasRunning = useRef(false)
  const check = () => api(`/api/jobs/${name}`).then((x) => {
    if (wasRunning.current && !x.running && x.finished) onDone?.()
    wasRunning.current = x.running
    setSt(x)
  }).catch((e) => { if (String(e.message).match(/owner|403|forbidden/i)) setDenied(true) })
  useEffect(() => { check() }, [name]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!st?.running) return undefined
    const t = setInterval(check, 5000)
    return () => clearInterval(t)
  }, [st?.running]) // eslint-disable-line react-hooks/exhaustive-deps
  const start = async () => { setBusy(true); try { const x = await post(`/api/jobs/${name}/start`); wasRunning.current = x.running; setSt(x) } finally { setBusy(false) } }
  if (denied) return <div className="small muted">Only the owner of this EquityLens can run this test.</div>
  if (!st) return null
  if (st.running) {
    const p = st.progress, pctDone = p?.total ? Math.round((p.done / p.total) * 100) : 0
    return (
      <div className="pmap-job">
        <div className="small"><b>{st.label}: running</b> · {p ? `${p.done.toLocaleString('en-IN')} of ${p.total.toLocaleString('en-IN')} stocks` : 'starting…'}{st.started ? ` · started ${ago(st.started)}` : ''} · you can keep using the app</div>
        <div className="pmap-prog"><div style={{ width: `${pctDone}%` }} /></div>
        {st.last_lines?.length > 0 && <div className="small muted" style={{ fontFamily: 'monospace', fontSize: 11 }}>{st.last_lines[st.last_lines.length - 1]}</div>}
      </div>
    )
  }
  return (
    <div className="pmap-job">
      {st.failed && (
        <div className="small" style={{ color: 'var(--bad)', marginBottom: 6 }}>The last run stopped before finishing:
          <pre style={{ whiteSpace: 'pre-wrap', fontSize: 11, margin: '4px 0' }}>{st.last_lines.slice(-4).join('\n')}</pre>
        </div>
      )}
      <div className="row" style={{ gap: 10, flexWrap: 'wrap' }}>
        <button className={compact ? 'btn small' : 'btn primary small'} disabled={busy} onClick={start}>{st.result_built ? '↻ Run again' : '▶ Run the test now'}</button>
        <span className="small muted">{what} · {howLong} · runs in the background{st.result_built ? ` · last result ${st.result_built}` : ''}</span>
      </div>
    </div>
  )
}
