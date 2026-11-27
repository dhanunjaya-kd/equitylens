// Shared by the desktop bundle and Vite. React owns the host; the panel owns its contents.
class FnoScanner extends HTMLElement {
  connectedCallback() {
    this.innerHTML = `<details class="tile" style="margin:14px 0;padding:12px">
      <summary style="cursor:pointer;font-weight:700;color:var(--accent)">F&amp;O Scanner</summary>
      <p class="small">Evening watchlist for the next NSE session. Levels refer to the underlying stock.</p>
      <p class="small"><b>CE · breakout</b> &nbsp; Close above SMA50, within 2% of the 20-session high. Quality compounders rules: 5y ROCE (ROE for lenders) ≥20%, 5y profit growth ≥15%, debt/equity 0–0.5, CFO/profit ≥0.8. Missing metrics are excluded.</p>
      <p class="small"><b>PE · breakdown</b> &nbsp; Close below SMA50, within 2% of the 20-session low. Both sides require ≥1.25× the preceding 20 sessions’ average volume.</p>
      <p class="small muted">Next session, 09:30–09:45 IST: first 15-minute close beyond the level and opening VWAP (from 5-minute candles), within 1% of the level. Check NSE eligibility, dated ban list, scheduled board events, ATM expiry ≥7 days, spread ≤2% and one lot of ask depth. Paper signals; thresholds have not been backtested.</p>
      <div class="row wrapflex" style="gap:8px"><button type="button" class="btn primary" data-run>Scan now</button><button type="button" class="btn" data-check>Check opening triggers</button></div>
      <p class="small" data-status role="status"></p><p class="small" data-check-status role="status"></p><div data-results></div>
    </details>`
    this.token = 0
    this.querySelector('details').ontoggle = e => {
      if (e.target.open) this.scan(false)
      else { clearTimeout(this.timer); this.token++ }
    }
    this.querySelector('[data-run]').onclick = () => this.scan(true)
    this.querySelector('[data-check]').onclick = () => this.check()
  }
  disconnectedCallback() { clearTimeout(this.timer); this.token++ }
  async request(path, method) {
    const r = await fetch('/api/fno-scanner/' + path, {method, cache:'no-store'})
    const d = await r.json()
    if (!r.ok) throw Error(d.detail || 'Request failed')
    return d
  }
  async scan(start) {
    const clock = new Date(Date.now() + 330 * 60000).toISOString()
    const minute = clock.slice(11,16)
    if (start && this.result?.rows?.length && this.result.day < clock.slice(0,10)
        && minute >= '09:30' && minute < '09:45') return this.check()
    clearTimeout(this.timer)
    const token = ++this.token, button = this.querySelector('[data-run]')
    const status = this.querySelector('[data-status]')
    button.disabled = true
    if (start) {status.textContent = 'Loading NSE universe…'; this.checks = null}
    try {
      const d = await this.request(start ? 'scan' : 'status', start ? 'POST' : 'GET')
      if (!this.isConnected || token !== this.token) return
      status.textContent = d.running ? 'Scanning ' + d.done + ' / ' + (d.total || '…') + ' stocks…' : d.error || ''
      this.renderResult(d.result)
      button.disabled = d.running
      this.querySelector('[data-check]').disabled = d.running || !d.result?.rows?.length
      if (d.running) this.timer = setTimeout(() => this.scan(false), 1800)
    } catch (e) { if (token === this.token) {button.disabled = false; status.textContent = e.message} }
  }
  async check() {
    const button = this.querySelector('[data-check]'), status = this.querySelector('[data-check-status]')
    button.disabled = true
    this.checks = null
    this.renderResult(this.result)
    status.textContent = 'Checking opening candles and current contracts…'
    try {
      this.checks = await this.request('confirm', 'POST')
      this.renderResult(this.result)
      status.textContent = 'Opening checks completed.'
    } catch (e) {status.textContent = e.message}
    finally {button.disabled = false}
  }
  renderResult(result) {
    this.result = result
    const root = this.querySelector('[data-results]')
    root.replaceChildren()
    const add = (parent, tag, text) => {
      const el = document.createElement(tag); el.textContent = text; parent.append(el); return el
    }
    if (!result) return
    add(root,'p','Saved watchlist · '+result.day+' · '+result.total+' F&O stocks · '+result.skipped.length+' incomplete')
    if (result.skipped.length) {
      const detail = add(root,'details','')
      add(detail,'summary','Stocks with incomplete data')
      add(detail,'p',result.skipped.join(', '))
    }
    for (const side of ['CE','PE']) {
      const rows = result.rows.filter(r => r.side === side)
      add(root,'h4',side+' watchlist · '+rows.length)
      if (!rows.length) {add(root,'p','No qualifying setups'); continue}
      const wrap = add(root,'div',''); wrap.style.overflowX = 'auto'
      const table = add(wrap,'table',''), header = table.createTHead().insertRow()
      for (const h of ['Stock','Close ₹',side === 'CE' ? 'Break above ₹' : 'Break below ₹','Volume ×','Opening check']) add(header,'th',h)
      const body = table.createTBody()
      for (const r of rows) {
        const tr = body.insertRow()
        for (const value of [r.symbol,r.close,r.level,r.rvol,this.checks?.day === result.day && this.checks.checks[r.symbol] || 'Pending']) add(tr,'td',value)
      }
    }
  }
}
customElements.define('fno-scanner', FnoScanner)
