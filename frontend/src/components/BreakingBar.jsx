import { useEffect, useState } from 'react'
import { api, go, me, watchlist } from '../util'

const KEY = 'eql_breaking_seen', RANG = 'eql_breaking_rang', SOUND = 'eql_breaking_sound'
const seen = () => { try { return JSON.parse(localStorage.getItem(KEY) || '[]') } catch { return [] } }
const rang = () => { try { return JSON.parse(localStorage.getItem(RANG) || '[]') } catch { return [] } }
export const soundOn = () => { try { return localStorage.getItem(SOUND) !== 'off' } catch { return true } }
export const setSound = (on) => { try { localStorage.setItem(SOUND, on ? 'on' : 'off') } catch { /* ignore */ } }

// A short two-tone alert made in the browser (no sound file). Browsers allow it once you have clicked anywhere in the app.
export function chime() {
  try {
    const A = window.AudioContext || window.webkitAudioContext
    if (!A) return
    const ctx = new A()
    ;[[880, 0], [660, 0.22], [880, 0.44]].forEach(([f, at]) => {
      const o = ctx.createOscillator(), g = ctx.createGain()
      o.type = 'sine'; o.frequency.value = f
      g.gain.setValueAtTime(0.0001, ctx.currentTime + at)
      g.gain.exponentialRampToValueAtTime(0.35, ctx.currentTime + at + 0.02)
      g.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + at + 0.2)
      o.connect(g).connect(ctx.destination); o.start(ctx.currentTime + at); o.stop(ctx.currentTime + at + 0.22)
    })
    setTimeout(() => ctx.close(), 1200)
  } catch { /* ignore */ }
}

// Sound + a desktop notification (if allowed) for each breaking item, once per item on this device.
function ring(items) {
  const done = rang(), fresh = items.filter((i) => !done.includes(i.id))
  if (!fresh.length) return
  try { localStorage.setItem(RANG, JSON.stringify([...done, ...fresh.map((i) => i.id)].slice(-200))) } catch { /* ignore */ }
  if (!soundOn()) return
  chime()
  try {
    if ('Notification' in window && Notification.permission === 'granted' && document.hidden) {
      fresh.slice(0, 2).forEach((i) => new Notification('BREAKING · EquityLens', { body: i.title, tag: i.id }))
    }
  } catch { /* ignore */ }
}

// Settings: one switch per device (sound is played by this browser, so it is saved on this device).
export function BreakingSoundCard() {
  const [on, setOn] = useState(soundOn())
  const [perm, setPerm] = useState(typeof Notification !== 'undefined' ? Notification.permission : 'unsupported')
  const flip = (v) => {
    setOn(v); setSound(v)
    if (v) {
      chime()
      if (typeof Notification !== 'undefined' && Notification.permission === 'default') Notification.requestPermission().then(setPerm).catch(() => {})
    }
  }
  return (
    <div className="card">
      <div className="row between"><h3 style={{ margin: 0 }}>🔔 Breaking news sound</h3>
        <label className="row small" style={{ gap: 6, cursor: 'pointer' }}><input type="checkbox" checked={on} onChange={(e) => flip(e.target.checked)} /> {on ? 'On' : 'Off'}</label>
      </div>
      <div className="small muted" style={{ marginTop: 4 }}>
        A short alert sound on this device when a breaking item appears (checked every minute while EquityLens is open), once per item.
        {perm === 'granted' ? ' Desktop notifications are allowed, so you also get one when this tab is in the background.'
          : perm === 'denied' ? ' Desktop notifications are blocked in this browser; allow them in the site settings to get one when the tab is in the background.'
            : perm === 'default' ? ' Switching on also asks to allow desktop notifications for when this tab is in the background.' : ''}
        {' '}For alerts on your phone when the app is closed, use Telegram alerts.
      </div>
      <button className="btn" style={{ marginTop: 8 }} onClick={chime}>▶ Test sound</button>
    </div>
  )
}

// A red bar on every page while something serious is happening: a market-wide event two publishers report,
// a central-bank announcement, or a main index moving 2%+ today. Dismissed items stay dismissed.
export default function BreakingBar({ market }) {
  const [items, setItems] = useState([]), [hid, setHid] = useState(seen())
  useEffect(() => {
    const load = () => !document.hidden && api(`/api/news/breaking?market=${market}`).then((d) => { setItems(d.items || []); ring(d.items || []) }).catch(() => {})
    load()
    const t = setInterval(load, 60 * 1000)
    return () => clearInterval(t)
  }, [market])
  useEffect(() => {   // keep the Telegram alerts' watchlist in step with this device's watchlists (owner only)
    if (me() && me().role !== 'owner') return
    api('/api/alerts', { method: 'POST', body: JSON.stringify({ watch: watchlist.all().map((i) => i.symbol) }), headers: { 'Content-Type': 'application/json' } }).catch(() => {})
  }, [])
  const it = items.find((i) => !hid.includes(i.id))
  if (!it) return null
  const close = (e) => { e.stopPropagation(); const h = [...hid, it.id].slice(-100); setHid(h); try { localStorage.setItem(KEY, JSON.stringify(h)) } catch { /* ignore */ } }
  const open = () => (it.url ? window.open(it.url, '_blank', 'noopener') : go('news'))
  const t = new Date(it.time).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })
  return (
    <div className="brk" onClick={open} role="button">
      <span className="brk-pill">BREAKING</span>
      <span className="brk-title">{it.title}</span>
      <span className="brk-meta"><span className="src-note">{(it.sources || []).map((s) => s.name).slice(0, 2).join(', ')} · </span>{t}{items.filter((i) => !hid.includes(i.id)).length > 1 ? ` · +${items.filter((i) => !hid.includes(i.id)).length - 1} more` : ''}</span>
      <button className="brk-x" onClick={close} aria-label="Dismiss">✕</button>
    </div>
  )
}
