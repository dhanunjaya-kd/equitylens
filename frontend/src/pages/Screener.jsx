import { useEffect, useMemo, useState } from 'react'
import { FnoBadge, FnoToggle, Logo, ScoreRing, UniverseChips, useFno, useUniv } from '../components/ui'
import FnoScanner from '../components/FnoScanner'
import { ExplainList } from './AI'
import { api, cr, getMarket, go, inUniv, num, ok, saveLocal, ticker, univLabel } from '../util'

// key, label, group, unit
export const FIELDS = [
  ['overall', 'Overall score', 'Scores', ''], ['business', 'Business score', 'Scores', ''], ['valuation', 'Valuation score', 'Scores', ''],
  ['growth', 'Growth score', 'Scores', ''], ['quality', 'Quality score', 'Scores', ''],
  ['market_cap', 'Market cap (₹ Cr / $ M)', 'Size', ''], ['price', 'Price', 'Size', ''], ['off_high_pct', '% from 52w high', 'Size', '%'],
  ['pe', 'P/E', 'Valuation', ''], ['pb', 'Price / Book', 'Valuation', 'x'], ['peg', 'PEG', 'Valuation', ''],
  ['pe_vs_median', 'P/E ÷ own 10y median', 'Valuation', 'x'], ['ev_ebitda', 'EV / EBITDA', 'Valuation', 'x'],
  ['earnings_yield', 'Earnings yield', 'Valuation', '%'], ['dividend_yield', 'Dividend yield', 'Valuation', '%'],
  ['fair_value_upside', 'Upside to fair value', 'Valuation', '%'], ['margin_of_safety', 'Margin of safety', 'Valuation', '%'],
  ['graham_upside', 'Upside to Graham number', 'Valuation', '%'],
  ['sales_cagr_3', 'Sales growth 3y', 'Growth', '%'], ['sales_cagr_5', 'Sales growth 5y', 'Growth', '%'], ['sales_cagr_10', 'Sales growth 10y', 'Growth', '%'],
  ['profit_cagr_3', 'Profit growth 3y', 'Growth', '%'], ['profit_cagr_5', 'Profit growth 5y', 'Growth', '%'], ['profit_cagr_10', 'Profit growth 10y', 'Growth', '%'],
  ['eps_cagr_5', 'EPS growth 5y', 'Growth', '%'],
  ['roce', 'ROCE (ROE for lenders) 5y', 'Quality', '%'], ['roe', 'ROE 5y', 'Quality', '%'], ['opm', 'Operating margin', 'Quality', '%'],
  ['debt_to_equity', 'Debt / equity', 'Safety', 'x'], ['interest_coverage', 'Interest coverage', 'Safety', 'x'],
  ['cfo_to_pat', 'Cash conversion (CFO ÷ profit)', 'Safety', 'x'],
  ['promoter', 'Promoter holding', 'Ownership', '%'], ['promoter_change', 'Promoter change (2y, pts)', 'Ownership', ''],
  ['inst_change', 'FII+DII change (2y, pts)', 'Ownership', ''], ['pledged', 'Pledged %', 'Ownership', '%'],
  ['piotroski', 'Piotroski F (0-9)', 'Forensics', ''], ['altman_z', 'Altman Z', 'Forensics', ''], ['beneish_m', 'Beneish M', 'Forensics', ''],
  ['high_flags', 'High red flags (count)', 'Forensics', ''],
  ['base_3y', 'Base-case return 3y', 'Outlook', '%'], ['base_5y', 'Base-case return 5y', 'Outlook', '%'], ['base_10y', 'Base-case return 10y', 'Outlook', '%'],
  ['is_holdco', 'Holding / investment company', 'Type', 'bool'], ['is_financial', 'Bank / NBFC', 'Type', 'bool'], ['fno', 'F&O stock (NSE)', 'Type', 'bool'],
  ['ret_1w', 'Return 1 week', 'Trend & money (live)', '%'], ['ret_1m', 'Return 1 month', 'Trend & money (live)', '%'],
  ['ret_3m', 'Return 3 months', 'Trend & money (live)', '%'], ['ret_1y', 'Return 1 year', 'Trend & money (live)', '%'],
  ['near_high', '% from 52w high (live)', 'Trend & money (live)', '%'], ['rvol', 'Relative volume today', 'Trend & money (live)', 'x'],
  ['above50', 'Above 50-day average', 'Trend & money (live)', 'bool'], ['above200', 'Above 200-day average', 'Trend & money (live)', 'bool'],
  ['dp', 'Delivery % today (NSE)', 'Trend & money (live)', '%'], ['deliv_x', 'Delivery qty vs 10-day avg', 'Trend & money (live)', 'x'],
  ['insider_net', 'Insider net buying (₹ Cr / $ M)', 'Trend & money (live)', ''], ['insider_buying', 'Insiders / promoters buying', 'Trend & money (live)', 'bool'],
  ['surveillance', 'Under NSE surveillance', 'Trend & money (live)', 'bool'],
]
const F = Object.fromEntries(FIELDS.map(([k, l, g, u]) => [k, { label: l, group: g, unit: u }]))
// fields that only exist for NSE stocks (promoters, pledges, delivery, F&O, NSE surveillance): not offered in the US view
const IN_ONLY_F = new Set(['promoter', 'promoter_change', 'inst_change', 'pledged', 'fno', 'dp', 'deliv_x', 'surveillance'])
const fieldsFor = (mk) => FIELDS.filter((f) => mk !== 'US' || !IN_ONLY_F.has(f[0])).map((f) => (mk === 'US' && f[0] === 'market_cap' ? [f[0], 'Market cap ($ M)', f[2], f[3]] : f))

// ⭐ EquityLens signature scans: each combines the business, the price trend and the money flow
export const SIGNATURE = [
  { name: 'Quality breakout', emoji: '🚀', tone: 'good',
    what: 'Strong businesses trading near a 52-week high, above their 50- and 200-day averages, with no red flags.',
    why: 'Good companies making new highs tend to keep leading: the business and the market agree.',
    next: 'Open the Chart tab: buy-zones are pullbacks to the 20/50 EMA, the risk line is the last swing low.',
    needs: 'Movers', rules: [['business', '>=', 65], ['above200', '=', 1], ['above50', '=', 1], ['near_high', '>=', -5], ['high_flags', '=', 0], ['surveillance', '=', 0]] },
  { name: 'Smart-money accumulation', emoji: '🧭', tone: 'ok',
    what: 'Decent businesses where real money is buying: delivery well above normal (India) or insiders buying (US).',
    why: 'Delivery and insider buying show conviction that intraday volume and price alone cannot.',
    next: 'Open Smart money on the stock: check who is buying, the 10-day delivery bars and any deals.',
    needs: 'Money', rules: [['business', '>=', 60], ['deliv_x', '>=', 1.3], ['dp', '>=', 45], ['ret_1m', '>=', 0], ['surveillance', '=', 0]],
    rulesUS: [['business', '>=', 60], ['insider_buying', '=', 1], ['high_flags', '=', 0]] },
  { name: 'Quality on sale', emoji: '💎', tone: 'warn',
    what: 'Great businesses (score 70+) that fell 15%+ from their high but still look undervalued, with healthy forensics.',
    why: 'Long-term returns come from buying excellent companies when the market is temporarily pessimistic.',
    next: 'Check the Overview red flags and the latest quarter: make sure the fall is the market, not the business.',
    needs: null, rules: [['business', '>=', 70], ['off_high_pct', '<=', -15], ['fair_value_upside', '>=', 10], ['piotroski', '>=', 6], ['high_flags', '=', 0]] },
]

export const PRESETS = [
  { name: 'Quality compounders', desc: 'High returns, steady growth, low debt, real cash', rules: [['roce', '>=', 20], ['profit_cagr_5', '>=', 15], ['debt_to_equity', '<=', 0.5], ['cfo_to_pat', '>=', 0.8]] },
  { name: 'Value with quality', desc: 'Cheap P/E but still a good business', rules: [['pe', '<=', 18], ['roce', '>=', 15], ['piotroski', '>=', 6], ['high_flags', '=', 0]] },
  { name: 'Below fair value', desc: 'Fair-value estimates well above price', rules: [['fair_value_upside', '>=', 20], ['business', '>=', 60]] },
  { name: 'Holding-company discount', inOnly: true, desc: 'Elcid-type: investment cos far below book', rules: [['is_holdco', '=', 1], ['pb', '<=', 0.5]] },
  { name: 'Debt-free growers', desc: 'No debt, double-digit growth', rules: [['debt_to_equity', '<=', 0.1], ['sales_cagr_5', '>=', 12], ['profit_cagr_5', '>=', 12]] },
  { name: 'Improving fast (Piotroski 8+)', desc: 'Fundamentals improving on almost every test', rules: [['piotroski', '>=', 8]] },
  { name: 'Promoters buying', inOnly: true, desc: 'Insiders raising their stake, no big red flags', rules: [['promoter_change', '>=', 1], ['high_flags', '=', 0]] },
  { name: 'Cheap vs own history', desc: 'P/E below 10-yr median, safe balance sheet', rules: [['pe_vs_median', '<=', 0.85], ['altman_z', '>=', 3], ['profit_cagr_5', '>=', 8]] },
  { name: '10-year compounders', desc: 'Best base-case 10y return with a strong business', rules: [['base_10y', '>=', 13], ['business', '>=', 70]] },
]

const pass = (row, [k, op, v]) => {
  const x = row[k]
  if (F[k]?.unit === 'bool') return op === '=' ? Boolean(x) === Boolean(+v) : Boolean(x) !== Boolean(+v)
  if (!ok(x) || x === null) return false
  if (op === '>=') return x >= v
  if (op === '<=') return x <= v
  if (op === '>') return x > v
  if (op === '<') return x < v
  return x === v
}
const fmt = (k, v) => {
  const u = F[k]?.unit
  if (u === 'bool') return v ? 'Yes' : 'No'
  if (!ok(v) || v === null) return '—'
  if (k === 'market_cap') return cr(v)
  return `${num(v, Math.abs(v) < 10 ? 2 : 1)}${u === '%' ? '%' : u === 'x' ? 'x' : ''}`
}
const loadSaved = () => { try { return JSON.parse(localStorage.getItem('eql_screens') || '[]') } catch { return [] } }

export default function Screener() {
  const [rows, setRows] = useState(null)
  const [rules, setRules] = useState(PRESETS[0].rules)
  const [sort, setSort] = useState('overall')
  const [saved, setSaved] = useState(loadSaved())
  const [name, setName] = useState('')
  const [active, setActive] = useState(PRESETS[0].name)
  const mk = getMarket()
  const [fno] = useFno()
  const [univ] = useUniv()
  useEffect(() => { api(`/api/rankings?market=${mk}`).then((d) => setRows(d.rows || [])).catch(() => setRows([])) }, [mk])
  const base = useMemo(() => (rows || []).filter((r) => mk === 'US' || ((!fno || r.fno) && inUniv(r, univ))), [rows, fno, mk, univ])
  const sigRules = (p) => (mk === 'US' && p.rulesUS ? p.rulesUS : p.rules)
  const count = (rs) => base.filter((r) => rs.every((ru) => pass(r, ru))).length
  const hasLive = (rows || []).some((r) => r.above200 !== undefined)
  const hasMoney = (rows || []).some((r) => (mk === 'US' ? r.insider_net !== null && r.insider_net !== undefined : r.deliv_x !== undefined))

  const res = useMemo(() => base.filter((r) => rules.every((ru) => pass(r, ru)))
    .sort((a, b) => (ok(b[sort]) ? b[sort] : -1e9) - (ok(a[sort]) ? a[sort] : -1e9)), [base, rules, sort])
  const stale = rows && rows.length > 0 && rows.filter((r) => r.piotroski === undefined).length > rows.length / 2

  const setRule = (i, part, val) => setRules(rules.map((r, j) => (j === i ? r.map((p, k) => (k === part ? val : p)) : r)))
  const save = () => {
    if (!name.trim()) return
    const s = [{ name: name.trim(), rules }, ...saved.filter((x) => x.name !== name.trim())]
    setSaved(s); saveLocal('eql_screens', s)
    setActive(name.trim()); setName('')
  }
  const del = (n) => { const s = saved.filter((x) => x.name !== n); setSaved(s); saveLocal('eql_screens', s) }
  const usePreset = (p) => { setRules(p.rules); setActive(p.name) }
  const showCols = [...new Set(rules.map((r) => r[0]))].filter((k) => F[k]?.unit !== 'bool').slice(0, 4)

  return (
    <>
      <div className="card">
        <div className="row between wrapflex" style={{ gap: 8 }}>
          <h3 style={{ margin: 0 }}>{mk === 'US' ? '🇺🇸' : '🇮🇳'} Screener</h3>
          <div className="row wrapflex" style={{ gap: 8 }}><UniverseChips /><FnoToggle count={fno && rows ? base.length : undefined} /></div>
        </div>
        <div className="small muted" style={{ margin: '4px 0 12px' }}>Start with an EquityLens signature scan, or pick a ready-made screen and tweak the rules below.</div>
        <div className="sig-grid">
          {SIGNATURE.map((p) => {
            const rs = sigRules(p)
            const missing = (p.needs === 'Movers' && !hasLive) || (p.needs === 'Money' && !hasMoney)
            return (
              <div key={p.name} className={`sig-card sig-${p.tone} ${active === p.name ? 'on' : ''}`} onClick={() => usePreset({ ...p, rules: rs })}>
                <div className="row between"><b className="sig-title">{p.emoji} {p.name}</b>{rows && <span className="sig-count">{count(rs)}</span>}</div>
                <div className="small">{p.what}</div>
                <div className="small muted sig-why">💡 {p.why}</div>
                {missing && <div className="small t-warn">Needs live data: open {p.needs === 'Movers' ? 'Market Movers' : mk === 'US' ? 'Smart Money' : 'Smart Money → Delivery'} once.</div>}
                {active === p.name && <div className="small sig-next">👉 {p.next}</div>}
              </div>
            )
          })}
        </div>
        {mk !== 'US' && <FnoScanner />}
        <div className="small muted" style={{ margin: '14px 0 8px', fontWeight: 700 }}>More ready-made screens</div>
        <div className="preset-row">
          {[...saved.map((s) => ({ ...s, desc: 'Saved screen', mine: true })), ...PRESETS.filter((p) => !(mk === 'US' && p.inOnly))].map((p) => (
            <div key={p.name} className="tile preset" style={{ cursor: 'pointer', borderColor: active === p.name ? 'var(--accent)' : null }} onClick={() => usePreset(p)}>
              <div className="row between"><b style={{ fontSize: 13 }}>{p.mine ? '★ ' : ''}{p.name}</b>
                {p.mine && <span className="small muted" onClick={(e) => { e.stopPropagation(); del(p.name) }}>✕</span>}</div>
              <div className="small muted" style={{ marginTop: 3 }}>{p.desc}</div>
            </div>
          ))}
        </div>
      </div>

      <div className="card">
        <h3>Rules <span className="small muted">(all must match)</span></h3>
        {rules.map((r, i) => (
          <div key={i} className="row" style={{ gap: 6, marginBottom: 8 }}>
            <select style={{ flex: 2, minWidth: 0 }} value={r[0]} onChange={(e) => {
              const k = e.target.value
              setRules(rules.map((x, j) => (j === i ? (F[k].unit === 'bool' ? [k, '=', 1] : [k, x[1] === '=' ? '>=' : x[1], x[2]]) : x)))
            }}>
              {[...new Set(fieldsFor(mk).map((f) => f[2]))].map((g) => (
                <optgroup key={g} label={g}>{fieldsFor(mk).filter((f) => f[2] === g).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</optgroup>
              ))}
            </select>
            {F[r[0]]?.unit === 'bool' ? (
              <select style={{ flex: 1.3, minWidth: 0 }} value={r[2]} onChange={(e) => setRule(i, 2, +e.target.value)}><option value={1}>Yes</option><option value={0}>No</option></select>
            ) : (
              <>
                <select style={{ width: 62 }} value={r[1]} onChange={(e) => setRule(i, 1, e.target.value)}>{['>=', '<=', '>', '<', '='].map((o) => <option key={o}>{o}</option>)}</select>
                <input style={{ width: 74 }} type="number" inputMode="decimal" value={r[2]} onChange={(e) => setRule(i, 2, e.target.value === '' ? '' : +e.target.value)} />
              </>
            )}
            <button className="btn small" onClick={() => setRules(rules.filter((_, j) => j !== i))}>✕</button>
          </div>
        ))}
        <div className="row wrapflex" style={{ gap: 8 }}>
          <button className="btn small" onClick={() => setRules([...rules, ['roce', '>=', 15]])}>+ Add rule</button>
          <input style={{ flex: 1, minWidth: 120 }} placeholder="Name this screen" value={name} onChange={(e) => setName(e.target.value)} />
          <button className="btn small primary" onClick={save} disabled={!name.trim()}>Save</button>
        </div>
      </div>

      <div className="card" style={{ padding: 0 }}>
        <div className="row between" style={{ padding: '12px 14px' }}>
          <b>{rows ? `${res.length} match${res.length === 1 ? '' : 'es'}` : 'Loading…'} <span className="small muted">of {base.length}{mk === 'IN' ? ` scanned ${univ === 'ALL' ? '' : univLabel(univ) + ' '}${fno ? 'F&O ' : ''}stocks` : ''}</span></b>
          <select value={sort} onChange={(e) => setSort(e.target.value)} style={{ maxWidth: 190 }}>
            {fieldsFor(mk).filter((f) => f[3] !== 'bool').map(([k, l]) => <option key={k} value={k}>Sort: {l}</option>)}
          </select>
        </div>
        {stale && <div className="small t-warn" style={{ padding: '0 14px 10px' }}>Most stocks were scanned before forensic and valuation fields existed. Run a new scan on Top Picks to fill them.</div>}
        {rows && rows.length === 0 && <div className="empty">No scanned stocks yet. Run a scan on <a href="#/rankings">Top Picks</a> first.</div>}
        {res.slice(0, 200).map((r) => (
          <div key={r.symbol} className="rank-item" onClick={() => go(`stock/${r.symbol}`)}>
            <div className="ring-sm"><ScoreRing value={r.overall} size={44} /></div>
            <div className="grow">
              <div className="ellip"><Logo sym={r.symbol} name={r.name} size={20} /><b>{r.name}</b> <span className="small muted">{ticker(r.symbol)}</span>{r.fno && <FnoBadge lot={r.lot} />}{r.surveillance && <span className="tagc bad" title={(r.surv_labels || []).join(', ')}>🚨</span>}</div>
              <div className="small muted ellip">{r.sector || '—'} · {cr(r.market_cap)}</div>
              <div className="small" style={{ marginTop: 3, display: 'flex', flexWrap: 'wrap', gap: '2px 10px' }}>
                {showCols.map((k) => <span key={k}><span className="muted">{F[k].label.split(' (')[0]}:</span> <b>{fmt(k, r[k])}</b></span>)}
              </div>
            </div>
          </div>
        ))}
      </div>
      {res.length > 0 && <ExplainList symbols={res.map((r) => r.symbol)} title={`Screen: ${active}`} />}
      <p className="disclaimer">Screens filter scanned stocks only. A match is a starting point for research, not a recommendation.</p>
    </>
  )
}
