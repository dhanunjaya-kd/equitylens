import { useEffect, useRef, useState } from 'react'
import { api } from '../util'

export default function FnoScanner() {
  const [open, setOpen] = useState(false)
  const [status, setStatus] = useState('')
  const [checkStatus, setCheckStatus] = useState('')
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState(null)
  const [checks, setChecks] = useState(null)
  const timer = useRef(null)

  const poll = async (start = false) => {
    const clock = new Date(Date.now() + 330 * 60000).toISOString()
    const minute = clock.slice(11, 16)
    if (start && result?.rows?.length && result.day < clock.slice(0, 10) && minute >= '09:30' && minute < '09:45') {
      return confirmOpen()
    }
    clearTimeout(timer.current)
    if (start) { setStatus('Loading NSE universe…'); setChecks(null) }
    try {
      const d = await api(`/api/fno-scanner/${start ? 'scan' : 'status'}`, { method: start ? 'POST' : 'GET' })
      setRunning(!!d.running)
      setStatus(d.running ? `Scanning ${d.done} / ${d.total || '…'} stocks…` : d.error || '')
      if (d.result) setResult(d.result)
      if (d.running) timer.current = setTimeout(() => poll(false), 1800)
    } catch (e) {
      setRunning(false)
      setStatus(e.message)
    }
  }

  const confirmOpen = async () => {
    setRunning(true); setChecks(null); setCheckStatus('Checking opening candles and current contracts…')
    try {
      const d = await api('/api/fno-scanner/confirm', { method: 'POST' })
      setChecks(d); setCheckStatus('Opening checks completed.')
    } catch (e) {
      setCheckStatus(e.message)
    } finally {
      setRunning(false)
    }
  }

  useEffect(() => {
    if (open) poll(false)
    else clearTimeout(timer.current)
    return () => clearTimeout(timer.current)
  }, [open]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <details className="tile" style={{ margin: '14px 0', padding: 12 }} onToggle={(e) => setOpen(e.target.open)}>
      <summary style={{ cursor: 'pointer', fontWeight: 700, color: 'var(--accent)' }}>F&amp;O Scanner</summary>
      <p className="small">Evening watchlist for the next NSE session. Levels refer to the underlying stock.</p>
      <p className="small"><b>CE · breakout</b> &nbsp; Close above SMA50, within 2% of the 20-session high. Quality compounders rules: 5y ROCE (ROE for lenders) ≥20%, 5y profit growth ≥15%, debt/equity 0–0.5, CFO/profit ≥0.8. Missing metrics are excluded.</p>
      <p className="small"><b>PE · breakdown</b> &nbsp; Close below SMA50, within 2% of the 20-session low. Both sides require ≥1.25× the preceding 20 sessions’ average volume.</p>
      <p className="small muted">Next session, 09:30–09:45 IST: first 15-minute close beyond the level and opening VWAP (from 5-minute candles), within 1% of the level. Check NSE eligibility, dated ban list, scheduled board events, ATM expiry ≥7 days, spread ≤2% and one lot of ask depth.</p>
      <div className="row wrapflex" style={{ gap: 8 }}>
        <button type="button" className="btn primary small" disabled={running} onClick={() => poll(true)}>Scan now</button>
        <button type="button" className="btn small" disabled={running || !result?.rows?.length} onClick={confirmOpen}>Check opening triggers</button>
      </div>
      {status && <p className="small" role="status">{status}</p>}
      {checkStatus && <p className="small" role="status">{checkStatus}</p>}
      {result && (
        <div style={{ marginTop: 10 }}>
          <p className="small muted">Saved watchlist · {result.day} · {result.total} F&amp;O stocks · {result.skipped.length} incomplete</p>
          {['CE', 'PE'].map((side) => {
            const rows = result.rows.filter((r) => r.side === side)
            return (
              <div key={side} style={{ marginTop: 10 }}>
                <h4>{side} watchlist · {rows.length}</h4>
                {!rows.length ? <p className="small muted">No qualifying setups</p> : (
                  <div className="tbl-wrap"><table className="tbl"><thead><tr>
                    <th>Stock</th><th>Close ₹</th><th>{side === 'CE' ? 'Break above ₹' : 'Break below ₹'}</th><th>Volume ×</th><th>Opening check</th>
                  </tr></thead><tbody>
                    {rows.map((r) => (
                      <tr key={r.symbol}>
                        <td><b>{r.symbol}</b></td><td>{r.close}</td><td>{r.level}</td><td>{r.rvol}</td>
                        <td>{checks?.day === result.day && checks.checks[r.symbol] ? checks.checks[r.symbol] : 'Pending'}</td>
                      </tr>
                    ))}
                  </tbody></table></div>
                )}
              </div>
            )
          })}
        </div>
      )}
    </details>
  )
}
