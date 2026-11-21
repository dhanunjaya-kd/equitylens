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

const SRC_L = { zigzag: 'Major swing', gap: 'Unfilled gap', volume: 'Volume profile', fib: 'Fibonacci', ma: 'Moving average', '52w': '52-week high/low' }
const zoneTxt = (z, cur) => (z.lo === z.hi ? `${cur}${n2(z.lo)}` : `${cur}${n2(z.lo)} – ${n2(z.hi)}`)
const pct = (x) => (x === null || x === undefined ? '—' : `${(+x).toFixed(1)}%`)
const num = (x) => (x === null || x === undefined ? '—' : (+x).toLocaleString('en-IN'))
const SIDE = { support: { title: 'Support zones', verb: 'price bounced', more: 'moved up' }, resistance: { title: 'Resistance zones', verb: 'price turned down', more: 'moved down' } }

function SettingsLink({ text }) {
  return <button className="btn small" onClick={() => go('settings')}>{text}</button>
}

function ZoneEvidence({ tr }) {
  const [open, setOpen] = useState(false)
  if (!tr) {
    return (
      <div className="pmap-ev">
        <b>Reliability check: not run yet.</b> These zones come from this stock's own history. Whether zones like these usually hold has not been checked yet, so treat them as a map only.
        <div style={{ marginTop: 6 }}><SettingsLink text="Run it in Settings → Data checks" /></div>
      </div>
    )
  }
  if (tr.stale) {
    return (
      <div className="pmap-ev">
        <b>Reliability check is out of date</b> (it was run on older zone rules, {tr.built}). Run it again to check the zones shown here.
        <div style={{ marginTop: 6 }}><SettingsLink text="Run it in Settings → Data checks" /></div>
      </div>
    )
  }
  const line = (side) => {
    const b = tr.result?.[side]
    if (!b) return null
    const S = SIDE[side]
    let chance
    if (!tr.has_chance) chance = <span className="muted"> Not yet compared with random prices: run the check again in Settings.</span>
    else if (b.beats_chance === true) chance = <> At random prices of the same width and distance it was {pct(b.random?.held_pct)}: <b style={{ color: 'var(--good)' }}>real zones beat chance by {b.edge_pts} points</b>.</>
    else if (b.beats_chance === false) chance = <> At random prices of the same width and distance it was {pct(b.random?.held_pct)}: <b style={{ color: 'var(--bad)' }}>real zones did not clearly beat chance</b> ({b.edge_pts} points).</>
    else chance = <span className="muted"> Too few tests to compare with random prices.</span>
    return <div style={{ marginTop: 4 }}><b>{S.title}:</b> {S.verb} {pct(b.all.held_pct)} of the time ({num(b.all.n)} tests).{chance}</div>
  }
  const rec = ['support', 'resistance'].map((k) => tr.result?.[k]?.passed)
  return (
    <div className="pmap-ev">
      <div className="muted">Reliability check on {num(tr.stocks)} NSE stocks, built {tr.built}. "Held" = price then moved two days' normal move away from the zone before closing half a day's move through it.</div>
      {line('support')}{line('resistance')}
      <div style={{ marginTop: 4 }}>
        {rec.every((x) => x === false) && <>A zone's own past record ("held X of Y") <b>did not</b> predict its next test, so those counts below are history only.</>}
        {rec.every((x) => x === true) && <>A zone's own past record ("held X of Y") <b>did</b> predict its next test.</>}
        {!rec.every((x) => x === false) && !rec.every((x) => x === true) && <>Whether a zone's own record predicts its next test: supports {rec[0] === true ? 'yes' : rec[0] === false ? 'no' : 'too few tests'}, resistances {rec[1] === true ? 'yes' : rec[1] === false ? 'no' : 'too few tests'}.</>}
      </div>
      {tr.market_note && <div style={{ color: 'var(--warn)', marginTop: 4 }}>{tr.market_note}</div>}
      <button className="btn small" style={{ marginTop: 8 }} onClick={() => setOpen(!open)}>{open ? 'Hide the evidence' : 'See the evidence'}</button>
      {open && <EvidenceTable tr={tr} />}
    </div>
  )
}

function EvidenceTable({ tr }) {
  const R = tr.result || {}
  const rows = (side) => {
    const b = R[side]
    if (!b) return []
    const out = [['All zones', b.all, b.halves?.first_half, b.halves?.second_half, true]]
    if (b.random) out.push(['Random prices (same width)', b.random, b.random.halves?.first_half, b.random.halves?.second_half, true])
    out.push(['— by the zone\'s own record —'])
    Object.entries(b.buckets || {}).forEach(([k, v]) => out.push([k, v, v.first_half, v.second_half]))
    out.push(['— by kind of level —'])
    Object.entries(b.sources || {}).forEach(([k, v]) => out.push([SRC_L[k] || k, v, v.first_half, v.second_half]))
    if (b.confluence) Object.entries(b.confluence).forEach(([k, v]) => out.push([`Zones with ${k}`, v]))
    return out
  }
  const cell = (x) => (x ? `${pct(x.held_pct)} · ${num(x.n)}` : '')
  return (
    <div style={{ overflowX: 'auto', marginTop: 8 }}>
      {['support', 'resistance'].map((side) => (
        <div key={side} style={{ marginBottom: 12 }}>
          <b>{SIDE[side].title}: held at the next test (% · number of tests)</b>
          <table className="pm-table" style={{ minWidth: 520 }}>
            <thead><tr><th /><th>All years</th><th>Before {tr.split?.slice(0, 4) || '2021'}</th><th>From {tr.split?.slice(0, 4) || '2021'}</th></tr></thead>
            <tbody>{rows(side).map(([k, a, f, s2, strong]) => (k.startsWith('—')
              ? <tr key={k}><td colSpan={4} className="muted small">{k}</td></tr>
              : <tr key={k} style={strong ? { fontWeight: 700 } : undefined}><td>{k}</td><td>{cell(a)}</td><td>{cell(f)}</td><td>{cell(s2)}</td></tr>))}</tbody>
          </table>
          {R[side]?.bands?.length > 0 && (
            <table className="pm-table" style={{ minWidth: 520, marginTop: 6 }}>
              <thead><tr><th>Distance from price (days' move)</th><th>Real zones</th><th>Random prices</th></tr></thead>
              <tbody>{R[side].bands.map((bd) => <tr key={bd.band}><td>{bd.band}</td><td>{cell(bd.real)}</td><td>{cell(bd.random)}</td></tr>)}</tbody>
            </table>
          )}
          {R[side]?.random_placed?.tried > 0 && (
            <div className="small muted">A random zone could be placed (a free price with no real zone near it) for {R[side].random_placed.pct}% of {num(R[side].random_placed.tried)} real zones; the rest had zones all around and no random partner.</div>
          )}
          {R[side]?.edge_by_half && Object.keys(R[side].edge_by_half).length > 0 && (
            <div className="small muted">Edge over random prices at the same distance: before {tr.split?.slice(0, 4) || '2021'} {R[side].edge_by_half.first_half ?? '—'} pts · from {tr.split?.slice(0, 4) || '2021'} {R[side].edge_by_half.second_half ?? '—'} pts · all years {R[side].edge_pts ?? '—'} pts</div>
          )}
        </div>
      ))}
      <div className="small muted" style={{ lineHeight: 1.5 }}>
        <div>Tests fixed before the run. Record: {tr.pass_test}</div>
        {tr.chance_test && <div>Chance: {tr.chance_test}</div>}
        {tr.skipped && Object.keys(tr.skipped).length > 0 && <div>Stocks left out: {Object.entries(tr.skipped).map(([k, v]) => `${k} (${v})`).join(' · ')}</div>}
        {tr.note && <div>{tr.note}</div>}
      </div>
    </div>
  )
}

function ZoneRow({ l, cur, tr, beyond }) {
  const [open, setOpen] = useState(false)
  const res = l.kind === 'resistance'
  const kinds = l.sources || [l.source]
  const ks = tr && !tr.stale ? tr.result?.[l.kind]?.sources?.[l.source] : null
  return (
    <div className="pmap-lv pmap-click" onClick={() => setOpen(!open)}>
      <span className="pmap-kind" style={{ color: res ? 'var(--bad)' : 'var(--good)' }}>{res ? 'RESISTANCE' : 'SUPPORT'}</span>
      <b className="pmap-px">{zoneTxt(l, cur)}</b>
      <span className="pmap-dist">{sg(l.dist_pct)} · {Math.abs(l.dist_atr)} days' move{beyond ? <><br /><span style={{ fontSize: 11 }}>beyond a normal month</span></> : ''}</span>
      <span className="pmap-what">
        {kinds.map((k) => <span key={k} className="pmap-chip">{SRC_L[k] || k}</span>)}
        <span className="muted small"> {open ? '▴' : '▾ details'}</span>
        {open && (
          <span style={{ display: 'block', marginTop: 6 }} className="small">
            {(l.parts || [l.what]).map((p) => <span key={p} style={{ display: 'block' }}>• {p}</span>)}
            {ks && ks.n > 0 && <span className="pmap-bt" style={{ color: 'var(--muted)' }}>Reliability check: zones led by this kind ({SRC_L[l.source] || l.source}) held at the next test {pct(ks.held_pct)} of {num(ks.n)} times.</span>}
            {l.last_test && <span className="pmap-bt" style={{ color: 'var(--muted)' }}>Last test here: {l.last_test}</span>}
          </span>
        )}
      </span>
      <span className="pmap-held">{l.tests ? `held ${l.held} of ${l.tests}` : 'not tested in 3 years'}<br /><span style={{ fontSize: 11 }}>{l.tests ? 'history only' : ''}</span></span>
    </div>
  )
}

function Ladder({ lv, cur, tr, range, sym }) {
  const beyond = (l) => !!range && (l.kind === 'support' ? l.hi < range.lo : l.lo > range.hi)
  return (
    <div className="card">
      <h3 style={{ marginTop: 0 }}>Support and resistance zones</h3>
      <div className="small muted">From {sym}'s own price history: major swing highs and lows, the most-traded prices of the last year, unfilled gaps, Fibonacci levels, 50/200-day averages and the 52-week high/low. {sym} usually moves about {cur}{n2(lv.atr)} ({lv.atr_pct}%) a day; distances are shown in % and in days of that move. Tap a zone for details.</div>
      <ZoneEvidence tr={tr} />
      {[...lv.resistance].reverse().map((l, i) => <ZoneRow key={`r${i}`} l={l} cur={cur} tr={tr} beyond={beyond(l)} />)}
      <div className="pmap-lv pmap-now">
        <span className="pmap-kind">NOW</span><b className="pmap-px">{cur}{n2(lv.price)}</b><span className="pmap-dist" />
        <span className="pmap-what">Last close{lv.inside?.length > 0 && lv.inside.map((z) => <span key={z.lo} className="pmap-bt" style={{ color: 'var(--warn)' }}>Sitting inside a zone: {zoneTxt(z, cur)} ({(z.sources || []).map((k) => SRC_L[k] || k).join(', ')})</span>)}</span>
        <span className="pmap-held" />
      </div>
      {lv.support.map((l, i) => <ZoneRow key={`s${i}`} l={l} cur={cur} tr={tr} beyond={beyond(l)} />)}
      {!lv.support.length && <div className="small muted" style={{ padding: 8 }}>No support zone below today's price (down to half of it).</div>}
      {!lv.resistance.length && <div className="small muted" style={{ padding: 8 }}>No resistance zone above (up to twice today's price).</div>}
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
          ) : (
            <div style={{ marginTop: 6 }}>
              <div className="small" style={{ color: 'var(--warn)', marginBottom: 6 }}>{v.record_note}</div>
              {v.record_note?.includes('Not tested') && <SettingsLink text="Run it in Settings → Data checks" />}
            </div>
          )}
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
      <Ladder lv={d.levels} cur={cur} tr={d.level_track} range={d.further.range_1m} sym={sym} />
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
