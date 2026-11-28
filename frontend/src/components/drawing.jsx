import { num, signed } from '../util'

// Drawing tools for the chart. A point is { t: candle time, f: offset in candle widths (-0.5..0.5), v: price },
// so drawings stay on their candles when the chart scrolls, zooms or gets new candles.
const I = (d) => <path d={d} />
export const TOOL_GROUPS = [
  { key: 'lines', label: 'Lines', tools: [
    ['trend', 'Trend line', 2, I('M4 19L20 5')], ['ray', 'Ray', 2, I('M4 18L21 6')], ['xline', 'Extended line', 2, I('M2 20L22 4')],
    ['hline', 'Horizontal line', 1, I('M3 12h18')], ['hray', 'Horizontal ray', 1, I('M7 12h14M7 10v4')], ['vline', 'Vertical line', 1, I('M12 3v18')],
    ['channel', 'Parallel channel', 3, I('M3 15L15 5M9 19L21 9')],
  ] },
  { key: 'fib', label: 'Fibonacci and measure', tools: [
    ['fib', 'Fib retracement', 2, I('M3 5h18M3 9.5h18M3 14h18M3 19h18')], ['measure', 'Price and bar range', 2, I('M4 20L20 4M7 20l-3-3M20 7l-3-3')],
  ] },
  { key: 'shapes', label: 'Shapes', tools: [
    ['rect', 'Rectangle', 2, <rect x="4" y="6" width="16" height="12" rx="1" />], ['circle', 'Circle', 2, <circle cx="12" cy="12" r="8" />],
    ['ellipse', 'Ellipse', 2, <ellipse cx="12" cy="12" rx="9" ry="6" />], ['triangle', 'Triangle', 3, I('M12 4L21 19H3z')],
    ['path', 'Path (double-tap or Enter to finish)', 0, I('M3 17l5-9 5 6 4-8 4 4')],
  ] },
  { key: 'arrows', label: 'Arrows', tools: [
    ['arrow', 'Arrow', 2, I('M5 19L19 5M11 5h8v8')], ['arrow_up', 'Arrow mark up', 1, I('M12 4l6 7h-4v9h-4v-9H6z')], ['arrow_down', 'Arrow mark down', 1, I('M12 20l6-7h-4V4h-4v9H6z')],
  ] },
  { key: 'brushes', label: 'Brushes', tools: [
    ['brush', 'Brush (drag)', -1, I('M4 20c3 0 4-2 5-4s3-3 5-2M14 14l6-10')], ['highlighter', 'Highlighter (drag)', -1, I('M6 18l3-8 6 6-8 3zM9 10l6-6 5 5-6 6')],
  ] },
  { key: 'text', label: 'Text', tools: [['text', 'Text', 1, I('M5 6h14M12 6v13')]] },
]
export const TOOL = Object.fromEntries(TOOL_GROUPS.flatMap((g) => g.tools.map(([k, label, need, icon]) => [k, { k, label, need, icon, group: g.key }])))
const FIB = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1]
export const DRAW_C = '#2962ff'

export function makeXY(chart, series) {
  const ts = chart.timeScale()
  const sp = ts.options().barSpacing
  return {
    X: (p) => { const x = ts.timeToCoordinate(p.t); return x === null ? null : x + (p.f || 0) * sp },
    Y: (p) => series.priceToCoordinate(p.v),
  }
}

function arrowHead(ctx, xa, ya, xb, yb, size = 10) {
  const a = Math.atan2(yb - ya, xb - xa)
  ctx.beginPath(); ctx.moveTo(xb, yb)
  ctx.lineTo(xb - size * Math.cos(a - 0.45), yb - size * Math.sin(a - 0.45))
  ctx.lineTo(xb - size * Math.cos(a + 0.45), yb - size * Math.sin(a + 0.45)); ctx.closePath(); ctx.fill()
}
const extend = (xa, ya, xb, yb, w, back) => {
  const dx = xb - xa, dy = yb - ya
  if (dx === 0) return [xa, back ? 0 : ya, xb, dy > 0 ? 1e4 : -1e4]
  const k1 = (w - xa) / dx, k0 = (0 - xa) / dx
  return [back ? 0 : xa, back ? ya + dy * k0 : ya, w, ya + dy * k1]
}

export function drawShapes(ctx, w, h, chart, series, shapes, temp, dark, selected) {
  ctx.clearRect(0, 0, w, h)
  const { X, Y } = makeXY(chart, series)
  const txt = dark ? '#d1d4dc' : '#131722'
  const all = temp ? [...shapes, temp] : shapes
  ctx.font = '12px -apple-system, Segoe UI, sans-serif'
  all.forEach((s, idx) => {
    const pts = s.p.map((p) => [X(p), Y(p)])
    if (pts.some(([x, y]) => x === null || y === null)) return
    const col = s.c || DRAW_C
    ctx.strokeStyle = col; ctx.fillStyle = col; ctx.lineWidth = idx === selected ? 2.6 : 1.6
    ctx.setLineDash(s === temp ? [4, 3] : [])
    const [a, b, c] = pts
    const k = s.k
    if (k === 'hline') { ctx.beginPath(); ctx.moveTo(0, a[1]); ctx.lineTo(w, a[1]); ctx.stroke(); ctx.fillText(num(s.p[0].v, 2), 6, a[1] - 4) }
    else if (k === 'hray') { ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(w, a[1]); ctx.stroke(); ctx.fillText(num(s.p[0].v, 2), a[0] + 4, a[1] - 4) }
    else if (k === 'vline') { ctx.beginPath(); ctx.moveTo(a[0], 0); ctx.lineTo(a[0], h); ctx.stroke() }
    else if (k === 'arrow_up' || k === 'arrow_down') {
      const up = k === 'arrow_up', y0 = a[1] + (up ? 6 : -6)
      ctx.fillStyle = up ? '#089981' : '#f23645'
      ctx.beginPath(); ctx.moveTo(a[0], up ? y0 : y0); ctx.lineTo(a[0] - 8, y0 + (up ? 10 : -10)); ctx.lineTo(a[0] - 3, y0 + (up ? 10 : -10)); ctx.lineTo(a[0] - 3, y0 + (up ? 22 : -22))
      ctx.lineTo(a[0] + 3, y0 + (up ? 22 : -22)); ctx.lineTo(a[0] + 3, y0 + (up ? 10 : -10)); ctx.lineTo(a[0] + 8, y0 + (up ? 10 : -10)); ctx.closePath(); ctx.fill()
    } else if (k === 'text') {
      ctx.font = 'bold 13px -apple-system, Segoe UI, sans-serif'
      ctx.fillStyle = s.c || (dark ? '#e6edf3' : '#131722')
      ctx.fillText(s.text || '', a[0], a[1])
      if (idx === selected) { const tw = ctx.measureText(s.text || '').width; ctx.strokeRect(a[0] - 3, a[1] - 14, tw + 6, 19) }
    } else if (k === 'brush' || k === 'highlighter') {
      ctx.lineWidth = k === 'highlighter' ? 14 : (idx === selected ? 3 : 2); ctx.lineCap = 'round'; ctx.lineJoin = 'round'
      ctx.globalAlpha = k === 'highlighter' ? 0.28 : 1
      if (k === 'highlighter') ctx.strokeStyle = s.c || '#f5c400'
      ctx.beginPath(); pts.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y))); ctx.stroke()
      ctx.globalAlpha = 1; ctx.lineCap = 'butt'
    } else if (k === 'path' && pts.length >= 1) {
      ctx.beginPath(); pts.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y))); ctx.stroke()
      pts.forEach(([x, y]) => { ctx.beginPath(); ctx.arc(x, y, 2.5, 0, 7); ctx.fill() })
    } else if (b) {
      if (k === 'trend') { ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); ctx.stroke() }
      if (k === 'ray' || k === 'xline') { const [x0, y0, x1, y1] = extend(a[0], a[1], b[0], b[1], w, k === 'xline'); ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(x1, y1); ctx.stroke() }
      if (k === 'arrow') { ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); ctx.stroke(); arrowHead(ctx, a[0], a[1], b[0], b[1]) }
      if (k === 'rect') { ctx.globalAlpha = 0.12; ctx.fillRect(Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.abs(b[0] - a[0]), Math.abs(b[1] - a[1])); ctx.globalAlpha = 1; ctx.strokeRect(Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.abs(b[0] - a[0]), Math.abs(b[1] - a[1])) }
      if (k === 'circle') { const r = Math.hypot(b[0] - a[0], b[1] - a[1]); ctx.beginPath(); ctx.arc(a[0], a[1], r, 0, 7); ctx.globalAlpha = 0.1; ctx.fill(); ctx.globalAlpha = 1; ctx.stroke() }
      if (k === 'ellipse') { ctx.beginPath(); ctx.ellipse((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, Math.abs(b[0] - a[0]) / 2, Math.abs(b[1] - a[1]) / 2, 0, 0, 7); ctx.globalAlpha = 0.1; ctx.fill(); ctx.globalAlpha = 1; ctx.stroke() }
      if (k === 'triangle') { ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); if (c) ctx.lineTo(c[0], c[1]); ctx.closePath(); ctx.globalAlpha = 0.1; if (c) ctx.fill(); ctx.globalAlpha = 1; ctx.stroke() }
      if (k === 'channel') {
        ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); ctx.stroke()
        if (c) {
          const off = c[1] - (a[1] + ((b[1] - a[1]) * (c[0] - a[0])) / ((b[0] - a[0]) || 1))
          ctx.beginPath(); ctx.moveTo(a[0], a[1] + off); ctx.lineTo(b[0], b[1] + off); ctx.stroke()
          ctx.globalAlpha = 0.08; ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); ctx.lineTo(b[0], b[1] + off); ctx.lineTo(a[0], a[1] + off); ctx.closePath(); ctx.fill(); ctx.globalAlpha = 1
          ctx.setLineDash([4, 4]); ctx.beginPath(); ctx.moveTo(a[0], a[1] + off / 2); ctx.lineTo(b[0], b[1] + off / 2); ctx.stroke(); ctx.setLineDash([])
        }
      }
      if (k === 'fib') {
        FIB.forEach((f) => {
          const p = s.p[1].v + (s.p[0].v - s.p[1].v) * f, y = series.priceToCoordinate(p)
          if (y === null) return
          ctx.globalAlpha = f === 0.5 || f === 0.618 ? 1 : 0.7
          ctx.beginPath(); ctx.moveTo(Math.min(a[0], b[0]), y); ctx.lineTo(w, y); ctx.stroke()
          ctx.fillStyle = txt; ctx.fillText(`${f} (${num(p, 2)})`, Math.min(a[0], b[0]) + 4, y - 3); ctx.fillStyle = col
        })
        ctx.globalAlpha = 1
      }
      if (k === 'measure') {
        const up = s.p[1].v >= s.p[0].v
        ctx.globalAlpha = 0.16; ctx.fillStyle = up ? '#089981' : '#f23645'; ctx.fillRect(Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.abs(b[0] - a[0]), Math.abs(b[1] - a[1])); ctx.globalAlpha = 1
        const lab = `${signed(s.p[1].v - s.p[0].v, 2)} (${signed(((s.p[1].v - s.p[0].v) / s.p[0].v) * 100, 2, '%')})${s.bars ? ` · ${s.bars} bars` : ''}`
        ctx.fillStyle = up ? '#089981' : '#f23645'
        const tw = ctx.measureText(lab).width + 10
        ctx.fillRect((a[0] + b[0]) / 2 - tw / 2, Math.min(a[1], b[1]) - 20, tw, 17)
        ctx.fillStyle = '#fff'; ctx.fillText(lab, (a[0] + b[0]) / 2 - tw / 2 + 5, Math.min(a[1], b[1]) - 8)
      }
    } else if (a && s === temp) { ctx.beginPath(); ctx.arc(a[0], a[1], 3, 0, 7); ctx.fill() }
    if (idx === selected) { ctx.fillStyle = '#fff'; ctx.strokeStyle = col; ctx.lineWidth = 1.5; pts.slice(0, 3).forEach(([x, y]) => { ctx.beginPath(); ctx.arc(x, y, 4, 0, 7); ctx.fill(); ctx.stroke() }) }
  })
  ctx.setLineDash([])
}

const segDist = (px, py, ax, ay, bx, by) => {
  const dx = bx - ax, dy = by - ay, L = dx * dx + dy * dy
  const t = L ? Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / L)) : 0
  return Math.hypot(px - (ax + t * dx), py - (ay + t * dy))
}

// The drawing under a tap (index into shapes) or -1. Newest drawings win.
export function hitTest(x, y, w, chart, series, shapes, ctx) {
  const { X, Y } = makeXY(chart, series)
  for (let i = shapes.length - 1; i >= 0; i--) {
    const s = shapes[i]
    const pts = s.p.map((p) => [X(p), Y(p)])
    if (pts.some(([a, b]) => a === null || b === null)) continue
    const [a, b, c] = pts, k = s.k, near = 7
    let d = Infinity
    if (k === 'hline') d = Math.abs(y - a[1])
    else if (k === 'hray') d = x >= a[0] - near ? Math.abs(y - a[1]) : Infinity
    else if (k === 'vline') d = Math.abs(x - a[0])
    else if (k === 'arrow_up' || k === 'arrow_down') d = Math.hypot(x - a[0], y - (a[1] + (k === 'arrow_up' ? 16 : -16))) - 10
    else if (k === 'text') { ctx.font = 'bold 13px -apple-system, Segoe UI, sans-serif'; const tw = ctx.measureText(s.text || '').width; d = x >= a[0] - 4 && x <= a[0] + tw + 4 && y >= a[1] - 15 && y <= a[1] + 5 ? 0 : Infinity }
    else if (k === 'brush' || k === 'highlighter' || k === 'path') { for (let j = 1; j < pts.length; j++) d = Math.min(d, segDist(x, y, ...pts[j - 1], ...pts[j])); if (k === 'highlighter') d -= 6 }
    else if (b) {
      if (k === 'trend' || k === 'arrow') d = segDist(x, y, ...a, ...b)
      else if (k === 'ray' || k === 'xline') { const [x0, y0, x1, y1] = extend(a[0], a[1], b[0], b[1], w, k === 'xline'); d = segDist(x, y, x0, y0, x1, y1) }
      else if (k === 'rect' || k === 'measure' || k === 'ellipse') d = x >= Math.min(a[0], b[0]) - near && x <= Math.max(a[0], b[0]) + near && y >= Math.min(a[1], b[1]) - near && y <= Math.max(a[1], b[1]) + near ? 0 : Infinity
      else if (k === 'circle') d = Math.abs(Math.hypot(x - a[0], y - a[1]) - Math.hypot(b[0] - a[0], b[1] - a[1])) > Math.hypot(b[0] - a[0], b[1] - a[1]) ? Infinity : 0
      else if (k === 'triangle' && c) d = Math.min(segDist(x, y, ...a, ...b), segDist(x, y, ...b, ...c), segDist(x, y, ...c, ...a))
      else if (k === 'channel') { d = segDist(x, y, ...a, ...b); if (c) { const off = c[1] - (a[1] + ((b[1] - a[1]) * (c[0] - a[0])) / ((b[0] - a[0]) || 1)); d = Math.min(d, segDist(x, y, a[0], a[1] + off, b[0], b[1] + off)) } }
      else if (k === 'fib') d = x >= Math.min(a[0], b[0]) - near ? Math.min(...FIB.map((f) => { const yy = series.priceToCoordinate(s.p[1].v + (s.p[0].v - s.p[1].v) * f); return yy === null ? Infinity : Math.abs(y - yy) })) : Infinity
    }
    if (d <= near) return i
  }
  return -1
}
