// Chart indicators, worked out from the candles on the chart. Standard definitions (TradingView's defaults);
// the values are checked against the independent `ta` library in backend/tests/test_indicators_js.py.
// Every function returns arrays aligned with the bars, null where there is not enough history yet.

// ---------------------------------------------------------------- building blocks
const N = (x) => (x === null || x === undefined || Number.isNaN(x) ? null : x)
export const sma = (v, n) => {
  const out = new Array(v.length).fill(null)
  let s = 0, cnt = 0
  for (let i = 0; i < v.length; i++) {
    if (v[i] === null) { s = 0; cnt = 0; continue }
    s += v[i]; cnt++
    if (cnt > n) { s -= v[i - n]; cnt = n }
    if (cnt === n) out[i] = s / n
  }
  return out
}
// EMA seeded with the SMA of the first n values (TradingView)
export const ema = (v, n) => {
  const out = new Array(v.length).fill(null), k = 2 / (n + 1)
  let e = null, start = v.findIndex((x) => x !== null)
  if (start < 0) return out
  for (let i = start; i < v.length; i++) {
    if (v[i] === null) continue
    if (e === null) {
      if (i - start + 1 < n) continue
      let s = 0; for (let j = i - n + 1; j <= i; j++) s += v[j]
      e = s / n
    } else e = v[i] * k + e * (1 - k)
    out[i] = e
  }
  return out
}
// Wilder's smoothing (RMA): SMA seed, then (prev * (n - 1) + x) / n
export const rma = (v, n) => {
  const out = new Array(v.length).fill(null)
  let e = null, start = v.findIndex((x) => x !== null)
  if (start < 0) return out
  for (let i = start; i < v.length; i++) {
    if (v[i] === null) continue
    if (e === null) {
      if (i - start + 1 < n) continue
      let s = 0; for (let j = i - n + 1; j <= i; j++) s += v[j]
      e = s / n
    } else e = (e * (n - 1) + v[i]) / n
    out[i] = e
  }
  return out
}
export const wma = (v, n) => v.map((_, i) => {
  if (i < n - 1) return null
  let s = 0, w = 0
  for (let j = 0; j < n; j++) { const x = v[i - n + 1 + j]; if (x === null) return null; s += x * (j + 1); w += j + 1 }
  return s / w
})
const roll = (v, n, f) => v.map((_, i) => { if (i < n - 1) return null; const w = v.slice(i - n + 1, i + 1); return w.some((x) => x === null) ? null : f(w) })
const highest = (v, n) => roll(v, n, (w) => Math.max(...w))
const lowest = (v, n) => roll(v, n, (w) => Math.min(...w))
const sum = (v, n) => roll(v, n, (w) => w.reduce((a, b) => a + b, 0))
const stdev = (v, n) => roll(v, n, (w) => { const m = w.reduce((a, b) => a + b, 0) / n; return Math.sqrt(w.reduce((a, b) => a + (b - m) ** 2, 0) / n) })
const sub = (a, b) => a.map((x, i) => (x === null || b[i] === null ? null : x - b[i]))
const tr = (b) => b.map((x, i) => (i ? Math.max(x.h - x.l, Math.abs(x.h - b[i - 1].c), Math.abs(x.l - b[i - 1].c)) : x.h - x.l))
export const atr = (b, n = 14) => rma(tr(b), n)

// ---------------------------------------------------------------- indicators
const C = (b) => b.map((x) => x.c)
const H = (b) => b.map((x) => x.h)
const Lo = (b) => b.map((x) => x.l)
const V = (b) => b.map((x) => x.v || 0)

export const calc = {
  sma: (b, n) => sma(C(b), n),
  ema: (b, n) => ema(C(b), n),
  wma: (b, n) => wma(C(b), n),
  hma: (b, n) => { const c = C(b); const d = sub(wma(c, Math.floor(n / 2)).map((x) => (x === null ? null : 2 * x)), wma(c, n)); return wma(d, Math.floor(Math.sqrt(n))) },
  dema: (b, n) => { const e = ema(C(b), n); const e2 = ema(e, n); return e.map((x, i) => (x === null || e2[i] === null ? null : 2 * x - e2[i])) },
  tema: (b, n) => { const e = ema(C(b), n), e2 = ema(e, n), e3 = ema(e2, n); return e.map((x, i) => (e3[i] === null ? null : 3 * x - 3 * e2[i] + e3[i])) },
  vwma: (b, n) => { const pv = sum(b.map((x) => x.c * (x.v || 0)), n), vv = sum(V(b), n); return pv.map((x, i) => (x === null || !vv[i] ? null : x / vv[i])) },
  smma: (b, n) => rma(C(b), n),
  kama: (b, n = 10, f = 2, s = 30) => {
    const c = C(b), out = new Array(c.length).fill(null), fs = 2 / (f + 1), ss = 2 / (s + 1)
    let k = null
    for (let i = n; i < c.length; i++) {
      let vol = 0; for (let j = i - n + 1; j <= i; j++) vol += Math.abs(c[j] - c[j - 1])
      const er = vol ? Math.abs(c[i] - c[i - n]) / vol : 0
      const sc = (er * (fs - ss) + ss) ** 2
      k = k === null ? c[i] : k + sc * (c[i] - k)
      out[i] = k
    }
    return out
  },
  rsi: (b, n = 14) => {
    const c = C(b), up = c.map((x, i) => (i ? Math.max(x - c[i - 1], 0) : null)), dn = c.map((x, i) => (i ? Math.max(c[i - 1] - x, 0) : null))
    const u = rma(up, n), d = rma(dn, n)
    return u.map((x, i) => (x === null ? null : d[i] === 0 ? 100 : 100 - 100 / (1 + x / d[i])))
  },
  stoch: (b, n = 14, k = 3, d = 3) => {
    const hh = highest(H(b), n), ll = lowest(Lo(b), n)
    const raw = b.map((x, i) => (hh[i] === null ? null : hh[i] === ll[i] ? 50 : (100 * (x.c - ll[i])) / (hh[i] - ll[i])))
    const K = sma(raw, k); return [K, sma(K, d)]
  },
  stochrsi: (b, r = 14, n = 14, k = 3, d = 3) => {
    const rs = calc.rsi(b, r), hh = highest(rs, n), ll = lowest(rs, n)
    const raw = rs.map((x, i) => (hh[i] === null ? null : hh[i] === ll[i] ? 0 : (100 * (x - ll[i])) / (hh[i] - ll[i])))
    const K = sma(raw, k); return [K, sma(K, d)]
  },
  macd: (b, f = 12, s = 26, g = 9) => { const m = sub(ema(C(b), f), ema(C(b), s)); const sg = ema(m, g); return [m, sg, sub(m, sg)] },
  ppo: (b, f = 12, s = 26, g = 9) => { const ef = ema(C(b), f), es = ema(C(b), s); const p = ef.map((x, i) => (x === null || es[i] === null ? null : (100 * (x - es[i])) / es[i])); const sg = ema(p, g); return [p, sg, sub(p, sg)] },
  cci: (b, n = 20) => {
    const tp = b.map((x) => (x.h + x.l + x.c) / 3), m = sma(tp, n)
    return tp.map((x, i) => { if (m[i] === null) return null; let md = 0; for (let j = i - n + 1; j <= i; j++) md += Math.abs(tp[j] - m[i]); md /= n; return md ? (x - m[i]) / (0.015 * md) : 0 })
  },
  willr: (b, n = 14) => { const hh = highest(H(b), n), ll = lowest(Lo(b), n); return b.map((x, i) => (hh[i] === null ? null : hh[i] === ll[i] ? -50 : (-100 * (hh[i] - x.c)) / (hh[i] - ll[i]))) },
  roc: (b, n = 12) => b.map((x, i) => (i >= n ? (100 * (x.c - b[i - n].c)) / b[i - n].c : null)),
  mom: (b, n = 10) => b.map((x, i) => (i >= n ? x.c - b[i - n].c : null)),
  ao: (b) => { const mp = b.map((x) => (x.h + x.l) / 2); return sub(sma(mp, 5), sma(mp, 34)) },
  tsi: (b, r = 25, s = 13, g = 13) => {
    const c = C(b), pc = c.map((x, i) => (i ? x - c[i - 1] : null)), apc = pc.map((x) => (x === null ? null : Math.abs(x)))
    const num = ema(ema(pc, r), s), den = ema(ema(apc, r), s)
    const t = num.map((x, i) => (x === null || !den[i] ? null : (100 * x) / den[i])); return [t, ema(t, g)]
  },
  uo: (b, a = 7, m = 14, l = 28) => {
    const bp = b.map((x, i) => (i ? x.c - Math.min(x.l, b[i - 1].c) : null)), t = b.map((x, i) => (i ? Math.max(x.h, b[i - 1].c) - Math.min(x.l, b[i - 1].c) : null))
    const av = (n) => { const s1 = sum(bp, n), s2 = sum(t, n); return s1.map((x, i) => (x === null || !s2[i] ? null : x / s2[i])) }
    const A = av(a), M = av(m), Lg = av(l)
    return A.map((x, i) => (Lg[i] === null ? null : (100 * (4 * x + 2 * M[i] + Lg[i])) / 7))
  },
  cmo: (b, n = 14) => {
    const c = C(b), up = c.map((x, i) => (i ? Math.max(x - c[i - 1], 0) : null)), dn = c.map((x, i) => (i ? Math.max(c[i - 1] - x, 0) : null))
    const su = sum(up, n), sd = sum(dn, n); return su.map((x, i) => (x === null || x + sd[i] === 0 ? null : (100 * (x - sd[i])) / (x + sd[i])))
  },
  trix: (b, n = 15) => { const e3 = ema(ema(ema(C(b), n), n), n); return e3.map((x, i) => (i && x !== null && e3[i - 1] ? (100 * (x - e3[i - 1])) / e3[i - 1] : null)) },
  bb: (b, n = 20, k = 2) => { const c = C(b), m = sma(c, n), sd = stdev(c, n); return [m.map((x, i) => (x === null ? null : x + k * sd[i])), m, m.map((x, i) => (x === null ? null : x - k * sd[i]))] },
  bbpct: (b, n = 20, k = 2) => { const [u, , l] = calc.bb(b, n, k); return b.map((x, i) => (u[i] === null || u[i] === l[i] ? null : (x.c - l[i]) / (u[i] - l[i]))) },
  bbw: (b, n = 20, k = 2) => { const [u, m, l] = calc.bb(b, n, k); return m.map((x, i) => (x ? (100 * (u[i] - l[i])) / x : null)) },
  atr: (b, n = 14) => atr(b, n),
  stdev: (b, n = 20) => stdev(C(b), n),
  hv: (b, n = 20, perYear = 252) => { const c = C(b), lr = c.map((x, i) => (i ? Math.log(x / c[i - 1]) : null)); return stdev(lr, n).map((x) => (x === null ? null : x * Math.sqrt(perYear) * 100)) },
  chop: (b, n = 14) => { const s = sum(tr(b), n), hh = highest(H(b), n), ll = lowest(Lo(b), n); return s.map((x, i) => (x === null || hh[i] === ll[i] ? null : (100 * Math.log10(x / (hh[i] - ll[i]))) / Math.log10(n))) },
  donchian: (b, n = 20) => { const u = highest(H(b), n), l = lowest(Lo(b), n); return [u, u.map((x, i) => (x === null ? null : (x + l[i]) / 2)), l] },
  keltner: (b, n = 20, k = 2, an = 10) => { const m = ema(C(b), n), a = atr(b, an); return [m.map((x, i) => (x === null || a[i] === null ? null : x + k * a[i])), m, m.map((x, i) => (x === null || a[i] === null ? null : x - k * a[i]))] },
  adx: (b, n = 14) => {
    const pdm = b.map((x, i) => { if (!i) return null; const u = x.h - b[i - 1].h, d = b[i - 1].l - x.l; return u > d && u > 0 ? u : 0 })
    const mdm = b.map((x, i) => { if (!i) return null; const u = x.h - b[i - 1].h, d = b[i - 1].l - x.l; return d > u && d > 0 ? d : 0 })
    const t = tr(b).map((x, i) => (i ? x : null))
    const st = rma(t, n), sp = rma(pdm, n), sm = rma(mdm, n)
    const pdi = sp.map((x, i) => (x === null || !st[i] ? null : (100 * x) / st[i])), mdi = sm.map((x, i) => (x === null || !st[i] ? null : (100 * x) / st[i]))
    const dx = pdi.map((x, i) => (x === null || x + mdi[i] === 0 ? (x === null ? null : 0) : (100 * Math.abs(x - mdi[i])) / (x + mdi[i])))
    return [rma(dx, n), pdi, mdi]
  },
  aroon: (b, n = 25) => {
    const up = [], dn = []
    for (let i = 0; i < b.length; i++) {
      if (i < n) { up.push(null); dn.push(null); continue }
      let hi = i - n, lo = i - n
      for (let j = i - n; j <= i; j++) { if (b[j].h >= b[hi].h) hi = j; if (b[j].l <= b[lo].l) lo = j }
      up.push((100 * (n - (i - hi))) / n); dn.push((100 * (n - (i - lo))) / n)
    }
    return [up, dn]
  },
  vortex: (b, n = 14) => {
    const vp = b.map((x, i) => (i ? Math.abs(x.h - b[i - 1].l) : null)), vm = b.map((x, i) => (i ? Math.abs(x.l - b[i - 1].h) : null)), t = tr(b).map((x, i) => (i ? x : null))
    const sp = sum(vp, n), sm2 = sum(vm, n), st = sum(t, n)
    return [sp.map((x, i) => (x === null || !st[i] ? null : x / st[i])), sm2.map((x, i) => (x === null || !st[i] ? null : x / st[i]))]
  },
  supertrend: (b, n = 10, m = 3) => {
    const a = atr(b, n), line = [], dir = []
    let up = null, dn = null, trend = 1
    b.forEach((x, i) => {
      if (a[i] === null) { line.push(null); dir.push(0); return }
      const mid = (x.h + x.l) / 2, bu = mid - m * a[i], bd = mid + m * a[i]
      up = up === null || b[i - 1].c < up ? bu : Math.max(bu, up)
      dn = dn === null || b[i - 1].c > dn ? bd : Math.min(bd, dn)
      if (trend === 1 && x.c < up) trend = -1; else if (trend === -1 && x.c > dn) trend = 1
      line.push(trend === 1 ? up : dn); dir.push(trend)
    })
    return [line.map((v, i) => (dir[i] === 1 ? v : null)), line.map((v, i) => (dir[i] === -1 ? v : null))]
  },
  // TradingView's ta.sar, step by step (its documented Pine version): move toward the extreme point, flip when price
  // crosses, then keep the SAR beyond the last two candles' lows (highs in a downtrend)
  psar: (b, start = 0.02, inc = 0.02, max = 0.2) => {
    const out = new Array(b.length).fill(null)
    if (b.length < 2) return out
    let below = b[1].c > b[0].c, ext = below ? b[1].h : b[1].l, res = below ? b[0].l : b[0].h, af = start
    for (let i = 1; i < b.length; i++) {
      let first = i === 1
      res = res + af * (ext - res)
      if (below) {
        if (res > b[i].l) { first = true; below = false; res = Math.max(b[i].h, ext); ext = b[i].l; af = start }
      } else if (res < b[i].h) { first = true; below = true; res = Math.min(b[i].l, ext); ext = b[i].h; af = start }
      if (!first) {
        if (below) { if (b[i].h > ext) { ext = b[i].h; af = Math.min(af + inc, max) } } else if (b[i].l < ext) { ext = b[i].l; af = Math.min(af + inc, max) }
      }
      if (below) { res = Math.min(res, b[i - 1].l); if (i > 1) res = Math.min(res, b[i - 2].l) } else { res = Math.max(res, b[i - 1].h); if (i > 1) res = Math.max(res, b[i - 2].h) }
      out[i] = res
    }
    return out
  },
  ichimoku: (b, t = 9, k = 26, s = 52) => {
    const mid = (n) => { const hh = highest(H(b), n), ll = lowest(Lo(b), n); return hh.map((x, i) => (x === null ? null : (x + ll[i]) / 2)) }
    const ten = mid(t), kij = mid(k), sb = mid(s)
    const sa = ten.map((x, i) => (x === null || kij[i] === null ? null : (x + kij[i]) / 2))
    const shift = (v) => v.map((_, i) => (i >= k ? v[i - k] : null))     // the cloud is plotted 26 bars ahead; beyond the last candle it is not drawn
    return [ten, kij, shift(sa), shift(sb)]
  },
  linreg: (b, n = 50) => C(b).map((_, i, c) => {
    if (i < n - 1) return null
    let sx = 0, sy = 0, sxy = 0, sxx = 0
    for (let j = 0; j < n; j++) { const y = c[i - n + 1 + j]; sx += j; sy += y; sxy += j * y; sxx += j * j }
    const a = (n * sxy - sx * sy) / (n * sxx - sx * sx), bb = (sy - a * sx) / n
    return a * (n - 1) + bb
  }),
  obv: (b) => { let s = 0; return b.map((x, i) => { if (i) s += x.c > b[i - 1].c ? x.v : x.c < b[i - 1].c ? -x.v : 0; return s }) },
  ad: (b) => { let s = 0; return b.map((x) => { const r = x.h - x.l; s += r ? (((x.c - x.l) - (x.h - x.c)) / r) * (x.v || 0) : 0; return s }) },
  cmf: (b, n = 20) => { const mfv = b.map((x) => { const r = x.h - x.l; return r ? (((x.c - x.l) - (x.h - x.c)) / r) * (x.v || 0) : 0 }); const a = sum(mfv, n), vv = sum(V(b), n); return a.map((x, i) => (x === null || !vv[i] ? null : x / vv[i])) },
  mfi: (b, n = 14) => {
    const tp = b.map((x) => (x.h + x.l + x.c) / 3)
    const pos = tp.map((x, i) => (i ? (x > tp[i - 1] ? x * (b[i].v || 0) : 0) : null)), neg = tp.map((x, i) => (i ? (x < tp[i - 1] ? x * (b[i].v || 0) : 0) : null))
    const sp = sum(pos, n), sn = sum(neg, n)
    return sp.map((x, i) => (x === null ? null : sn[i] === 0 ? 100 : 100 - 100 / (1 + x / sn[i])))
  },
  fi: (b, n = 13) => ema(b.map((x, i) => (i ? (x.c - b[i - 1].c) * (x.v || 0) : null)), n),
  eom: (b, n = 14) => sma(b.map((x, i) => (i && x.v ? (((x.h - b[i - 1].h) + (x.l - b[i - 1].l)) * (x.h - x.l)) / (2 * x.v) * 1e8 : i ? 0 : null)), n),
  vo: (b, f = 5, s = 10) => { const a = ema(V(b), f), z = ema(V(b), s); return a.map((x, i) => (x === null || !z[i] ? null : (100 * (x - z[i])) / z[i])) },
  pvt: (b) => { let s = 0; return b.map((x, i) => { if (i && b[i - 1].c) s += ((x.c - b[i - 1].c) / b[i - 1].c) * (x.v || 0); return s }) },
  rvol: (b, n = 20) => { const v = V(b); return v.map((x, i) => { if (i < n) return null; let s = 0; for (let j = i - n; j < i; j++) s += v[j]; return s ? x / (s / n) : null }) },
  swings: (b, k = 5) => {
    const out = []
    for (let i = k; i < b.length - k; i++) {
      let hi = true, lo = true
      for (let j = i - k; j <= i + k; j++) { if (j === i) continue; if (b[j].h > b[i].h || (j > i && b[j].h === b[i].h)) hi = false; if (b[j].l < b[i].l || (j > i && b[j].l === b[i].l)) lo = false }
      if (hi) out.push({ i, kind: 'H', p: b[i].h })
      if (lo) out.push({ i, kind: 'L', p: b[i].l })
    }
    return out
  },
  zigzag: (b, pct = 5) => {
    const pts = []
    if (b.length < 2) return pts
    let dir = 0, ext = { i: 0, p: b[0].c }
    for (let i = 1; i < b.length; i++) {
      const x = b[i]
      if (dir >= 0 && x.h > ext.p && (dir === 1 || x.h >= ext.p * (1 + pct / 100) || !pts.length)) { if (dir !== 1 && pts.length === 0) pts.push({ ...ext }); dir = 1; ext = { i, p: x.h } }
      if (dir === 1 && x.l <= ext.p * (1 - pct / 100)) { pts.push({ ...ext }); dir = -1; ext = { i, p: x.l }; continue }
      if (dir <= 0 && x.l < ext.p && (dir === -1 || x.l <= ext.p * (1 - pct / 100))) { if (dir !== -1 && pts.length === 0) pts.push({ ...ext }); dir = -1; ext = { i, p: x.l } }
      if (dir === -1 && x.h >= ext.p * (1 + pct / 100)) { pts.push({ ...ext }); dir = 1; ext = { i, p: x.h } }
    }
    pts.push({ ...ext })
    return pts
  },
  prevday: (b, dayOf) => {
    // previous session's high and low, drawn across the next session (intraday frames)
    const hi = new Array(b.length).fill(null), lo = new Array(b.length).fill(null)
    let cur = null, curH = null, curL = null, pH = null, pL = null
    b.forEach((x, i) => {
      const d = dayOf(x)
      if (d !== cur) { if (cur !== null) { pH = curH; pL = curL } cur = d; curH = x.h; curL = x.l } else { curH = Math.max(curH, x.h); curL = Math.min(curL, x.l) }
      hi[i] = pH; lo[i] = pL
    })
    return [hi, lo]
  },
}

// ---------------------------------------------------------------- the menu: name, group, where it is drawn, its lines
const P = (k, label, color, extra = {}) => ({ k, label, color, ...extra })
const ma = (id, name, short, fn, n, color) => ({ id, name: `${name} (${n})`, short: `${short} ${n}`, cat: 'Averages', pane: 'price', lines: [P('v', `${short} ${n}`, color)], run: (b) => ({ v: calc[fn](b, n) }) })

export const INDICATORS = [
  ma('sma20', 'Simple Moving Average', 'SMA', 'sma', 20, '#26a69a'),
  ma('sma50', 'Simple Moving Average', 'SMA', 'sma', 50, '#ef5350'),
  ma('sma200', 'Simple Moving Average', 'SMA', 'sma', 200, '#ab47bc'),
  ma('ema9', 'Exponential Moving Average', 'EMA', 'ema', 9, '#00bcd4'),
  ma('ema20', 'Exponential Moving Average', 'EMA', 'ema', 20, '#2962ff'),
  ma('ema50', 'Exponential Moving Average', 'EMA', 'ema', 50, '#e040fb'),
  ma('ema200', 'Exponential Moving Average', 'EMA', 'ema', 200, '#ffb300'),
  ma('wma20', 'Weighted Moving Average', 'WMA', 'wma', 20, '#8d6e63'),
  ma('hma20', 'Hull Moving Average', 'HMA', 'hma', 20, '#43a047'),
  ma('dema20', 'Double Exponential Moving Average', 'DEMA', 'dema', 20, '#5c6bc0'),
  ma('tema20', 'Triple Exponential Moving Average', 'TEMA', 'tema', 20, '#7e57c2'),
  ma('vwma20', 'Volume Weighted Moving Average', 'VWMA', 'vwma', 20, '#f57c00'),
  ma('smma20', 'Smoothed Moving Average (RMA)', 'SMMA', 'smma', 20, '#78909c'),
  { id: 'kama', name: 'Kaufman Adaptive Moving Average (10, 2, 30)', short: 'KAMA', cat: 'Averages', pane: 'price', lines: [P('v', 'KAMA', '#c0ca33')], run: (b) => ({ v: calc.kama(b) }) },

  { id: 'st', name: 'Supertrend (10, 3)', short: 'Supertrend', cat: 'Trend', pane: 'price', lines: [P('u', 'ST', '#089981', { width: 2 }), P('d', '', '#f23645', { width: 2 })], run: (b) => { const [u, d] = calc.supertrend(b); return { u, d } } },
  { id: 'psar', name: 'Parabolic SAR (0.02, 0.2)', short: 'SAR', cat: 'Trend', pane: 'price', lines: [P('v', 'SAR', '#90a4ae', { dots: true })], run: (b) => ({ v: calc.psar(b) }) },
  { id: 'ichimoku', name: 'Ichimoku Cloud (9, 26, 52)', short: 'Ichimoku', cat: 'Trend', pane: 'price', note: 'Spans A and B are drawn 26 bars ahead; the part beyond the last candle is not shown.',
    lines: [P('t', 'Conversion', '#2962ff'), P('k', 'Base', '#b71c1c'), P('a', 'Span A', '#43a047', { dash: true }), P('b', 'Span B', '#e53935', { dash: true })], run: (b) => { const [t, k, a, s] = calc.ichimoku(b); return { t, k, a, b: s } } },
  { id: 'donchian', name: 'Donchian Channels (20)', short: 'DC 20', cat: 'Trend', pane: 'price', lines: [P('u', 'DC', '#2196f3'), P('m', '', '#ff6d00', { dash: true }), P('l', '', '#2196f3')], run: (b) => { const [u, m, l] = calc.donchian(b); return { u, m, l } } },
  { id: 'linreg', name: 'Linear Regression Curve (50)', short: 'LinReg 50', cat: 'Trend', pane: 'price', lines: [P('v', 'LinReg', '#ff9800')], run: (b) => ({ v: calc.linreg(b) }) },
  { id: 'adx', name: 'Average Directional Index / DMI (14)', short: 'ADX 14', cat: 'Trend', pane: 'own', levels: [25], lines: [P('a', 'ADX', '#ff5252', { width: 2 }), P('p', '+DI', '#089981'), P('m', '−DI', '#f23645')], run: (b) => { const [a, p, m] = calc.adx(b); return { a, p, m } } },
  { id: 'aroon', name: 'Aroon (25)', short: 'Aroon', cat: 'Trend', pane: 'own', levels: [70, 30], lines: [P('u', 'Up', '#ff6d00'), P('d', 'Down', '#2962ff')], run: (b) => { const [u, d] = calc.aroon(b); return { u, d } } },
  { id: 'vortex', name: 'Vortex Indicator (14)', short: 'VI', cat: 'Trend', pane: 'own', levels: [1], lines: [P('p', 'VI+', '#2962ff'), P('m', 'VI−', '#e91e63')], run: (b) => { const [p, m] = calc.vortex(b); return { p, m } } },

  { id: 'rsi', name: 'Relative Strength Index (14)', short: 'RSI 14', cat: 'Momentum', pane: 'own', levels: [70, 30], lines: [P('v', 'RSI', '#7e57c2')], run: (b) => ({ v: calc.rsi(b) }) },
  { id: 'stoch', name: 'Stochastic (14, 3, 3)', short: 'Stoch', cat: 'Momentum', pane: 'own', levels: [80, 20], lines: [P('k', '%K', '#2962ff'), P('d', '%D', '#ff6d00')], run: (b) => { const [k, d] = calc.stoch(b); return { k, d } } },
  { id: 'stochrsi', name: 'Stochastic RSI (3, 3, 14, 14)', short: 'Stoch RSI', cat: 'Momentum', pane: 'own', levels: [80, 20], lines: [P('k', 'K', '#2962ff'), P('d', 'D', '#ff6d00')], run: (b) => { const [k, d] = calc.stochrsi(b); return { k, d } } },
  { id: 'macd', name: 'MACD (12, 26, 9)', short: 'MACD', cat: 'Momentum', pane: 'own', hist: 'h', lines: [P('m', 'MACD', '#2962ff'), P('s', 'Signal', '#ff6d00')], run: (b) => { const [m, s, h] = calc.macd(b); return { m, s, h } } },
  { id: 'ppo', name: 'Percentage Price Oscillator (12, 26, 9)', short: 'PPO', cat: 'Momentum', pane: 'own', hist: 'h', levels: [0], lines: [P('p', 'PPO', '#26a69a'), P('s', 'Signal', '#ff6d00')], run: (b) => { const [p, s, h] = calc.ppo(b); return { p, s, h } } },
  { id: 'cci', name: 'Commodity Channel Index (20)', short: 'CCI 20', cat: 'Momentum', pane: 'own', levels: [100, -100], lines: [P('v', 'CCI', '#2196f3')], run: (b) => ({ v: calc.cci(b) }) },
  { id: 'willr', name: 'Williams %R (14)', short: '%R', cat: 'Momentum', pane: 'own', levels: [-20, -80], lines: [P('v', '%R', '#7e57c2')], run: (b) => ({ v: calc.willr(b) }) },
  { id: 'roc', name: 'Rate of Change (12)', short: 'ROC 12', cat: 'Momentum', pane: 'own', levels: [0], lines: [P('v', 'ROC', '#2962ff')], run: (b) => ({ v: calc.roc(b) }) },
  { id: 'mom', name: 'Momentum (10)', short: 'Mom 10', cat: 'Momentum', pane: 'own', levels: [0], lines: [P('v', 'Mom', '#3f51b5')], run: (b) => ({ v: calc.mom(b) }) },
  { id: 'ao', name: 'Awesome Oscillator', short: 'AO', cat: 'Momentum', pane: 'own', hist: 'v', lines: [], run: (b) => ({ v: calc.ao(b) }) },
  { id: 'tsi', name: 'True Strength Index (25, 13, 13)', short: 'TSI', cat: 'Momentum', pane: 'own', levels: [0], lines: [P('t', 'TSI', '#2962ff'), P('s', 'Signal', '#e91e63')], run: (b) => { const [t, s] = calc.tsi(b); return { t, s } } },
  { id: 'uo', name: 'Ultimate Oscillator (7, 14, 28)', short: 'UO', cat: 'Momentum', pane: 'own', levels: [70, 30], lines: [P('v', 'UO', '#f44336')], run: (b) => ({ v: calc.uo(b) }) },
  { id: 'cmo', name: 'Chande Momentum Oscillator (14)', short: 'CMO', cat: 'Momentum', pane: 'own', levels: [50, -50], lines: [P('v', 'CMO', '#2196f3')], run: (b) => ({ v: calc.cmo(b) }) },
  { id: 'trix', name: 'TRIX (15)', short: 'TRIX', cat: 'Momentum', pane: 'own', levels: [0], lines: [P('v', 'TRIX', '#ff5252')], run: (b) => ({ v: calc.trix(b) }) },

  { id: 'bb', name: 'Bollinger Bands (20, 2)', short: 'BB', cat: 'Volatility', pane: 'price', lines: [P('u', 'BB', '#2962ff', { dash: true }), P('m', '', '#ff6d00'), P('l', '', '#2962ff', { dash: true })], run: (b) => { const [u, m, l] = calc.bb(b); return { u, m, l } } },
  { id: 'kc', name: 'Keltner Channels (20, 2, ATR 10)', short: 'KC', cat: 'Volatility', pane: 'price', lines: [P('u', 'KC', '#2196f3'), P('m', '', '#787b86', { dash: true }), P('l', '', '#2196f3')], run: (b) => { const [u, m, l] = calc.keltner(b); return { u, m, l } } },
  { id: 'bbpct', name: 'Bollinger Bands %B (20, 2)', short: '%B', cat: 'Volatility', pane: 'own', levels: [1, 0], lines: [P('v', '%B', '#26a69a')], run: (b) => ({ v: calc.bbpct(b) }) },
  { id: 'bbw', name: 'Bollinger BandWidth (20, 2)', short: 'BBW', cat: 'Volatility', pane: 'own', lines: [P('v', 'BBW %', '#ff6d00')], run: (b) => ({ v: calc.bbw(b) }) },
  { id: 'atr', name: 'Average True Range (14)', short: 'ATR 14', cat: 'Volatility', pane: 'own', lines: [P('v', 'ATR', '#b71c1c')], run: (b) => ({ v: calc.atr(b) }) },
  { id: 'stdev', name: 'Standard Deviation (20)', short: 'StdDev', cat: 'Volatility', pane: 'own', lines: [P('v', 'StdDev', '#7e57c2')], run: (b) => ({ v: calc.stdev(b) }) },
  { id: 'hv', name: 'Historical Volatility (20, annualised %)', short: 'HV 20', cat: 'Volatility', pane: 'own', lines: [P('v', 'HV %', '#00897b')], run: (b, ctx) => ({ v: calc.hv(b, 20, ctx.perYear) }) },
  { id: 'chop', name: 'Choppiness Index (14)', short: 'CHOP', cat: 'Volatility', pane: 'own', levels: [61.8, 38.2], lines: [P('v', 'CHOP', '#2962ff')], run: (b) => ({ v: calc.chop(b) }) },

  { id: 'vol', name: 'Volume', short: 'Vol', cat: 'Volume', pane: 'price', special: 'vol', lines: [] },
  { id: 'vwap', name: 'VWAP (intraday, from these candles)', short: 'VWAP', cat: 'Volume', pane: 'price', special: 'vwap', lines: [P('v', 'VWAP', '#ff9800')] },
  { id: 'obv', name: 'On Balance Volume', short: 'OBV', cat: 'Volume', pane: 'own', lines: [P('v', 'OBV', '#2962ff')], run: (b) => ({ v: calc.obv(b) }) },
  { id: 'ad', name: 'Accumulation / Distribution', short: 'A/D', cat: 'Volume', pane: 'own', lines: [P('v', 'A/D', '#999915')], run: (b) => ({ v: calc.ad(b) }) },
  { id: 'cmf', name: 'Chaikin Money Flow (20)', short: 'CMF', cat: 'Volume', pane: 'own', levels: [0], lines: [P('v', 'CMF', '#43a047')], run: (b) => ({ v: calc.cmf(b) }) },
  { id: 'mfi', name: 'Money Flow Index (14)', short: 'MFI', cat: 'Volume', pane: 'own', levels: [80, 20], lines: [P('v', 'MFI', '#7e57c2')], run: (b) => ({ v: calc.mfi(b) }) },
  { id: 'fi', name: 'Force Index (13)', short: 'EFI', cat: 'Volume', pane: 'own', levels: [0], lines: [P('v', 'EFI', '#f44336')], run: (b) => ({ v: calc.fi(b) }) },
  { id: 'eom', name: 'Ease of Movement (14)', short: 'EOM', cat: 'Volume', pane: 'own', levels: [0], lines: [P('v', 'EOM', '#43a047')], run: (b) => ({ v: calc.eom(b) }) },
  { id: 'vo', name: 'Volume Oscillator (5, 10)', short: 'VO', cat: 'Volume', pane: 'own', levels: [0], lines: [P('v', 'VO %', '#2962ff')], run: (b) => ({ v: calc.vo(b) }) },
  { id: 'pvt', name: 'Price Volume Trend', short: 'PVT', cat: 'Volume', pane: 'own', lines: [P('v', 'PVT', '#2962ff')], run: (b) => ({ v: calc.pvt(b) }) },
  { id: 'rvol', name: 'Relative Volume (vs previous 20 bars)', short: 'RVOL', cat: 'Volume', pane: 'own', levels: [1], hist: 'v', lines: [], run: (b) => ({ v: calc.rvol(b) }) },

  { id: 'swings', name: 'Swing highs and lows (5 bars each side)', short: 'Swings', cat: 'Structure', pane: 'price', special: 'swings', lines: [] },
  { id: 'zigzag', name: 'Zig Zag (5%)', short: 'ZigZag 5%', cat: 'Structure', pane: 'price', special: 'zigzag', lines: [P('v', 'ZigZag', '#ff9800', { width: 2 })] },
  { id: 'prevday', name: 'Previous session high / low (intraday)', short: 'Prev H/L', cat: 'Structure', pane: 'price', intraday: true, lines: [P('h', 'PDH', '#089981', { dash: true }), P('l', 'PDL', '#f23645', { dash: true })], run: (b, ctx) => { const [h, l] = calc.prevday(b, ctx.dayOf); return { h, l } } },
]
export const BY_ID = Object.fromEntries(INDICATORS.map((x) => [x.id, x]))
export const CATS = ['Averages', 'Trend', 'Momentum', 'Volatility', 'Volume', 'Structure']
export const POPULAR = ['vwap', 'st', 'ema20', 'rsi', 'bb', 'atr', 'adx', 'obv', 'macd', 'sma50']
export { N }
