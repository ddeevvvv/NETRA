import { useState, useRef, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { debugStreamUrl, createZone, updateZone } from '../api'
import ZoneEditorModal from './ZoneEditorModal'
import {
  VideoOff,
  WifiOff,
  AlertTriangle,
  Radio,
  PauseCircle,
  RefreshCw,
  PenTool,
  Undo2,
  Check,
  X,
  Zap,
  RotateCcw,
  Clock,
} from 'lucide-react'

/**
 * CameraGrid — renders camera cards showing:
 *  - Live MJPEG annotated stream (embedded via <img> tag)
 *  - Interactive "Add Zone" drawing mode with real-time SVG polygon overlay
 *  - Real-time alert-triggered visual highlighting with auto-fade Framer Motion glow
 *  - Robust error fallback UI with retry capability
 *  - Status badge with Lucide icons (ONLINE, DEGRADED, OFFLINE)
 *  - Measured FPS and FROZEN indicator
 */
export default function CameraGrid({
  cameras,
  healthMap,
  alertHighlightMap = {},
  drawTarget = null,
  onClearDrawTarget,
  onZoneChange,
}) {
  const [activeDrawCamId, setActiveDrawCamId] = useState(null)
  const [editingZone, setEditingZone] = useState(null)
  const [drawPoints, setDrawPoints] = useState([])
  const [modalState, setModalState] = useState({ isOpen: false, mode: 'create', zone: null, polygonCoords: null, cameraId: '' })
  const [streamRefreshKeys, setStreamRefreshKeys] = useState({})
  const [selectedCamId, setSelectedCamId] = useState(null)

  // Handle external redraw trigger from ZonesList
  useEffect(() => {
    if (drawTarget?.cameraId) {
      setActiveDrawCamId(drawTarget.cameraId)
      setEditingZone(drawTarget.zone || null)
      setDrawPoints([])
      onClearDrawTarget?.()
    }
  }, [drawTarget, onClearDrawTarget])

  const handleStartDraw = (cameraId, zone = null) => {
    setActiveDrawCamId(cameraId)
    setEditingZone(zone)
    setDrawPoints([])
  }

  const handleCancelDraw = () => {
    setActiveDrawCamId(null)
    setEditingZone(null)
    setDrawPoints([])
  }

  const handleFinishDraw = () => {
    if (drawPoints.length < 3) return
    setModalState({
      isOpen: true,
      mode: editingZone ? 'edit' : 'create',
      zone: editingZone,
      polygonCoords: drawPoints,
      cameraId: activeDrawCamId,
    })
  }

  const handleModalClose = () => {
    setModalState((prev) => ({ ...prev, isOpen: false }))
    handleCancelDraw()
  }

  const handleModalSave = async (payload) => {
    if (modalState.mode === 'create') {
      await createZone(payload)
    } else if (modalState.mode === 'edit' && modalState.zone?.id) {
      await updateZone(modalState.zone.id, payload)
    }

    // Bump stream refresh key for camera to ensure immediate visual pickup
    const camId = payload.camera_id || activeDrawCamId
    if (camId) {
      setStreamRefreshKeys((prev) => ({ ...prev, [camId]: (prev[camId] || 0) + 1 }))
    }

    onZoneChange?.()
  }

  if (!cameras.length) {
    return (
      <div className="camera-grid">
        <div className="loading">No cameras registered.</div>
      </div>
    )
  }

  const selectedCam = cameras.find((c) => c.id === selectedCamId) || null
  const gridClass = cameras.length >= 9 ? 'camera-grid camera-grid-9' : 'camera-grid'

  return (
    <>
      {/* Preview panel — appears when a tile is clicked */}
      {selectedCam && (
        <div className="camera-preview-panel">
          <div className="camera-preview-header">
            <span className="camera-preview-title">
              {selectedCam.name || selectedCam.id}
            </span>
            <button
              className="camera-preview-close"
              onClick={() => setSelectedCamId(null)}
              aria-label="Close preview"
            >
              ×
            </button>
          </div>
          <div className="camera-preview-feed">
            <img
              src={`/api/v1/cameras/${selectedCam.id}/stream?key=${streamRefreshKeys[selectedCam.id] || 0}`}
              alt={`Preview: ${selectedCam.name || selectedCam.id}`}
              className="camera-preview-img"
              onError={(e) => { e.currentTarget.style.display = 'none' }}
            />
          </div>
          <div className="camera-preview-meta">
            <span>{selectedCam.id}</span>
            <span>•</span>
            <span>{selectedCam.location || '—'}</span>
            <span>•</span>
            <span style={{ color: healthMap[selectedCam.id]?.is_connected ? 'var(--netra-cyan)' : 'var(--netra-danger)' }}>
              {healthMap[selectedCam.id]?.connection_state ?? 'OFFLINE'}
            </span>
          </div>
        </div>
      )}

      <div className={gridClass}>
        {cameras.map((cam) => (
          <CameraCard
            key={cam.id}
            cam={cam}
            health={healthMap[cam.id]}
            alertHighlight={alertHighlightMap[cam.id]}
            refreshKey={streamRefreshKeys[cam.id] || 0}
            isDrawing={activeDrawCamId === cam.id}
            drawPoints={activeDrawCamId === cam.id ? drawPoints : []}
            setDrawPoints={setDrawPoints}
            onStartDraw={() => handleStartDraw(cam.id)}
            onCancelDraw={handleCancelDraw}
            onFinishDraw={handleFinishDraw}
            isSelected={selectedCamId === cam.id}
            onSelect={() => setSelectedCamId(cam.id === selectedCamId ? null : cam.id)}
          />
        ))}
      </div>

      <ZoneEditorModal
        isOpen={modalState.isOpen}
        mode={modalState.mode}
        zone={modalState.zone}
        polygonCoords={modalState.polygonCoords}
        cameraId={modalState.cameraId}
        onSave={handleModalSave}
        onRedraw={(z) => handleStartDraw(z.camera_id, z)}
        onClose={handleModalClose}
      />
    </>
  )
}

function CameraCard({
  cam,
  health,
  alertHighlight,
  refreshKey,
  isDrawing,
  drawPoints,
  setDrawPoints,
  onStartDraw,
  onCancelDraw,
  onFinishDraw,
  isSelected = false,
  onSelect,
}) {
  const [streamError, setStreamError] = useState(false)
  const [localRetryKey, setLocalRetryKey] = useState(0)
  const [mousePos, setMousePos] = useState(null)
  const feedWrapRef = useRef(null)
  const status = healthStatus(health)

  const handleRetry = () => {
    setStreamError(false)
    setLocalRetryKey((k) => k + 1)
  }

  const isDisconnected = health?.is_connected === false
  const connState = health?.connection_state ?? 'OFFLINE'

  // Click on video feed to add a vertex
  const handleFeedClick = (e) => {
    if (!isDrawing) return
    const rect = e.currentTarget.getBoundingClientRect()
    if (!rect.width || !rect.height) return

    const rawX = (e.clientX - rect.left) / rect.width
    const rawY = (e.clientY - rect.top) / rect.height
    // Clamp to [0.0, 1.0] and round to 4 decimal places
    const x = Math.max(0, Math.min(1, Math.round(rawX * 10000) / 10000))
    const y = Math.max(0, Math.min(1, Math.round(rawY * 10000) / 10000))

    setDrawPoints((prev) => [...prev, [x, y]])
  }

  // Mouse move over video feed for rubber-band dynamic guide line
  const handleFeedMouseMove = (e) => {
    if (!isDrawing) return
    const rect = e.currentTarget.getBoundingClientRect()
    if (!rect.width || !rect.height) return

    const x = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width))
    const y = Math.max(0, Math.min(1, (e.clientY - rect.top) / rect.height))
    setMousePos({ x, y })
  }

  const handleFeedMouseLeave = () => {
    setMousePos(null)
  }

  // Double click to finish polygon if >= 3 points
  const handleFeedDoubleClick = (e) => {
    if (!isDrawing) return
    e.preventDefault()
    e.stopPropagation()
    if (drawPoints.length >= 3) {
      onFinishDraw()
    }
  }

  const handleUndoPoint = (e) => {
    e.stopPropagation()
    setDrawPoints((prev) => prev.slice(0, -1))
  }

  const totalStreamKey = `${refreshKey}_${localRetryKey}`

  const sevLower = alertHighlight?.severity?.toLowerCase() || 'info'
  const highlightColor = sevLower === 'critical' 
    ? 'var(--sev-critical)' 
    : sevLower === 'high' 
      ? 'var(--sev-high)' 
      : sevLower === 'warning' 
        ? 'var(--sev-warning)' 
        : 'var(--sev-info)'

  return (
    <motion.div
      className={`camera-card card-${status} ${isDrawing ? 'card-drawing-mode' : ''} ${
        alertHighlight ? `alert-active alert-${sevLower}` : ''
      } ${isSelected ? 'card-selected-preview' : ''}`}
      animate={
        alertHighlight
          ? {
              boxShadow: [
                `0 0 0px ${highlightColor}`,
                `0 0 20px ${highlightColor}`,
                `0 0 6px ${highlightColor}`,
              ],
              borderColor: highlightColor,
            }
          : {
              boxShadow: '0 0 0px transparent',
            }
      }
      transition={{
        duration: 0.8,
        repeat: alertHighlight ? Infinity : 0,
        repeatType: 'reverse',
        ease: 'easeInOut',
      }}
    >
      <div className="camera-card-header">
        <div>
          <div className="camera-name-wrap">
            <span className="camera-name">{cam.id}</span>
            <AnimatePresence>
              {alertHighlight && (
                <motion.span
                  initial={{ opacity: 0, scale: 0.6, x: -5 }}
                  animate={{ opacity: 1, scale: 1, x: 0 }}
                  exit={{ opacity: 0, scale: 0.6, x: -5 }}
                  className={`alert-trigger-badge sev-bg-${sevLower}`}
                  title={`Active alert: ${alertHighlight.type} (${alertHighlight.severity})`}
                >
                  <Zap size={10} className="pulse-icon" />
                  <span>{alertHighlight.severity}: {alertHighlight.type}</span>
                </motion.span>
              )}
            </AnimatePresence>
          </div>
          <div className="camera-location">
            {cam.name} · {cam.location}
          </div>
        </div>
        <div className="camera-header-actions">
          <button
            type="button"
            className="btn-preview-expand"
            onClick={(e) => { e.stopPropagation(); onSelect?.() }}
            title={isSelected ? 'Close preview' : 'Open full preview'}
            aria-label={isSelected ? 'Close preview' : 'Open full preview'}
          >
            {isSelected ? <X size={11} /> : <RotateCcw size={11} style={{ transform: 'rotate(45deg)' }} />}
          </button>
          <button
            type="button"
            className={`btn-add-zone ${isDrawing ? 'btn-drawing-active' : ''}`}
            onClick={() => (isDrawing ? onCancelDraw() : onStartDraw())}
            title={isDrawing ? 'Cancel drawing' : 'Draw a new virtual fence zone on this camera feed'}
          >
            <PenTool size={11} />
            <span>{isDrawing ? 'Cancel Draw' : 'Add Zone'}</span>
          </button>
          <StatusBadge status={status} fps={health?.measured_fps} />
        </div>
      </div>

      <div
        ref={feedWrapRef}
        className={`camera-feed-wrap feed-border-${status} ${isDrawing ? 'feed-drawing' : ''}`}
        onClick={handleFeedClick}
        onMouseMove={handleFeedMouseMove}
        onMouseLeave={handleFeedMouseLeave}
        onDoubleClick={handleFeedDoubleClick}
      >
        {isDisconnected ? (
          <div className="camera-feed-placeholder">
            {connState === 'RECONNECTING' ? (
              <RotateCcw size={24} className="feed-fallback-icon spin-icon" />
            ) : (
              <WifiOff size={24} className="feed-fallback-icon" />
            )}
            <span className="fallback-title">
              {connState === 'RECONNECTING' ? 'Reconnecting…' : 'Camera Offline'}
            </span>
            <span className="fallback-sub">
              {connState === 'RECONNECTING'
                ? `Attempt #${health?.reconnect_attempt_count ?? '?'} — RTSP endpoint unreachable`
                : 'RTSP stream could not be established'}
            </span>
            {health?.last_seen_at && (
              <span className="fallback-lastseen">
                <Clock size={11} />
                Last seen: {formatRelativeTime(health.last_seen_at)}
              </span>
            )}
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
            key={totalStreamKey}
            src={`${debugStreamUrl(cam.id)}?t=${totalStreamKey}`}
            alt={`Live feed: ${cam.id}`}
            title="Live annotated stream"
            onLoad={() => setStreamError(false)}
            onError={() => setStreamError(true)}
          />
        )}

        {/* ── Active Polygon Drawing Overlay ── */}
        {isDrawing && (
          <>
            {/* Top helper banner */}
            <div className="drawing-help-banner">
              <PenTool size={11} className="pulse-icon" />
              <span>Click on frame to place vertices (min 3). Double-click to finish.</span>
            </div>

            {/* SVG Canvas Overlay */}
            <svg
              className="drawing-svg-overlay"
              viewBox="0 0 100 100"
              preserveAspectRatio="none"
            >
              {/* Completed/preview polygon fill */}
              {drawPoints.length >= 3 && (
                <polygon
                  points={drawPoints.map(([x, y]) => `${x * 100},${y * 100}`).join(' ')}
                  className="drawing-polygon-preview"
                />
              )}

              {/* Connecting lines between points */}
              {drawPoints.length >= 2 && (
                <polyline
                  points={drawPoints.map(([x, y]) => `${x * 100},${y * 100}`).join(' ')}
                  className="drawing-polyline"
                />
              )}

              {/* Trailing rubber-band guide line from last point to mouse cursor */}
              {drawPoints.length >= 1 && mousePos && (
                <line
                  x1={drawPoints[drawPoints.length - 1][0] * 100}
                  y1={drawPoints[drawPoints.length - 1][1] * 100}
                  x2={mousePos.x * 100}
                  y2={mousePos.y * 100}
                  className="drawing-guide-line"
                />
              )}

              {/* Closing line preview back to start if >= 2 points */}
              {drawPoints.length >= 2 && mousePos && (
                <line
                  x1={mousePos.x * 100}
                  y1={mousePos.y * 100}
                  x2={drawPoints[0][0] * 100}
                  y2={drawPoints[0][1] * 100}
                  className="drawing-close-guide"
                />
              )}

              {/* Drawn vertices */}
              {drawPoints.map(([px, py], idx) => (
                <g key={idx}>
                  {idx === 0 && (
                    <circle
                      cx={px * 100}
                      cy={py * 100}
                      r="3.2"
                      className="drawing-vertex-pulse"
                    />
                  )}
                  <circle
                    cx={px * 100}
                    cy={py * 100}
                    r="1.6"
                    className={`drawing-vertex ${idx === 0 ? 'drawing-vertex-first' : ''}`}
                  />
                </g>
              ))}
            </svg>

            {/* Bottom floating toolbar */}
            <div className="drawing-toolbar" onClick={(e) => e.stopPropagation()}>
              <span className="drawing-point-count">
                <strong>{drawPoints.length}</strong> pt{drawPoints.length === 1 ? '' : 's'}{' '}
                {drawPoints.length < 3 ? `(need ${3 - drawPoints.length} more)` : '✓ shape ready'}
              </span>
              <div className="drawing-toolbar-actions">
                <button
                  type="button"
                  className="drawing-btn btn-undo"
                  onClick={handleUndoPoint}
                  disabled={drawPoints.length === 0}
                  title="Undo last placed point"
                >
                  <Undo2 size={11} />
                  <span>Undo</span>
                </button>
                <button
                  type="button"
                  className="drawing-btn btn-finish"
                  onClick={onFinishDraw}
                  disabled={drawPoints.length < 3}
                  title={drawPoints.length < 3 ? 'Click at least 3 points first' : 'Finish polygon and set rules'}
                >
                  <Check size={11} />
                  <span>Finish Shape</span>
                </button>
                <button
                  type="button"
                  className="drawing-btn btn-cancel"
                  onClick={onCancelDraw}
                  title="Cancel drawing mode"
                >
                  <X size={11} />
                  <span>Cancel</span>
                </button>
              </div>
            </div>
          </>
        )}
      </div>

      <div className="camera-card-footer">
        <span className="footer-stats">
          {health
            ? `${health.measured_fps?.toFixed(1) ?? '0.0'} fps · ${health.active_zones_count ?? 0} zone(s)`
            : 'Loading health...'}
        </span>
        <span className="footer-right">
          {health?.last_seen_at && (
            <span className="footer-lastseen" title={new Date(health.last_seen_at).toLocaleString()}>
              <Clock size={10} />
              {formatRelativeTime(health.last_seen_at)}
            </span>
          )}
          {health?.is_frozen && (
            <span className="frozen-badge">
              <PauseCircle size={12} />
              <span>FROZEN</span>
            </span>
          )}
        </span>
      </div>
    </motion.div>
  )
}

/**
 * Maps the backend connection_state + frozen/low-fps flags to a display status.
 * Priority: no health → unknown; RECONNECTING → reconnecting; offline → offline;
 * frozen/low-fps → degraded; else → ok.
 */
function healthStatus(health) {
  if (!health) return 'unknown'
  const cs = health.connection_state ?? ''
  if (cs === 'RECONNECTING') return 'reconnecting'
  if (!health.is_connected || cs === 'OFFLINE') return 'offline'
  if (health.is_frozen || health.is_low_fps || cs === 'DEGRADED') return 'degraded'
  return 'ok'
}

/** Human-friendly relative time, e.g. "3 s ago" or "2 min ago". */
function formatRelativeTime(isoString) {
  if (!isoString) return ''
  const diffSec = Math.round((Date.now() - new Date(isoString).getTime()) / 1000)
  if (diffSec < 5) return 'just now'
  if (diffSec < 60) return `${diffSec}s ago`
  const diffMin = Math.round(diffSec / 60)
  if (diffMin < 60) return `${diffMin}m ago`
  return `${Math.round(diffMin / 60)}h ago`
}

function StatusBadge({ status, fps }) {
  const labels = {
    ok: 'ONLINE',
    degraded: 'DEGRADED',
    reconnecting: 'RECONNECTING',
    offline: 'OFFLINE',
    unknown: 'UNKNOWN',
  }
  const colors = {
    ok: 'var(--status-nominal)',
    degraded: 'var(--sev-warning)',
    reconnecting: 'var(--sev-warning)',
    offline: 'var(--sev-high)',
    unknown: 'var(--text-dim)',
  }

  const icons = {
    ok: <Radio size={11} className="pulse-icon" />,
    degraded: <AlertTriangle size={11} />,
    reconnecting: <RotateCcw size={11} className="spin-icon" />,
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
