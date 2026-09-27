import { useState, useEffect, useCallback, useRef } from 'react'
import CameraGrid from './components/CameraGrid'
import AlertPanel from './components/AlertPanel'
import HealthStrip from './components/HealthStrip'
import InvestigateView from './components/InvestigateView'
import ANPRPanel from './components/ANPRPanel'
import ZonesList from './components/ZonesList'
import StatsStrip from './components/StatsStrip'
import MapView from './components/MapView'
import FacesView from './components/FacesView'
import { getCameras, getCameraHealth, getSitesStatus } from './api'
import { ShieldCheck, LayoutDashboard, MapPin, Search, User } from 'lucide-react'
import './index.css'

const VIEWS = {
  dashboard: { label: 'Dashboard', icon: LayoutDashboard },
  map: { label: 'Site Map', icon: MapPin },
  investigate: { label: 'Investigate', icon: Search },
  faces: { label: 'Faces', icon: User },
}

export default function App() {
  const [view, setView] = useState(() => {
    const p = typeof window !== 'undefined' ? new URLSearchParams(window.location.search).get('view') : null
    return (p && VIEWS[p]) ? p : 'dashboard'
  })
  const [cameras, setCameras] = useState([])
  const [healthMap, setHealthMap] = useState({})
  // Stats strip state — fed from child component callbacks
  // alerts list comes from AlertPanel (WS stream), unackedCount from DB-authoritative sites/status
  const [alertList, setAlertList] = useState([])
  const [unackedCount, setUnackedCount] = useState(0)
  const [zoneCount, setZoneCount] = useState(0)
  const [zoneVersion, setZoneVersion] = useState(0)
  const [trackPlateTarget, setTrackPlateTarget] = useState(() => {
    return typeof window !== 'undefined' ? (new URLSearchParams(window.location.search).get('plate') || '') : ''
  })

  const highlightTimersRef = useRef({})
  const [alertHighlightMap, setAlertHighlightMap] = useState({})
  const [drawTarget, setDrawTarget] = useState(null)

  const handleTrackPlate = useCallback((plate) => {
    setTrackPlateTarget(plate)
    setView('investigate')
  }, [])

  // AlertPanel callback — only use the alerts list for today-count display.
  // unackedCount is managed separately via sites/status so it matches the Map.
  const handleAlertStats = useCallback((alerts) => {
    setAlertList(alerts)
  }, [])

  const handleNewAlert = useCallback((alert) => {
    // Live increment for actionable alerts requiring operator acknowledgment
    if (alert.requires_acknowledgment !== false && !alert.acknowledged) {
      setUnackedCount((c) => c + 1)
    }

    const camId = alert.camera_id
    if (!camId) return

    const highlight = {
      severity: alert.severity || 'HIGH',
      type: alert.type || 'ALERT',
      timestamp: Date.now(),
    }

    setAlertHighlightMap((prev) => ({
      ...prev,
      [camId]: highlight,
    }))

    if (highlightTimersRef.current[camId]) {
      clearTimeout(highlightTimersRef.current[camId])
    }

    highlightTimersRef.current[camId] = setTimeout(() => {
      setAlertHighlightMap((prev) => {
        const next = { ...prev }
        delete next[camId]
        return next
      })
      delete highlightTimersRef.current[camId]
    }, 5000)
  }, [])

  const handleZoneCount = useCallback((count) => {
    setZoneCount(count)
  }, [])

  const handleZoneChange = useCallback(() => {
    setZoneVersion((v) => v + 1)
  }, [])

  // Load camera list on startup
  useEffect(() => {
    getCameras()
      .then(setCameras)
      .catch((e) => console.error('Failed to load cameras:', e))
  }, [])

  // ── Authoritative unacked counter — sourced from sites/status (same as Map view) ──
  // Fetched immediately on mount, then reconciled every 5 s so the Dashboard counter
  // always agrees with the Map pins even after bulk-acks, second-tab actions, or
  // missed WS frames. WS events still provide live +1/-1 increments between polls.
  const refreshUnackedCount = useCallback(async () => {
    try {
      const sites = await getSitesStatus()
      const total = sites.reduce((sum, s) => sum + (s.unacked_alert_count ?? 0), 0)
      setUnackedCount(total)
    } catch (e) {
      console.error('Failed to refresh unacked count:', e)
    }
  }, [])

  const handleAcknowledge = useCallback((count = 1) => {
    setUnackedCount((c) => Math.max(0, c - count))
    refreshUnackedCount()
  }, [refreshUnackedCount])

  useEffect(() => {
    refreshUnackedCount()                            // seed immediately on mount
    const t = setInterval(refreshUnackedCount, 5000) // reconcile every 5 s (matches Map)
    return () => clearInterval(t)
  }, [refreshUnackedCount])

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
          alerts={alertList}
          unackedCount={unackedCount}
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
                <CameraGrid
                  cameras={cameras}
                  healthMap={healthMap}
                  alertHighlightMap={alertHighlightMap}
                  drawTarget={drawTarget}
                  onClearDrawTarget={() => setDrawTarget(null)}
                  onZoneChange={handleZoneChange}
                />

                {/* Sub-panels for Active Zones & ANPR Activity */}
                <div className="dashboard-analytics-row">
                  <ZonesList
                    cameras={cameras}
                    zoneVersion={zoneVersion}
                    onZoneCount={handleZoneCount}
                    onZoneChange={handleZoneChange}
                    onStartRedraw={(target) => setDrawTarget(target)}
                  />

                  <ANPRPanel cameras={cameras} />
                </div>
              </div>

              {/* Consolidated Health Strip pinned at bottom */}
              <HealthStrip cameras={cameras} healthMap={healthMap} />
            </div>

            {/* Right Column: Real-time Alert Feed */}
            <div className="alert-section">
              <AlertPanel
                onStatsUpdate={handleAlertStats}
                onNewAlert={handleNewAlert}
                onTrackPlate={handleTrackPlate}
                onAcknowledge={handleAcknowledge}
              />
            </div>
          </>
        )}

        {view === 'map' && (
          <MapView onNavigateToDashboard={() => setView('dashboard')} />
        )}

        {view === 'investigate' && (
          <InvestigateView cameras={cameras} initialPlate={trackPlateTarget} />
        )}

        {view === 'faces' && (
          <FacesView />
        )}
      </div>
    </div>
  )
}
