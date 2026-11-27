import { useEffect, useMemo, useRef, useState } from 'react'
import { Badge, FnoBadge, FnoToggle, Logo, UniverseChips, UsUniverseChips, useFno, useUniv, useUsUniv } from '../components/ui'
import { ago, api, cr, getMarket, go, isDesktop, num, ok, pct, rs, signed, ticker, watchlist } from '../util'
import { Md } from './AI'

const TFS = ['1D', '1W', '1M', '3M', '1Y']
const TF_WORD = { '1D': 'today', '1W': 'this week', '1M': 'this month', '3M': 'in 3 months', '1Y': 'this year' }

// key, label, emoji, help
const LISTS = [
  ['gainers', 'Top gainers', '🚀', 'Biggest price rise'],
  ['losers', 'Top losers', '📉', 'Biggest price fall'],
  ['buyers', 'Top buyers', '🟢', 'Strongest buying pressure: most volume on up-days (1D: closed near the day\'s high)'],
  ['sellers', 'Top sellers', '🔴', 'Strongest selling pressure: most volume on down-days (1D: closed near the day\'s low)'],
  ['high52', '52W high', '🏔️', 'At or near a 52-week high; ✅ = volume-confirmed breakout'],
  ['low52', '52W low', '🕳️', 'At or near a 52-week low'],
  ['volume', 'Volume shockers', '🔊', 'Volume far above normal'],
  ['active', 'Most active', '💰', 'Highest traded value'],
  ['quality', 'Quality on sale', '💎', 'Strong business (score ≥ 70) trading 15%+ below its 52-week high'],
  ['hype', 'Hype watch', '⚠️', 'Rising fast, but weak fundamentals or red flags'],
]

function build(list, rows, tf) {
  const r = (x) => x.ret?.[tf]
  const have = rows.filter((x) => ok(r(x)))
  const by = (f, desc = true) => [...have].sort((a, b) => (desc ? f(b) - f(a) : f(a) - f(b)))
  switch (list) {
    case 'gainers': return by(r).filter((x) => r(x) > 0)
    case 'losers': return by(r, false).filter((x) => r(x) < 0)
    case 'buyers': return by((x) => x.pressure[tf] * 100 + r(x) / 10).filter((x) => r(x) > 0 && x.pressure[tf] > 0)
    case 'sellers': return by((x) => x.pressure[tf] * 100 + r(x) / 10, false).filter((x) => r(x) < 0 && x.pressure[tf] < 0)
    case 'high52': return (tf === '1D' ? have.filter((x) => x.new_high) : have.filter((x) => x.from_hi >= -3)).sort((a, b) => b.from_hi - a.from_hi || (b.rvol || 0) - (a.rvol || 0))
    case 'low52': return (tf === '1D' ? have.filter((x) => x.new_low) : have.filter((x) => x.from_lo <= 3)).sort((a, b) => a.from_lo - b.from_lo)
    case 'volume': return by((x) => x.vol_change[tf] || 0).filter((x) => (x.vol_change[tf] || 0) >= (tf === '1D' ? 1.8 : 1.3))
    case 'active': return by((x) => x.turnover[tf] || 0)
    case 'quality': return have.filter((x) => x.fund && x.fund.business >= 70 && x.from_hi <= -15).sort((a, b) => (b.fund.business - a.fund.business) || (a.from_hi - b.from_hi))
    case 'hype': {
      const sorted = by(r); const cut = sorted[Math.floor(sorted.length * 0.2)]
      return sorted.filter((x) => cut && r(x) >= r(cut) && r(x) > 0 && x.fund && (x.fund.business < 50 || x.fund.high_flags > 0))
    }
    default: return have
  }
}

function Spark({ data, up }) {
  if (!data || data.length < 2) return <svg width="70" height="26" />
  const min = Math.min(...data), max = Math.max(...data), w = 70, h = 26
  const pts = data.map((v, i) => `${(i / (data.length - 1)) * w},${h - 2 - ((v - min) / (max - min || 1)) * (h - 4)}`).join(' ')
  return <svg width={w} height={h} className="spark"><polyline points={pts} fill="none" stroke={up ? 'var(--good)' : 'var(--bad)'} strokeWidth="1.6" /></svg>
}

function Gauge({ score, label, tone }) {
  const a = Math.PI * (1 - score / 100)
  const x = 60 + 46 * Math.cos(a), y = 58 - 46 * Math.sin(a)
  return (
    <svg viewBox="0 0 120 70" width="150" height="88">
      <defs><linearGradient id="mg" x1="0" x2="1"><stop offset="0" stopColor="#ef4444" /><stop offset=".45" stopColor="#f59e0b" /><stop offset=".55" stopColor="#8b98a5" /><stop offset="1" stopColor="#22c55e" /></linearGradient></defs>
      <path d="M14 58 A46 46 0 0 1 106 58" fill="none" stroke="url(#mg)" strokeWidth="10" strokeLinecap="round" />
      <circle cx={x} cy={y} r="6" fill="var(--text)" stroke="var(--card)" strokeWidth="2" />
      <text x="60" y="54" textAnchor="middle" fontSize="18" fontWeight="800" fill="var(--text)">{score}</text>
      <text x="60" y="68" textAnchor="middle" fontSize="8.5" fill={`var(--${tone})`} fontWeight="700">{label.toUpperCase()}</text>
    </svg>
  )
}

export default function Movers() {
  const mk = getMarket()
  const ss = (k, d) => { try { return sessionStorage.getItem(k) || d } catch { return d } }
  const [tf, setTfRaw] = useState(ss('eql_mv_tf', '1D'))
  const [list, setListRaw] = useState(ss('eql_mv_list', 'gainers'))
  const setTf = (v) => { try { sessionStorage.setItem('eql_mv_tf', v) } catch {} ; setTfRaw(v) }
  const setList = (v) => { try { sessionStorage.setItem('eql_mv_list', v) } catch {} ; setListRaw(v) }
  const [d, setD] = useState(null)
  const [sector, setSector] = useState('')
  const [showF, setShowF] = useState(false)
  const [f, setF] = useState({ minPrice: '', maxPrice: '', minTurn: '', minCap: '', minScore: '', watch: false, above200: false })
  const [ai, setAi] = useState(null), [aiBusy, setAiBusy] = useState(false), [aiErr, setAiErr] = useState(null)
  const poll = useRef()

  const [univ] = useUniv()
  const [uu] = useUsUniv()
  const load = () => api(`/api/movers?market=${mk}&tf=${tf}&universe=${mk === 'IN' ? univ : uu}`).then(setD).catch(() => setD({ rows: [], status: {} }))
  useEffect(() => { load(); setAi(null) }, [tf, mk, univ, uu])
  useEffect(() => {
    clearInterval(poll.current)
    if (d?.status?.running) poll.current = setInterval(load, 4000)
    return () => clearInterval(poll.current)
  }, [d?.status?.running])

  const watchSet = useMemo(() => new Set(watchlist.all().map((w) => w.symbol)), [])
  const [fno] = useFno()
  const filtered = useMemo(() => {
    const rows = d?.rows || []
    return rows.filter((x) => (!sector || x.sector === sector)
      && (f.minPrice === '' || x.price >= +f.minPrice) && (f.maxPrice === '' || x.price <= +f.maxPrice)
      && (f.minTurn === '' || (x.turnover?.[tf] || 0) >= +f.minTurn)
      && (f.minCap === '' || (x.fund?.market_cap || x.mcap_nasdaq || 0) >= +f.minCap)
      && (f.minScore === '' || (x.fund?.overall || 0) >= +f.minScore)
      && (!f.watch || watchSet.has(x.symbol)) && (!f.above200 || x.above200) && (!fno || x.fno))
  }, [d, sector, f, tf, fno])
  const items = useMemo(() => build(list, filtered, tf).slice(0, 50), [list, filtered, tf])
  const counts = useMemo(() => Object.fromEntries(LISTS.map(([k]) => [k, build(k, filtered, tf).length])), [filtered, tf])
  const st = d?.status || {}
  const mood = d?.mood
  const activeF = Object.entries(f).filter(([, v]) => v !== '' && v !== false).length + (sector ? 1 : 0)
  const money = mk === 'US' ? '$ M' : '₹ Cr'
  const explain = async () => {
    setAiBusy(true); setAiErr(null)
    try { setAi(await api(`/api/ai/movers?market=${mk}&tf=${tf}`, { method: 'POST' })) } catch (e) { setAiErr(e.message) } finally { setAiBusy(false) }
  }

  const metric = (x) => {
    if (list === 'buyers' || list === 'sellers') return `${tf === '1D' ? 'Close in range' : 'Up-vol share'} ${signed(x.pressure[tf] * 100, 0, '')}`
    if (list === 'high52' || list === 'low52') return list === 'high52' ? `${signed(x.from_hi, 1, '%')} from high${x.rvol >= 1.5 ? ' · ✅ vol' : ''}` : `${signed(x.from_lo, 1, '%')} above low`
    if (list === 'volume') return `${num(x.vol_change[tf], 1)}× normal volume`
    if (list === 'active') return `${num(x.turnover[tf], 0)} ${money}/day`
    if (list === 'quality') return `Score ${x.fund?.business} · ${signed(x.from_hi, 0, '%')} from high`
    if (list === 'hype') return x.fund?.high_flags ? `${x.fund.high_flags} red flag(s)` : `Business score ${x.fund?.business}`
    return `${signed(x.from_hi, 0, '%')} from 52W high`
  }

  return (
    <div className="movers">
      <div className="card">
        <div className="row between wrapflex">
          <div><h3 style={{ margin: 0 }}>{mk === 'US' ? '🇺🇸' : '🇮🇳'} Market Movers <button className="btn small" style={{ marginLeft: 8, verticalAlign: 'middle' }} onClick={() => go('heatmap')}>🗺️ Heatmap</button><button className="btn small" style={{ marginLeft: 6, verticalAlign: 'middle' }} onClick={() => go('news')}>📰 News</button><button className="btn small" style={{ marginLeft: 6, verticalAlign: 'middle' }} onClick={() => go('ipo')}>🚀 IPOs</button><button className="btn small" style={{ marginLeft: 6, verticalAlign: 'middle' }} onClick={() => go('terminal')}>📈 Terminal</button></h3>
            <div className="small muted">{mk === 'US' ? ({ SP500: 'S&P 500', NDX: 'Nasdaq-100', ALL: 'All US stocks' }[d?.universe] || 'S&P 500') : (univ === 'ALL' && d?.universe === 'ALL' ? 'All NSE stocks' : univ === 'ALL' ? 'NIFTY 500' : univ.replace('N', 'NIFTY '))} · {d?.rows?.length || 0} stocks · {d?.session ? <>{d.live ? <b style={{ color: 'var(--good)' }}>● Live session </b> : 'Session '}{new Date(d.session + 'T12:00:00').toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric', month: 'short' })} · </> : null}{d?.updated ? `updated ${ago(d.updated)}` : 'loading…'}</div></div>
          <button className="btn small" disabled={st.running} onClick={async () => { await api(`/api/movers/refresh?market=${mk}`, { method: 'POST' }); load() }}>{st.running ? 'Refreshing…' : '↻ Refresh'}</button>
        </div>
        {mk === 'IN' && <div style={{ marginTop: 10 }}><UniverseChips /></div>}
        {mk === 'US' && <div style={{ marginTop: 10 }}><UsUniverseChips /></div>}
        {mk === 'US' && d?.snapshot && (
          <div className="univ-note small">
            {num(d.count, 0)} stocks: {num(d.count - d.snapshot.snapshot, 0)} with daily history (S&P 500, Nasdaq-100) and {num(d.snapshot.snapshot, 0)} from Nasdaq's daily snapshot{d.snapshot.updated ? ` (${ago(d.snapshot.updated)})` : ''}. The snapshot has the day's move, volume and market cap only, so for those stocks{tf === '1D' ? ' 52-week, volume-shock and buyer/seller lists stay empty' : ` there is no ${tf} move`}.
            {(d.snapshot.sources || []).filter((x) => !x.ok).map((x) => <div key={x.exchange} style={{ color: 'var(--bad)' }}>{x.exchange}: could not load ({x.error})</div>)}
          </div>
        )}
        {mk === 'IN' && univ === 'ALL' && d && d.universe !== 'ALL' && !st.running && (
          <div className="univ-note small">
            Prices are loaded for the NIFTY 500 only. <b>Load every NSE stock</b> (~2,000 companies, runs in the background for about 10–15 minutes; after that it refreshes on its own).
            <button className="btn small primary" onClick={async () => { await api(`/api/movers/refresh?market=IN&universe=ALL`, { method: 'POST' }); load() }}>Load all NSE stocks</button>
          </div>
        )}
        {st.running && <><div className="small" style={{ marginTop: 8 }}>Loading prices {st.done}/{st.total}…</div><div className="progress"><div style={{ width: `${st.total ? (st.done / st.total) * 100 : 0}%` }} /></div></>}
        <div className="row" style={{ gap: 6, marginTop: 12 }}>
          {TFS.map((t) => <button key={t} className={`tab ${tf === t ? 'on' : ''}`} style={{ flex: 1 }} onClick={() => setTf(t)}>{t}</button>)}
        </div>
      </div>

      {(!d || (!d.rows.length && st.running)) && <div className="card empty">Fetching prices for the whole index. The first load takes 1–3 minutes, after that it's instant.</div>}

      {d?.rows?.length > 0 && (
        <div className="movers-grid">
          <div className="movers-side">
            {mood && (
              <div className="card">
                <h3>🌡️ Market mood · {tf}</h3>
                <div className="row" style={{ gap: 10, alignItems: 'center' }}>
                  <Gauge score={mood.score} label={mood.label} tone={mood.tone} />
                  <div className="grow small" style={{ lineHeight: 1.5 }}>{mood.read}</div>
                </div>
                <div className="ad-bar" title="Advances vs declines">
                  <div style={{ width: `${(mood.advances / Math.max(mood.advances + mood.declines + mood.unchanged, 1)) * 100}%`, background: 'var(--good)' }} />
                  <div style={{ width: `${(mood.unchanged / Math.max(mood.advances + mood.declines + mood.unchanged, 1)) * 100}%`, background: 'var(--neutral)' }} />
                  <div style={{ flex: 1, background: 'var(--bad)' }} />
                </div>
                <div className="row between small" style={{ marginTop: 4 }}><span className="t-good">▲ {mood.advances} up</span><span className="muted">median {signed(mood.median, 2, '%')}</span><span className="t-bad">{mood.declines} down ▼</span></div>
                <div className="grid3" style={{ marginTop: 10 }}>
                  <div className="tile"><div className="k">Above 200 DMA</div><div className="v">{mood.above200}%</div></div>
                  <div className="tile"><div className="k">Above 50 DMA</div><div className="v">{mood.above50}%</div></div>
                  <div className="tile"><div className="k">52W highs · lows</div><div className="v"><span className="t-good">{mood.new_highs}</span> · <span className="t-bad">{mood.new_lows}</span></div></div>
                </div>
              </div>
            )}
            <div className="card">
              <h3>🗺️ Sector heatmap · {tf}</h3>
              <div className="heat">
                {d.sectors.map((s) => {
                  const a = Math.min(Math.abs(s.avg) / ({ '1D': 2, '1W': 4, '1M': 8, '3M': 15, '1Y': 30 }[tf]), 1)
                  const bg = s.avg >= 0 ? `rgba(34,197,94,${0.15 + a * 0.6})` : `rgba(239,68,68,${0.15 + a * 0.6})`
                  return (
                    <button key={s.sector} className={`heat-cell ${sector === s.sector ? 'on' : ''}`} style={{ background: bg }} onClick={() => setSector(sector === s.sector ? '' : s.sector)}>
                      <div className="hs">{s.sector}</div><div className="hv">{signed(s.avg, 1, '%')}</div><div className="hn">{s.up}/{s.count} up</div>
                    </button>
                  )
                })}
              </div>
              <div className="small muted" style={{ marginTop: 6 }}>Tap a sector to filter the lists. Average move of its stocks {TF_WORD[tf]}.</div>
            </div>
            <div className="card">
              <div className="row between"><h3 style={{ margin: 0 }}>✨ Explain the move</h3><button className="btn small primary" disabled={aiBusy} onClick={explain}>{ai ? '↻ Again' : 'Explain'}</button></div>
              {aiBusy && <div className="small muted" style={{ marginTop: 8 }}>Reading the market…</div>}
              {aiErr && <div className="small t-bad" style={{ marginTop: 8 }}>⚠️ {aiErr}</div>}
              {ai ? <><Md text={ai.text} /><div className="small muted">{ai.model}</div></> : !aiBusy && <p className="small muted" style={{ marginBottom: 0 }}>AI summary of the mood, sector rotation and notable moves, checked against fundamentals.</p>}
            </div>
          </div>

          <div className="movers-main">
            <div className="card" style={{ paddingBottom: 8 }}>
              <div className="list-chips">
                {LISTS.map(([k, l, e]) => (
                  <button key={k} className={`tab ${list === k ? 'on' : ''}`} onClick={() => setList(k)}>{e} {l} <span className="cnt">{counts[k] || 0}</span></button>
                ))}
              </div>
              <div className="small muted" style={{ marginTop: 6 }}>{LISTS.find((l) => l[0] === list)[3]} · {TF_WORD[tf]}.</div>
              <div className="row between wrapflex" style={{ marginTop: 10, gap: 6 }}>
                <div className="row" style={{ gap: 6 }}><button className="btn small" onClick={() => setShowF(!showF)}>⚙️ Filters{activeF ? ` (${activeF})` : ''}</button><FnoToggle /></div>
                {sector && <span className="chip" style={{ cursor: 'pointer', margin: 0, color: 'var(--accent)' }} onClick={() => setSector('')}>{sector} ✕</span>}
              </div>
              {showF && (
                <div className="filters">
                  <label>Min price<input type="number" value={f.minPrice} onChange={(e) => setF({ ...f, minPrice: e.target.value })} /></label>
                  <label>Max price<input type="number" value={f.maxPrice} onChange={(e) => setF({ ...f, maxPrice: e.target.value })} /></label>
                  <label>Min traded value ({money}/day)<input type="number" value={f.minTurn} onChange={(e) => setF({ ...f, minTurn: e.target.value })} /></label>
                  <label>Min market cap ({money})<input type="number" value={f.minCap} onChange={(e) => setF({ ...f, minCap: e.target.value })} /></label>
                  <label>Min EquityLens score<input type="number" value={f.minScore} onChange={(e) => setF({ ...f, minScore: e.target.value })} /></label>
                  <label>Sector<select value={sector} onChange={(e) => setSector(e.target.value)}><option value="">All</option>{d.sectors.map((s) => <option key={s.sector}>{s.sector}</option>)}</select></label>
                  <label className="chk"><input type="checkbox" checked={f.above200} onChange={(e) => setF({ ...f, above200: e.target.checked })} /> Only above 200-day average</label>
                  <label className="chk"><input type="checkbox" checked={f.watch} onChange={(e) => setF({ ...f, watch: e.target.checked })} /> Only my watchlist</label>
                  <button className="btn small" onClick={() => { setF({ minPrice: '', maxPrice: '', minTurn: '', minCap: '', minScore: '', watch: false, above200: false }); setSector('') }}>Clear all</button>
                  <div className="small muted" style={{ gridColumn: '1 / -1' }}>Market cap and score filters use stocks you've scanned in Top Picks ({d.scanned} so far).</div>
                </div>
              )}
            </div>

            <div className="card" style={{ padding: 0 }}>
              {(list === 'quality' || list === 'hype') && d.scanned === 0 && <div className="empty">This list combines price moves with fundamentals.<br />Run a scan in <a href="#/rankings">Top Picks</a> first.</div>}
              {items.length === 0 && !(list === 'quality' || list === 'hype') && <div className="empty">No stocks match {TF_WORD[tf]} with these filters.</div>}
              {items.map((x, i) => {
                const rv = x.ret[tf]
                return (
                  <div key={x.symbol} className="mv-row" onClick={() => go(`stock/${x.symbol}/chart`)}>
                    <div className="rank-num">{i + 1}</div>
                    <Logo sym={x.symbol} name={x.name} size={32} />
                    <div className="grow" style={{ minWidth: 0 }}>
                      <div className="ellip"><b>{x.name}</b> <span className="small muted">{ticker(x.symbol)}</span>{x.fno && <FnoBadge />}{x.closed_high && tf === '1D' && <span className="tagc good">only buyers</span>}{x.closed_low && tf === '1D' && <span className="tagc bad">only sellers</span>}{x.deliv && x.deliv.dq_x >= 1.5 && x.deliv.dp >= 50 && tf === '1D' && <span className="tagc good" title="Delivery % and delivery quantity well above normal">📦 {Math.round(x.deliv.dp)}% delivery</span>}{x.surv && <span className="tagc bad" title={x.surv.join(', ')}>🚨 surveillance</span>}</div>
                      <div className="small muted ellip">{x.sector} · {metric(x)}</div>
                      {x.fund && <span className={`badge sm t-${x.fund.tone} bg-${x.fund.tone}`} style={{ marginTop: 3 }}>{x.fund.overall ?? '—'} · {x.fund.verdict}</span>}
                    </div>
                    <Spark data={x.spark?.slice(-({ '1D': 10, '1W': 10, '1M': 22, '3M': 40, '1Y': 40 }[tf]))} up={rv >= 0} />
                    <div style={{ textAlign: 'right', minWidth: 78 }}>
                      <div><b>{mk === 'US' ? '$' : '₹'}{num(x.price, x.price < 100 ? 2 : 0)}</b></div>
                      <div className={rv >= 0 ? 't-good' : 't-bad'} style={{ fontWeight: 700 }}>{signed(rv, 2, '%')}</div>
                    </div>
                  </div>
                )
              })}
            </div>
            <p className="disclaimer"><span className="src-note">Prices from Yahoo Finance. </span>Prices refresh after every market close and every 15 minutes while the market is open. "Top buyers/sellers" measure volume pressure from daily data, not live order flow.</p>
          </div>
        </div>
      )}
    </div>
  )
}
