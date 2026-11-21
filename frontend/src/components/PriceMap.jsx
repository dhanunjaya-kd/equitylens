import { useEffect, useState } from 'react'
import { api, ago, go } from '../util'
import { Badge, Loading } from './ui'
import { Md, useAISettings } from '../pages/AI'
import { Busy, CONF, Unverified, post } from './EntryCard'

const n2 = (v, d = 2) => (v === null || v === undefined ? '—' : (+v).toLocaleString('en-IN', { maximumFractionDigits: d, minimumFractionDigits: d }))
const sg = (v, d = 1) => (v === null || v === undefined ? '—' : `${v > 0 ? '+' : ''}${(+v).toFixed(d)}%`)
const STAGE_TONE = { 'At its high': 'good', Pullback: 'ok', Correction: 'warn', 'Bear phase': 'bad' }

function Tile({ k, v, s, tone }) {
  return (
    <div className="tile">
      <div className="k">{k}</div>
      <div className="v" style={{ color: tone ? `var(--${tone})` : undefined }}>{v}</div>
      {s && <div className="s">{s}</div>}
    </div>
  )
}

function heldText(l) {
  if (!l.tests) return 'not tested in the last 2 years'
  return `held ${l.held} of ${l.tests} test${l.tests > 1 ? 's' : ''}${l.tests < 3 ? ' · thin evidence' : ''}`
}

function TrackLine({ tr }) {
  if (!tr) {
    return <div className="small" style={{ color: 'var(--warn)', margin: '4px 0 6px' }}>Not tested yet: whether a level's past record predicts its next test. Run <code>tools\levels_backtest.py</code> once; until then the counts are history only.</div>
  }
  const side = (k, lab) => {
    const b = tr.result?.[k]
    if (!b) return null
    const st = b.passed === true ? ['var(--good)', 'past record DID predict the next test'] : b.passed === false ? ['var(--bad)', 'past record did NOT predict the next test'] : ['var(--warn)', 'too few tests to say']
    return <div key={k}>{lab}: all levels held at the next test {b.all.held_pct}% of {b.all.n.toLocaleString('en-IN')} → <b style={{ color: st[0] }}>{st[1]}</b></div>
  }
  return (
    <div className="small" style={{ margin: '4px 0 6px', lineHeight: 1.5 }}>
      <div className="muted">Backtest, {tr.universe}, {tr.stocks} stocks, {tr.tests?.toLocaleString('en-IN')} level tests (built {tr.built}). Fixed test: {tr.pass_test}</div>
      {side('support', 'Supports')}{side('resistance', 'Resistances')}
      {tr.market_note && <div style={{ color: 'var(--warn)' }}>{tr.market_note}</div>}
    </div>
  )
}

function Ladder({ lv, cur, tr }) {
  const row = (l, i) => {
    const res = l.kind === 'resistance'
    const b = tr?.result?.[l.kind]?.buckets?.[l.bucket]
    return (
      <div key={`${l.kind}${i}`} className="pmap-lv">
        <span className="pmap-kind" style={{ color: res ? 'var(--bad)' : 'var(--good)' }}>{res ? 'RESISTANCE' : 'SUPPORT'}</span>
        <b className="pmap-px">{cur}{n2(l.price)}</b>
        <span className="pmap-dist">{sg(l.dist_pct)}</span>
        <span className="pmap-what">{l.what}
          {b && b.n >= 100 && <span className="pmap-bt">Backtest: {l.kind === 'support' ? 'supports' : 'resistances'} with this record ({l.bucket}) held at the next test {b.held_pct}% of {b.n.toLocaleString('en-IN')} times</span>}
          {b && b.n < 100 && <span className="pmap-bt" style={{ color: 'var(--warn)' }}>Backtest: only {b.n} tests of levels with this record ({l.bucket}), too few for a percentage</span>}
        </span>
        <span className="pmap-held">{heldText(l)}</span>
      </div>
    )
  }
  return (
    <div className="card">
      <h3 style={{ marginTop: 0 }}>Where buyers and sellers stepped in before</h3>
      <div className="small muted">Each level comes from this stock's own prices. A test = price came within 1%; held = it moved 3% away before closing 1% through, within 20 sessions.</div>
      <TrackLine tr={tr} />
      {[...lv.resistance].reverse().map(row)}
      <div className="pmap-lv pmap-now">
        <span className="pmap-kind">NOW</span><b className="pmap-px">{cur}{n2(lv.price)}</b><span className="pmap-dist" /><span className="pmap-what">Last close</span><span className="pmap-held" />
      </div>
      {lv.support.map(row)}
      {!lv.support.length && <div className="small muted" style={{ padding: 8 }}>No support level below today's price in the last 2 years.</div>}
    </div>
  )
}

function Buckets({ s }) {
  const max = Math.max(1, ...(s.buckets || []).map((b) => b.n))
  return (
    <div className="pmap-buckets">
      {(s.buckets || []).map((b) => (
        <div key={b.label} className="pmap-bk">
          <div className="small">{b.n}</div>
          <div className="pmap-bar" style={{ height: b.n ? `${8 + (b.n / max) * 70}px` : '2px' }} />
          <div className="small muted">{b.label}</div>
        </div>
      ))}
    </div>
  )
}

function CaseStats({ s, who }) {
  if (!s.n) return <p className="small muted">No earlier case of {who} falling this far in the data.</p>
  if (!s.enough) return <p className="small" style={{ color: 'var(--warn)' }}>Only {s.n} case{s.n > 1 ? 's' : ''} for {who}: too few for percentages (the rule needs 10). They are listed below.</p>
  return (
    <div className="pmap-stats">
      <div><div className="k">Half the time it fell less than</div><b>{s.median}% more</b></div>
      <div><div className="k">3 times in 4, less than</div><b>{s.p75}% more</b></div>
      <div><div className="k">Worst case seen</div><b>{s.worst}% more</b></div>
      <div><div className="k">Sessions to the low (median)</div><b>{s.median_days}</b></div>
      <div><div className="k">Back to that price within 3 months</div><b>{s.back_3m_pct}%</b> <span className="small muted">of {s.back_n}</span></div>
    </div>
  )
}

function Further({ f, w, cur, sym }) {
  if (!f.applies) {
    return (
      <div className="card">
        <h3 style={{ marginTop: 0 }}>How much further could it fall?</h3>
        <p className="small muted">It is only {w.fall_pct}% below its 52-week high. This section starts at a 5% fall.</p>
        {f.range_1m && <Range r={f.range_1m} cur={cur} />}
      </div>
    )
  }
  return (
    <div className="card">
      <h3 style={{ marginTop: 0 }}>How much further could it fall?</h3>
      <div className="small muted" style={{ marginBottom: 10 }}>Not a forecast. This is what happened every earlier time a stock first fell {f.depth_pct}% from its 52-week high, up to its next 52-week high. The fall still running is left out.</div>
      <div className="grid2">
        <div className="tile">
          <div className="k">{sym}'s own history · {f.own.n} cases since {f.since?.slice(0, 4)}</div>
          <CaseStats s={f.own} who={sym} />
          {f.own.n > 0 && <Buckets s={f.own} />}
          {f.own.n > 0 && !f.own.enough && (
            <table className="pm-table" style={{ minWidth: 0, marginTop: 6 }}>
              <thead><tr><th>Date it hit this depth</th><th>Then fell</th><th>Sessions to low</th><th>New high on</th></tr></thead>
              <tbody>{f.own_cases.map((c) => <tr key={c.date}><td>{c.date}</td><td>{c.further_pct}%</td><td>{c.days_to_low}</td><td>{c.recovered}</td></tr>)}</tbody>
            </table>
          )}
        </div>
        <div className="tile">
          <div className="k">Its sector peers at the same depth · {f.peers.n} cases from {f.peer_count} stocks</div>
          <CaseStats s={f.peers} who="these peers" />
          {f.peers.n > 0 && <Buckets s={f.peers} />}
        </div>
      </div>
      <div className="small muted" style={{ marginTop: 6 }}>Bars show how much further the price fell after hitting this depth, before its next 52-week high.</div>
      {f.range_1m && <Range r={f.range_1m} cur={cur} />}
    </div>
  )
}

function Range({ r, cur }) {
  return (
    <div className="small" style={{ marginTop: 8 }}>
      Normal 1-month move for this stock (last 3 years, 4 times in 5): <b>{sg(r.lo_pct)} to {sg(r.hi_pct)}</b>, so about <b>{cur}{n2(r.lo)} – {cur}{n2(r.hi)}</b> from today. <span className="muted">{r.n} overlapping 21-session windows.</span>
    </div>
  )
}

function Sector({ s, sym, m }) {
  const ix = s.index
  const rows = []
  if (m && !m.error) {
    rows.push([`Market · ${m.name} from its high`, `−${m.fall_pct}% · ${m.stage.toLowerCase()} · ${m.above50 ? 'above' : 'below'} its 50-day, ${m.above200 ? 'above' : 'below'} its 200-day`])
    if (m.beta) rows.push([`How much ${sym} moves with the market`, `about ${m.beta.beta}× its daily moves (correlation ${m.beta.corr}, ${m.beta.n} days)`])
  }
  if (ix && !ix.error) {
    rows.push([`${ix.name} (${ix.ticker}) from its high`, `−${ix.fall_pct}% · ${ix.stage.toLowerCase()}`])
    rows.push(['Sector trend', `${ix.above50 ? 'above' : 'below'} its 50-day, ${ix.above200 ? 'above' : 'below'} its 200-day`])
    if (ix.beta) rows.push([`How much ${sym} moves with it`, `about ${ix.beta.beta}× its daily moves (correlation ${ix.beta.corr}, ${ix.beta.n} days)`])
  }
  if (s.breadth) rows.push(['Peers above their 50-day average', `${s.breadth.above50} of ${s.breadth.of}`])
  if (s.peer_median_fall !== undefined) rows.push(['Median peer fall from its 52-week high', `−${s.peer_median_fall}%`])
  if (s.vs_sector_3m) rows.push([`${sym} vs ${s.vs_sector_3m.against}, last 3 months`, `${sg(s.vs_sector_3m.stock)} vs ${sg(s.vs_sector_3m.sector)} → ${s.vs_sector_3m.diff >= 0 ? 'stronger' : 'weaker'} by ${Math.abs(s.vs_sector_3m.diff)} pts`])
  return (
    <div className="card">
      <h3 style={{ marginTop: 0 }}>Is it the market, the sector, or just this stock?</h3>
      <p style={{ fontWeight: 600, margin: '0 0 2px' }}>{s.layers || s.answer}</p>
      {s.layers && <p className="small muted" style={{ margin: '0 0 8px' }}>{s.answer}</p>}
      {rows.map(([k, v]) => <div key={k} className="pmap-kv"><span className="muted">{k}</span><b>{v}</b></div>)}
      {m?.error && <div className="small" style={{ color: 'var(--warn)', marginTop: 6 }}>Market index: {m.error}.</div>}
      {ix?.error && <div className="small" style={{ color: 'var(--warn)', marginTop: 6 }}>Sector index: {ix.error}. Using peers only.</div>}
      {!ix && <div className="small muted" style={{ marginTop: 6 }}>No sector index matches “{(s.path || []).join(' › ')}”, so peers only.</div>}
      {s.peers?.length > 0 && (
        <div style={{ overflowX: 'auto', marginTop: 10 }}>
          <div className="small muted">How sector stocks are moving · {s.peers_with_prices} of {s.peers_asked} peers with prices, from {s.peer_source}</div>
          <table className="pm-table" style={{ minWidth: 420 }}>
            <thead><tr><th>Stock</th><th>From 52-week high</th><th>Last 3 months</th><th>Above 50-day</th></tr></thead>
            <tbody>{s.peers.slice(0, 12).map((p) => (
              <tr key={p.symbol} style={{ cursor: 'pointer' }} onClick={() => go(`stock/${p.symbol}/pricemap`)}>
                <td><b>{p.symbol.replace(/^US:/, '')}</b></td><td>−{p.fall_pct}%</td><td>{sg(p.ret_3m)}</td><td>{p.above50 ? '✓' : '✕'}</td>
              </tr>))}</tbody>
          </table>
        </div>
      )}
      <div className="small muted" style={{ marginTop: 6 }}>India uses the closest NSE sector index; US uses the closest sector fund, matched on the SEC industry.</div>
    </div>
  )
}

function ValueFloor({ v, cur, price }) {
  const fmtR = (r) => (r.below !== undefined ? `below ${cur}${n2(r.below)}` : r.above !== undefined ? `above ${cur}${n2(r.above)}` : `${cur}${n2(r.from)} – ${cur}${n2(r.to)}`)
  const pc = (x) => (x === null || x === undefined ? '—' : sg(x))
  return (
    <div className="card">
      <h3 style={{ marginTop: 0 }}>Value floor from its own P/E history</h3>
      {!v.ranges && <p className="small muted">{v.note}</p>}
      {v.ranges && (
        <>
          <div className="small muted" style={{ marginBottom: 6 }}>{v.how}</div>
          <div style={{ overflowX: 'auto' }}>
            <table className="pm-table" style={{ minWidth: 520 }}>
              <thead><tr><th>P/E state</th><th>Price range</th>{v.record && <><th>12m vs peers</th><th>24m</th><th>36m</th><th>Stock-months tested</th></>}</tr></thead>
              <tbody>{v.ranges.map((r) => {
                const here = r.state === v.pe_state
                const rec = v.record?.[r.state]
                return (
                  <tr key={r.state} style={here ? { background: 'var(--card2)', fontWeight: 700 } : undefined}>
                    <td>{r.state}{here ? ' ← now' : ''}</td><td>{fmtR(r)}</td>
                    {v.record && <><td>{pc(rec?.p12)}</td><td>{pc(rec?.p24)}</td><td>{pc(rec?.p36)}</td><td>{rec?.n?.toLocaleString('en-IN') ?? '—'}</td></>}
                  </tr>)
              })}</tbody>
            </table>
          </div>
          <div className="small" style={{ marginTop: 6 }}>Now: {cur}{n2(price)}, P/E at the {v.pe_percentile}th percentile of its own history ({v.pe_state}).{v.state && v.state !== v.pe_state ? ` The entry card says ${v.state} because it also uses fair value (${v.fv_state}).` : ''}</div>
          {v.record ? (
            <div className="small muted" style={{ marginTop: 4 }}>
              Record: entry backtest ({v.record_scope}, built {v.record_built}), average return minus same-month peers. {v.record_basis}
              {v.value_test && <> Fixed value test ({v.value_test.rule}): <b style={{ color: v.value_test.passed ? 'var(--good)' : 'var(--bad)' }}>{v.value_test.passed ? 'passed' : 'not passed'}</b>.</>}
            </div>
          ) : <div className="small" style={{ color: 'var(--warn)', marginTop: 4 }}>{v.record_note}</div>}
        </>
      )}
    </div>
  )
}

const VERDICT = { better: ['var(--good)', 'better than any day in a fall'], same: ['var(--muted)', 'about the same as any day in a fall'], worse: ['var(--bad)', 'worse than any day in a fall'] }

function recordText(r) {
  if (!r || r.verdict === 'too_few') {
    const list = (r?.cases || []).map((c) => `${c.date} ${sg(c.fwd_pct)}`).join(' · ')
    return <span style={{ color: 'var(--warn)' }}>Too few cases on this stock ({r?.n || 0}; the rule needs 10){list ? `: ${list}` : ''}</span>
  }
  const [c, t] = VERDICT[r.verdict]
  return (
    <span>After it switched on in past falls: higher a month later <b>{r.up_pct}%</b> of the time (median {sg(r.median_pct)}) vs {r.base_up_pct}% on any day in a fall · {r.n} cases → <b style={{ color: c }}>{t}</b></span>
  )
}

function Signals({ list }) {
  return (
    <div className="card">
      <h3 style={{ marginTop: 0 }}>Signs of a turn</h3>
      <div className="small muted" style={{ marginBottom: 8 }}>Five fixed signals, each with its record on this stock during falls of 10% or more. No date for a turn is predicted.</div>
      {list.map((g) => (
        <div key={g.key} className="pmap-sig">
          <span className="pmap-mark" style={{ color: g.on === null ? 'var(--muted)' : g.on ? 'var(--good)' : 'var(--bad)' }}>{g.on === null ? '–' : g.on ? '✓' : '✕'}</span>
          <div>
            <div><b>{g.name}</b> <span className="small muted">· {g.state}</span></div>
            <div className="small" style={{ lineHeight: 1.45 }}>{recordText(g.record)}</div>
            <div className="small muted" style={{ fontSize: 11.5 }}>Rule: {g.rule}</div>
          </div>
        </div>
      ))}
    </div>
  )
}

function Business({ b }) {
  return (
    <div className="grid2" style={{ marginBottom: 12 }}>
      <div className="tile"><div className="k" style={{ color: 'var(--good)' }}>Business positives</div>
        {b.plus.length ? b.plus.map((x) => <div key={x} className="small" style={{ marginTop: 6 }}>+ {x}</div>) : <div className="small muted">None in the data.</div>}
      </div>
      <div className="tile"><div className="k" style={{ color: 'var(--bad)' }}>Business negatives</div>
        {b.minus.length ? b.minus.map((x) => <div key={x} className="small" style={{ marginTop: 6 }}>− {x}</div>) : <div className="small muted">No serious red flags in the data.</div>}
      </div>
    </div>
  )
}

const SOS = { stock: ['warn', 'Mostly this stock'], sector: ['ok', 'Mostly the sector'], both: ['warn', 'Stock and sector'], unclear: ['ok', 'Unclear'] }

function PriceMapAI({ sym, date }) {
  const settings = useAISettings()
  const [r, setR] = useState(null), [busy, setBusy] = useState(false), [err, setErr] = useState(null)
  const run = async (refresh) => {
    setBusy(true); setErr(null)
    try { setR(await post(`/api/ai/pricemap/${encodeURIComponent(sym)}${refresh ? '?refresh=1' : ''}`)) } catch (x) { setErr(x.message) } finally { setBusy(false) }
  }
  useEffect(() => { setR(null); if (settings?.ready) run(false) }, [settings?.ready, sym, date]) // eslint-disable-line react-hooks/exhaustive-deps
  const so = r?.structured && (SOS[r.stock_or_sector?.answer] || SOS.unclear)
  return (
    <div className="card">
      <div className="row between" style={{ gap: 8, flexWrap: 'wrap' }}>
        <h3 style={{ margin: 0 }}>✦ AI research: why it fell, what holds it, what would turn it</h3>
        <div className="row" style={{ gap: 8 }}>
          {so && <Badge tone={so[0]}>{so[1]}</Badge>}
          {r && <button className="btn small" disabled={busy} onClick={() => run(true)}>↻ Redo</button>}
        </div>
      </div>
      {settings && !settings.ready && <p className="small muted">Add an AI key in Settings to get AI research on the price map. <button className="btn small" onClick={() => go('settings')}>⚙️ Settings</button></p>}
      {busy && <Busy text="Reading the levels, the fall cases, the sector, the turn signals and the last 8 quarters… (20–60 s)" />}
      {err && <div className="small t-bad">⚠️ {err}</div>}
      {r && !r.structured && <Md text={r.text} />}
      {r?.structured && (
        <>
          <p style={{ fontWeight: 600, margin: '10px 0 4px' }}>{r.headline}</p>
          <p className="small" style={{ margin: 0 }}>{r.stock_or_sector.why}</p>
          <Unverified list={r.unverified_top} />
          <div className="grid2" style={{ marginTop: 10 }}>
            <div className="tile"><div className="k">Levels that matter</div>
              {r.levels.map((l, i) => (
                <div key={i} style={{ marginTop: 8 }}>
                  <b style={{ color: l.kind === 'resistance' ? 'var(--bad)' : 'var(--good)' }}>{l.kind} {l.price}</b>
                  <div className="small muted">{l.evidence}</div><div className="small">{l.why}</div><Unverified list={l.unverified} />
                </div>))}
            </div>
            <div className="tile"><div className="k">How much further, from history</div>
              <div className="small" style={{ marginTop: 8 }}>{r.fall_risk.summary}</div>
              <div className="small muted" style={{ marginTop: 4 }}>{r.fall_risk.caveat}</div>
            </div>
          </div>
          {r.turn_watch.length > 0 && (
            <div className="tile" style={{ marginTop: 10 }}><div className="k">Turn signals to watch</div>
              {r.turn_watch.map((t, i) => (
                <div key={i} style={{ marginTop: 8 }} className="small"><b>{t.signal}</b> · now: {t.now}<div className="muted">{t.record}</div><div>{t.meaning}</div><Unverified list={t.unverified} /></div>))}
            </div>
          )}
          {r.why_it_fell.length > 0 && (
            <div className="tile" style={{ marginTop: 10 }}><div className="k">Why it may have fallen (from the data only)</div>
              {r.why_it_fell.map((x, i) => (
                <div key={i} style={{ marginTop: 8 }}><b style={{ fontSize: 13.5 }}>{x.point}</b> <span className="chip" style={{ fontSize: 10.5, padding: '1px 6px' }}>{x.source}</span><div className="small muted">{x.evidence}</div><Unverified list={x.unverified} /></div>))}
            </div>
          )}
          <div className="grid2" style={{ marginTop: 10 }}>
            <div className="tile"><div className="k" style={{ color: 'var(--good)' }}>AI: business positives</div>{r.business.plus.map((x) => <div key={x} className="small" style={{ marginTop: 6 }}>+ {x}</div>)}</div>
            <div className="tile"><div className="k" style={{ color: 'var(--bad)' }}>AI: business negatives</div>{r.business.minus.map((x) => <div key={x} className="small" style={{ marginTop: 6 }}>− {x}</div>)}</div>
          </div>
          <Unverified list={r.business.unverified} />
          <div className="small" style={{ marginTop: 10, display: 'flex', flexWrap: 'wrap', gap: '4px 18px' }}>
            <span>Confidence: <b style={{ color: CONF[r.confidence?.level] || 'var(--text)' }}>{r.confidence?.level}</b> <span className="muted">· {r.confidence?.why}</span></span>
            {r.numbers?.checked > 0 && <span style={{ color: r.numbers.found === r.numbers.checked ? 'var(--good)' : 'var(--warn)' }}>Numbers checked: {r.numbers.found} of {r.numbers.checked} found in EquityLens data</span>}
          </div>
          {r.confidence?.data_gaps?.length > 0 && <div className="small muted">Not in the data: {r.confidence.data_gaps.join('; ')}</div>}
          <div className="small muted" style={{ marginTop: 4 }}>{r.model} · {ago(r.created)} · there is no news in EquityLens data, so the AI cannot know news-driven reasons.</div>
        </>
      )}
    </div>
  )
}

export default function PriceMap({ symbol }) {
  const [d, setD] = useState(null), [err, setErr] = useState(null)
  const load = (refresh) => {
    setErr(null); if (refresh) setD(null)
    api(`/api/pricemap/${encodeURIComponent(symbol)}${refresh ? '?refresh=1' : ''}`).then(setD).catch((e) => setErr(e.message))
  }
  useEffect(() => { setD(null); load(false) }, [symbol]) // eslint-disable-line react-hooks/exhaustive-deps
  if (err) return <div className="card t-bad">⚠️ {err}</div>
  if (!d) return <Loading text="Measuring levels, past falls, the sector and its peers… (first time can take ~20 s)" />
  const w = d.where, cur = d.currency, sym = (d.symbol || '').replace(/^US:/, '')
  const ix = d.sector.index
  const secFall = ix && !ix.error ? ix.fall_pct : d.sector.peer_median_fall
  return (
    <>
      <div className="pm-tiles" style={{ marginBottom: 12 }}>
        <Tile k="Fall so far" v={`−${w.fall_pct}%`} s={`from its highest close in 52 weeks, ${cur}${n2(w.high)} on ${w.high_date}, ${w.days_since_high} sessions ago`} tone={w.fall_pct >= 10 ? 'bad' : undefined} />
        <Tile k="Stage" v={w.stage} s="pullback <10% · correction 10–20% · bear >20%" tone={STAGE_TONE[w.stage]} />
        <Tile k={ix && !ix.error ? `Sector · ${ix.name}` : 'Sector · median peer'} v={secFall !== undefined && secFall !== null ? `−${secFall}%` : '—'}
          s={d.sector.breadth ? `${d.sector.breadth.above50} of ${d.sector.breadth.of} peers above their 50-day` : 'no peer prices'} />
        <Tile k="Business" v={d.business.score !== null && d.business.score !== undefined ? `${Math.round(d.business.score)}/100` : '—'} s={d.business.verdict || ''} />
      </div>
      <Ladder lv={d.levels} cur={cur} tr={d.level_track} />
      <Further f={d.further} w={w} cur={cur} sym={sym} />
      <Sector s={d.sector} sym={sym} m={d.market} />
      <ValueFloor v={d.value} cur={cur} price={w.price} />
      <Signals list={d.signals} />
      <Business b={d.business} />
      <PriceMapAI sym={d.symbol} date={w.date} />
      <details className="card small">
        <summary style={{ cursor: 'pointer' }}>How every number here is measured</summary>
        <pre style={{ whiteSpace: 'pre-wrap', fontSize: 12, marginTop: 8 }}>{d.rules}</pre>
        <div className="muted">Prices: {d.price_source}{d.real_ohlc ? '' : ' (closes only: highs and lows are closes)'} · {d.bars_n} sessions from {d.bars_from} to {w.date}. <button className="btn small" onClick={() => load(true)}>↻ Re-measure</button></div>
      </details>
      <div className="small muted">Research aid, not investment advice. Levels and odds describe this stock's past, not a promise.</div>
    </>
  )
}
