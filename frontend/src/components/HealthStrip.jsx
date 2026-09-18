import { Activity, AlertTriangle, Radio } from 'lucide-react'

/**
 * HealthStrip — bottom bar showing live health per camera.
 * Consumes healthMap passed from App.jsx (no duplicate network polling).
 */
export default function HealthStrip({ cameras, healthMap = {} }) {
  return (
    <div className="health-strip">
      <div className="health-strip-title">
        <Activity size={12} className="accent-icon" />
        <span className="health-label">System Health</span>
      </div>

      <div className="health-chips-container">
        {cameras.map((cam) => {
          const h = healthMap[cam.id]
          const dotClass = healthDotClass(h)
          return (
            <div
              className={`health-chip chip-${dotClass}`}
              key={cam.id}
              title={h ? `Status: ${dotClass.toUpperCase()}\nFPS: ${h.measured_fps ?? 'N/A'}\nFailures: ${h.active_failures?.join(', ') || 'None'}` : 'Loading...'}
            >
              <div className={`health-dot ${dotClass}`} />
              <span className="health-cam-id">{cam.id}</span>
              {h?.measured_fps != null && (
                <span className="health-fps">{h.measured_fps.toFixed(1)} fps</span>
              )}
              {h?.active_failures?.length > 0 && (
                <span className="health-failure-tag">
                  <AlertTriangle size={10} />
                  <span>{h.active_failures.join(', ')}</span>
                </span>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

function healthDotClass(h) {
  if (!h) return 'unknown'
  if (!h.is_connected) return 'offline'
  if (h.is_frozen || h.is_low_fps) return 'degraded'
  return 'ok'
}
