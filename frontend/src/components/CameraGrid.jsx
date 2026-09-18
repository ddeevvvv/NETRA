import { useState } from 'react'
import { debugStreamUrl } from '../api'
import { VideoOff, WifiOff, AlertTriangle, Radio, PauseCircle, RefreshCw } from 'lucide-react'

/**
 * CameraGrid — renders camera cards showing:
 *  - Live MJPEG annotated stream (embedded via <img> tag)
 *  - Robust error fallback UI with retry capability
 *  - Status badge with Lucide icons (ONLINE, DEGRADED, OFFLINE)
 *  - Measured FPS and FROZEN indicator
 */
export default function CameraGrid({ cameras, healthMap }) {
  if (!cameras.length) {
    return (
      <div className="camera-grid">
        <div className="loading">No cameras registered.</div>
      </div>
    )
  }

  return (
    <div className="camera-grid">
      {cameras.map((cam) => (
        <CameraCard key={cam.id} cam={cam} health={healthMap[cam.id]} />
      ))}
    </div>
  )
}

function CameraCard({ cam, health }) {
  const [streamError, setStreamError] = useState(false)
  const [streamKey, setStreamKey] = useState(0)
  const status = healthStatus(health)

  const handleRetry = () => {
    setStreamError(false)
    setStreamKey((k) => k + 1)
  }

  const isDisconnected = health?.is_connected === false

  return (
    <div className={`camera-card card-${status}`}>
      <div className="camera-card-header">
        <div>
          <div className="camera-name">{cam.id}</div>
          <div className="camera-location">
            {cam.name} · {cam.location}
          </div>
        </div>
        <StatusBadge status={status} fps={health?.measured_fps} />
      </div>

      <div className={`camera-feed-wrap feed-border-${status}`}>
        {isDisconnected ? (
          <div className="camera-feed-placeholder">
            <WifiOff size={24} className="feed-fallback-icon" />
            <span className="fallback-title">Camera Disconnected</span>
            <span className="fallback-sub">RTSP endpoint unreachable</span>
          </div>
        ) : streamError ? (
          <div className="camera-feed-placeholder">
            <VideoOff size={24} className="feed-fallback-icon" />
            <span className="fallback-title">Feed Unavailable</span>
            <span className="fallback-sub">MJPEG stream interrupted or failed to load</span>
            <button className="stream-retry-btn" onClick={handleRetry}>
              <RefreshCw size={12} />
              <span>Retry Stream</span>
            </button>
          </div>
        ) : (
          <img
            key={streamKey}
            src={`${debugStreamUrl(cam.id)}?t=${streamKey}`}
            alt={`Live feed: ${cam.id}`}
            title="Live annotated stream"
            onLoad={() => setStreamError(false)}
            onError={() => setStreamError(true)}
          />
        )}
      </div>

      <div className="camera-card-footer">
        <span className="footer-stats">
          {health
            ? `${health.measured_fps?.toFixed(1)} fps · ${health.active_zones_count ?? 0} zone(s)`
            : 'Loading health...'}
        </span>
        {health?.is_frozen && (
          <span className="frozen-badge">
            <PauseCircle size={12} />
            <span>FROZEN</span>
          </span>
        )}
      </div>
    </div>
  )
}

function healthStatus(health) {
  if (!health) return 'unknown'
  if (!health.is_connected) return 'offline'
  if (health.is_frozen || health.is_low_fps) return 'degraded'
  return 'ok'
}

function StatusBadge({ status, fps }) {
  const labels = { ok: 'ONLINE', degraded: 'DEGRADED', offline: 'OFFLINE', unknown: 'UNKNOWN' }
  const colors = {
    ok: 'var(--sev-info)',
    degraded: 'var(--sev-warning)',
    offline: 'var(--sev-high)',
    unknown: 'var(--text-dim)',
  }

  const icons = {
    ok: <Radio size={11} className="pulse-icon" />,
    degraded: <AlertTriangle size={11} />,
    offline: <VideoOff size={11} />,
    unknown: null,
  }

  return (
    <div className={`status-badge-wrap status-${status}`} style={{ color: colors[status] }}>
      {icons[status]}
      <span className="status-badge-text">{labels[status]}</span>
    </div>
  )
}
