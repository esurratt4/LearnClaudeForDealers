// MY LOT: your own inventory. How much, what mix, and what is aging.

import { useMemo } from 'react'
import { useData } from '../lib/data'
import { applyFilters, useFilters } from '../lib/filters'
import FilterPillBar from '../components/FilterPillBar'
import { Banner, SectionLabel } from '../components/ui'
import {
  AgeBucketChart, DaysByField, InventoryByModel, LotKPICards, LotVehicleTable,
  PriceDistribution, TrimMix,
} from '../components/lot/LotCharts'

const FILTER_KEYS = ['condition', 'make', 'model', 'trim', 'bodyType', 'exteriorColor', 'interiorColor', 'engine', 'drivetrain', 'ageBucket']

const byColor = v => v.exterior_color
const byEngine = v => v.engine_short
const byTrim = v => v.trim
const byBody = v => v.body_type

export default function LotView() {
  const { own } = useData()
  const { filters } = useFilters()
  const vehicles = useMemo(() => applyFilters(own, filters), [own, filters])
  const oldest = own.reduce((m, v) => Math.max(m, v.days_on_lot ?? 0), 0)

  if (own.length === 0) {
    return (
      <Banner tone="warn" title="No vehicles for your own store yet">
        This page shows your own lot. Check that your dealership is under <b>own_store:</b> in config/dealers.yml and that its scrape found vehicles.
      </Banner>
    )
  }

  return (
    <div className="space-y-5">
      <FilterPillBar vehicles={own} keys={FILTER_KEYS} />

      {oldest < 7 && (
        <Banner title="Days on lot starts counting today">
          Days on lot counts from the first day the scraper saw each car, so a new setup reads close to 0 everywhere. Run the scraper daily and within a week or two these numbers show which units are really sitting.
        </Banner>
      )}

      <LotKPICards vehicles={vehicles} />

      <SectionLabel>Inventory breakdown</SectionLabel>
      <div className="grid grid-cols-1 gap-5 xl:grid-cols-2">
        <InventoryByModel vehicles={vehicles} />
        <TrimMix vehicles={vehicles} />
      </div>

      <SectionLabel>Aging</SectionLabel>
      <div className="grid grid-cols-1 gap-5 xl:grid-cols-2">
        <AgeBucketChart vehicles={vehicles} />
        <DaysByField vehicles={vehicles} title="Avg days on lot by color" getValue={byColor} filterKey="exteriorColor" emptyHint="Some dealer sites do not publish color." />
      </div>

      <SectionLabel>Turn performance</SectionLabel>
      <div className="grid grid-cols-1 gap-5 xl:grid-cols-2">
        <DaysByField vehicles={vehicles} title="Avg days on lot by trim" getValue={byTrim} filterKey="trim" />
        <DaysByField vehicles={vehicles} title="Avg days on lot by engine" getValue={byEngine} filterKey="engine" width={200} emptyHint="Some dealer sites do not publish the engine." />
      </div>

      <SectionLabel>Pricing</SectionLabel>
      <div className="grid grid-cols-1 gap-5 xl:grid-cols-2">
        <PriceDistribution vehicles={vehicles} />
        <DaysByField vehicles={vehicles} title="Avg days on lot by body style" getValue={byBody} filterKey="bodyType" emptyHint="Some dealer sites do not publish body style." />
      </div>

      <SectionLabel>Detail</SectionLabel>
      <LotVehicleTable vehicles={vehicles} />
    </div>
  )
}
