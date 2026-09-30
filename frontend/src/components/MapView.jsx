import { useState, useEffect, useCallback, useRef } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import 'leaflet-draw'
import 'leaflet-draw/dist/leaflet.draw.css'
import {
  getSitesStatus,
  acknowledgeBulkEvents,
  getSiteRestrictions,
  createSiteRestriction,
  deleteSiteRestriction,
} from '../api'
import {
  MapPin,
  ShieldAlert,
  ShieldCheck,
  Activity,
  AlertTriangle,
  AlertOctagon,
  RefreshCw,
  ChevronRight,
  Info,
  Radio,
  Trash2,
  Pentagon,
  Shield,
  PlusCircle,
  X,
  CheckCircle2,
} from 'lucide-react'

// Default fallback GIS coordinates centered on Jammu/Kathua border sector
const DEFAULT_COORDS = {
  'BOP-01': [32.5850, 74.8320],
  'BOP-02': [32.5310, 74.9650],
  'CP-03': [32.4630, 74.8050],
}

const MAP_CENTER = [32.5300, 74.8800]
const MAP_ZOOM = 11

// Tactical sector boundary line coordinates (subtle defense demarcation line)
const SECTOR_BOUNDARY_LINE = [
  [32.6200, 74.7700],
  [32.5850, 74.8320],
  [32.5500, 74.8900],
  [32.5310, 74.9650],
  [32.4900, 75.0300],
]

/**
 * Calculate distance between two lat/lng coordinates (simple Euclidean for proximity)
 */
function getDistance(lat1, lng1, lat2, lng2) {
  const dLat = lat1 - lat2
  const dLng = lng1 - lng2
  return Math.sqrt(dLat * dLat + dLng * dLng)
}

/**
 * MapView — Tactical GIS Site Map & Situational Awareness View.
 * Interactive Leaflet.js map with OpenStreetMap tiles (CSS-inverted for dark mode),
 * live marker status indicators, outpost drilldown inspection, and site restriction zones.
 */
export default function MapView({ onNavigateToDashboard }) {
  const [sites, setSites] = useState([])
  const [restrictions, setRestrictions] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [selectedSite, setSelectedSite] = useState(null)
  const [clearingSite, setClearingSite] = useState(false)
  const [confirmClearSite, setConfirmClearSite] = useState(false)

  // Drawing state
  const [isDrawingMode, setIsDrawingMode] = useState(false)
  const [pendingZone, setPendingZone] = useState(null) // { coords, site_id, name, restriction_level }
  const [savingZone, setSavingZone] = useState(false)
  const [deletingZoneId, setDeletingZoneId] = useState(null)

  const mapContainerRef = useRef(null)
  const mapInstanceRef = useRef(null)
  const markersLayerRef = useRef(null)
  const restrictionsLayerRef = useRef(null)
  const drawHandlerRef = useRef(null)

  const fetchSitesAndRestrictions = useCallback(async () => {
    try {
      setError(null)
      const [sitesData, restrictionsData] = await Promise.all([
        getSitesStatus(),
        getSiteRestrictions().catch(() => []),
      ])

      const validSites = Array.isArray(sitesData) ? sitesData : []
      const validRestrictions = Array.isArray(restrictionsData) ? restrictionsData : []

      setSites(validSites)
      setRestrictions(validRestrictions)

      setSelectedSite((prev) => {
        if (!prev) return null
        return validSites.find((s) => s.id === prev.id) || prev
      })
    } catch (err) {
      console.error('Failed to load sites/restrictions status:', err)
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchSitesAndRestrictions()
    const timer = setInterval(fetchSitesAndRestrictions, 5000)
    return () => clearInterval(timer)
  }, [fetchSitesAndRestrictions])

  // Initialize Leaflet Map
  useEffect(() => {
    if (!mapContainerRef.current || mapInstanceRef.current) return

    // Ensure Leaflet container isn't already initialized
    const container = mapContainerRef.current
    if (container._leaflet_id) {
      container._leaflet_id = null
    }

    const map = L.map(container, {
      center: MAP_CENTER,
      zoom: MAP_ZOOM,
      zoomControl: false,
      attributionControl: true,
      minZoom: 9,
      maxZoom: 18,
    })

    // OpenStreetMap standard tiles — genuinely free, no API key needed ever.
    // Dark tactical look achieved via CSS filter on .leaflet-tile-pane.
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap</a> contributors',
      maxZoom: 19,
    }).addTo(map)

    // Add subtle tactical sector defense demarcation polyline
    L.polyline(SECTOR_BOUNDARY_LINE, {
      color: '#06b6d4',
      weight: 1.8,
      opacity: 0.45,
      dashArray: '6, 8',
      interactive: false,
    }).addTo(map)

    // Zoom control at bottom-right
    L.control.zoom({ position: 'bottomright' }).addTo(map)

    const restrictionsLayer = L.featureGroup().addTo(map)
    const markersLayer = L.layerGroup().addTo(map)

    mapInstanceRef.current = map
    markersLayerRef.current = markersLayer
    restrictionsLayerRef.current = restrictionsLayer

    // Setup Leaflet Draw event listener
    map.on(L.Draw.Event.CREATED, (e) => {
      const layer = e.layer
      const latlngs = layer.getLatLngs()
      // Normalize polygon latlngs array
      const flatCoords = Array.isArray(latlngs[0]) ? latlngs[0] : latlngs
      const coords = flatCoords.map((pt) => [Number(pt.lat.toFixed(5)), Number(pt.lng.toFixed(5))])

      // Compute centroid to detect nearest site
      let sumLat = 0
      let sumLng = 0
      coords.forEach(([lat, lng]) => {
        sumLat += lat
        sumLng += lng
      })
      const centerLat = sumLat / coords.length
      const centerLng = sumLng / coords.length

      // Find closest site
      let closestSiteId = 'BOP-01'
      let minDistance = Infinity

      Object.entries(DEFAULT_COORDS).forEach(([siteId, [sLat, sLng]]) => {
        const dist = getDistance(centerLat, centerLng, sLat, sLng)
        if (dist < minDistance) {
          minDistance = dist
          closestSiteId = siteId
        }
      })

      setPendingZone({
        coords,
        site_id: closestSiteId,
        name: `${closestSiteId} Restricted Perimeter`,
        restriction_level: 'HIGH',
      })

      setIsDrawingMode(false)
    })

    // Clean resize on window resize
    const resizeObserver = new ResizeObserver(() => {
      map.invalidateSize()
    })
    resizeObserver.observe(container)

    // Initial size invalidation
    setTimeout(() => map.invalidateSize(), 150)

    return () => {
      resizeObserver.disconnect()
      map.remove()
      mapInstanceRef.current = null
      markersLayerRef.current = null
      restrictionsLayerRef.current = null
    }
  }, [])

  // Invalidate map size when drawing mode changes
  useEffect(() => {
    if (mapInstanceRef.current) {
      setTimeout(() => mapInstanceRef.current?.invalidateSize(), 50)
    }
  }, [isDrawingMode])

  // Update Markers when sites data or selectedSite changes
  useEffect(() => {
    const map = mapInstanceRef.current
    const markersLayer = markersLayerRef.current
    if (!map || !markersLayer) return

    markersLayer.clearLayers()
    if (!sites.length) return

    sites.forEach((site) => {
      const lat = site.lat ?? DEFAULT_COORDS[site.id]?.[0] ?? MAP_CENTER[0]
      const lng = site.lng ?? DEFAULT_COORDS[site.id]?.[1] ?? MAP_CENTER[1]
      const isSelected = selectedSite?.id === site.id
      const pinClass = getPinStyleClass(site)
      const hasAlert =
        site.highest_alert_severity === 'CRITICAL' ||
        site.highest_alert_severity === 'HIGH' ||
        site.status === 'CRITICAL_ALERT' ||
        site.status === 'HIGH_ALERT'

      const hasRestriction = site.has_restriction || (site.active_restrictions && site.active_restrictions.length > 0)

      const customHtml = `
        <div class="schematic-pin-node ${pinClass} ${isSelected ? 'pin-selected' : ''}" id="map-marker-${site.id}">
          ${hasAlert ? '<div class="pin-pulse-ring"></div>' : ''}
          <div class="pin-badge ${hasRestriction ? 'pin-badge-restricted' : ''}">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0Z"/><circle cx="12" cy="10" r="3"/></svg>
            <span class="pin-id">${site.id}</span>
            ${hasRestriction ? '<span class="pin-restr-indicator" title="Active Restriction Zone">🛡️</span>' : ''}
          </div>
          <div class="pin-label-box">
            <div class="pin-name">${site.name}</div>
            <div class="pin-sub">
              ${site.online_count}/${site.total_cameras} Online${site.unacked_alert_count > 0 ? ` · ${site.unacked_alert_count} Alerts` : ''}
            </div>
          </div>
        </div>
      `

      const icon = L.divIcon({
        html: customHtml,
        className: 'leaflet-tactical-marker',
        iconSize: [120, 60],
        iconAnchor: [60, 30],
      })

      const marker = L.marker([lat, lng], {
        icon,
        title: `${site.name} (${site.id})`,
        zIndexOffset: isSelected ? 1000 : 100,
      })

      marker.on('click', () => {
        setSelectedSite(site)
        map.panTo([lat, lng], { animate: true, duration: 0.4 })
      })

      marker.addTo(markersLayer)
    })
  }, [sites, selectedSite])

  // Render Restriction Zone Polygons on Map
  useEffect(() => {
    const map = mapInstanceRef.current
    const restrLayer = restrictionsLayerRef.current
    if (!map || !restrLayer) return

    restrLayer.clearLayers()

    restrictions.forEach((restr) => {
      let coords = []
      if (Array.isArray(restr.polygon_geojson)) {
        coords = restr.polygon_geojson
      } else if (restr.polygon_geojson?.coordinates) {
        // GeoJSON format [lng, lat] -> Leaflet [lat, lng]
        coords = restr.polygon_geojson.coordinates[0].map(([lng, lat]) => [lat, lng])
      }

      if (!coords || coords.length < 3) return

      const isCritical = restr.restriction_level === 'CRITICAL'
      const polyColor = isCritical ? '#ef4444' : '#f97316'
      const fillOpacity = isCritical ? 0.28 : 0.2

      const polygon = L.polygon(coords, {
        color: polyColor,
        weight: 2,
        dashArray: '5, 5',
        fillColor: polyColor,
        fillOpacity,
        className: 'tactical-restriction-polygon',
      })

      polygon.bindTooltip(
        `<strong>🛡️ ${restr.name || `${restr.site_id} RESTRICTED`}</strong><br/><span style="color:${polyColor};font-weight:600;">LEVEL: ${restr.restriction_level}</span>`,
        {
          permanent: false,
          direction: 'center',
          className: 'tactical-polygon-tooltip',
        }
      )

      polygon.on('click', () => {
        const matchingSite = sites.find((s) => s.id === restr.site_id)
        if (matchingSite) setSelectedSite(matchingSite)
      })

      polygon.addTo(restrLayer)
    })
  }, [restrictions, sites])

  // Start Leaflet Draw Polygon Handler
  const startDrawPolygon = () => {
    const map = mapInstanceRef.current
    if (!map) return

    if (drawHandlerRef.current) {
      drawHandlerRef.current.disable()
    }

    const polygonDrawer = new L.Draw.Polygon(map, {
      allowIntersection: false,
      showArea: true,
      shapeOptions: {
        color: '#ef4444',
        fillColor: '#ef4444',
        fillOpacity: 0.25,
        weight: 2,
        dashArray: '4, 4',
      },
    })

    polygonDrawer.enable()
    drawHandlerRef.current = polygonDrawer
    setIsDrawingMode(true)
  }

  // Cancel drawing
  const cancelDrawing = () => {
    if (drawHandlerRef.current) {
      drawHandlerRef.current.disable()
      drawHandlerRef.current = null
    }
    setIsDrawingMode(false)
    setPendingZone(null)
  }

  // Quick-add perimeter box around selected site
  const handleQuickAddPerimeter = (siteId) => {
    const targetSiteId = siteId || selectedSite?.id || 'BOP-01'
    const [cLat, cLng] = DEFAULT_COORDS[targetSiteId] || MAP_CENTER
    const deltaLat = 0.018
    const deltaLng = 0.024

    const coords = [
      [Number((cLat + deltaLat).toFixed(5)), Number((cLng - deltaLng).toFixed(5))],
      [Number((cLat + deltaLat).toFixed(5)), Number((cLng + deltaLng).toFixed(5))],
      [Number((cLat - deltaLat).toFixed(5)), Number((cLng + deltaLng).toFixed(5))],
      [Number((cLat - deltaLat).toFixed(5)), Number((cLng - deltaLng).toFixed(5))],
    ]

    setPendingZone({
      coords,
      site_id: targetSiteId,
      name: `${targetSiteId} Restricted Perimeter`,
      restriction_level: 'HIGH',
    })
  }

  // Save pending restriction zone
  const handleSaveRestriction = async () => {
    if (!pendingZone) return
    setSavingZone(true)
    try {
      await createSiteRestriction({
        site_id: pendingZone.site_id,
        name: pendingZone.name,
        restriction_level: pendingZone.restriction_level,
        polygon_geojson: pendingZone.coords,
        is_active: true,
      })

      setPendingZone(null)
      await fetchSitesAndRestrictions()
    } catch (err) {
      console.error('Failed to create site restriction:', err)
      alert(`Failed to save restriction zone: ${err.message}`)
    } finally {
      setSavingZone(false)
    }
  }

  // Delete restriction zone
  const handleDeleteRestriction = async (restrictionId) => {
    if (!restrictionId) return
    setDeletingZoneId(restrictionId)
    try {
      await deleteSiteRestriction(restrictionId)
      await fetchSitesAndRestrictions()
    } catch (err) {
      console.error('Failed to delete restriction:', err)
      alert(`Failed to delete restriction zone: ${err.message}`)
    } finally {
      setDeletingZoneId(null)
    }
  }

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
      await fetchSitesAndRestrictions()
    } catch (err) {
      console.error('Clear site alerts failed:', err)
    } finally {
      setClearingSite(false)
    }
  }

  // Summary counts
  const totalSites = sites.length
  const alertSites = sites.filter((s) => s.highest_alert_severity !== 'NONE').length
  const restrictedSitesCount = sites.filter((s) => s.has_restriction || (s.active_restrictions && s.active_restrictions.length > 0)).length
  const offlineSites = sites.filter((s) => s.offline_count > 0).length
  const healthySites = sites.filter(
    (s) => s.status === 'HEALTHY' || (s.offline_count === 0 && s.highest_alert_severity === 'NONE')
  ).length

  // Active restrictions for currently selected site
  const selectedSiteRestrictions = selectedSite
    ? restrictions.filter((r) => r.site_id === selectedSite.id)
    : []

  return (
    <div className="map-view-container">
      {/* ── Top Summary & Action Bar ── */}
      <div className="map-header-bar">
        <div className="map-title-group">
          <div className="map-title">
            <MapPin size={18} className="text-cyan" />
            <span>Tactical GIS Site Map & Situational Awareness</span>
          </div>
          <span className="map-subtitle">
            Live interactive geospatial intelligence · Real-time BOP health & perimeter monitoring
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
          <div className="map-stat-pill pill-restricted">
            <Shield size={12} className="text-red" />
            <span>Restricted: <strong>{restrictedSitesCount}</strong></span>
          </div>
          <div className="map-stat-pill pill-offline">
            <Activity size={12} />
            <span>Offline Cameras: <strong>{offlineSites}</strong></span>
          </div>

          {/* Draw Restricted Zone action button */}
          <button
            type="button"
            className={`btn-draw-zone ${isDrawingMode ? 'active-drawing' : ''}`}
            onClick={isDrawingMode ? cancelDrawing : startDrawPolygon}
            title={isDrawingMode ? 'Cancel Drawing' : 'Draw Polygon Restriction Zone on Map'}
          >
            <Pentagon size={13} />
            <span>{isDrawingMode ? 'Cancel Drawing' : 'Draw Restricted Zone'}</span>
          </button>

          <button
            type="button"
            className="map-refresh-btn"
            onClick={fetchSitesAndRestrictions}
            disabled={loading}
            title="Refresh Site Status"
          >
            <RefreshCw size={12} className={loading ? 'spin' : ''} />
          </button>
        </div>
      </div>

      {error && <div className="error-banner">Failed to load site map data: {error}</div>}

      {/* ── Active Drawing Banner Hint ── */}
      {isDrawingMode && (
        <div className="draw-instructions-banner">
          <div className="banner-left">
            <Pentagon size={14} className="pulse-icon text-red" />
            <span>
              <strong>POLYGON RESTRICTION DRAW MODE:</strong> Click on the map to place perimeter vertices. Click the first vertex again to close the polygon.
            </span>
          </div>
          <button type="button" className="btn-cancel-draw-banner" onClick={cancelDrawing}>
            <X size={13} />
            <span>Exit Draw Mode</span>
          </button>
        </div>
      )}

      {/* ── Main Map Workspace ── */}
      <div className="map-workspace">
        {/* Leaflet Geospatial Canvas */}
        <div
          id="tactical-leaflet-map"
          ref={mapContainerRef}
          className="leaflet-map-canvas"
        />

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

              {/* ── Site-Level Restriction Zone Section ── */}
              <div className="site-restriction-box">
                <div className="restr-box-header">
                  <div className="restr-title">
                    <Shield size={13} className={selectedSiteRestrictions.length > 0 ? 'text-red' : 'text-dim'} />
                    <span>Site Restriction Zone</span>
                  </div>
                  {selectedSiteRestrictions.length > 0 ? (
                    <span className="restr-active-tag">
                      {selectedSiteRestrictions[0].restriction_level} RESTRICTION
                    </span>
                  ) : (
                    <span className="restr-inactive-tag">STANDARD</span>
                  )}
                </div>

                {selectedSiteRestrictions.length > 0 ? (
                  <div className="restr-active-content">
                    <div className="restr-desc">
                      Elevated alert status active. All {selectedSite.total_cameras} cameras at this outpost inherit automatic severity elevation &amp; tagging.
                    </div>
                    <div className="restr-actions">
                      <button
                        type="button"
                        className="btn-delete-restriction"
                        onClick={() => handleDeleteRestriction(selectedSiteRestrictions[0].id)}
                        disabled={deletingZoneId === selectedSiteRestrictions[0].id}
                        title="Remove restriction zone from this outpost"
                      >
                        <Trash2 size={11} />
                        <span>
                          {deletingZoneId === selectedSiteRestrictions[0].id ? 'Removing…' : 'Remove Restriction'}
                        </span>
                      </button>
                    </div>
                  </div>
                ) : (
                  <div className="restr-inactive-content">
                    <div className="restr-desc">
                      No restriction zone applied. Cameras emit standard severity alerts.
                    </div>
                    <button
                      type="button"
                      className="btn-add-site-restriction"
                      onClick={() => handleQuickAddPerimeter(selectedSite.id)}
                      title="Set restriction perimeter around this outpost"
                    >
                      <PlusCircle size={12} />
                      <span>Restrict Outpost Perimeter</span>
                    </button>
                  </div>
                )}
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
              <div className="placeholder-title">Select a Map Pin</div>
              <div className="placeholder-sub">
                Click any Border Outpost (BOP) marker on the interactive GIS map to inspect connected camera health, active alerts, and configure perimeter restriction zones.
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ── Modal / Dialog: Confirm Restriction Zone on Draw ── */}
      {pendingZone && (
        <div className="restr-modal-backdrop">
          <div className="restr-modal-dialog">
            <div className="restr-modal-header">
              <div className="modal-title-group">
                <Shield size={16} className="text-red" />
                <span>Configure Site Restriction Zone</span>
              </div>
              <button
                type="button"
                className="btn-close-modal"
                onClick={() => setPendingZone(null)}
                aria-label="Close dialog"
              >
                <X size={14} />
              </button>
            </div>

            <div className="restr-modal-body">
              <div className="form-group">
                <label htmlFor="restr-site-select">Associate with Outpost / Site:</label>
                <select
                  id="restr-site-select"
                  className="restr-select"
                  value={pendingZone.site_id}
                  onChange={(e) =>
                    setPendingZone({
                      ...pendingZone,
                      site_id: e.target.value,
                      name: `${e.target.value} Restricted Perimeter`,
                    })
                  }
                >
                  {sites.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name} ({s.id}) — {s.total_cameras} Cameras
                    </option>
                  ))}
                </select>
              </div>

              <div className="form-group">
                <label htmlFor="restr-name-input">Zone Name / Label:</label>
                <input
                  id="restr-name-input"
                  type="text"
                  className="restr-input"
                  value={pendingZone.name}
                  onChange={(e) => setPendingZone({ ...pendingZone, name: e.target.value })}
                  placeholder="e.g. BOP-01 Perimeter Zone"
                />
              </div>

              <div className="form-group">
                <label htmlFor="restr-level-select">Restriction Severity Level:</label>
                <select
                  id="restr-level-select"
                  className="restr-select"
                  value={pendingZone.restriction_level}
                  onChange={(e) => setPendingZone({ ...pendingZone, restriction_level: e.target.value })}
                >
                  <option value="HIGH">HIGH (Bumps WARNING → HIGH alerts)</option>
                  <option value="CRITICAL">CRITICAL (Bumps HIGH → CRITICAL alerts)</option>
                  <option value="WARNING">WARNING (Elevated vigilance)</option>
                </select>
              </div>

              <div className="restr-summary-note">
                <CheckCircle2 size={13} className="text-cyan" />
                <span>
                  All cameras assigned to <strong>{pendingZone.site_id}</strong> will automatically inherit elevated severity tags and alerts in the Live Feed.
                </span>
              </div>
            </div>

            <div className="restr-modal-footer">
              <button
                type="button"
                className="btn-modal-cancel"
                onClick={() => setPendingZone(null)}
                disabled={savingZone}
              >
                Discard
              </button>
              <button
                type="button"
                className="btn-modal-save"
                onClick={handleSaveRestriction}
                disabled={savingZone}
              >
                {savingZone ? 'Saving Zone…' : 'Apply & Save Restriction'}
              </button>
            </div>
          </div>
        </div>
      )}
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
