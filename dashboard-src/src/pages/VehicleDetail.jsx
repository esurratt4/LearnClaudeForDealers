// ONE VEHICLE: its details, where it sits against the same model at other stores,
// and every price the scraper has recorded for it (price_history).

import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { ArrowLeft, ExternalLink, MapPin } from 'lucide-react'
import { classifyError, enrichVehicle, getClient, useData } from '../lib/data'
import { avg, fmt$, fmtDate, fmtNum } from '../lib/format'
import { COLORS, COMPETITOR_TEXT, HOME_COLOR, daysTextColor } from '../lib/theme'
import { Banner, ChartCard, EmptyChart } from '../components/ui'
import DataTable from '../components/DataTable'
import { ListingLink, VinLink } from '../components/market/MarketCharts'

function PriceHistoryChart({ history }) {
  const data = history.map(h => ({
    ts: new Date(h.observed_at).getTime(),
    observed_at: h.observed_at,
    msrp: h.msrp != null ? Number(h.msrp) : null,
    selling_price: h.selling_price != null ? Number(h.selling_price) : null,
  }))

  if (!data.length) {
    return <EmptyChart message="No price history recorded for this vehicle yet." />
  }

  const ys = data.flatMap(d => [d.msrp, d.selling_price]).filter(v => v != null)
  if (!ys.length) return <EmptyChart message="This dealer's site does not post a price for this vehicle." />

  const yMin = Math.min(...ys)
  const yMax = Math.max(...ys)
  const yPad = Math.max((yMax - yMin) * 0.15, 500)
  const tsMin = data[0].ts
  const tsMax = data[data.length - 1].ts
  const xPad = Math.max((tsMax - tsMin) * 0.08, 86400000 * 0.5)
  const sparse = data.length === 1
  const fmtDay = ts => new Date(ts).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })

  return (
    <div>
      <ResponsiveContainer width="100%" height={320}>
        <LineChart data={data} margin={{ top: 10, right: 24, left: 8, bottom: 8 }}>
          <CartesianGrid stroke={COLORS.gridLine} vertical={false} />
          <XAxis dataKey="ts" type="number" scale="time" domain={[tsMin - xPad, tsMax + xPad]} tickFormatter={fmtDay} tick={{ fontSize: 13, fill: COLORS.axisLabel }} />
          <YAxis domain={[Math.floor((yMin - yPad) / 1000) * 1000, Math.ceil((yMax + yPad) / 1000) * 1000]} tickCount={6} allowDecimals={false} tickFormatter={v => fmt$(v)} tick={{ fontSize: 13, fill: COLORS.axisLabel }} width={84} />
          <Tooltip
            labelFormatter={ts => fmtDate(ts)}
            formatter={(val, name) => [fmt$(val), name]}
            contentStyle={{ borderRadius: 10, fontSize: 14 }}
          />
          <Legend wrapperStyle={{ fontSize: 14 }} />
          <Line type="stepAfter" dataKey="msrp" name="MSRP" stroke={COLORS.cat[1]} strokeWidth={2} strokeDasharray="5 4" dot={{ r: sparse ? 6 : 3 }} isAnimationActive={false} connectNulls />
          <Line type="stepAfter" dataKey="selling_price" name="Selling price" stroke={HOME_COLOR} strokeWidth={3} dot={{ r: sparse ? 7 : 4 }} isAnimationActive={false} connectNulls />
        </LineChart>
      </ResponsiveContainer>
      {sparse && (
        <p className="mt-2 text-base text-zinc-500">
          One price recorded so far, on {fmtDate(data[0].observed_at)}. Each later scrape that sees a different price adds a point here.
        </p>
      )}
    </div>
  )
}

function Box({ label, value, color }) {
  return (
    <div className="min-w-[120px]">
      <p className="text-xs font-semibold uppercase tracking-wider text-zinc-500">{label}</p>
      <p className="text-3xl font-semibold tabular-nums" style={{ color: color || '#18181B' }}>{value}</p>
    </div>
  )
}

function Spec({ label, value }) {
  if (value == null || value === '') return null
  return (
    <div className="flex justify-between gap-4 border-b border-zinc-100 py-2 text-base">
      <span className="text-zinc-500">{label}</span>
      <span className="text-right font-medium text-zinc-900">{value}</span>
    </div>
  )
}

export default function VehicleDetail() {
  const { dealerKey, vin } = useParams()
  const navigate = useNavigate()
  const { config, vehicles } = useData()
  const [state, setState] = useState({ loading: true, unit: null, history: [], error: null })

  useEffect(() => {
    let cancelled = false
    async function load() {
      setState(s => ({ ...s, loading: true }))
      const sb = getClient(config)
      const [unitRes, histRes] = await Promise.all([
        sb.from('vehicles').select('*').eq('dealer_key', dealerKey).eq('vin', vin).maybeSingle(),
        sb.from('price_history').select('observed_at, msrp, selling_price').eq('dealer_key', dealerKey).eq('vin', vin).order('observed_at', { ascending: true }).limit(1000),
      ])
      if (cancelled) return
      const err = unitRes.error || histRes.error
      if (err) {
        setState({ loading: false, unit: null, history: [], error: classifyError(err) })
        return
      }
      setState({ loading: false, unit: unitRes.data ? enrichVehicle(unitRes.data) : null, history: histRes.data || [], error: null })
    }
    load()
    return () => { cancelled = true }
  }, [config, dealerKey, vin])

  const { unit, history, loading, error } = state

  // Same make and model on the ground right now, at every store.
  const comparable = useMemo(() => {
    if (!unit) return []
    return vehicles.filter(v => v.make === unit.make && v.model === unit.model && !(v.vin === unit.vin && v.dealer_key === unit.dealer_key))
  }, [vehicles, unit])
  const sameTrim = comparable.filter(v => (v.trim || '') === (unit?.trim || ''))

  const back = (
    <button onClick={() => navigate(-1)} className="mb-4 inline-flex items-center gap-1.5 text-base font-medium text-zinc-600 hover:text-accent">
      <ArrowLeft className="h-4 w-4" /> Back
    </button>
  )

  if (loading) {
    return (
      <div className="space-y-4">
        {back}
        <div className="h-10 w-80 animate-pulse rounded bg-zinc-200" />
        <div className="h-72 animate-pulse rounded-2xl bg-zinc-100" />
      </div>
    )
  }

  if (error) {
    return <div>{back}<Banner tone="warn" title="Could not load this vehicle">{error.message}</Banner></div>
  }

  if (!unit) {
    return (
      <div>
        {back}
        <Banner tone="warn" title="Vehicle not found">
          No vehicle with VIN <span className="font-mono">{vin}</span> at dealer <b>{dealerKey}</b> is in your database. <Link to="/" className="font-medium underline">Back to the market</Link>
        </Banner>
      </div>
    )
  }

  const discountPct = unit.msrp && unit.selling_price ? ((unit.msrp - unit.selling_price) / unit.msrp) * 100 : null
  const prices = history.map(h => (h.selling_price != null ? Number(h.selling_price) : null)).filter(v => v != null)
  let cuts = 0
  for (let i = 1; i < prices.length; i++) if (prices[i] < prices[i - 1]) cuts++
  const photos = (unit.photo_urls || []).filter(Boolean).slice(0, 6)
  const marketAvg = avg(sameTrim.filter(v => !v.is_own_store || !unit.is_own_store).map(v => v.price))

  const compareColumns = [
    { key: 'dealer_label', label: 'Dealer', render: r => <span className="font-medium" style={{ color: r.is_own_store ? HOME_COLOR : '#18181B' }}>{r.dealer_label}{r.is_own_store ? ' (you)' : ''}</span> },
    { key: 'vin', label: 'VIN', render: r => <VinLink v={r} /> },
    { key: 'year', label: 'Year', align: 'right' },
    { key: 'trim', label: 'Trim' },
    { key: 'exterior_color', label: 'Ext color' },
    { key: 'price', label: 'Asking', align: 'right', render: r => <span className="font-semibold">{fmt$(r.price)}</span> },
    { key: 'days_on_lot', label: 'Days', align: 'right', render: r => <span className="font-semibold" style={{ color: daysTextColor(r.days_on_lot) }}>{r.days_on_lot ?? '--'}</span> },
    { key: 'listing_url', label: 'Site', sortable: false, render: r => <ListingLink url={r.listing_url} />, csv: r => r.listing_url },
  ]

  return (
    <div className="space-y-5">
      {back}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight text-zinc-900">
            {[unit.year, unit.make, unit.model, unit.trim].filter(Boolean).join(' ')}
          </h1>
          <p className="mt-1 font-mono text-base text-zinc-500">{unit.vin}{unit.stock_number ? `  ·  Stock #${unit.stock_number}` : ''}</p>
        </div>
        <div className="flex items-center gap-2">
          <span className="rounded-full px-3 py-1 text-sm font-semibold" style={unit.is_own_store ? { background: '#E6EFEE', color: HOME_COLOR } : { background: '#F1ECE5', color: COMPETITOR_TEXT }}>
            {unit.is_own_store ? 'Your store' : 'Competitor'}
          </span>
          {unit.is_active
            ? <span className="rounded-full px-3 py-1 text-sm font-semibold" style={{ background: COLORS.goodBg, color: COLORS.goodText }}>Listed</span>
            : <span className="rounded-full bg-zinc-200 px-3 py-1 text-sm font-semibold text-zinc-700">Gone from site {fmtDate(unit.removed_at || unit.last_seen_at)}</span>}
        </div>
      </div>

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-5">
        <div className="space-y-5 xl:col-span-3">
          <ChartCard title="Pricing">
            <div className="flex flex-wrap gap-x-10 gap-y-4">
              <Box label="MSRP" value={fmt$(unit.msrp)} />
              <Box label="Selling price" value={fmt$(unit.selling_price)} color={HOME_COLOR} />
              {discountPct != null && <Box label="Off MSRP" value={`${discountPct.toFixed(1)}%`} color={discountPct >= 5 ? COLORS.good : undefined} />}
              <Box label="Days on lot" value={unit.days_on_lot ?? '--'} color={daysTextColor(unit.days_on_lot)} />
              <Box label="Price cuts" value={cuts} color={cuts ? COLORS.bad : undefined} />
            </div>
            {marketAvg != null && unit.price != null && (
              <p className="mt-4 text-base text-zinc-600">
                Same trim elsewhere averages <b>{fmt$(marketAvg)}</b>. This one is{' '}
                <b style={{ color: unit.price <= marketAvg ? COLORS.good : COLORS.bad }}>
                  {fmt$(Math.abs(unit.price - marketAvg))} {unit.price <= marketAvg ? 'below' : 'above'}
                </b>{' '}that.
              </p>
            )}
          </ChartCard>

          <ChartCard title="Price history" subtitle="Every price the scraper has recorded for this vehicle at this store.">
            <PriceHistoryChart history={history} />
          </ChartCard>
        </div>

        <div className="space-y-5 xl:col-span-2">
          <ChartCard title="Dealer">
            <div className="flex items-start gap-2 text-lg">
              <MapPin className="mt-1 h-5 w-5 text-zinc-400" />
              <div>
                <p className="font-semibold text-zinc-900">{unit.dealer_label}</p>
                <p className="text-base text-zinc-500">{[unit.dealer_city, unit.dealer_state].filter(Boolean).join(', ')}</p>
              </div>
            </div>
            {unit.listing_url && (
              <a href={unit.listing_url} target="_blank" rel="noopener noreferrer"
                className="mt-4 inline-flex items-center gap-2 rounded-lg border border-zinc-300 px-4 py-2 text-base font-medium text-zinc-700 hover:bg-zinc-50">
                <ExternalLink className="h-4 w-4" /> Open on their website
              </a>
            )}
            {photos.length > 0 && (
              <div className="mt-4 grid grid-cols-3 gap-2">
                {photos.map(src => (
                  <img key={src} src={src} alt="" loading="lazy" referrerPolicy="no-referrer"
                    className="aspect-[4/3] w-full rounded-lg bg-zinc-100 object-cover"
                    onError={e => { e.currentTarget.style.display = 'none' }} />
                ))}
              </div>
            )}
          </ChartCard>

          <ChartCard title="Details">
            <Spec label="Condition" value={unit.condition ? unit.condition[0].toUpperCase() + unit.condition.slice(1) : null} />
            <Spec label="Body" value={unit.body_type} />
            <Spec label="Engine" value={unit.engine} />
            <Spec label="Fuel" value={unit.fuel_type} />
            <Spec label="Drivetrain" value={unit.drivetrain} />
            <Spec label="Exterior" value={unit.exterior_color} />
            <Spec label="Interior" value={unit.interior_color} />
            <Spec label="Horsepower" value={unit.horsepower ? `${unit.horsepower} hp` : null} />
            <Spec label="Mileage" value={unit.mileage != null ? `${fmtNum(unit.mileage)} mi` : null} />
            <Spec label="First seen" value={fmtDate(unit.first_seen_at)} />
            <Spec label="Last seen" value={fmtDate(unit.last_seen_at)} />
          </ChartCard>
        </div>
      </div>

      <ChartCard title={`Every ${unit.make || ''} ${unit.model || ''} on the ground`} subtitle="The same make and model at your store and every competitor, right now.">
        <DataTable
          rows={comparable}
          columns={compareColumns}
          defaultSort="price"
          defaultDir="asc"
          pageSize={25}
          maxHeight={480}
          emptyMessage="No other store has this model listed right now."
        />
      </ChartCard>
    </div>
  )
}
