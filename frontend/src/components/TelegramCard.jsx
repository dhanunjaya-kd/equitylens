import { useEffect, useState } from 'react'
import { ago, api } from '../util'

const post = (path, body) => api(path, { method: 'POST', body: JSON.stringify(body || {}), headers: { 'Content-Type': 'application/json' } })
const OPTS = [['breaking', '🔴 Breaking market news', 'Serious market-wide events that at least two publishers report, central-bank emergencies, and NIFTY / SENSEX / S&P 500 / Nasdaq moving 2% or more in a day'],
  ['filings', '📄 Filings of my watchlist stocks', 'Results, orders and deals, corporate actions and top-management changes of the stocks in your watchlists'],
  ['central', '🏛 RBI and Fed releases', 'Policy, rates, liquidity and market operations'],
  ['top', '📰 Top stories', 'Stories covered by three or more publishers (more messages)']]

export default function TelegramCard() {
  const [s, setS] = useState(null), [token, setToken] = useState(''), [msg, setMsg] = useState(null), [busy, setBusy] = useState('')
  const load = () => api('/api/alerts').then(setS).catch((e) => setMsg(['bad', e.message]))
  useEffect(() => { load() }, [])
  const run = async (what, fn) => {
    setBusy(what); setMsg(null)
    try { const r = await fn(); if (r && r.has_token !== undefined) setS(r); return r } catch (e) { setMsg(['bad', e.message]) } finally { setBusy('') }
    return null
  }
  if (!s) return <div className="card"><h3 style={{ marginTop: 0 }}>📨 Telegram alerts</h3><div className="small muted">{msg ? msg[1] : 'Loading…'}</div></div>
  const ready = s.has_token && s.chat_id
  return (
    <div className="card">
      <div className="row between"><h3 style={{ margin: 0 }}>📨 Telegram alerts</h3>
        {ready && <label className="row small" style={{ gap: 6, cursor: 'pointer' }}><input type="checkbox" checked={s.on} onChange={(e) => run('on', () => post('/api/alerts', { on: e.target.checked }))} /> {s.on ? 'On' : 'Off'}</label>}
      </div>
      <div className="small muted" style={{ margin: '4px 0 10px' }}>Breaking market news and your stocks' filings sent to your own Telegram, checked every 5 minutes while EquityLens is running. Each item is sent once; nothing older than the moment you switch alerts on.</div>
      {!ready && (
        <ol className="small tg-steps">
          <li>In Telegram, open <b>@BotFather</b>, send <code>/newbot</code>, pick a name. It replies with a <b>token</b>.</li>
          <li>Paste the token here: <span className="row" style={{ gap: 6, marginTop: 6 }}><input className="input" style={{ flex: 1 }} placeholder="123456789:AA…" value={token} onChange={(e) => setToken(e.target.value)} />
            <button className="btn small" disabled={!token.trim() || busy} onClick={() => run('token', () => post('/api/alerts', { token: token.trim() }))}>Save</button></span>
            {s.has_token && <span className="muted"> Saved ({s.token_hint}).</span>}</li>
          <li>Open your new bot in Telegram, press <b>Start</b> (or send it any message), then press <button className="btn small" disabled={!s.has_token || busy} onClick={() => run('chat', () => post('/api/alerts/find-chat'))}>{busy === 'chat' ? 'Looking…' : 'Find my chat'}</button></li>
        </ol>
      )}
      {ready && (
        <>
          <div className="small" style={{ marginBottom: 8 }}>Sending to <b>{s.chat_name || s.chat_id}</b> · bot {s.token_hint}
            <button className="btn small" style={{ marginLeft: 8 }} disabled={!!busy} onClick={() => run('test', async () => { await post('/api/alerts/test'); setMsg(['good', 'Test message sent: check Telegram.']) })}>{busy === 'test' ? 'Sending…' : 'Send a test'}</button>
            <button className="btn small" style={{ marginLeft: 6 }} onClick={() => run('reset', () => post('/api/alerts', { on: false, token: '', chat_id: '', chat_name: '' }))}>Change bot</button></div>
          {OPTS.map(([k, l, d]) => (
            <label key={k} className="tg-opt"><input type="checkbox" checked={!!s[k]} onChange={(e) => run(k, () => post('/api/alerts', { [k]: e.target.checked }))} />
              <span><b>{l}</b><span className="small muted"> · {d}</span></span></label>))}
          <div className="row small" style={{ gap: 12, marginTop: 6 }}>Markets:
            {['IN', 'US'].map((m) => <label key={m} className="row" style={{ gap: 4 }}><input type="checkbox" checked={s.markets.includes(m)} onChange={(e) => run('mk', () => post('/api/alerts', { markets: e.target.checked ? [...s.markets, m] : s.markets.filter((x) => x !== m) }))} />{m === 'IN' ? '🇮🇳 India' : '🇺🇸 US'}</label>)}
          </div>
          <div className="small muted" style={{ marginTop: 8 }}>
            {s.on ? `On · ${s.sent_count || 0} sent${s.last_sent ? ` · last ${ago(s.last_sent)}` : ''} · watching ${s.watch.length} watchlist stock${s.watch.length === 1 ? '' : 's'}` : 'Off: switch on (top right) to start.'}
            {s.last_error && <div style={{ color: 'var(--warn)' }}>Last problem: {s.last_error}</div>}
          </div>
        </>
      )}
      {msg && <div className="small" style={{ marginTop: 8, color: msg[0] === 'bad' ? 'var(--bad)' : 'var(--good)' }}>{msg[1]}</div>}
    </div>
  )
}
