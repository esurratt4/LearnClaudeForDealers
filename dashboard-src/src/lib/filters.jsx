// Slice and dice. Every filter pill, every clickable bar and every table on a page
// shares this one set of filters. Filters reset when you switch pages.

import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import { useLocation } from 'react-router-dom'

// key: the filter name, label: what the pill says, get: how to read it off a row
export const FILTER_DEFS = {
  dealer: { label: 'Dealer', get: v => v.dealer_label },
  condition: { label: 'New / Used', get: v => (v.condition ? v.condition[0].toUpperCase() + v.condition.slice(1) : null) },
  make: { label: 'Make', get: v => v.make },
  model: { label: 'Model', get: v => v.model },
  trim: { label: 'Trim', get: v => v.trim },
  bodyType: { label: 'Body', get: v => v.body_type },
  exteriorColor: { label: 'Ext Color', get: v => v.exterior_color },
  interiorColor: { label: 'Int Color', get: v => v.interior_color },
  engine: { label: 'Engine', get: v => v.engine_short },
  drivetrain: { label: 'Drivetrain', get: v => v.drivetrain },
  ageBucket: { label: 'Age', get: v => (v.age_bucket ? `${v.age_bucket} days` : null) },
}

const emptyFilters = () => Object.fromEntries(Object.keys(FILTER_DEFS).map(k => [k, []]))

// Apply the filters to a list of rows. `skip` lists filter keys to ignore
// (for example, the Dealer filter should not hide your own store's cars).
export function applyFilters(rows, filters, skip = []) {
  let out = rows
  for (const [key, selected] of Object.entries(filters)) {
    if (!selected?.length || skip.includes(key) || !FILTER_DEFS[key]) continue
    const get = FILTER_DEFS[key].get
    out = out.filter(v => selected.includes(get(v)))
  }
  return out
}

const FilterContext = createContext(null)

export function FilterProvider({ children }) {
  const [filters, setFilters] = useState(emptyFilters)

  const toggleFilter = useCallback((key, value) => {
    if (value == null || value === '' || value === 'Unknown') return
    setFilters(prev => {
      const arr = prev[key] || []
      return { ...prev, [key]: arr.includes(value) ? arr.filter(v => v !== value) : [...arr, value] }
    })
  }, [])

  const removeFilter = useCallback((key, value) => {
    setFilters(prev => ({ ...prev, [key]: (prev[key] || []).filter(v => v !== value) }))
  }, [])

  const clearAll = useCallback(() => setFilters(emptyFilters()), [])

  const { pathname } = useLocation()
  const prevPath = useRef(pathname)
  useEffect(() => {
    if (pathname !== prevPath.current) {
      prevPath.current = pathname
      setFilters(emptyFilters())
    }
  }, [pathname])

  const activeChips = []
  for (const [key, vals] of Object.entries(filters)) {
    for (const v of vals) activeChips.push({ key, value: v, label: `${FILTER_DEFS[key].label}: ${v}` })
  }

  return (
    <FilterContext.Provider value={{ filters, toggleFilter, removeFilter, clearAll, activeChips }}>
      {children}
    </FilterContext.Provider>
  )
}

export function useFilters() {
  return useContext(FilterContext)
}
