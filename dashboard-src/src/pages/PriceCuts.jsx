// PRICE CUTS: every vehicle whose asking price is lower now than the first time we
// saw it. Comes straight from the v_price_drops report in sql/schema.sql.

import { useMemo, useState } from 'react'
import { useData } from '../lib/data'
import { applyFilters, useFilters } from '../lib/filters'
import FilterPillBar from '../components/FilterPillBar'
import DataTable from '../components/DataTable'
import { Banner, ChartCard, KPIRow, Metric } from '../components/ui'
import { ListingLink, VinLink } from '../components/market/MarketCharts'
import { avg, fmt$, fmt$Short, fmtNum } from '../lib/format'
import { COLORS, HOME_COLOR, daysTextColor } from '../lib/theme'

const FILTER_KEYS = ['dealer', 'make', 'model', 'trim']

export function PriceCutsTable({ rows, title, subtitle, compact = false }) {
  const columns = [
    {
      key: 'dealer_label',
      label: 'Dealer',
      render: r => <span className="font-medium" style={{ color: r.is_own_store ? HOME_COLOR : '#18181B' }}>{r.dealer_label}{r.is_own_store ? ' (you)' : ''}</span>,
    },
    { key: 'vehicle', label: 'Vehicle', sortValue: r => `${r.model} ${r.trim}`, csv: r => [r.year, r.make, r.model, r.trim].filter(Boolean).join(' '),
      render: r => <span className="font-medium text-zinc-900">{[r.year, r.make, r.model, r.trim].filter(Boolean).join(' ')}</span> },
    { key: 'vin', label: 'VIN', render: r => <VinLink v={r} /> },
    { key: 'original_price', label: 'Was', align: 'right', render: r => <span className="text-zinc-500 line-through">{fmt$(r.original_price)}</span> },
    { key: 'current_price', label: 'Now', align: 'right', render: r => <span className="font-semibold text-zinc-900">{fmt$(r.current_price)}</span> },
    { key: 'price_drop', label: 'Cut', align: 'right', render: r => <span className="rounded-md px-2 py-0.5 font-bold" style={{ background: COLORS.badBg, color: COLORS.badText }}>-{fmt$(r.price_drop)}</span> },
    { key: 'price_drop_pct', label: 'Cut %', align: 'right', render: r => `${fmtNum(r.price_drop_pct, 1)}%` },
    { key: 'days_between', label: 'Days before cut', align: 'right', render: r => fmtNum(r.days_between) },
    { key: 'days_on_lot', label: 'Days on lot', align: 'right', render: r => <span className="font-semibold" style={{ color: daysTextColor(r.days_on_lot) }}>{r.days_on_lot ?? '--'}</span> },
    ...(compact ? [] : [{ key: 'is_active', label: 'Status', sortValue: r => (r.is_active ? 1 : 0), csv: r => (r.is_active ? 'Listed' : 'Gone from site'),
      render: r => (r.is_active
        ? <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-sm font-medium text-emerald-800">Listed</span>
        : <span className="rounded-full bg-zinc-100 px-2 py-0.5 text-sm font-medium text-zinc-600">Gone from site</span>) }]),
    { key: 'listing_url', label: 'Site', sortable: false, render: r => <ListingLink url={r.listing_url} />, csv: r => r.listing_url },
  ]

  return (
    <ChartCard title={title} subtitle={subtitle}>
      {rows.length === 0 ? (
        <div className="rounded-xl border border-dashed border-zinc-200 bg-zinc-50/60 px-6 py-8 text-center">
          <p className="text-lg font-medium text-zinc-700">No price cuts caught yet.</p>
          <p className="mx-auto mt-1 max-w-2xl text-base text-zinc-500">
            A price cut is the difference between two looks at the same car, so this fills in once the scraper has run on at least two different days. Schedule the daily scrape and check back in a week.
          </p>
        </div>
      ) : (
        <DataTable
          rows={rows}
          columns={columns}
          searchKeys={['dealer_label', 'vin', 'stock_number', 'make', 'model', 'trim']}
          searchPlaceholder="Search dealer, VIN, model, trim..."
          defaultSort="price_drop"
          defaultDir="desc"
          exportName="price-cuts"
          pageSize={compact ? 10 : 50}
          maxHeight={compact ? 520 : 640}
        />
      )}
    </ChartCard>
  )
}

function Toggle({ checked, onChange, children }) {
  return (
    <label className="flex cursor-pointer items-center gap-2 rounded-lg border border-zinc-200 bg-white px-3 py-2 text-sm font-medium text-zinc-700">
      <input type="checkbox" checked={checked} onChange={e => onChange(e.target.checked)} className="h-4 w-4 accent-[#C2692A]" />
      {children}
    </label>
  )
}

export default function PriceCuts() {
  const { drops } = useData()
  const { filters } = useFilters()
  const [listedOnly, setListedOnly] = useState(true)
  const [competitorsOnly, setCompetitorsOnly] = useState(true)

  const base = useMemo(
    () => drops.filter(d => (!listedOnly || d.is_active) && (!competitorsOnly || !d.is_own_store)),
    [drops, listedOnly, competitorsOnly],
  )
  const rows = useMemo(() => applyFilters(base, filters), [base, filters])

  const totalCut = rows.reduce((s, r) => s + (r.price_drop || 0), 0)
  const stores = new Set(rows.map(r => r.dealer_key)).size

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start gap-3">
        <div className="flex-1"><FilterPillBar vehicles={base} keys={FILTER_KEYS} /></div>
        <Toggle checked={listedOnly} onChange={setListedOnly}>Still listed only</Toggle>
        <Toggle checked={competitorsOnly} onChange={setCompetitorsOnly}>Competitors only</Toggle>
      </div>

      <Banner title="What this tells you">
        A cut on a unit that sat for weeks shows a competitor's floor and their aging pain. "Days before cut" is how long they held the original price.
      </Banner>

      <KPIRow>
        <Metric label="Price cuts caught" value={fmtNum(rows.length)} subtitle="units priced lower than first seen" />
        <Metric label="Stores cutting" value={fmtNum(stores)} />
        <Metric label="Avg cut" value={fmt$(avg(rows.map(r => r.price_drop)))} subtitle={`${fmtNum(avg(rows.map(r => r.price_drop_pct)), 1)}% on average`} />
        <Metric label="Total dollars cut" value={fmt$Short(totalCut)} />
        <Metric label="Avg days before cut" value={fmtNum(avg(rows.map(r => r.days_between)), 1)} />
      </KPIRow>

      <PriceCutsTable rows={rows} title="Every price cut" subtitle="Biggest dollar cut first. Click a VIN for the full price history." />
    </div>
  )
}
