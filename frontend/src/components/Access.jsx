import { useEffect, useRef, useState } from 'react'
import qrcode from 'qrcode-generator'
import { ago, api, loadAccountData } from '../util'

// ---------------------------------------------------------------- sign-in
// Accounts on: every person signs in (GitHub or email + password). Before that: the old EQL_PASSWORD screen, if set.
export function Gate({ children }) {
  const [a, setA] = useState(null)
  const check = () => api('/api/auth')
    .then(async (x) => { if (x.accounts && x.user) { try { await loadAccountData(x.user) } catch { /* lists stay as they are */ } } setA(x) })
    .catch(() => setA({ ok: true }))
  useEffect(() => {
    check()
    window.addEventListener('eql-login', check)
    return () => window.removeEventListener('eql-login', check)
  }, [])
  if (!a) return null
  if (a.accounts && !a.ok) return <SignIn github={a.github} />
  if (!a.accounts && a.required && !a.ok) return <Login onDone={() => window.location.reload()} />
  return children
}

const postJSON = (path, body) => api(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) })
const GitHubIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M9 19c-4.3 1.4-4.3-2.5-6-3m12 5v-3.5c0-1 .1-1.4-.5-2 2.8-.3 5.5-1.4 5.5-6a4.6 4.6 0 0 0-1.3-3.2 4.2 4.2 0 0 0-.1-3.2s-1.1-.3-3.5 1.3a12.3 12.3 0 0 0-6.2 0C6.5 2.8 5.4 3.1 5.4 3.1a4.2 4.2 0 0 0-.1 3.2A4.6 4.6 0 0 0 4 9.5c0 4.6 2.7 5.7 5.5 6-.6.6-.6 1.2-.5 2V21" /></svg>
)

export function SignIn({ github }) {
  const hashErr = (() => { try { return new URLSearchParams(window.location.hash.split('?')[1] || '').get('error') } catch { return null } })()
  const [mode, setMode] = useState('in'), [email, setEmail] = useState(''), [name, setName] = useState(''), [pw, setPw] = useState('')
  const [err, setErr] = useState(hashErr), [busy, setBusy] = useState(false)
  const submit = async (e) => {
    e.preventDefault(); setBusy(true); setErr(null)
    try {
      await postJSON(mode === 'in' ? '/api/auth/login' : '/api/auth/register', { email, password: pw, name })
      window.location.hash = '#/'; window.location.reload()
    } catch (er) { setErr(er.message) } finally { setBusy(false) }
  }
  return (
    <div className="login-wrap">
      <form className="card login signin" onSubmit={submit}>
        <img src="/icon.svg" alt="" width="52" height="52" />
        <h2 style={{ margin: '10px 0 2px' }}>{mode === 'in' ? 'Sign in' : 'Create your account'}</h2>
        <div className="small muted" style={{ marginBottom: 16, lineHeight: 1.5 }}>Your watchlist, saved screens, notes and chart layouts follow you to every device.</div>
        {github && (
          <>
            <a className="btn gh-btn" href="/api/auth/github/start"><GitHubIcon /> Continue with GitHub</a>
            <div className="or-line small muted"><span />or with your email<span /></div>
          </>
        )}
        {mode === 'up' && (
          <label className="small muted field">Name
            <input autoComplete="name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Your name" />
          </label>
        )}
        <label className="small muted field">Email
          <input type="email" required autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" />
        </label>
        <label className="small muted field">Password
          <input type="password" required minLength={mode === 'up' ? 10 : undefined} autoComplete={mode === 'in' ? 'current-password' : 'new-password'}
            value={pw} onChange={(e) => setPw(e.target.value)} placeholder={mode === 'up' ? 'At least 10 characters' : ''} />
        </label>
        <button className="btn primary" disabled={!email || !pw || busy} style={{ width: '100%', marginTop: 12, height: 46 }}>
          {busy ? 'Please wait…' : mode === 'in' ? 'Sign in' : 'Create account'}
        </button>
        {err && <div role="alert" className="small t-bad" style={{ marginTop: 10, lineHeight: 1.45 }}>⚠️ {err}</div>}
        <div className="small" style={{ marginTop: 14 }}>
          {mode === 'in'
            ? <>Invited by the owner? <button type="button" className="linkish" onClick={() => { setMode('up'); setErr(null) }}>Create account</button></>
            : <>Have an account? <button type="button" className="linkish" onClick={() => { setMode('in'); setErr(null) }}>Sign in</button></>}
        </div>
        <div className="small muted" style={{ marginTop: 14, lineHeight: 1.5 }}>This EquityLens is invite-only. Passwords are stored only as a salted hash on its server. GitHub shares your username and email, nothing else.</div>
      </form>
    </div>
  )
}

// ---------------------------------------------------------------- Settings → Accounts (turn on sign-in, invite people, GitHub)
export function AccountsCard() {
  const [a, setA] = useState(null)
  useEffect(() => { api('/api/auth').then(setA).catch(() => {}) }, [])
  if (!a) return null
  if (!a.accounts) return <SetupCard can={a.can_setup} />
  if (a.user?.role !== 'owner') return null
  return <><PeopleCard /><GitHubCard /></>
}

function SetupCard({ can }) {
  const [f, setF] = useState({ name: '', email: '', password: '', again: '' }), [err, setErr] = useState(null), [busy, setBusy] = useState(false)
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })
  const go2 = async (e) => {
    e.preventDefault()
    if (f.password !== f.again) return setErr('The two passwords are different.')
    setBusy(true); setErr(null)
    try { await postJSON('/api/auth/setup', f); window.location.hash = '#/account'; window.location.reload() } catch (x) { setErr(x.message) } finally { setBusy(false) }
  }
  return (
    <div className="card">
      <h3>👤 Accounts and sign-in</h3>
      <p className="small muted" style={{ lineHeight: 1.5, marginTop: 0 }}>Sign-in is off: anyone who can open this EquityLens uses the same lists. Turn it on to give each person their own watchlist, screens, notes and AI key, and to invite people by email or GitHub username. You become the owner.</p>
      {!can && <p className="small t-warn">Turn sign-in on from the computer that runs EquityLens.</p>}
      {can && (
        <form onSubmit={go2} className="grid2">
          <label className="small muted field">Your name<input value={f.name} onChange={set('name')} autoComplete="name" /></label>
          <label className="small muted field">Email<input type="email" required value={f.email} onChange={set('email')} autoComplete="email" /></label>
          <label className="small muted field">Password (10+ characters)<input type="password" required minLength={10} value={f.password} onChange={set('password')} autoComplete="new-password" /></label>
          <label className="small muted field">Password again<input type="password" required value={f.again} onChange={set('again')} autoComplete="new-password" /></label>
          <div style={{ gridColumn: '1 / -1' }}>
            <button className="btn primary" disabled={busy}>{busy ? 'Turning on…' : 'Turn on sign-in and create my owner account'}</button>
            {err && <div className="small t-bad" style={{ marginTop: 8 }}>⚠️ {err}</div>}
            <div className="small muted" style={{ marginTop: 8 }}>After this everyone, including you, signs in. The lists already in this browser can be added to your account in one tap.</div>
          </div>
        </form>
      )}
    </div>
  )
}

function PeopleCard() {
  const [p, setP] = useState(null), [who, setWho] = useState(''), [err, setErr] = useState(null)
  const load = () => api('/api/auth/people').then(setP).catch((x) => setErr(x.message))
  useEffect(() => { load() }, [])
  const add = async (e) => { e.preventDefault(); setErr(null); try { await postJSON('/api/auth/invites', { who }); setWho(''); load() } catch (x) { setErr(x.message) } }
  const del = async (path) => { try { await api(path, { method: 'DELETE' }); load() } catch (x) { setErr(x.message) } }
  return (
    <div className="card">
      <h3>👥 People</h3>
      <form onSubmit={add} className="row" style={{ gap: 8 }}>
        <input className="grow" aria-label="Invite by email or GitHub username" placeholder="Invite: friend@example.com or a GitHub username" value={who} onChange={(e) => setWho(e.target.value)} />
        <button className="btn primary" disabled={!who.trim()}>Invite</button>
      </form>
      <div className="small muted" style={{ marginTop: 6 }}>Invited people create their account on the sign-in screen (email) or with Continue with GitHub. Send them this EquityLens's address.</div>
      {err && <div className="small t-bad" style={{ marginTop: 6 }}>⚠️ {err}</div>}
      {p && (
        <>
          <h4>Accounts</h4>
          {p.users.map((u) => (
            <div key={u.id} className="row between" style={{ padding: '7px 0', borderTop: '1px solid var(--line)', gap: 8 }}>
              <span><b>{u.name}</b> <span className="small muted">{u.email || ''}{u.github ? ` · GitHub @${u.github}` : ''} · {u.role}{u.last_login ? ` · last in ${ago(u.last_login)}` : ''}</span></span>
              {u.role !== 'owner' && <button className="btn small" onClick={() => window.confirm(`Remove ${u.name}? Their saved lists are deleted.`) && del(`/api/auth/users/${u.id}`)}>Remove</button>}
            </div>
          ))}
          <h4>Invites</h4>
          {!p.invites.length && <div className="small muted">No invites yet.</div>}
          {p.invites.map((i) => (
            <div key={i.who} className="row between" style={{ padding: '7px 0', borderTop: '1px solid var(--line)', gap: 8 }}>
              <span>{i.kind === 'github' ? `GitHub @${i.who}` : i.who} <span className="small muted">· {i.used_by ? 'joined' : 'not joined yet'}</span></span>
              {!i.used_by && <button className="btn small" onClick={() => del(`/api/auth/invites/${encodeURIComponent(i.who)}`)}>Cancel</button>}
            </div>
          ))}
        </>
      )}
    </div>
  )
}

function GitHubCard() {
  const [g, setG] = useState(null), [msg, setMsg] = useState(null)
  useEffect(() => { api('/api/auth/github/config').then(setG).catch(() => {}) }, [])
  if (!g) return null
  const save = async () => { try { setG(await postJSON('/api/auth/github/config', g)); setMsg('Saved ✓') } catch (x) { setMsg(`⚠️ ${x.message}`) } }
  return (
    <div className="card">
      <h3>GitHub sign-in {g.enabled ? <span className="small t-good">· on</span> : <span className="small muted">· off</span>}</h3>
      <ol className="small" style={{ lineHeight: 1.6, paddingLeft: 18, marginTop: 0 }}>
        <li>On github.com: your photo → <b>Settings → Developer settings → OAuth Apps → New OAuth App</b>.</li>
        <li>Application name: <b>EquityLens</b>. Homepage URL: this EquityLens's address. <b>Authorization callback URL</b>: <code style={{ userSelect: 'all' }}>{g.callback_url}</code></li>
        <li>Register, then <b>Generate a new client secret</b>. Paste the Client ID and the secret below.</li>
      </ol>
      <div className="grid2">
        <label className="small muted field">Client ID<input value={g.client_id} onChange={(e) => setG({ ...g, client_id: e.target.value })} /></label>
        <label className="small muted field">Client secret<input type="password" value={g.client_secret} onChange={(e) => setG({ ...g, client_secret: e.target.value })} /></label>
      </div>
      <div className="row" style={{ gap: 8, marginTop: 10 }}><button className="btn primary" onClick={save}>Save</button>{msg && <span className="small">{msg}</span>}</div>
      <div className="small muted" style={{ marginTop: 8 }}>The callback URL must match exactly. Opening EquityLens on another address (cloud domain, Tailscale)? Use that address in the OAuth App.</div>
    </div>
  )
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
