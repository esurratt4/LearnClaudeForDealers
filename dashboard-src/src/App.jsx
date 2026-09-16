// Page map. HashRouter (addresses like http://localhost:8000/#/lot) because the
// simple Python web server cannot route clean URLs back to index.html.
//
//   #/                         Market       your lot vs every competitor
//   #/lot                      My Lot       your own inventory and aging
//   #/price-cuts               Price Cuts   every price drop the scraper has caught
//   #/vehicle/:dealerKey/:vin  one vehicle with its price history

import { Component } from 'react'
import { HashRouter, Navigate, Route, Routes } from 'react-router-dom'
import { readConfig } from './lib/config'
import { DataProvider, useData } from './lib/data'
import { FilterProvider } from './lib/filters'
import Shell from './components/Shell'
import { ConfigProblem, ConnectionProblem, EmptyDatabase, LoadingScreen } from './components/StatusScreens'
import MarketIntel from './pages/MarketIntel'
import LotView from './pages/LotView'
import PriceCuts from './pages/PriceCuts'
import VehicleDetail from './pages/VehicleDetail'

class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }
  static getDerivedStateFromError(error) {
    return { error }
  }
  render() {
    if (this.state.error) {
      return (
        <ConnectionProblem
          error={{ kind: 'unknown', message: String(this.state.error?.message || this.state.error) }}
          retry={() => window.location.reload()}
        />
      )
    }
    return this.props.children
  }
}

function Pages() {
  const { status, error, retry, runs, refresh, refreshing } = useData()
  if (status === 'loading') return <LoadingScreen />
  if (status === 'error') return <ConnectionProblem error={error} retry={retry} />
  if (status === 'empty') return <EmptyDatabase runs={runs} refresh={refresh} refreshing={refreshing} />
  return (
    <ErrorBoundary>
      <Routes>
        <Route path="/" element={<MarketIntel />} />
        <Route path="/lot" element={<LotView />} />
        <Route path="/price-cuts" element={<PriceCuts />} />
        <Route path="/vehicle/:dealerKey/:vin" element={<VehicleDetail />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </ErrorBoundary>
  )
}

export default function App() {
  const config = readConfig()
  if (!config.ok) {
    return (
      <div className="min-h-screen bg-surface">
        <ConfigProblem problem={config} />
      </div>
    )
  }
  return (
    <ErrorBoundary>
      <HashRouter>
        <DataProvider config={config}>
          <FilterProvider>
            <Shell>
              <Pages />
            </Shell>
          </FilterProvider>
        </DataProvider>
      </HashRouter>
    </ErrorBoundary>
  )
}
