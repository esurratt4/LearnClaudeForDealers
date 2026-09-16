// ============================================================================
//  DATA LAYER
//
//  Everything the dashboard shows comes from your Supabase database, read with the
//  read-only anon key. What we load (see sql/schema.sql):
//
//    vehicles               every car currently on a lot (is_active = true).
//                           is_own_store = true is YOUR lot; false is a competitor.
//    v_inventory_by_dealer  one line per store: units, avg price, last scraped
//    v_price_drops          every car whose price went down since we first saw it
//    scraper_runs           the last few scraper runs (shown when the lot is empty)
//
//  Price: there is no single "price" column. We use selling_price when the site
//  shows one, otherwise msrp, the same rule the SQL reports use.
//  Days on lot: today's date minus the date the scraper FIRST saw the car on that
//  dealer's site, the same rule as v_active_inventory.
// ============================================================================

import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import { createClient } from '@supabase/supabase-js'
import { ageBucket } from './theme'

const PAGE = 1000
const REFRESH_MS = 5 * 60 * 1000

const VEHICLE_COLUMNS = [
  'id', 'vin', 'dealer_key', 'dealer_name', 'dealer_city', 'dealer_state', 'is_own_store',
  'condition', 'stock_number', 'year', 'make', 'model', 'trim', 'body_type', 'engine',
  'fuel_type', 'drivetrain', 'exterior_color', 'interior_color', 'msrp', 'selling_price',
  'mileage', 'horsepower', 'listing_url', 'first_seen_at', 'last_seen_at', 'is_active',
].join(',')

let client = null
let clientKey = ''
export function getClient(config) {
  const k = config.url + '|' + config.key
  if (!client || clientKey !== k) {
    client = createClient(config.url, config.key, {
      auth: { persistSession: false, autoRefreshToken: false, detectSessionInUrl: false },
    })
    clientKey = k
  }
  return client
}

// Supabase returns at most 1000 rows per request, so ask page by page.
async function fetchAll(build) {
  const out = []
  let from = 0
  for (;;) {
    const { data, error } = await build().range(from, from + PAGE - 1)
    if (error) throw error
    out.push(...(data || []))
    if (!data || data.length < PAGE) break
    from += PAGE
  }
  return out
}

function num(v) {
  if (v == null || v === '') return null
  const n = Number(v)
  return Number.isFinite(n) ? n : null
}

// Whole days between two dates, counted by calendar date (UTC, like the database).
export function daysBetween(from, to = new Date()) {
  if (!from) return null
  const a = new Date(from)
  const b = new Date(to)
  const ua = Date.UTC(a.getUTCFullYear(), a.getUTCMonth(), a.getUTCDate())
  const ub = Date.UTC(b.getUTCFullYear(), b.getUTCMonth(), b.getUTCDate())
  return Math.max(0, Math.round((ub - ua) / 86400000))
}

export function shortEngine(e) {
  if (!e) return null
  return String(e).replace(/ - .*/, '').trim() || null
}

export function enrichVehicle(v) {
  const msrp = num(v.msrp)
  const selling = num(v.selling_price)
  const price = selling ?? msrp
  const days = v.is_active === false ? daysBetween(v.first_seen_at, v.last_seen_at) : daysBetween(v.first_seen_at)
  return {
    ...v,
    msrp,
    selling_price: selling,
    price,
    mileage: num(v.mileage),
    year: num(v.year),
    days_on_lot: days,
    age_bucket: ageBucket(days),
    dealer_label: v.dealer_name || v.dealer_key,
    engine_short: shortEngine(v.engine),
    condition: v.condition ? String(v.condition).toLowerCase() : null,
  }
}

// Turn a Supabase error into one of a few problems we can explain in plain English.
export function classifyError(err) {
  const msg = String((err && (err.message || err.error_description)) || err || '')
  const code = err && err.code
  if (/Failed to fetch|NetworkError|fetch failed|Load failed|network/i.test(msg)) return { kind: 'network', message: msg }
  if (/Invalid API key|No API key|JWT|JWS|signature|Unauthorized|invalid.*key/i.test(msg) || code === 'PGRST301' || code === 'PGRST302') {
    return { kind: 'key', message: msg }
  }
  if (code === 'PGRST205' || code === '42P01' || /does not exist|Could not find the (table|relation)|schema cache/i.test(msg)) {
    return { kind: 'no-tables', message: msg }
  }
  if (code === '42501' || /permission denied/i.test(msg)) return { kind: 'permission', message: msg }
  return { kind: 'unknown', message: msg || 'Unknown error' }
}

const DataContext = createContext(null)

export function DataProvider({ config, children }) {
  const [state, setState] = useState({
    status: 'loading', // loading | ready | empty | error
    error: null,
    vehicles: [],
    dealers: [],
    drops: [],
    runs: [],
    loadedAt: null,
  })
  const [refreshing, setRefreshing] = useState(false)
  const inFlight = useRef(false)

  const load = useCallback(async ({ background = false } = {}) => {
    if (inFlight.current) return
    inFlight.current = true
    if (background) setRefreshing(true)
    const sb = getClient(config)
    try {
      const [vehicles, dealers, drops, runsRes] = await Promise.all([
        fetchAll(() => sb.from('vehicles').select(VEHICLE_COLUMNS).eq('is_active', true).order('id')),
        fetchAll(() => sb.from('v_inventory_by_dealer').select('*').order('dealer_key')),
        fetchAll(() => sb.from('v_price_drops').select('*').order('vin').order('dealer_key')),
        sb.from('scraper_runs').select('*').order('started_at', { ascending: false }).limit(10),
      ])
      if (runsRes.error) throw runsRes.error

      const enriched = vehicles.map(enrichVehicle)
      const byKey = new Map(enriched.map(v => [`${v.dealer_key}|${v.vin}`, v]))
      const dropRows = drops.map(d => {
        const live = byKey.get(`${d.dealer_key}|${d.vin}`)
        return {
          ...d,
          original_price: num(d.original_price),
          current_price: num(d.current_price),
          price_drop: num(d.price_drop),
          price_drop_pct: num(d.price_drop_pct),
          dealer_label: d.dealer_name || d.dealer_key,
          condition: live?.condition ?? null,
          exterior_color: live?.exterior_color ?? null,
        }
      })

      setState({
        status: enriched.length ? 'ready' : 'empty',
        error: null,
        vehicles: enriched,
        dealers: dealers.map(d => ({
          ...d,
          active_units: num(d.active_units),
          avg_msrp: num(d.avg_msrp),
          avg_selling_price: num(d.avg_selling_price),
          avg_days_on_lot: num(d.avg_days_on_lot),
        })),
        drops: dropRows,
        runs: runsRes.data || [],
        loadedAt: new Date(),
      })
    } catch (err) {
      const classified = classifyError(err)
      // A failed background refresh keeps the data already on screen.
      setState(prev => (background && (prev.status === 'ready' || prev.status === 'empty'))
        ? prev
        : { ...prev, status: 'error', error: classified })
    } finally {
      inFlight.current = false
      setRefreshing(false)
    }
  }, [config])

  useEffect(() => { load() }, [load])

  useEffect(() => {
    const id = setInterval(() => load({ background: true }), REFRESH_MS)
    return () => clearInterval(id)
  }, [load])

  const own = state.vehicles.filter(v => v.is_own_store)
  const competitors = state.vehicles.filter(v => !v.is_own_store)
  const ownStoreName = own[0]?.dealer_label
    || state.dealers.find(d => d.is_own_store)?.dealer_name
    || ''

  const value = {
    ...state,
    own,
    competitors,
    ownStoreName,
    dealershipName: config.dealershipName || ownStoreName || 'My Dealership',
    refreshing,
    refresh: () => load({ background: true }),
    retry: () => { setState(s => ({ ...s, status: 'loading' })); load() },
    config,
  }

  return <DataContext.Provider value={value}>{children}</DataContext.Provider>
}

export function useData() {
  return useContext(DataContext)
}
