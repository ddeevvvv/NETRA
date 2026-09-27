"""
IBVAP camera_worker per-stage pipeline profiler.

Replicates the EXACT order of operations in camera_worker.py start() loop
and measures each stage separately. Uses webcam 0 as the RTSP substitute.

Run from repo root:
    python3 profiler/pipeline_profiler.py

Stages timed:
  S1  grab_drain     8x cap.grab() buffer drain
  S2  decode         cap.retrieve()
  S3  frozen_diff    cv2.absdiff greyscale diff
  S4  yolo           detector.detect() (direct call; to_thread adds ~0.2ms)
  S5  bytetrack      tracker.update()  (runs ON event loop in real worker)
  S6  zone_engine    ZoneEngine.process_frame()  (ON event loop)
  S7  rendering      OpenCV annotation  (ON event loop)
  S8  event_post     stub measuring dict + asyncio.create_task overhead
"""

import sys
import time
import statistics
import numpy as np
import cv2

sys.path.insert(0, "backend")

STAGES = ["S1_grab_drain", "S2_decode", "S3_frozen_diff",
          "S4_yolo", "S5_bytetrack", "S6_zone_engine",
          "S7_rendering", "S8_event_post_stub"]
timings = {s: [] for s in STAGES}

print("Loading inference components ...", flush=True)
t_load = time.perf_counter()

from app.inference.detector import Detector
from app.inference.tracker import Tracker
from app.analytics.zone_engine import ZoneEngine

detector = Detector()
tracker = Tracker(frame_rate=5)
zone_engine = ZoneEngine(temporal_confirmation_frames=2, track_timeout_seconds=3.0)

print(f"  device={detector.device}  imgsz={detector.imgsz}")
print(f"  Load time: {(time.perf_counter()-t_load)*1000:.0f} ms\n")

FAKE_ZONES = [
    {
        "id": "Z-PROFILE-01",
        "name": "Profile Zone A",
        "zone_type": "POLYGON",
        "polygon_coords": [[0.1, 0.1], [0.5, 0.1], [0.5, 0.5], [0.1, 0.5]],
        "restriction_level": "RESTRICTED",
        "dwell_threshold_seconds": 5.0,
    }
]

_stub_count = 0
def _stub_post(payload):
    global _stub_count
    _stub_count += 1

N_WARMUP = 3
N_BENCH = 40
CAMERA_ID = "CAM-PROFILE"
prev_gray = None
frame_count = 0

print("Opening webcam 0 ...", flush=True)
cap = cv2.VideoCapture(0)
cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
if not cap.isOpened():
    print("ERROR: cannot open webcam 0")
    sys.exit(1)
print("Webcam opened\n")

for iteration in range(N_WARMUP + N_BENCH):
    is_warmup = (iteration < N_WARMUP)
    label = "WARMUP" if is_warmup else f"FRAME {iteration - N_WARMUP + 1}/{N_BENCH}"
    print(f"\r{label}    ", end="", flush=True)

    frame_start = time.perf_counter()

    # S1: grab/buffer drain
    t0 = time.perf_counter()
    grabbed = False
    consec_fail = 0
    for _ in range(8):
        if cap.grab():
            grabbed = True
            consec_fail = 0
        else:
            consec_fail += 1
            if consec_fail >= 3:
                break
    s1_ms = (time.perf_counter() - t0) * 1000

    # S2: decode
    t0 = time.perf_counter()
    if grabbed:
        ret, frame = cap.retrieve()
    else:
        ret, frame = cap.read()
    s2_ms = (time.perf_counter() - t0) * 1000

    if not ret or frame is None:
        continue
    frame_count += 1

    # S3: frozen-frame diff
    t0 = time.perf_counter()
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    if prev_gray is not None:
        diff = cv2.absdiff(gray, prev_gray)
        _ = float(np.mean(diff))
    prev_gray = gray
    s3_ms = (time.perf_counter() - t0) * 1000

    # S4: YOLO inference
    t0 = time.perf_counter()
    raw_detections = detector.detect(frame)
    s4_ms = (time.perf_counter() - t0) * 1000

    # S5: ByteTrack update (ON event loop in real worker)
    t0 = time.perf_counter()
    tracks = tracker.update(raw_detections, frame)
    s5_ms = (time.perf_counter() - t0) * 1000

    # S6: ZoneEngine (ON event loop in real worker)
    t0 = time.perf_counter()
    zone_events, active_zone_map = zone_engine.process_frame(
        camera_id=CAMERA_ID,
        tracks=tracks,
        frame_shape=frame.shape,
        zones=FAKE_ZONES,
        current_time=time.time(),
    )
    for evt in zone_events:
        _stub_post(evt)
    s6_ms = (time.perf_counter() - t0) * 1000

    # S7: OpenCV rendering (ON event loop in real worker)
    t0 = time.perf_counter()
    annotated = frame.copy()
    h, w = frame.shape[:2]
    overlay = annotated.copy()
    for z in FAKE_ZONES:
        coords = z.get("polygon_coords", [])
        if coords and len(coords) >= 3:
            pts = (np.array(coords, dtype=np.float32) * np.array([w, h])).astype(np.int32)
            pts = pts.reshape((-1, 1, 2))
            cv2.fillPoly(overlay, [pts], (0, 0, 220))
            cv2.polylines(annotated, [pts], isClosed=True, color=(0, 0, 220), thickness=1)
    cv2.addWeighted(overlay, 0.25, annotated, 0.75, 0, annotated)
    for t in tracks:
        x1, y1, x2, y2 = int(t["bbox"][0]), int(t["bbox"][1]), int(t["bbox"][2]), int(t["bbox"][3])
        cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 255, 0), 1)
        cv2.putText(annotated, f"#{t['track_id']} {t['object_class']}", (x1, max(y1-5,0)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.38, (255, 255, 255), 1, cv2.LINE_AA)
    s7_ms = (time.perf_counter() - t0) * 1000

    # S8: event-post stub
    t0 = time.perf_counter()
    _stub_post({"camera_id": CAMERA_ID, "type": "PROFILE_TICK"})
    s8_ms = (time.perf_counter() - t0) * 1000

    if not is_warmup:
        timings["S1_grab_drain"].append(s1_ms)
        timings["S2_decode"].append(s2_ms)
        timings["S3_frozen_diff"].append(s3_ms)
        timings["S4_yolo"].append(s4_ms)
        timings["S5_bytetrack"].append(s5_ms)
        timings["S6_zone_engine"].append(s6_ms)
        timings["S7_rendering"].append(s7_ms)
        timings["S8_event_post_stub"].append(s8_ms)

cap.release()
print("\n")

print("=" * 74)
print(f"NETRA/IBVAP  Per-Stage Pipeline Profile  (n={N_BENCH} frames, webcam 0)")
print(f"Device: {detector.device}  |  imgsz: {detector.imgsz}")
print("=" * 74)
print(f"{'Stage':<24}  {'Min':>7}  {'Mean':>7}  {'p50':>7}  {'p95':>7}  {'% total':>8}")
print("-" * 74)

grand_mean = sum(statistics.mean(v) for v in timings.values() if v)

for stage, vals in timings.items():
    if not vals:
        continue
    mn  = min(vals)
    avg = statistics.mean(vals)
    p50 = statistics.median(vals)
    p95 = sorted(vals)[int(len(vals) * 0.95)]
    pct = (avg / grand_mean * 100) if grand_mean > 0 else 0
    blocked = "  [EVENT LOOP]" if stage in ("S5_bytetrack", "S6_zone_engine", "S7_rendering") else ""
    print(f"{stage:<24}  {mn:>6.1f}ms  {avg:>6.1f}ms  {p50:>6.1f}ms  {p95:>6.1f}ms  {pct:>7.1f}%{blocked}")

print("-" * 74)
print(f"{'TOTAL (summed)':<24}  {'':>7}  {grand_mean:>6.1f}ms  {'':>39}  100.0%")
fps = 1000.0 / grand_mean if grand_mean > 0 else 0
print(f"\nMax single-camera sequential FPS: {fps:.1f}")
print("\nNOTES:")
print("  [EVENT LOOP] = currently blocks all other cameras during this stage")
print("  S4 (YOLO) already offloaded via asyncio.to_thread in real worker")
print("  S8 stub: real httpx POST adds full TCP round-trip (~2-10ms per event)")
print("  S1 grab drain: webcam is local; RTSP over TCP adds network latency on each grab")
print("=" * 74)
