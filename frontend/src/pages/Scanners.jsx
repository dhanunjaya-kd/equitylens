import { useEffect, useMemo, useState } from 'react'
import { FnoBadge, Logo, UniverseChips, UsUniverseChips, useFno, useUniv, useUsUniv } from '../components/ui'
import { api, getMarket, go, num, ok, signed, ticker } from '../util'

// short badge text for each scanner (used here and on Market Movers)
export const TAG_SHORT = {
  vcp: 'VCP', leader: '👑 Leader', pocket_pivot: 'Pocket pivot', bull_snort: 'Bull snort', flag: '🚩 Flag', cup_handle: 'Cup & handle',
  double_bottom: 'W bottom', flat_base: 'Flat base', wtc: '3 weeks tight', inside_bar: 'Inside bar', nr7: 'NR7', mini_coil: 'Mini coil',
  minervini: 'Minervini ✓', stage2: 'Stage 2', ti65: 'TI65', rs_first: 'RS high first', gap_up: 'Gap up', highest_volume: 'Top volume', lowest_volume: 'Volume dry-up',
}
const TAG_TONE = { vcp: 'p', leader: 'y', pocket_pivot: 'g', bull_snort: 'g', flag: 'r', cup_handle: 'p', double_bottom: 'p', flat_base: 'p', minervini: 'g', rs_first: 'b', gap_up: 'g' }
export function ScanBadges({ tags = [], only, results }) {
  const list = only ? tags.filter((t) => only.includes(t)) : tags
  if (!list.length) return null
  return <span className="scan-badges">{list.map((t) => <span key={t} className={`scb ${TAG_TONE[t] || ''}`}>{TAG_SHORT[t] || t}{t === 'gap_up' && results ? ' · results' : ''}</span>)}</span>
}

const COLS = [
  ['chg', '1D %'], ['price', 'LTP'], ['adr', 'ADR %'], ['rs', 'RS'], ['ti65', 'TI65'], ['lin', 'Linearity'],
  ['from_hi', '% 52W H'], ['from_lo', '% 52W L'], ['mcap', 'M.cap'], ['turn20', 'Turnover'],
]
const tone = (v) => (v > 0 ? 'var(--good)' : v < 0 ? 'var(--bad)' : undefined)

function Record({ rec, keys, rules, horizons }) {
  if (!rec) return <div className="small muted">The tested record is built with the next price update (once a day) — it needs every stock's 2-year history.</div>
  const base = rec.baseline || {}
  const rows = keys.map((k) => [k, rec.scanners?.[k]])
  return (
    <div className="tbl-wrap">
      <table className="tbl scan-rec">
        <thead><tr><th style={{ textAlign: 'left' }}>After the signal</th>{horizons.map((h) => <th key={h} colSpan={3}>{h} sessions later</th>)}</tr>
          <tr><th />{horizons.map((h) => [<th key={`${h}m`}>median</th>, <th key={`${h}w`}>up</th>, <th key={`${h}n`}>signals</th>])}</tr></thead>
        <tbody>
          {rows.map(([k, r]) => (
            <tr key={k}>
              <td style={{ textAlign: 'left' }}><b>{rules[k]?.name}</b></td>
              {horizons.map((h) => {
                const x = r?.[h]
                const few = !x || x.n < 30
                return [
                  <td key={`${h}m`} style={{ color: few ? undefined : tone(x.median - (base[h]?.median || 0)) }}>{x ? signed(x.median, 1, '%') : '—'}</td>,
                  <td key={`${h}w`}>{x ? `${num(x.win, 0)}%` : '—'}</td>,
                  <td key={`${h}n`} className="muted">{x ? (few ? `${x.n} (too few)` : num(x.n, 0)) : '0'}</td>,
                ]
              })}
            </tr>
          ))}
          <tr className="muted"><td style={{ textAlign: 'left' }}>Any stock, any day (baseline)</td>
            {horizons.map((h) => [<td key={`${h}m`}>{base[h] ? signed(base[h].median, 1, '%') : '—'}</td>, <td key={`${h}w`}>{base[h] ? `${num(base[h].win, 0)}%` : '—'}</td>, <td key={`${h}n`}>{base[h] ? num(base[h].n, 0) : '—'}</td>])}</tr>
        </tbody>
      </table>
      <div className="small muted" style={{ marginTop: 6 }}>
        {rec.stocks} stocks · signals from {rec.from} to {rec.to}, checked at each day's close; move = close to close. Green = median better than the baseline.
        Limits: only stocks in today's list, about one year of signals, no costs. Under 30 signals is too few to read anything into.
      </div>
    </div>
  )
}

export default function Scanners() {
  const mk = getMarket()
  const [univ] = useUniv()
  const [uu] = useUsUniv()
  const [fno] = useFno()
  const [d, setD] = useState(null)
  const [err, setErr] = useState(null)
  const [sel, setSel] = useState(() => { try { return JSON.parse(localStorage.getItem('eql_scan_sel') || '["vcp"]') } catch { return ['vcp'] } })
  const [sort, setSort] = useState(['rs', -1])
  const [f, setF] = useState({ adr: '', turn: '', rs: '' })
  const [copied, setCopied] = useState(false)
  const which = mk === 'IN' ? univ : uu
  const load = () => api(`/api/scanners?market=${mk}&universe=${which}`).then((x) => { setD(x); setErr(null) }).catch((e) => setErr(e.message))
  useEffect(() => { setD(null); load() }, [mk, which])
  useEffect(() => { const r = d?.status?.running; if (!r) return undefined; const t = setTimeout(load, 8000); return () => clearTimeout(t) }, [d])
  useEffect(() => { try { localStorage.setItem('eql_scan_sel', JSON.stringify(sel)) } catch { /* ignore */ } }, [sel])

  const counts = useMemo(() => {
    const c = {}
    for (const r of d?.rows || []) for (const t of r.tags) c[t] = (c[t] || 0) + 1
    return c
  }, [d])
  const unit = mk === 'US' ? 1e6 : 1e7
  const unitL = mk === 'US' ? '$ M' : '₹ Cr'
  const rows = useMemo(() => {
    let r = (d?.rows || []).filter((x) => sel.every((t) => x.tags.includes(t)))
    if (fno && mk === 'IN') r = r.filter((x) => x.fno)
    if (f.adr !== '') r = r.filter((x) => (x.adr || 0) >= +f.adr)
    if (f.turn !== '') r = r.filter((x) => (x.turn20 || 0) / unit >= +f.turn)
    if (f.rs !== '') r = r.filter((x) => (x.rs || 0) >= +f.rs)
    const [k, dir] = sort
    return [...r].sort((a, b) => ((a[k] ?? -1e18) - (b[k] ?? -1e18)) * dir)
  }, [d, sel, fno, f, sort, mk, unit])
  const toggle = (k) => setSel(sel.includes(k) ? sel.filter((x) => x !== k) : [...sel, k])
  const copyTV = () => {
    const txt = rows.map((r) => (mk === 'US' ? ticker(r.symbol) : `NSE:${r.symbol}`)).join(',\n')
    navigator.clipboard?.writeText(txt).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500) }).catch(() => {})
  }
  const rules = d?.rules || {}
  const list = mk === 'US' ? ({ SP500: 'S&P 500', NDX: 'Nasdaq-100', ALL: 'S&P 500 + Nasdaq-100' }[which] || 'S&P 500') : ({ N50: 'NIFTY 50', N100: 'NIFTY 100', N500: 'NIFTY 500', ALL: 'All NSE' }[which] || 'NIFTY 500')

  return (
    <div className="scanners">
      <div className="card">
        <div className="row between wrapflex" style={{ gap: 8 }}>
          <div>
            <h2 style={{ margin: '2px 0' }}>🔎 Scanners</h2>
            <div className="small muted">{list} · {d ? `${num(d.rows.length, 0)} stocks with daily history` : 'loading…'}{d?.session ? ` · session ${d.session}` : ''} · every scanner is one written rule; tick several to combine them</div>
          </div>
          {d?.status?.running && <div className="small">Loading prices {d.status.done}/{d.status.total}…</div>}
        </div>
        <div style={{ marginTop: 10 }}>{mk === 'IN' ? <UniverseChips /> : <UsUniverseChips />}</div>
        {mk === 'US' && which === 'ALL' && <div className="small muted" style={{ marginTop: 6 }}>Scanners need daily history, which the app keeps for the S&P 500 and Nasdaq-100; other US stocks have only Nasdaq's daily snapshot.</div>}
      </div>
      {err && <div className="card" style={{ color: 'var(--bad)' }}>{err}</div>}
      {d && (
        <div className="scan-menu">
          {d.groups.map((g) => (
            <div key={g.key} className="card scan-group">
              <div className="small muted" style={{ letterSpacing: '.05em', textTransform: 'uppercase', marginBottom: 6 }}>{g.label}</div>
              {g.items.map((k) => (
                <button key={k} className={`scan-item ${sel.includes(k) ? 'on' : ''}`} onClick={() => toggle(k)} title={rules[k]?.rule}>
                  <span><b>{rules[k]?.name}</b><small>{rules[k]?.short}</small></span><span className="scan-n">{counts[k] || 0}</span>
                </button>
              ))}
            </div>
          ))}
        </div>
      )}
      {d && sel.length > 0 && (
        <div className="card">
          <h3 style={{ marginTop: 0 }}>{sel.map((k) => rules[k]?.name).join(' + ')} <span className="small muted">· the rules</span></h3>
          {sel.map((k) => <div key={k} className="small" style={{ marginBottom: 6 }}><b>{rules[k]?.name}:</b> {rules[k]?.rule}</div>)}
          <h4 style={{ marginBottom: 6 }}>Tested record</h4>
          <Record rec={d.record} keys={sel} rules={rules} horizons={d.horizons} />
        </div>
      )}
      {d && (
        <div className="card">
          <div className="row between wrapflex" style={{ gap: 8, marginBottom: 8 }}>
            <b>{sel.length ? `${rows.length} stocks meet ${sel.length > 1 ? 'all of these' : 'this'} today` : `${rows.length} stocks`}</b>
            <div className="row wrapflex" style={{ gap: 6 }}>
              <label className="small">ADR ≥ <input style={{ width: 54 }} value={f.adr} onChange={(e) => setF({ ...f, adr: e.target.value })} placeholder="%" /></label>
              <label className="small">Turnover ≥ <input style={{ width: 64 }} value={f.turn} onChange={(e) => setF({ ...f, turn: e.target.value })} placeholder={unitL} /></label>
              <label className="small">RS ≥ <input style={{ width: 48 }} value={f.rs} onChange={(e) => setF({ ...f, rs: e.target.value })} placeholder="1-99" /></label>
              <button className="btn small" onClick={copyTV} disabled={!rows.length}>{copied ? 'Copied ✓' : '📋 Copy TradingView list'}</button>
            </div>
          </div>
          {!rows.length ? <div className="small muted">No stock meets {sel.length > 1 ? 'all of these rules' : 'this rule'} today.</div> : (
            <div className="tbl-wrap">
              <table className="tbl scan-tbl">
                <thead><tr><th style={{ textAlign: 'left' }}>Stock</th>
                  {COLS.map(([k, l]) => <th key={k} onClick={() => setSort([k, sort[0] === k ? -sort[1] : -1])} style={{ cursor: 'pointer' }}>{l}{sort[0] === k ? (sort[1] < 0 ? ' ▾' : ' ▴') : ''}</th>)}</tr></thead>
                <tbody>
                  {rows.slice(0, 400).map((r) => (
                    <tr key={r.symbol} onClick={() => go(`stock/${r.symbol}`)} style={{ cursor: 'pointer' }}>
                      <td style={{ textAlign: 'left', whiteSpace: 'normal', minWidth: 220 }}>
                        <span className="co"><Logo sym={r.symbol} name={r.name} size={24} /><span className="nm"><b>{ticker(r.symbol)}</b>{r.fno && <FnoBadge />}<small>{r.sector}</small></span></span>
                        <ScanBadges tags={r.tags.filter((t) => !sel.includes(t))} results={r.results} />
                      </td>
                      <td style={{ color: tone(r.chg) }}>{ok(r.chg) ? signed(r.chg, 2, '%') : '—'}</td>
                      <td>{num(r.price, 2)}</td>
                      <td>{ok(r.adr) ? num(r.adr, 2) : '—'}</td>
                      <td><b style={{ color: r.rs >= 80 ? 'var(--good)' : r.rs <= 30 ? 'var(--bad)' : undefined }}>{r.rs ?? '—'}</b></td>
                      <td style={{ color: r.ti65 >= 1.05 ? 'var(--good)' : r.ti65 < 1 ? 'var(--bad)' : undefined }}>{ok(r.ti65) ? num(r.ti65, 2) : '—'}</td>
                      <td>{ok(r.lin) ? num(r.lin, 2) : '—'}</td>
                      <td style={{ color: tone(r.from_hi) }}>{ok(r.from_hi) ? signed(r.from_hi, 1, '%') : '—'}</td>
                      <td style={{ color: tone(r.from_lo) }}>{ok(r.from_lo) ? signed(r.from_lo, 0, '%') : '—'}</td>
                      <td>{ok(r.mcap) ? num(r.mcap, 0) : '—'}</td>
                      <td>{ok(r.turn20) ? num(r.turn20 / unit, 1) : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {rows.length > 400 && <div className="small muted">Showing the first 400 by your sort.</div>}
            </div>
          )}
          <div className="small muted" style={{ marginTop: 8 }}>
            {Object.entries(d.indicators || {}).map(([k, t]) => <div key={k}>{t}</div>)}
            <div>M.cap in {mk === 'US' ? '$ M' : '₹ Cr'} (from the company scan, or Nasdaq for US); Turnover in {unitL}, 20-day average. Signals are as of the last session's close.</div>
          </div>
        </div>
      )}
    </div>
  )
}
