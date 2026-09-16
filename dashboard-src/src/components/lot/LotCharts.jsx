// My Lot page panels: your own inventory, how old it is, and what is sitting.

import { useMemo } from 'react'
import {
  Bar, BarChart, CartesianGrid, Cell, LabelList, Pie, PieChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { ChartCard, EmptyChart, KPIRow, Metric } from '../ui'
import DataTable from '../DataTable'
import { ListingLink, VinLink } from '../market/MarketCharts'
import { useFilters } from '../../lib/filters'
import { avg, fmt$, fmt$Short, fmtNum } from '../../lib/format'
import {
  AGE_BUCKETS, AGE_COLORS, AXIS_TICK, CHART_COLORS, COLORS, GRID_STROKE,
  HOME_COLOR, TOOLTIP_STYLE, daysFill, daysTextColor,
} from '../../lib/theme'

const field = (e, name) => e?.payload?.[name] ?? e?.[name]

export function LotKPICards({ vehicles }) {
  const n = vehicles.length
  const aged = vehicles.filter(v => v.days_on_lot >= 60)
  const agedPct = n ? (aged.length / n) * 100 : 0
  const total = vehicles.reduce((s, v) => s + (v.price || 0), 0)
  const atRisk = aged.reduce((s, v) => s + (v.price || 0), 0)
  const newCount = vehicles.filter(v => v.condition === 'new').length
  const usedCount = vehicles.filter(v => v.condition === 'used').length
  return (
    <KPIRow>
      <Metric label="Units on lot" value={fmtNum(n)} subtitle={`${newCount} new / ${usedCount} used`} />
      <Metric label="Avg days on lot" value={fmtNum(avg(vehicles.map(v => v.days_on_lot)), 1)} subtitle="since first scraped" />
      <Metric label="Aged 60+ days" value={fmtNum(aged.length)} subtitle={`${agedPct.toFixed(0)}% of inventory`} tone={agedPct > 10 ? 'bad' : undefined} />
      <Metric label="Total asking" value={fmt$Short(total)} subtitle="sum of asking prices" />
      <Metric label="Capital at risk" value={fmt$Short(atRisk)} subtitle="asking price of 60+ day units" tone={atRisk > 0 ? 'bad' : undefined} />
    </KPIRow>
  )
}

export function InventoryByModel({ vehicles }) {
  const { toggleFilter, filters } = useFilters()
  const data = useMemo(() => {
    const models = {}
    for (const v of vehicles) {
      const m = v.model || 'Unknown'
      if (!models[m]) models[m] = { model: m, units: 0, days: [] }
      models[m].units++
      if (v.days_on_lot != null) models[m].days.push(v.days_on_lot)
    }
    return Object.values(models)
      .map(d => ({ ...d, avgDays: Math.round(avg(d.days) ?? 0) }))
      .sort((a, b) => b.units - a.units)
      .slice(0, 20)
  }, [vehicles])

  if (!data.length) return <ChartCard title="Inventory by model"><EmptyChart /></ChartCard>

  return (
    <ChartCard title="Inventory by model" subtitle="Units in stock, with average days on lot. Click a bar to filter.">
      <ResponsiveContainer width="100%" height={Math.max(300, data.length * 40 + 40)}>
        <BarChart data={data} layout="vertical" margin={{ left: 10, right: 80 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={GRID_STROKE} horizontal={false} />
          <XAxis type="number" tick={AXIS_TICK} axisLine={false} tickLine={false} allowDecimals={false} />
          <YAxis dataKey="model" type="category" tick={{ ...AXIS_TICK, fill: COLORS.ink }} axisLine={false} tickLine={false} width={130} />
          <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(val, _n, p) => [`${val} units (avg ${p.payload.avgDays} days)`, 'Inventory']} />
          <Bar dataKey="units" radius={[0, 4, 4, 0]} barSize={24} onClick={e => toggleFilter('model', field(e, 'model'))} style={{ cursor: 'pointer' }}>
            {data.map(d => (
              <Cell key={d.model} fill={HOME_COLOR} opacity={filters.model.length && !filters.model.includes(d.model) ? 0.3 : 0.9} />
            ))}
            <LabelList dataKey="units" position="right" content={(props) => {
              const { x = 0, y = 0, width = 0, height = 0, index } = props
              const d = data[index]
              if (!d) return null
              return (
                <text x={x + width + 6} y={y + height / 2} dominantBaseline="central" style={{ fontSize: 13, fontWeight: 600 }}>
                  <tspan fill={COLORS.ink}>{d.units}</tspan>
                  <tspan fill="#A1A1AA"> · </tspan>
                  <tspan fill={daysFill(d.avgDays)}>{d.avgDays}d</tspan>
                </text>
              )
            }} />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </ChartCard>
  )
}

export function TrimMix({ vehicles }) {
  const { toggleFilter, filters } = useFilters()
  const data = useMemo(() => {
    const buckets = {}
    for (const v of vehicles) {
      const t = v.trim || 'Unknown'
      if (!buckets[t]) buckets[t] = { count: 0, days: [] }
      buckets[t].count++
      if (v.days_on_lot != null) buckets[t].days.push(v.days_on_lot)
    }
    return Object.entries(buckets)
      .map(([trim, b]) => ({ trim, count: b.count, pct: ((b.count / (vehicles.length || 1)) * 100).toFixed(1), avgDays: Math.round(avg(b.days) ?? 0) }))
      .sort((a, b) => b.count - a.count)
  }, [vehicles])

  if (!data.length) return <ChartCard title="Trim mix"><EmptyChart /></ChartCard>

  const dim = d => (filters.trim.length && !filters.trim.includes(d.trim) ? 0.35 : 1)

  return (
    <ChartCard title="Trim mix" subtitle="Click a slice or row to filter.">
      <ResponsiveContainer width="100%" height={250}>
        <PieChart>
          <Pie data={data} dataKey="count" nameKey="trim" innerRadius={60} outerRadius={110} paddingAngle={2}
            onClick={e => toggleFilter('trim', field(e, 'trim'))} style={{ cursor: 'pointer' }} isAnimationActive={false}>
            {data.map((d, i) => <Cell key={d.trim} fill={CHART_COLORS[i % CHART_COLORS.length]} opacity={dim(d)} />)}
          </Pie>
          <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(val, name, p) => [`${val} units (${p.payload.pct}%), avg ${p.payload.avgDays} days`, name]} />
        </PieChart>
      </ResponsiveContainer>
      <div className="mt-3 max-h-[280px] overflow-y-auto">
        <table className="w-full text-base">
          <thead className="sticky top-0 bg-white">
            <tr className="text-sm text-zinc-500">
              <th className="pb-1.5 text-left font-semibold">Trim</th>
              <th className="pb-1.5 text-right font-semibold">Units</th>
              <th className="pb-1.5 text-right font-semibold">%</th>
              <th className="pb-1.5 text-right font-semibold">Avg days</th>
            </tr>
          </thead>
          <tbody>
            {data.map((d, i) => (
              <tr key={d.trim} onClick={() => toggleFilter('trim', d.trim)}
                className={`cursor-pointer border-t border-zinc-100 hover:bg-zinc-50 ${filters.trim.includes(d.trim) ? 'bg-zinc-50 font-semibold' : ''}`}>
                <td className="max-w-[260px] truncate py-1.5" title={d.trim}>
                  <span className="mr-2 inline-block h-3 w-3 rounded-sm align-middle" style={{ background: CHART_COLORS[i % CHART_COLORS.length], opacity: dim(d) }} />
                  {d.trim}
                </td>
                <td className="py-1.5 text-right tabular-nums">{d.count}</td>
                <td className="py-1.5 text-right tabular-nums text-zinc-500">{d.pct}%</td>
                <td className="py-1.5 text-right font-semibold tabular-nums" style={{ color: daysTextColor(d.avgDays) }}>{d.avgDays}d</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </ChartCard>
  )
}

export function AgeBucketChart({ vehicles }) {
  const { toggleFilter, filters } = useFilters()
  const data = AGE_BUCKETS.map(b => {
    const count = vehicles.filter(v => v.age_bucket === b).length
    return { label: `${b} days`, bucket: b, count, pct: vehicles.length ? Math.round((count / vehicles.length) * 100) : 0 }
  })
  return (
    <ChartCard title="Age distribution" subtitle="How long your units have been listed. Click a bar to filter.">
      <ResponsiveContainer width="100%" height={300}>
        <BarChart data={data} margin={{ top: 24 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={GRID_STROKE} vertical={false} />
          <XAxis dataKey="label" tick={{ ...AXIS_TICK, fill: COLORS.ink }} axisLine={false} tickLine={false} />
          <YAxis tick={AXIS_TICK} axisLine={false} tickLine={false} allowDecimals={false} />
          <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(val, _n, p) => [`${val} units (${p.payload.pct}%)`, 'Vehicles']} />
          <Bar dataKey="count" radius={[6, 6, 0, 0]} barSize={64} onClick={e => toggleFilter('ageBucket', field(e, 'label'))} style={{ cursor: 'pointer' }}>
            {data.map(d => (
              <Cell key={d.bucket} fill={AGE_COLORS[d.bucket]} opacity={filters.ageBucket.length && !filters.ageBucket.includes(d.label) ? 0.3 : 0.9} />
            ))}
            <LabelList dataKey="count" position="top" style={{ fontSize: 14, fontWeight: 700, fill: COLORS.ink }} />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </ChartCard>
  )
}

// Average days on lot grouped by any field (color, engine, trim, body style).
export function DaysByField({ vehicles, title, getValue, filterKey, width = 170, emptyHint }) {
  const { toggleFilter, filters } = useFilters()
  const data = useMemo(() => {
    const groups = {}
    for (const v of vehicles) {
      const k = getValue(v)
      if (!k || v.days_on_lot == null) continue
      if (!groups[k]) groups[k] = { name: k, units: 0, days: [] }
      groups[k].units++
      groups[k].days.push(v.days_on_lot)
    }
    return Object.values(groups)
      .map(d => ({ ...d, avgDays: Math.round(avg(d.days)) }))
      .sort((a, b) => b.avgDays - a.avgDays || b.units - a.units)
      .slice(0, 15)
  }, [vehicles, getValue])

  if (!data.length) return <ChartCard title={title}><EmptyChart message="No data for this breakdown." hint={emptyHint} /></ChartCard>

  const selected = filters[filterKey] || []
  return (
    <ChartCard title={title} subtitle="Slowest first (top 15). Click a bar to filter.">
      <ResponsiveContainer width="100%" height={Math.max(260, data.length * 34 + 50)}>
        <BarChart data={data} layout="vertical" margin={{ left: 10, right: 50, bottom: 16 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={GRID_STROKE} horizontal={false} />
          <XAxis type="number" tick={AXIS_TICK} axisLine={false} tickLine={false} allowDecimals={false}
            label={{ value: 'Avg days on lot', position: 'insideBottom', offset: -10, fontSize: 13, fill: '#71717A' }} />
          <YAxis dataKey="name" type="category" width={width} tick={{ ...AXIS_TICK, fill: COLORS.ink }} axisLine={false} tickLine={false}
            tickFormatter={v => (v.length > 24 ? v.slice(0, 22) + '...' : v)} />
          <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(val, _n, p) => [`${val} days (${p.payload.units} units)`, 'Avg days']} />
          <Bar dataKey="avgDays" radius={[0, 4, 4, 0]} barSize={18} onClick={e => toggleFilter(filterKey, field(e, 'name'))} style={{ cursor: 'pointer' }}>
            {data.map(d => <Cell key={d.name} fill={daysFill(d.avgDays)} opacity={selected.length && !selected.includes(d.name) ? 0.3 : 0.9} />)}
            <LabelList dataKey="avgDays" position="right" formatter={v => `${v}d`} style={{ fontSize: 12, fontWeight: 600, fill: '#52525B' }} />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </ChartCard>
  )
}

export function PriceDistribution({ vehicles }) {
  const data = useMemo(() => {
    const bands = {}
    for (const v of vehicles) {
      if (v.price == null) continue
      const lower = Math.floor(v.price / 10000) * 10000
      const label = `$${lower / 1000}-${(lower + 10000) / 1000}K`
      if (!bands[label]) bands[label] = { band: label, sort: lower, count: 0, days: [] }
      bands[label].count++
      if (v.days_on_lot != null) bands[label].days.push(v.days_on_lot)
    }
    return Object.values(bands).map(d => ({ ...d, avgDays: Math.round(avg(d.days) ?? 0) })).sort((a, b) => a.sort - b.sort)
  }, [vehicles])

  if (!data.length) return <ChartCard title="Price distribution"><EmptyChart message="No prices in the scraped data." /></ChartCard>

  return (
    <ChartCard title="Price distribution" subtitle="Units by asking-price band, in $10K steps.">
      <ResponsiveContainer width="100%" height={Math.max(260, data.length * 38 + 40)}>
        <BarChart data={data} layout="vertical" margin={{ left: 10, right: 40 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={GRID_STROKE} horizontal={false} />
          <XAxis type="number" tick={AXIS_TICK} axisLine={false} tickLine={false} allowDecimals={false} />
          <YAxis dataKey="band" type="category" tick={{ ...AXIS_TICK, fill: COLORS.ink }} axisLine={false} tickLine={false} width={100} />
          <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(val, _n, p) => [`${val} units (avg ${p.payload.avgDays} days on lot)`, 'Vehicles']} />
          <Bar dataKey="count" fill={HOME_COLOR} radius={[0, 4, 4, 0]} barSize={24} opacity={0.9}>
            <LabelList dataKey="count" position="right" style={{ fontSize: 13, fontWeight: 600, fill: '#52525B' }} />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </ChartCard>
  )
}

export function LotVehicleTable({ vehicles }) {
  const showMileage = vehicles.some(v => v.mileage != null && v.mileage > 500)
  const columns = [
    { key: 'stock_number', label: 'Stock #' },
    { key: 'vin', label: 'VIN', render: r => <VinLink v={r} /> },
    { key: 'year', label: 'Year', align: 'right' },
    { key: 'make', label: 'Make' },
    { key: 'model', label: 'Model', render: r => <span className="font-medium text-zinc-900">{r.model ?? '--'}</span> },
    { key: 'trim', label: 'Trim' },
    { key: 'exterior_color', label: 'Ext color' },
    { key: 'engine_short', label: 'Engine', render: r => <span className="inline-block max-w-[200px] truncate align-bottom" title={r.engine || ''}>{r.engine_short ?? '--'}</span> },
    { key: 'drivetrain', label: 'Drive' },
    ...(showMileage ? [{ key: 'mileage', label: 'Miles', align: 'right', render: r => fmtNum(r.mileage) }] : []),
    { key: 'msrp', label: 'MSRP', align: 'right', render: r => fmt$(r.msrp) },
    { key: 'selling_price', label: 'Selling price', align: 'right', render: r => <span className="font-semibold text-zinc-900">{fmt$(r.selling_price)}</span> },
    { key: 'days_on_lot', label: 'Days', align: 'right', render: r => <span className="font-bold" style={{ color: daysTextColor(r.days_on_lot) }}>{r.days_on_lot ?? '--'}</span> },
    { key: 'listing_url', label: 'Site', sortable: false, render: r => <ListingLink url={r.listing_url} />, csv: r => r.listing_url },
  ]
  return (
    <ChartCard title="Every unit on your lot" subtitle="Oldest first. Click a VIN for its price history.">
      <DataTable
        rows={vehicles}
        columns={columns}
        searchKeys={['stock_number', 'vin', 'make', 'model', 'trim', 'exterior_color', 'interior_color', 'drivetrain']}
        searchPlaceholder="Search stock #, VIN, model, color..."
        defaultSort="days_on_lot"
        defaultDir="desc"
        exportName="my-lot"
      />
    </ChartCard>
  )
}
