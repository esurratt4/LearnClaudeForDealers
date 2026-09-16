// Market page panels: your store (teal) against the competition (brown).

import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  Bar, BarChart, CartesianGrid, Cell, LabelList, Legend, Pie, PieChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { ArrowDownRight, ArrowUpRight, ExternalLink } from 'lucide-react'
import { ChartCard, EmptyChart, Select } from '../ui'
import DataTable from '../DataTable'
import { useFilters } from '../../lib/filters'
import { avg, fmt$, fmtAgo, fmtNum } from '../../lib/format'
import {
  AXIS_TICK, CHART_COLORS, CHART_COLORS_DESAT, COLORS, COMPETITOR_COLOR, COMPETITOR_TEXT,
  GRID_STROKE, HOME_COLOR, TOOLTIP_STYLE, daysTextColor,
} from '../../lib/theme'

// Recharts hands click handlers either the row or a wrapper around it.
const field = (e, name) => e?.payload?.[name] ?? e?.[name]
const pct = (n, total) => (total ? ((n / total) * 100).toFixed(1) : '0.0')

// ---------------------------------------------------------------------------
//  KPI row: you vs them
// ---------------------------------------------------------------------------
function CompareMetric({ label, yours, theirs, format = fmtNum, lowerIsBetter = false, note, showDiff = true }) {
  const hasBoth = showDiff && yours != null && theirs != null && theirs !== 0
  const diff = hasBoth ? yours - theirs : 0
  const diffPct = hasBoth ? Math.round((diff / theirs) * 100) : 0
  const ahead = lowerIsBetter ? diff < 0 : diff > 0
  const Arrow = ahead ? ArrowUpRight : ArrowDownRight
  return (
    <div className="min-w-0">
      <p className="mb-1 text-xs font-semibold uppercase tracking-[0.07em] text-zinc-500">{label}</p>
      <div className="flex flex-wrap items-baseline gap-x-2">
        <p className="text-[32px] font-semibold leading-none tracking-tight tabular-nums" style={{ color: HOME_COLOR }}>{format(yours)}</p>
        <span className="text-lg text-zinc-300">/</span>
        <p className="text-xl font-semibold tabular-nums" style={{ color: COMPETITOR_TEXT }}>{format(theirs)}</p>
      </div>
      <div className="mt-1.5 flex flex-wrap items-center gap-2 text-sm">
        <span className="text-zinc-500">{note || 'You / Them'}</span>
        {hasBoth && diffPct !== 0 && (
          <span className={`flex items-center gap-0.5 font-semibold ${ahead ? 'text-emerald-700' : 'text-red-700'}`}>
            <Arrow className="h-4 w-4" />
            {Math.abs(diffPct)}% {lowerIsBetter ? (diff < 0 ? 'lower' : 'higher') : (diff > 0 ? 'more' : 'fewer')}
          </span>
        )}
      </div>
    </div>
  )
}

export function MarketKPICards({ ours, theirs, competitorCount }) {
  const distinct = (rows, key) => new Set(rows.map(v => v[key]).filter(Boolean)).size
  return (
    <div className="animate-fade-in grid grid-cols-2 gap-x-6 gap-y-5 rounded-2xl border border-zinc-200 bg-white px-6 py-5 md:grid-cols-3 xl:grid-cols-5">
      <CompareMetric label="Units on the ground" yours={ours.length} theirs={theirs.length} note={`You / ${competitorCount} competitor${competitorCount === 1 ? '' : 's'} combined`} showDiff={false} />
      <CompareMetric label="Avg asking price" yours={avg(ours.map(v => v.price))} theirs={avg(theirs.map(v => v.price))} format={fmt$} lowerIsBetter />
      <CompareMetric label="Models stocked" yours={distinct(ours, 'model')} theirs={distinct(theirs, 'model')} />
      <CompareMetric label="Unique trims" yours={distinct(ours, 'trim')} theirs={distinct(theirs, 'trim')} />
      <CompareMetric label="Avg days on lot" yours={avg(ours.map(v => v.days_on_lot))} theirs={avg(theirs.map(v => v.days_on_lot))} format={v => fmtNum(v, 1)} lowerIsBetter />
    </div>
  )
}

// ---------------------------------------------------------------------------
//  The stores we watch (v_inventory_by_dealer)
// ---------------------------------------------------------------------------
export function DealerScoreboard({ dealers }) {
  const { filters, toggleFilter } = useFilters()
  const rows = [...dealers].sort((a, b) => (b.is_own_store - a.is_own_store) || (b.active_units - a.active_units))
  return (
    <ChartCard title="The stores" subtitle="One line per store. Click a competitor to show only that store.">
      <div className="overflow-auto rounded-xl border border-zinc-200">
        <table className="w-full text-base">
          <thead className="bg-zinc-50 text-left">
            <tr className="text-xs font-semibold uppercase tracking-wider text-zinc-500">
              <th className="px-3 py-2.5">Store</th>
              <th className="px-3 py-2.5">Location</th>
              <th className="px-3 py-2.5 text-right">Units</th>
              <th className="px-3 py-2.5 text-right">Avg MSRP</th>
              <th className="px-3 py-2.5 text-right">Avg selling price</th>
              <th className="px-3 py-2.5 text-right">Avg days on lot</th>
              <th className="px-3 py-2.5 text-right">Last scraped</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(d => {
              const name = d.dealer_name || d.dealer_key
              const active = filters.dealer.includes(name)
              return (
                <tr
                  key={d.dealer_key}
                  onClick={() => !d.is_own_store && toggleFilter('dealer', name)}
                  className={`border-t border-zinc-100 ${d.is_own_store ? '' : 'cursor-pointer hover:bg-amber-50/50'} ${active ? 'bg-amber-50' : ''}`}
                >
                  <td className="whitespace-nowrap px-3 py-2.5 font-semibold">
                    <span className="mr-2 inline-block h-2.5 w-2.5 rounded-full" style={{ background: d.is_own_store ? HOME_COLOR : COMPETITOR_COLOR }} />
                    <span style={{ color: d.is_own_store ? HOME_COLOR : '#27272A' }}>{name}</span>
                    {d.is_own_store && <span className="ml-2 rounded bg-home/10 px-1.5 py-0.5 text-xs font-semibold uppercase text-home">You</span>}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2.5 text-zinc-600">{[d.dealer_city, d.dealer_state].filter(Boolean).join(', ') || '--'}</td>
                  <td className="px-3 py-2.5 text-right font-semibold tabular-nums">{fmtNum(d.active_units)}</td>
                  <td className="px-3 py-2.5 text-right tabular-nums">{fmt$(d.avg_msrp)}</td>
                  <td className="px-3 py-2.5 text-right tabular-nums">{fmt$(d.avg_selling_price)}</td>
                  <td className="px-3 py-2.5 text-right font-medium tabular-nums" style={{ color: daysTextColor(d.avg_days_on_lot) }}>{fmtNum(d.avg_days_on_lot, 1)}</td>
                  <td className="whitespace-nowrap px-3 py-2.5 text-right text-zinc-600">{fmtAgo(d.last_scraped_at)}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </ChartCard>
  )
}

// ---------------------------------------------------------------------------
//  Inventory by model
// ---------------------------------------------------------------------------
export function InventoryComparison({ ours, theirs, storeLabel }) {
  const { toggleFilter } = useFilters()
  const data = useMemo(() => {
    const models = {}
    const add = (v, side) => {
      const m = v.model || 'Unknown'
      if (!models[m]) models[m] = { model: m, ours: 0, theirs: 0 }
      models[m][side]++
    }
    ours.forEach(v => add(v, 'ours'))
    theirs.forEach(v => add(v, 'theirs'))
    return Object.values(models)
      .map(d => ({ ...d, ourPct: pct(d.ours, ours.length), theirPct: pct(d.theirs, theirs.length) }))
      .sort((a, b) => (b.ours + b.theirs) - (a.ours + a.theirs))
      .slice(0, 20)
  }, [ours, theirs])

  if (!data.length) return <ChartCard title="Inventory by model"><EmptyChart /></ChartCard>

  return (
    <ChartCard title="Inventory by model" subtitle="Units in stock, with each model's share of that side's lot. Click a bar to filter.">
      <ResponsiveContainer width="100%" height={Math.max(300, data.length * 48 + 60)}>
        <BarChart data={data} layout="vertical" margin={{ left: 10, right: 56 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={GRID_STROKE} horizontal={false} />
          <XAxis type="number" tick={AXIS_TICK} axisLine={false} tickLine={false} allowDecimals={false} />
          <YAxis dataKey="model" type="category" tick={{ ...AXIS_TICK, fill: COLORS.ink }} axisLine={false} tickLine={false} width={130} />
          <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(val, name, p) => [`${val} units (${name === storeLabel ? p.payload.ourPct : p.payload.theirPct}%)`, name]} />
          <Legend iconType="circle" iconSize={10} wrapperStyle={{ fontSize: 14 }} itemSorter="dataKey" />
          <Bar dataKey="ours" name={storeLabel} fill={HOME_COLOR} radius={[0, 4, 4, 0]} barSize={16} onClick={e => toggleFilter('model', field(e, 'model'))} style={{ cursor: 'pointer' }}>
            <LabelList dataKey="ourPct" position="right" formatter={v => `${v}%`} style={{ fontSize: 12, fill: HOME_COLOR, fontWeight: 600 }} />
          </Bar>
          <Bar dataKey="theirs" name="Competitors" fill={COMPETITOR_COLOR} radius={[0, 4, 4, 0]} barSize={16} onClick={e => toggleFilter('model', field(e, 'model'))} style={{ cursor: 'pointer' }}>
            <LabelList dataKey="theirPct" position="right" formatter={v => `${v}%`} style={{ fontSize: 12, fill: COMPETITOR_TEXT, fontWeight: 600 }} />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </ChartCard>
  )
}

// ---------------------------------------------------------------------------
//  Trim mix for one model, side by side
// ---------------------------------------------------------------------------
function TrimTooltip({ active, payload }) {
  if (!active || !payload?.[0]) return null
  const d = payload[0].payload
  return (
    <div className="rounded-lg border border-zinc-200 bg-white px-3 py-2 text-sm shadow-lg">
      <p className="font-semibold text-zinc-800">{d.trim}</p>
      <p className="text-zinc-600">{d.count} units ({d.pct}% of model)</p>
    </div>
  )
}

export function TrimMixComparison({ ours, theirs, storeLabel }) {
  const { toggleFilter, filters } = useFilters()
  const models = useMemo(() => {
    const counts = {}
    for (const v of [...ours, ...theirs]) {
      const m = v.model || 'Unknown'
      counts[m] = (counts[m] || 0) + 1
    }
    return Object.entries(counts).sort((a, b) => b[1] - a[1]).map(([m]) => m)
  }, [ours, theirs])
  const [selected, setSelected] = useState('')
  // Start on the biggest model YOU stock, so both donuts have something in them.
  const firstShared = models.find(m => ours.some(v => (v.model || 'Unknown') === m))
  const model = models.includes(selected) ? selected : firstShared || models[0] || ''

  const mix = (rows) => {
    const inModel = rows.filter(v => (v.model || 'Unknown') === model)
    const counts = {}
    for (const v of inModel) {
      const t = v.trim || 'Unknown'
      counts[t] = (counts[t] || 0) + 1
    }
    return Object.entries(counts)
      .map(([trim, count]) => ({ trim, count, pct: pct(count, inModel.length) }))
      .sort((a, b) => b.count - a.count)
  }
  const ourData = mix(ours)
  const theirData = mix(theirs)
  const combined = {}
  for (const d of ourData) combined[d.trim] = { trim: d.trim, ours: d.count, ourPct: d.pct, theirs: 0, theirPct: '0.0' }
  for (const d of theirData) {
    combined[d.trim] = combined[d.trim] || { trim: d.trim, ours: 0, ourPct: '0.0' }
    combined[d.trim].theirs = d.count
    combined[d.trim].theirPct = d.pct
  }
  const rows = Object.values(combined).sort((a, b) => (b.ours + b.theirs) - (a.ours + a.theirs))

  if (!models.length) return <ChartCard title="Trim mix"><EmptyChart /></ChartCard>

  const donut = (data, palette, label, color) => (
    <div>
      <p className="mb-1 text-center text-sm font-semibold uppercase tracking-wider" style={{ color }}>{label}</p>
      {data.length ? (
        <ResponsiveContainer width="100%" height={210}>
          <PieChart>
            <Pie data={data} dataKey="count" nameKey="trim" innerRadius={45} outerRadius={90} paddingAngle={2}
              onClick={e => toggleFilter('trim', field(e, 'trim'))} style={{ cursor: 'pointer' }} isAnimationActive={false}>
              {data.map((d, i) => (
                <Cell key={d.trim} fill={palette[i % palette.length]} opacity={filters.trim.length && !filters.trim.includes(d.trim) ? 0.35 : 1} />
              ))}
            </Pie>
            <Tooltip content={<TrimTooltip />} />
          </PieChart>
        </ResponsiveContainer>
      ) : (
        <div className="flex h-[210px] items-center justify-center text-center text-base text-zinc-400">None in stock</div>
      )}
    </div>
  )

  return (
    <ChartCard title="Trim mix" subtitle={`How ${model} inventory splits by trim. Click a slice or row to filter.`}>
      {models.length > 1 && <div className="mb-3"><Select value={model} onChange={setSelected} options={models} /></div>}
      <div className="grid grid-cols-2 gap-4">
        {donut(ourData, CHART_COLORS, storeLabel, HOME_COLOR)}
        {donut(theirData, CHART_COLORS_DESAT, 'Competitors', COMPETITOR_TEXT)}
      </div>
      <div className="mt-3 max-h-[280px] overflow-y-auto">
        <table className="w-full text-base">
          <thead className="sticky top-0 bg-white">
            <tr className="text-sm text-zinc-500">
              <th className="pb-1.5 text-left font-semibold">Trim</th>
              <th className="pb-1.5 text-right font-semibold" style={{ color: HOME_COLOR }}>You</th>
              <th className="pb-1.5 text-right font-semibold" style={{ color: HOME_COLOR }}>%</th>
              <th className="pb-1.5 text-right font-semibold" style={{ color: COMPETITOR_TEXT }}>Them</th>
              <th className="pb-1.5 text-right font-semibold" style={{ color: COMPETITOR_TEXT }}>%</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(d => (
              <tr key={d.trim} onClick={() => toggleFilter('trim', d.trim)}
                className={`cursor-pointer border-t border-zinc-100 hover:bg-zinc-50 ${filters.trim.includes(d.trim) ? 'bg-zinc-50 font-semibold' : ''}`}>
                <td className="max-w-[220px] truncate py-1.5 text-zinc-800" title={d.trim}>{d.trim}</td>
                <td className="py-1.5 text-right font-semibold tabular-nums">{d.ours}</td>
                <td className="py-1.5 text-right tabular-nums text-zinc-500">{d.ourPct}%</td>
                <td className="py-1.5 text-right tabular-nums" style={{ color: COMPETITOR_TEXT }}>{d.theirs}</td>
                <td className="py-1.5 text-right tabular-nums text-zinc-500">{d.theirPct}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </ChartCard>
  )
}

// ---------------------------------------------------------------------------
//  Color availability
// ---------------------------------------------------------------------------
export function ColorAvailability({ ours, theirs, storeLabel }) {
  const { toggleFilter } = useFilters()
  const data = useMemo(() => {
    const colors = {}
    const add = (v, side) => {
      if (!v.exterior_color) return
      const c = v.exterior_color
      if (!colors[c]) colors[c] = { color: c, ours: 0, theirs: 0 }
      colors[c][side]++
    }
    ours.forEach(v => add(v, 'ours'))
    theirs.forEach(v => add(v, 'theirs'))
    return Object.values(colors)
      .map(d => ({ ...d, ourPct: pct(d.ours, ours.length), theirPct: pct(d.theirs, theirs.length) }))
      .sort((a, b) => (b.ours + b.theirs) - (a.ours + a.theirs))
      .slice(0, 15)
  }, [ours, theirs])

  if (!data.length) {
    return <ChartCard title="Color availability"><EmptyChart message="No exterior colors in the scraped data." hint="Some dealer sites do not publish color." /></ChartCard>
  }

  return (
    <ChartCard title="Color availability" subtitle="Top 15 exterior colors, as a share of each side's inventory. Click a bar to filter.">
      <ResponsiveContainer width="100%" height={Math.max(300, data.length * 44 + 60)}>
        <BarChart data={data} layout="vertical" margin={{ left: 10, right: 56 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={GRID_STROKE} horizontal={false} />
          <XAxis type="number" tick={AXIS_TICK} axisLine={false} tickLine={false} allowDecimals={false} />
          <YAxis dataKey="color" type="category" tick={{ ...AXIS_TICK, fill: COLORS.ink }} axisLine={false} tickLine={false} width={170}
            tickFormatter={v => (v.length > 24 ? v.slice(0, 22) + '...' : v)} />
          <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(val, name, p) => [`${val} units (${name === storeLabel ? p.payload.ourPct : p.payload.theirPct}%)`, name]} />
          <Legend iconType="circle" iconSize={10} wrapperStyle={{ fontSize: 14 }} itemSorter="dataKey" />
          <Bar dataKey="ours" name={storeLabel} fill={HOME_COLOR} radius={[0, 4, 4, 0]} barSize={14} onClick={e => toggleFilter('exteriorColor', field(e, 'color'))} style={{ cursor: 'pointer' }}>
            <LabelList dataKey="ourPct" position="right" formatter={v => `${v}%`} style={{ fontSize: 12, fill: HOME_COLOR, fontWeight: 600 }} />
          </Bar>
          <Bar dataKey="theirs" name="Competitors" fill={COMPETITOR_COLOR} radius={[0, 4, 4, 0]} barSize={14} onClick={e => toggleFilter('exteriorColor', field(e, 'color'))} style={{ cursor: 'pointer' }}>
            <LabelList dataKey="theirPct" position="right" formatter={v => `${v}%`} style={{ fontSize: 12, fill: COMPETITOR_TEXT, fontWeight: 600 }} />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </ChartCard>
  )
}

// ---------------------------------------------------------------------------
//  Price position by model / trim
// ---------------------------------------------------------------------------
export function PriceComparison({ ours, theirs }) {
  const data = useMemo(() => {
    const map = {}
    const add = (v, side) => {
      if (v.price == null) return
      const key = `${v.make}||${v.model}||${v.trim || ''}`
      if (!map[key]) map[key] = { key, make: v.make, model: v.model || 'Unknown', trim: v.trim || '', ours: [], theirs: [] }
      map[key][side].push(v.price)
    }
    ours.forEach(v => add(v, 'ours'))
    theirs.forEach(v => add(v, 'theirs'))
    return Object.values(map).map(d => {
      const ourAvg = avg(d.ours)
      const theirAvg = avg(d.theirs)
      const diff = ourAvg != null && theirAvg != null ? ourAvg - theirAvg : null
      return {
        ...d,
        ourCount: d.ours.length,
        theirCount: d.theirs.length,
        ourAvg,
        theirAvg,
        diff,
        diffPct: diff != null && theirAvg ? (diff / theirAvg) * 100 : null,
      }
    })
  }, [ours, theirs])

  const columns = [
    { key: 'model', label: 'Model', render: r => <span className="font-semibold text-zinc-900">{r.model}</span> },
    { key: 'trim', label: 'Trim', render: r => r.trim || '--' },
    { key: 'ourCount', label: 'Your #', align: 'right', render: r => r.ourCount || '--' },
    { key: 'ourAvg', label: 'Your avg price', align: 'right', render: r => fmt$(r.ourAvg), csv: r => r.ourAvg?.toFixed(0) },
    { key: 'theirCount', label: 'Their #', align: 'right', render: r => r.theirCount || '--' },
    { key: 'theirAvg', label: 'Their avg price', align: 'right', render: r => fmt$(r.theirAvg), csv: r => r.theirAvg?.toFixed(0) },
    {
      key: 'diff',
      label: 'You vs them',
      align: 'right',
      csv: r => r.diff?.toFixed(0),
      render: r => {
        if (r.diff == null) return <span className="text-zinc-400">--</span>
        const style = r.diff < 0 ? { background: COLORS.goodBg, color: COLORS.goodText } : r.diff > 0 ? { background: COLORS.badBg, color: COLORS.badText } : {}
        return (
          <span className="rounded-md px-2 py-0.5 font-semibold" style={style}>
            {r.diff > 0 ? '+' : ''}{fmt$(r.diff)} ({r.diff > 0 ? '+' : ''}{r.diffPct.toFixed(1)}%)
          </span>
        )
      },
    },
  ]

  return (
    <ChartCard title="Price position" subtitle="Average asking price by model and trim (selling price, or MSRP when no selling price is posted). Sorted by where you are priced highest. Green = you are cheaper.">
      <DataTable
        rows={data}
        columns={columns}
        searchKeys={['model', 'trim', 'make']}
        searchPlaceholder="Search model or trim..."
        defaultSort="diff"
        defaultDir="desc"
        exportName="price-position"
        maxHeight={460}
        emptyMessage="No prices to compare with these filters."
      />
    </ChartCard>
  )
}

// ---------------------------------------------------------------------------
//  Gap analysis
// ---------------------------------------------------------------------------
export function GapAnalysis({ ours, theirs, stacked = false }) {
  const { toggleFilter } = useFilters()
  const gaps = useMemo(() => {
    const keyOf = v => `${v.make || ''}||${v.model || ''}||${v.trim || ''}`
    const ourSet = new Set(ours.map(keyOf))
    const theirSet = new Set(theirs.map(keyOf))
    const group = (rows, exclude) => {
      const out = {}
      for (const v of rows) {
        if (!v.model) continue
        const k = keyOf(v)
        if (exclude.has(k)) continue
        if (!out[k]) out[k] = { make: v.make, model: v.model, trim: v.trim || '', count: 0, prices: [], dealers: new Set() }
        out[k].count++
        if (v.price != null) out[k].prices.push(v.price)
        out[k].dealers.add(v.dealer_label)
      }
      return Object.values(out).map(d => ({ ...d, avgPrice: avg(d.prices), dealerCount: d.dealers.size })).sort((a, b) => b.count - a.count)
    }
    return { missing: group(theirs, ourSet), exclusive: group(ours, theirSet) }
  }, [ours, theirs])

  const table = (rows, color, showDealers) => (
    <div className="max-h-[400px] overflow-auto rounded-xl border border-zinc-200">
      <table className="w-full text-base">
        <thead className="sticky top-0 bg-zinc-50">
          <tr className="text-xs font-semibold uppercase tracking-wider text-zinc-500">
            <th className="px-3 py-2 text-left">Model</th>
            <th className="px-3 py-2 text-left">Trim</th>
            <th className="px-3 py-2 text-right">Units</th>
            {showDealers && <th className="px-3 py-2 text-right">Stores</th>}
            <th className="px-3 py-2 text-right">Avg price</th>
          </tr>
        </thead>
        <tbody>
          {rows.slice(0, 25).map(d => (
            <tr key={`${d.make}-${d.model}-${d.trim}`} onClick={() => toggleFilter('model', d.model)} className="cursor-pointer border-t border-zinc-100 hover:bg-zinc-50">
              <td className="whitespace-nowrap px-3 py-2 font-semibold text-zinc-900">{d.model}</td>
              <td className="px-3 py-2 text-zinc-600">{d.trim || '--'}</td>
              <td className="px-3 py-2 text-right font-bold tabular-nums" style={{ color }}>{d.count}</td>
              {showDealers && <td className="px-3 py-2 text-right tabular-nums text-zinc-600">{d.dealerCount}</td>}
              <td className="px-3 py-2 text-right tabular-nums text-zinc-600">{fmt$(d.avgPrice)}</td>
            </tr>
          ))}
          {rows.length === 0 && (
            <tr><td colSpan={5} className="px-3 py-6 text-center text-zinc-500">None with these filters</td></tr>
          )}
        </tbody>
      </table>
    </div>
  )

  return (
    <ChartCard title="Gap analysis" subtitle="Model and trim combinations only one side has on the ground right now. Click a row to filter by that model.">
      <div className={`grid grid-cols-1 gap-5 ${stacked ? '' : 'xl:grid-cols-2'}`}>
        <div>
          <h4 className="mb-2 text-sm font-bold uppercase tracking-wider" style={{ color: COLORS.bad }}>They have it, you don't</h4>
          {table(gaps.missing, COLORS.bad, true)}
        </div>
        <div>
          <h4 className="mb-2 text-sm font-bold uppercase tracking-wider" style={{ color: COLORS.good }}>You have it, they don't</h4>
          {table(gaps.exclusive, COLORS.good, false)}
        </div>
      </div>
    </ChartCard>
  )
}

// ---------------------------------------------------------------------------
//  Every competitor vehicle
// ---------------------------------------------------------------------------
export function VinLink({ v }) {
  return (
    <Link to={`/vehicle/${encodeURIComponent(v.dealer_key)}/${encodeURIComponent(v.vin)}`} className="font-mono text-[13px] font-medium hover:underline" style={{ color: HOME_COLOR }}>
      {v.vin}
    </Link>
  )
}

export function ListingLink({ url }) {
  if (!url) return <span className="text-zinc-300">--</span>
  return (
    <a href={url} target="_blank" rel="noopener noreferrer" title="Open on the dealer's website" className="inline-flex items-center gap-1 text-zinc-500 hover:text-accent">
      <ExternalLink className="h-4 w-4" />
    </a>
  )
}

export function CompetitorTable({ vehicles }) {
  const showMileage = vehicles.some(v => v.mileage != null && v.mileage > 500)
  const columns = [
    { key: 'dealer_label', label: 'Dealer', render: r => <span className="font-medium text-zinc-900">{r.dealer_label}</span> },
    { key: 'vin', label: 'VIN', render: r => <VinLink v={r} /> },
    { key: 'year', label: 'Year', align: 'right' },
    { key: 'make', label: 'Make' },
    { key: 'model', label: 'Model' },
    { key: 'trim', label: 'Trim' },
    { key: 'exterior_color', label: 'Ext color' },
    { key: 'msrp', label: 'MSRP', align: 'right', render: r => fmt$(r.msrp) },
    { key: 'selling_price', label: 'Selling price', align: 'right', render: r => <span className="font-semibold text-zinc-900">{fmt$(r.selling_price)}</span> },
    { key: 'days_on_lot', label: 'Days', align: 'right', render: r => <span className="font-semibold" style={{ color: daysTextColor(r.days_on_lot) }}>{r.days_on_lot ?? '--'}</span> },
    ...(showMileage ? [{ key: 'mileage', label: 'Miles', align: 'right', render: r => fmtNum(r.mileage) }] : []),
    { key: 'drivetrain', label: 'Drive' },
    { key: 'listing_url', label: 'Site', sortable: false, render: r => <ListingLink url={r.listing_url} />, csv: r => r.listing_url },
  ]
  return (
    <ChartCard title="Competitor inventory" subtitle="Every competitor vehicle matching your filters. Click a VIN for its price history.">
      <DataTable
        rows={vehicles}
        columns={columns}
        searchKeys={['vin', 'stock_number', 'dealer_label', 'make', 'model', 'trim', 'exterior_color', 'drivetrain']}
        searchPlaceholder="Search VIN, dealer, model, trim, color..."
        defaultSort="dealer_label"
        exportName="competitor-inventory"
      />
    </ChartCard>
  )
}
