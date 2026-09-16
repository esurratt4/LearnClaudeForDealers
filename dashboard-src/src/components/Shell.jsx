import { useEffect } from 'react'
import { NavLink } from 'react-router-dom'
import { Car, Globe, RefreshCw, TrendingDown } from 'lucide-react'
import { useData } from '../lib/data'
import { fmtAgo } from '../lib/format'

const NAV = [
  { to: '/', label: 'Market', icon: Globe, end: true },
  { to: '/lot', label: 'My Lot', icon: Car },
  { to: '/price-cuts', label: 'Price Cuts', icon: TrendingDown },
]

export default function Shell({ children }) {
  const { dealershipName, loadedAt, refresh, refreshing, dealers, status } = useData()

  useEffect(() => {
    document.title = `${dealershipName} | Market Dashboard`
  }, [dealershipName])

  const lastScraped = dealers.reduce((max, d) => (d.last_scraped_at && d.last_scraped_at > max ? d.last_scraped_at : max), '')
  const showNav = status === 'ready'

  return (
    <div className="min-h-screen bg-surface">
      <header className="sticky top-0 z-40 border-b border-zinc-300/60 bg-frame">
        <div className="mx-auto flex max-w-[1600px] flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3 lg:px-6">
          <div className="flex min-w-0 items-center gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-home text-white">
              <svg viewBox="0 0 24 24" className="h-6 w-6" fill="currentColor" aria-hidden="true">
                <rect x="3" y="12" width="4" height="9" rx="1" /><rect x="10" y="7" width="4" height="14" rx="1" /><rect x="17" y="3" width="4" height="18" rx="1" />
              </svg>
            </div>
            <div className="min-w-0">
              <p className="truncate text-xl font-bold leading-tight tracking-tight text-zinc-900 md:text-2xl">{dealershipName}</p>
              <p className="text-sm text-zinc-600">Market dashboard</p>
            </div>
          </div>

          {showNav && (
            <nav className="flex items-center gap-1">
              {NAV.map(({ to, label, icon: Icon, end }) => (
                <NavLink
                  key={to}
                  to={to}
                  end={end}
                  className={({ isActive }) =>
                    `flex items-center gap-2 rounded-lg px-3.5 py-2 text-base font-medium transition-colors ${
                      isActive ? 'bg-white text-zinc-900 shadow-sm' : 'text-zinc-600 hover:bg-white/50 hover:text-zinc-900'
                    }`
                  }
                >
                  <Icon className="h-4 w-4" />
                  {label}
                </NavLink>
              ))}
            </nav>
          )}

          <div className="ml-auto flex items-center gap-3">
            {lastScraped && (
              <span className="hidden text-sm text-zinc-600 md:inline">
                Last scrape <b className="font-semibold text-zinc-800">{fmtAgo(lastScraped)}</b>
              </span>
            )}
            {loadedAt && (
              <button
                onClick={refresh}
                disabled={refreshing}
                title={`Data loaded ${fmtAgo(loadedAt)}. Refreshes itself every 5 minutes.`}
                className="flex items-center gap-2 rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm font-medium text-zinc-700 hover:bg-zinc-50 disabled:opacity-60"
              >
                <RefreshCw className={`h-4 w-4 ${refreshing ? 'animate-spin' : ''}`} />
                Refresh
              </button>
            )}
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1600px] px-4 py-6 lg:px-6">{children}</main>

      <footer className="mx-auto max-w-[1600px] px-4 pb-8 text-sm text-zinc-400 lg:px-6">
        Read-only view of your Supabase database. Nothing on this page can change your data.
      </footer>
    </div>
  )
}
