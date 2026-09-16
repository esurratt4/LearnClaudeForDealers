// Small building blocks shared by every page.

import { AlertTriangle, Info } from 'lucide-react'

export function ChartCard({ title, subtitle, children, className = '', action }) {
  return (
    <section className={`animate-fade-in rounded-2xl border border-zinc-200 bg-white p-5 shadow-[0_1px_2px_rgba(0,0,0,0.03)] ${className}`}>
      <div className="mb-4 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold uppercase tracking-[0.08em] text-zinc-500">{title}</h3>
          {subtitle && <p className="mt-1 text-sm text-zinc-500">{subtitle}</p>}
        </div>
        {action}
      </div>
      {children}
    </section>
  )
}

export function EmptyChart({ message = 'Nothing to show with these filters.', hint }) {
  return (
    <div className="flex h-48 flex-col items-center justify-center gap-1 rounded-xl border border-dashed border-zinc-200 bg-zinc-50/60 px-6 text-center">
      <p className="text-base text-zinc-500">{message}</p>
      {hint && <p className="text-sm text-zinc-400">{hint}</p>}
    </div>
  )
}

export function SectionLabel({ children }) {
  return (
    <div className="flex items-center gap-3 pt-4">
      <h2 className="shrink-0 text-sm font-semibold uppercase tracking-wider text-zinc-500">{children}</h2>
      <div className="h-px flex-1 bg-zinc-200" />
    </div>
  )
}

export function Banner({ tone = 'info', title, children }) {
  const warn = tone === 'warn'
  const Icon = warn ? AlertTriangle : Info
  return (
    <div
      className="animate-fade-in flex gap-3 rounded-xl border px-4 py-3"
      style={warn
        ? { background: '#FBF3E6', borderColor: '#EBD3A8', color: '#6B4412' }
        : { background: '#EEF5F4', borderColor: '#C9DFDC', color: '#1F4F4B' }}
    >
      <Icon className="mt-0.5 h-5 w-5 shrink-0" />
      <div className="text-base leading-snug">
        {title && <p className="font-semibold">{title}</p>}
        <div>{children}</div>
      </div>
    </div>
  )
}

export function KPIRow({ children }) {
  return (
    <div className="animate-fade-in grid grid-cols-2 gap-x-6 gap-y-5 rounded-2xl border border-zinc-200 bg-white px-6 py-5 md:grid-cols-3 xl:grid-cols-5">
      {children}
    </div>
  )
}

export function Metric({ label, value, subtitle, tone }) {
  const color = tone === 'bad' ? '#9B3D2B' : tone === 'good' ? '#2D5E38' : '#18181B'
  return (
    <div className="min-w-0">
      <p className="mb-1 text-xs font-semibold uppercase tracking-[0.07em] text-zinc-500">{label}</p>
      <p className="text-[32px] font-semibold leading-none tracking-tight tabular-nums" style={{ color }}>{value}</p>
      {subtitle && <p className="mt-1.5 text-sm text-zinc-500">{subtitle}</p>}
    </div>
  )
}

export function Select({ value, onChange, options }) {
  return (
    <select
      value={value}
      onChange={e => onChange(e.target.value)}
      className="w-full rounded-lg border border-zinc-200 bg-zinc-50 px-3 py-2 text-base text-zinc-700 focus:border-accent focus:bg-white focus:outline-none"
    >
      {options.map(o => <option key={o} value={o}>{o}</option>)}
    </select>
  )
}
