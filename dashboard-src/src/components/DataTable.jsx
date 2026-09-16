// A searchable, sortable, paged table with CSV export. Used for every vehicle list.
//
// columns: [{ key, label, align, render(row), sortValue(row), csv(row), className }]

import { useEffect, useMemo, useState } from 'react'
import { ChevronDown, ChevronUp, Download, Search } from 'lucide-react'
import { downloadCSV } from '../lib/format'

export default function DataTable({
  rows,
  columns,
  searchKeys = [],
  searchPlaceholder = 'Search...',
  defaultSort,
  defaultDir = 'asc',
  exportName,
  pageSize = 50,
  emptyMessage = 'No vehicles match these filters.',
  maxHeight = 560,
}) {
  const [search, setSearch] = useState('')
  const [sortKey, setSortKey] = useState(defaultSort || columns[0].key)
  const [sortDir, setSortDir] = useState(defaultDir)
  const [page, setPage] = useState(0)

  useEffect(() => { setPage(0) }, [rows])

  const sorted = useMemo(() => {
    const q = search.trim().toLowerCase()
    let result = rows
    if (q) {
      result = rows.filter(r => searchKeys.some(k => String(r[k] ?? '').toLowerCase().includes(q)))
    }
    const col = columns.find(c => c.key === sortKey)
    const get = col?.sortValue || (r => r[sortKey])
    return [...result].sort((a, b) => {
      const av = get(a)
      const bv = get(b)
      // Blanks always sink to the bottom
      if (av == null || av === '') return 1
      if (bv == null || bv === '') return -1
      if (typeof av === 'number' && typeof bv === 'number') return sortDir === 'asc' ? av - bv : bv - av
      return sortDir === 'asc' ? String(av).localeCompare(String(bv)) : String(bv).localeCompare(String(av))
    })
  }, [rows, search, searchKeys, columns, sortKey, sortDir])

  const totalPages = Math.max(1, Math.ceil(sorted.length / pageSize))
  const pageRows = sorted.slice(page * pageSize, (page + 1) * pageSize)

  const toggleSort = (key) => {
    if (sortKey === key) setSortDir(d => (d === 'asc' ? 'desc' : 'asc'))
    else {
      setSortKey(key)
      const sample = rows.find(r => r[key] != null)
      setSortDir(sample && typeof sample[key] === 'number' ? 'desc' : 'asc')
    }
    setPage(0)
  }

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-3">
        {searchKeys.length > 0 && (
          <div className="relative min-w-[220px] flex-1">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-400" />
            <input
              type="text"
              value={search}
              onChange={e => { setSearch(e.target.value); setPage(0) }}
              placeholder={searchPlaceholder}
              className="w-full rounded-lg border border-zinc-200 bg-zinc-50 py-2 pl-9 pr-3 text-base text-zinc-700 placeholder:text-zinc-400 focus:border-accent focus:bg-white focus:outline-none"
            />
          </div>
        )}
        <span className="text-sm tabular-nums text-zinc-500">{sorted.length.toLocaleString()} {sorted.length === 1 ? 'row' : 'rows'}</span>
        {exportName && (
          <button
            onClick={() => downloadCSV(`${exportName}-${new Date().toISOString().slice(0, 10)}.csv`, columns.filter(c => c.csv !== false), sorted)}
            className="flex items-center gap-1.5 rounded-lg border border-zinc-200 bg-white px-3 py-2 text-sm font-medium text-zinc-600 hover:bg-zinc-50"
          >
            <Download className="h-4 w-4" />
            Export CSV
          </button>
        )}
      </div>
      <div className="overflow-auto rounded-xl border border-zinc-200" style={{ maxHeight }}>
        <table className="w-full text-sm">
          <thead className="sticky top-0 z-10 bg-zinc-50 text-left">
            <tr>
              {columns.map(col => (
                <th
                  key={col.key}
                  onClick={() => col.sortable !== false && toggleSort(col.key)}
                  className={`whitespace-nowrap px-3 py-2.5 text-xs font-semibold uppercase tracking-wider text-zinc-500 ${col.sortable !== false ? 'cursor-pointer hover:text-zinc-800' : ''} ${col.align === 'right' ? 'text-right' : ''}`}
                >
                  {col.label}
                  {sortKey === col.key && (sortDir === 'asc'
                    ? <ChevronUp className="ml-0.5 inline h-3.5 w-3.5" />
                    : <ChevronDown className="ml-0.5 inline h-3.5 w-3.5" />)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {pageRows.map((r, i) => (
              <tr key={r.id ?? `${r.dealer_key}-${r.vin}-${i}`} className={`border-t border-zinc-100 hover:bg-amber-50/40 ${i % 2 ? 'bg-zinc-50/40' : 'bg-white'}`}>
                {columns.map(col => (
                  <td key={col.key} className={`whitespace-nowrap px-3 py-2 tabular-nums text-zinc-700 ${col.align === 'right' ? 'text-right' : ''} ${col.className || ''}`}>
                    {col.render ? col.render(r) : (r[col.key] ?? '--')}
                  </td>
                ))}
              </tr>
            ))}
            {pageRows.length === 0 && (
              <tr><td colSpan={columns.length} className="px-3 py-8 text-center text-base text-zinc-500">{emptyMessage}</td></tr>
            )}
          </tbody>
        </table>
      </div>
      {totalPages > 1 && (
        <div className="mt-3 flex items-center justify-between text-sm text-zinc-500">
          <span className="tabular-nums">Page {page + 1} of {totalPages}</span>
          <div className="flex gap-2">
            <button disabled={page === 0} onClick={() => setPage(p => p - 1)} className="rounded-lg border border-zinc-200 px-4 py-2 font-medium hover:bg-zinc-50 disabled:opacity-30">Prev</button>
            <button disabled={page >= totalPages - 1} onClick={() => setPage(p => p + 1)} className="rounded-lg border border-zinc-200 px-4 py-2 font-medium hover:bg-zinc-50 disabled:opacity-30">Next</button>
          </div>
        </div>
      )}
    </div>
  )
}
