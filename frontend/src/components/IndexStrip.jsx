import { useEffect, useState } from 'react'
import { api, num, ok, signed } from '../util'

function Spark({ data, up, w = 56, h = 22 }) {
  if (!data || data.length < 2) return null
  const min = Math.min(...data), max = Math.max(...data)
  const pts = data.map((v, i) => `${(i / (data.length - 1)) * w},${h - 2 - ((v - min) / (max - min || 1)) * (h - 4)}`).join(' ')
  return <svg width={w} height={h} className="ix-spark"><polyline points={pts} fill="none" stroke={up ? 'var(--good)' : 'var(--bad)'} strokeWidth="1.5" /></svg>
}

// 🇮🇳 NIFTY 50 · BANK NIFTY · SENSEX · INDIA VIX   |   🇺🇸 S&P 500 · NASDAQ · DOW · RUSSELL 2000 · VIX
export default function IndexStrip({ market }) {
  const [d, setD] = useState(null)
  const [tip, setTip] = useState(null)
  useEffect(() => {
    let alive = true
    const load = () => { if (document.visibilityState === 'visible') api(`/api/indices?market=${market}`).then((x) => alive && setD(x)).catch(() => {}) }
    load()
    const t = setInterval(load, 60000)
    return () => { alive = false; clearInterval(t) }
  }, [market])
  if (!d) return <div className="ix-strip ix-loading" />
  const live = d.items.some((i) => i.open)
  return (
    <div className="ix-wrap">
      <div className="ix-strip">
        {d.items.map((i) => {
          const vix = i.kind === 'vix'
          const up = (i.change_pct || 0) >= 0
          const good = vix ? !up : up                   // VIX rising = more fear
          return (
            <div key={i.symbol} className={`ix ${vix ? 'ix-vix' : ''}`} onClick={() => setTip(tip === i.symbol ? null : i.symbol)} title={i.mood?.read || ''}>
              <div className="ix-top"><span className="ix-name">{i.name}</span>{vix && i.mood && <span className={`ix-mood t-${i.mood.tone} bg-${i.mood.tone}`}>{i.mood.label}</span>}</div>
              {ok(i.price) ? (
                <div className="ix-row">
                  <div>
                    <div className="ix-val">{num(i.price, vix ? 2 : 0)}</div>
                    <div className={`ix-chg ${good ? 't-good' : 't-bad'}`}>{up ? '▲' : '▼'} {signed(i.change, vix ? 2 : 0)} ({signed(i.change_pct, 2, '%')})</div>
                  </div>
                  <Spark data={i.spark} up={up !== vix} />
                </div>
              ) : <div className="small muted">not available</div>}
              {tip === i.symbol && (
                <div className="ix-tip small">
                  {ok(i.low) && <div>Day range {num(i.low, vix ? 2 : 0)} – {num(i.high, vix ? 2 : 0)}</div>}
                  {ok(i.lo52) && <div>52-week {num(i.lo52, vix ? 2 : 0)} – {num(i.hi52, vix ? 2 : 0)}{ok(i.price) && ok(i.hi52) && !vix ? ` · ${signed((i.price / i.hi52 - 1) * 100, 1, '%')} from high` : ''}</div>}
                  {i.mood && <div className="muted">{i.mood.read}</div>}
                </div>
              )}
            </div>
          )
        })}
      </div>
      <div className="ix-foot small muted"><span className={`ix-dot ${live ? 'on' : ''}`} />{live ? 'Live · updates every minute' : 'Closed · last close'}<span className="src-note"> · Yahoo</span> · may be delayed · tap a card for ranges</div>
    </div>
  )
}
