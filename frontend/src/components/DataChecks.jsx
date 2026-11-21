import JobRunner from './JobRunner'

// Owner-only: the long checks behind the evidence shown on stock pages. Each runs once in the background;
// the result then appears on every stock automatically.
export default function DataChecks() {
  return (
    <div className="card">
      <h3 style={{ marginTop: 0 }}>Data checks</h3>
      <p className="small muted" style={{ marginTop: 0 }}>
        These checks test EquityLens's rules on all NSE stocks, so the evidence shown on each stock page is measured, not assumed.
        Run each one once. The result then appears on every stock automatically; run it again only after a rules update or to add newer prices.
      </p>
      <div style={{ marginBottom: 12 }}>
        <b>Support and resistance zones</b>
        <div className="small muted" style={{ margin: '2px 0 6px' }}>Do zones really hold more often than random prices, and does a zone's own record predict its next test? Shown on every Price map.</div>
        <JobRunner name="levels" what="All NSE stocks" howLong="about 40–60 min" />
      </div>
      <div>
        <b>Entry decision and value record</b>
        <div className="small muted" style={{ margin: '2px 0 6px' }}>The track record behind the entry card and the value floor on the Price map.</div>
        <JobRunner name="entry" what="All NSE stocks" howLong="2–3 hours the first time (downloads P/E history), faster after" />
      </div>
    </div>
  )
}
