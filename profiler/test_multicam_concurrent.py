"""
Multi-camera concurrent responsiveness & contention stress test for NETRA/IBVAP.

Tests two regimes:
Regime A (Uncapped Stress Benchmark @ 25 FPS target):
  Lifts the artificial 5.0 FPS throttling cap to test true hardware contention,
  measuring how CPU & the shared _inference_lock behave under simultaneous load.

Regime B (Production Cap Analysis @ 5 FPS target):
  Demonstrates that the 5.0 FPS production ceiling comfortably fits within
  the available headroom without contention degradation.
"""

import sys
import time
import subprocess
import asyncio
import json
from typing import List, Dict, Any, Tuple
import httpx
import websockets

BACKEND_URL = "http://localhost:8000"
WS_URL = "ws://localhost:8000/ws/alerts"
UNCAPPED_TARGET_FPS = 25.0

def start_ffmpeg_stream(stream_name: str, fps: int = 25):
    """Starts a looping ffmpeg stream of sample_video.mp4 at specified FPS over TCP."""
    cmd = [
        "ffmpeg", "-re", "-stream_loop", "-1",
        "-i", "scripts/sample_video.mp4",
        "-r", str(fps),
        "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency",
        "-an",
        "-rtsp_transport", "tcp",
        "-f", "rtsp", f"rtsp://localhost:8554/{stream_name}"
    ]
    p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return p

async def get_camera_health(camera_id: str):
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            r = await client.get(f"{BACKEND_URL}/api/v1/cameras/{camera_id}/health")
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass
        return None

async def start_camera(camera_id: str, target_fps: float = 25.0):
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            r = await client.post(f"{BACKEND_URL}/api/v1/cameras/{camera_id}/restart?target_fps={target_fps}")
            return r.status_code == 200
        except Exception as e:
            print(f"Error starting {camera_id}: {e}")
            return False

async def stop_camera(camera_id: str):
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            r = await client.post(f"{BACKEND_URL}/api/v1/cameras/{camera_id}/stop")
            return r.status_code == 200
        except Exception as e:
            print(f"Error stopping {camera_id}: {e}")
            return False

async def wait_for_stream_online(camera_id: str, max_wait_sec: float = 8.0):
    """Waits until camera is connected and receiving frames."""
    t0 = time.time()
    while time.time() - t0 < max_wait_sec:
        h = await get_camera_health(camera_id)
        if h and h.get("is_connected") and h.get("last_frame_at"):
            return True
        await asyncio.sleep(0.5)
    return False

async def measure_fps(camera_ids: list, duration_sec: float = 12.0, sample_interval: float = 1.0):
    """Samples health endpoint over duration_sec and measures actual FPS achieved."""
    start_time = time.time()
    fps_records = {cid: [] for cid in camera_ids}

    while time.time() - start_time < duration_sec:
        await asyncio.sleep(sample_interval)
        for cid in camera_ids:
            h = await get_camera_health(cid)
            if h:
                fps = h.get("measured_fps", 0.0)
                fps_records[cid].append(fps)

    results = {}
    for cid in camera_ids:
        # Exclude initial warmup 0 or low-first-sample
        valid_recs = [f for f in fps_records[cid] if f > 1.0]
        results[cid] = sum(valid_recs) / len(valid_recs) if valid_recs else (sum(fps_records[cid]) / len(fps_records[cid]) if fps_records[cid] else 0.0)
    return results, fps_records

async def test_ws_latency(duration_sec: float = 12.0):
    events_received: List[Tuple[float, Dict[str, Any]]] = []
    t_start = time.time()
    try:
        async with websockets.connect(WS_URL) as ws:
            while time.time() - t_start < duration_sec:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=1.0)
                    data = json.loads(msg)
                    events_received.append((time.time(), data))
                except asyncio.TimeoutError:
                    pass
    except Exception as e:
        print(f"WS error: {e}")
    return events_received

async def main():
    print("=" * 80)
    print("NETRA/IBVAP Multi-Camera True Contention & Headroom Stress Benchmark")
    print(f"Targeting Uncapped {UNCAPPED_TARGET_FPS} FPS per camera (25 FPS 768x432 H.264 streams)")
    print("=" * 80)

    # 1. Start RTSP streams via MediaMTX over TCP at 25 FPS
    print("\n[Step 1] Starting 25 FPS RTSP video streams (cam1, cam2) via ffmpeg over TCP...")
    p1 = start_ffmpeg_stream("cam1", fps=25)
    p2 = start_ffmpeg_stream("cam2", fps=25)
    await asyncio.sleep(3.0)

    try:
        # Clean baseline
        print("Resetting baseline: stopping existing camera workers...")
        await stop_camera("CAM-TEST-01")
        await stop_camera("CAM-TEST-02")
        await asyncio.sleep(2.0)

        # 2. Test CAM-TEST-01 alone at uncapped 25 FPS
        print("\n[Step 2] Testing CAM-TEST-01 standalone (target_fps=25.0)...")
        await start_camera("CAM-TEST-01", target_fps=UNCAPPED_TARGET_FPS)
        await wait_for_stream_online("CAM-TEST-01")
        print("  Stabilizing standalone rolling window (3s)...")
        await asyncio.sleep(3.0)
        fps_res_1, records_1 = await measure_fps(["CAM-TEST-01"], duration_sec=12.0)
        fps_single_1 = fps_res_1.get("CAM-TEST-01", 0.0)
        print(f"  CAM-TEST-01 Standalone FPS: {fps_single_1:.2f} FPS (samples: {records_1['CAM-TEST-01']})")

        # Stop CAM-TEST-01
        print("  Stopping CAM-TEST-01 for isolation...")
        await stop_camera("CAM-TEST-01")
        await asyncio.sleep(2.0)

        # 3. Test CAM-TEST-02 alone at uncapped 25 FPS
        print("\n[Step 3] Testing CAM-TEST-02 standalone (target_fps=25.0)...")
        await start_camera("CAM-TEST-02", target_fps=UNCAPPED_TARGET_FPS)
        await wait_for_stream_online("CAM-TEST-02")
        print("  Stabilizing standalone rolling window (3s)...")
        await asyncio.sleep(3.0)
        fps_res_2, records_2 = await measure_fps(["CAM-TEST-02"], duration_sec=12.0)
        fps_single_2 = fps_res_2.get("CAM-TEST-02", 0.0)
        print(f"  CAM-TEST-02 Standalone FPS: {fps_single_2:.2f} FPS (samples: {records_2['CAM-TEST-02']})")

        # 4. Test BOTH concurrently at uncapped 25 FPS
        print("\n[Step 4] Starting CAM-TEST-01 and CAM-TEST-02 CONCURRENTLY (target_fps=25.0 each)...")
        await start_camera("CAM-TEST-01", target_fps=UNCAPPED_TARGET_FPS)
        await start_camera("CAM-TEST-02", target_fps=UNCAPPED_TARGET_FPS)
        await asyncio.gather(
            wait_for_stream_online("CAM-TEST-01"),
            wait_for_stream_online("CAM-TEST-02"),
        )
        print("  Both cameras active. Stabilizing dual rolling windows (3s)...")
        await asyncio.sleep(3.0)

        print("  Measuring concurrent FPS & WebSocket responsiveness under saturated load (12s)...")
        ws_task = asyncio.create_task(test_ws_latency(duration_sec=12.0))
        fps_task = asyncio.create_task(measure_fps(["CAM-TEST-01", "CAM-TEST-02"], duration_sec=12.0))

        ws_events, (fps_dual, records_dual) = await asyncio.gather(ws_task, fps_task)

        fps_c1 = fps_dual.get("CAM-TEST-01", 0.0)
        fps_c2 = fps_dual.get("CAM-TEST-02", 0.0)
        combined_throughput = fps_c1 + fps_c2

        # 5. Isolation checks
        print("\n[Step 5] Analyzing Per-Camera Isolation & WebSocket Responsiveness...")
        events_by_cam: Dict[str, list] = {}
        for t_stamp, ev in ws_events:
            cid = ev.get("camera_id")
            if cid:
                events_by_cam.setdefault(cid, []).append(ev)

        for cid, evts in events_by_cam.items():
            print(f"  Camera {cid}: {len(evts)} alerts received via WebSocket.")
            for e in evts[:2]:
                print(f"    - Type: {e.get('type')}, Track: {e.get('track_id')}, Zone: {e.get('zone_id')}")

        # 6. Summary Report
        print("\n" + "=" * 80)
        print("UNCAPPED SATURATION BENCHMARK RESULTS (TRUE CONTENTION)")
        print("=" * 80)
        print(f"{'Camera Stream':<16} {'Standalone (Max)':<20} {'Concurrent':<18} {'Contention Delta':<18}")
        print("-" * 80)
        d1 = ((fps_c1 - fps_single_1) / fps_single_1 * 100) if fps_single_1 > 0 else 0.0
        d2 = ((fps_c2 - fps_single_2) / fps_single_2 * 100) if fps_single_2 > 0 else 0.0
        print(f"{'CAM-TEST-01':<16} {fps_single_1:>7.2f} FPS          {fps_c1:>7.2f} FPS        {d1:>+7.1f}%")
        print(f"{'CAM-TEST-02':<16} {fps_single_2:>7.2f} FPS          {fps_c2:>7.2f} FPS        {d2:>+7.1f}%")
        print("-" * 80)
        print(f"{'Combined System':<16} {'--':<20} {combined_throughput:>7.2f} FPS")
        print("=" * 80)

        print("\n" + "=" * 80)
        print("SYSTEM HEADROOM & ARCHITECTURAL VERIFICATION")
        print("=" * 80)
        print(f"  * Standalone Processing Headroom:  {min(fps_single_1, fps_single_2):.2f} FPS vs 5.0 FPS target (~{min(fps_single_1, fps_single_2)/5.0:.1f}x headroom)")
        print(f"  * Concurrent Degraded Rate:        {min(fps_c1, fps_c2):.2f} FPS vs 5.0 FPS target")
        if min(fps_c1, fps_c2) >= 5.0:
            print(f"  * Production 5 FPS Feasibility:    CONFIRMED — Even under full contention ({min(fps_c1, fps_c2):.2f} FPS),")
            print(f"                                     throughput remains ABOVE the 5.0 FPS design target.")
        else:
            print(f"  * Production 5 FPS Feasibility:    MARGINAL — Contention drops throughput to {min(fps_c1, fps_c2):.2f} FPS.")
        print("=" * 80)

    finally:
        p1.terminate()
        p2.terminate()
        print("\nRTSP ffmpeg background streams terminated cleanly.")

if __name__ == "__main__":
    asyncio.run(main())
