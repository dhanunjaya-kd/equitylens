import { useEffect, useState } from 'react'
import { api, deviceBackup, dropDeviceBackup, go, importDeviceBackup, me, saveLocal, signOut } from '../util'
import { Badge } from '../components/ui'

// My account: who is signed in, what is saved with the account, lists found only in this browser, security.
const count = (k) => { try { const v = JSON.parse(localStorage.getItem(k) || 'null'); return Array.isArray(v) ? v.length : v && typeof v === 'object' ? Object.keys(v).length : 0 } catch { return 0 } }
const LABEL = { eql_watch: 'watchlist stocks', eql_screens: 'saved screens', eql_notes: 'stock notes', eql_recent: 'recent stocks', eql_over2: 'chart layout', eql_panes: 'chart panels' }
const postJSON = (path, body) => api(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) })

export default function Account() {
  const [a, setA] = useState(null), [ai, setAi] = useState(null), [tick, setTick] = useState(0)
  const [pw, setPw] = useState({ old: '', new: '' }), [pwMsg, setPwMsg] = useState(null), [hideImport, setHideImport] = useState(false)
  useEffect(() => { api('/api/auth').then(setA).catch(() => {}); api('/api/ai/settings').then(setAi).catch(() => {}) }, [])
  useEffect(() => { const on = () => setTick((t) => t + 1); window.addEventListener('eql-data', on); return () => window.removeEventListener('eql-data', on) }, [])
  if (!a) return <div className="empty">Loading…</div>
  if (!a.accounts) {
    return (
      <div className="card">
        <h3>👤 My account</h3>
        <p className="muted" style={{ lineHeight: 1.5 }}>Sign-in is off on this EquityLens, so your lists are kept only in this browser. The owner can turn sign-in on in Settings → Accounts.</p>
        <button className="btn primary" onClick={() => go('settings')}>Open Settings</button>
      </div>
    )
  }
  const u = a.user || me() || {}
  const backup = deviceBackup()
  const backupItems = Object.entries(backup).map(([k, raw]) => { let n = 0; try { const v = JSON.parse(raw); n = Array.isArray(v) ? v.length : Object.keys(v || {}).length } catch { /* skip */ } return [k, n] }).filter(([, n]) => n)
  const rows = [
    ['Watchlist', `${count('eql_watch')} stocks`, 'watch'],
    ['Saved screens', `${count('eql_screens')}`, 'screener'],
    ['My notes on stocks', `${count('eql_notes')} stocks`, null],
    ['Recent stocks', `${count('eql_recent')}`, ''],
    ['Chart layout', count('eql_over2') ? 'saved' : 'default', null],
    ['AI settings and key', ai ? (ai.ready ? `${ai.provider} · ready` : 'not set up') : '…', 'settings'],
  ]
  const changePw = async (e) => {
    e.preventDefault(); setPwMsg(null)
    try { await postJSON('/api/auth/password', pw); setPw({ old: '', new: '' }); setPwMsg('Password changed ✓') } catch (x) { setPwMsg(`⚠️ ${x.message}`) }
  }
  const download = async () => {
    const d = await api('/api/me/export')
    const url = URL.createObjectURL(new Blob([JSON.stringify(d, null, 2)], { type: 'application/json' }))
    const link = Object.assign(document.createElement('a'), { href: url, download: `equitylens-${(u.email || u.github || 'me').replace(/[^\w.-]/g, '_')}.json` })
    link.click(); URL.revokeObjectURL(url)
  }
  return (
    <div className="account" data-tick={tick}>
      <h2 style={{ margin: '6px 0 12px' }}>👤 My account</h2>
      <div className="card row" style={{ gap: 12 }}>
        <span className="avatar" aria-hidden="true">{(u.name || u.email || '?').slice(0, 1).toUpperCase()}</span>
        <div className="grow">
          <b>{u.name}</b> {u.role === 'owner' && <Badge tone="ok">Owner</Badge>}
          <div className="small muted">{[u.email, u.github && `GitHub @${u.github}`].filter(Boolean).join(' · ')}</div>
        </div>
      </div>

      {backupItems.length > 0 && !hideImport && (
        <div className="card" role="status" style={{ borderColor: 'var(--accent)' }}>
          <b>Found saved lists on this device</b>
          <p className="small muted" style={{ lineHeight: 1.5 }}>{backupItems.map(([k, n]) => `${n} ${LABEL[k] || k}`).join(', ')} are stored only in this browser. Add them to your account so they show on every device?</p>
          <div className="row" style={{ gap: 8 }}>
            <button className="btn primary" onClick={async () => { await importDeviceBackup(); setTick((t) => t + 1) }}>Add to my account</button>
            <button className="btn" onClick={() => setHideImport(true)}>Not now</button>
            <button className="btn small" onClick={() => { if (window.confirm('Delete the lists stored only in this browser?')) { dropDeviceBackup(); setTick((t) => t + 1) } }}>Discard them</button>
          </div>
        </div>
      )}

      <div className="card">
        <h4 style={{ marginTop: 0 }}>Saved with your account</h4>
        {rows.map(([name, val, path]) => (
          <div key={name} className="row between" style={{ padding: '10px 0', borderTop: '1px solid var(--line)', cursor: path != null ? 'pointer' : 'default' }} onClick={() => path != null && go(path)}>
            <b>{name}</b><span className="small muted">{val}{path != null ? ' ›' : ''}</span>
          </div>
        ))}
        <div className="small muted" style={{ marginTop: 6 }}>Changes are saved to your account within a second. Your AI key is yours only: no one else on this EquityLens can see or use it.</div>
      </div>

      <div className="card">
        <h4 style={{ marginTop: 0 }}>Sign-in</h4>
        {!u.github && a.github && <p className="small"><a className="btn small" href="/api/auth/github/start">Link my GitHub account</a> <span className="muted">so you can also sign in with GitHub</span></p>}
        <form onSubmit={changePw} className="grid2">
          {u.has_password && <label className="small muted field">Current password<input type="password" autoComplete="current-password" value={pw.old} onChange={(e) => setPw({ ...pw, old: e.target.value })} /></label>}
          <label className="small muted field">{u.has_password ? 'New password' : 'Set a password (10+ characters)'}<input type="password" minLength={10} autoComplete="new-password" value={pw.new} onChange={(e) => setPw({ ...pw, new: e.target.value })} /></label>
          <div style={{ gridColumn: '1 / -1' }}><button className="btn" disabled={!pw.new}>{u.has_password ? 'Change password' : 'Set password'}</button> {pwMsg && <span className="small">{pwMsg}</span>}</div>
        </form>
      </div>

      <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
        <button className="btn" onClick={download}>Download my data</button>
        <button className="btn" style={{ color: 'var(--bad)' }} onClick={signOut}>Sign out</button>
      </div>
    </div>
  )
}

// 📝 My notes on a stock (Overview tab): saved in this browser and, with sign-in on, to the account
export function NotesCard({ symbol }) {
  const read = () => { try { return JSON.parse(localStorage.getItem('eql_notes') || '{}') } catch { return {} } }
  const [text, setText] = useState(() => read()[symbol]?.text || ''), [saved, setSaved] = useState(null)
  useEffect(() => { const on = () => setText(read()[symbol]?.text || ''); window.addEventListener('eql-data', on); return () => window.removeEventListener('eql-data', on) }, [symbol])
  useEffect(() => {
    const t = setTimeout(() => {
      const all = read()
      if ((all[symbol]?.text || '') === text) return
      if (text.trim()) all[symbol] = { text, updated: Date.now() }
      else delete all[symbol]
      saveLocal('eql_notes', all)
      setSaved(new Date())
    }, 800)
    return () => clearTimeout(t)
  }, [text, symbol])
  return (
    <div className="card">
      <div className="row between"><h3 style={{ margin: 0 }}>📝 My notes</h3>{saved && <span className="small muted">saved {saved.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>}</div>
      <textarea aria-label={`My notes on ${symbol}`} value={text} onChange={(e) => setText(e.target.value)} rows={4}
        placeholder="Why you're watching it, your buy price, what to check next results…" style={{ width: '100%', marginTop: 8, resize: 'vertical' }} />
      <div className="small muted">{me() ? 'Saved to your account.' : 'Saved in this browser.'}</div>
    </div>
  )
}
