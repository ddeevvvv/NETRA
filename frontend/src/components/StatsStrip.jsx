import { Camera, MapPin, Bell, AlertOctagon } from 'lucide-react'

/**
 * StatsStrip — compact single-row summary bar shown between the navbar and the
 * main dashboard grid. Derives all values from already-fetched data — no new
 * network calls.
 *
 * Props:
 *   cameras       – array from GET /api/v1/cameras
 *   healthMap     – { [cameraId]: healthObject } polled by App.jsx
 *   alerts        – full alert array from AlertPanel (passed via callback)
 *   unackedCount  – live count of un-acknowledged alerts
 *   zoneCount     – total active zones across all cameras (from ZonesList fetch)
 */
export default function StatsStrip({
  cameras = [],
  healthMap = {},
  alerts = [],
  unackedCount = 0,
  zoneCount = 0,
}) {
  // Cameras ONLINE = those that are connected and not OFFLINE
  const onlineCount = cameras.filter((c) => {
    const h = healthMap[c.id]
    if (!h) return false
    return Boolean(h.is_connected && h.connection_state !== 'OFFLINE')
  }).length

  const degradedCount = cameras.filter((c) => {
    const h = healthMap[c.id]
    return h && (h.is_low_fps || h.is_frozen || h.connection_state === 'DEGRADED')
  }).length

  // Alerts TODAY — filter by today's date (local)
  const todayStr = new Date().toDateString()
  const todayCount = alerts.filter((a) => {
    try {
      return new Date(a.timestamp).toDateString() === todayStr
    } catch {
      return false
    }
  }).length

  const isAllOnline = onlineCount === cameras.length && cameras.length > 0

  const stats = [
    {
      id: 'stat-cameras-online',
      label: 'Cameras Online',
      value: `${onlineCount} / ${cameras.length}`,
      icon: Camera,
      tag: isAllOnline ? (degradedCount > 0 ? 'DEGRADED' : 'ONLINE') : cameras.length === 0 ? 'OFFLINE' : 'DEGRADED',
      tagType: isAllOnline ? (degradedCount > 0 ? 'amber' : 'green') : cameras.length === 0 ? 'dim' : 'amber',
      pulse: isAllOnline && degradedCount === 0,
    },
    {
      id: 'stat-active-zones',
      label: 'Active Zones',
      value: zoneCount,
      icon: MapPin,
      tag: zoneCount > 0 ? 'ACTIVE' : 'NONE',
      tagType: zoneCount > 0 ? 'cyan' : 'dim',
      pulse: false,
    },
    {
      id: 'stat-alerts-today',
      label: 'Alerts Today',
      value: todayCount,
      icon: Bell,
      tag: todayCount > 0 ? 'LOGGED' : 'QUIET',
      tagType: todayCount > 0 ? 'amber' : 'dim',
      pulse: false,
    },
    {
      id: 'stat-live-unacked',
      label: 'Unacknowledged',
      value: unackedCount,
      icon: AlertOctagon,
      tag: unackedCount > 0 ? 'ACTION REQ' : 'NOMINAL',
      tagType: unackedCount > 0 ? 'red' : 'green',
      pulse: unackedCount > 0,
      isUrgent: unackedCount > 0,
    },
  ]

  return (
    <div className="stats-strip">
      {stats.map(({ id, label, value, icon: Icon, tag, tagType, pulse, isUrgent }) => (
        <div key={id} id={id} className={`stat-card ${isUrgent ? 'stat-card-urgent' : ''}`}>
          <div className="stat-icon-wrap">
            <Icon size={15} className={`stat-icon ${pulse ? 'pulse-icon' : ''}`} />
          </div>
          <div className="stat-body">
            <span className="stat-value">{value}</span>
            <div className="stat-meta-row">
              <span className="stat-label">{label}</span>
              <span className={`stat-micro-pill pill-${tagType}`}>
                <span className={`micro-dot dot-${tagType} ${pulse ? 'live-pulse' : ''}`} />
                {tag}
              </span>
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}
