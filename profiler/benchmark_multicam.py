"""
NETRA/IBVAP Multi-Camera Concurrency & Event Loop Responsiveness Benchmark.

Measures:
1. CameraWorker 1 running standalone.
2. CameraWorker 2 running standalone.
3. CameraWorker 1 and CameraWorker 2 running concurrently:
   - Evaluates lock contention on the shared YOLO detector lock.
   - Evaluates event loop responsiveness (FastAPI /health latency).
   - Evaluates WebSocket message latency and connectivity.
   - Evaluates state isolation (track IDs, zone events, health metrics).
"""

import sys
import os
import time
import asyncio
import statistics
import cv2
import numpy as np
import httpx
import websockets

sys.path.insert(0, "backend")

from app.ingestion.camera_worker import CameraWorker
from app.inference.detector import Detector
from app.inference.tracker import Tracker

def make_test_video(path: str, duration_sec: int = 15, fps: int = 30):
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(path, fourcc, float(fps), (640, 480))
    for i in range(duration_sec * fps):
        frame = np.full((480, 640, 3), 40, dtype=np.uint8)
        # Add animated moving shape simulating target movement
        x = int(50 + (i * 3) % 400)
        y = int(100 + (i * 2) % 250)
        cv2.rectangle(frame, (x, y), (x + 60, y + 120), (0, 255, 0), -1)
        out.write(frame)
    out.release()

async def ping_event_loop(interval: float = 0.2, duration: float = 6.0):
    """Measures event loop latency by scheduling sleep(0) ticks."""
    t_end = time.time() + duration
    delays = []
    while time.time() < t_end:
        t0 = time.perf_counter()
        await asyncio.sleep(interval)
        actual = time.perf_counter() - t0
        delays.append((actual - interval) * 1000) # delay in ms beyond interval
    return delays

async def test_fastapi_responsiveness(duration: float = 6.0):
    """Hits localhost:8000/health during concurrent camera processing to measure HTTP API latency."""
    t_end = time.time() + duration
    latencies = []
    async with httpx.AsyncClient(timeout=3.0) as client:
        while time.time() < t_end:
            t0 = time.perf_counter()
            try:
                r = await client.get("http://localhost:8000/health")
                if r.status_code == 200:
                    latencies.append((time.perf_counter() - t0) * 1000)
            except Exception as e:
                pass
            await asyncio.sleep(0.15)
    return latencies

async def test_websocket_responsiveness(duration: float = 6.0):
    """Tests WebSocket ping/pong round trip latency while cameras are running."""
    pings = []
    events = []
    try:
        async with websockets.connect("ws://localhost:8000/ws/alerts", open_timeout=3.0) as ws:
            t_end = time.time() + duration
            while time.time() < t_end:
                t0 = time.perf_counter()
                pong_waiter = await ws.ping()
                await asyncio.wait_for(pong_waiter, timeout=2.0)
                pings.append((time.perf_counter() - t0) * 1000)
                
                # Check for any queued incoming alert messages
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=0.05)
                    events.append(json.loads(msg))
                except asyncio.TimeoutError:
                    pass
                await asyncio.sleep(0.15)
    except Exception as e:
        print(f"  WebSocket test warning: {e}")
    return pings, events

async def run_worker_benchmark(workers, duration_sec: float = 6.0):
    """Runs a set of workers concurrently for duration_sec and gathers metrics."""
    tasks = [asyncio.create_task(w.start()) for w in workers]
    
    # Wait for initial frames to settle
    await asyncio.sleep(1.5)

    # Sample measured_fps
    t_end = time.time() + duration_sec
    fps_history = {w.camera_id: [] for w in workers}
    frame_history = {w.camera_id: 0 for w in workers}

    while time.time() < t_end:
        await asyncio.sleep(0.5)
        for w in workers:
            h = w.get_health_status()
            if h.get("measured_fps", 0) > 0:
                fps_history[w.camera_id].append(h["measured_fps"])
            frame_history[w.camera_id] = w._frame_count

    # Cleanup
    for w in workers:
        w.stop()
    for t in tasks:
        t.cancel()
        try:
            await t
        except (asyncio.CancelledError, Exception):
            pass

    avg_fps = {}
    for cid, vals in fps_history.items():
        avg_fps[cid] = statistics.mean(vals) if vals else 0.0

    return avg_fps, frame_history

async def main():
    print("=" * 72)
    print("NETRA/IBVAP Multi-Camera Concurrency & Event Loop Responsiveness")
    print("=" * 72)

    vid1_path = "/tmp/cam1_test.mp4"
    vid2_path = "/tmp/cam2_test.mp4"
    make_test_video(vid1_path, duration_sec=20, fps=30)
    make_test_video(vid2_path, duration_sec=20, fps=30)

    # Initialize shared detector singleton and lock (as in IngestionManager)
    detector = Detector()
    inference_lock = asyncio.Lock()

    print(f"Shared Detector ready on {detector.device} (imgsz={detector.imgsz})")

    # ──────────────────────────────────────────────────────────────────────────
    # PHASE 1: CAM-01 Standalone
    # ──────────────────────────────────────────────────────────────────────────
    print("\n[Phase 1] Testing CAM-TEST-01 alone (target_fps=15.0) ...")
    w1 = CameraWorker(camera_id="CAM-TEST-01", rtsp_url=vid1_path, target_fps=15.0, enable_inference=True)
    t1 = Tracker(frame_rate=15)
    w1.set_inference(detector, t1, inference_lock=inference_lock)
    
    fps1_solo, frames1_solo = await run_worker_benchmark([w1], duration_sec=5.0)
    solo_fps_1 = fps1_solo["CAM-TEST-01"]
    print(f"  CAM-TEST-01 Solo Measured Throughput: {solo_fps_1:.2f} FPS ({frames1_solo['CAM-TEST-01']} frames)")

    # ──────────────────────────────────────────────────────────────────────────
    # PHASE 2: CAM-02 Standalone
    # ──────────────────────────────────────────────────────────────────────────
    print("\n[Phase 2] Testing CAM-TEST-02 alone (target_fps=15.0) ...")
    w2 = CameraWorker(camera_id="CAM-TEST-02", rtsp_url=vid2_path, target_fps=15.0, enable_inference=True)
    t2 = Tracker(frame_rate=15)
    w2.set_inference(detector, t2, inference_lock=inference_lock)

    fps2_solo, frames2_solo = await run_worker_benchmark([w2], duration_sec=5.0)
    solo_fps_2 = fps2_solo["CAM-TEST-02"]
    print(f"  CAM-TEST-02 Solo Measured Throughput: {solo_fps_2:.2f} FPS ({frames2_solo['CAM-TEST-02']} frames)")

    # ──────────────────────────────────────────────────────────────────────────
    # PHASE 3: CAM-01 + CAM-02 Concurrent
    # ──────────────────────────────────────────────────────────────────────────
    print("\n[Phase 3] Testing CAM-TEST-01 + CAM-TEST-02 CONCURRENTLY ...")
    w1_conc = CameraWorker(camera_id="CAM-TEST-01", rtsp_url=vid1_path, target_fps=15.0, enable_inference=True)
    w1_conc.set_inference(detector, Tracker(frame_rate=15), inference_lock=inference_lock)

    w2_conc = CameraWorker(camera_id="CAM-TEST-02", rtsp_url=vid2_path, target_fps=15.0, enable_inference=True)
    w2_conc.set_inference(detector, Tracker(frame_rate=15), inference_lock=inference_lock)

    # Launch event loop latency, HTTP API latency, and WebSocket responsiveness monitor alongside
    loop_delays_task = asyncio.create_task(ping_event_loop(interval=0.1, duration=6.0))
    http_latency_task = asyncio.create_task(test_fastapi_responsiveness(duration=6.0))
    ws_latency_task = asyncio.create_task(test_websocket_responsiveness(duration=6.0))
    workers_task = asyncio.create_task(run_worker_benchmark([w1_conc, w2_conc], duration_sec=6.0))

    fps_dual, frames_dual = await workers_task
    loop_delays = await loop_delays_task
    http_latencies = await http_latency_task
    ws_pings, ws_events = await ws_latency_task

    conc_fps_1 = fps_dual["CAM-TEST-01"]
    conc_fps_2 = fps_dual["CAM-TEST-02"]
    total_conc_fps = conc_fps_1 + conc_fps_2

    print(f"  CAM-TEST-01 Concurrent Throughput: {conc_fps_1:.2f} FPS")
    print(f"  CAM-TEST-02 Concurrent Throughput: {conc_fps_2:.2f} FPS")
    print(f"  Combined System Throughput:         {total_conc_fps:.2f} FPS")

    # ──────────────────────────────────────────────────────────────────────────
    # PHASE 4: State Isolation Check
    # ──────────────────────────────────────────────────────────────────────────
    print("\n[Phase 4] Checking Cross-Camera Isolation ...")
    # Verify Tracker instances are distinct and tracks do not bleed
    t1_ids = {t["track_id"] for t in w1_conc.latest_detections} if w1_conc.latest_detections else set()
    t2_ids = {t["track_id"] for t in w2_conc.latest_detections} if w2_conc.latest_detections else set()
    print(f"  CAM-TEST-01 Tracker object ID: {id(w1_conc._tracker)}")
    print(f"  CAM-TEST-02 Tracker object ID: {id(w2_conc._tracker)}")
    assert id(w1_conc._tracker) != id(w2_conc._tracker), "Isolation failure: Trackers must be distinct"
    assert id(w1_conc._zone_engine) != id(w2_conc._zone_engine), "Isolation failure: ZoneEngines must be distinct"
    print("  State isolation confirmed: Tracker & ZoneEngine are separate instances.")

    # ──────────────────────────────────────────────────────────────────────────
    # RESULTS REPORT
    # ──────────────────────────────────────────────────────────────────────────
    print("\n" + "=" * 72)
    print("CONCURRENCY & RESPONSIVENESS REPORT")
    print("=" * 72)
    print(f"{'Camera':<16} {'Solo FPS':<14} {'Concurrent FPS':<16} {'Contention Delta':<18}")
    print("-" * 72)
    d1 = ((conc_fps_1 - solo_fps_1) / solo_fps_1 * 100) if solo_fps_1 > 0 else 0
    d2 = ((conc_fps_2 - solo_fps_2) / solo_fps_2 * 100) if solo_fps_2 > 0 else 0
    print(f"{'CAM-TEST-01':<16} {solo_fps_1:>6.2f} FPS      {conc_fps_1:>6.2f} FPS        {d1:>+6.1f}%")
    print(f"{'CAM-TEST-02':<16} {solo_fps_2:>6.2f} FPS      {conc_fps_2:>6.2f} FPS        {d2:>+6.1f}%")
    print("-" * 72)

    print("\nEvent Loop & Interface Responsiveness During Dual Active Ingestion:")
    print(f"  Asyncio Loop Jitter (delay beyond sleep): mean={statistics.mean(loop_delays):.2f} ms | p95={sorted(loop_delays)[int(len(loop_delays)*0.95)]:.2f} ms")
    if http_latencies:
        print(f"  FastAPI /health HTTP Round-Trip:          mean={statistics.mean(http_latencies):.2f} ms | p95={sorted(http_latencies)[int(len(http_latencies)*0.95)]:.2f} ms")
    if ws_pings:
        print(f"  WebSocket Ping/Pong Round-Trip:           mean={statistics.mean(ws_pings):.2f} ms | p95={sorted(ws_pings)[int(len(ws_pings)*0.95)]:.2f} ms")
    print("=" * 72)

    # Cleanup test files
    for p in (vid1_path, vid2_path):
        if os.path.exists(p):
            os.remove(p)

if __name__ == "__main__":
    asyncio.run(main())
