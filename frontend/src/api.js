// ─── IBVAP API client ─────────────────────────────────────────────────────────
// All paths are relative — Vite proxies /api → http://localhost:8000
// and /ws → ws://localhost:8000

const BASE = '/api/v1'

// ── Cameras ──────────────────────────────────────────────────────────────────

export async function getCameras() {
  const res = await fetch(`${BASE}/cameras`)
  if (!res.ok) throw new Error(`GET /cameras failed: ${res.status}`)
  return res.json()
}

export async function getCameraHealth(cameraId) {
  const res = await fetch(`${BASE}/cameras/${cameraId}/health`)
  if (!res.ok) throw new Error(`GET /cameras/${cameraId}/health failed: ${res.status}`)
  return res.json()
}

export async function getAllCameraHealth() {
  const res = await fetch(`${BASE}/cameras/health-all`)
  if (!res.ok) throw new Error(`GET /cameras/health-all failed: ${res.status}`)
  return res.json()
}

/** Returns the MJPEG stream URL to use as an <img src>. */
export function debugStreamUrl(cameraId) {
  return `${BASE}/cameras/${cameraId}/debug/stream`
}

export async function getAnprCrops(cameraId) {
  const res = await fetch(`${BASE}/cameras/${cameraId}/debug/anpr-crops`)
  if (!res.ok) throw new Error(`GET /cameras/${cameraId}/debug/anpr-crops failed: ${res.status}`)
  return res.json()
}

// ── Zones ────────────────────────────────────────────────────────────────────

export async function getZones(cameraId) {
  const url = cameraId ? `${BASE}/zones?camera_id=${encodeURIComponent(cameraId)}` : `${BASE}/zones`
  const res = await fetch(url)
  if (!res.ok) throw new Error(`GET /zones failed: ${res.status}`)
  return res.json()
}

export async function createZone(zoneData) {
  const res = await fetch(`${BASE}/zones`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(zoneData),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || `POST /zones failed: ${res.status}`)
  }
  return res.json()
}

export async function updateZone(zoneId, zoneData) {
  const res = await fetch(`${BASE}/zones/${encodeURIComponent(zoneId)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(zoneData),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || `PUT /zones failed: ${res.status}`)
  }
  return res.json()
}

export async function deleteZone(zoneId) {
  const res = await fetch(`${BASE}/zones/${encodeURIComponent(zoneId)}`, {
    method: 'DELETE',
  })
  if (!res.ok && res.status !== 204) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || `DELETE /zones failed: ${res.status}`)
  }
  return true
}

// ── Events ───────────────────────────────────────────────────────────────────

/**
 * Fetch events with optional filters.
 * @param {object} filters - { camera_id, type, severity, start_time, end_time, limit, offset, signal }
 */
export async function getEvents(filters = {}) {
  const { signal, ...rest } = filters
  const params = new URLSearchParams()
  if (rest.camera_id)  params.set('camera_id',  rest.camera_id)
  if (rest.type)       params.set('type',        rest.type)
  if (rest.severity)   params.set('severity',    rest.severity)
  if (rest.acknowledged !== undefined && rest.acknowledged !== null) {
    params.set('acknowledged', rest.acknowledged)
  }
  if (rest.requires_acknowledgment !== undefined && rest.requires_acknowledgment !== null) {
    params.set('requires_acknowledgment', rest.requires_acknowledgment)
  }
  if (rest.start_time) params.set('start_time',  rest.start_time)
  if (rest.end_time)   params.set('end_time',    rest.end_time)
  params.set('limit',  rest.limit  ?? 100)
  params.set('offset', rest.offset ?? 0)
  const res = await fetch(`${BASE}/events?${params}`, { signal })
  if (!res.ok) throw new Error(`GET /events failed: ${res.status}`)
  return res.json()
}

/**
 * Fetch clustered incident summaries.
 * @param {{ camera_id?: string, window_minutes?: number, only_unacked?: boolean, signal?: AbortSignal }} opts
 */
export async function getIncidentSummaries({ camera_id, window_minutes = 30, only_unacked = true, signal } = {}) {
  const params = new URLSearchParams()
  if (camera_id) params.set('camera_id', camera_id)
  params.set('window_minutes', window_minutes)
  params.set('only_unacked', only_unacked)
  const res = await fetch(`${BASE}/events/summaries?${params}`, { signal })
  if (!res.ok) throw new Error(`GET /events/summaries failed: ${res.status}`)
  return res.json()
}


/**
 * Acknowledge an event.
 * @param {string} eventId
 * @param {string} [operator='operator']
 */
export async function acknowledgeEvent(eventId, operator = 'operator') {
  const res = await fetch(`${BASE}/events/${eventId}/acknowledge`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ acknowledged_by: operator }),
  })
  if (!res.ok) throw new Error(`POST /events/${eventId}/acknowledge failed: ${res.status}`)
  return res.json()
}

/**
 * Bulk-acknowledge unacknowledged incidents.
 * @param {object} filters - Optional { camera_id, site_id, event_ids, acknowledged_by }
 *   If no filter is given, ALL unacked incidents are cleared.
 */
export async function acknowledgeBulkEvents(filters = {}) {
  const res = await fetch(`${BASE}/events/acknowledge-bulk`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ acknowledged_by: 'operator', ...filters }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || `POST /events/acknowledge-bulk failed: ${res.status}`)
  }
  return res.json()
}

// ── WebSocket ─────────────────────────────────────────────────────────────────

/**
 * Open the /ws/alerts WebSocket. Calls onMessage(event) for each incoming alert.
 * Returns a cleanup function to close the socket.
 */
export function connectAlertStream(onMessage, onStatusChange) {
  const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
  const wsUrl = `${protocol}://${window.location.host}/ws/alerts`

  let ws = null
  let reconnectTimer = null
  let stopped = false

  function connect() {
    ws = new WebSocket(wsUrl)

    ws.onopen = () => {
      onStatusChange?.('connected')
    }

    ws.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data)
        onMessage(data)
      } catch {
        // ignore malformed frames
      }
    }

    ws.onerror = () => {
      onStatusChange?.('error')
    }

    ws.onclose = () => {
      if (stopped) return
      onStatusChange?.('reconnecting')
      reconnectTimer = setTimeout(connect, 3000)
    }
  }

  connect()

  return () => {
    stopped = true
    clearTimeout(reconnectTimer)
    ws?.close()
  }
}

// ── Vehicle Tracking ──────────────────────────────────────────────────────────

/**
 * Fetch chronological sighting history for a vehicle plate across all cameras.
 * @param {string} plate
 * @param {AbortSignal} [signal]
 */
export async function getVehicleSightings(plate, signal) {
  if (!plate || !plate.trim()) return []
  const res = await fetch(`${BASE}/vehicles/${encodeURIComponent(plate.trim())}/sightings`, { signal })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || `GET /vehicles/${plate}/sightings failed: ${res.status}`)
  }
  return res.json()
}

export async function getVehicleHistory(plate) {
  return getVehicleSightings(plate)
}

// ── Sites / Situational Awareness Map ───────────────────────────────────────

export async function getSitesStatus() {
  const res = await fetch(`${BASE}/sites/status`)
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || `GET /sites/status failed: ${res.status}`)
  }
  return res.json()
}

// ── Evidence Package Exports ────────────────────────────────────────────────

async function triggerFileDownload(res, fallbackName) {
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || `Export failed with status ${res.status}`)
  }

  let filename = fallbackName
  const disposition = res.headers.get('content-disposition')
  if (disposition && disposition.includes('filename=')) {
    const match = disposition.match(/filename="?([^";]+)"?/)
    if (match && match[1]) filename = match[1].trim()
  }

  const blob = await res.blob()
  const url = window.URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.style.display = 'none'
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  window.URL.revokeObjectURL(url)
  document.body.removeChild(a)
}

/**
 * Download Evidence Package for an Incident Cluster.
 */
export async function downloadIncidentEvidencePackage({ camera_id, zone_id, start_time, end_time, event_ids, format = 'pdf' }) {
  const params = new URLSearchParams()
  if (camera_id) params.set('camera_id', camera_id)
  if (zone_id) params.set('zone_id', zone_id)
  if (start_time) params.set('start_time', start_time)
  if (end_time) params.set('end_time', end_time)
  if (event_ids) params.set('event_ids', event_ids)
  params.set('format', format)

  const res = await fetch(`${BASE}/events/incident-evidence-package?${params}`)
  await triggerFileDownload(res, `IBVAP_Incident_Evidence.${format}`)
}

/**
 * Download Evidence Package for a single Event.
 */
export async function downloadEventEvidencePackage(eventId, format = 'pdf') {
  const res = await fetch(`${BASE}/events/${encodeURIComponent(eventId)}/evidence-package?format=${format}`)
  await triggerFileDownload(res, `IBVAP_Event_${eventId}.${format}`)
}

/**
 * Download Evidence Package for Vehicle Plate History Dossier.
 */
export async function downloadVehicleEvidencePackage(plate, format = 'pdf') {
  const res = await fetch(`${BASE}/vehicles/${encodeURIComponent(plate.trim())}/evidence-package?format=${format}`)
  await triggerFileDownload(res, `IBVAP_Vehicle_${plate.trim()}.${format}`)
}

/**
 * Fetch all site restriction zones.
 * @param {string} [siteId] Optional site filter
 */
export async function getSiteRestrictions(siteId) {
  const params = new URLSearchParams()
  if (siteId) params.set('site_id', siteId)
  const res = await fetch(`${BASE}/sites/restrictions?${params}`)
  if (!res.ok) throw new Error(`GET /sites/restrictions failed: ${res.status}`)
  return res.json()
}

/**
 * Create a new site-level restriction zone.
 * @param {{ site_id: string, name?: string, restriction_level?: string, polygon_geojson: any, is_active?: boolean }} data
 */
export async function createSiteRestriction(data) {
  const res = await fetch(`${BASE}/sites/restrictions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error(`POST /sites/restrictions failed: ${res.status}`)
  return res.json()
}

/**
 * Delete a site restriction zone.
 * @param {string} restrictionId
 */
export async function deleteSiteRestriction(restrictionId) {
  const res = await fetch(`${BASE}/sites/restrictions/${encodeURIComponent(restrictionId)}`, {
    method: 'DELETE',
  })
  if (!res.ok) throw new Error(`DELETE /sites/restrictions failed: ${res.status}`)
  return res.json()
}

