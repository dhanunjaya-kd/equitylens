export async function api(path, opts = {}) {
  const r = await fetch(path, opts)
  let body = null
  try { body = await r.json() } catch { /* not json */ }
  if (!r.ok) throw new Error((body && body.detail) || `Request failed (${r.status})`)
  return body
}

// ---- market (🇮🇳 IND / 🇺🇸 US) and currency
const readLS = (k, d) => { try { return localStorage.getItem(k) || d } catch { return d } }
let MARKET = readLS('eql_market', 'IN')
let CUR = { code: 'INR', symbol: '₹', unit: 'Cr' }
export const getMarket = () => MARKET
export const setMarketLS = (m) => { MARKET = m; try { localStorage.setItem('eql_market', m) } catch { /* ignore */ } }
export const setCurrency = (c) => { CUR = c || { code: 'INR', symbol: '₹', unit: 'Cr' } }
export const cur = () => CUR.symbol
export const unitLabel = () => (CUR.code === 'USD' ? '$ M' : '₹ Cr')
export const unitWords = () => (CUR.code === 'USD' ? 'US$ million' : '₹ crore')
export const isUS = (sym) => String(sym || '').toUpperCase().startsWith('US:')
export const ticker = (sym) => String(sym || '').replace(/^US:/i, '')
export const flag = (sym) => (isUS(sym) ? '🇺🇸' : '🇮🇳')
export const marketCurrency = (m) => (m === 'US' ? { code: 'USD', symbol: '$', unit: 'M' } : { code: 'INR', symbol: '₹', unit: 'Cr' })

const nf = () => new Intl.NumberFormat(CUR.code === 'USD' ? 'en-US' : 'en-IN', { maximumFractionDigits: 0 })
const nf2 = () => new Intl.NumberFormat(CUR.code === 'USD' ? 'en-US' : 'en-IN', { maximumFractionDigits: 2 })

export const ok = (v) => v !== null && v !== undefined && !Number.isNaN(v)
export const num = (v, d = 0) => (ok(v) ? (d ? nf2().format(+(+v).toFixed(d)) : nf().format(v)) : '—')
export const pct = (v, d = 1) => (ok(v) ? `${(+v).toFixed(d)}%` : '—')
export const x = (v, d = 2) => (ok(v) ? `${(+v).toFixed(d)}x` : '—')
export const rs = (v, d = 0) => (ok(v) ? `${CUR.symbol}${num(v, d)}` : '—')
export const cr = (v) => {
  if (!ok(v)) return '—'
  if (CUR.code === 'USD') {
    if (Math.abs(v) >= 1e6) return `$${(v / 1e6).toFixed(2)} T`
    if (Math.abs(v) >= 1e3) return `$${(v / 1e3).toFixed(1)} B`
    return `$${nf().format(v)} M`
  }
  if (Math.abs(v) >= 100000) return `₹${(v / 100000).toFixed(2)} L Cr`
  return `₹${nf().format(v)} Cr`
}
export const signed = (v, d = 1, unit = '') => (ok(v) ? `${v > 0 ? '+' : ''}${(+v).toFixed(d)}${unit}` : '—')

export function scoreColor(s) {
  if (!ok(s)) return 'var(--neutral)'
  if (s >= 75) return 'var(--good)'
  if (s >= 60) return 'var(--ok)'
  if (s >= 45) return 'var(--warn)'
  return 'var(--bad)'
}

export function ago(ts) {
  if (!ts) return ''
  const s = Date.now() / 1000 - ts
  if (s < 90) return 'just now'
  if (s < 3600) return `${Math.round(s / 60)} min ago`
  if (s < 86400) return `${Math.round(s / 3600)} h ago`
  return `${Math.round(s / 86400)} d ago`
}

// --- local lists (stored on this device only)
const read = (k) => { try { return JSON.parse(localStorage.getItem(k) || '[]') } catch { return [] } }
const write = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)) } catch { /* private mode */ } }
export const watchlist = {
  all: () => read('eql_watch'),
  has: (s) => read('eql_watch').some((w) => w.symbol === s),
  toggle: (s, name) => {
    const w = read('eql_watch')
    write('eql_watch', w.some((i) => i.symbol === s) ? w.filter((i) => i.symbol !== s) : [{ symbol: s, name }, ...w])
  },
}
export const recent = {
  all: () => read('eql_recent'),
  add: (s, name) => write('eql_recent', [{ symbol: s, name }, ...read('eql_recent').filter((r) => r.symbol !== s)].slice(0, 8)),
}

// hash routing:  #/  #/stock/TCS  #/rankings  #/watch  #/compare?s=A,B
export function parseHash() {
  const h = decodeURIComponent(window.location.hash.replace(/^#\/?/, ''))
  const [path, query] = h.split('?')
  const parts = path.split('/').filter(Boolean)
  const params = new URLSearchParams(query || '')
  if (parts[0] === 'stock' && parts[1]) return { page: 'stock', symbol: parts[1].toUpperCase(), tab: parts[2] || 'overview' }
  if (parts[0] === 'rankings') return { page: 'rankings' }
  if (parts[0] === 'watch') return { page: 'watch' }
  if (parts[0] === 'screener') return { page: 'screener' }
  if (parts[0] === 'movers') return { page: 'movers' }
  if (parts[0] === 'guide') return { page: 'guide' }
  if (parts[0] === 'portfolio') return { page: 'portfolio' }
  if (parts[0] === 'money') return { page: 'money', tab: parts[1] }
  if (parts[0] === 'calendar') return { page: 'calendar', tab: parts[1] || 'results' }
  if (parts[0] === 'settings') return { page: 'settings' }
  if (parts[0] === 'compare') return { page: 'compare', symbols: (params.get('s') || '').split(',').filter(Boolean) }
  return { page: 'home' }
}
export const go = (path) => { window.location.hash = '#/' + path }

export const isDesktop = () => typeof window !== 'undefined' && window.matchMedia('(min-width: 1100px)').matches

// ---- theme (dark / light)
export const cssVar = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim() || '#888'
export const getTheme = () => readLS('eql_theme', (typeof window !== 'undefined' && window.matchMedia('(prefers-color-scheme: light)').matches) ? 'light' : 'dark')
export const applyTheme = (t) => {
  document.documentElement.dataset.theme = t
  try { localStorage.setItem('eql_theme', t) } catch { /* ignore */ }
  const m = document.querySelector('meta[name="theme-color"]')
  if (m) m.setAttribute('content', t === 'light' ? '#f4f6f9' : '#0b1016')
}
export const logoUrl = (sym, name = '') => `/api/logo/${encodeURIComponent(sym)}${name ? `?name=${encodeURIComponent(name)}` : ''}`

// 🎯 F&O-only switch (India): one setting shared by every list page
export const getFno = () => readLS('eql_fno', '0') === '1'
export const setFnoLS = (v) => { try { localStorage.setItem('eql_fno', v ? '1' : '0') } catch { /* ignore */ } ; window.dispatchEvent(new Event('eql-fno')) }

// 🏛️ Stock list (India): NIFTY 50 · NIFTY 100 · NIFTY 500 · All NSE — shared by every list page
export const UNIVERSES = [['N50', 'NIFTY 50'], ['N100', 'NIFTY 100'], ['N500', 'NIFTY 500'], ['ALL', 'All NSE']]
export const getUniv = () => readLS('eql_univ', 'N500')
export const setUnivLS = (v) => { try { localStorage.setItem('eql_univ', v) } catch { /* ignore */ } ; window.dispatchEvent(new Event('eql-univ')) }
export const inUniv = (row, u) => u === 'ALL' || !row.idx || row.idx.includes(u)
export const univLabel = (u) => (UNIVERSES.find((x) => x[0] === u) || [u, u])[1]
