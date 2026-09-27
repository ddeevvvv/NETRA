import { useState, useEffect } from 'react'
import { ShieldAlert, Eye, Clock, X, Check, RefreshCw, AlertCircle, Compass } from 'lucide-react'

export default function ZoneEditorModal({
  isOpen,
  mode = 'create',
  zone = null,
  polygonCoords = null,
  cameraId = '',
  onSave,
  onRedraw,
  onClose,
}) {
  const [name, setName] = useState('')
  const [restrictionLevel, setRestrictionLevel] = useState('RESTRICTED')
  const [dwellThreshold, setDwellThreshold] = useState(5.0)
  const [virtualFence, setVirtualFence] = useState(true)
  const [minConfidence, setMinConfidence] = useState(0.5)
  const [error, setError] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)

  // Initialize or reset form state when opened
  useEffect(() => {
    if (isOpen) {
      setError('')
      if (mode === 'edit' && zone) {
        setName(zone.name || '')
        setRestrictionLevel(zone.restriction_level || 'RESTRICTED')
        setDwellThreshold(zone.dwell_threshold_seconds ?? 5.0)
        setVirtualFence(zone.rules?.virtual_fence ?? true)
        setMinConfidence(zone.rules?.min_confidence ?? 0.5)
      } else {
        setName('')
        setRestrictionLevel('RESTRICTED')
        setDwellThreshold(5.0)
        setVirtualFence(true)
        setMinConfidence(0.5)
      }
    }
  }, [isOpen, mode, zone])

  if (!isOpen) return null

  const activeCoords = polygonCoords || zone?.polygon_coords || []

  const handleSubmit = async (e) => {
    e?.preventDefault()
    setError('')

    const trimmedName = name.trim()
    if (!trimmedName) {
      setError('Zone name is required.')
      return
    }

    const dwellVal = parseFloat(dwellThreshold)
    if (isNaN(dwellVal) || dwellVal <= 0) {
      setError('Dwell threshold must be a positive number greater than 0.')
      return
    }

    if (activeCoords.length < 3) {
      setError('A valid zone requires at least 3 polygon points.')
      return
    }

    setIsSubmitting(true)
    try {
      const payload = {
        name: trimmedName,
        camera_id: cameraId || zone?.camera_id,
        zone_type: 'POLYGON',
        restriction_level: restrictionLevel,
        dwell_threshold_seconds: dwellVal,
        rules: {
          virtual_fence: virtualFence,
          min_confidence: parseFloat(minConfidence) || 0.5,
        },
      }

      if (mode === 'create') {
        // Auto-generate concise unique ID e.g. Z-CAM-01-A9F2
        const camPrefix = (cameraId || 'CAM').replace(/[^a-zA-Z0-9]/g, '')
        const randSuffix = Math.random().toString(36).substring(2, 6).toUpperCase()
        payload.id = `Z-${camPrefix}-${randSuffix}`
        payload.polygon_coords = activeCoords
      } else {
        // In edit mode, if user drew new coordinates, pass them, else omit or pass existing
        if (polygonCoords && polygonCoords.length >= 3) {
          payload.polygon_coords = polygonCoords
        }
      }

      await onSave(payload)
      onClose()
    } catch (err) {
      setError(err.message || 'Failed to save zone')
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-container zone-editor-modal" onClick={(e) => e.stopPropagation()}>
        {/* Modal Header */}
        <div className="modal-header">
          <div className="modal-title-group">
            <Compass size={16} className="accent-icon" />
            <h3 className="modal-title">
              {mode === 'create' ? 'Define Virtual Zone' : `Edit Zone: ${zone?.name || zone?.id}`}
            </h3>
            <span className="camera-id-pill">{cameraId || zone?.camera_id}</span>
          </div>
          <button className="modal-close-btn" onClick={onClose} aria-label="Close modal">
            <X size={16} />
          </button>
        </div>

        {/* Modal Body Form */}
        <form onSubmit={handleSubmit} className="modal-body zone-editor-form">
          {error && (
            <div className="zone-form-error">
              <AlertCircle size={14} />
              <span>{error}</span>
            </div>
          )}

          {/* Geometry status */}
          <div className="zone-geometry-status">
            <div className="geom-info">
              <span className="geom-label">Boundary Geometry</span>
              <span className="geom-coords-count">
                {activeCoords.length} vertex points {activeCoords.length >= 3 ? '(valid polygon)' : '(min 3 needed)'}
              </span>
            </div>
            {mode === 'edit' && (
              <button
                type="button"
                className="zone-redraw-btn"
                onClick={() => {
                  onClose()
                  onRedraw?.(zone)
                }}
              >
                <RefreshCw size={12} />
                <span>Redraw Shape on Feed</span>
              </button>
            )}
          </div>

          {/* Zone Name */}
          <div className="form-group">
            <label className="form-label" htmlFor="zone-name-input">
              Zone Name <span className="req-star">*</span>
            </label>
            <input
              id="zone-name-input"
              name="name"
              type="text"
              className="form-input"
              placeholder="e.g. Restricted Sector Alpha, Perimeter Gate 2"
              value={name}
              onChange={(e) => setName(e.target.value)}
              autoFocus
            />
          </div>

          {/* Restriction Level */}
          <div className="form-group">
            <label className="form-label" htmlFor="zone-restriction-select">
              Restriction Level
            </label>
            <div className="select-wrap">
              <select
                id="zone-restriction-select"
                name="restriction_level"
                className="form-select"
                value={restrictionLevel}
                onChange={(e) => setRestrictionLevel(e.target.value)}
              >
                <option value="RESTRICTED">RESTRICTED (High-Severity Alerts on Intrusion)</option>
                <option value="MONITORED">MONITORED (Activity Tracking & Presence Log)</option>
              </select>
            </div>
            <div className="form-help-text">
              {restrictionLevel === 'RESTRICTED' ? (
                <span className="help-restricted">
                  <ShieldAlert size={11} /> Triggers CRITICAL/HIGH alerts and pushes notifications immediately.
                </span>
              ) : (
                <span className="help-monitored">
                  <Eye size={11} /> Tracks dwell time and logs presence without urgent audible alerts.
                </span>
              )}
            </div>
          </div>

          {/* Dwell Threshold */}
          <div className="form-group">
            <label className="form-label" htmlFor="zone-dwell-input">
              Dwell Confirmation Threshold (seconds)
            </label>
            <div className="input-with-icon">
              <Clock size={14} className="input-icon" />
              <input
                id="zone-dwell-input"
                name="dwell_threshold"
                type="number"
                step="0.5"
                min="0.5"
                max="60"
                className="form-input has-icon"
                value={dwellThreshold}
                onChange={(e) => setDwellThreshold(e.target.value)}
              />
            </div>
            <span className="form-help-text">
              Target must remain continuously inside the polygon for this duration to confirm intrusion.
            </span>
          </div>

          {/* Virtual Fence Intrusion Toggle */}
          <div className="form-checkbox-group">
            <label className="checkbox-label" htmlFor="zone-virtual-fence-checkbox">
              <input
                id="zone-virtual-fence-checkbox"
                name="virtual_fence_intrusion"
                type="checkbox"
                checked={virtualFence}
                onChange={(e) => setVirtualFence(e.target.checked)}
              />
              <span>Enable Virtual Fence Cross-Line Detection</span>
            </label>
          </div>

          {/* Modal Actions */}
          <div className="modal-footer">
            <button type="button" className="btn-secondary" onClick={onClose} disabled={isSubmitting}>
              Cancel
            </button>
            <button type="submit" className="btn-primary" disabled={isSubmitting}>
              {isSubmitting ? (
                <>
                  <RefreshCw size={13} className="spin-icon" />
                  <span>Saving...</span>
                </>
              ) : (
                <>
                  <Check size={14} />
                  <span>{mode === 'create' ? 'Save Zone' : 'Update Zone'}</span>
                </>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
