import { useState, Fragment } from 'react'
import { getEvents, acknowledgeEvent } from '../api'
import {
  Search,
  Check,
  ChevronDown,
  ChevronUp,
  AlertOctagon,
  AlertTriangle,
  AlertCircle,
  Info,
  Image as ImageIcon,
  Clock,
  Filter
} from 'lucide-react'

const EVENT_TYPES = ['', 'INTRUSION', 'FACE_DETECTED', 'ANPR_MATCH', 'ANPR_READ', 'CAMERA_HEALTH', 'LOITERING', 'ZONE_ENTRY', 'ZONE_EXIT']
const SEVERITIES = ['', 'INFO', 'WARNING', 'HIGH', 'CRITICAL']

/**
 * InvestigateView — historical event queries with filter form,
 * expandable rows revealing evidence snapshots & detailed metadata, and Lucide icons.
 */
export default function InvestigateView({ cameras }) {
  const [filters, setFilters] = useState({
    camera_id: '',
    type: '',
    severity: '',
    start_time: '',
    end_time: '',
    limit: '100',
  })
  const [events, setEvents] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [ackingId, setAckingId] = useState(null)

  const set = (key) => (e) => setFilters((f) => ({ ...f, [key]: e.target.value }))

  const search = async () => {
    setLoading(true)
    setError(null)
    try {
      const f = { ...filters }
      if (f.start_time) f.start_time = new Date(f.start_time).toISOString()
      if (f.end_time) f.end_time = new Date(f.end_time).toISOString()
      const data = await getEvents(f)
      setEvents(data)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  const handleAck = async (eventId, e) => {
    e.stopPropagation()
    setAckingId(eventId)
    try {
      const updated = await acknowledgeEvent(eventId, 'operator')
      setEvents((prev) =>
        prev.map((ev) =>
          ev.id === updated.id
            ? { ...ev, acknowledged: true, acknowledged_by: updated.acknowledged_by }
            : ev
        )
      )
    } catch (e) {
      alert('Acknowledge failed: ' + e.message)
    } finally {
      setAckingId(null)
    }
  }

  return (
    <div className="investigate-view">
      {/* ── Filter bar ── */}
      <div className="filters-bar">
        <div className="filter-group">
          <label className="filter-label">
            <Filter size={10} /> Camera
          </label>
          <select value={filters.camera_id} onChange={set('camera_id')}>
            <option value="">All cameras</option>
            {cameras.map((c) => (
              <option key={c.id} value={c.id}>
                {c.id}
              </option>
            ))}
          </select>
        </div>

        <div className="filter-group">
          <label className="filter-label">Event Type</label>
          <select value={filters.type} onChange={set('type')}>
            {EVENT_TYPES.map((t) => (
              <option key={t} value={t}>
                {t || 'All types'}
              </option>
            ))}
          </select>
        </div>

        <div className="filter-group">
          <label className="filter-label">Severity</label>
          <select value={filters.severity} onChange={set('severity')}>
            {SEVERITIES.map((s) => (
              <option key={s} value={s}>
                {s || 'All'}
              </option>
            ))}
          </select>
        </div>

        <div className="filter-group">
          <label className="filter-label">From</label>
          <input type="datetime-local" value={filters.start_time} onChange={set('start_time')} />
        </div>

        <div className="filter-group">
          <label className="filter-label">To</label>
          <input type="datetime-local" value={filters.end_time} onChange={set('end_time')} />
        </div>

        <div className="filter-group">
          <label className="filter-label">Limit</label>
          <select value={filters.limit} onChange={set('limit')}>
            {['25', '50', '100', '200'].map((n) => (
              <option key={n}>{n}</option>
            ))}
          </select>
        </div>

        <button className="search-btn" onClick={search} disabled={loading}>
          <Search size={13} />
          <span>{loading ? 'Searching…' : 'Search'}</span>
        </button>
      </div>

      {/* ── Results ── */}
      {error && <div className="error-banner">Error: {error}</div>}

      {events === null && !loading && (
        <div className="no-data">Set query parameters above and click Search to inspect event records.</div>
      )}

      {events !== null && (
        <div className="events-table-wrap">
          {events.length === 0 ? (
            <div className="no-data">No events match the specified filter criteria.</div>
          ) : (
            <>
              <div className="results-header">
                <span>
                  {events.length} event record{events.length !== 1 ? 's' : ''} retrieved
                </span>
                <span className="results-hint">Click any row to view full metadata & evidence</span>
              </div>
              <table className="investigate-table">
                <thead>
                  <tr>
                    <th style={{ width: 28 }}></th>
                    <th>Timestamp</th>
                    <th>Camera</th>
                    <th>Type</th>
                    <th>Severity</th>
                    <th>Zone</th>
                    <th>Object</th>
                    <th>Conf</th>
                    <th>Ack Status</th>
                    <th style={{ textAlign: 'right' }}>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {events.map((ev) => (
                    <EventRowItem
                      key={ev.id}
                      event={ev}
                      acking={ackingId === ev.id}
                      onAck={handleAck}
                    />
                  ))}
                </tbody>
              </table>
            </>
          )}
        </div>
      )}
    </div>
  )
}

function EventRowItem({ event, acking, onAck }) {
  const [isExpanded, setIsExpanded] = useState(false)

  const ts = new Date(event.timestamp)
  const dateStr = ts.toLocaleDateString('en-IN', { day: '2-digit', month: 'short' })
  const timeStr = ts.toLocaleTimeString('en-IN', { hour12: false })

  const meta = event.event_metadata || event.metadata || {}
  const snapshotUri = event.evidence?.snapshot_uri

  return (
    <Fragment>
      <tr
        className={`event-row ${event.acknowledged ? 'row-acked' : ''} ${
          isExpanded ? 'row-expanded' : ''
        }`}
        onClick={() => setIsExpanded(!isExpanded)}
      >
        <td className="row-toggle-cell">
          <button className="row-chevron-btn" aria-label="Toggle row details">
            {isExpanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
          </button>
        </td>
        <td className="ts-cell">
          {dateStr} {timeStr}
        </td>
        <td className="cam-cell">{event.camera_id}</td>
        <td className="type-cell">{event.type}</td>
        <td>
          <SeverityBadge severity={event.severity} />
        </td>
        <td className="meta-cell">{event.zone_id ?? '—'}</td>
        <td className="meta-cell">{event.object_type ?? '—'}</td>
        <td className="meta-cell">
          {event.confidence != null ? `${(event.confidence * 100).toFixed(0)}%` : '—'}
        </td>
        <td>
          {event.acknowledged ? (
            <span className="acked-badge">
              <Check size={11} />
              <span>{event.acknowledged_by}</span>
            </span>
          ) : (
            <span className="pending-badge">Pending</span>
          )}
        </td>
        <td style={{ textAlign: 'right' }}>
          {!event.acknowledged && (
            <button
              className="ack-btn"
              onClick={(e) => onAck(event.id, e)}
              disabled={acking}
            >
              <Check size={11} />
              <span>{acking ? '…' : 'Ack'}</span>
            </button>
          )}
        </td>
      </tr>

      {/* ── Expanded Detail Accordion ── */}
      {isExpanded && (
        <tr className="detail-accordion-row">
          <td colSpan={10} className="detail-accordion-cell">
            <div className="table-detail-container">
              {snapshotUri && (
                <div className="table-snapshot-box">
                  <img
                    src={snapshotUri}
                    alt="Evidence snapshot"
                    className="table-snapshot-img"
                  />
                  <div className="snapshot-caption">
                    <ImageIcon size={10} />
                    <span>Evidence Frame</span>
                  </div>
                </div>
              )}

              <div className="table-meta-box">
                <div className="meta-section-title">Event Metadata & Forensics</div>
                <div className="table-kv-grid">
                  <div className="table-kv-item">
                    <span className="kv-label">Event UUID:</span>
                    <span className="kv-val mono">{event.id}</span>
                  </div>
                  {event.track_id != null && (
                    <div className="table-kv-item">
                      <span className="kv-label">Track ID:</span>
                      <span className="kv-val">#{event.track_id}</span>
                    </div>
                  )}
                  {event.acknowledged && (
                    <div className="table-kv-item">
                      <span className="kv-label">Acknowledged At:</span>
                      <span className="kv-val">
                        {event.acknowledged_at
                          ? new Date(event.acknowledged_at).toLocaleString('en-IN')
                          : 'Yes'}
                      </span>
                    </div>
                  )}
                  {Object.entries(meta).map(([key, val]) => {
                    const displayVal =
                      typeof val === 'object' && val !== null
                        ? JSON.stringify(val)
                        : String(val)
                    return (
                      <div key={key} className="table-kv-item">
                        <span className="kv-label">{formatKey(key)}:</span>
                        <span className="kv-val">{displayVal}</span>
                      </div>
                    )
                  })}
                </div>
              </div>
            </div>
          </td>
        </tr>
      )}
    </Fragment>
  )
}

function SeverityBadge({ severity }) {
  const icons = {
    CRITICAL: <AlertOctagon size={10} />,
    HIGH: <AlertTriangle size={10} />,
    WARNING: <AlertCircle size={10} />,
    INFO: <Info size={10} />,
  }

  return (
    <span className={`badge sev-badge sev-${severity}`}>
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
