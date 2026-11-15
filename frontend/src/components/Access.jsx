import { useEffect, useRef, useState } from 'react'
import qrcode from 'qrcode-generator'
import { api } from '../util'

// ---------------------------------------------------------------- sign-in (only when EQL_PASSWORD is set)
export function Gate({ children }) {
  const [need, setNeed] = useState(null)
  useEffect(() => {
    api('/api/auth').then((a) => setNeed(a.required && !a.ok)).catch(() => setNeed(false))
    const on = () => setNeed(true)
    window.addEventListener('eql-login', on)
    return () => window.removeEventListener('eql-login', on)
  }, [])
  if (need === null) return null
  if (need) return <Login onDone={() => { setNeed(false); window.location.reload() }} />
  return children
}

function Login({ onDone }) {
  const [pw, setPw] = useState(''), [err, setErr] = useState(null), [busy, setBusy] = useState(false)
  const submit = async (e) => {
    e.preventDefault(); setBusy(true); setErr(null)
    try { await api('/api/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ password: pw }) }); onDone() } catch (er) { setErr(er.message) } finally { setBusy(false) }
  }
  return (
    <div className="login-wrap">
      <form className="card login" onSubmit={submit}>
        <img src="/icon.svg" alt="" width="56" height="56" />
        <h2 style={{ margin: '10px 0 2px' }}>Equity<span className="t-acc">Lens</span></h2>
        <div className="small muted" style={{ marginBottom: 16 }}>This EquityLens is password protected.</div>
        <input type="password" autoFocus autoComplete="current-password" placeholder="Password" value={pw} onChange={(e) => setPw(e.target.value)} />
        <button className="btn primary" disabled={!pw || busy} style={{ width: '100%', marginTop: 10 }}>{busy ? 'Checking…' : 'Sign in'}</button>
        {err && <div className="small t-bad" style={{ marginTop: 10 }}>⚠️ {err}</div>}
        <div className="small muted" style={{ marginTop: 14 }}>The password is <code>EQL_PASSWORD</code> in <code>backend/.env</code> on the computer or server running EquityLens. You stay signed in for 90 days.</div>
      </form>
    </div>
  )
}

// ---------------------------------------------------------------- QR code
export function QR({ text, size = 148 }) {
  const q = qrcode(0, 'M')
  q.addData(text); q.make()
  const svg = q.createSvgTag({ cellSize: 4, margin: 2, scalable: true })
  return <div className="qr" style={{ width: size, height: size }} dangerouslySetInnerHTML={{ __html: svg }} />
}

// ---------------------------------------------------------------- Settings → Use on your phone
export function PhoneCard() {
  const [n, setN] = useState(null)
  useEffect(() => { api('/api/network').then(setN).catch(() => setN(null)) }, [])
  if (!n) return null
  const here = window.location.origin
  const local = ['localhost', '127.0.0.1'].includes(window.location.hostname)
  const wifi = n.addresses.filter((a) => a.kind === 'wifi')
  const ts = n.addresses.filter((a) => a.kind === 'tailscale')
  const links = local ? [...wifi.slice(0, 2).map((a) => ({ ...a, label: '📶 Same Wi-Fi' })), ...ts.map((a) => ({ ...a, label: '🌐 Anywhere (Tailscale)' }))]
    : [{ url: here, label: n.cloud ? '☁️ This server' : '🔗 This address', kind: 'here' }]
  return (
    <div className="card">
      <h3>📱 Use on your phone</h3>
      {links.length ? (
        <div className="qr-row">
          {links.map((l) => (
            <div key={l.url} className="qr-item">
              <QR text={l.url} />
              <b className="small">{l.label}</b>
              <code className="small">{l.url}</code>
            </div>
          ))}
        </div>
      ) : <p className="small muted">No network address found. Connect this computer to Wi-Fi, or install Tailscale.</p>}
      <ol className="small brk-steps" style={{ marginTop: 10 }}>
        <li>Scan a code with the phone camera, or type the address in the phone's browser.</li>
        <li><b>Same Wi-Fi</b> works at home with no set-up. <b>Tailscale</b> (free app on the computer and the phone, same account) works from anywhere, on mobile data too.</li>
        <li>Make it an app: iPhone Safari → <b>Share → Add to Home Screen</b>. Android Chrome → <b>⋮ → Add to Home screen</b>.</li>
        <li>This computer must stay on with EquityLens running. To use it with the computer off, host it in the cloud (see the README guide).</li>
      </ol>
      {local && !n.password && <div className="small t-warn">🔒 Anyone on the same Wi-Fi can open it. For shared Wi-Fi (hostel, office) set <code>EQL_PASSWORD=…</code> in <code>backend/.env</code> and restart.</div>}
      {local && !n.listening_all && <div className="small t-warn">EQL_HOST is set to local-only, so phones can't connect. Remove EQL_HOST from backend/.env.</div>}
      {n.password && <div className="small muted">🔒 Password protection is on.</div>}
      <div className="small muted" style={{ marginTop: 6 }}>Windows may ask to allow Python on private networks the first time: choose <b>Allow</b>.</div>
    </div>
  )
}

// ---------------------------------------------------------------- Settings → Logs
export function LogsCard() {
  const [open, setOpen] = useState(false), [l, setL] = useState(null), [file, setFile] = useState('equitylens.log')
  const box = useRef(null)
  useEffect(() => { if (box.current) box.current.scrollTop = box.current.scrollHeight }, [l, file])
  const load = () => api('/api/logs?lines=300').then(setL).catch((e) => setL({ error: e.message }))
  useEffect(() => { if (open) load() }, [open])
  const names = l?.files ? Object.keys(l.files) : []
  return (
    <div className="card">
      <div className="row between"><h3 style={{ margin: 0 }}>🧾 Logs</h3><button className="btn small" onClick={() => setOpen(!open)}>{open ? 'Hide' : 'Show'}</button></div>
      <p className="small muted" style={{ marginBottom: 0 }}>EquityLens runs without a window, so its messages go to a log file. Look here if something doesn't load.</p>
      {open && l && (
        l.error ? <div className="small t-bad">⚠️ {l.error}</div> : <>
          <div className="row" style={{ gap: 6, margin: '10px 0' }}>
            {names.map((k) => <button key={k} className={`chip ${file === k ? 'on' : ''}`} onClick={() => setFile(k)}>{k}</button>)}
            <button className="btn small" onClick={load}>↻ Refresh</button>
          </div>
          <pre className="logbox" ref={box}>{l.files[file] || 'Empty.'}</pre>
          <div className="small muted">Folder: <code>{l.folder}</code></div>
        </>
      )}
    </div>
  )
}
