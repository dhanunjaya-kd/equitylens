import { useEffect, useState } from 'react'
import { Area, AreaChart, CartesianGrid, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { FnoBadge, Logo, ScoreRing } from '../components/ui'
import { ago, api, getMarket, go, isDesktop, ok, parseHash, signed } from '../util'
import { Md } from './AI'
import Watch from './Watch'

// money in full (not crores): ₹1,65,714 / $12,340
const money = (v, mk, d = 0) => (ok(v) ? (v < 0 ? '-' : '') + (mk === 'US' ? '$' : '₹') + Math.abs(v).toLocaleString(mk === 'US' ? 'en-US' : 'en-IN', { maximumFractionDigits: d }) : '—')
const tone = (v) => (v > 0 ? 't-good' : v < 0 ? 't-bad' : '')

function BrokerCard({ b, onChange, mk }) {
  const [open, setOpen] = useState(false), [vals, setVals] = useState({}), [busy, setBusy] = useState(''), [msg, setMsg] = useState(null), [paste, setPaste] = useState(false), [url, setUrl] = useState('')
  const save = async () => {
    setBusy('save'); setMsg(null)
    try { await api(`/api/brokers/${b.id}/config`, { method: 'POST', body: JSON.stringify(vals), headers: { 'Content-Type': 'application/json' } }); setVals({}); setMsg({ ok: 'Saved on this computer.' }); onChange() } catch (e) { setMsg({ err: e.message }) } finally { setBusy('') }
  }
  const connect = async () => {
    setBusy('connect'); setMsg(null)
    try {
      const r = await api(`/api/brokers/${b.id}/connect`, { method: 'POST' })
      if (r.url) {
        if (b.auth === 'paste') { window.open(r.url, '_blank'); setPaste(true) } else window.location.href = r.url
      } else { setMsg({ ok: `Connected · ${r.holdings} holdings imported.` }); onChange() }
    } catch (e) { setMsg({ err: e.message }) } finally { setBusy('') }
  }
  const sendPaste = async () => {
    setBusy('paste'); setMsg(null)
    try { const r = await api('/api/brokers/schwab/paste', { method: 'POST', body: JSON.stringify({ url }), headers: { 'Content-Type': 'application/json' } }); setPaste(false); setMsg({ ok: `Connected · ${r.holdings} holdings imported.` }); onChange() } catch (e) { setMsg({ err: e.message }) } finally { setBusy('') }
  }
  const sync = async () => { setBusy('sync'); setMsg(null); try { const r = await api(`/api/brokers/${b.id}/sync`, { method: 'POST' }); setMsg({ ok: `${r.holdings} holdings updated.` }); onChange() } catch (e) { setMsg({ err: e.message }); onChange() } finally { setBusy('') } }
  const remove = async () => { if (!window.confirm(`Remove ${b.name}? Its saved keys and holdings are deleted from this computer.`)) return; await api(`/api/brokers/${b.id}`, { method: 'DELETE' }); onChange() }
  const state = b.error ? ['warn', b.error.startsWith('Session expired') ? 'Session expired' : 'Needs attention'] : b.connected ? ['good', 'Connected'] : b.configured ? ['ok', 'Ready to connect'] : ['neutral', 'Not set up']
  return (
    <div className={`brk ${b.connected ? 'on' : ''}`}>
      <div className="row between">
        <div><b>{b.name}</b><div className="small muted">{b.holdings ? `${b.holdings} holdings · synced ${ago(b.last_sync)}` : b.expires}</div></div>
        <span className={`badge sm t-${state[0]} bg-${state[0]}`}>{state[1]}</span>
      </div>
      <div className="row wrapflex" style={{ gap: 6, marginTop: 10 }}>
        {b.configured && <button className="btn small primary" disabled={!!busy} onClick={connect}>{busy === 'connect' ? 'Connecting…' : b.connected ? '↻ Reconnect' : '🔗 Connect'}</button>}
        {b.connected && <button className="btn small" disabled={!!busy} onClick={sync}>{busy === 'sync' ? 'Syncing…' : 'Sync now'}</button>}
        <button className="btn small" onClick={() => setOpen(!open)}>{open ? 'Close' : b.configured ? '⚙️ Keys' : '⚙️ Set up'}</button>
        {(b.configured || b.holdings > 0) && <button className="btn small" onClick={remove}>Remove</button>}
      </div>
      {msg && <div className={`small ${msg.err ? 't-bad' : 't-good'}`} style={{ marginTop: 8 }}>{msg.err ? '⚠️ ' : '✓ '}{msg.err || msg.ok}</div>}
      {b.error && !msg && <div className="small t-warn" style={{ marginTop: 8 }}>{b.error}</div>}
      {paste && (
        <div className="brk-form">
          <div className="small">After logging in to Schwab you land on a page that doesn't load. Copy that page's full address and paste it here:</div>
          <input placeholder="https://127.0.0.1/?code=…" value={url} onChange={(e) => setUrl(e.target.value)} />
          <button className="btn small primary" disabled={!url || !!busy} onClick={sendPaste}>Finish connecting</button>
        </div>
      )}
      {open && (
        <div className="brk-form">
          <ol className="small brk-steps">{b.steps.map((s) => <li key={s} dangerouslySetInnerHTML={{ __html: s.replace(/\*\*(.+?)\*\*/g, '<b>$1</b>') }} />)}</ol>
          <a className="small" href={b.site} target="_blank" rel="noreferrer">Open {b.site.replace('https://', '')} ↗</a>
          {b.redirect_uri && (
            <div className="small">Redirect URL to paste in the broker's app:
              <div className="copy-row"><code>{b.redirect_uri}</code><button className="btn small" onClick={() => navigator.clipboard?.writeText(b.redirect_uri)}>Copy</button></div>
              <span className="muted">Open EquityLens with this same address when you connect.</span>
            </div>
          )}
          {b.fields.map((f) => (
            <label key={f.key} className="small">{f.label}
              <input type={f.secret ? 'password' : 'text'} autoComplete="off" placeholder={f.set ? (f.secret ? f.value : f.value) : ''} value={vals[f.key] ?? ''} onChange={(e) => setVals({ ...vals, [f.key]: e.target.value })} />
            </label>
          ))}
          <button className="btn small primary" disabled={busy === 'save'} onClick={save}>Save keys</button>
        </div>
      )}
    </div>
  )
}

function FileCard({ b, mk, onChange }) {
  const [busy, setBusy] = useState(false), [msg, setMsg] = useState(null)
  const pick = (e) => {
    const f = e.target.files?.[0]
    if (!f) return
    setBusy(true); setMsg(null)
    const rd = new FileReader()
    rd.onload = async () => {
      try {
        const data = String(rd.result).split(',')[1]
        const r = await api('/api/portfolio/upload', { method: 'POST', body: JSON.stringify({ filename: f.name, market: mk, data }), headers: { 'Content-Type': 'application/json' } })
        setMsg({ ok: `${r.holdings} holdings imported from ${r.file}.` }); onChange()
      } catch (er) { setMsg({ err: er.message }) } finally { setBusy(false); e.target.value = '' }
    }
    rd.readAsDataURL(f)
  }
  return (
    <div className={`brk ${b?.connected ? 'on' : ''}`}>
      <div className="row between"><div><b>📄 Any broker: upload holdings</b>
        <div className="small muted">{b?.holdings ? `${b.holdings} holdings from ${b.file} · ${ago(b.last_sync)}` : mk === 'US' ? 'CSV / Excel export from Robinhood, Fidelity, IBKR, Schwab…' : 'CSV / Excel from Groww, Zerodha Console, Kotak, ICICI, HDFC Sec…'}</div></div>
        {b?.holdings ? <span className="badge sm t-good bg-good">Imported</span> : null}</div>
      <div className="row wrapflex" style={{ gap: 6, marginTop: 10 }}>
        <label className="btn small primary">{busy ? 'Reading…' : '⬆️ Upload file'}<input type="file" accept=".csv,.xlsx,.xlsm" hidden onChange={pick} /></label>
        {b?.holdings ? <button className="btn small" onClick={async () => { await api('/api/brokers/file', { method: 'DELETE' }); onChange() }}>Remove</button> : null}
      </div>
      <div className="small muted" style={{ marginTop: 6 }}>The file needs a symbol (or ISIN) column and a quantity column; average price and LTP are used if present.</div>
      {msg && <div className={`small ${msg.err ? 't-bad' : 't-good'}`} style={{ marginTop: 8 }}>{msg.err ? '⚠️ ' : '✓ '}{msg.err || msg.ok}</div>}
    </div>
  )
}

function Bars({ items, label, value }) {
  const max = Math.max(...items.map((i) => i[value]), 1)
  return (
    <div className="pbars">
      {items.map((i) => (
        <div key={i[label]} className="pbar"><span className="ellip">{i[label]}</span><div className="pbar-track"><div style={{ width: `${(i[value] / max) * 100}%` }} /></div><b>{i[value]}%</b></div>
      ))}
    </div>
  )
}

function Holdings({ x, mk }) {
  const desk = isDesktop()
  if (desk) {
    return (
      <div className="card" style={{ padding: 0, overflowX: 'auto' }}>
        <table className="ptable">
          <thead><tr><th>Company</th><th>Qty</th><th>Avg</th><th>LTP</th><th>Value</th><th>P&L</th><th>Weight</th><th>Score</th><th>Entry</th><th>Div Yield</th><th>Verdict</th><th>Watch-outs</th></tr></thead>
          <tbody>
            {x.rows.map((r) => (
              <tr key={r.symbol} onClick={() => go(`stock/${r.symbol}`)}>
                <td><div className="row" style={{ gap: 10 }}><Logo sym={r.symbol} name={r.name} size={28} /><div><b>{r.name}</b>{r.fno && <FnoBadge lot={r.lot} />}<div className="small muted">{r.symbol.replace('US:', '')} · {r.brokers.join(', ')}</div></div></div></td>
                <td>{r.qty}</td><td>{money(r.avg, mk, 2)}</td><td>{money(r.ltp, mk, 2)}</td><td><b>{money(r.value, mk)}</b></td>
                <td className={tone(r.pnl)}>{money(r.pnl, mk)}<div className="small">{signed(r.pnl_pct, 1, '%')}</div></td>
                <td><div className="wbar"><div style={{ width: `${Math.min(r.weight || 0, 100)}%` }} /></div><span className="small">{r.weight}%</span></td>
                <td>{r.scored ? <ScoreRing value={r.overall} size={38} /> : <span className="small muted">{r.fund ? 'fund / ETF' : 'not scored'}</span>}</td>
                <td>{r.entry_verdict && r.entry_verdict !== 'NA' ? <span className={`badge sm ${r.entry_verdict === 'ENTER' ? 't-good bg-good' : 't-warn bg-warn'}`}>{r.entry_verdict}</span> : '—'}</td>
                <td className="small">{ok(r.dividend_yield) ? `${r.dividend_yield}%` : '—'}</td>
                <td>{r.verdict ? <span className={`badge sm t-${r.tone} bg-${r.tone}`}>{r.verdict}</span> : '—'}</td>
                <td className="small">{[r.surveillance && '🚨 surveillance', r.high_flags > 0 && `🚩 ${r.high_flags} red flag${r.high_flags > 1 ? 's' : ''}`, r.pledged >= 10 && `🔒 pledge ${r.pledged}%`, r.next_results && `📅 results ${r.next_results.slice(5)}`].filter(Boolean).join(' · ') || '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    )
  }
  return (
    <div className="card" style={{ padding: 0 }}>
      {x.rows.map((r) => (
        <div key={r.symbol} className="mv-row" onClick={() => go(`stock/${r.symbol}`)}>
          <Logo sym={r.symbol} name={r.name} size={32} />
          <div className="grow" style={{ minWidth: 0 }}>
            <div className="ellip"><b>{r.name}</b>{r.fno && <FnoBadge />}{r.surveillance && <span className="tagc bad">🚨</span>}{r.high_flags > 0 && <span className="tagc bad">🚩{r.high_flags}</span>}</div>
            <div className="small muted ellip">{r.qty} × {money(r.avg, mk, 2)} · {r.weight}% · {r.scored ? `score ${r.overall ?? '—'}` : r.fund ? 'fund / ETF' : 'not scored'}</div>
          </div>
          <div className="cal-num"><b>{money(r.value, mk)}</b><div className={`small ${tone(r.pnl)}`}>{signed(r.pnl_pct, 1, '%')}</div></div>
        </div>
      ))}
    </div>
  )
}

export default function Portfolio() {
  const mk = getMarket()
  const q = new URLSearchParams((window.location.hash.split('?')[1]) || '')
  const [tab, setTab] = useState(q.get('tab') === 'watch' ? 'watch' : 'holdings')
  const [b, setB] = useState(null), [x, setX] = useState(null), [ai, setAi] = useState(null), [aiBusy, setAiBusy] = useState(false), [aiErr, setAiErr] = useState(null)
  const [scan, setScan] = useState(null), [syncing, setSyncing] = useState(false)
  const [note, setNote] = useState(q.get('connected') ? { ok: `Connected to ${q.get('connected')} — holdings imported.` } : q.get('error') ? { err: q.get('error') } : null)
  const load = () => { api('/api/brokers').then((r) => setB(r.brokers)).catch(() => setB([])); api(`/api/portfolio?market=${mk}`).then(setX).catch(() => setX({ rows: [] })) }
  useEffect(load, [mk])
  useEffect(() => {
    if (!scan?.running) return
    const t = setInterval(async () => { const s = await api('/api/scan/status').catch(() => null); if (s) { setScan(s); if (!s.running) load() } }, 3000)
    return () => clearInterval(t)
  }, [scan?.running])
  const mine = (b || []).filter((k) => k.market === mk)
  const file = (b || []).find((k) => k.id === 'file')
  const syncAll = async () => { setSyncing(true); for (const k of mine.filter((k) => k.connected)) { try { await api(`/api/brokers/${k.id}/sync`, { method: 'POST' }) } catch { /* shown on the card */ } } setSyncing(false); load() }
  const scoreAll = async () => { const r = await api(`/api/portfolio/score?market=${mk}`, { method: 'POST' }); if (r.scan) setScan(r.scan) }
  const review = async () => { setAiBusy(true); setAiErr(null); try { setAi(await api(`/api/ai/portfolio?market=${mk}`, { method: 'POST' })) } catch (e) { setAiErr(e.message) } finally { setAiBusy(false) } }
  const s = x?.summary

  return (
    <div className="movers">
      <div className="card">
        <div className="row between wrapflex" style={{ gap: 8 }}>
          <div><h3 style={{ margin: 0 }}>{mk === 'US' ? '🇺🇸' : '🇮🇳'} My portfolio</h3>
            <div className="small muted">🔒 Read-only: EquityLens can see your holdings but can never place orders. Keys stay on this computer.</div></div>
          <div className="row" style={{ gap: 6 }}>
            <button className={`tab ${tab === 'holdings' ? 'on' : ''}`} onClick={() => setTab('holdings')}>💼 Holdings</button>
            <button className={`tab ${tab === 'watch' ? 'on' : ''}`} onClick={() => setTab('watch')}>⭐ Watchlist</button>
          </div>
        </div>
        {note && <div className={`small ${note.err ? 't-bad' : 't-good'}`} style={{ marginTop: 8 }}>{note.err ? '⚠️ ' : '✓ '}{note.err || note.ok} <span className="muted" style={{ cursor: 'pointer' }} onClick={() => setNote(null)}>✕</span></div>}
        {tab === 'holdings' && s && (
          <div className="ptiles">
            <div className="tile"><div className="k">Current value</div><div className="v">{money(s.value, mk)}</div><div className="s">Invested {money(s.invested, mk)}</div></div>
            <div className="tile"><div className="k">Total P&amp;L</div><div className={`v ${tone(s.pnl)}`}>{money(s.pnl, mk)} <span className="small">{signed(s.pnl_pct, 1, '%')}</span></div>
              {s.benchmark && <div className="s">vs {s.benchmark.name}: <b className={tone(s.benchmark.alpha_1y)}>{signed(s.benchmark.alpha_1y, 1, '%')} alpha (1Y)</b></div>}</div>
            <div className="tile"><div className="k">Portfolio Health Score</div><div className="v">{s.score ?? '—'}<span className="small muted"> / 100 · {s.scored}/{s.count} scored</span></div></div>
            <div className="tile"><div className="k">Est. Annual Dividends</div><div className="v">{money(s.est_dividend || 0, mk)}<span className="small muted"> / yr</span></div>
              {ok(s.dividend_yield) && <div className="s">{s.dividend_yield}% portfolio yield</div>}</div>
          </div>
        )}
        {tab === 'holdings' && s && <div className="row wrapflex small muted" style={{ gap: 10, marginTop: 8 }}><span>{s.count} holdings · {s.brokers.join(', ')} · synced {ago(s.synced)}</span>
          <button className="btn small" disabled={syncing} onClick={syncAll}>{syncing ? 'Syncing…' : '↻ Sync all brokers'}</button></div>}
      </div>

      {tab === 'watch' && <Watch />}

      {tab === 'holdings' && (
        <div className="movers-grid">
          <div className="movers-side">
            <div className="card">
              <h3>🔗 Connect your broker</h3>
              <div className="brk-list">
                {mine.map((k) => <BrokerCard key={k.id} b={k} mk={mk} onChange={load} />)}
                <FileCard b={file} mk={mk} onChange={load} />
              </div>
            </div>
          </div>

          <div className="movers-main">
            {x && !x.rows.length && (
              <div className="card empty">
                <div style={{ fontSize: 34 }}>💼</div>
                <b>No holdings yet</b>
                <div className="small muted" style={{ marginTop: 6 }}>Connect {mk === 'US' ? 'Alpaca, Tradier or Schwab' : 'Zerodha, Upstox, Fyers, Angel One or Dhan'}, or upload your broker's holdings file. EquityLens then scores every stock you own, flags risks, shows results dates and checks how balanced the portfolio is.</div>
              </div>
            )}
            {s && (
              <>
                {s.unscored.length > 0 && (
                  <div className="card univ-note small">
                    <div><b>{s.unscored.length} holding{s.unscored.length > 1 ? 's are' : ' is'} not scored yet</b> — scoring reads each company's 10-year financials (about 5 seconds each).</div>
                    {scan?.running ? <div>Scoring {scan.current || '…'} · {scan.done}/{scan.total}<div className="progress"><div style={{ width: `${scan.total ? (scan.done / scan.total) * 100 : 0}%` }} /></div></div>
                      : <button className="btn small primary" onClick={scoreAll}>Score my holdings</button>}
                  </div>
                )}
                {(s.benchmark || s.drift?.length > 0) && (
                  <div className="pgrid">
                    {s.benchmark && (
                      <div className="card">
                        <div className="row between" style={{ marginBottom: 6 }}>
                          <h3 style={{ margin: 0 }}>📈 Portfolio vs {s.benchmark.name} (1Y)</h3>
                          <span className={`badge sm ${s.benchmark.alpha_1y >= 0 ? 't-good bg-good' : 't-bad bg-bad'}`}>{signed(s.benchmark.alpha_1y, 1, '%')} alpha</span>
                        </div>
                        <ResponsiveContainer width="100%" height={180}>
                          <AreaChart data={s.benchmark.series}>
                            <CartesianGrid stroke="var(--grid)" strokeDasharray="3 3" />
                            <XAxis dataKey="date" stroke="var(--muted)" fontSize={10} tickFormatter={(d) => d.slice(5)} />
                            <YAxis stroke="var(--muted)" fontSize={10} width={38} tickFormatter={(v) => `${v}%`} />
                            <Tooltip contentStyle={{ background: 'var(--card)', border: '1px solid var(--line)', borderRadius: 8, fontSize: 12 }} formatter={(v) => `${v}%`} />
                            <Legend wrapperStyle={{ fontSize: 11 }} />
                            <Area type="monotone" dataKey="portfolio" name="Portfolio" stroke="#2dd4bf" fill="rgba(45,212,191,.16)" strokeWidth={2} />
                            <Line type="monotone" dataKey="benchmark" name={s.benchmark.name} stroke="#8b98a5" strokeDasharray="4 4" strokeWidth={1.5} dot={false} />
                          </AreaChart>
                        </ResponsiveContainer>
                      </div>
                    )}
                    {s.drift?.length > 0 && (
                      <div className="card">
                        <h3>⚡ Fundamental Drift &amp; Risk Alerts</h3>
                        {s.drift.map((d, i) => (
                          <div key={i} className={`drift-row t-${d.tone}`} onClick={() => d.symbol && go(`stock/${d.symbol}`)} style={{ cursor: d.symbol ? 'pointer' : 'default' }}>
                            <b>{d.symbol ? `${d.symbol.replace('US:', '')}: ` : ''}</b>{d.text}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
                {s.warnings.length > 0 && (
                  <div className="card">
                    <h3>⚠️ Look at these closely</h3>
                    {s.warnings.map((w) => (
                      <div key={w.symbol} className="ins-row" onClick={() => go(`stock/${w.symbol}`)}>
                        <Logo sym={w.symbol} name={w.name} size={26} />
                        <div className="grow"><b>{w.name}</b><div className="small">{w.why.join(' · ')}</div></div>
                        <span className="small muted">{w.weight}%</span>
                      </div>
                    ))}
                  </div>
                )}
                <div className="pgrid">
                  <div className="card"><h3>🏭 Sector mix</h3><Bars items={s.sectors.slice(0, 8)} label="sector" value="weight" />
                    {s.funds?.length > 0 && <div className="small muted" style={{ marginTop: 6 }}>{s.funds.length} fund/ETF holding{s.funds.length > 1 ? 's' : ''} (no company financials) not counted in the score.</div>}
                    <div className="small muted" style={{ marginTop: 6 }}>Top 5 holdings = <b>{s.top5}%</b> of the portfolio{s.top5 > 70 ? ' — concentrated' : ''}.</div></div>
                  {s.mix && <div className="card"><h3>🏛️ Size mix</h3><Bars items={Object.entries(s.mix).map(([k, v]) => ({ k, v }))} label="k" value="v" />
                    <div className="small muted" style={{ marginTop: 6 }}>{s.fno} F&O stock{s.fno === 1 ? '' : 's'} in the portfolio.</div></div>}
                </div>
                {s.results_soon.length > 0 && (
                  <div className="card"><h3>📅 Results coming up</h3>
                    {s.results_soon.map((r) => <span key={r.symbol} className="chip chip-logo" style={{ cursor: 'pointer' }} onClick={() => go(`stock/${r.symbol}`)}><Logo sym={r.symbol} name={r.name} size={18} />{r.name} · {r.date}</span>)}
                  </div>
                )}
                <Holdings x={x} mk={mk} />
                <div className="card">
                  <div className="row between"><h3 style={{ margin: 0 }}>✨ Review my portfolio</h3><button className="btn small primary" disabled={aiBusy} onClick={review}>{ai ? '↻ Again' : 'Review'}</button></div>
                  {aiBusy && <div className="small muted" style={{ marginTop: 8 }}>Reading your holdings…</div>}
                  {aiErr && <div className="small t-bad" style={{ marginTop: 8 }}>⚠️ {aiErr}</div>}
                  {ai ? <><Md text={ai.text} /><div className="small muted">{ai.model}</div></> : !aiBusy && <p className="small muted" style={{ marginBottom: 0 }}>Strongest holdings, the ones to look at closely, and how balanced the portfolio is. No buy/sell calls.</p>}
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
