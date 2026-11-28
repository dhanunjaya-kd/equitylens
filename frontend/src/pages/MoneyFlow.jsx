import { useEffect, useMemo, useState } from 'react'
import { FnoBadge, Logo, UniverseChips, UsUniverseChips, useUniv, useUsUniv } from '../components/ui'
import { api, getMarket, go, num, ok, signed, ticker } from '../util'
import { ScanBadges } from './Scanners'

// Flow score (stated on the page): average of four percentile ranks among the groups of one level
//   net 5-day flow ÷ the group's delivered (US: traded) value over 10 sessions · delivery vs the 5 sessions before
//   · median 1W move · median 1M move
const median = (xs) => { const v = xs.filter(ok).sort((a, b) => a - b); if (!v.length) return null; const m = v.length >> 1; return v.length % 2 ? v[m] : (v[m - 1] + v[m]) / 2 }
const pctRank = (vals) => {
  const idx = vals.map((v, i) => [v, i]).filter(([v]) => ok(v)).sort((a, b) => a[0] - b[0])
  const out = vals.map(() => null)
  idx.forEach(([, i], k) => { out[i] = idx.length > 1 ? (k / (idx.length - 1)) * 100 : 50 })
  return out
}
const RANKS = [['score', '💰 Flow'], ['net', 'Net 5D'], ['rvol', 'Delivery vs before'], ['r1w', '1W'], ['r1m', '1M'], ['r3m', '3M'], ['r6m', '6M']]

function groupsOf(stocks, level, minN) {
  const by = {}
  for (const s of stocks) { const g = s.g?.[level]; if (g) (by[g] = by[g] || []).push(s) }
  const gs = Object.entries(by).filter(([, xs]) => xs.length >= minN).map(([name, xs]) => {
    const fl = xs.filter((x) => x.flow)
    const net = fl.reduce((a, x) => a + x.flow.flow5, 0)
    const v5 = fl.reduce((a, x) => a + x.flow.val5, 0)
    const p5 = fl.reduce((a, x) => a + x.flow.prev5, 0)
    return { name, stocks: xs, n: xs.length, net: fl.length ? net : null, share: v5 + p5 > 0 ? net / (v5 + p5) : null, rvol: p5 > 0 ? v5 / p5 : null,
      r1w: median(xs.map((x) => x.r1w)), r1m: median(xs.map((x) => x.r1m)), r3m: median(xs.map((x) => x.r3m)), r6m: median(xs.map((x) => x.r6m)) }
  })
  const parts = ['share', 'rvol', 'r1w', 'r1m'].map((k) => pctRank(gs.map((g) => g[k])))
  gs.forEach((g, i) => { const p = parts.map((a) => a[i]).filter(ok); g.score = p.length === 4 ? Math.round(p.reduce((a, b) => a + b, 0) / 4) : null })
  return gs
}
const label = (g) => (g.net === null ? 'no delivery data' : g.net > 0 ? (g.r1m > 0 ? 'Money in, price already up' : 'Money in early') : g.net < 0 ? (g.r1m < 0 ? 'Money leaving, price down' : 'Money leaving') : 'Money flat')
const tone = (v) => (v > 0 ? 'var(--good)' : v < 0 ? 'var(--bad)' : undefined)

function Combined({ stocks }) {
  // equal-weight line of the group's stocks: each stock's last 40 closes rebased to 100, averaged
  const ser = stocks.map((s) => s.spark).filter((p) => p && p.length >= 10)
  if (!ser.length) return null
  const n = Math.min(...ser.map((p) => p.length))
  const line = Array.from({ length: n }, (_, k) => ser.reduce((a, p) => a + (p[p.length - n + k] / p[p.length - n]) * 100, 0) / ser.length)
  const lo = Math.min(...line), hi = Math.max(...line), W = 260, H = 60
  const pts = line.map((v, k) => `${(k / (n - 1)) * W},${H - ((v - lo) / (hi - lo || 1)) * H}`).join(' ')
  const up = line[n - 1] >= line[0]
  return (
    <div className="small muted"><svg width={W} height={H + 4} style={{ display: 'block' }}><polyline points={pts} fill="none" stroke={up ? 'var(--good)' : 'var(--bad)'} strokeWidth="2" /></svg>
      Equal-weight line of {ser.length} stocks, last {n} sessions: {signed(line[n - 1] - 100, 1, '%')}</div>
  )
}

export default function MoneyFlow() {
  const mk = getMarket()
  const [univ] = useUniv()
  const [uu] = useUsUniv()
  const which = mk === 'IN' ? univ : uu
  const [d, setD] = useState(null)
  const [err, setErr] = useState(null)
  const [rank, setRank] = useState('score')
  const [level, setLevel] = useState(null)
  const [open, setOpen] = useState(null)
  const [minN, setMinN] = useState(2)
  const [seg, setSeg] = useState('all')
  const [f, setF] = useState({ turn: '', adr: '', ltp: '', hi: '', lo: '', cmin: '', cmax: '' })
  const [copied, setCopied] = useState(false)
  const load = () => api(`/api/moneyflow?market=${mk}&universe=${which}`).then((x) => { setD(x); setErr(null) }).catch((e) => setErr(e.message))
  useEffect(() => { setD(null); setOpen(null); load() }, [mk, which])
  useEffect(() => { if (!(d?.lookup?.running || d?.status?.running)) return undefined; const t = setTimeout(load, 15000); return () => clearTimeout(t) }, [d])
  const lv = level || (mk === 'IN' ? 'industry' : 'sector')
  const unit = d?.unit || ''
  const money = (v) => (ok(v) ? `${v > 0 ? '+' : v < 0 ? '−' : ''}${mk === 'US' ? '$' : '₹'}${num(Math.abs(v), Math.abs(v) < 10 ? 1 : 0)} ${mk === 'US' ? 'M' : 'Cr'}` : '—')

  const stocks = useMemo(() => (d?.stocks || []).filter((s) => {
    if (seg === 'fno' && !s.fno) return false
    if (seg === 'cash' && s.fno) return false
    const n = (k, v) => f[k] === '' || (ok(v) && v >= +f[k])
    const m = (k, v) => f[k] === '' || (ok(v) && v <= +f[k])
    return n('turn', s.turn) && n('adr', s.adr) && n('ltp', s.price) && m('hi', -(s.from_hi ?? 0)) && m('lo', s.from_lo)
      && (f.cmin === '' || (ok(s.mcap) && s.mcap >= +f.cmin)) && (f.cmax === '' || (ok(s.mcap) && s.mcap <= +f.cmax))
  }), [d, seg, f])
  const byLevel = useMemo(() => Object.fromEntries((d?.levels || []).map(({ key }) => [key, groupsOf(stocks, key, minN)])), [stocks, d, minN])
  const sorted = (gs) => [...gs].sort((a, b) => ((b[rank] ?? -1e18) - (a[rank] ?? -1e18)))
  const groups = sorted(byLevel[lv] || [])
  const byNet = [...(byLevel[lv] || [])].filter((g) => ok(g.net)).sort((a, b) => b.net - a.net)
  const headline = byNet.length >= 4 ? { into: byNet.slice(0, 2).filter((g) => g.net > 0), out: byNet.slice(-2).reverse().filter((g) => g.net < 0) } : null
  const shown = open ? groups.filter((g) => g.name === open) : groups
  const copyTV = () => {
    const seen = new Set()
    const txt = shown.map((g) => [`###${g.name.toUpperCase()}`, ...[...g.stocks].sort((a, b) => (b.flow?.flow5 ?? -1e18) - (a.flow?.flow5 ?? -1e18))
      .filter((s) => !seen.has(s.symbol) && seen.add(s.symbol)).map((s) => (mk === 'US' ? ticker(s.symbol) : `NSE:${s.symbol}`))].join(',\n')).join(',\n')
    navigator.clipboard?.writeText(txt).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500) }).catch(() => {})
  }

  return (
    <div>
      <div className="card">
        <div className="row between wrapflex" style={{ gap: 8 }}>
          <div><h3 style={{ margin: 0 }}>💰 Where money is flowing</h3>
            <div className="small muted">{d ? `${num(stocks.length, 0)} stocks in ${num((byLevel[lv] || []).length, 0)} groups` : 'loading…'}{d?.flow_days?.length ? ` · flow from ${d.flow_days[d.flow_days.length - 1]} to ${d.flow_days[0]}` : ''}{d?.session ? ` · prices ${d.session}` : ''}</div></div>
          <button className="btn small" onClick={copyTV} disabled={!shown.length}>{copied ? 'Copied ✓' : `📋 Copy TradingView list${open ? ` (${open})` : ''}`}</button>
        </div>
        <div style={{ marginTop: 10 }}>{mk === 'IN' ? <UniverseChips /> : <UsUniverseChips />}</div>
        {d?.status?.running && <div className="small" style={{ marginTop: 8 }}>⏳ Loading daily prices for the stock list: {d.status.done}/{d.status.total || '…'} (the same prices as Market Movers and Scanners). Groups fill when this finishes; the page refreshes itself.</div>}
        {d && !d.status?.running && !d.stocks.length && !d.unclassified && <div className="small" style={{ marginTop: 8 }}>No stocks with daily prices yet. Opening Market Movers or Scanners starts the price update.</div>}
        {d?.unclassified > 0 && <div className="small" style={{ marginTop: 8 }}>⏳ {d.unclassified} stocks don't have NSE's classification saved yet, so they're left out of the groups. They're being looked up from NSE in the background (about one a second){d.lookup?.running ? `: ${d.lookup.done}/${d.lookup.total}` : ''}; this page refreshes itself.</div>}
        {headline && (headline.into.length > 0 || headline.out.length > 0) && (
          <div className="mf-head">📌 Money is going into {headline.into.map((g) => <b key={g.name}>{g.name} </b>)}{headline.out.length > 0 && <>and leaving {headline.out.map((g) => <b key={g.name}>{g.name} </b>)}</>}· last 5 sessions</div>
        )}
        <div className="row wrapflex" style={{ gap: 6, marginTop: 10 }}>
          {(d?.levels || []).map(({ key, label: l }) => <button key={key} className={`tab ${lv === key ? 'on' : ''}`} onClick={() => { setLevel(key); setOpen(null) }}>{l}</button>)}
          <span className="small muted" style={{ marginLeft: 8 }}>Rank by</span>
          {RANKS.map(([k, l]) => <button key={k} className={`chip ${rank === k ? 'ipo-on' : ''}`} onClick={() => setRank(k)}>{l}</button>)}
        </div>
        <div className="mf-filters">
          {mk === 'IN' && <div className="row" style={{ gap: 4 }}>{[['all', 'All'], ['fno', 'F&O'], ['cash', 'Cash']].map(([k, l]) => <button key={k} className={`chip ${seg === k ? 'ipo-on' : ''}`} onClick={() => setSeg(k)}>{l}</button>)}</div>}
          {[['turn', `Turnover ≥ (${unit})`], ['adr', 'ADR ≥ %'], ['ltp', 'Price ≥'], ['hi', '≤ % below 52W high'], ['lo', '≤ % above 52W low'], ['cmin', `M.cap ≥ (${unit})`], ['cmax', `M.cap ≤ (${unit})`]].map(([k, l]) => (
            <label key={k} className="small">{l}<input value={f[k]} onChange={(e) => setF({ ...f, [k]: e.target.value })} /></label>
          ))}
          <label className="small">Min stocks<input value={minN} onChange={(e) => setMinN(Math.max(1, +e.target.value || 1))} /></label>
        </div>
      </div>
      {err && <div className="card" style={{ color: 'var(--bad)' }}>{err}</div>}
      {d && !open && (
        <div className="mf-cols">
          {[['Most money coming in', groups.slice(0, 8)], ['Lowest score · money leaving', [...groups].reverse().slice(0, 8)]].map(([title, gs]) => (
            <div key={title} className="card" style={{ marginBottom: 0 }}>
              <div className="small muted" style={{ textTransform: 'uppercase', letterSpacing: '.05em', marginBottom: 6 }}>{title}</div>
              {gs.map((g, k) => (
                <button key={g.name} className="mf-row" onClick={() => setOpen(g.name)}>
                  <span className="muted" style={{ width: 18 }}>{k + 1}</span>
                  <span className="grow" style={{ minWidth: 0 }}><b className="ellip" style={{ display: 'block' }}>{g.name}</b><small style={{ color: tone(g.net) }}>{label(g)} · {g.n} stocks</small></span>
                  <span className={`mf-score ${g.score >= 60 ? 'g' : g.score <= 40 ? 'r' : ''}`}>{g.score ?? '—'}</span>
                  <span style={{ minWidth: 92, textAlign: 'right', color: tone(g.net), fontWeight: 700 }}>{rank === 'score' || rank === 'net' ? money(g.net) : rank === 'rvol' ? (ok(g.rvol) ? `${num(g.rvol, 2)}×` : '—') : signed(g[rank], 1, '%')}</span>
                </button>
              ))}
            </div>
          ))}
        </div>
      )}
      {d && (
        <div className="card">
          <div className="row between" style={{ marginBottom: 6 }}><b>{open ? `${open}` : `All ${(d.levels.find((x) => x.key === lv) || {}).label?.toLowerCase()} groups`}</b>{open && <button className="btn small" onClick={() => setOpen(null)}>← All groups</button>}</div>
          {!open && (
            <div className="tbl-wrap"><table className="tbl mf-tbl"><thead><tr><th style={{ textAlign: 'left' }}>Group</th><th>Score</th><th>Net 5D</th><th>Delivery vs before</th><th>1W</th><th>1M</th><th>3M</th><th>6M</th><th>Stocks</th></tr></thead>
              <tbody>{groups.map((g) => (
                <tr key={g.name} onClick={() => setOpen(g.name)} style={{ cursor: 'pointer' }}>
                  <td style={{ textAlign: 'left' }}><b>{g.name}</b><div className="small" style={{ color: tone(g.net) }}>{label(g)}</div></td>
                  <td><span className={`mf-score ${g.score >= 60 ? 'g' : g.score <= 40 ? 'r' : ''}`}>{g.score ?? '—'}</span></td>
                  <td style={{ color: tone(g.net) }}>{money(g.net)}</td><td>{ok(g.rvol) ? `${num(g.rvol, 2)}×` : '—'}</td>
                  {['r1w', 'r1m', 'r3m', 'r6m'].map((k) => <td key={k} style={{ color: tone(g[k]) }}>{signed(g[k], 1, '%')}</td>)}
                  <td>{g.n}</td>
                </tr>
              ))}</tbody></table></div>
          )}
          {open && shown[0] && (
            <>
              <div className="grid4" style={{ marginBottom: 10 }}>
                <div className="tile"><div className="k">Flow score</div><div className="v">{shown[0].score ?? '—'}</div></div>
                <div className="tile"><div className="k">Net 5 sessions</div><div className="v" style={{ color: tone(shown[0].net) }}>{money(shown[0].net)}</div></div>
                <div className="tile"><div className="k">Delivery vs before</div><div className="v">{ok(shown[0].rvol) ? `${num(shown[0].rvol, 2)}×` : '—'}</div></div>
                <div className="tile"><div className="k">Median 1M</div><div className="v" style={{ color: tone(shown[0].r1m) }}>{signed(shown[0].r1m, 1, '%')}</div></div>
              </div>
              <Combined stocks={shown[0].stocks} />
              <div className="tbl-wrap" style={{ marginTop: 8 }}><table className="tbl mf-tbl"><thead><tr><th style={{ textAlign: 'left' }}>Stock</th><th>Net 5D</th><th>1D</th><th>1W</th><th>1M</th><th>ADR</th><th>RS</th><th>% 52W H</th><th>Turnover</th></tr></thead>
                <tbody>{[...shown[0].stocks].sort((a, b) => (b.flow?.flow5 ?? -1e18) - (a.flow?.flow5 ?? -1e18)).map((s) => (
                  <tr key={s.symbol} onClick={() => go(`stock/${s.symbol}`)} style={{ cursor: 'pointer' }}>
                    <td style={{ textAlign: 'left', whiteSpace: 'normal', minWidth: 200 }}><span className="co"><Logo sym={s.symbol} name={s.name} size={22} /><span className="nm"><b>{ticker(s.symbol)}</b>{s.fno && <FnoBadge />}<small>{s.name}</small></span></span><ScanBadges tags={s.tags} only={['leader', 'vcp', 'flag', 'cup_handle', 'pocket_pivot', 'bull_snort', 'minervini', 'rs_first']} /></td>
                    <td style={{ color: tone(s.flow?.flow5) }}>{money(s.flow?.flow5)}</td>
                    {['r1d', 'r1w', 'r1m'].map((k) => <td key={k} style={{ color: tone(s[k]) }}>{signed(s[k], 1, '%')}</td>)}
                    <td>{ok(s.adr) ? num(s.adr, 1) : '—'}</td><td>{s.rs ?? '—'}</td><td>{signed(s.from_hi, 1, '%')}</td><td>{ok(s.turn) ? num(s.turn, 1) : '—'}</td>
                  </tr>
                ))}</tbody></table></div>
            </>
          )}
        </div>
      )}
      {d && (
        <div className="small muted" style={{ padding: '0 6px 14px', lineHeight: 1.6 }}>
          <div><b>How money flow is measured:</b> {d.method}</div>
          <div><b>Flow score (0-100):</b> among the groups shown, the average of four ranks: net 5-day flow as a share of the group's {mk === 'IN' ? 'delivered' : 'traded'} value over 10 sessions, {mk === 'IN' ? 'delivery' : 'traded value'} in the last 5 sessions vs the 5 before, median 1-week move and median 1-month move. Groups are {mk === 'IN' ? "NSE's own classification (macro sector › sector › industry › basic industry)" : 'GICS sector and sub-industry (S&P 500 list) or Nasdaq\'s industry'}. Price moves are medians of the group's stocks.</div>
        </div>
      )}
    </div>
  )
}
