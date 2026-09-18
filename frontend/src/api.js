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

// ── Events ───────────────────────────────────────────────────────────────────

/**
 * Fetch events with optional filters.
 * @param {object} filters - { camera_id, type, severity, start_time, end_time, limit, offset }
 */
export async function getEvents(filters = {}) {
  const params = new URLSearchParams()
  if (filters.camera_id)  params.set('camera_id',  filters.camera_id)
  if (filters.type)       params.set('type',        filters.type)
  if (filters.severity)   params.set('severity',    filters.severity)
  if (filters.start_time) params.set('start_time',  filters.start_time)
  if (filters.end_time)   params.set('end_time',    filters.end_time)
  params.set('limit',  filters.limit  ?? 100)
  params.set('offset', filters.offset ?? 0)
  const res = await fetch(`${BASE}/events?${params}`)
  if (!res.ok) throw new Error(`GET /events failed: ${res.status}`)
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
