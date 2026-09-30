import { useState, useEffect, useCallback, useRef, Fragment } from 'react'
import { getEvents, acknowledgeEvent, getIncidentSummaries, downloadIncidentEvidencePackage, downloadEventEvidencePackage } from '../api'
import VehicleTrackTimeline from './VehicleTrackTimeline'
import FacesView from './FacesView'
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
  Filter,
  Car,
  FileText,
  Layers,
  RefreshCw,
  Shield,
  FileDown,
  Download,
  Loader2,
  User,
} from 'lucide-react'

const EVENT_TYPES = ['', 'INTRUSION', 'FACE_DETECTED', 'ANPR_MATCH', 'ANPR_READ', 'CAMERA_HEALTH', 'LOITERING', 'ZONE_ENTRY', 'ZONE_EXIT']
const SEVERITIES = ['', 'INFO', 'WARNING', 'HIGH', 'CRITICAL']

/**
 * InvestigateView — historical event queries, vehicle tracking timeline, and face detections.
 */
export default function InvestigateView({ cameras, initialPlate = '', initialTab = '' }) {
  const [activeSubTab, setActiveSubTab] = useState(() => {
    if (initialTab) return initialTab
    if (initialPlate) return 'track'
    return 'summaries'
  })
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

  // ── Incident Summaries state ────────────────────────────────────────────
  const [summariesData, setSummariesData] = useState(null)
  const [summariesLoading, setSummariesLoading] = useState(false)
  const [summariesError, setSummariesError] = useState(null)
  const [summaryWindow, setSummaryWindow] = useState(5)
  const [summaryCameraFilter, setSummaryCameraFilter] = useState('')

  const summariesAbortRef = useRef(null)
  const searchAbortRef = useRef(null)

  useEffect(() => {
    if (initialPlate) {
      setActiveSubTab('track')
    }
  }, [initialPlate])

  const fetchSummaries = useCallback(async () => {
    if (summariesAbortRef.current) {
      summariesAbortRef.current.abort()
    }
    const ac = new AbortController()
    summariesAbortRef.current = ac

    setSummariesLoading(true)
    setSummariesError(null)
    try {
      const data = await getIncidentSummaries({
        camera_id: summaryCameraFilter || undefined,
        window_minutes: summaryWindow,
        only_unacked: true,
        signal: ac.signal,
      })
      setSummariesData(data)
    } catch (e) {
      if (e.name === 'AbortError') return
      setSummariesError(e.message)
    } finally {
      setSummariesLoading(false)
    }
  }, [summaryCameraFilter, summaryWindow])

  const search = useCallback(async () => {
    if (searchAbortRef.current) {
      searchAbortRef.current.abort()
    }
    const ac = new AbortController()
    searchAbortRef.current = ac

    setLoading(true)
    setError(null)
    try {
      const f = { ...filters }
      if (f.start_time) f.start_time = new Date(f.start_time).toISOString()
      if (f.end_time) f.end_time = new Date(f.end_time).toISOString()
      const data = await getEvents({ ...f, signal: ac.signal })
      setEvents(data)
    } catch (e) {
      if (e.name === 'AbortError') return
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [filters])

  // Auto-load tab data on activeSubTab change
  useEffect(() => {
    if (activeSubTab === 'summaries') {
      fetchSummaries()
    } else if (activeSubTab === 'events' && events === null) {
      search()
    }
  }, [activeSubTab, fetchSummaries, search, events])

  // Cleanup in-flight requests on unmount
  useEffect(() => {
    return () => {
      if (summariesAbortRef.current) summariesAbortRef.current.abort()
      if (searchAbortRef.current) searchAbortRef.current.abort()
    }
  }, [])

  const set = (key) => (e) => setFilters((f) => ({ ...f, [key]: e.target.value }))

  const handleAck = async (eventId, e) => {
    e.stopPropagation()
    setAckingId(eventId)
    try {
      const updated = await acknowledgeEvent(eventId, 'operator')
      setEvents((prev) =>
        prev
          ? prev.map((ev) =>
              ev.id === updated.id
                ? { ...ev, acknowledged: true, acknowledged_by: updated.acknowledged_by }
                : ev
            )
          : prev
      )
    } catch (e) {
      alert('Acknowledge failed: ' + e.message)
    } finally {
      setAckingId(null)
    }
  }

  return (
    <div className="investigate-view">
      {/* ── Sub-tab navigation ── */}
      <div className="investigate-subtabs">
        <button
          type="button"
          className={`subtab-btn ${activeSubTab === 'summaries' ? 'subtab-active' : ''}`}
          onClick={() => setActiveSubTab('summaries')}
        >
          <Layers size={13} />
          <span>Incident Summaries</span>
        </button>

        <button
          type="button"
          className={`subtab-btn ${activeSubTab === 'events' ? 'subtab-active' : ''}`}
          onClick={() => setActiveSubTab('events')}
        >
          <FileText size={13} />
          <span>Event Log Search</span>
        </button>

        <button
          type="button"
          className={`subtab-btn ${activeSubTab === 'track' ? 'subtab-active' : ''}`}
          onClick={() => setActiveSubTab('track')}
        >
          <Car size={13} />
          <span>Track Vehicle Sightings</span>
        </button>

        <button
          type="button"
          className={`subtab-btn ${activeSubTab === 'faces' ? 'subtab-active' : ''}`}
          onClick={() => setActiveSubTab('faces')}
        >
          <User size={13} />
          <span>Face Detections</span>
        </button>
      </div>

      {activeSubTab === 'track' ? (
        <VehicleTrackTimeline cameras={cameras} initialPlate={initialPlate} />
      ) : activeSubTab === 'summaries' ? (
        <IncidentSummariesTab
          cameras={cameras}
          data={summariesData}
          loading={summariesLoading}
          error={summariesError}
          window={summaryWindow}
          cameraFilter={summaryCameraFilter}
          onWindowChange={setSummaryWindow}
          onCameraFilterChange={setSummaryCameraFilter}
          onRefresh={fetchSummaries}
        />
      ) : activeSubTab === 'faces' ? (
        <FacesView cameras={cameras} />
      ) : (
        <>
          {/* ── Filter bar ── */}
      {/* ── Filter bar ── */}
      <div className="filters-bar">
        <div className="filter-group">
          <label className="filter-label" htmlFor="filter-camera-id">
            <Filter size={10} /> Camera
          </label>
          <select id="filter-camera-id" name="camera_id" value={filters.camera_id} onChange={set('camera_id')}>
            <option value="">All cameras</option>
            {cameras.map((c) => (
              <option key={c.id} value={c.id}>
                {c.id}
              </option>
            ))}
          </select>
        </div>

        <div className="filter-group">
          <label className="filter-label" htmlFor="filter-event-type">Event Type</label>
          <select id="filter-event-type" name="type" value={filters.type} onChange={set('type')}>
            {EVENT_TYPES.map((t) => (
              <option key={t} value={t}>
                {t || 'All types'}
              </option>
            ))}
          </select>
        </div>

        <div className="filter-group">
          <label className="filter-label" htmlFor="filter-severity">Severity</label>
          <select id="filter-severity" name="severity" value={filters.severity} onChange={set('severity')}>
            {SEVERITIES.map((s) => (
              <option key={s} value={s}>
                {s || 'All'}
              </option>
            ))}
          </select>
        </div>

        <div className="filter-group">
          <label className="filter-label" htmlFor="filter-start-time">From</label>
          <input id="filter-start-time" name="start_time" type="datetime-local" value={filters.start_time} onChange={set('start_time')} />
        </div>

        <div className="filter-group">
          <label className="filter-label" htmlFor="filter-end-time">To</label>
          <input id="filter-end-time" name="end_time" type="datetime-local" value={filters.end_time} onChange={set('end_time')} />
        </div>

        <div className="filter-group">
          <label className="filter-label" htmlFor="filter-limit">Limit</label>
          <select id="filter-limit" name="limit" value={filters.limit} onChange={set('limit')}>
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
        </>
      )}
    </div>
  )
}

/** ── Incident Summaries Tab ──────────────────────────────────────────────── */
function IncidentSummariesTab({ cameras, data, loading, error, window: winMin, cameraFilter, onWindowChange, onCameraFilterChange, onRefresh }) {
  const _sev_rank = { CRITICAL: 4, HIGH: 3, WARNING: 2, INFO: 1 }

  return (
    <div className="summaries-tab">
      {/* Controls */}
      <div className="summaries-controls">
        <div className="filter-group">
          <label className="filter-label" htmlFor="summary-filter-camera"><Filter size={10} /> Camera</label>
          <select id="summary-filter-camera" name="summary_camera" value={cameraFilter} onChange={(e) => onCameraFilterChange(e.target.value)}>
            <option value="">All cameras</option>
            {cameras.map((c) => (
              <option key={c.id} value={c.id}>{c.id}</option>
            ))}
          </select>
        </div>

        <div className="filter-group">
          <label className="filter-label" htmlFor="summary-cluster-window"><Clock size={10} /> Cluster window</label>
          <select id="summary-cluster-window" name="cluster_window" value={winMin} onChange={(e) => onWindowChange(Number(e.target.value))}>
            {[5, 15, 30, 60, 120, 240, 480, 1440].map((m) => (
              <option key={m} value={m}>{m < 60 ? `${m} min` : `${m / 60}h`}</option>
            ))}
          </select>
        </div>

        <button className="search-btn" onClick={onRefresh} disabled={loading}>
          <RefreshCw size={13} className={loading ? 'spin-icon' : ''} />
          <span>{loading ? 'Loading…' : 'Refresh'}</span>
        </button>
      </div>

      {/* State display */}
      {error && <div className="error-banner">Error: {error}</div>}

      {loading && <div className="no-data">Loading incident summaries…</div>}

      {!loading && data && data.summaries.length === 0 && (
        <div className="no-data">
          <Shield size={32} style={{ opacity: 0.3, marginBottom: 8 }} />
          <div>No unacknowledged incidents</div>
          <div style={{ fontSize: 11, marginTop: 4, opacity: 0.6 }}>All clear — no open incident clusters in this window.</div>
        </div>
      )}

      {!loading && data && data.summaries.length > 0 && (
        <>
          <div className="summaries-header">
            <span>{data.total_clusters} incident cluster{data.total_clusters !== 1 ? 's' : ''} · {winMin}-min window</span>
            <span className="results-hint">Sorted by severity</span>
          </div>
          <div className="summaries-list">
            {data.summaries.map((s, idx) => (
              <SummaryCard key={idx} summary={s} />
            ))}
          </div>
        </>
      )}
    </div>
  )
}

function SummaryCard({ summary }) {
  const [exporting, setExporting] = useState(false)
  const [exportError, setExportError] = useState(null)

  const sevLower = (summary.severity || 'INFO').toLowerCase()
  const firstTs = summary.first_event_at ? new Date(summary.first_event_at) : null
  const lastTs  = summary.last_event_at  ? new Date(summary.last_event_at)  : null

  const fmtTime = (dt) =>
    dt ? dt.toLocaleTimeString('en-IN', { hour12: false, hour: '2-digit', minute: '2-digit' }) : '—'
  const fmtDate = (dt) =>
    dt ? dt.toLocaleDateString('en-IN', { day: '2-digit', month: 'short' }) : '—'

  const sameDay = firstTs && lastTs && fmtDate(firstTs) === fmtDate(lastTs)

  const handleExport = async (format = 'pdf') => {
    setExporting(true)
    setExportError(null)
    try {
      await downloadIncidentEvidencePackage({
        camera_id: summary.camera_id,
        zone_id: summary.zone_id || undefined,
        start_time: summary.first_event_at,
        end_time: summary.last_event_at,
        format,
      })
    } catch (err) {
      setExportError(err.message)
    } finally {
      setExporting(false)
    }
  }

  return (
    <div className={`summary-card summary-sev-${sevLower}`}>
      <div className="summary-card-left">
        <SeverityBadge severity={summary.severity} />
      </div>

      <div className="summary-card-body">
        <div className="summary-desc">{summary.description}</div>

        <div className="summary-meta-row">
          {/* Camera */}
          <span className="summary-chip chip-camera">{summary.camera_id}</span>

          {/* Zone */}
          {summary.zone_id && (
            <span className="summary-chip chip-zone">{summary.zone_id}</span>
          )}

          {/* Event type chips */}
          {summary.event_types.map((t) => (
            <span key={t} className="summary-chip chip-type">{t}</span>
          ))}
        </div>

        {/* Rule name if known */}
        {summary.rule_name && (
          <div className="summary-rule-callout">
            <Shield size={10} />
            <span>Rule: {summary.rule_name}</span>
          </div>
        )}

        {/* Export action bar */}
        <div className="summary-actions-row">
          <button
            type="button"
            className="btn-export-evidence"
            onClick={() => handleExport('pdf')}
            disabled={exporting}
            title="Export certified evidence package (PDF)"
          >
            {exporting ? (
              <>
                <Loader2 size={12} className="spin-icon" />
                <span>Generating Evidence Package…</span>
              </>
            ) : (
              <>
                <FileDown size={12} />
                <span>Export Evidence Package</span>
              </>
            )}
          </button>

          <button
            type="button"
            className="btn-export-zip-compact"
            onClick={() => handleExport('zip')}
            disabled={exporting}
            title="Export raw ZIP archive"
          >
            <Download size={11} />
            <span>ZIP</span>
          </button>
        </div>

        {exportError && <div className="summary-export-err">⚠ {exportError}</div>}
      </div>

      <div className="summary-card-right">
        <div className="summary-count-badge">
          <span className="summary-count-num">{summary.total_count}</span>
          <span className="summary-count-label">events</span>
        </div>
        {summary.unacked_count > 0 && (
          <span className="summary-unacked-pill">{summary.unacked_count} pending</span>
        )}
        <div className="summary-timerange">
          {sameDay
            ? <><span>{fmtDate(firstTs)}</span><span>{fmtTime(firstTs)} – {fmtTime(lastTs)}</span></>
            : <><span>{fmtDate(firstTs)} {fmtTime(firstTs)}</span><span>→ {fmtDate(lastTs)} {fmtTime(lastTs)}</span></>
          }
        </div>
      </div>
    </div>
  )
}


function EventRowItem({ event, acking, onAck }) {
  const [isExpanded, setIsExpanded] = useState(false)
  const [exportingSingle, setExportingSingle] = useState(false)
  const [singleExportErr, setSingleExportErr] = useState(null)

  const handleExportSingle = async (format = 'pdf') => {
    setExportingSingle(true)
    setSingleExportErr(null)
    try {
      await downloadEventEvidencePackage(event.id, format)
    } catch (err) {
      setSingleExportErr(err.message)
    } finally {
      setExportingSingle(false)
    }
  }

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

                <div className="table-meta-actions">
                  <button
                    type="button"
                    className="btn-export-single-evidence"
                    onClick={() => handleExportSingle('pdf')}
                    disabled={exportingSingle}
                  >
                    {exportingSingle ? (
                      <>
                        <Loader2 size={11} className="spin-icon" />
                        <span>Exporting…</span>
                      </>
                    ) : (
                      <>
                        <FileDown size={11} />
                        <span>Export Event Record (PDF)</span>
                      </>
                    )}
                  </button>
                  {singleExportErr && <span className="single-export-err">⚠ {singleExportErr}</span>}
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
