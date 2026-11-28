import { useEffect, useMemo, useState } from 'react'
import { Area, AreaChart, CartesianGrid, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { FnoBadge, Logo, ScoreRing } from '../components/ui'
import { ago, api, getMarket, go, isDesktop, ok, parseHash, signed } from '../util'
import { Md } from './AI'
import Watch from './Watch'
import PortfolioConnect from './PortfolioConnect'
import { ScanBadges } from './Scanners'

// money in full (not crores): ₹1,65,714 / $12,340
const money = (v, mk, d = 0) => (ok(v) ? (v < 0 ? '-' : '') + (mk === 'US' ? '$' : '₹') + Math.abs(v).toLocaleString(mk === 'US' ? 'en-US' : 'en-IN', { maximumFractionDigits: d }) : '—')
const tone = (v) => (v > 0 ? 't-good' : v < 0 ? 't-bad' : '')

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

// money flowing into / out of each stock's industry over 5 sessions (same rule as Smart Money → Money flow)
function industryFlows(mf) {
  const by = {}
  for (const st of mf?.stocks || []) {
    const g = st.g?.industry
    if (!g || !st.flow) continue
    by[g] = (by[g] || 0) + st.flow.flow5
  }
  return { ind: Object.fromEntries((mf?.stocks || []).map((st) => [st.symbol, st.g?.industry])), net: by }
}

const SORTS = { value: (r) => r.value, pnl: (r) => r.pnl_pct, weight: (r) => r.weight, score: (r) => r.overall, rs: (r) => r._rs, results: (r) => r.next_results || '9999' }

function Holdings({ x, mk }) {
  const desk = isDesktop()
  const [sc, setSc] = useState(null), [mf, setMf] = useState(null)
  const [broker, setBroker] = useState(''), [sort, setSort] = useState(['value', -1]), [flt, setFlt] = useState('')
  useEffect(() => { api(`/api/scanners?market=${mk}`).then(setSc).catch(() => {}); api(`/api/moneyflow?market=${mk}`).then(setMf).catch(() => {}) }, [mk])
  const scan = useMemo(() => Object.fromEntries((sc?.rows || []).map((r) => [r.symbol, r])), [sc])
  const flows = useMemo(() => industryFlows(mf), [mf])
  const brokers = [...new Set(x.rows.flatMap((r) => r.brokers))]
  const rows = useMemo(() => {
    let r = x.rows.map((h) => ({ ...h, _rs: scan[h.symbol]?.rs, _tags: scan[h.symbol]?.tags || [], _ind: flows.ind[h.symbol], _flow: flows.net[flows.ind[h.symbol]] }))
    if (broker) r = r.filter((h) => h.brokers.includes(broker))
    if (flt === 'watch') r = r.filter((h) => h.surveillance || h.high_flags > 0 || (h.pledged || 0) >= 10)
    if (flt === 'loss') r = r.filter((h) => (h.pnl || 0) < 0)
    if (flt === 'results') r = r.filter((h) => h.next_results)
    const [k, dir] = sort
    const f = SORTS[k]
    return [...r].sort((a, b) => { const va = f(a), vb = f(b); if (va == null) return 1; if (vb == null) return -1; return (va > vb ? 1 : va < vb ? -1 : 0) * dir })
  }, [x, scan, flows, broker, flt, sort])
  const th = (k, l) => <th onClick={() => setSort([k, sort[0] === k ? -sort[1] : -1])} style={{ cursor: 'pointer' }}>{l}{sort[0] === k ? (sort[1] < 0 ? ' ▾' : ' ▴') : ''}</th>
  const unit = mk === 'US' ? '$ M' : '₹ Cr'
  const bar = (
    <div className="row wrapflex" style={{ gap: 6, padding: '10px 12px' }}>
      <b style={{ marginRight: 6 }}>Holdings · {rows.length}</b>
      {brokers.length > 1 && <>{['', ...brokers].map((k) => <button key={k || 'all'} className={`chip ${broker === k ? 'ipo-on' : ''}`} onClick={() => setBroker(k)}>{k || 'All brokers'}</button>)}<span className="muted">|</span></>}
      {[['', 'All'], ['loss', 'In loss'], ['watch', 'Watch-outs'], ['results', 'Results coming']].map(([k, l]) => <button key={k || 'a'} className={`chip ${flt === k ? 'ipo-on' : ''}`} onClick={() => setFlt(k)}>{l}</button>)}
    </div>
  )
  if (desk) {
    return (
      <div className="card" style={{ padding: 0, overflowX: 'auto' }}>
        {bar}
        <table className="ptable">
          <thead><tr><th>Company</th><th>Qty</th><th>Avg</th><th>LTP</th>{th('value', 'Value')}{th('pnl', 'P&L')}{th('weight', 'Weight')}{th('score', 'Score')}{th('rs', 'RS')}<th>Industry money (5D)</th>{th('results', 'Next results')}<th>Verdict</th><th>Watch-outs</th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.symbol} onClick={() => go(`stock/${r.symbol}`)}>
                <td><div className="row" style={{ gap: 10 }}><Logo sym={r.symbol} name={r.name} size={28} /><div><b>{r.name}</b>{r.fno && <FnoBadge lot={r.lot} />}<div className="small muted">{r.symbol.replace('US:', '')} · {r.brokers.join(', ')}</div>
                  <ScanBadges tags={r._tags} only={['leader', 'vcp', 'flag', 'cup_handle', 'pocket_pivot', 'bull_snort', 'minervini', 'rs_first', 'gap_up']} /></div></div></td>
                <td>{r.qty}</td><td>{money(r.avg, mk, 2)}</td><td>{money(r.ltp, mk, 2)}</td><td><b>{money(r.value, mk)}</b></td>
                <td className={tone(r.pnl)}>{money(r.pnl, mk)}<div className="small">{signed(r.pnl_pct, 1, '%')}</div></td>
                <td><div className="wbar"><div style={{ width: `${Math.min(r.weight || 0, 100)}%` }} /></div><span className="small">{r.weight}%</span></td>
                <td>{r.scored ? <ScoreRing value={r.overall} size={38} /> : <span className="small muted">{r.fund ? 'fund / ETF' : 'not scored'}</span>}</td>
                <td><b style={{ color: r._rs >= 80 ? 'var(--good)' : r._rs <= 30 ? 'var(--bad)' : undefined }}>{r._rs ?? '—'}</b></td>
                <td className="small">{ok(r._flow) ? <><b className={tone(r._flow)}>{r._flow > 0 ? '▲ in' : r._flow < 0 ? '▼ out' : 'flat'} {Math.abs(r._flow).toLocaleString(undefined, { maximumFractionDigits: 0 })} {unit}</b><div className="muted ellip" style={{ maxWidth: 150 }}>{r._ind}</div></> : '—'}</td>
                <td className="small">{r.next_results ? r.next_results : '—'}</td>
                <td>{r.verdict ? <span className={`badge sm t-${r.tone} bg-${r.tone}`}>{r.verdict}</span> : '—'}</td>
                <td className="small">{[r.surveillance && '🚨 surveillance', r.high_flags > 0 && `🚩 ${r.high_flags} red flag${r.high_flags > 1 ? 's' : ''}`, r.pledged >= 10 && `🔒 pledge ${r.pledged}%`].filter(Boolean).join(' · ') || '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="small muted" style={{ padding: '8px 12px' }}>RS and badges from Scanners; industry money from Smart Money → Money flow (estimate of direction, last 5 sessions). "—" when that page has no data for the stock yet.</div>
      </div>
    )
  }
  return (
    <div className="card" style={{ padding: 0 }}>
      {bar}
      {rows.map((r) => (
        <div key={r.symbol} className="mv-row" onClick={() => go(`stock/${r.symbol}`)}>
          <Logo sym={r.symbol} name={r.name} size={32} />
          <div className="grow" style={{ minWidth: 0 }}>
            <div className="ellip"><b>{r.name}</b>{r.fno && <FnoBadge />}{r.surveillance && <span className="tagc bad">🚨</span>}{r.high_flags > 0 && <span className="tagc bad">🚩{r.high_flags}</span>}</div>
            <div className="small muted ellip">{r.qty} × {money(r.avg, mk, 2)} · {r.weight}% · {r.scored ? `score ${r.overall ?? '—'}` : r.fund ? 'fund / ETF' : 'not scored'}{r._rs ? ` · RS ${r._rs}` : ''}</div>
            <ScanBadges tags={r._tags} only={['leader', 'vcp', 'flag', 'cup_handle', 'pocket_pivot', 'minervini']} />
          </div>
          <div className="cal-num"><b>{money(r.value, mk)}</b><div className={`small ${tone(r.pnl)}`}>{signed(r.pnl_pct, 1, '%')}</div></div>
        </div>
      ))}
    </div>
  )
}

function History({ h, mk }) {
  if (!h) return null
  const pts = h.points || []
  if (pts.length < 2) return <div className="card small muted">📆 Your portfolio's own history starts {h.since ? `on ${h.since}` : 'today'}: its value is saved once a day when you open or sync it, so this chart fills in day by day. Earlier days are never made up.</div>
  return (
    <div className="card">
      <h3 style={{ marginTop: 0 }}>📆 Your portfolio since {h.since}</h3>
      <ResponsiveContainer width="100%" height={200}>
        <AreaChart data={pts}>
          <CartesianGrid stroke="var(--grid)" strokeDasharray="3 3" />
          <XAxis dataKey="date" stroke="var(--muted)" fontSize={10} tickFormatter={(d) => d.slice(5)} />
          <YAxis stroke="var(--muted)" fontSize={10} width={64} tickFormatter={(v) => money(v, mk)} domain={['auto', 'auto']} />
          <Tooltip contentStyle={{ background: 'var(--card)', border: '1px solid var(--line)', borderRadius: 8, fontSize: 12 }} formatter={(v) => money(v, mk)} />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          <Area type="monotone" dataKey="value" name="Value" stroke="#2dd4bf" fill="rgba(45,212,191,.16)" strokeWidth={2} />
          <Line type="monotone" dataKey="invested" name="Invested" stroke="#8b98a5" strokeWidth={1.5} dot={false} />
          {pts.some((p) => p.index) && <Line type="monotone" dataKey="index" name={`${h.index}, same start`} stroke="#f59e0b" strokeDasharray="4 4" strokeWidth={1.5} dot={false} />}
        </AreaChart>
      </ResponsiveContainer>
      <div className="small muted">Saved once a day. The {h.index} line starts at your first saved value and moves with the index; money you added or took out later moves your line but not the index line.</div>
    </div>
  )
}

export default function Portfolio() {
  const mk = getMarket()
  const q = new URLSearchParams((window.location.hash.split('?')[1]) || '')
  const [tab, setTab] = useState(q.get('tab') === 'watch' ? 'watch' : 'holdings')
  const [b, setB] = useState(null), [keys, setKeys] = useState(null), [x, setX] = useState(null), [ai, setAi] = useState(null), [aiBusy, setAiBusy] = useState(false), [aiErr, setAiErr] = useState(null)
  const [scan, setScan] = useState(null), [syncing, setSyncing] = useState(false)
  const [note, setNote] = useState(q.get('connected') ? { ok: `Connected to ${q.get('connected')} — holdings imported.` } : q.get('error') ? { err: q.get('error') } : null)
  const load = () => { api('/api/brokers').then((r) => { setB(r.brokers); setKeys(r.keys) }).catch(() => setB([])); api(`/api/portfolio?market=${mk}`).then(setX).catch(() => setX({ rows: [] })) }
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
        <>
          <PortfolioConnect brokers={b} keys={keys} mk={mk} onChange={load} />
          <div>
            {x && !x.rows.length && (
              <div className="card empty">
                <div style={{ fontSize: 34 }}>💼</div>
                <b>No holdings yet</b>
                <div className="small muted" style={{ marginTop: 6 }}>Connect a broker or upload a holdings file above. EquityLens then scores every stock you own, flags risks, shows results dates, money flow and scanner signals, and checks how balanced the portfolio is.</div>
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
                <History h={s.history} mk={mk} />
                <div className="card">
                  <div className="row between"><h3 style={{ margin: 0 }}>✨ Review my portfolio</h3><button className="btn small primary" disabled={aiBusy} onClick={review}>{ai ? '↻ Again' : 'Review'}</button></div>
                  {aiBusy && <div className="small muted" style={{ marginTop: 8 }}>Reading your holdings…</div>}
                  {aiErr && <div className="small t-bad" style={{ marginTop: 8 }}>⚠️ {aiErr}</div>}
                  {ai ? <><Md text={ai.text} /><div className="small muted">{ai.model}</div></> : !aiBusy && <p className="small muted" style={{ marginBottom: 0 }}>Strongest holdings, the ones to look at closely, and how balanced the portfolio is. No buy/sell calls.</p>}
                </div>
              </>
            )}
          </div>
        </>
      )}
    </div>
  )
}
