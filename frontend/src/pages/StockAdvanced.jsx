import { useMemo, useState } from 'react'
import {
  Area, CartesianGrid, ComposedChart, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { Badge, Tile } from '../components/ui'
import { cr, go, num, ok, pct, rs, signed, x } from '../util'

const C = { a: '#2dd4bf', b: '#38bdf8', c: '#a78bfa', d: '#f59e0b', e: '#f472b6', good: '#22c55e', bad: '#ef4444', grid: '#223040', muted: '#8b98a5' }
const axis = { stroke: C.muted, fontSize: 11, tickLine: false }
const tip = { contentStyle: { background: '#121a23', border: '1px solid #223040', borderRadius: 10, fontSize: 12 }, labelStyle: { color: '#e6edf3' } }

// ====================================================================== FORENSICS
export function Forensics({ d }) {
  const fx = d.analysis.forensics
  if (!fx) return <div className="card empty">Refresh this stock to load forensic checks.</div>
  const { piotroski: p, altman: a, beneish: b, dupont } = fx
  return (
    <>
      <div className="grid3" style={{ marginBottom: 12 }}>
        <Tile k="Piotroski F" v={p.available ? `${p.score_9}/9` : 'n/a'} s={p.available ? p.zone : ''} color={p.available ? `var(--${p.tone})` : null} />
        <Tile k="Altman Z" v={a.available ? num(a.z, 2) : 'n/a'} s={a.available ? a.zone : 'not for lenders'} color={a.available ? `var(--${a.tone})` : null} />
        <Tile k="Beneish M" v={b.available ? num(b.m, 2) : 'n/a'} s={b.available ? b.zone : 'not for lenders'} color={b.available ? `var(--${b.tone})` : null} />
      </div>

      {p.available && (
        <div className="card">
          <div className="row between"><h3 style={{ margin: 0 }}>Piotroski F-score</h3><Badge tone={p.tone}>{p.score}/{p.out_of} passed</Badge></div>
          <p className="small muted" style={{ margin: '6px 0 8px' }}>9 yes/no tests of whether the business got healthier in {p.year} vs {p.vs_year}. 7–9 = strong, 0–3 = weak.</p>
          {['Profitability', 'Safety', 'Efficiency'].map((g) => (
            <div key={g}>
              <h4>{g}</h4>
              <ul className="list">
                {p.checks.filter((c) => c.group === g).map((c) => (
                  <li key={c.name}>
                    <span className={`ic ${c.pass === null ? 't-neutral' : c.pass ? 't-good' : 't-bad'}`}>{c.pass === null ? '–' : c.pass ? '✓' : '✗'}</span>
                    {c.name}{c.proxy && <span className="chip" style={{ marginLeft: 6, marginBottom: 0 }}>proxy</span>}
                    <div className="small muted">{c.detail}</div>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}

      {a.available && (
        <div className="card">
          <div className="row between"><h3 style={{ margin: 0 }}>Altman Z-score · bankruptcy risk</h3><Badge tone={a.tone}>{a.zone}</Badge></div>
          <ZoneBar value={a.z} min={0} max={6} zones={[[0, 1.81, 'var(--bad)', 'Distress'], [1.81, 2.99, 'var(--warn)', 'Grey'], [2.99, 6, 'var(--good)', 'Safe']]} />
          <div className="tbl-wrap" style={{ marginTop: 10 }}>
            <table className="tbl">
              <thead><tr><th>Part</th><th>Ratio</th><th>×</th><th>Adds</th></tr></thead>
              <tbody>{a.parts.map((r) => <tr key={r.name}><td>{r.name}</td><td>{num(r.value, 3)}</td><td>{r.weight}</td><td>{num(r.contribution, 2)}</td></tr>)}</tbody>
            </table>
          </div>
          <p className="small muted" style={{ marginBottom: 0 }}>Above 2.99 = safe, below 1.81 = distress. Debt-free companies often score very high. {a.note}</p>
        </div>
      )}

      {b.available && (
        <div className="card">
          <div className="row between"><h3 style={{ margin: 0 }}>Beneish M-score · earnings quality</h3><Badge tone={b.tone}>{b.zone}</Badge></div>
          <ZoneBar value={b.m} min={-4} max={0} zones={[[-4, -2.22, 'var(--good)', 'Unlikely'], [-2.22, -1.78, 'var(--warn)', 'Watch'], [-1.78, 0, 'var(--bad)', 'Risk']]} />
          <div className="tbl-wrap" style={{ marginTop: 10 }}>
            <table className="tbl">
              <thead><tr><th>Signal</th><th>Value</th><th style={{ textAlign: 'left' }}>What it means</th></tr></thead>
              <tbody>{b.parts.map((r) => <tr key={r.name}><td>{r.name}</td><td>{num(r.value, 3)}</td><td style={{ textAlign: 'left', whiteSpace: 'normal', minWidth: 160 }}>{r.meaning}</td></tr>)}</tbody>
            </table>
          </div>
          <p className="small muted" style={{ marginBottom: 0 }}>Below −2.22 = unlikely manipulation, above −1.78 = numbers look aggressive. {b.notes.join(' · ')}.</p>
        </div>
      )}

      {dupont?.length > 0 && (
        <div className="card">
          <h3>DuPont · where ROE comes from</h3>
          <p className="small muted" style={{ marginTop: -4 }}>ROE = net margin × asset turnover × leverage. ROE built on margins or turnover is healthier than ROE built on debt.</p>
          <div style={{ height: 210 }}>
            <ResponsiveContainer>
              <ComposedChart data={dupont.map((r) => ({ ...r, p: r.year.replace(/^(\w{3}) (\d{2})(\d{2})$/, "$1 '$3") }))} margin={{ top: 6, right: 0, left: -14, bottom: 0 }}>
                <CartesianGrid stroke={C.grid} vertical={false} />
                <XAxis dataKey="p" {...axis} interval="preserveStartEnd" />
                <YAxis yAxisId="l" {...axis} tickFormatter={(v) => `${v}%`} />
                <YAxis yAxisId="r" orientation="right" {...axis} tickFormatter={(v) => `${v}x`} />
                <Tooltip {...tip} /><Legend wrapperStyle={{ fontSize: 12 }} />
                <Area yAxisId="l" dataKey="roe" name="ROE %" stroke={C.a} fill={C.a} fillOpacity={0.15} />
                <Line yAxisId="l" dataKey="net_margin" name="Net margin %" stroke={C.d} dot={false} />
                <Line yAxisId="r" dataKey="asset_turnover" name="Turnover x" stroke={C.b} dot={false} />
                <Line yAxisId="r" dataKey="leverage" name="Leverage x" stroke={C.e} dot={false} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
          <div className="tbl-wrap" style={{ marginTop: 8 }}>
            <table className="tbl">
              <thead><tr><th>Year</th><th>Net margin</th><th>Turnover</th><th>Leverage</th><th>ROE</th></tr></thead>
              <tbody>{dupont.slice().reverse().map((r) => <tr key={r.year}><td>{r.year}</td><td>{pct(r.net_margin)}</td><td>{x(r.asset_turnover)}</td><td>{x(r.leverage)}</td><td><b>{pct(r.roe)}</b></td></tr>)}</tbody>
            </table>
          </div>
        </div>
      )}

      {fx.flags?.length > 0 && (
        <div className="card">
          <h3>Accounting checks</h3>
          <ul className="list">{fx.flags.map((f, i) => <li key={i}><span className={`ic ${f.severity === 'high' ? 't-bad' : f.severity === 'medium' ? 't-warn' : 't-neutral'}`}>!</span>{f.text}</li>)}</ul>
        </div>
      )}
      <p className="disclaimer">These models were built on US company data and use proxies where the summary financials lack a line. Treat a bad score as "read the annual report carefully", not as proof.</p>
    </>
  )
}

function ZoneBar({ value, min, max, zones }) {
  const pos = (v) => `${Math.max(0, Math.min(100, ((v - min) / (max - min)) * 100))}%`
  return (
    <div style={{ margin: '14px 0 4px' }}>
      <div style={{ position: 'relative', height: 10, borderRadius: 99, overflow: 'hidden', display: 'flex' }}>
        {zones.map(([a, b, col]) => <div key={a} style={{ width: `${((b - a) / (max - min)) * 100}%`, background: col, opacity: 0.55 }} />)}
      </div>
      <div style={{ position: 'relative', height: 18 }}>
        <div style={{ position: 'absolute', left: pos(value), top: -15, transform: 'translateX(-50%)', width: 4, height: 18, background: '#e6edf3', borderRadius: 2 }} />
      </div>
      <div className="row between small muted" style={{ marginTop: -4 }}>{zones.map(([a, , , l]) => <span key={l}>{l}</span>)}</div>
    </div>
  )
}

// ====================================================================== VALUATION LAB
function dcf(base, g1, g2, gt, r) {
  g1 /= 100; g2 /= 100; gt /= 100; r /= 100
  if (!(r > gt) || !(base > 0)) return null
  let cf = base, pv = 0
  for (let t = 1; t <= 10; t++) { cf *= 1 + (t <= 5 ? g1 : g2); pv += cf / (1 + r) ** t }
  const tv = (cf * (1 + gt)) / (r - gt) / (1 + r) ** 10
  return { value: pv + tv, stage: pv, terminal: tv }
}

function Slider({ label, value, set, min, max, step = 0.5, unit = '%' }) {
  return (
    <div style={{ margin: '10px 0' }}>
      <div className="row between small"><span>{label}</span><b>{value}{unit}</b></div>
      <input type="range" min={min} max={max} step={step} value={value} onChange={(e) => set(+e.target.value)}
        style={{ width: '100%', padding: 0, accentColor: 'var(--accent)', background: 'transparent', border: 0 }} />
    </div>
  )
}

export function ValuationLab({ d }) {
  const a = d.analysis, m = a.metrics, v = a.valuation || {}, peers = d.peers
  const dc = v.dcf || {}
  const [base, setBase] = useState(dc.defaults?.base)
  const [g1, setG1] = useState(dc.defaults?.g1 ?? 10)
  const [g2, setG2] = useState(dc.defaults?.g2 ?? 7)
  const [gt, setGt] = useState(dc.defaults?.gt ?? 5)
  const [r, setR] = useState(dc.defaults?.r ?? 12)
  const baseVal = dc.options?.[base]?.value
  const res = useMemo(() => dcf(baseVal, g1, g2, gt, r), [baseVal, g1, g2, gt, r])
  const mos = res && m.price ? ((res.value - m.price) / res.value) * 100 : null
  const reset = () => { setBase(dc.defaults.base); setG1(dc.defaults.g1); setG2(dc.defaults.g2); setGt(dc.defaults.gt); setR(dc.defaults.r) }
  const fv = v.fair_value
  const bands = v.pe_bands
  const peerMedianPE = peers?.median?.['P/E']
  const pe = d.pe_chart || {}
  const peSeries = (pe['Price to Earning'] || pe.PE || []).map(([dt, val]) => ({ d: dt.slice(0, 7), PE: val }))

  return (
    <>
      {fv && (
        <div className="card">
          <div className="row between"><h3 style={{ margin: 0 }}>Fair value range</h3>
            <Badge tone={fv.upside >= 15 ? 'good' : fv.upside >= -10 ? 'warn' : 'bad'}>{fv.upside >= 15 ? 'Below fair value' : fv.upside >= -10 ? 'Around fair value' : 'Above fair value'}</Badge></div>
          <RangeBar low={fv.low} mid={fv.mid} high={fv.high} price={m.price} />
          <div className="grid3" style={{ marginTop: 8 }}>
            <Tile k="Middle estimate" v={rs(fv.mid)} s={`${signed(fv.upside, 1, '%')} vs price`} />
            <Tile k="Margin of safety" v={pct(fv.margin_of_safety)} s="≥30% = classic buffer" color={fv.margin_of_safety >= 30 ? 'var(--good)' : fv.margin_of_safety < 0 ? 'var(--bad)' : null} />
            <Tile k="Price now" v={rs(m.price)} />
          </div>
          <div className="tbl-wrap" style={{ marginTop: 10 }}>
            <table className="tbl">
              <thead><tr><th>Method</th><th>Value</th><th>vs price</th></tr></thead>
              <tbody>{v.methods.map((mt) => (
                <tr key={mt.name}><td style={{ whiteSpace: 'normal', minWidth: 150 }}><b>{mt.name}</b><div className="small muted">{mt.how}</div></td>
                  <td>{rs(mt.value)}</td><td style={{ color: mt.upside >= 0 ? 'var(--good)' : 'var(--bad)' }}>{signed(mt.upside, 0, '%')}</td></tr>
              ))}</tbody>
            </table>
          </div>
        </div>
      )}

      {baseVal && (
        <div className="card">
          <div className="row between"><h3 style={{ margin: 0 }}>Your DCF</h3><button className="btn small" onClick={reset}>Reset</button></div>
          <p className="small muted" style={{ margin: '6px 0' }}>Move the sliders. The value updates instantly.</p>
          {Object.keys(dc.options).length > 1 && (
            <select value={base} onChange={(e) => setBase(e.target.value)} style={{ width: '100%', marginTop: 4 }}>
              {Object.entries(dc.options).map(([k, o]) => <option key={k} value={k}>Start from: {o.label} ₹{o.value}</option>)}
            </select>
          )}
          <Slider label="Growth, years 1–5" value={g1} set={setG1} min={0} max={35} />
          <Slider label="Growth, years 6–10" value={g2} set={setG2} min={0} max={25} />
          <Slider label="Growth forever after" value={gt} set={setGt} min={0} max={8} />
          <Slider label="Your required return (discount rate)" value={r} set={setR} min={8} max={20} />
          {res ? (
            <>
              <div className="grid3" style={{ marginTop: 8 }}>
                <Tile k="Intrinsic value" v={rs(res.value)} color="var(--accent)" />
                <Tile k="Margin of safety" v={pct(mos)} color={mos >= 30 ? 'var(--good)' : mos < 0 ? 'var(--bad)' : 'var(--warn)'} />
                <Tile k="From terminal" v={pct((res.terminal / res.value) * 100, 0)} s="share of value after yr 10" />
              </div>
              <Sensitivity base={baseVal} g1={g1} g2={g2} gt={gt} r={r} price={m.price} />
            </>
          ) : <div className="small t-bad" style={{ marginTop: 8 }}>Discount rate must be above the forever-growth rate.</div>}
          <p className="small muted" style={{ marginBottom: 0 }}>If over 70% of the value comes from after year 10, the result leans heavily on long-run guesses.</p>
        </div>
      )}

      {bands?.series?.length > 0 && (
        <div className="card">
          <h3>P/E bands</h3>
          <p className="small muted" style={{ marginTop: -4 }}>Price vs what it would be at the stock's own low (10th pct), median and high (90th pct) P/E. Today's P/E is higher than {num(bands.percentile_now)}% of the last 10 years.</p>
          <div style={{ height: 240 }}>
            <ResponsiveContainer>
              <LineChart data={bands.series} margin={{ top: 6, right: 6, left: -4, bottom: 0 }}>
                <CartesianGrid stroke={C.grid} vertical={false} />
                <XAxis dataKey="d" {...axis} minTickGap={50} tickFormatter={(s) => s.slice(0, 4)} />
                <YAxis {...axis} tickFormatter={(s) => num(s)} />
                <Tooltip {...tip} formatter={(s) => rs(s)} /><Legend wrapperStyle={{ fontSize: 11 }} />
                <Line dataKey="p90" name={`${bands.bands.p90}x`} stroke={C.bad} dot={false} strokeDasharray="4 3" />
                <Line dataKey="p50" name={`${bands.bands.p50}x`} stroke={C.d} dot={false} strokeDasharray="4 3" />
                <Line dataKey="p10" name={`${bands.bands.p10}x`} stroke={C.good} dot={false} strokeDasharray="4 3" />
                <Line dataKey="price" name="Price" stroke={C.a} dot={false} strokeWidth={2} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      <div className="grid3" style={{ marginBottom: 12 }}>
        <Tile k="P/E now" v={num(m.pe, 1)} s={ok(a.median_pe) ? `median ${num(a.median_pe, 1)}` : ''} />
        <Tile k="Peer median P/E" v={num(peerMedianPE, 1)} />
        <Tile k="PEG" v={num(m.peg, 2)} s="P/E ÷ growth" />
        <Tile k="Price / Book" v={x(m.pb)} s={`book ${rs(m.book_value)}`} />
        {v.ev ? <Tile k="EV / EBITDA" v={num(v.ev.ev_ebitda, 1)} s={`EV ${cr(v.ev.ev)}`} /> : <Tile k="Earnings yield" v={pct(m.earnings_yield, 2)} />}
        <Tile k="Graham number" v={rs(v.graham_number)} s="strict value ceiling" />
      </div>

      {peSeries.length > 0 && !bands?.series?.length && (
        <div className="card">
          <h3>P/E over 10 years</h3>
          <div style={{ height: 200 }}>
            <ResponsiveContainer>
              <LineChart data={peSeries} margin={{ top: 6, right: 6, left: -14, bottom: 0 }}>
                <CartesianGrid stroke={C.grid} vertical={false} /><XAxis dataKey="d" {...axis} minTickGap={40} /><YAxis {...axis} />
                <Tooltip {...tip} />{ok(a.median_pe) && <ReferenceLine y={a.median_pe} stroke={C.d} strokeDasharray="4 4" />}
                <Line dataKey="PE" stroke={C.a} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {peers?.rows?.length > 0 && (
        <div className="card">
          <h3>Peers</h3>
          <div className="tbl-wrap">
            <table className="tbl">
              <thead><tr>{peers.columns.map((c) => <th key={c}>{c}</th>)}</tr></thead>
              <tbody>
                {peers.rows.map((row) => (
                  <tr key={row.name} className="click" onClick={() => row.symbol && go(`stock/${row.symbol}`)}>
                    {peers.columns.map((c) => <td key={c}>{c.toLowerCase() === 'name' ? <b style={{ color: row.symbol === d.symbol ? 'var(--accent)' : null }}>{row.name}</b> : num(row[c], 1)}</td>)}
                  </tr>
                ))}
                {peers.median && Object.keys(peers.median).length > 0 && (
                  <tr>{peers.columns.map((c) => <td key={c} className="muted">{c.toLowerCase() === 'name' ? 'Median' : num(peers.median[c], 1)}</td>)}</tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}
      <p className="disclaimer">Every valuation is an estimate built on assumptions. Use the range, not a single number.</p>
    </>
  )
}

function RangeBar({ low, mid, high, price }) {
  const lo = Math.min(low, price) * 0.9, hi = Math.max(high, price) * 1.05
  const p = (v) => `${((v - lo) / (hi - lo)) * 100}%`
  return (
    <div style={{ position: 'relative', height: 58, margin: '14px 4px 0' }}>
      <div style={{ position: 'absolute', top: 22, left: 0, right: 0, height: 6, background: 'var(--card2)', borderRadius: 99 }} />
      <div style={{ position: 'absolute', top: 22, left: p(low), width: `calc(${p(high)} - ${p(low)})`, height: 6, background: 'var(--accent)', opacity: 0.5, borderRadius: 99 }} />
      <div style={{ position: 'absolute', top: 16, left: p(mid), width: 3, height: 18, background: 'var(--accent)', transform: 'translateX(-50%)' }} />
      <div style={{ position: 'absolute', top: 12, left: p(price), width: 3, height: 26, background: '#e6edf3', transform: 'translateX(-50%)' }} />
      <div className="small" style={{ position: 'absolute', top: -4, left: p(price), transform: 'translateX(-50%)', whiteSpace: 'nowrap' }}>Price {rs(price)}</div>
      <div className="small muted" style={{ position: 'absolute', top: 38, left: p(low), transform: 'translateX(-20%)' }}>{rs(low)}</div>
      <div className="small muted" style={{ position: 'absolute', top: 38, left: p(high), transform: 'translateX(-80%)' }}>{rs(high)}</div>
    </div>
  )
}

function Sensitivity({ base, g1, g2, gt, r, price }) {
  const rs_ = [r - 2, r - 1, r, r + 1, r + 2].filter((v) => v > gt)
  const gs = [g1 - 4, g1 - 2, g1, g1 + 2, g1 + 4].filter((v) => v >= 0)
  return (
    <>
      <h4>Sensitivity · value per share</h4>
      <div className="tbl-wrap">
        <table className="tbl">
          <thead><tr><th>Growth ↓ / Return →</th>{rs_.map((v) => <th key={v}>{v}%</th>)}</tr></thead>
          <tbody>{gs.map((g) => (
            <tr key={g}><td>{g}%</td>{rs_.map((rr) => {
              const val = dcf(base, g, g2, gt, rr)?.value
              const col = !val ? null : val >= price * 1.3 ? 'var(--good)' : val >= price ? 'var(--ok)' : val >= price * 0.8 ? 'var(--warn)' : 'var(--bad)'
              return <td key={rr} style={{ color: col, fontWeight: g === g1 && rr === r ? 800 : 400 }}>{val ? num(val) : '—'}</td>
            })}</tr>
          ))}</tbody>
        </table>
      </div>
      <div className="small muted" style={{ marginTop: 4 }}>Green = 30%+ above price · blue = above · amber = slightly below · red = well below.</div>
    </>
  )
}

// ====================================================================== DOCUMENTS
export function Documents({ d }) {
  const docs = d.company.documents || []
  if (!docs.length) return <div className="card empty">No documents found. Use ↻ Refresh to fetch them.</div>
  return (
    <>
      {docs.map((g) => (
        <div className="card" key={g.category}>
          <h3>{g.category}</h3>
          <ul className="list">
            {g.items.map((it, i) => (
              <li key={i}>
                <span className="ic" style={{ color: 'var(--accent)' }}>›</span>
                {it.url ? <a href={it.url} target="_blank" rel="noreferrer">{it.title}</a> : <b>{it.title}</b>}
                {it.sub && <div className="small muted">{it.sub}</div>}
                {it.links?.length > 0 && <div style={{ marginTop: 4 }}>{it.links.map((l) => <a key={l.url} className="chip" style={{ color: 'var(--accent)' }} href={l.url} target="_blank" rel="noreferrer">{l.label}</a>)}</div>}
              </li>
            ))}
          </ul>
        </div>
      ))}
      <p className="small muted">Read the latest annual report and the last two concall transcripts before investing. Management's own words are where the future is discussed.</p>
    </>
  )
}
