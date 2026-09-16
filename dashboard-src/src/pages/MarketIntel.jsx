// MARKET: your lot against every competitor you track.

import { useMemo } from 'react'
import { Link } from 'react-router-dom'
import { useData } from '../lib/data'
import { applyFilters, useFilters } from '../lib/filters'
import FilterPillBar from '../components/FilterPillBar'
import { Banner, SectionLabel } from '../components/ui'
import {
  ColorAvailability, CompetitorTable, DealerScoreboard, GapAnalysis, InventoryComparison,
  MarketKPICards, PriceComparison, TrimMixComparison,
} from '../components/market/MarketCharts'
import { PriceCutsTable } from './PriceCuts'

const FILTER_KEYS = ['dealer', 'condition', 'make', 'model', 'trim', 'bodyType', 'exteriorColor', 'drivetrain']

export default function MarketIntel() {
  const { vehicles, own, competitors, dealers, drops, ownStoreName } = useData()
  const { filters } = useFilters()

  // The Dealer filter narrows the competition. It never hides your own cars.
  const ours = useMemo(() => applyFilters(own, filters, ['dealer']), [own, filters])
  const theirs = useMemo(() => applyFilters(competitors, filters), [competitors, filters])
  const recentCuts = useMemo(
    () => applyFilters(drops.filter(d => !d.is_own_store && d.is_active), filters, ['condition', 'bodyType', 'drivetrain']),
    [drops, filters],
  )

  const storeLabel = ownStoreName || 'Your store'
  const competitorCount = filters.dealer.length || new Set(competitors.map(v => v.dealer_key)).size
  const optionSource = useMemo(() => ({ dealer: competitors }), [competitors])

  return (
    <div className="space-y-5">
      <FilterPillBar vehicles={vehicles} keys={FILTER_KEYS} optionSource={optionSource} />

      {own.length === 0 && (
        <Banner tone="warn" title="No vehicles for your own store yet">
          Every comparison below needs your lot on one side. Check that your dealership is under <b>own_store:</b> in config/dealers.yml and that its scrape found vehicles.
        </Banner>
      )}
      {competitors.length === 0 && (
        <Banner tone="warn" title="No competitor vehicles yet">
          Add competitors under <b>competitors:</b> in config/dealers.yml and run the scraper on them.
        </Banner>
      )}

      <MarketKPICards ours={ours} theirs={theirs} competitorCount={competitorCount} />

      <DealerScoreboard dealers={dealers} />

      <SectionLabel>Inventory comparison</SectionLabel>
      <div className="grid grid-cols-1 gap-5 xl:grid-cols-2">
        <InventoryComparison ours={ours} theirs={theirs} storeLabel={storeLabel} />
        <ColorAvailability ours={ours} theirs={theirs} storeLabel={storeLabel} />
      </div>

      <SectionLabel>Gap analysis and trim mix</SectionLabel>
      <div className="grid grid-cols-1 gap-5 xl:grid-cols-2">
        <GapAnalysis ours={ours} theirs={theirs} stacked />
        <TrimMixComparison ours={ours} theirs={theirs} storeLabel={storeLabel} />
      </div>

      <SectionLabel>Price position</SectionLabel>
      <PriceComparison ours={ours} theirs={theirs} />

      <SectionLabel>Competitor price cuts</SectionLabel>
      <PriceCutsTable
        rows={recentCuts}
        title="Who blinked"
        subtitle={<>Competitor units still listed whose price is lower than when we first saw them. <Link to="/price-cuts" className="font-medium text-accent hover:underline">See every price cut</Link></>}
        compact
      />

      <SectionLabel>Competitor detail</SectionLabel>
      <CompetitorTable vehicles={theirs} />
    </div>
  )
}
