import { useState, useEffect, useRef } from 'react'
import { User, RefreshCw, Camera, Clock, ShieldAlert } from 'lucide-react'

const API_BASE = '/api/v1'
const POLL_INTERVAL = 4000   // ms
const PAGE_SIZE = 30

function relativeTime(ts) {
  if (!ts) return '—'
  const diff = (Date.now() - new Date(ts).getTime()) / 1000
  if (diff < 5) return 'just now'
  if (diff < 60) return `${Math.round(diff)}s ago`
  if (diff < 3600) return `${Math.round(diff / 60)}m ago`
  return new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

function ConfBar({ value }) {
  const pct = Math.round((value || 0) * 100)
  const color = pct >= 80 ? 'var(--netra-cyan)' : pct >= 60 ? 'var(--sev-warning)' : 'var(--sev-high)'
  return (
    <div className="faces-conf-bar-wrap">
      <div
        className="faces-conf-bar"
        style={{ width: `${pct}%`, background: color }}
      />
      <span className="faces-conf-label">{pct}%</span>
    </div>
  )
}

export default function FacesView() {
  const [events, setEvents] = useState([])
  const [loading, setLoading] = useState(true)
  const [lastRefresh, setLastRefresh] = useState(null)
  const [selectedCamera, setSelectedCamera] = useState('all')
  const [cameras, setCameras] = useState([])
  const pollerRef = useRef(null)

  async function fetchFaces() {
    try {
      const camParam = selectedCamera !== 'all' ? `&camera_id=${selectedCamera}` : ''
      const url = `${API_BASE}/events?type=FACE_DETECTED&limit=${PAGE_SIZE}${camParam}`
      const res = await fetch(url)
      if (!res.ok) return
      const data = await res.json()
      setEvents(Array.isArray(data) ? data : (data.items || []))
      setLastRefresh(new Date())
    } catch (_) {}
    setLoading(false)
  }

  async function fetchCameras() {
    try {
      const res = await fetch(`${API_BASE}/cameras`)
      if (!res.ok) return
      setCameras(await res.json())
    } catch (_) {}
  }

  useEffect(() => {
    fetchCameras()
    fetchFaces()
    pollerRef.current = setInterval(fetchFaces, POLL_INTERVAL)
    return () => clearInterval(pollerRef.current)
  }, [])   // eslint-disable-line

  // Re-fetch when camera filter changes
  useEffect(() => {
    fetchFaces()
  }, [selectedCamera])  // eslint-disable-line

  const isEmpty = !loading && events.length === 0

  return (
    <div className="faces-view">
      {/* Header bar */}
      <div className="faces-header">
        <div className="faces-title-row">
          <User size={20} className="faces-title-icon" />
          <h2 className="faces-title">Face Detection Gallery</h2>
          <span className="faces-badge">{events.length} detected</span>
        </div>

        <div className="faces-controls">
          {/* Camera filter */}
          <select
            className="faces-cam-filter"
            value={selectedCamera}
            onChange={(e) => setSelectedCamera(e.target.value)}
          >
            <option value="all">All cameras</option>
            {cameras.map((c) => (
              <option key={c.id} value={c.id}>{c.id} — {c.name || c.location}</option>
            ))}
          </select>

          <button
            className="faces-refresh-btn"
            onClick={fetchFaces}
            title="Refresh now"
          >
            <RefreshCw size={14} />
            Refresh
          </button>

          {lastRefresh && (
            <span className="faces-last-refresh">
              Updated {relativeTime(lastRefresh)}
            </span>
          )}
        </div>
      </div>

      {/* Content */}
      {loading ? (
        <div className="faces-loading">
          <div className="spinner" />
          <span>Loading face events…</span>
        </div>
      ) : isEmpty ? (
        <div className="faces-empty">
          <User size={48} className="faces-empty-icon" />
          <p className="faces-empty-title">No face detections yet</p>
          <p className="faces-empty-sub">
            Face detection runs on every active camera worker.
            Ensure cameras are online and people are in frame.
          </p>
        </div>
      ) : (
        <div className="faces-grid">
          {events.map((evt) => (
            <FaceCard key={evt.id} event={evt} />
          ))}
        </div>
      )}
    </div>
  )
}

function FaceCard({ event }) {
  const meta = event.metadata || {}
  const bbox = meta.face_bbox || null
  const conf = event.confidence ?? 0
  const isRestricted = meta.restriction_level === 'RESTRICTED'
  const zone = meta.zone_name || event.zone_id || null

  return (
    <div className={`face-card ${isRestricted ? 'face-card-restricted' : ''}`}>
      {/* Icon / avatar placeholder */}
      <div className="face-card-avatar">
        <User size={28} />
        {isRestricted && (
          <span className="face-card-restricted-badge" title="Detected in restricted zone">
            <ShieldAlert size={12} />
          </span>
        )}
      </div>

      <div className="face-card-body">
        {/* Camera + time */}
        <div className="face-card-meta">
          <span className="face-card-cam">
            <Camera size={11} />
            {event.camera_id}
          </span>
          <span className="face-card-time">
            <Clock size={11} />
            {relativeTime(event.timestamp)}
          </span>
        </div>

        {/* Confidence bar */}
        <div className="face-card-conf-row">
          <span className="face-card-conf-label">Confidence</span>
          <ConfBar value={conf} />
        </div>

        {/* Zone info */}
        {zone && (
          <div className={`face-card-zone ${isRestricted ? 'face-card-zone-restricted' : ''}`}>
            {isRestricted && <ShieldAlert size={11} />}
            {zone}
          </div>
        )}

        {/* BBox */}
        {bbox && (
          <div className="face-card-bbox">
            Bbox: [{bbox.map((v) => Math.round(v)).join(', ')}]
          </div>
        )}

        {/* Track link */}
        {event.track_id != null && (
          <div className="face-card-track">Track #{event.track_id}</div>
        )}
      </div>
    </div>
  )
}
