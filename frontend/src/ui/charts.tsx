import { useId, useMemo, useState } from 'react'

/* Dependency-free SVG charts. Each chart has a text alternative for screen readers and tooltips on hover/focus. */

export type Point = { label: string; value: number; tip?: string }

const nice = (max: number) => {
  if (max <= 0) return 1
  const p = 10 ** Math.floor(Math.log10(max))
  const n = max / p
  return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10) * p
}
const compact = (n: number) => new Intl.NumberFormat(undefined, { notation: 'compact', maximumFractionDigits: 1 }).format(n)

export function Sparkline({ values, color = 'var(--brand)' }: { values: number[]; color?: string }) {
  if (values.length < 2 || values.every((v) => v === 0)) return null
  const max = Math.max(...values), min = Math.min(...values), span = max - min || 1
  const pts = values.map((v, i) => `${(i / (values.length - 1)) * 100},${34 - ((v - min) / span) * 28}`)
  const id = useId()
  return (
    <svg className="spark" viewBox="0 0 100 40" preserveAspectRatio="none" aria-hidden>
      <defs><linearGradient id={id} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor={color} stopOpacity=".28" /><stop offset="1" stopColor={color} stopOpacity="0" /></linearGradient></defs>
      <polygon points={`0,40 ${pts.join(' ')} 100,40`} fill={`url(#${id})`} />
      <polyline points={pts.join(' ')} fill="none" stroke={color} strokeWidth="1.6" vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
    </svg>
  )
}

/** Area + line chart with optional second series (dashed). Hover or focus a column to read exact values. */
export function AreaChart({ points, second, label, format, secondLabel, firstLabel = 'Collected' }: { points: Point[]; second?: Point[]; label: string; format: (n: number) => string; secondLabel?: string; firstLabel?: string }) {
  const [hover, setHover] = useState<number | null>(null)
  const id = useId()
  const W = 720, H = 220, L = 46, R = 10, T = 12, B = 26
  const max = useMemo(() => nice(Math.max(1, ...points.map((p) => p.value), ...(second ?? []).map((p) => p.value))), [points, second])
  if (points.length < 1 || points.every((p) => p.value === 0) && (second ?? []).every((p) => p.value === 0)) return <div className="empty">No data in this period.</div>
  const x = (i: number) => L + (points.length === 1 ? (W - L - R) / 2 : (i / (points.length - 1)) * (W - L - R))
  const y = (v: number) => T + (1 - v / max) * (H - T - B)
  const line = (ps: Point[]) => ps.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(p.value).toFixed(1)}`).join(' ')
  const ticks = [0, 0.25, 0.5, 0.75, 1]
  const step = Math.max(1, Math.ceil(points.length / 7))
  const total = points.reduce((n, p) => n + p.value, 0)
  const h = hover !== null ? points[hover] : null
  return (
    <div style={{ position: 'relative' }}>
      <svg className="chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${label}. Total ${format(total)} over ${points.length} periods.`} onMouseLeave={() => setHover(null)}>
        <defs><linearGradient id={id} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="var(--brand)" stopOpacity=".3" /><stop offset="1" stopColor="var(--brand)" stopOpacity="0" /></linearGradient></defs>
        {ticks.map((t) => <g key={t}><line x1={L} x2={W - R} y1={y(max * t)} y2={y(max * t)} stroke="var(--border)" strokeDasharray={t === 0 ? undefined : '3 4'} /><text x={L - 8} y={y(max * t) + 4} fontSize="11" textAnchor="end" fill="var(--muted)">{compact(max * t)}</text></g>)}
        <path d={`${line(points)} L${x(points.length - 1)},${y(0)} L${x(0)},${y(0)} Z`} fill={`url(#${id})`} />
        {second && <path d={line(second)} fill="none" stroke="var(--gold)" strokeWidth="2" strokeDasharray="5 4" strokeLinejoin="round" />}
        <path d={line(points)} fill="none" stroke="var(--brand)" strokeWidth="2.6" strokeLinejoin="round" strokeLinecap="round" />
        {points.map((p, i) => i % step === 0 || i === points.length - 1 ? <text key={`l${i}`} x={x(i)} y={H - 6} fontSize="11" textAnchor={i === 0 ? 'start' : i === points.length - 1 ? 'end' : 'middle'} fill="var(--muted)">{p.label}</text> : null)}
        {hover !== null && <g><line x1={x(hover)} x2={x(hover)} y1={T} y2={H - B} stroke="var(--gold)" strokeDasharray="3 3" /><circle cx={x(hover)} cy={y(points[hover].value)} r="5" fill="var(--surface)" stroke="var(--brand)" strokeWidth="2.5" /></g>}
        {points.map((p, i) => (
          <rect key={i} x={x(i) - (W - L - R) / points.length / 2} y={T} width={(W - L - R) / points.length} height={H - T - B} fill="transparent" tabIndex={0} role="img" aria-label={p.tip ?? `${p.label}: ${format(p.value)}`}
            onMouseEnter={() => setHover(i)} onFocus={() => setHover(i)} onBlur={() => setHover(null)} />
        ))}
      </svg>
      {h && hover !== null && (
        <div style={{ position: 'absolute', left: `${(x(hover) / W) * 100}%`, top: 0, transform: `translate(${hover > points.length / 2 ? '-105%' : '5%'}, 0)`, background: 'var(--ink)', color: '#f6efe4', padding: '8px 12px', borderRadius: 10, fontSize: '.82rem', pointerEvents: 'none', boxShadow: 'var(--shadow-lg)', whiteSpace: 'nowrap', zIndex: 2 }}>
          <b style={{ display: 'block', marginBottom: 2 }}>{h.label}</b>
          <span>{firstLabel}: {format(h.value)}</span>
          {second && <span style={{ display: 'block', color: 'var(--gold)' }}>{secondLabel}: {format(second[hover]?.value ?? 0)}</span>}
        </div>
      )}
    </div>
  )
}

/** Horizontal ranked bars (best sellers, branches...). */
export function BarList({ rows, format, empty = 'Nothing to show.' }: { rows: { label: string; value: number; sub?: string }[]; format: (n: number) => string; empty?: string }) {
  const max = Math.max(1, ...rows.map((r) => r.value))
  if (!rows.length) return <div className="empty">{empty}</div>
  return (
    <div role="list">
      {rows.map((r) => (
        <div className="bar-row" role="listitem" key={r.label}>
          <span title={r.label} style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.label}{r.sub && <small className="muted" style={{ display: 'block' }}>{r.sub}</small>}</span>
          <div className="track" aria-hidden><div className="fill" style={{ width: `${(r.value / max) * 100}%` }} /></div>
          <b className="num">{format(r.value)}</b>
        </div>
      ))}
    </div>
  )
}

/** Donut with a centre label and a legend. */
export function Donut({ slices, centre, sub }: { slices: { label: string; value: number; color: string }[]; centre: string; sub: string }) {
  const total = slices.reduce((n, s) => n + s.value, 0)
  if (!total) return <div className="empty">No orders in this period.</div>
  const r = 52, c = 2 * Math.PI * r
  let acc = 0
  return (
    <div style={{ display: 'flex', gap: 22, alignItems: 'center', flexWrap: 'wrap' }}>
      <svg viewBox="0 0 140 140" width="150" height="150" role="img" aria-label={slices.map((s) => `${s.label} ${s.value}`).join(', ')}>
        <circle cx="70" cy="70" r={r} fill="none" stroke="var(--bg-soft)" strokeWidth="18" />
        {slices.filter((s) => s.value > 0).map((s) => {
          const len = (s.value / total) * c
          const el = <circle key={s.label} cx="70" cy="70" r={r} fill="none" stroke={s.color} strokeWidth="18" strokeDasharray={`${Math.max(len - 2, 0.5)} ${c - len + 2}`} strokeDashoffset={-acc} transform="rotate(-90 70 70)" />
          acc += len
          return el
        })}
        <text x="70" y="68" textAnchor="middle" fontSize="22" fontFamily="var(--font-display)" fill="var(--text)" fontWeight="600">{centre}</text>
        <text x="70" y="86" textAnchor="middle" fontSize="10" fill="var(--muted)">{sub}</text>
      </svg>
      <div className="legend" style={{ flexDirection: 'column', gap: 8 }}>
        {slices.map((s) => <span key={s.label}><i style={{ background: s.color }} />{s.label} <b style={{ color: 'var(--text)' }}>{s.value}</b></span>)}
      </div>
    </div>
  )
}
