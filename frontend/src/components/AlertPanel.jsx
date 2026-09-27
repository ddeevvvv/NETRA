import { useState, useEffect, useRef, useCallback } from 'react'
import { connectAlertStream, acknowledgeEvent, acknowledgeBulkEvents, getEvents } from '../api'
import {
  AlertOctagon,
  AlertTriangle,
  AlertCircle,
  Info,
  Check,
  ChevronDown,
  ChevronUp,
  Image as ImageIcon,
  Radio,
  Clock,
  Shield,
  Tag,
  Trash2,
} from 'lucide-react'

const MAX_ALERTS = 200 // cap in-memory list

/**
 * AlertPanel — real-time alert feed via WebSocket.
 * - Auto-reconnects on disconnect
 * - Color-coded by severity with Lucide icons
 * - Expandable cards revealing full metadata & evidence snapshots
 * - Operator Acknowledge button calling backend API
 */
export default function AlertPanel({ onStatsUpdate, onNewAlert, onTrackPlate, onAcknowledge }) {
  const [alerts, setAlerts] = useState([])
  const [wsStatus, setWsStatus] = useState('connecting')
  const [ackingId, setAckingId] = useState(null)
  const [newFlash, setNewFlash] = useState(false)
  const [clearing, setClearing] = useState(false)
  const [confirmClear, setConfirmClear] = useState(false)
  const bottomRef = useRef(null)

  // Seed recent alerts on mount from backend so existing alerts appear immediately
  useEffect(() => {
    getEvents({ limit: 50 })
      .then((data) => {
        if (Array.isArray(data) && data.length > 0) {
          setAlerts((prev) => {
            const existingIds = new Set(prev.map((a) => a.id))
            const newItems = data.filter((a) => !existingIds.has(a.id))
            return [...prev, ...newItems].slice(0, MAX_ALERTS)
          })
        }
      })
      .catch((err) => console.error('Failed to load initial alerts:', err))
  }, [])

  const handleMessage = useCallback((event) => {
    setAlerts((prev) => {
      // Deduplicate by id — WS may send the same event twice
      if (prev.some((a) => a.id === event.id)) {
        return prev.map((a) => (a.id === event.id ? { ...a, ...event } : a))
      }
      const next = [event, ...prev] // newest first
      return next.slice(0, MAX_ALERTS)
    })
    // Forward to parent for camera grid alert highlighting
    onNewAlert?.(event)
    // Brief flash on new real event
    setNewFlash(true)
    setTimeout(() => setNewFlash(false), 600)
  }, [onNewAlert])

  useEffect(() => {
    const cleanup = connectAlertStream(handleMessage, setWsStatus)
    return cleanup
  }, [handleMessage])

  // Notify parent of updated stats whenever alerts list changes
  useEffect(() => {
    if (!onStatsUpdate) return
    const unacked = alerts.filter((a) => !a.acknowledged).length
    onStatsUpdate(alerts, unacked)
  }, [alerts, onStatsUpdate])

  const handleAck = async (alert, e) => {
    e.stopPropagation()
    setAckingId(alert.id)
    try {
      const updated = await acknowledgeEvent(alert.id, 'operator')
      setAlerts((prev) =>
        prev.map((a) =>
          a.id === updated.id
            ? { ...a, acknowledged: true, acknowledged_by: updated.acknowledged_by }
            : a
        )
      )
      onAcknowledge?.(1)
    } catch (err) {
      console.error('Acknowledge failed:', err)
    } finally {
      setAckingId(null)
    }
  }

  const handleClearAll = async () => {
    if (!confirmClear) {
      // First click: arm the confirm state, auto-reset after 3 s
      setConfirmClear(true)
      setTimeout(() => setConfirmClear(false), 3000)
      return
    }
    setClearing(true)
    setConfirmClear(false)
    try {
      const unackedBefore = alerts.filter((a) => !a.acknowledged).length
      await acknowledgeBulkEvents({})
      setAlerts((prev) => prev.map((a) => ({ ...a, acknowledged: true, acknowledged_by: 'operator' })))
      onAcknowledge?.(unackedBefore || 1)
    } catch (err) {
      console.error('Bulk acknowledge failed:', err)
    } finally {
      setClearing(false)
    }
  }

  const wsLabel = {
    connected: 'Live Stream',
    reconnecting: 'Reconnecting…',
    error: 'Connection Error',
    connecting: 'Connecting…',
  }

  return (
    <div className={`alert-panel-root ${newFlash ? 'alert-new-flash' : ''}`}>
      <div className="alert-section-header">
        <div className="alert-header-title">
          <Radio size={13} className={wsStatus === 'connected' ? 'pulse-icon' : ''} />
          <span className="section-title" style={{ padding: 0 }}>
            Live Alerts
          </span>
        </div>
        <div className="ws-status">
          <div
            className={`ws-dot ${
              wsStatus === 'connected' ? 'connected live-pulse' : wsStatus === 'error' ? 'error' : ''
            }`}
          />
          <span>{wsLabel[wsStatus] ?? wsStatus}</span>
          <span className="alert-count">({alerts.length})</span>
        </div>
        {alerts.some((a) => !a.acknowledged) && (
          <button
            type="button"
            className={`btn-clear-all ${confirmClear ? 'btn-clear-confirm' : ''}`}
            onClick={handleClearAll}
            disabled={clearing}
            title={confirmClear ? 'Click again to confirm clearing all alerts' : 'Bulk-acknowledge all active alerts'}
          >
            <Trash2 size={11} />
            <span>{clearing ? 'Clearing…' : confirmClear ? 'Confirm?' : 'Clear All'}</span>
          </button>
        )}
      </div>

      <div className="alert-list">
        {alerts.length === 0 && (
          <div className="radar-empty-state">
            <div className="radar-viewport">
              <div className="radar-ring ring-1" />
              <div className="radar-ring ring-2" />
              <div className="radar-ring ring-3" />
              <div className="radar-crosshair-h" />
              <div className="radar-crosshair-v" />
              <div className="radar-sweep" />
              <div className="radar-blip" />
            </div>
            <div className="radar-content">
              <div className="radar-headline">SYSTEM ARMED // SCANNING SECTOR ALPHA</div>
              <div className="radar-subtext">All virtual fences nominal · 0 active perimeter breaches</div>
            </div>
          </div>
        )}
        {alerts.map((alert) => (
          <AlertItem
            key={alert.id}
            alert={alert}
            acking={ackingId === alert.id}
            onAck={handleAck}
            onTrackPlate={onTrackPlate}
          />
        ))}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}

function AlertItem({ alert, acking, onAck, onTrackPlate }) {
  const [isExpanded, setIsExpanded] = useState(false)

  const ts = new Date(alert.timestamp)
  const timeStr = ts.toLocaleTimeString('en-IN', { hour12: false })
  const dateStr = ts.toLocaleDateString('en-IN', { month: 'short', day: 'numeric' })

  const meta = alert.metadata || alert.event_metadata || {}
  const snapshotUri = alert.evidence?.snapshot_uri
  const detectedPlate = meta.license_plate || meta.plate_text || meta.plate

  const metaParts = []
  if (alert.camera_id) metaParts.push(alert.camera_id)
  if (alert.object_type && alert.object_type !== 'system') metaParts.push(alert.object_type)
  if (alert.confidence != null) metaParts.push(`conf: ${(alert.confidence * 100).toFixed(0)}%`)
  if (meta.condition) metaParts.push(meta.condition)

  return (
    <div
      className={`alert-item sev-${alert.severity} ${alert.acknowledged ? 'acked' : ''} ${
        isExpanded ? 'expanded' : ''
      }`}
      onClick={() => setIsExpanded(!isExpanded)}
    >
      <div className="alert-header-row">
        <div className="alert-badge-group">
          <SeverityBadge severity={alert.severity} />
          {alert.camera_id && <span className="alert-cam-tag">{alert.camera_id}</span>}
          <span className="alert-type">{alert.type}</span>
        </div>
        <div className="alert-header-right">
          {snapshotUri && !isExpanded && (
            <img
              src={snapshotUri}
              alt="Thumbnail"
              className="alert-thumb-mini"
              onError={(e) => (e.target.style.display = 'none')}
            />
          )}
          <span className="alert-ts">
            {dateStr} {timeStr}
          </span>
          <button className="expand-toggle-btn" aria-label="Expand alert details">
            {isExpanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
          </button>
        </div>
      </div>

      {metaParts.length > 0 && <div className="alert-meta">{metaParts.join(' · ')}</div>}

      {alert.zone_id && (
        <div className="alert-zone">
          <Shield size={11} className="zone-icon" />
          <span>Zone: {alert.zone_id}</span>
        </div>
      )}

      {/* ── Expanded Detail View ── */}
      {isExpanded && (
        <div className="alert-expanded-content" onClick={(e) => e.stopPropagation()}>
          {snapshotUri && (
            <div className="alert-snapshot-wrap">
              <img
                src={snapshotUri}
                alt="Event Evidence"
                className="alert-snapshot-img"
              />
              <div className="snapshot-caption">
                <ImageIcon size={10} />
                <span>Evidence Snapshot</span>
              </div>
            </div>
          )}

          <div className="alert-kv-grid">
            <div className="alert-kv-row">
              <span className="kv-key">Event ID</span>
              <span className="kv-val mono">{alert.id}</span>
            </div>
            {alert.track_id != null && (
              <div className="alert-kv-row">
                <span className="kv-key">Track ID</span>
                <span className="kv-val">#{alert.track_id}</span>
              </div>
            )}
            {Object.entries(meta).map(([key, val]) => {
              const displayVal =
                typeof val === 'object' && val !== null
                  ? JSON.stringify(val)
                  : String(val)
              return (
                <div key={key} className="alert-kv-row">
                  <span className="kv-key">{formatKey(key)}</span>
                  <span className="kv-val">{displayVal}</span>
                </div>
              )
            })}
          </div>
        </div>
      )}

      <div className="alert-footer-row">
        {detectedPlate && (
          <button
            type="button"
            className="btn-track-plate-shortcut"
            onClick={(e) => {
              e.stopPropagation()
              onTrackPlate?.(detectedPlate)
            }}
            title={`Track movement history for plate ${detectedPlate}`}
          >
            <Tag size={11} />
            <span>Track Plate ({detectedPlate})</span>
          </button>
        )}

        {alert.acknowledged ? (
          <span className="acked-label">
            <Check size={11} className="ack-check-icon" />
            <span>Acked by {alert.acknowledged_by ?? 'operator'}</span>
          </span>
        ) : (
          <button
            className="ack-btn"
            onClick={(e) => onAck(alert, e)}
            disabled={acking}
          >
            <Check size={11} />
            <span>{acking ? 'Acknowledging…' : 'Acknowledge'}</span>
          </button>
        )}
      </div>
    </div>
  )
}

function SeverityBadge({ severity }) {
  const icons = {
    CRITICAL: <AlertOctagon size={11} />,
    HIGH: <AlertTriangle size={11} />,
    WARNING: <AlertCircle size={11} />,
    INFO: <Info size={11} />,
  }

  return (
    <span className={`sev-badge sev-${severity}`}>
      {icons[severity]}
      <span>{severity}</span>
    </span>
  )
}

function formatKey(str) {
  return str
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase())
}
