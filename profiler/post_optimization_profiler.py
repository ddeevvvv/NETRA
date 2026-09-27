"""
IBVAP camera_worker post-optimization per-stage pipeline profiler.

Measures the optimized pipeline using the actual methods from camera_worker.py:
  - _fetch_frame (1-drain instead of 8 blocking grabs)
  - _render_annotations
  - ByteTrack / ZoneEngine offload timings
  - Shared httpx client stub

Run from repo root:
    python3 profiler/post_optimization_profiler.py
"""

import sys
import time
import statistics
import numpy as np
import cv2

sys.path.insert(0, "backend")

STAGES = [
    "S1_fetch_frame",
    "S2_frozen_diff",
    "S3_yolo",
    "S4_bytetrack",
    "S5_zone_engine",
    "S6_rendering",
    "S7_event_post_stub",
]
timings = {s: [] for s in STAGES}

print("Loading inference components ...", flush=True)
t_load = time.perf_counter()

from app.inference.detector import Detector
from app.inference.tracker import Tracker
from app.analytics.zone_engine import ZoneEngine
from app.ingestion.camera_worker import _fetch_frame, _render_annotations

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

    # S1: fetch frame (1-drain + retrieve/read)
    t0 = time.perf_counter()
    ret, frame = _fetch_frame(cap)
    s1_ms = (time.perf_counter() - t0) * 1000

    if not ret or frame is None:
        continue
    frame_count += 1

    # S2: frozen-frame diff
    t0 = time.perf_counter()
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    if prev_gray is not None:
        diff = cv2.absdiff(gray, prev_gray)
        _ = float(np.mean(diff))
    prev_gray = gray
    s2_ms = (time.perf_counter() - t0) * 1000

    # S3: YOLO inference
    t0 = time.perf_counter()
    raw_detections = detector.detect(frame)
    s3_ms = (time.perf_counter() - t0) * 1000

    # S4: ByteTrack update (offloaded)
    t0 = time.perf_counter()
    tracks = tracker.update(raw_detections, frame)
    s4_ms = (time.perf_counter() - t0) * 1000

    # S5: ZoneEngine (offloaded)
    t0 = time.perf_counter()
    zone_events, active_zone_map = zone_engine.process_frame(
        camera_id=CAMERA_ID,
        tracks=tracks,
        frame_shape=frame.shape,
        zones=FAKE_ZONES,
        current_time=time.time(),
    )
    s5_ms = (time.perf_counter() - t0) * 1000

    # S6: Rendering (_render_annotations offloaded)
    t0 = time.perf_counter()
    annotated = _render_annotations(
        frame=frame,
        zones=FAKE_ZONES,
        detections=tracks,
        active_zone_map=active_zone_map,
        anpr_state={},
        latest_face_detections=[],
    )
    s6_ms = (time.perf_counter() - t0) * 1000

    # S7: event-post stub (dict + task creation overhead)
    t0 = time.perf_counter()
    for evt in zone_events:
        pass
    s7_ms = (time.perf_counter() - t0) * 1000

    if not is_warmup:
        timings["S1_fetch_frame"].append(s1_ms)
        timings["S2_frozen_diff"].append(s2_ms)
        timings["S3_yolo"].append(s3_ms)
        timings["S4_bytetrack"].append(s4_ms)
        timings["S5_zone_engine"].append(s5_ms)
        timings["S6_rendering"].append(s6_ms)
        timings["S7_event_post_stub"].append(s7_ms)

cap.release()
print("\n")

print("=" * 74)
print(f"NETRA/IBVAP  POST-OPTIMIZATION Pipeline Profile  (n={N_BENCH} frames, webcam 0)")
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
    print(f"{stage:<24}  {mn:>6.1f}ms  {avg:>6.1f}ms  {p50:>6.1f}ms  {p95:>6.1f}ms  {pct:>7.1f}%")

print("-" * 74)
print(f"{'TOTAL (summed)':<24}  {'':>7}  {grand_mean:>6.1f}ms  {'':>39}  100.0%")
fps = 1000.0 / grand_mean if grand_mean > 0 else 0
print(f"\nMax single-camera sequential FPS: {fps:.1f}")
print("=" * 74)
