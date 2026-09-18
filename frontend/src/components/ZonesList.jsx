import { useState, useEffect } from 'react'
import { getZones } from '../api'
import { ShieldAlert, Eye, Clock, ChevronDown, ChevronUp, Layers } from 'lucide-react'

/**
 * ZonesList — Compact, collapsible section showing active virtual-fence zones.
 * Displays zone ID, name, restriction level, and dwell threshold.
 */
export default function ZonesList({ cameras, onZoneCount }) {
  const [zones, setZones] = useState([])
  const [isExpanded, setIsExpanded] = useState(true)
  const [selectedCamId, setSelectedCamId] = useState('')

  // Default to first camera if not set
  useEffect(() => {
    if (cameras.length > 0 && (!selectedCamId || !cameras.some((c) => c.id === selectedCamId))) {
      setSelectedCamId(cameras[0].id)
    }
  }, [cameras, selectedCamId])

  useEffect(() => {
    let isMounted = true
    const fetchZones = async () => {
      try {
        const data = await getZones(selectedCamId)
        if (isMounted) {
          setZones(data || [])
          onZoneCount?.(data?.length ?? 0)
        }
      } catch (err) {
        // Silently handle if offline
      }
    }

    fetchZones()
  }, [selectedCamId, onZoneCount])

  const restrictedCount = zones.filter((z) => z.restriction_level === 'RESTRICTED').length
  const monitoredCount = zones.filter((z) => z.restriction_level === 'MONITORED').length

  return (
    <div className="zones-collapsible">
      <div className="zones-header" onClick={() => setIsExpanded(!isExpanded)}>
        <div className="zones-title-group">
          <ShieldAlert size={14} className="accent-icon" />
          <span className="zones-title">Virtual Zones</span>
          <span className="zones-count-pill">{zones.length}</span>
          <span className="zones-summary">
            {restrictedCount > 0 && (
              <span className="summary-restricted">{restrictedCount} Restricted</span>
            )}
            {monitoredCount > 0 && (
              <span className="summary-monitored">{monitoredCount} Monitored</span>
            )}
          </span>
        </div>

        <button className="zones-toggle-btn" aria-label="Toggle zones view">
          {isExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        </button>
      </div>

      {isExpanded && (
        <div className="zones-body">
          {zones.length === 0 ? (
            <div className="zones-empty">No virtual fence zones configured for this camera.</div>
          ) : (
            <div className="zones-grid">
              {zones.map((zone) => {
                const isRestricted = zone.restriction_level === 'RESTRICTED'
                return (
                  <div key={zone.id} className={`zone-item ${isRestricted ? 'zone-restricted' : 'zone-monitored'}`}>
                    <div className="zone-main">
                      <div className="zone-id-tag">{zone.id}</div>
                      <div className="zone-name">{zone.name}</div>
                    </div>

                    <div className="zone-specs">
                      <span className={`zone-level-badge ${isRestricted ? 'badge-restricted' : 'badge-monitored'}`}>
                        {isRestricted ? <ShieldAlert size={10} /> : <Eye size={10} />}
                        {zone.restriction_level}
                      </span>
                      <span className="zone-dwell">
                        <Clock size={10} />
                        {zone.dwell_threshold_seconds}s dwell
                      </span>
                      <span className="zone-pts">
                        <Layers size={10} />
                        {zone.polygon_coords?.length || 0}-pt
                      </span>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
