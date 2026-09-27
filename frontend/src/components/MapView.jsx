import { useState, useEffect, useCallback } from 'react'
import { getSitesStatus, acknowledgeBulkEvents } from '../api'
import {
  MapPin,
  ShieldAlert,
  ShieldCheck,
  Camera,
  Activity,
  AlertTriangle,
  AlertOctagon,
  RefreshCw,
  ExternalLink,
  ChevronRight,
  Info,
  Radio,
  Trash2,
} from 'lucide-react'

/**
 * MapView — Tactical Schematic Site Map & Situational Awareness View.
 * Displays schematic Border Outpost (BOP) locations, camera connectivity,
 * and live active alert status indicators.
 */
export default function MapView({ onNavigateToDashboard }) {
  const [sites, setSites] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [selectedSite, setSelectedSite] = useState(null)
  const [lastRefreshed, setLastRefreshed] = useState(null)
  const [clearingSite, setClearingSite] = useState(false)
  const [confirmClearSite, setConfirmClearSite] = useState(false)

  const fetchSites = useCallback(async () => {
    try {
      setError(null)
      const data = await getSitesStatus()
      setSites(data || [])
      setLastRefreshed(new Date())

      // Maintain selection if currently selected
      if (selectedSite) {
        const updated = data.find((s) => s.id === selectedSite.id)
        if (updated) setSelectedSite(updated)
      }
    } catch (err) {
      console.error('Failed to load sites status:', err)
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [selectedSite])

  useEffect(() => {
    fetchSites()
    const timer = setInterval(fetchSites, 5000)
    return () => clearInterval(timer)
  }, [fetchSites])

  const handleClearSiteAlerts = async () => {
    if (!selectedSite) return
    if (!confirmClearSite) {
      setConfirmClearSite(true)
      setTimeout(() => setConfirmClearSite(false), 3000)
      return
    }
    setClearingSite(true)
    setConfirmClearSite(false)
    try {
      await acknowledgeBulkEvents({ site_id: selectedSite.id })
      // Refresh so counts update
      await fetchSites()
    } catch (err) {
      console.error('Clear site alerts failed:', err)
    } finally {
      setClearingSite(false)
    }
  }

  // Summary counts
  const totalSites = sites.length
  const alertSites = sites.filter((s) => s.highest_alert_severity !== 'NONE').length
  const offlineSites = sites.filter((s) => s.offline_count > 0).length
  const healthySites = sites.filter(
    (s) => s.status === 'HEALTHY' || (s.offline_count === 0 && s.highest_alert_severity === 'NONE')
  ).length

  return (
    <div className="map-view-container">
      {/* ── Top Summary & Filter Bar ── */}
      <div className="map-header-bar">
        <div className="map-title-group">
          <div className="map-title">
            <MapPin size={18} className="text-cyan" />
            <span>Tactical Site Map & Situational Awareness</span>
          </div>
          <span className="map-subtitle">
            Schematic Border Outpost (BOP) status overview · Live health & alert monitoring
          </span>
        </div>

        <div className="map-stats-strip">
          <div className="map-stat-pill">
            <Radio size={12} className="text-cyan" />
            <span>Total Sites: <strong>{totalSites}</strong></span>
          </div>
          <div className="map-stat-pill pill-healthy">
            <ShieldCheck size={12} />
            <span>Healthy: <strong>{healthySites}</strong></span>
          </div>
          <div className="map-stat-pill pill-alert">
            <ShieldAlert size={12} />
            <span>Active Alerts: <strong>{alertSites}</strong></span>
          </div>
          <div className="map-stat-pill pill-offline">
            <Activity size={12} />
            <span>Offline Cameras: <strong>{offlineSites}</strong></span>
          </div>

          <button
            type="button"
            className="map-refresh-btn"
            onClick={fetchSites}
            disabled={loading}
            title="Refresh Site Status"
          >
            <RefreshCw size={12} className={loading ? 'spin' : ''} />
          </button>
        </div>
      </div>

      {error && <div className="error-banner">Failed to load site map data: {error}</div>}

      {/* ── Main Map Workspace ── */}
      <div className="map-workspace">
        {/* Schematic Canvas Layout */}
        <div className="schematic-canvas">
          {/* Tactical Grid Background SVG */}
          <svg className="schematic-svg-bg" width="100%" height="100%">
            <defs>
              <pattern id="tactical-grid" width="40" height="40" patternUnits="userSpaceOnUse">
                <path d="M 40 0 L 0 0 0 40" fill="none" stroke="rgba(6, 182, 212, 0.08)" strokeWidth="1" />
              </pattern>
            </defs>
            <rect width="100%" height="100%" fill="url(#tactical-grid)" />
            
            {/* Border Sector Line representation */}
            <path
              d="M 50 150 Q 300 120 500 250 T 950 350"
              fill="none"
              stroke="rgba(6, 182, 212, 0.25)"
              strokeWidth="2"
              strokeDasharray="6 4"
            />
            <text x="60" y="140" fill="rgba(6, 182, 212, 0.4)" fontSize="11" fontFamily="monospace">
              INTERNATIONAL BORDER DEMARCATION LINE
            </text>
          </svg>

          {/* Site Pins Overlay */}
          {sites.map((site) => {
            const isSelected = selectedSite?.id === site.id
            const pinClass = getPinStyleClass(site)

            return (
              <div
                key={site.id}
                className={`schematic-pin-node ${pinClass} ${isSelected ? 'pin-selected' : ''}`}
                style={{ left: `${site.x}%`, top: `${site.y}%` }}
                onClick={() => setSelectedSite(site)}
              >
                {/* Pulsing Aura for active alert */}
                {(site.highest_alert_severity === 'CRITICAL' || site.highest_alert_severity === 'HIGH') && (
                  <div className="pin-pulse-ring" />
                )}

                <div className="pin-badge">
                  <MapPin size={14} />
                  <span className="pin-id">{site.id}</span>
                </div>

                <div className="pin-label-box">
                  <div className="pin-name">{site.name}</div>
                  <div className="pin-sub">
                    {site.online_count}/{site.total_cameras} Online
                    {site.unacked_alert_count > 0 && ` · ${site.unacked_alert_count} Alerts`}
                  </div>
                </div>
              </div>
            )
          })}
        </div>

        {/* ── Right Panel: Selected Site Drawer ── */}
        <div className="site-details-panel">
          {selectedSite ? (
            <div className="site-card-expanded">
              <div className="site-card-header">
                <div>
                  <div className="site-card-title">{selectedSite.name}</div>
                  <div className="site-card-sub">{selectedSite.location_label}</div>
                </div>
                <StatusBadge status={selectedSite.status} severity={selectedSite.highest_alert_severity} />
              </div>

              <div className="site-card-stats">
                <div className="site-mini-stat">
                  <span className="mini-label">Total Cameras</span>
                  <span className="mini-val">{selectedSite.total_cameras}</span>
                </div>
                <div className="site-mini-stat">
                  <span className="mini-label">Online</span>
                  <span className="mini-val text-cyan">{selectedSite.online_count}</span>
                </div>
                <div className="site-mini-stat">
                  <span className="mini-label">Offline</span>
                  <span className="mini-val text-red">{selectedSite.offline_count}</span>
                </div>
                <div className="site-mini-stat">
                  <span className="mini-label">Active Alerts</span>
                  <span className="mini-val text-amber">{selectedSite.unacked_alert_count}</span>
                </div>
              </div>

              {selectedSite.unacked_alert_count > 0 && (
                <button
                  type="button"
                  className={`btn-clear-site-alerts ${confirmClearSite ? 'btn-clear-confirm' : ''}`}
                  onClick={handleClearSiteAlerts}
                  disabled={clearingSite}
                  title={confirmClearSite ? 'Click again to confirm' : `Acknowledge all alerts for ${selectedSite.name}`}
                >
                  <Trash2 size={11} />
                  <span>{clearingSite ? 'Clearing…' : confirmClearSite ? 'Confirm?' : 'Clear Site Alerts'}</span>
                </button>
              )}

              <div className="site-cameras-section">
                <div className="section-subtitle">Assigned Camera Feeds</div>
                {selectedSite.cameras.length === 0 ? (
                  <div className="empty-cams-hint">No cameras currently assigned to this outpost.</div>
                ) : (
                  <div className="site-cam-list">
                    {selectedSite.cameras.map((cam) => (
                      <div key={cam.id} className="site-cam-item">
                        <div className="cam-item-left">
                          <span className={`conn-indicator ${cam.is_connected ? 'conn-on' : 'conn-off'}`} />
                          <div>
                            <div className="cam-item-id">{cam.id}</div>
                            <div className="cam-item-name">{cam.name}</div>
                          </div>
                        </div>
                        <button
                          type="button"
                          className="btn-focus-cam"
                          onClick={() => onNavigateToDashboard?.(cam.id)}
                          title="Focus camera in Dashboard"
                        >
                          <span>Focus</span>
                          <ChevronRight size={12} />
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ) : (
            <div className="site-card-placeholder">
              <Info size={24} className="text-dim" />
              <div className="placeholder-title">Select a Site Pin</div>
              <div className="placeholder-sub">
                Click any Border Outpost (BOP) pin on the schematic map to inspect connected camera health and active alerts.
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function StatusBadge({ status, severity }) {
  if (severity === 'CRITICAL' || status === 'CRITICAL_ALERT') {
    return (
      <span className="site-status-badge badge-critical">
        <AlertOctagon size={11} />
        <span>CRITICAL ALERT</span>
      </span>
    )
  }
  if (severity === 'HIGH' || status === 'HIGH_ALERT') {
    return (
      <span className="site-status-badge badge-high">
        <AlertTriangle size={11} />
        <span>HIGH ALERT</span>
      </span>
    )
  }
  if (status === 'OFFLINE') {
    return (
      <span className="site-status-badge badge-offline">
        <Activity size={11} />
        <span>OFFLINE</span>
      </span>
    )
  }
  if (status === 'DEGRADED') {
    return (
      <span className="site-status-badge badge-degraded">
        <AlertTriangle size={11} />
        <span>DEGRADED</span>
      </span>
    )
  }
  return (
    <span className="site-status-badge badge-healthy">
      <ShieldCheck size={11} />
      <span>HEALTHY</span>
    </span>
  )
}

function getPinStyleClass(site) {
  if (site.highest_alert_severity === 'CRITICAL' || site.status === 'CRITICAL_ALERT') return 'pin-critical'
  if (site.highest_alert_severity === 'HIGH' || site.status === 'HIGH_ALERT') return 'pin-high'
  if (site.status === 'OFFLINE') return 'pin-offline'
  if (site.status === 'DEGRADED') return 'pin-degraded'
  return 'pin-healthy'
}
