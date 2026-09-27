import { useState, useEffect } from 'react'
import { getVehicleSightings, downloadVehicleEvidencePackage } from '../api'
import {
  Car,
  Search,
  Camera,
  Clock,
  ShieldAlert,
  ShieldCheck,
  Info,
  MapPin,
  Image as ImageIcon,
  X,
  ExternalLink,
  ChevronRight,
  Zap,
  FileDown,
  Download,
  Loader2,
} from 'lucide-react'

// Distinct vibrant color accents for camera node grouping
const CAMERA_COLORS = [
  { border: 'var(--cyan)', bg: 'rgba(6, 182, 212, 0.12)', text: 'var(--cyan)' },
  { border: '#a855f7', bg: 'rgba(168, 85, 247, 0.12)', text: '#c084fc' },
  { border: '#f59e0b', bg: 'rgba(245, 158, 11, 0.12)', text: '#fbbf24' },
  { border: '#ec4899', bg: 'rgba(236, 72, 153, 0.12)', text: '#f472b6' },
  { border: '#10b981', bg: 'rgba(16, 185, 129, 0.12)', text: '#34d399' },
]

export default function VehicleTrackTimeline({ cameras = [], initialPlate = '' }) {
  const [searchPlate, setSearchPlate] = useState(initialPlate || '')
  const [activePlate, setActivePlate] = useState(initialPlate || '')
  const [sightings, setSightings] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [selectedSnapshot, setSelectedSnapshot] = useState(null)
  const [exportingDossier, setExportingDossier] = useState(false)
  const [dossierError, setDossierError] = useState(null)


  // Map camera IDs to consistent visual color tokens
  const cameraColorMap = {}
  cameras.forEach((c, idx) => {
    cameraColorMap[c.id] = CAMERA_COLORS[idx % CAMERA_COLORS.length]
  })

  const executeTrack = async (plateToSearch) => {
    const target = (plateToSearch || searchPlate).trim()
    if (!target) return
    setActivePlate(target)
    setLoading(true)
    setError(null)
    try {
      const data = await getVehicleSightings(target)
      setSightings(data)
    } catch (err) {
      setError(err.message)
      setSightings([])
    } finally {
      setLoading(false)
    }
  }

  // Trigger auto-search if initialPlate is passed
  useEffect(() => {
    if (initialPlate) {
      setSearchPlate(initialPlate)
      executeTrack(initialPlate)
    }
  }, [initialPlate])

  const handleSubmit = (e) => {
    e.preventDefault()
    executeTrack(searchPlate)
  }

  const handleClear = () => {
    setSearchPlate('')
    setActivePlate('')
    setSightings(null)
    setError(null)
  }

  const handleExportDossier = async (format = 'pdf') => {
    if (!activePlate) return
    setExportingDossier(true)
    setDossierError(null)
    try {
      await downloadVehicleEvidencePackage(activePlate, format)
    } catch (err) {
      setDossierError(err.message)
    } finally {
      setExportingDossier(false)
    }
  }

  // Group stats
  const uniqueCamerasCount = sightings
    ? new Set(sightings.map((s) => s.camera_id)).size
    : 0

  return (
    <div className="vehicle-track-view">
      {/* ── Search & Controls Bar ── */}
      <div className="vehicle-search-card">
        <div className="search-card-header">
          <div className="search-title">
            <Car size={16} className="text-cyan" />
            <span>Vehicle Plate Movement Tracker</span>
          </div>
          <span className="search-subtitle">
            Exact match on normalized plate text across all system cameras
          </span>
        </div>

        <form onSubmit={handleSubmit} className="vehicle-search-form">
          <div className="input-wrap">
            <Search size={14} className="input-icon" />
            <input
              id="vehicle-plate-search"
              name="plate_query"
              aria-label="Enter license plate to track vehicle sightings"
              type="text"
              className="vehicle-plate-input"
              placeholder="Enter license plate (e.g. KA05NB4912 or DL01AB1234)..."
              value={searchPlate}
              onChange={(e) => setSearchPlate(e.target.value.toUpperCase())}
            />
            {searchPlate && (
              <button type="button" className="input-clear-btn" onClick={handleClear}>
                <X size={12} />
              </button>
            )}
          </div>

          <button type="submit" className="btn-track-submit" disabled={loading || !searchPlate.trim()}>
            {loading ? (
              <span>Tracing…</span>
            ) : (
              <>
                <Zap size={13} />
                <span>Track Vehicle</span>
              </>
            )}
          </button>
        </form>

        {/* Quick sample tags */}
        <div className="quick-tags-wrap">
          <span className="quick-label">Sample Watchlist Plates:</span>
          {['KA05NB4912', 'DL01AB1234', 'MH12PQ9999'].map((plate) => (
            <button
              key={plate}
              type="button"
              className={`quick-tag-btn ${activePlate === plate ? 'tag-active' : ''}`}
              onClick={() => {
                setSearchPlate(plate)
                executeTrack(plate)
              }}
            >
              {plate}
            </button>
          ))}
        </div>
      </div>

      {/* ── Honest System Capability Disclaimer Banner ── */}
      <div className="tracking-disclaimer-banner">
        <Info size={14} className="disclaimer-icon" />
        <div className="disclaimer-text">
          <strong>Chronological Network Sighting Timeline</strong> — Shows where and when this vehicle was detected across your registered IP camera streams. It does <em>not</em> provide real-time GPS or satellite geolocation tracking.
        </div>
      </div>

      {/* ── Error Banner ── */}
      {error && <div className="error-banner">Failed to query vehicle history: {error}</div>}

      {/* ── Loading Skeleton ── */}
      {loading && (
        <div className="timeline-loading">
          <div className="spinner-cyan" />
          <span>Searching camera records across timeline…</span>
        </div>
      )}

      {/* ── Empty State ── */}
      {sightings !== null && !loading && sightings.length === 0 && (
        <div className="timeline-empty-card">
          <ShieldAlert size={28} className="empty-icon" />
          <div className="empty-title">No Sightings Found</div>
          <div className="empty-sub">
            No ANPR plate reads recorded for <strong>"{activePlate}"</strong> across any camera in the system database.
          </div>
        </div>
      )}

      {/* ── Results Timeline ── */}
      {sightings !== null && !loading && sightings.length > 0 && (
        <div className="timeline-results-wrap">
          {/* Summary stats & export bar */}
          <div className="timeline-summary-bar">
            <div className="timeline-stats-left">
              <div className="stat-pill">
                <Car size={12} />
                <span>Target Plate: <strong>{activePlate}</strong></span>
              </div>
              <div className="stat-pill">
                <Camera size={12} />
                <span>Detected across <strong>{uniqueCamerasCount}</strong> camera{uniqueCamerasCount !== 1 ? 's' : ''}</span>
              </div>
              <div className="stat-pill">
                <Clock size={12} />
                <span>Total Sightings: <strong>{sightings.length}</strong></span>
              </div>
            </div>

            <div className="timeline-actions-right">
              <button
                type="button"
                className="btn-export-dossier"
                onClick={() => handleExportDossier('pdf')}
                disabled={exportingDossier}
                title="Export certified vehicle tracking dossier (PDF)"
              >
                {exportingDossier ? (
                  <>
                    <Loader2 size={12} className="spin-icon" />
                    <span>Generating Dossier…</span>
                  </>
                ) : (
                  <>
                    <FileDown size={12} />
                    <span>Export Vehicle Dossier (PDF)</span>
                  </>
                )}
              </button>

              <button
                type="button"
                className="btn-export-zip-compact"
                onClick={() => handleExportDossier('zip')}
                disabled={exportingDossier}
                title="Export ZIP archive with metadata and images"
              >
                <Download size={11} />
                <span>ZIP</span>
              </button>
            </div>
          </div>

          {dossierError && <div className="summary-export-err">⚠ Export failed: {dossierError}</div>}


          {/* Vertical Timeline */}
          <div className="vehicle-timeline">
            {sightings.map((sighting, idx) => {
              const camStyle = cameraColorMap[sighting.camera_id] || CAMERA_COLORS[0]
              const ts = new Date(sighting.timestamp)
              const timeStr = ts.toLocaleTimeString('en-IN', { hour12: false })
              const dateStr = ts.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' })
              const snapshot = sighting.evidence?.snapshot_uri

              return (
                <div key={sighting.event_id || idx} className="timeline-node">
                  {/* Timeline connector dot & line */}
                  <div className="node-axis">
                    <div
                      className="node-dot"
                      style={{ borderColor: camStyle.border, backgroundColor: camStyle.border }}
                    >
                      <span className="node-number">{idx + 1}</span>
                    </div>
                    {idx < sightings.length - 1 && <div className="node-connector" />}
                  </div>

                  {/* Sighting card content */}
                  <div className="node-card" style={{ borderColor: camStyle.border }}>
                    <div className="node-card-header">
                      <div className="cam-attribution">
                        <span
                          className="cam-pill"
                          style={{
                            borderColor: camStyle.border,
                            background: camStyle.bg,
                            color: camStyle.text,
                          }}
                        >
                          <Camera size={11} />
                          <span>{sighting.camera_id}</span>
                        </span>
                        <div className="cam-meta">
                          <span className="cam-name">{sighting.camera_name}</span>
                          <span className="cam-loc">
                            <MapPin size={10} /> {sighting.location}
                          </span>
                        </div>
                      </div>

                      <div className="node-header-right">
                        {sighting.watchlist_match ? (
                          <span className={`watchlist-badge list-${(sighting.list_type || 'BLACK').toLowerCase()}`}>
                            <ShieldAlert size={11} />
                            <span>{(sighting.list_type || 'WATCHLIST')} MATCH</span>
                          </span>
                        ) : (
                          <span className="watchlist-badge list-none">
                            <ShieldCheck size={11} />
                            <span>STANDARD READ</span>
                          </span>
                        )}

                        <div className="timestamp-box">
                          <Clock size={11} />
                          <span>{dateStr} {timeStr}</span>
                        </div>
                      </div>
                    </div>

                    <div className="node-card-body">
                      {snapshot && (
                        <div
                          className="sighting-thumbnail-box"
                          onClick={() => setSelectedSnapshot({ uri: snapshot, sighting })}
                          title="Click to expand evidence frame"
                        >
                          <img src={snapshot} alt={`Sighting on ${sighting.camera_id}`} />
                          <div className="thumb-hover-overlay">
                            <ImageIcon size={14} />
                            <span>View Frame</span>
                          </div>
                        </div>
                      )}

                      <div className="sighting-details">
                        <div className="detail-row">
                          <span className="detail-label">Plate Read:</span>
                          <span className="detail-val mono-plate">{sighting.plate_text}</span>
                          {sighting.raw_ocr && sighting.raw_ocr !== sighting.plate_text && (
                            <span className="raw-ocr-hint">(Raw OCR: {sighting.raw_ocr})</span>
                          )}
                        </div>

                        <div className="detail-row">
                          <span className="detail-label">ANPR Confidence:</span>
                          <div className="conf-bar-wrap">
                            <div
                              className="conf-bar-fill"
                              style={{ width: `${Math.round(sighting.confidence * 100)}%` }}
                            />
                            <span className="conf-text">{(sighting.confidence * 100).toFixed(0)}%</span>
                          </div>
                        </div>

                        {(sighting.zone_id || sighting.zone_name) && (
                          <div className="detail-row">
                            <span className="detail-label">Virtual Zone:</span>
                            <span className="detail-val zone-pill" style={{ color: 'var(--cyan)' }}>
                              {sighting.zone_name ? `${sighting.zone_name} (${sighting.zone_id})` : sighting.zone_id}
                            </span>
                          </div>
                        )}

                        {sighting.notes && (
                          <div className="detail-row notes-row">
                            <span className="detail-label">Watchlist Notes:</span>
                            <span className="notes-val">{sighting.notes}</span>
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* ── Snapshot Lightbox Modal ── */}
      {selectedSnapshot && (
        <div className="lightbox-overlay" onClick={() => setSelectedSnapshot(null)}>
          <div className="lightbox-modal" onClick={(e) => e.stopPropagation()}>
            <div className="lightbox-header">
              <div>
                <span className="lightbox-title">
                  Evidence Frame — {selectedSnapshot.sighting.camera_id}
                </span>
                <span className="lightbox-sub">
                  {selectedSnapshot.sighting.camera_name} · {selectedSnapshot.sighting.timestamp}
                </span>
              </div>
              <button type="button" className="btn-close" onClick={() => setSelectedSnapshot(null)}>
                <X size={14} />
              </button>
            </div>
            <div className="lightbox-body">
              <img src={selectedSnapshot.uri} alt="Full evidence frame" />
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
