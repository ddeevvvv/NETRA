import { useState, useEffect, useCallback } from 'react'
import CameraGrid from './components/CameraGrid'
import AlertPanel from './components/AlertPanel'
import HealthStrip from './components/HealthStrip'
import InvestigateView from './components/InvestigateView'
import ANPRPanel from './components/ANPRPanel'
import ZonesList from './components/ZonesList'
import StatsStrip from './components/StatsStrip'
import { getCameras, getCameraHealth } from './api'
import { ShieldCheck, LayoutDashboard, Search } from 'lucide-react'
import './index.css'

const VIEWS = {
  dashboard: { label: 'Dashboard', icon: LayoutDashboard },
  investigate: { label: 'Investigate', icon: Search },
}

export default function App() {
  const [view, setView] = useState('dashboard')
  const [cameras, setCameras] = useState([])
  const [healthMap, setHealthMap] = useState({})
  // Stats strip state — fed from child component callbacks
  const [alertStats, setAlertStats] = useState({ alerts: [], unackedCount: 0 })
  const [zoneCount, setZoneCount] = useState(0)

  const handleAlertStats = useCallback((alerts, unackedCount) => {
    setAlertStats({ alerts, unackedCount })
  }, [])

  const handleZoneCount = useCallback((count) => {
    setZoneCount(count)
  }, [])

  // Load camera list on startup
  useEffect(() => {
    getCameras()
      .then(setCameras)
      .catch((e) => console.error('Failed to load cameras:', e))
  }, [])

  // Single consolidated health polling source — runs every 10 seconds
  const refreshHealth = useCallback(async () => {
    if (!cameras.length) return
    const results = await Promise.allSettled(
      cameras.map((c) => getCameraHealth(c.id).then((h) => ({ id: c.id, h })))
    )
    const map = {}
    results.forEach((r) => {
      if (r.status === 'fulfilled') map[r.value.id] = r.value.h
    })
    setHealthMap(map)
  }, [cameras])

  useEffect(() => {
    if (!cameras.length) return
    refreshHealth()
    const t = setInterval(refreshHealth, 10_000)
    return () => clearInterval(t)
  }, [cameras, refreshHealth])

  return (
    <div className="app">
      {/* ── Top Header Bar ── */}
      <header className="header">
        <div className="header-logo">
          <ShieldCheck size={20} className="logo-shield" />
          <span>NETRA</span>
        </div>
        <div className="header-sub">
          Intelligent Border Video Analytics Platform · IBVAP · SIH 2026
        </div>
        <nav className="header-nav">
          {Object.entries(VIEWS).map(([key, config]) => {
            const Icon = config.icon
            return (
              <button
                key={key}
                id={`nav-${key}`}
                className={`nav-btn ${view === key ? 'active' : ''}`}
                onClick={() => setView(key)}
              >
                <Icon size={14} />
                <span>{config.label}</span>
              </button>
            )
          })}
        </nav>
      </header>

      {/* ── Stats Strip — summary metrics row ── */}
      {view === 'dashboard' && (
        <StatsStrip
          cameras={cameras}
          healthMap={healthMap}
          alerts={alertStats.alerts}
          unackedCount={alertStats.unackedCount}
          zoneCount={zoneCount}
        />
      )}

      {/* ── Main Workspace ── */}
      <div className="main-content">
        {view === 'dashboard' && (
          <>
            {/* Left Column: Feeds, Analytics & Health */}
            <div className="camera-section">
              <div className="camera-top-bar">
                <span className="section-title">
                  Camera Feeds · {cameras.length} registered
                </span>
              </div>

              <div className="camera-scroll-area">
                <CameraGrid cameras={cameras} healthMap={healthMap} />

                {/* Sub-panels for Active Zones & ANPR Activity */}
                <div className="dashboard-analytics-row">
                  <ZonesList cameras={cameras} onZoneCount={handleZoneCount} />

                  <ANPRPanel cameras={cameras} />
                </div>
              </div>

              {/* Consolidated Health Strip pinned at bottom */}
              <HealthStrip cameras={cameras} healthMap={healthMap} />
            </div>

            {/* Right Column: Real-time Alert Feed */}
            <div className="alert-section">
              <AlertPanel onStatsUpdate={handleAlertStats} />
            </div>
          </>
        )}

        {view === 'investigate' && <InvestigateView cameras={cameras} />}
      </div>
    </div>
  )
}
