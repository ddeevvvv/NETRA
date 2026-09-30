import { useState, useEffect, useCallback, useRef } from 'react'
import CameraGrid from './components/CameraGrid'
import AlertPanel from './components/AlertPanel'
import HealthStrip from './components/HealthStrip'
import InvestigateView from './components/InvestigateView'
import StatsStrip from './components/StatsStrip'
import MapView from './components/MapView'
import { getCameras, getCameraHealth, getAllCameraHealth, getSitesStatus } from './api'
import { ShieldCheck, LayoutDashboard, MapPin, Search } from 'lucide-react'
import './index.css'

const VIEWS = {
  dashboard: { label: 'Dashboard', icon: LayoutDashboard },
  map: { label: 'Site Map', icon: MapPin },
  investigate: { label: 'Investigate', icon: Search },
}

export default function App() {
  const [view, setView] = useState(() => {
    const p = typeof window !== 'undefined' ? new URLSearchParams(window.location.search).get('view') : null
    if (p === 'faces') return 'investigate'
    return (p && VIEWS[p]) ? p : 'dashboard'
  })
  const [initialInvestigateTab, setInitialInvestigateTab] = useState(() => {
    if (typeof window === 'undefined') return ''
    const params = new URLSearchParams(window.location.search)
    if (params.get('view') === 'faces') return 'faces'
    return params.get('tab') || ''
  })
  const [cameras, setCameras] = useState([])
  const [healthMap, setHealthMap] = useState({})
  // Stats strip state — fed from child component callbacks
  // alerts list comes from AlertPanel (WS stream), unackedCount from DB-authoritative sites/status
  const [alertList, setAlertList] = useState([])
  const [unackedCount, setUnackedCount] = useState(0)
  const [trackPlateTarget, setTrackPlateTarget] = useState(() => {
    return typeof window !== 'undefined' ? (new URLSearchParams(window.location.search).get('plate') || '') : ''
  })

  const highlightTimersRef = useRef({})
  const [alertHighlightMap, setAlertHighlightMap] = useState({})

  const handleViewChange = useCallback((newView) => {
    setView(newView)
    if (typeof window !== 'undefined') {
      const url = new URL(window.location.href)
      if (newView === 'dashboard') {
        url.searchParams.delete('view')
      } else {
        url.searchParams.set('view', newView)
      }
      window.history.replaceState({}, '', url.toString())
    }
  }, [])

  const handleTrackPlate = useCallback((plate) => {
    setTrackPlateTarget(plate)
    handleViewChange('investigate')
  }, [handleViewChange])

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

    // Real-time camera health synchronization from WebSocket alerts
    if (alert.type === 'CAMERA_HEALTH') {
      const meta = alert.metadata || alert.event_metadata || {}
      const condition = meta.condition || ''
      const isOffline = condition === 'OFFLINE' || condition === 'DISCONNECTED'
      const isFrozen = condition === 'FROZEN'
      const isLowFps = condition === 'LOW_FPS'
      const isDegraded = isFrozen || isLowFps || condition === 'DEGRADED'

      setHealthMap((prev) => {
        const existing = prev[camId] || {
          camera_id: camId,
          is_connected: true,
          connection_state: 'ONLINE',
          measured_fps: meta.measured_fps ?? 0,
        }
        return {
          ...prev,
          [camId]: {
            ...existing,
            is_connected: !isOffline,
            is_frozen: isFrozen,
            is_low_fps: isLowFps,
            connection_state: isOffline ? 'OFFLINE' : isDegraded ? 'DEGRADED' : 'ONLINE',
            measured_fps: meta.measured_fps ?? existing.measured_fps,
            last_seen_at: alert.timestamp || new Date().toISOString(),
          },
        }
      })
    }

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



  // Load camera list & initial health on startup
  useEffect(() => {
    getCameras()
      .then((cams) => {
        setCameras(cams)
        getAllCameraHealth()
          .then((map) => {
            if (map && typeof map === 'object') setHealthMap(map)
          })
          .catch((e) => console.error('Failed to load initial health:', e))
      })
      .catch((e) => console.error('Failed to load cameras:', e))
  }, [])

  // ── Authoritative unacked counter — sourced from sites/status (same as Map view) ──
  // Only polls on dashboard view (map view has its own poller). Uses AbortController
  // to cancel stale in-flight requests and prevent connection pile-up.
  const unackedAbortRef = useRef(null)
  const refreshUnackedCount = useCallback(async () => {
    // Skip when MapView is active — it has its own sites/status poll
    if (view === 'map') return
    if (unackedAbortRef.current) unackedAbortRef.current.abort()
    const ac = new AbortController()
    unackedAbortRef.current = ac
    try {
      const res = await fetch('/api/v1/sites/status', { signal: ac.signal })
      if (!res.ok) throw new Error(`status ${res.status}`)
      const sites = await res.json()
      const total = sites.reduce((sum, s) => sum + (s.unacked_alert_count ?? 0), 0)
      setUnackedCount(total)
    } catch (e) {
      if (e.name === 'AbortError') return
      console.error('Failed to refresh unacked count:', e)
    }
  }, [view])

  const handleAcknowledge = useCallback((count = 1) => {
    setUnackedCount((c) => Math.max(0, c - count))
    refreshUnackedCount()
  }, [refreshUnackedCount])

  useEffect(() => {
    refreshUnackedCount()
    const t = setInterval(refreshUnackedCount, 5000)
    return () => {
      clearInterval(t)
      if (unackedAbortRef.current) unackedAbortRef.current.abort()
    }
  }, [refreshUnackedCount])

  // Single consolidated health polling source — runs every 10 seconds.
  // Only active on dashboard view. Uses AbortController to prevent pile-up.
  const healthAbortRef = useRef(null)
  const refreshHealth = useCallback(async () => {
    if (!cameras.length) return
    // Only poll health when dashboard is visible — other views don't render camera feeds
    if (view !== 'dashboard') return
    if (healthAbortRef.current) healthAbortRef.current.abort()
    const ac = new AbortController()
    healthAbortRef.current = ac
    try {
      const res = await fetch('/api/v1/cameras/health-all', { signal: ac.signal })
      if (!res.ok) throw new Error(`status ${res.status}`)
      const allHealth = await res.json()
      if (allHealth && typeof allHealth === 'object' && Object.keys(allHealth).length > 0) {
        setHealthMap(allHealth)
        return
      }
    } catch (e) {
      if (e.name === 'AbortError') return
      console.warn('getAllCameraHealth failed, falling back:', e)
    }

    try {
      const results = await Promise.allSettled(
        cameras.map((c) =>
          fetch(`/api/v1/cameras/${c.id}/health`, { signal: ac.signal })
            .then((r) => r.json())
            .then((h) => ({ id: c.id, h }))
        )
      )
      const map = {}
      results.forEach((r) => {
        if (r.status === 'fulfilled') {
          map[r.value.id] = r.value.h
        }
      })
      if (Object.keys(map).length > 0) {
        setHealthMap(map)
      }
    } catch (e) {
      if (e.name === 'AbortError') return
    }
  }, [cameras, view])

  useEffect(() => {
    if (!cameras.length) return
    refreshHealth()
    const t = setInterval(refreshHealth, 10_000)
    return () => {
      clearInterval(t)
      if (healthAbortRef.current) healthAbortRef.current.abort()
    }
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
                onClick={() => handleViewChange(key)}
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
                />
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
          <MapView onNavigateToDashboard={() => handleViewChange('dashboard')} />
        )}

        {view === 'investigate' && (
          <InvestigateView
            cameras={cameras}
            initialPlate={trackPlateTarget}
            initialTab={initialInvestigateTab}
          />
        )}
      </div>
    </div>
  )
}
