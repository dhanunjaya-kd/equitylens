export async function api(path, opts = {}) {
  const r = await fetch(path, opts)
  let body = null
  try { body = await r.json() } catch { /* not json */ }
  if (r.status === 401 && body && body.login) window.dispatchEvent(new Event('eql-login'))
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

// --- saved lists: kept in this browser, and copied to your account when sign-in is on
// browser key -> account key
export const SYNC = { eql_watch: 'watchlist', eql_recent: 'recent', eql_screens: 'screens', eql_over2: 'chart_over', eql_panes: 'chart_panes', eql_notes: 'notes' }
let ME = null
const timers = {}
export const me = () => ME
export const setMe = (u) => { ME = u }
const push = (k) => {
  if (!ME || !SYNC[k]) return
  clearTimeout(timers[k])
  timers[k] = setTimeout(() => {
    const v = localStorage.getItem(k)
    api(`/api/me/data/${SYNC[k]}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: v ?? 'null' }).catch(() => {})
  }, 700)
}
export const saveLocal = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)) } catch { /* private mode */ } ; push(k) }
const read = (k) => { try { return JSON.parse(localStorage.getItem(k) || '[]') } catch { return [] } }
const write = saveLocal

// After sign-in: the account's copy replaces this browser's. Lists that exist only in this browser are kept aside
// (eql_device_backup) so My account can offer to add them; nothing is copied without asking.
export async function loadAccountData(user) {
  setMe(user)
  const data = await api('/api/me/data')
  const backup = {}
  for (const [k, key] of Object.entries(SYNC)) {
    const local = localStorage.getItem(k)
    if (data[key] !== undefined) localStorage.setItem(k, JSON.stringify(data[key]))
    else if (local && local !== '[]' && local !== '{}') { backup[k] = local; localStorage.removeItem(k) }
  }
  const old = JSON.parse(localStorage.getItem('eql_device_backup') || '{}')
  if (Object.keys(backup).length) localStorage.setItem('eql_device_backup', JSON.stringify({ ...old, ...backup }))
  window.dispatchEvent(new Event('eql-data'))
}
export const deviceBackup = () => { try { return JSON.parse(localStorage.getItem('eql_device_backup') || '{}') } catch { return {} } }
export async function importDeviceBackup() {
  const b = deviceBackup()
  for (const [k, raw] of Object.entries(b)) {
    let mine, theirs
    try { mine = JSON.parse(localStorage.getItem(k) || 'null'); theirs = JSON.parse(raw) } catch { continue }
    let merged = theirs
    if (k === 'eql_watch') merged = mergeWatch(mine, theirs)
    else if (Array.isArray(theirs) && Array.isArray(mine)) {          // lists: keep the account's items first, add the new ones
      const key = (x) => (x && (x.symbol || x.name)) || JSON.stringify(x)
      const seen = new Set(mine.map(key))
      merged = [...mine, ...theirs.filter((x) => !seen.has(key(x)))]
    } else if (mine && typeof mine === 'object' && !Array.isArray(mine)) merged = { ...theirs, ...mine }
    localStorage.setItem(k, JSON.stringify(merged))
    push(k)
  }
  localStorage.removeItem('eql_device_backup')
  window.dispatchEvent(new Event('eql-data'))
}
export const dropDeviceBackup = () => { localStorage.removeItem('eql_device_backup') }
export async function signOut() {
  try { await api('/api/auth/logout', { method: 'POST' }) } catch { /* already signed out */ }
  for (const k of Object.keys(SYNC)) localStorage.removeItem(k)         // the next person on this device sees none of it
  window.location.hash = '#/'
  window.location.reload()
}
// Watchlists: up to 10 named lists. Stored as { v: 2, active, lists: [{ id, name, items: [{ symbol, name, added, price }] }] }.
// The old single list (an array) becomes the first list, "My watchlist".
export const MAX_LISTS = 10
export const normWatch = (raw) => {
  if (Array.isArray(raw)) return { v: 2, active: 'w1', lists: [{ id: 'w1', name: 'My watchlist', items: raw.filter((x) => x && x.symbol) }] }
  if (raw && raw.v === 2 && Array.isArray(raw.lists) && raw.lists.length) return raw
  return { v: 2, active: 'w1', lists: [{ id: 'w1', name: 'My watchlist', items: [] }] }
}
const wget = () => { try { return normWatch(JSON.parse(localStorage.getItem('eql_watch') || '[]')) } catch { return normWatch([]) } }
const wset = (d) => { write('eql_watch', d); window.dispatchEvent(new Event('eql-watch')) }
const wedit = (fn) => { const d = wget(); fn(d); wset(d); return d }
const today = () => new Date().toISOString().slice(0, 10)
export const watchlist = {
  data: wget,
  lists: () => wget().lists,
  active: () => { const d = wget(); return d.lists.find((l) => l.id === d.active) || d.lists[0] },
  setActive: (id) => wedit((d) => { d.active = id }),
  // every stock in any list, once, in list order (used by Calendar, Smart Money, ...)
  all: () => { const seen = new Set(); const out = []; wget().lists.forEach((l) => l.items.forEach((i) => { if (!seen.has(i.symbol)) { seen.add(i.symbol); out.push(i) } })); return out },
  has: (s) => wget().lists.some((l) => l.items.some((i) => i.symbol === s)),
  listsWith: (s) => wget().lists.filter((l) => l.items.some((i) => i.symbol === s)).map((l) => l.id),
  create: (name) => {
    let id = null
    wedit((d) => {
      if (d.lists.length >= MAX_LISTS) return
      id = `w${Date.now().toString(36)}`
      d.lists.push({ id, name: String(name || 'New list').trim().slice(0, 40) || 'New list', items: [] })
      d.active = id
    })
    return id
  },
  rename: (id, name) => wedit((d) => { const l = d.lists.find((x) => x.id === id); if (l && String(name).trim()) l.name = String(name).trim().slice(0, 40) }),
  remove: (id) => wedit((d) => {
    d.lists = d.lists.filter((l) => l.id !== id)
    if (!d.lists.length) d.lists = normWatch([]).lists
    if (!d.lists.some((l) => l.id === d.active)) d.active = d.lists[0].id
  }),
  add: (id, s, name, price) => wedit((d) => {
    const l = d.lists.find((x) => x.id === id)
    if (l && !l.items.some((i) => i.symbol === s)) l.items.unshift({ symbol: s, name, added: today(), price: price ?? null })
  }),
  drop: (id, s) => wedit((d) => { const l = d.lists.find((x) => x.id === id); if (l) l.items = l.items.filter((i) => i.symbol !== s) }),
  moveTo: (from, to, s, copy = false) => wedit((d) => {
    const a = d.lists.find((x) => x.id === from), b = d.lists.find((x) => x.id === to)
    const it = a?.items.find((i) => i.symbol === s)
    if (!a || !b || !it || a === b) return
    if (!b.items.some((i) => i.symbol === s)) b.items.unshift({ ...it })
    if (!copy) a.items = a.items.filter((i) => i.symbol !== s)
  }),
  reorder: (id, from, to) => wedit((d) => {
    const l = d.lists.find((x) => x.id === id)
    if (!l || from === to || from < 0 || to < 0 || from >= l.items.length || to >= l.items.length) return
    const [x] = l.items.splice(from, 1)
    l.items.splice(to, 0, x)
  }),
  // old one-tap star: add to / remove from the active list
  toggle: (s, name, price) => { const a = watchlist.active(); if (a.items.some((i) => i.symbol === s)) watchlist.drop(a.id, s); else watchlist.add(a.id, s, name, price) },
}
// merge two watchlist stores (device + account): lists with the same name are joined, the rest added (max 10)
export const mergeWatch = (mine, theirs) => {
  const a = normWatch(mine), b = normWatch(theirs)
  b.lists.forEach((l) => {
    const same = a.lists.find((x) => x.name.toLowerCase() === l.name.toLowerCase())
    if (same) { const have = new Set(same.items.map((i) => i.symbol)); same.items.push(...l.items.filter((i) => !have.has(i.symbol))) }
    else if (a.lists.length < MAX_LISTS) a.lists.push({ ...l, id: a.lists.some((x) => x.id === l.id) ? `w${Date.now().toString(36)}${a.lists.length}` : l.id })
  })
  return a
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
  if (parts[0] === 'heatmap') return { page: 'heatmap', sector: parts[1] ? decodeURIComponent(parts[1]) : '' }
  if (parts[0] === 'premarket') return { page: 'premarket' }
  if (parts[0] === 'account') return { page: 'account' }
  if (parts[0] === 'guide') return { page: 'guide' }
  if (parts[0] === 'portfolio') return { page: 'portfolio' }
  if (parts[0] === 'money') return { page: 'money', tab: parts[1] }
  if (parts[0] === 'fiidii') return { page: 'fiidii', tab: parts[1] }
  if (parts[0] === 'news') return { page: 'news' }
  if (parts[0] === 'ipo') return { page: 'ipo', tab: parts[1] || 'open' }
  if (parts[0] === 'terminal') return { page: 'terminal' }
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
// NSE F&O exists only in the Indian view: in the US view the switch is hidden, so it must not filter anything there
export const getFno = () => getMarket() === 'IN' && readLS('eql_fno', '0') === '1'
export const setFnoLS = (v) => { try { localStorage.setItem('eql_fno', v ? '1' : '0') } catch { /* ignore */ } ; window.dispatchEvent(new Event('eql-fno')) }

// 🏛️ Stock list (India): NIFTY 50 · NIFTY 100 · NIFTY 500 · All NSE — shared by every list page
export const UNIVERSES = [['N50', 'NIFTY 50'], ['N100', 'NIFTY 100'], ['N500', 'NIFTY 500'], ['ALL', 'All NSE']]
export const getUniv = () => readLS('eql_univ', 'N500')
export const setUnivLS = (v) => { try { localStorage.setItem('eql_univ', v) } catch { /* ignore */ } ; window.dispatchEvent(new Event('eql-univ')) }
export const inUniv = (row, u) => u === 'ALL' || !row.idx || row.idx.includes(u)
export const univLabel = (u) => (UNIVERSES.find((x) => x[0] === u) || [u, u])[1]

// ---- data sources: hidden everywhere by default; Settings -> Data sources shows them (at the end of each page / section)
export const sourcesShown = () => readLS('eql_sources', 'off') === 'on'
export const applySources = (on = sourcesShown()) => { if (typeof document !== 'undefined') document.documentElement.dataset.src = on ? 'on' : 'off' }
export const setSourcesShown = (on) => { try { localStorage.setItem('eql_sources', on ? 'on' : 'off') } catch { /* ignore */ } applySources(on) }
applySources()
