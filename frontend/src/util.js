export async function api(path, opts = {}) {
  const r = await fetch(path, opts)
  let body = null
  try { body = await r.json() } catch { /* not json */ }
  if (!r.ok) throw new Error((body && body.detail) || `Request failed (${r.status})`)
  return body
}

const inr = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 })
const inr2 = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 2 })

export const ok = (v) => v !== null && v !== undefined && !Number.isNaN(v)
export const num = (v, d = 0) => (ok(v) ? (d ? inr2.format(+(+v).toFixed(d)) : inr.format(v)) : '—')
export const pct = (v, d = 1) => (ok(v) ? `${(+v).toFixed(d)}%` : '—')
export const x = (v, d = 2) => (ok(v) ? `${(+v).toFixed(d)}x` : '—')
export const rs = (v, d = 0) => (ok(v) ? `₹${num(v, d)}` : '—')
export const cr = (v) => {
  if (!ok(v)) return '—'
  if (Math.abs(v) >= 100000) return `₹${(v / 100000).toFixed(2)} L Cr`
  return `₹${inr.format(v)} Cr`
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
  if (parts[0] === 'settings') return { page: 'settings' }
  if (parts[0] === 'compare') return { page: 'compare', symbols: (params.get('s') || '').split(',').filter(Boolean) }
  return { page: 'home' }
}
export const go = (path) => { window.location.hash = '#/' + path }
