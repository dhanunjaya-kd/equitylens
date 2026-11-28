import { marked } from 'marked'
import { AccountsCard, LogsCard, PhoneCard } from '../components/Access'
import DataChecks from '../components/DataChecks'
import Automation from '../components/Automation'
import { sourcesShown, setSourcesShown } from '../util'
import TelegramCard from '../components/TelegramCard'
import { BreakingSoundCard } from '../components/BreakingBar'
import { useEffect, useRef, useState } from 'react'
import { Badge } from '../components/ui'
import { ago, api, go, me, streamSse } from '../util'

marked.setOptions({ gfm: true, breaks: true })
const esc = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
export const Md = ({ text }) => <div className="md" dangerouslySetInnerHTML={{ __html: marked.parse(esc(text || '')) }} />

const post = (path, body) => api(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) })

export function useAISettings() {
  const [s, setS] = useState(null)
  useEffect(() => { api('/api/ai/settings').then(setS).catch(() => setS({ ready: false })) }, [])
  return s
}

function ModelBar({ settings }) {
  if (!settings) return null
  const label = { claude: `Claude · ${settings.claude_model}`, openai: `OpenAI · ${settings.openai_model}`, gemini: `Gemini · ${settings.gemini_model}`, ollama: `Ollama · ${settings.ollama_model}`, demo: 'Demo (offline)' }[settings.provider]
  return (
    <div className="card row between" style={{ padding: '10px 14px' }}>
      <div className="small"><span className="muted">AI model:</span> <b>{label}</b> {settings.ready ? <span className="t-good">● ready</span> : <span className="t-bad">● needs a key</span>}</div>
      <button className="btn small" onClick={() => go('settings')}>⚙️ Settings</button>
    </div>
  )
}

function Busy({ text }) { return <div className="row small muted" style={{ padding: '10px 0' }}><div className="spinner" style={{ width: 18, height: 18, margin: 0, borderWidth: 2 }} />{text}</div> }
function Err({ e }) { return e ? <div className="small t-bad" style={{ marginTop: 8 }}>⚠️ {e}</div> : null }

// ====================================================================== stock AI tab
export function StockAI({ d }) {
  const settings = useAISettings()
  const sym = d.symbol
  return (
    <>
      <ModelBar settings={settings} />
      <Note sym={sym} />
      <Chat sym={sym} name={d.company.name} />
      <Guidance sym={sym} />
      <Debate sym={sym} />
      <DocReader d={d} />
      <p className="disclaimer">AI answers are generated from EquityLens's data for this stock and can still be wrong. Check important numbers in the Financials tab and the company's reports.</p>
    </>
  )
}

function Note({ sym }) {
  const [r, setR] = useState(null), [stream, setStream] = useState(''), [busy, setBusy] = useState(false), [err, setErr] = useState(null)
  const run = async (refresh) => {
    setBusy(true); setErr(null); setStream('')
    try {
      let acc = ''
      const res = await streamSse(`/api/ai/stream/note/${sym}${refresh ? '?refresh=1' : ''}`, { method: 'POST' }, (ev) => {
        if (ev.type === 'delta') { acc += ev.text; setStream(acc) }
      })
      if (res) setR(res)
    } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }
  return (
    <div className="card">
      <div className="row between"><h3 style={{ margin: 0 }}>🧠 AI research note</h3>
        <div className="row" style={{ gap: 8 }}>
          {busy && <span className="stream-badge">Streaming…</span>}
          {r ? <button className="btn small" disabled={busy} onClick={() => run(true)}>↻ Rewrite</button> : <button className="btn small primary" disabled={busy} onClick={() => run(false)}>Write note</button>}
        </div>
      </div>
      {!r && !busy && <p className="small muted" style={{ marginBottom: 0 }}>A full write-up: business quality, growth, balance sheet, forensics, valuation, 3/5/10-year view, risks and what to watch.</p>}
      {busy && !stream && <Busy text="Reading the whole report and streaming…" />}
      {busy && stream && <div className="streaming"><Md text={stream} /><span className="stream-cur" /></div>}
      <Err e={err} />
      {!busy && r && <><Md text={r.text} /><div className="small muted">{r.model} · {ago(r.created)}</div></>}
    </div>
  )
}

const SUGGEST = ['Is the debt a worry?', 'Why did margins change?', 'What could go wrong in 5 years?', 'Is it cheap or expensive vs history?', 'Explain the forensic scores simply']

function Chat({ sym, name }) {
  const [msgs, setMsgs] = useState([]), [stream, setStream] = useState(''), [q, setQ] = useState(''), [busy, setBusy] = useState(false), [err, setErr] = useState(null)
  const end = useRef()
  useEffect(() => { end.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }) }, [msgs, stream, busy])
  const ask = async (text) => {
    const t = (text ?? q).trim()
    if (!t || busy) return
    const next = [...msgs, { role: 'user', content: t }]
    setMsgs(next); setQ(''); setBusy(true); setErr(null); setStream('')
    try {
      let acc = ''
      const res = await streamSse(`/api/ai/stream/chat/${sym}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ messages: next }) }, (ev) => {
        if (ev.type === 'delta') { acc += ev.text; setStream(acc) }
      })
      setMsgs([...next, { role: 'assistant', content: res?.text || acc }])
    } catch (e) { setErr(e.message) } finally { setBusy(false); setStream('') }
  }
  return (
    <div className="card">
      <div className="row between"><h3 style={{ margin: 0 }}>💬 Ask about {name}</h3>
        <div className="row" style={{ gap: 8 }}>
          {busy && <span className="stream-badge">Live SSE</span>}
          {msgs.length > 0 && <button className="btn small" onClick={() => setMsgs([])}>Clear</button>}
        </div>
      </div>
      {msgs.length === 0 && <div style={{ marginTop: 10 }}>{SUGGEST.map((s) => <span key={s} className="chip" style={{ cursor: 'pointer' }} onClick={() => ask(s)}>{s}</span>)}</div>}
      <div style={{ marginTop: 8 }}>
        {msgs.map((m, i) => (
          <div key={i} className={`bubble ${m.role}`}>{m.role === 'assistant' ? <Md text={m.content} /> : m.content}</div>
        ))}
        {busy && (stream ? <div className="bubble assistant streaming"><Md text={stream} /><span className="stream-cur" /></div> : <Busy text="Thinking…" />)}
        <div ref={end} />
      </div>
      <Err e={err} />
      <div className="row" style={{ marginTop: 8 }}>
        <input className="grow" value={q} placeholder="Ask anything about this stock…" onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && ask()} />
        <button className="btn primary" disabled={busy || !q.trim()} onClick={() => ask()}>Ask</button>
      </div>
    </div>
  )
}

function Guidance({ sym }) {
  const [r, setR] = useState(null), [busy, setBusy] = useState(false), [err, setErr] = useState(null)
  const run = async (refresh) => { setBusy(true); setErr(null); try { setR(await post(`/api/ai/guidance/${sym}${refresh ? '?refresh=1' : ''}`)) } catch (e) { setErr(e.message) } finally { setBusy(false) } }
  return (
    <div className="card">
      <div className="row between"><h3 style={{ margin: 0 }}>🎯 Management guidance check</h3>
        {r ? <button className="btn small" disabled={busy} onClick={() => run(true)}>↻ Re-check</button> : <button className="btn small primary" disabled={busy} onClick={() => run(false)}>Check</button>}</div>
      {!r && !busy && <p className="small muted" style={{ marginBottom: 0 }}>Takes every target management has set (growth, margins, capacity, capex) and checks it against the company's own track record: achievable, stretch or unlikely.</p>}
      {busy && <Busy text="Comparing targets with the numbers…" />}
      <Err e={err} />
      {r && <><Md text={r.text} /><div className="small muted">{r.model} · {ago(r.created)}</div></>}
    </div>
  )
}

function Debate({ sym }) {
  const [r, setR] = useState(null), [parts, setParts] = useState({ bull: '', bear: '', judge: '' }), [busy, setBusy] = useState(false), [err, setErr] = useState(null)
  const run = async (refresh) => {
    setBusy(true); setErr(null); setParts({ bull: '', bear: '', judge: '' })
    try {
      const acc = { bull: '', bear: '', judge: '' }
      const res = await streamSse(`/api/ai/stream/debate/${sym}${refresh ? '?refresh=1' : ''}`, { method: 'POST' }, (ev) => {
        if (ev.type === 'part' && ev.role) { acc[ev.role] += ev.text; setParts({ ...acc }) }
      })
      if (res) setR(res)
    } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }
  const show = busy ? parts : r
  const tone = { Bull: 'good', Bear: 'bad', Balanced: 'warn' }[r?.leaning] || 'neutral'
  return (
    <div className="card">
      <div className="row between"><h3 style={{ margin: 0 }}>⚔️ Bull vs Bear debate</h3>
        <div className="row" style={{ gap: 8 }}>
          {busy && <span className="stream-badge">Streaming…</span>}
          {r ? <button className="btn small" disabled={busy} onClick={() => run(true)}>↻ Re-run</button> : <button className="btn small primary" disabled={busy} onClick={() => run(false)}>Start debate</button>}
        </div>
      </div>
      {!r && !busy && <p className="small muted" style={{ marginBottom: 0 }}>Three AI agents: one argues for, one against, and a judge checks both against the data.</p>}
      {busy && !parts.bull && <Busy text="Bull, bear and judge are starting…" />}
      <Err e={err} />
      {show && (show.bull || show.bear || show.judge) && (
        <>
          {show.bull && <div className="debate bull"><div className="dh t-good">🐂 Bull case</div><Md text={show.bull} /></div>}
          {show.bear && <div className="debate bear"><div className="dh t-bad">🐻 Bear case</div><Md text={show.bear} /></div>}
          {show.judge && <div className="debate judge"><div className="dh row between"><span>⚖️ Judge</span>{r?.leaning && <Badge tone={tone}>Leaning: {r.leaning}</Badge>}</div><Md text={show.judge} /></div>}
          {!busy && r && <div className="small muted">{r.model} · {ago(r.created)}</div>}
        </>
      )}
    </div>
  )
}

function DocReader({ d }) {
  const groups = (d.company.documents || []).filter((g) => /annual|concall|announce|rating/i.test(g.category))
  const [open, setOpen] = useState(null), [res, setRes] = useState({}), [busy, setBusy] = useState(null), [err, setErr] = useState(null)
  const read = async (url, title) => {
    setOpen(url); if (res[url]) return
    setBusy(url); setErr(null)
    try { const r = await post(`/api/ai/doc/${d.symbol}`, { url, title }); setRes((x) => ({ ...x, [url]: r })) }
    catch (e) { setErr(e.message) } finally { setBusy(null) }
  }
  const items = []
  groups.forEach((g) => g.items.slice(0, /announce/i.test(g.category) ? 4 : 3).forEach((it) => {
    if (it.url) items.push({ cat: g.category, title: it.title, sub: it.sub, url: it.url })
    ;(it.links || []).filter((l) => /transcript|ppt|presentation|notes/i.test(l.label)).forEach((l) => items.push({ cat: g.category, title: `${it.title} · ${l.label}`, url: l.url }))
  }))
  return (
    <div className="card">
      <h3>📄 AI document reader</h3>
      <p className="small muted" style={{ marginTop: -4 }}>Reads annual reports and concall transcripts and pulls out guidance, capex, risks and tone. Long reports take a minute.</p>
      {items.length === 0 && <div className="small muted">No documents found for this stock.</div>}
      <ul className="list">
        {items.slice(0, 12).map((it) => (
          <li key={it.url}>
            <span className="ic" style={{ color: 'var(--accent)' }}>›</span>
            <div className="row between" style={{ alignItems: 'flex-start' }}>
              <div className="grow"><b>{it.title}</b><div className="small muted">{it.cat}{it.sub ? ` · ${it.sub}` : ''}</div></div>
              <button className="btn small" disabled={busy === it.url} onClick={() => (open === it.url && res[it.url] ? setOpen(null) : read(it.url, it.title))}>
                {busy === it.url ? 'Reading…' : res[it.url] ? (open === it.url ? 'Hide' : 'Show') : '✨ Summarise'}</button>
            </div>
            {busy === it.url && <Busy text="Downloading and reading the document…" />}
            {open === it.url && res[it.url] && <div style={{ marginTop: 8 }}><Md text={res[it.url].text} /><div className="small muted">{res[it.url].pages} pages · {res[it.url].model}</div></div>}
          </li>
        ))}
      </ul>
      <Err e={err} />
    </div>
  )
}

// ====================================================================== explain a list
export function ExplainList({ symbols, title }) {
  const [r, setR] = useState(null), [busy, setBusy] = useState(false), [err, setErr] = useState(null)
  const run = async () => { setBusy(true); setErr(null); try { setR(await post('/api/ai/picks', { symbols: symbols.slice(0, 15), title })) } catch (e) { setErr(e.message) } finally { setBusy(false) } }
  if (!symbols.length) return null
  return (
    <div className="card">
      <div className="row between"><div><h3 style={{ margin: 0 }}>✨ Explain this list with AI</h3><div className="small muted">Top {Math.min(symbols.length, 15)} stocks: why each ranks, what they share, what to check.</div></div>
        <button className="btn small primary" disabled={busy} onClick={run}>{r ? '↻ Again' : 'Explain'}</button></div>
      {busy && <Busy text="Analysing the list…" />}
      <Err e={err} />
      {r && <><Md text={r.text} /><div className="small muted">{r.model}</div></>}
    </div>
  )
}

// ====================================================================== settings page
function SourcesCard() {
  const [on, setOn] = useState(sourcesShown())
  return (
    <div className="card">
      <div className="row between" style={{ gap: 12 }}>
        <div>
          <h3 style={{ margin: 0 }}>📎 Data sources</h3>
          <div className="small muted" style={{ marginTop: 4 }}>Show where each figure comes from (the "Source" lines and notes at the end of pages and sections). Off: they are hidden everywhere in the app on this device. The numbers and their checks are the same either way.</div>
        </div>
        <label className="row" style={{ gap: 8, cursor: 'pointer', whiteSpace: 'nowrap' }}>
          <input type="checkbox" checked={on} onChange={(e) => { setOn(e.target.checked); setSourcesShown(e.target.checked) }} /> {on ? 'Shown' : 'Hidden'}
        </label>
      </div>
    </div>
  )
}

function SecurityVaultCard() {
  const [sec, setSec] = useState(null)
  useEffect(() => { api('/api/security/status').then(setSec).catch(() => {}) }, [])
  if (!sec) return null
  return (
    <div className="card">
      <h3 style={{ marginTop: 0 }}>🔐 Security &amp; Sync Vault</h3>
      <div className="vault-pills">
        {sec.vault_encrypted && <span className="badge sm t-good bg-good">API &amp; Broker Keys Encrypted</span>}
        {sec.strict_cors && <span className="badge sm t-good bg-good">Strict CORS Active</span>}
        <span className="badge sm t-good bg-good">Syncing {sec.sync_keys?.length || 9} Lists &amp; Drawings</span>
        <span className="badge sm t-ok bg-ok">Auth: {sec.auth_mode}</span>
      </div>
      <div className="small muted" style={{ marginTop: 8 }}>Stored secrets (AI keys, Telegram bot token, broker keys/tokens) are encrypted at rest with a local vault key.</div>
    </div>
  )
}

export function Settings() {
  const [s, setS] = useState(null), [saved, setSaved] = useState(false), [test, setTest] = useState(null), [busy, setBusy] = useState(false)
  const [gm, setGm] = useState(null), [gmErr, setGmErr] = useState(null)
  useEffect(() => { api('/api/ai/settings').then(setS) }, [])
  if (!s) return <div className="empty">Loading…</div>
  const set = (k, v) => { setS({ ...s, [k]: v }); setSaved(false) }
  const saveIt = async () => { setS(await post('/api/ai/settings', s)); setSaved(true) }
  const testIt = async () => { setBusy(true); setTest(null); try { await saveIt(); setTest(await post('/api/ai/test')) } catch (e) { setTest({ error: e.message }) } finally { setBusy(false) } }
  const P = [['claude', 'Claude', 'Anthropic · best for long reports'], ['openai', 'ChatGPT', 'OpenAI'], ['gemini', 'Gemini', 'Google · has a free tier'], ['ollama', 'Ollama', 'Free · runs on your laptop'], ['demo', 'Demo', 'Offline sample answers']]
  return (
    <>
      <SourcesCard />
      <div className="card">
        <h3>⚙️ AI settings</h3>
        <div className="grid2">
          {P.map(([k, l, sub]) => (
            <div key={k} className="tile" style={{ cursor: 'pointer', borderColor: s.provider === k ? 'var(--accent)' : null }} onClick={() => set('provider', k)}>
              <b style={{ color: s.provider === k ? 'var(--accent)' : null }}>{s.provider === k ? '● ' : ''}{l}</b><div className="small muted">{sub}</div>
            </div>
          ))}
        </div>
      </div>
      {s.provider === 'claude' && (
        <div className="card">
          <h3>Claude (Anthropic)</h3>
          <label className="small muted">API key</label>
          <input style={{ width: '100%', margin: '4px 0 10px' }} type="password" placeholder="sk-ant-…" value={s.anthropic_api_key} onChange={(e) => set('anthropic_api_key', e.target.value)} />
          <label className="small muted">Model</label>
          <select style={{ width: '100%', marginTop: 4 }} value={s.claude_model} onChange={(e) => set('claude_model', e.target.value)}>
            <option value="claude-sonnet-5-5">Claude Sonnet 5.5 — balanced (recommended)</option>
            <option value="claude-opus-5-5">Claude Opus 5.5 — deepest analysis, costs more</option>
            <option value="claude-haiku-5-5">Claude Haiku 5.5 — fastest, cheapest</option>
          </select>
          <p className="small muted" style={{ marginBottom: 0 }}>Get a key at console.anthropic.com → API keys. Billed per use.</p>
        </div>
      )}
      {s.provider === 'openai' && (
        <div className="card">
          <h3>ChatGPT (OpenAI)</h3>
          <label className="small muted">API key</label>
          <input style={{ width: '100%', margin: '4px 0 10px' }} type="password" placeholder="sk-…" value={s.openai_api_key} onChange={(e) => set('openai_api_key', e.target.value)} />
          <label className="small muted">Model name</label>
          <input style={{ width: '100%', marginTop: 4 }} value={s.openai_model} onChange={(e) => set('openai_model', e.target.value)} />
          <p className="small muted" style={{ marginBottom: 0 }}>Get a key at platform.openai.com → API keys. Billed per use. Any chat model name from your account works here.</p>
        </div>
      )}
      {s.provider === 'gemini' && (
        <div className="card">
          <h3>Gemini (Google)</h3>
          <label className="small muted">API key</label>
          <input style={{ width: '100%', margin: '4px 0 10px' }} type="password" placeholder="AIza…" value={s.gemini_api_key} onChange={(e) => set('gemini_api_key', e.target.value)} />
          <label className="small muted">Model</label>
          <div className="row" style={{ marginTop: 4 }}>
            {gm?.length ? (
              <select className="grow" value={s.gemini_model} onChange={(e) => set('gemini_model', e.target.value)}>
                {!gm.includes(s.gemini_model) && <option value={s.gemini_model}>{s.gemini_model}</option>}
                {gm.map((m) => <option key={m} value={m}>{m}</option>)}
              </select>
            ) : <input className="grow" value={s.gemini_model} onChange={(e) => set('gemini_model', e.target.value)} />}
            <button className="btn small" onClick={async () => {
              setGmErr(null)
              try { await saveIt(); setGm((await api('/api/ai/gemini-models')).models) } catch (e) { setGmErr(e.message) }
            }}>Load my models</button>
          </div>
          {gmErr && <div className="small t-bad" style={{ marginTop: 6 }}>⚠️ {gmErr}</div>}
          <p className="small muted" style={{ marginBottom: 0 }}>Get a free key at aistudio.google.com → Get API key. The free tier has daily limits; paid use is billed per use. Tap "Load my models" to pick from the models your key can use.</p>
        </div>
      )}
      {s.provider === 'ollama' && (
        <div className="card">
          <h3>Ollama (free, local)</h3>
          <label className="small muted">Ollama address</label>
          <input style={{ width: '100%', margin: '4px 0 10px' }} value={s.ollama_url} onChange={(e) => set('ollama_url', e.target.value)} />
          <label className="small muted">Model</label>
          <input style={{ width: '100%', marginTop: 4 }} value={s.ollama_model} onChange={(e) => set('ollama_model', e.target.value)} />
          <p className="small muted" style={{ marginBottom: 0 }}>Install from ollama.com, run <code>ollama pull {s.ollama_model}</code>, keep Ollama running. Slower and less sharp than Claude/ChatGPT, but costs nothing.</p>
        </div>
      )}
      <div className="card">
        <div className="row" style={{ gap: 8 }}>
          <button className="btn primary" onClick={saveIt}>Save</button>
          <button className="btn" disabled={busy} onClick={testIt}>{busy ? 'Testing…' : 'Save & test connection'}</button>
          {saved && <span className="small t-good">Saved ✓</span>}
        </div>
        {test && (test.error ? <div className="small t-bad" style={{ marginTop: 8 }}>⚠️ {test.error}</div>
          : <div className="small t-good" style={{ marginTop: 8 }}>✓ {test.model} replied "{test.reply}" in {test.seconds}s</div>)}
        <p className="small muted" style={{ marginBottom: 0 }}>Keys are stored only on your laptop (backend/data/ai_settings.json, not in Git) and shown masked here.</p>
      </div>
      <AccountsCard />
      <BreakingSoundCard />
      {(!me() || me().role === 'owner') && <><SecurityVaultCard /><Automation /><TelegramCard /><DataChecks /><PhoneCard /><LogsCard /></>}
    </>
  )
}
