import { useState, useEffect, useCallback } from 'react'
import { getZones, updateZone, deleteZone } from '../api'
import ZoneEditorModal from './ZoneEditorModal'
import {
  ShieldAlert,
  Eye,
  Clock,
  ChevronDown,
  ChevronUp,
  Layers,
  Pencil,
  Trash2,
  AlertTriangle,
  RefreshCw,
  Filter,
} from 'lucide-react'

/**
 * ZonesList — Compact, tactical section showing active virtual-fence zones.
 * Displays zone ID, camera association, restriction level, dwell threshold,
 * and allows editing metadata, redrawing polygon shape, and deleting zones.
 */
export default function ZonesList({
  cameras = [],
  zoneVersion = 0,
  onZoneCount,
  onZoneChange,
  onStartRedraw,
}) {
  const [zones, setZones] = useState([])
  const [isExpanded, setIsExpanded] = useState(true)
  const [selectedCamFilter, setSelectedCamFilter] = useState('ALL')
  const [editingZone, setEditingZone] = useState(null)
  const [deletingZone, setDeletingZone] = useState(null)
  const [isDeleting, setIsDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState('')

  const fetchZones = useCallback(async () => {
    try {
      const camParam = selectedCamFilter === 'ALL' ? undefined : selectedCamFilter
      const data = await getZones(camParam)
      const list = data || []
      setZones(list)
      onZoneCount?.(list.length)
    } catch (err) {
      console.error('Failed to load zones:', err)
    }
  }, [selectedCamFilter, onZoneCount])

  useEffect(() => {
    fetchZones()
  }, [fetchZones, zoneVersion])

  const handleEditSave = async (payload) => {
    if (!editingZone?.id) return
    await updateZone(editingZone.id, payload)
    await fetchZones()
    onZoneChange?.()
  }

  const handleDeleteConfirm = async () => {
    if (!deletingZone?.id) return
    setIsDeleting(true)
    setDeleteError('')
    try {
      await deleteZone(deletingZone.id)
      setDeletingZone(null)
      await fetchZones()
      onZoneChange?.()
    } catch (err) {
      setDeleteError(err.message || 'Failed to delete zone')
    } finally {
      setIsDeleting(false)
    }
  }

  const restrictedCount = zones.filter((z) => z.restriction_level === 'RESTRICTED').length
  const monitoredCount = zones.filter((z) => z.restriction_level === 'MONITORED').length

  return (
    <>
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

          <div className="zones-header-controls" onClick={(e) => e.stopPropagation()}>
            {/* Camera filter dropdown */}
            {cameras.length > 1 && (
              <div className="zones-filter-wrap">
                <Filter size={11} className="filter-icon" />
                <select
                  id="zones-cam-select"
                  name="zones_cam_select"
                  aria-label="Filter active zones by camera"
                  className="zones-cam-select"
                  value={selectedCamFilter}
                  onChange={(e) => setSelectedCamFilter(e.target.value)}
                >
                  <option value="ALL">All Cameras</option>
                  {cameras.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.id}
                    </option>
                  ))}
                </select>
              </div>
            )}

            <button
              type="button"
              className="zones-toggle-btn"
              onClick={() => setIsExpanded(!isExpanded)}
              aria-label="Toggle zones view"
            >
              {isExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
            </button>
          </div>
        </div>

        {isExpanded && (
          <div className="zones-body">
            {zones.length === 0 ? (
              <div className="zones-empty">
                No virtual fence zones configured for{' '}
                {selectedCamFilter === 'ALL' ? 'registered cameras' : selectedCamFilter}. Use "Add Zone"
                on a camera card to draw one.
              </div>
            ) : (
              <div className="zones-grid">
                {zones.map((zone) => {
                  const isRestricted = zone.restriction_level === 'RESTRICTED'
                  return (
                    <div
                      key={zone.id}
                      className={`zone-item ${isRestricted ? 'zone-restricted' : 'zone-monitored'}`}
                    >
                      <div className="zone-main">
                        <span className="zone-id-tag">{zone.id}</span>
                        <span className="zone-cam-tag">{zone.camera_id}</span>
                        <span className="zone-name">{zone.name}</span>
                      </div>

                      <div className="zone-specs-and-actions">
                        <div className="zone-specs">
                          <span
                            className={`zone-level-badge ${isRestricted ? 'badge-restricted' : 'badge-monitored'}`}
                          >
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

                        {/* Zone Actions: Edit & Delete */}
                        <div className="zone-actions">
                          <button
                            type="button"
                            className="zone-action-btn btn-edit"
                            onClick={() => setEditingZone(zone)}
                            title="Edit zone settings or redraw polygon"
                          >
                            <Pencil size={11} />
                            <span>Edit</span>
                          </button>
                          <button
                            type="button"
                            className="zone-action-btn btn-delete"
                            onClick={() => {
                              setDeleteError('')
                              setDeletingZone(zone)
                            }}
                            title="Delete this zone"
                          >
                            <Trash2 size={11} />
                            <span>Delete</span>
                          </button>
                        </div>
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Edit Zone Modal */}
      <ZoneEditorModal
        isOpen={Boolean(editingZone)}
        mode="edit"
        zone={editingZone}
        cameraId={editingZone?.camera_id}
        onSave={handleEditSave}
        onRedraw={(z) => {
          setEditingZone(null)
          onStartRedraw?.({ cameraId: z.camera_id, zone: z })
        }}
        onClose={() => setEditingZone(null)}
      />

      {/* Delete Confirmation Modal */}
      {deletingZone && (
        <div className="modal-backdrop" onClick={() => !isDeleting && setDeletingZone(null)}>
          <div
            className="modal-container zone-delete-modal"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="modal-header">
              <div className="modal-title-group">
                <AlertTriangle size={16} className="text-warning" />
                <h3 className="modal-title">Confirm Zone Deletion</h3>
              </div>
            </div>
            <div className="modal-body">
              <p className="delete-warning-text">
                Are you sure you want to delete virtual zone <strong>{deletingZone.name}</strong> (
                <code>{deletingZone.id}</code>) on camera <strong>{deletingZone.camera_id}</strong>?
              </p>
              <p className="delete-warning-sub">
                Intrusion detection rules and dwell tracking for this perimeter will cease immediately.
              </p>
              {deleteError && <div className="zone-form-error">{deleteError}</div>}
            </div>
            <div className="modal-footer">
              <button
                type="button"
                className="btn-secondary"
                onClick={() => setDeletingZone(null)}
                disabled={isDeleting}
              >
                Cancel
              </button>
              <button
                type="button"
                className="btn-danger"
                onClick={handleDeleteConfirm}
                disabled={isDeleting}
              >
                {isDeleting ? (
                  <>
                    <RefreshCw size={13} className="spin-icon" />
                    <span>Deleting...</span>
                  </>
                ) : (
                  <>
                    <Trash2 size={13} />
                    <span>Delete Zone</span>
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
