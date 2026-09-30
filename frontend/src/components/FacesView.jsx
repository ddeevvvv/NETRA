import { useState, useEffect, useRef, useCallback } from 'react'
import { User, RefreshCw, Camera, Clock, ShieldAlert, LayoutGrid, List } from 'lucide-react'

const API_BASE = '/api/v1'
const POLL_INTERVAL = 5000 // ms
const PAGE_SIZE = 50

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
  const color = pct >= 80 ? 'var(--cyan)' : pct >= 60 ? '#fbbf24' : '#f87171'
  return (
    <div className="faces-conf-bar-wrap" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
      <div
        className="faces-conf-bar"
        style={{
          height: 4,
          borderRadius: 2,
          width: 50,
          background: 'rgba(255,255,255,0.1)',
          overflow: 'hidden',
          position: 'relative',
        }}
      >
        <div style={{ width: `${pct}%`, height: '100%', background: color }} />
      </div>
      <span className="faces-conf-label" style={{ fontSize: 11, fontWeight: 700, color }}>{pct}%</span>
    </div>
  )
}

export default function FacesView({ cameras: propCameras = [] }) {
  const [events, setEvents] = useState([])
  const [loading, setLoading] = useState(true)
  const [lastRefresh, setLastRefresh] = useState(null)
  const [selectedCamera, setSelectedCamera] = useState('all')
  const [viewMode, setViewMode] = useState('gallery') // 'gallery' | 'table'
  const [cameras, setCameras] = useState(propCameras)
  const abortControllerRef = useRef(null)

  const fetchFaces = useCallback(async () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
    }
    const ac = new AbortController()
    abortControllerRef.current = ac

    try {
      const camParam = selectedCamera !== 'all' ? `&camera_id=${encodeURIComponent(selectedCamera)}` : ''
      const url = `${API_BASE}/events?type=FACE_DETECTED&limit=${PAGE_SIZE}${camParam}`
      const res = await fetch(url, { signal: ac.signal })
      if (!res.ok) throw new Error(`GET /events failed: ${res.status}`)
      const data = await res.json()
      setEvents(Array.isArray(data) ? data : (data.items || []))
      setLastRefresh(new Date())
    } catch (e) {
      if (e.name === 'AbortError') return
      console.error('Failed to fetch face detections:', e)
    } finally {
      setLoading(false)
    }
  }, [selectedCamera])

  const fetchCameras = useCallback(async () => {
    if (cameras.length > 0) return
    try {
      const res = await fetch(`${API_BASE}/cameras`)
      if (!res.ok) return
      setCameras(await res.json())
    } catch (_) {}
  }, [cameras.length])

  useEffect(() => {
    fetchCameras()
    fetchFaces()
    const timer = setInterval(fetchFaces, POLL_INTERVAL)
    return () => {
      clearInterval(timer)
      if (abortControllerRef.current) {
        abortControllerRef.current.abort()
      }
    }
  }, [fetchCameras, fetchFaces])

  const isEmpty = !loading && events.length === 0

  return (
    <div className="faces-view">
      {/* Header bar */}
      <div className="faces-header">
        <div className="faces-title-row" style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <User size={18} className="text-cyan" />
          <h2 style={{ margin: 0, fontSize: 15, fontWeight: 700 }}>Face Detection Intelligence</h2>
          <span className="faces-badge" style={{
            fontSize: 11,
            fontWeight: 700,
            background: 'rgba(6, 182, 212, 0.15)',
            color: 'var(--cyan)',
            padding: '2px 8px',
            borderRadius: 12,
            border: '1px solid rgba(6, 182, 212, 0.3)'
          }}>
            {events.length} detected
          </span>
        </div>

        <div className="faces-controls">
          {/* View mode toggle */}
          <div style={{ display: 'flex', gap: 4 }}>
            <button
              type="button"
              className={`faces-toggle-btn ${viewMode === 'gallery' ? 'active' : ''}`}
              onClick={() => setViewMode('gallery')}
              title="Gallery Grid View"
            >
              <LayoutGrid size={13} />
              <span>Gallery</span>
            </button>
            <button
              type="button"
              className={`faces-toggle-btn ${viewMode === 'table' ? 'active' : ''}`}
              onClick={() => setViewMode('table')}
              title="Detailed Table View"
            >
              <List size={13} />
              <span>Table</span>
            </button>
          </div>

          {/* Camera filter */}
          <select
            className="faces-cam-filter"
            style={{
              background: 'var(--bg-card)',
              border: '1px solid var(--border)',
              borderRadius: 6,
              color: 'var(--text)',
              fontSize: 12,
              padding: '4px 8px',
            }}
            value={selectedCamera}
            onChange={(e) => setSelectedCamera(e.target.value)}
          >
            <option value="all">All cameras</option>
            {cameras.map((c) => (
              <option key={c.id} value={c.id}>
                {c.id} {c.name ? `(${c.name})` : ''}
              </option>
            ))}
          </select>

          <button
            type="button"
            className="faces-refresh-btn"
            onClick={fetchFaces}
            title="Refresh now"
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 5,
              background: 'var(--bg-card)',
              border: '1px solid var(--border)',
              borderRadius: 6,
              color: 'var(--text-muted)',
              padding: '4px 10px',
              fontSize: 12,
              cursor: 'pointer',
            }}
          >
            <RefreshCw size={12} className={loading ? 'spin-icon' : ''} />
            <span>Refresh</span>
          </button>

          {lastRefresh && (
            <span style={{ fontSize: 11, color: 'var(--text-dim)', marginLeft: 4 }}>
              Updated {relativeTime(lastRefresh)}
            </span>
          )}
        </div>
      </div>

      {/* Content */}
      {loading && events.length === 0 ? (
        <div className="faces-loading" style={{ padding: 32, justifyContent: 'center' }}>
          <div className="spinner-cyan" />
          <span>Loading face events…</span>
        </div>
      ) : isEmpty ? (
        <div className="faces-empty" style={{ padding: 48 }}>
          <User size={44} style={{ opacity: 0.3 }} />
          <div style={{ fontWeight: 600, fontSize: 14 }}>No face detections recorded</div>
          <div style={{ fontSize: 11, opacity: 0.6, maxWidth: 360 }}>
            RetinaFace & ArcFace inference pipelines continuously scan operational feeds for human faces.
          </div>
        </div>
      ) : viewMode === 'gallery' ? (
        <div className="faces-gallery">
          {events.map((evt) => (
            <FaceGalleryCard key={evt.id} event={evt} />
          ))}
        </div>
      ) : (
        <div className="faces-table-wrap">
          <table className="faces-table">
            <thead>
              <tr>
                <th style={{ width: 44 }}>Snap</th>
                <th>Timestamp</th>
                <th>Camera</th>
                <th>Zone / Sector</th>
                <th>Track</th>
                <th>Confidence</th>
                <th>Bounding Box</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {events.map((evt) => {
                const meta = evt.metadata || evt.event_metadata || {}
                const isRestricted = meta.restricted_zone_active || meta.restriction_level === 'RESTRICTED'
                const bbox = meta.face_bbox || meta.bbox
                return (
                  <tr key={evt.id}>
                    <td>
                      {evt.evidence?.snapshot_uri ? (
                        <img
                          src={evt.evidence.snapshot_uri}
                          alt="Face"
                          className="faces-table-thumb"
                        />
                      ) : (
                        <div className="faces-table-thumb-placeholder">
                          <User size={16} />
                        </div>
                      )}
                    </td>
                    <td>
                      {new Date(evt.timestamp).toLocaleString('en-IN', {
                        dateStyle: 'short',
                        timeStyle: 'medium',
                        hour12: false,
                      })}
                    </td>
                    <td>
                      <span className="faces-cam-id">{evt.camera_id}</span>
                    </td>
                    <td>
                      {meta.zone_name || evt.zone_id || '—'}
                      {isRestricted && (
                        <span className="face-restricted" style={{ marginLeft: 6 }}>
                          RESTRICTED
                        </span>
                      )}
                    </td>
                    <td>{evt.track_id != null ? `#${evt.track_id}` : '—'}</td>
                    <td>
                      <ConfBar value={evt.confidence} />
                    </td>
                    <td style={{ fontFamily: 'monospace', fontSize: 11, color: 'var(--text-dim)' }}>
                      {bbox ? `[${bbox.map((v) => Math.round(v)).join(', ')}]` : '—'}
                    </td>
                    <td>
                      <span style={{ fontSize: 11, color: evt.acknowledged ? '#34d399' : '#fbbf24' }}>
                        {evt.acknowledged ? 'Acknowledged' : 'Live Detection'}
                      </span>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function FaceGalleryCard({ event }) {
  const meta = event.metadata || event.event_metadata || {}
  const bbox = meta.face_bbox || meta.bbox || null
  const conf = event.confidence ?? 0
  const isRestricted = meta.restricted_zone_active || meta.restriction_level === 'RESTRICTED'
  const zone = meta.zone_name || event.zone_id || null

  return (
    <div className={`face-card ${isRestricted ? 'border-red-500' : ''}`}>
      <div className="face-thumb-wrap">
        {event.evidence?.snapshot_uri ? (
          <img src={event.evidence.snapshot_uri} alt={`Face ${event.camera_id}`} />
        ) : (
          <div className="face-thumb-placeholder">
            <User size={36} />
          </div>
        )}
        <div className="face-conf-badge">
          {Math.round(conf * 100)}%
        </div>
      </div>

      <div className="face-card-info">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span className="face-cam-label">{event.camera_id}</span>
          <span className="face-ts">{relativeTime(event.timestamp)}</span>
        </div>

        {zone && (
          <div className="face-zone-label" style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            {isRestricted && <ShieldAlert size={10} color="#ef4444" />}
            <span>{zone}</span>
          </div>
        )}

        {isRestricted && (
          <span className="face-restricted">RESTRICTED ZONE</span>
        )}

        {bbox && (
          <div style={{ fontSize: 9, color: 'var(--text-dim)', fontFamily: 'monospace', marginTop: 2 }}>
            Bbox: [{bbox.map((v) => Math.round(v)).join(', ')}]
          </div>
        )}

        {event.track_id != null && (
          <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>
            Track ID: #{event.track_id}
          </div>
        )}
      </div>
    </div>
  )
}
