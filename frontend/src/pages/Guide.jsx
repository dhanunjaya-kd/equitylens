import { useState } from 'react'
import { getMarket, go, recent } from '../util'

// 📘 Beginner's guide: how to read a company with EquityLens, assuming zero knowledge.
const STEPS = [
  {
    emoji: '🔎', title: 'Find the company', tab: null,
    plain: 'Type the company name or its symbol in the search bar and pick it from the list. Everything below is about that one company.',
    look: ['The name, the exchange symbol and the sector chips tell you what kind of business it is (bank, IT, pharma…).', 'The F&O badge means the stock also trades in futures & options.'],
    good: 'You know in one line what the company sells and to whom.',
    bad: 'If you cannot explain the business to a friend in one sentence, read the Overview key points before going further.',
  },
  {
    emoji: '🟢', title: 'Read the verdict first', tab: 'overview',
    plain: 'At the top of the Overview you see one verdict, a score out of 100 and a short reason. Think of it as the summary of a long report.',
    look: ['Business score = how good the company is. Valuation score = how attractive the price is.', 'The colour: green = good & fair price, blue = good but expensive, yellow = average, orange/red = problems.'],
    good: 'Business score above 70 with a green or blue verdict.',
    bad: '"Serious red flags" or "Weak" — read the flags before anything else.',
  },
  {
    emoji: '📈', title: 'Is the business growing?', tab: 'financials',
    plain: 'Sales (revenue) is the money customers pay the company. Net profit is what is left after every cost and tax. Both should go up over many years, not just one.',
    look: ['The 10-year story timeline: big jumps, bad years and why.', 'Sales growth and profit growth for 3, 5 and 10 years in the scorecard.'],
    good: 'Sales and profit growing 10%+ a year for 5–10 years, without big gaps.',
    bad: 'Profit growing much faster than sales for years (can\'t last), or profit going up and down every year.',
  },
  {
    emoji: '🏭', title: 'Is it a high-quality business?', tab: 'quality',
    plain: 'ROCE tells you how much profit the company makes on every ₹100 (or $100) it has invested in the business. Higher means a better business.',
    look: ['ROCE (return on capital) and operating margin, and whether they are steady.', 'ROE for banks and finance companies.'],
    good: 'ROCE above 15–20% for many years. Steady margins.',
    bad: 'ROCE below 10%: the business earns less than a fixed deposit would on the same money.',
  },
  {
    emoji: '🛡️', title: 'Is it financially safe?', tab: 'quality',
    plain: 'Debt is borrowed money. Some is fine, too much is dangerous when business slows. Profit should also turn into real cash in the bank.',
    look: ['Debt / equity and interest coverage (how many times profit covers the interest).', 'Cash conversion: operating cash ÷ profit.'],
    good: 'Debt / equity below 0.5, interest covered 5×+, cash conversion near or above 0.8.',
    bad: 'Debt rising every year, or profit that never shows up as cash.',
  },
  {
    emoji: '🕵️', title: 'Check for red flags', tab: 'forensics',
    plain: 'Forensic checks look for signs of trouble in the accounts, like a doctor\'s check-up. You don\'t need the maths — read the colours and one-line meanings.',
    look: ['Piotroski F (0–9): is the business getting healthier? Altman Z: risk of financial stress. Beneish M: could profits be dressed up?', 'The red flags list on the Overview: pledging, promoter selling, dilution, low cash.'],
    good: 'Piotroski 6+, Altman Z "Safe", Beneish "Unlikely", no high red flags.',
    bad: 'Several high flags together, or a 🚨 surveillance banner from the exchange.',
  },
  {
    emoji: '💰', title: 'Is the price fair?', tab: 'valuation',
    plain: 'A great company can still be a bad buy if you pay too much. P/E = price ÷ yearly profit per share: how many years of today\'s profit you are paying for.',
    look: ['P/E compared with the company\'s own 10-year average and with its peers.', 'The fair-value range from 5 methods and the "margin of safety".'],
    good: 'Price inside or below the fair-value range; P/E below its own long-term average.',
    bad: 'P/E far above its history and peers — the price already assumes everything goes right.',
  },
  {
    emoji: '🔮', title: 'What has to go right for 3, 5, 10 years?', tab: 'future',
    plain: 'EquityLens projects the company\'s profit and price in a bad (bear), normal (base) and good (bull) case. Reverse DCF shows what growth today\'s price already expects.',
    look: ['The base-case yearly return for 3, 5 and 10 years.', 'The assumptions: growth rate and the P/E it ends at.'],
    good: 'Base case of 12%+ a year, and the growth needed is lower than what the company has already delivered.',
    bad: 'Even the bull case gives a low return, or the price needs growth the company has never achieved.',
  },
  {
    emoji: '👥', title: 'Who owns it and who is buying?', tab: 'money',
    plain: 'Promoters are the founders / owners. When they and big investors buy more, it is a vote of confidence. Delivery % shows people actually buying shares to keep, not just trading.',
    look: ['Ownership tab: promoter, FII (foreign) and DII (Indian funds) holding over time.', 'Smart money tab: insider trades, bulk/block deals, 10-day delivery bars.'],
    good: 'Promoters steady or buying, funds increasing, high delivery on up-days.',
    bad: 'Promoters selling or pledging shares, funds exiting.',
  },
  {
    emoji: '📊', title: 'Check the chart for timing', tab: 'chart',
    plain: 'Fundamentals tell you WHAT to buy, the chart helps with WHEN. The 200-day average is the long-term trend line.',
    look: ['Is the price above the 200 EMA (uptrend)? RSI above 70 = overheated, below 30 = beaten down.', 'Chart outlook: the likely range and the support / resistance levels.'],
    good: 'Price above the 200 EMA, buying near support rather than after a sharp jump.',
    bad: 'Price far below a falling 200 EMA — the market is still selling.',
  },
  {
    emoji: '✨', title: 'Ask the AI to explain', tab: 'ai',
    plain: 'If anything is confusing, the AI tab can write a full research note, answer your questions in plain language, or run a bull-vs-bear debate.',
    look: ['"Ask about this stock": e.g. "Explain this company to a beginner", "Is the debt a worry?"', 'The report reader summarises annual reports and concall transcripts.'],
    good: 'Use it to understand, then confirm the important numbers yourself.',
    bad: 'Never buy only because an AI said so.',
  },
]

const CHECKLIST = [
  'Can I explain what this company sells, in one sentence?',
  'Have sales and profit grown for 5+ years?',
  'Is ROCE above 15% and steady?',
  'Is debt low and does profit turn into cash?',
  'Are there no serious red flags or surveillance warnings?',
  'Are promoters holding or buying (not selling or pledging)?',
  'Is the price inside the fair-value range, not far above it?',
  'Does the base case give at least the return I want?',
  'Is the stock above its 200-day average, or am I fine waiting?',
  'Have I read the latest quarter and what management said?',
]

const GLOSSARY = [
  ['Share / stock', 'A small piece of ownership in a company.'],
  ['Market cap', 'Price × number of shares = what the whole company is worth on the market.'],
  ['Revenue / Sales', 'Money received from customers.'],
  ['Net profit (PAT)', 'What is left after all costs, interest and tax.'],
  ['EPS', 'Profit per share = net profit ÷ number of shares.'],
  ['P/E', 'Price ÷ EPS. How many years of current profit you pay for.'],
  ['P/B', 'Price ÷ book value (net assets per share). Used for banks.'],
  ['ROCE', 'Profit before interest & tax ÷ capital employed. Quality of the business.'],
  ['ROE', 'Profit ÷ shareholders\' money. Used for banks and lenders.'],
  ['Operating margin', 'Operating profit as a % of sales.'],
  ['Debt / equity', 'Borrowed money ÷ owners\' money. Lower is safer.'],
  ['Free cash flow', 'Cash left after running the business and investing in it.'],
  ['CAGR', 'Average yearly growth rate over several years.'],
  ['Dividend yield', 'Yearly dividend ÷ price.'],
  ['Promoter', 'Founder / controlling owner of an Indian company.'],
  ['FII / DII', 'Foreign / Indian institutional investors (funds, insurers).'],
  ['Pledge', 'Promoter shares given as security for a loan — risky if the price falls.'],
  ['Delivery %', 'Share of traded shares actually taken into demat accounts (not intraday).'],
  ['200 EMA', 'Average price of roughly the last 200 trading days: the long-term trend.'],
  ['RSI', '0–100 momentum gauge. Above 70 overheated, below 30 oversold.'],
  ['DCF', 'Valuing a company from the cash it will make in future, in today\'s money.'],
  ['Margin of safety', 'How far the price is below the estimated fair value.'],
  ['F&O', 'Futures & options: contracts on a stock or index, traded in lots.'],
  ['VIX', 'Fear gauge: how big the market expects price swings to be.'],
]

const DAILY = [
  ['📊', 'Index card', 'Glance at NIFTY / BANK NIFTY / SENSEX and the VIX mood.', ''],
  ['🔥', 'Market Movers', 'See what moved, the market mood and which sectors lead. Check 💎 Quality on sale.', 'movers'],
  ['📅', 'Calendar', 'Results of your watchlist this week and big economic events (RBI, CPI, Fed).', 'calendar'],
  ['🧭', 'Smart Money', 'Delivery buying, promoter trades, bulk deals and surveillance flags.', 'money'],
  ['🧮', 'Screener', 'Run the 3 signature scans to find new ideas, then research them step by step.', 'screener'],
]

export default function Guide() {
  const mk = getMarket()
  const ex = (recent.all().find((r) => (mk === 'US') === r.symbol.startsWith('US:')) || {}).symbol || (mk === 'US' ? 'US:AAPL' : 'RELIANCE')
  const [open, setOpen] = useState(0)
  const [done, setDone] = useState({})
  const score = Object.values(done).filter(Boolean).length
  return (
    <div className="guide">
      <div className="card guide-hero">
        <div className="guide-kicker">📘 Beginner's guide</div>
        <h1>How to read a company in 10 minutes</h1>
        <p className="muted">No finance background needed. Follow these steps on any stock — each one opens the right tab of the app. Example used: <b>{ex.replace('US:', '')}</b> (your last viewed stock).</p>
        <video className="guide-video" src="/guide.mp4" controls preload="metadata" playsInline poster="/guide_poster.jpg" />
        <div className="small muted">▶️ About 4-minute walkthrough of the whole app (no sound, with captions).</div>
      </div>

      <div className="guide-tips">
        <div className="card guide-tip" onClick={() => go('settings')}><b>📱 Use it on your phone</b><div className="small muted">Settings → Use on your phone → scan the QR code. Add to Home Screen to open it like an app.</div></div>
        <div className="card guide-tip" onClick={() => go('portfolio')}><b>💼 Check what you own</b><div className="small muted">Connect Zerodha, Upstox, Fyers, Angel One or Dhan (read-only), or upload your holdings file.</div></div>
      </div>

      <div className="guide-cols">
        <div>
          <h2 className="guide-h">The 11 steps</h2>
          {STEPS.map((s, i) => (
            <div key={s.title} className={`card guide-step ${open === i ? 'open' : ''}`}>
              <div className="guide-head" onClick={() => setOpen(open === i ? -1 : i)}>
                <span className="guide-num">{i + 1}</span>
                <b className="grow">{s.emoji} {s.title}</b>
                <span className="muted">{open === i ? '−' : '+'}</span>
              </div>
              {open === i && (
                <div className="guide-body">
                  <p>{s.plain}</p>
                  <div className="small muted" style={{ fontWeight: 700, marginBottom: 4 }}>WHAT TO LOOK AT</div>
                  <ul className="list">{s.look.map((l) => <li key={l}><span className="ic">👀</span>{l}</li>)}</ul>
                  <div className="guide-gb">
                    <div className="gb good"><b>✅ Good sign</b><div className="small">{s.good}</div></div>
                    <div className="gb bad"><b>🚩 Warning sign</b><div className="small">{s.bad}</div></div>
                  </div>
                  <div className="row between" style={{ marginTop: 10 }}>
                    {s.tab ? <button className="btn small primary" onClick={() => go(`stock/${ex}/${s.tab}`)}>Open this on {ex.replace('US:', '')} →</button> : <button className="btn small primary" onClick={() => go('')}>Go to search →</button>}
                    {i < STEPS.length - 1 && <button className="btn small" onClick={() => setOpen(i + 1)}>Next step ↓</button>}
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>

        <div>
          <h2 className="guide-h">✅ 10-question checklist</h2>
          <div className="card">
            <p className="small muted" style={{ marginTop: 0 }}>Tick what is true for the stock you are studying. 8+ ticks = worth deeper research; under 5 = probably skip.</p>
            {CHECKLIST.map((q, i) => (
              <label key={q} className="chk guide-chk"><input type="checkbox" checked={!!done[i]} onChange={(e) => setDone({ ...done, [i]: e.target.checked })} /> {q}</label>
            ))}
            <div className={`guide-score ${score >= 8 ? 't-good' : score >= 5 ? 't-warn' : 't-bad'}`}>{score} / 10 {score >= 8 ? '· worth deeper research' : score >= 5 ? '· mixed, dig into the weak points' : score ? '· probably skip' : ''}</div>
          </div>

          <h2 className="guide-h">⏱️ Your 5-minute daily routine</h2>
          <div className="card" style={{ padding: 0 }}>
            {DAILY.map(([e, t, d, r]) => (
              <div key={t} className="ins-row" onClick={() => go(r)}>
                <span style={{ fontSize: 22 }}>{e}</span>
                <div className="grow"><b>{t}</b><div className="small muted">{d}</div></div>
                <span className="muted">›</span>
              </div>
            ))}
          </div>

          <h2 className="guide-h">📖 Words you'll see</h2>
          <div className="card glossary">
            {GLOSSARY.map(([w, m]) => <div key={w} className="gl-row"><b>{w}</b><span className="small">{m}</span></div>)}
          </div>
          <p className="disclaimer">EquityLens is a research aid, not investment advice. Start small, diversify, and never invest money you may need soon.</p>
        </div>
      </div>
    </div>
  )
}
