"""
Stage 4 — End-to-End Detection + Tracking Demo Script

Runs a CameraWorker with YOLO + ByteTrack against webcam or an RTSP stream
and serves the annotated MJPEG stream locally WITHOUT requiring the full
FastAPI stack. Useful for quick visual verification.

Usage:
    python scripts/run_inference_demo.py            # webcam (device 0)
    python scripts/run_inference_demo.py 0          # explicit webcam
    python scripts/run_inference_demo.py rtsp://localhost:8554/cam1

Then open:  http://localhost:8765/stream  in your browser.

Metrics (FPS + inference latency) are logged to console every 5 seconds.
Press Ctrl-C to stop.
"""
import asyncio
import logging
import sys
import time
import threading
from typing import Optional

import cv2
import numpy as np

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s"
)
logger = logging.getLogger("ibvap.demo")

# ── HTTP server for MJPEG ─────────────────────────────────────────────────────

from http.server import BaseHTTPRequestHandler, HTTPServer

_latest_jpeg: Optional[bytes] = None
_latest_detections = []
_frame_lock = threading.Lock()
_stats = {"fps": 0.0, "latency_ms": 0.0, "device": "cpu", "frames": 0}


class MJPEGHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # suppress access log spam

    def do_GET(self):
        if self.path == "/stream":
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=ibvap")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            while True:
                with _frame_lock:
                    jpeg = _latest_jpeg
                if jpeg:
                    try:
                        self.wfile.write(
                            b"--ibvap\r\nContent-Type: image/jpeg\r\n"
                            + f"Content-Length: {len(jpeg)}\r\n\r\n".encode()
                            + jpeg + b"\r\n"
                        )
                        self.wfile.flush()
                    except BrokenPipeError:
                        break
                time.sleep(0.1)

        elif self.path == "/snapshot":
            with _frame_lock:
                jpeg = _latest_jpeg
            if jpeg:
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                self.wfile.write(jpeg)
            else:
                self.send_response(503)
                self.end_headers()

        else:
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            d = _stats
            html = (
                "<html><body style='font-family:monospace;background:#111;color:#eee;padding:20px'>"
                f"<h2>IBVAP Stage 4 — Detection Demo</h2>"
                f"<p>Device: <b>{d['device'].upper()}</b> | "
                f"FPS: <b>{d['fps']:.1f}</b> | "
                f"Latency: <b>{d['latency_ms']:.0f}ms</b> | "
                f"Total frames: <b>{d['frames']}</b></p>"
                f"<img src='/stream' style='max-width:90%;border:2px solid #444'>"
                "</body></html>"
            ).encode()
            self.wfile.write(html)


def _run_server(port: int):
    server = HTTPServer(("0.0.0.0", port), MJPEGHandler)
    logger.info(f"[Demo] HTTP server at http://localhost:{port}/  (stream: /stream, snapshot: /snapshot)")
    server.serve_forever()


# ── Main inference loop ───────────────────────────────────────────────────────

async def run_demo(source: str, port: int = 8765):
    global _latest_jpeg, _latest_detections

    # Start HTTP server in background thread
    t = threading.Thread(target=_run_server, args=(port,), daemon=True)
    t.start()

    # Load detector + tracker
    import os
    backend_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend")
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)
    from app.inference.detector import Detector
    from app.inference.tracker import Tracker

    detector = Detector()
    tracker = Tracker(frame_rate=5)
    _stats["device"] = detector.device

    # Open source
    cap_src = int(source) if source.isdigit() else source
    cap = cv2.VideoCapture(cap_src)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    if not cap.isOpened():
        logger.error(f"Cannot open source: {source!r}")
        return

    logger.info(f"[Demo] Opened source: {source!r}")

    target_fps = 5.0
    sample_interval = 1.0 / target_fps
    last_sample = time.time()
    last_log = time.time()
    frames_since_log = 0
    total_frames = 0

    while True:
        # Grab-and-discard (RTSP) or fallback read (MSMF webcam)
        grabbed = False
        consecutive_grab_fails = 0
        for _ in range(8):
            if cap.grab():
                grabbed = True
                consecutive_grab_fails = 0
            else:
                consecutive_grab_fails += 1
                if consecutive_grab_fails >= 3:
                    break

        if grabbed:
            ret, frame = cap.retrieve()
        else:
            ret, frame = cap.read()

        if not ret or frame is None:
            if cap.get(cv2.CAP_PROP_FRAME_COUNT) > 0:
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            await asyncio.sleep(0.01)
            continue

        now = time.time()
        if (now - last_sample) < sample_interval:
            await asyncio.sleep(0.002)
            continue

        last_sample = now
        total_frames += 1
        frames_since_log += 1
        _stats["frames"] = total_frames

        # ── Inference ────────────────────────────────────────────────────────
        t0 = time.perf_counter()
        raw_dets = detector.detect(frame)
        tracks = tracker.update(raw_dets, frame)
        latency_ms = (time.perf_counter() - t0) * 1000
        _stats["latency_ms"] = latency_ms

        # ── Annotate frame ────────────────────────────────────────────────────
        annotated = frame.copy()
        for trk in tracks:
            x1, y1, x2, y2 = [int(v) for v in trk["bbox"]]
            color = (0, 255, 0) if trk["object_class"] == "person" else (255, 128, 0)
            label = f"#{trk['track_id']} {trk['object_class']} {trk['confidence']:.2f}"
            cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
            cv2.putText(annotated, label, (x1, max(y1 - 8, 15)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)

        # Overlay stats
        cv2.putText(
            annotated,
            f"FPS:{_stats['fps']:.1f}  Lat:{latency_ms:.0f}ms  Tracks:{len(tracks)}  [{_stats['device'].upper()}]",
            (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2
        )

        # Encode to JPEG and publish
        _, buf = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 80])
        with _frame_lock:
            _latest_jpeg = buf.tobytes()
            _latest_detections = tracks

        # ── Periodic FPS log ─────────────────────────────────────────────────
        elapsed = now - last_log
        if elapsed >= 5.0:
            fps = frames_since_log / elapsed
            _stats["fps"] = fps
            logger.info(
                f"[Demo] FPS={fps:.2f} | latency={latency_ms:.0f}ms | "
                f"device={_stats['device'].upper()} | tracks={len(tracks)} | "
                f"total_frames={total_frames}"
            )
            frames_since_log = 0
            last_log = now

        await asyncio.sleep(0.002)


if __name__ == "__main__":
    source = sys.argv[1] if len(sys.argv) > 1 else "0"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8765
    print(f"\n  IBVAP Stage 4 Demo")
    print(f"  Source: {source!r}")
    print(f"  Open http://localhost:{port}/ in your browser to see live annotated stream.\n")
    try:
        asyncio.run(run_demo(source, port))
    except KeyboardInterrupt:
        print("\n[Demo] Stopped.")
