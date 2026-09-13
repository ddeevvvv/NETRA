# IBVAP — Intelligent Border Video Analytics Platform

AI-based video analytics middleware ingesting IP-camera RTSP/ONVIF streams with real-time detection, tracking, virtual-fence intrusion, ANPR, face recognition, and human-acknowledged alerting. Built for SIH 2026.

---

## 🚀 Quick Start (Docker Compose)

### 1. Start All Services
Launches PostgreSQL, Redis, and the FastAPI Backend:

```bash
docker-compose up --build -d
```

### 2. Check Backend Logs
```bash
docker-compose logs -f backend
```

---

## 📡 Real-Time Alert Delivery & Testing Pipeline (Stage 2)

### 1. Start the WebSocket Test Client (Terminal A)
Subscribes to `/ws/alerts` and prints live alerts as they are published to Redis:

```bash
python scripts/test_ws_client.py
```

### 2. Start the Fake Event Publisher (Terminal B)
Posts randomized realistic border alert scenarios (`INTRUSION`, `ANPR_MATCH`, `LOITERING`, `ROUTINE_CHECK`) every 3–6 seconds to `POST /api/v1/events`:

```bash
python scripts/fake_event_publisher.py --min-interval 3.0 --max-interval 6.0
```

---

## 📡 API Endpoints & Curl Verification

### 1. Health Check (`GET /health`)
```bash
curl -X GET "http://localhost:8000/health"
```

### 2. Ingest Event (`POST /api/v1/events`)
Submits an event to PostgreSQL and publishes JSON to Redis channel `ibvap:alerts`:

```bash
curl -X POST "http://localhost:8000/api/v1/events" \
  -H "Content-Type: application/json" \
  -d '{
    "camera_id": "CAM-07",
    "type": "INTRUSION",
    "severity": "CRITICAL",
    "timestamp": "2026-09-11T12:52:03Z",
    "object_type": "person",
    "track_id": 17,
    "confidence": 0.94,
    "zone_id": "Z-01",
    "evidence": {
      "snapshot_uri": "http://storage/snapshots/cam07_17.jpg",
      "clip_uri": "http://storage/clips/cam07_17.mp4"
    },
    "metadata": {
      "direction": "NORTHBOUND"
    }
  }'
```

### 3. Query & Filter Events (`GET /api/v1/events`)
Filter events by `camera_id`, `type`, `severity`, and time range:

```bash
curl -X GET "http://localhost:8000/api/v1/events?camera_id=CAM-07&type=INTRUSION&severity=CRITICAL"
```

### 4. Human Operator Acknowledgment (`POST /api/v1/events/{id}/acknowledge`)
```bash
curl -X POST "http://localhost:8000/api/v1/events/<EVENT_ID>/acknowledge" \
  -H "Content-Type: application/json" \
  -d '{
    "acknowledged_by": "Operator-Alpha"
  }'
```

---

## 📹 RTSP Camera Ingestion & Simulation (Stage 3)

### 1. Launch MediaMTX RTSP Server
MediaMTX is included in `docker-compose.yml` for local RTSP camera simulation:
```bash
docker-compose up -d mediamtx
```

### 2. Stream Simulation
Stream local video file or webcam to MediaMTX as an RTSP camera stream:
```bash
# Stream webcam (device index 0)
python scripts/simulate_camera.py 0 cam1

# Or stream a video file in a continuous loop
python scripts/simulate_camera.py path/to/sample.mp4 cam1
```

---

## 🧠 AI Inference & Object Tracking (Stage 4)

### 1. Architecture & Models
- **Detector (`backend/app/inference/detector.py`)**:
  - Auto-selects CUDA GPU when available; cleanly defaults to CPU.
  - Defaults to `yolov8n.pt` (nano) for high-speed edge/CPU performance.
  - To upgrade to `yolov8s.pt` (small) or `yolov8m.pt` (medium) on GPU, initialize with:
    `Detector(model_name="yolov8s.pt")` or configure via settings.
  - Target classes filtered to border monitoring scope: `person`, `car`, `truck`, `bus`, `motorcycle`.
  - Applies configurable confidence threshold (default `0.5`) and minimum bounding-box area filter (default `400 px²`) to suppress distant noise.
- **Tracker (`backend/app/inference/tracker.py`)**:
  - Employs **ByteTrack** via the `supervision` library.
  - Provides persistent, non-drifting `track_id` assignments across successive frames.

### 2. Live Debug Visualization Endpoints
When a camera is registered and ONLINE in FastAPI:
- **Annotated Snapshot**: `GET http://localhost:8000/api/v1/cameras/{id}/debug/snapshot`
  Returns the latest frame as JPEG with bounding boxes, class labels, and track IDs drawn.
- **Live MJPEG Stream**: `GET http://localhost:8000/api/v1/cameras/{id}/debug/stream`
  Streams live multipart JPEG frames directly in any web browser or VLC player.

### 3. Standalone Verification Demo
To test detection and tracking immediately against your webcam without starting FastAPI or DB:
```bash
# Run against webcam (device index 0) on port 8766
python scripts/run_inference_demo.py 0 8766
```
Open `http://localhost:8766/` in your browser to see the live feed, FPS, latency, and active track count.

### 4. Real-World Performance Measured
- **Device**: CPU (Intel/AMD x86_64, auto-detected)
- **Inference Latency**: 45–65 ms per frame (`yolov8n`)
- **Sampling Rate**: ~3.75 FPS maintained stably over 1,800+ continuous frames
- **Queue Stability**: Grab-and-discard frame buffering prevents queue bloat and stale frame latency.

---

## 🛡️ Virtual-Fence & Zone Analytics Engine (Stage 5)

### 1. Overview
The Zone Analytics Engine (`backend/app/analytics/zone_engine.py`) continuously evaluates real-time ByteTrack track positions against user-defined polygon zones:
- **Reference Point**: Evaluates the normalized bottom-center point of the bounding box `(center_x, bottom_y)` to represent ground-plane presence.
- **Normalized Coordinates**: Zone coordinates are defined in normalized range `[0.0, 1.0]`, ensuring consistency regardless of stream resolution.
- **Temporal Confirmation**: Requires a track to be detected inside a zone for at least 2 consecutive sampled frames before firing `INTRUSION` or `ZONE_ENTRY`, preventing single-frame jitter false alerts.
- **Dwell & Loitering Detection**: Emits a `LOITERING` alert (severity `WARNING`) once a track continuously dwells in a zone past `dwell_threshold_seconds` (e.g. 5.0s).
- **State Transitions**: Emits `ZONE_EXIT` (severity `INFO`) when a confirmed track departs or times out.

### 2. Zone API Endpoints
- **Create Zone**: `POST /api/v1/zones`
  ```bash
  curl -X POST "http://localhost:8000/api/v1/zones" \
    -H "Content-Type: application/json" \
    -d '{
      "id": "Z-01",
      "camera_id": "CAM-TEST-01",
      "name": "Restricted Sector Alpha",
      "zone_type": "POLYGON",
      "polygon_coords": [[0.45, 0.10], [0.95, 0.10], [0.95, 0.90], [0.45, 0.90]],
      "restriction_level": "RESTRICTED",
      "dwell_threshold_seconds": 5.0
    }'
  ```
- **List Zones**: `GET /api/v1/zones?camera_id=CAM-TEST-01`
- **Get Zone**: `GET /api/v1/zones/{id}`
- **Update Zone**: `PUT /api/v1/zones/{id}`
- **Delete Zone**: `DELETE /api/v1/zones/{id}`
- **Seed Script**: Run `python scripts/seed_test_zone.py` to seed or re-seed the default test zone `Z-01`.

### 3. Live Debug Visualization & Visual State Feedback
Open `http://localhost:8000/api/v1/cameras/CAM-TEST-01/debug/stream` or `http://localhost:8000/api/v1/cameras/CAM-TEST-01/debug/snapshot` in any browser:
- **Zone Boundaries**: Rendered as semi-transparent polygons (Red outline for `RESTRICTED`, Yellow/Cyan for `MONITORED`) with zone ID and name labels.
- **Track Status Colors**:
  - 🟢 **Green / Orange**: Track outside any zone (normal monitoring).
  - 🔴 **Bright Red (`[INTRUSION]`)**: Track confirmed inside a `RESTRICTED` virtual fence.
  - 🟡 **Yellow (`[MONITORED]`)**: Track confirmed inside a `MONITORED` buffer zone.

### 4. Triggering a Real Intrusion Alert End-to-End
1. In Terminal A, start the real-time WebSocket listener:
   ```bash
   python scripts/test_ws_client.py
   ```
2. In Terminal B, ensure the camera simulator is streaming your webcam:
   ```bash
   python scripts/simulate_camera.py --input 0 --stream-name cam1
   ```
3. Open `http://localhost:8000/api/v1/cameras/CAM-TEST-01/debug/stream` in your browser.
4. Walk into the right half of the webcam frame (the seeded `Z-01` zone).
5. **Verify**:
   - Your bounding box turns **RED** on screen with label `[INTRUSION]`.
   - Terminal A (`test_ws_client.py`) receives and prints a live `INTRUSION` alert (`severity: HIGH`, `zone_id: Z-01`).
   - If you remain in the zone for > 5 seconds, a `LOITERING` alert (`severity: WARNING`) is emitted.
   - When you step away, a `ZONE_EXIT` alert (`severity: INFO`) is emitted.

---

## 🧪 Running Unit & Integration Tests Locally

```bash
# Run all 26 backend unit and integration tests
$env:PYTHONPATH="backend"; python -m pytest backend/tests -v
```
