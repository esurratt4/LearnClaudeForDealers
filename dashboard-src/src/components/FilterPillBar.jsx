import { useEffect, useMemo, useRef, useState } from 'react'
import { ChevronDown, Search, X } from 'lucide-react'
import { FILTER_DEFS, applyFilters, useFilters } from '../lib/filters'

function PillDropdown({ label, options, selected, onToggle }) {
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')
  const inputRef = useRef(null)

  useEffect(() => {
    if (open && inputRef.current) inputRef.current.focus()
    if (!open) return
    const onKey = e => { if (e.key === 'Escape') { setOpen(false); setSearch('') } }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open])

  const shown = useMemo(() => {
    let items = [...options]
    if (search) {
      const q = search.toLowerCase()
      items = items.filter(o => o.value.toLowerCase().includes(q))
    }
    items.sort((a, b) => {
      const aS = selected.includes(a.value) ? 0 : 1
      const bS = selected.includes(b.value) ? 0 : 1
      if (aS !== bS) return aS - bS
      return b.count - a.count
    })
    return items
  }, [options, search, selected])

  const count = selected.length

  return (
    <div className="relative">
      <button
        onClick={() => setOpen(!open)}
        className={`flex items-center gap-1.5 rounded-lg border px-3.5 py-2 text-sm font-medium transition-colors ${
          count > 0 ? 'border-accent/40 bg-accent/5 text-accent' : 'border-zinc-200 bg-white text-zinc-700 hover:border-zinc-300'
        }`}
      >
        {label}
        {count > 0 && (
          <span className="flex h-5 min-w-5 items-center justify-center rounded-full bg-accent px-1 text-xs font-semibold text-white">{count}</span>
        )}
        <ChevronDown className={`h-4 w-4 transition-transform ${open ? 'rotate-180' : ''} ${count > 0 ? 'text-accent' : 'text-zinc-400'}`} />
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => { setOpen(false); setSearch('') }} />
          <div className="absolute left-0 top-full z-50 mt-1 w-72 rounded-xl border border-zinc-200 bg-white shadow-xl">
            <div className="p-2">
              <div className="relative">
                <Search className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-400" />
                <input
                  ref={inputRef}
                  type="text"
                  value={search}
                  onChange={e => setSearch(e.target.value)}
                  placeholder={`Search ${label.toLowerCase()}...`}
                  className="w-full rounded-md border border-zinc-200 bg-zinc-50 py-2 pl-8 pr-3 text-sm text-zinc-700 placeholder:text-zinc-400 focus:border-accent focus:bg-white focus:outline-none"
                />
              </div>
            </div>
            <div className="max-h-72 overflow-y-auto px-1 pb-2">
              {shown.map(opt => {
                const isSelected = selected.includes(opt.value)
                return (
                  <label
                    key={opt.value}
                    className={`flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 text-sm hover:bg-zinc-50 ${isSelected ? 'font-semibold text-zinc-900' : 'text-zinc-700'}`}
                  >
                    <input type="checkbox" checked={isSelected} onChange={() => onToggle(opt.value)} className="h-4 w-4 accent-[#C2692A]" />
                    <span className="flex-1 truncate" title={opt.value}>{opt.value}</span>
                    <span className="shrink-0 text-xs tabular-nums text-zinc-500">{opt.count}</span>
                  </label>
                )
              })}
              {shown.length === 0 && <p className="px-2 py-3 text-center text-sm text-zinc-500">No matches</p>}
            </div>
          </div>
        </>
      )}
    </div>
  )
}

// keys: which filters to offer on this page, in order.
// optionSource: optional per-key override of which rows the options are counted from.
export default function FilterPillBar({ vehicles, keys, optionSource = {} }) {
  const { filters, toggleFilter, removeFilter, clearAll, activeChips } = useFilters()

  // Options for each pill respect every OTHER active filter, so choosing a Make
  // narrows the Model list to that make.
  const options = useMemo(() => {
    const out = {}
    for (const key of keys) {
      const rows = applyFilters(optionSource[key] || vehicles, filters, [key])
      const counts = {}
      for (const v of rows) {
        const val = FILTER_DEFS[key].get(v)
        if (val != null && val !== '') counts[val] = (counts[val] || 0) + 1
      }
      out[key] = Object.entries(counts).map(([value, count]) => ({ value, count }))
    }
    return out
  }, [vehicles, keys, filters, optionSource])

  return (
    <div className="animate-fade-in relative z-30 space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        {keys.map(key => {
          const selected = filters[key] || []
          // A pill with a single choice and nothing selected is just noise.
          if ((options[key]?.length || 0) <= 1 && selected.length === 0) return null
          return (
            <PillDropdown
              key={key}
              label={FILTER_DEFS[key].label}
              options={options[key] || []}
              selected={selected}
              onToggle={v => toggleFilter(key, v)}
            />
          )
        })}
        {activeChips.length > 0 && (
          <button
            onClick={clearAll}
            className="rounded-lg border border-zinc-200 bg-white px-3.5 py-2 text-sm font-medium text-zinc-600 hover:border-red-200 hover:bg-red-50 hover:text-red-600"
          >
            Clear all
          </button>
        )}
      </div>
      {activeChips.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs font-semibold uppercase tracking-wider text-zinc-500">Showing only</span>
          {activeChips.map(chip => (
            <button
              key={`${chip.key}-${chip.value}`}
              onClick={() => removeFilter(chip.key, chip.value)}
              className="animate-chip-enter flex items-center gap-1 rounded-full bg-zinc-800 px-3 py-1 text-sm font-medium text-white hover:bg-red-600"
            >
              {chip.label}
              <X className="h-3.5 w-3.5" />
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
