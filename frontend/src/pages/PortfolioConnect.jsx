import { useEffect, useRef, useState } from 'react'
import { ago, api } from '../util'

const post = (url, body) => api(url, { method: 'POST', ...(body ? { body: JSON.stringify(body), headers: { 'Content-Type': 'application/json' } } : {}) })
const timeIST = (iso) => (iso ? new Date(iso).toLocaleString('en-IN', { weekday: 'short', hour: '2-digit', minute: '2-digit' }) : null)
const bold = (s) => ({ __html: String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/\*\*(.+?)\*\*/g, '<b>$1</b>') })

export function brokerState(b) {
  if (b.error) return ['warn', b.error.startsWith('Session expired') ? 'Reconnect needed' : 'Needs attention']
  if (b.connected && b.valid_until && new Date(b.valid_until) < new Date()) return ['warn', 'Reconnect needed today']
  if (b.connected) return ['good', 'Connected']
  if (b.configured) return ['ok', 'Ready to connect']
  return ['neutral', 'Not set up']
}

// A key box the browser cannot auto-fill (read-only until clicked, unique name, password managers told to skip it)
function KeyInput({ f, value, onChange }) {
  const [ro, setRo] = useState(true)
  const [nm] = useState(() => `eql-${f.key}-${Math.random().toString(36).slice(2, 7)}`)
  return (
    <label className="small pc-field">{f.label}
      <input type={f.secret ? 'password' : 'text'} name={nm} autoComplete={f.secret ? 'new-password' : 'off'}
        data-lpignore="true" data-1p-ignore="true" readOnly={ro} onFocus={() => setRo(false)} spellCheck={false}
        placeholder={f.set ? `saved: ${f.value}` : 'paste it here'} value={value ?? ''} onChange={(e) => onChange(e.target.value)} />
    </label>
  )
}

function Setup({ b, onChange }) {
  const [vals, setVals] = useState({}), [busy, setBusy] = useState(''), [msg, setMsg] = useState(null), [chk, setChk] = useState(null)
  const [paste, setPaste] = useState(false), [url, setUrl] = useState(''), [copied, setCopied] = useState(false)
  useEffect(() => { setVals({}); setMsg(null); setChk(null); setPaste(false) }, [b.id])
  const filled = Object.values(vals).some((v) => v)
  const save = async () => { await post(`/api/brokers/${b.id}/config`, vals); setVals({}); onChange() }
  const run = async (what, fn) => { setBusy(what); setMsg(null); try { await fn() } catch (e) { setMsg({ err: e.message }) } finally { setBusy('') } }
  const saveOnly = () => run('save', async () => { await save(); setMsg({ ok: 'Keys saved on this computer.' }) })
  const check = () => run('check', async () => { if (filled) await save(); setChk(await post(`/api/brokers/${b.id}/check`)) })
  const connect = () => run('connect', async () => {
    if (filled) await save()
    const r = await post(`/api/brokers/${b.id}/connect`)
    if (r.url) { if (b.auth === 'paste') { window.open(r.url, '_blank'); setPaste(true) } else window.location.href = r.url } else { setMsg({ ok: `Connected · ${r.holdings} holdings imported.` }); onChange() }
  })
  const sendPaste = () => run('paste', async () => { const r = await post('/api/brokers/schwab/paste', { url }); setPaste(false); setMsg({ ok: `Connected · ${r.holdings} holdings imported.` }); onChange() })
  const copy = () => { navigator.clipboard?.writeText(b.redirect_uri).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500) }) }
  const keysStep = b.redirect_uri ? 3 : 2
  return (
    <div className="pc-setup">
      <div className="row between wrapflex" style={{ gap: 6 }}>
        <div><b style={{ fontSize: 16 }}>Set up {b.name}</b> <span className="small muted">· once · then {b.expires}</span></div>
        <span className="small muted">🔒 Read-only: EquityLens can never place orders</span>
      </div>
      <div className="pc-steps">
        <div className="pc-step"><div className="pc-n">1</div><b>Create an app at {b.name}</b>
          <ol className="small">{b.steps.slice(0, b.redirect_uri ? -2 : -1).map((s) => <li key={s} dangerouslySetInnerHTML={bold(s)} />)}</ol>
          <a className="btn small" href={b.site} target="_blank" rel="noreferrer">Open {b.site.replace('https://', '')} ↗</a></div>
        {b.redirect_uri && (
          <div className="pc-step"><div className="pc-n">2</div><b>Paste this redirect URL in that app</b>
            <code className="pc-url">{b.redirect_uri}</code>
            <button className="btn small" onClick={copy}>{copied ? 'Copied ✓' : 'Copy'}</button>
            <div className="small muted" style={{ marginTop: 6 }}>Open EquityLens at this same address when you press Connect.</div></div>
        )}
        <div className="pc-step"><div className="pc-n">{keysStep}</div><b>Enter your keys</b>
          {b.fields.map((f) => <KeyInput key={f.key} f={f} value={vals[f.key]} onChange={(v) => setVals({ ...vals, [f.key]: v })} />)}
          <div className="row wrapflex" style={{ gap: 6 }}>
            <button className="btn small" disabled={!filled || !!busy} onClick={saveOnly}>{busy === 'save' ? 'Saving…' : 'Save keys'}</button>
            <button className="btn small" disabled={!!busy || (!filled && !b.configured)} onClick={check}>{busy === 'check' ? 'Checking…' : '✓ Check keys'}</button>
          </div></div>
        <div className="pc-step"><div className="pc-n">{keysStep + 1}</div><b>Connect</b>
          <div className="small muted">{b.auth === 'oauth' ? `You sign in at ${b.name} and come straight back here; holdings are imported.` : b.auth === 'paste' ? 'You sign in at Schwab, then paste back the address of the page you land on.' : 'EquityLens asks for your holdings with these keys.'}</div>
          <button className="btn primary" disabled={!!busy || (!filled && !b.configured)} onClick={connect} style={{ marginTop: 8 }}>{busy === 'connect' ? 'Connecting…' : b.connected ? '↻ Reconnect' : '🔗 Save and connect'}</button></div>
      </div>
      {chk && (
        <div className="pc-check">
          {chk.checks.map((c) => <div key={c.what} className="small"><span style={{ color: c.ok === false ? 'var(--bad)' : c.ok ? 'var(--good)' : 'var(--muted)' }}>{c.ok === false ? '✗' : c.ok ? '✓' : 'ℹ'}</span> <b>{c.what}:</b> {c.msg}</div>)}
        </div>
      )}
      {paste && (
        <div className="pc-check">
          <div className="small">After signing in to Schwab you land on a page that doesn't load. Copy that page's full address and paste it here:</div>
          <div className="row" style={{ gap: 6, marginTop: 6 }}><input className="grow" placeholder="https://127.0.0.1/?code=…" value={url} onChange={(e) => setUrl(e.target.value)} />
            <button className="btn small primary" disabled={!url || !!busy} onClick={sendPaste}>Finish connecting</button></div>
        </div>
      )}
      {msg && <div className={`small ${msg.err ? 't-bad' : 't-good'}`} style={{ marginTop: 8 }}>{msg.err ? '⚠️ ' : '✓ '}{msg.err || msg.ok}</div>}
    </div>
  )
}

function Upload({ mk, file, onChange }) {
  const [drag, setDrag] = useState(false), [busy, setBusy] = useState(false), [pv, setPv] = useState(null), [msg, setMsg] = useState(null)
  const raw = useRef(null)
  const read = (f) => {
    if (!f) return
    setBusy(true); setMsg(null); setPv(null)
    const rd = new FileReader()
    rd.onload = async () => {
      raw.current = { filename: f.name, market: mk, data: String(rd.result).split(',')[1] }
      try { setPv(await post('/api/portfolio/upload?preview=1', raw.current)) } catch (e) { setMsg({ err: e.message }) } finally { setBusy(false) }
    }
    rd.readAsDataURL(f)
  }
  const doImport = async () => { setBusy(true); try { const r = await post('/api/portfolio/upload', raw.current); setPv(null); setMsg({ ok: `${r.holdings} holdings imported from ${r.file}.` }); onChange() } catch (e) { setMsg({ err: e.message }) } finally { setBusy(false) } }
  return (
    <div className="pc-setup">
      <b style={{ fontSize: 16 }}>Upload a holdings file</b> <span className="small muted">· any broker · CSV or Excel · no keys needed</span>
      <label className={`pc-drop ${drag ? 'on' : ''}`} onDragOver={(e) => { e.preventDefault(); setDrag(true) }} onDragLeave={() => setDrag(false)}
        onDrop={(e) => { e.preventDefault(); setDrag(false); read(e.dataTransfer.files?.[0]) }}>
        <input type="file" accept=".csv,.xlsx,.xlsm" hidden onChange={(e) => { read(e.target.files?.[0]); e.target.value = '' }} />
        <div style={{ fontSize: 28 }}>📄</div>
        <b>{busy ? 'Reading…' : 'Drop the file here, or click to choose'}</b>
        <div className="small muted">{mk === 'US' ? 'Export from Robinhood, Fidelity, IBKR, Schwab…' : 'Export from Groww, Zerodha Console, Kotak, ICICI Direct, HDFC Securities…'} It needs a symbol (or ISIN) and a quantity column.</div>
      </label>
      {pv && (
        <div className="pc-check">
          <div className="small"><b>{pv.file}</b>: {pv.count} holdings found (header on row {pv.header_row}). Columns read: {Object.entries(pv.columns).filter(([, v]) => v).map(([k, v]) => `${k} = “${v}”`).join(' · ')}</div>
          <div className="tbl-wrap" style={{ marginTop: 6 }}><table className="tbl"><thead><tr><th style={{ textAlign: 'left' }}>Symbol</th><th>Qty</th><th>Avg</th><th>LTP</th></tr></thead>
            <tbody>{pv.sample.map((h) => <tr key={h.symbol}><td style={{ textAlign: 'left' }}>{h.symbol.replace('US:', '')}</td><td>{h.qty}</td><td>{h.avg ?? '—'}</td><td>{h.ltp ?? '—'}</td></tr>)}</tbody></table></div>
          {pv.count > pv.sample.length && <div className="small muted">…and {pv.count - pv.sample.length} more.</div>}
          <div className="row" style={{ gap: 6, marginTop: 8 }}><button className="btn primary small" disabled={busy} onClick={doImport}>Import {pv.count} holdings</button><button className="btn small" onClick={() => setPv(null)}>Cancel</button></div>
        </div>
      )}
      {file?.holdings > 0 && !pv && <div className="small muted" style={{ marginTop: 8 }}>Imported now: {file.holdings} holdings from {file.file} · {ago(file.last_sync)} <button className="btn small" onClick={async () => { await api('/api/brokers/file', { method: 'DELETE' }); onChange() }}>Remove</button></div>}
      {msg && <div className={`small ${msg.err ? 't-bad' : 't-good'}`} style={{ marginTop: 8 }}>{msg.err ? '⚠️ ' : '✓ '}{msg.err || msg.ok}</div>}
    </div>
  )
}

// Slim bar per connection once something is connected: last sync, how long the login stays valid, Sync / Reconnect.
function Health({ list, file, onChange, onSetup }) {
  const [busy, setBusy] = useState('')
  const sync = async (id) => { setBusy(id); try { await post(`/api/brokers/${id}/sync`) } catch { /* shown on the row */ } setBusy(''); onChange() }
  const reconnect = async (b) => { setBusy(b.id); try { const r = await post(`/api/brokers/${b.id}/connect`); if (r.url) { window.location.href = r.url; return } } catch { /* shown */ } setBusy(''); onChange() }
  return (
    <div className="pc-health">
      {list.map((b) => {
        const [tone, label] = brokerState(b)
        const until = b.valid_until ? (new Date(b.valid_until) > new Date() ? `login valid until ${timeIST(b.valid_until)}` : 'login ended') : b.token_time ? `logged in ${ago(b.token_time)} · ${b.expires}` : b.expires
        return (
          <div key={b.id} className="pc-hrow">
            <span className={`pc-dot t-${tone}`} />
            <b>{b.name}</b>
            <span className={`badge sm t-${tone} bg-${tone}`}>{label}</span>
            <span className="small muted grow">{b.holdings} holdings · synced {b.last_sync ? ago(b.last_sync) : '—'} · {until}{b.valid_rule ? ` (${b.valid_rule})` : ''}</span>
            {b.error && <span className="small t-warn">{b.error}</span>}
            <button className="btn small" disabled={busy === b.id} onClick={() => sync(b.id)}>{busy === b.id ? '…' : 'Sync'}</button>
            <button className="btn small" disabled={busy === b.id} onClick={() => reconnect(b)}>Reconnect</button>
            <button className="btn small" onClick={() => onSetup(b.id)}>Keys</button>
          </div>
        )
      })}
      {file?.holdings > 0 && (
        <div className="pc-hrow"><span className="pc-dot t-good" /><b>File</b><span className="badge sm t-good bg-good">Imported</span>
          <span className="small muted grow">{file.holdings} holdings from {file.file} · {ago(file.last_sync)}</span>
          <button className="btn small" onClick={() => onSetup('file')}>Replace</button></div>
      )}
    </div>
  )
}

export default function PortfolioConnect({ brokers, keys, mk, onChange }) {
  const mine = (brokers || []).filter((k) => k.market === mk)
  const file = (brokers || []).find((k) => k.id === 'file')
  const live = mine.filter((k) => k.connected || k.holdings > 0 || k.error)
  const any = live.length > 0 || file?.holdings > 0
  const [open, setOpen] = useState(!any)
  const [mode, setMode] = useState('broker')
  const [sel, setSel] = useState(null)
  useEffect(() => { if (!any) setOpen(true) }, [any])
  const pick = (id) => { setOpen(true); if (id === 'file') setMode('file'); else { setMode('broker'); setSel(id) } }
  const cur = mine.find((k) => k.id === sel) || mine[0]
  return (
    <div className="card pc">
      <div className="row between wrapflex" style={{ gap: 8 }}>
        <h3 style={{ margin: 0 }}>🔗 Your connections</h3>
        {any && <button className="btn small" onClick={() => setOpen(!open)}>{open ? 'Close' : '+ Add a broker or file'}</button>}
      </div>
      {any && <Health list={live} file={file} onChange={onChange} onSetup={pick} />}
      {open && (
        <>
          <div className="pc-choice">
            <button className={mode === 'broker' ? 'on' : ''} onClick={() => setMode('broker')}><b>🔌 Connect a broker</b><span className="small muted">Live and read-only; Sync updates it</span></button>
            <button className={mode === 'file' ? 'on' : ''} onClick={() => setMode('file')}><b>📄 Upload a holdings file</b><span className="small muted">Any broker · CSV or Excel · no keys</span></button>
          </div>
          {mode === 'broker' && (
            <>
              <div className="pc-tiles">
                {mine.map((b) => {
                  const [tone, label] = brokerState(b)
                  return <button key={b.id} className={cur?.id === b.id ? 'on' : ''} onClick={() => setSel(b.id)}><b>{b.name}</b><span className={`badge sm t-${tone} bg-${tone}`}>{label}</span></button>
                })}
              </div>
              {cur && <Setup b={cur} onChange={onChange} />}
            </>
          )}
          {mode === 'file' && <Upload mk={mk} file={file} onChange={onChange} />}
        </>
      )}
      <details className="pc-privacy">
        <summary className="small">🔒 Where your keys are kept</summary>
        <div className="small muted" style={{ marginTop: 6 }}>
          Only on this laptop, in <code>{keys?.file || 'backend/data/brokers.json'}</code>, {keys?.encrypted ? 'encrypted, ' : ''}and never in git.
          EquityLens only reads holdings; it cannot place orders or move money.
        </div>
        <div className="row wrapflex" style={{ gap: 6, marginTop: 8 }}>
          {mine.filter((b) => b.configured || b.holdings > 0).map((b) => (
            <button key={b.id} className="btn small" onClick={async () => { if (!window.confirm(`Remove ${b.name}? Its saved keys and holdings are deleted from this computer.`)) return; await api(`/api/brokers/${b.id}`, { method: 'DELETE' }); onChange() }}>Remove {b.name} keys</button>
          ))}
        </div>
      </details>
    </div>
  )
}
