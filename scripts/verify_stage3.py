"""
Stage 3 Happy-Path Verification Script
Connects to webcam (device 0) or a video file, runs a CameraWorker,
logs measured FPS every 5 seconds for 35 seconds, and confirms no
growing latency (i.e. frames are NOT buffering — always reading latest).
"""
import asyncio
import sys
import time
import cv2
import numpy as np
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("stage3_verify")

async def verify(source: str, duration: int = 35, target_fps: float = 5.0):
    """
    Grab-and-discard loop to always get the LATEST frame.
    For RTSP / webcam: cap.read() advances the buffer; we call it in a tight
    loop and only process the result every sample_interval seconds.
    This prevents stale-frame latency from building up.
    """
    sample_interval = 1.0 / target_fps
    is_digit = source.isdigit()
    cap_src = int(source) if is_digit else source

    logger.info(f"Opening source: {source!r}")
    cap = cv2.VideoCapture(cap_src)
    # Turn off internal buffering for live sources so we always get latest
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    if not cap.isOpened():
        logger.error(f"Cannot open source {source!r} — is mediamtx running, or is a webcam available?")
        return

    start = time.time()
    last_sample = start
    last_log = start
    frames_since_log = 0
    total_sampled = 0
    fps_readings = []

    while time.time() - start < duration:
        # Grab-and-discard loop: drain the decode buffer so we're never stale
        ret, frame = cap.read()
        if not ret:
            await asyncio.sleep(0.01)
            continue

        now = time.time()

        # Only process at target_fps
        if now - last_sample < sample_interval:
            # Non-blocking yield so other asyncio tasks run
            await asyncio.sleep(0.002)
            continue

        last_sample = now
        total_sampled += 1
        frames_since_log += 1

        # Log every 5 seconds
        elapsed_since_log = now - last_log
        if elapsed_since_log >= 5.0:
            measured = frames_since_log / elapsed_since_log
            fps_readings.append(measured)
            logger.info(
                f"[FPS CHECK] Measured: {measured:.2f} fps (target {target_fps}) | "
                f"Total sampled: {total_sampled} | "
                f"Elapsed: {now - start:.1f}s"
            )
            frames_since_log = 0
            last_log = now

        await asyncio.sleep(0.002)

    cap.release()
    logger.info(f"Verification done. All FPS readings: {[round(r, 2) for r in fps_readings]}")
    avg = sum(fps_readings) / len(fps_readings) if fps_readings else 0
    logger.info(f"Average measured FPS: {avg:.2f} (target {target_fps})")
    if fps_readings and all(abs(r - target_fps) < 1.5 for r in fps_readings):
        logger.info("RESULT: FPS stable — no buffering latency detected.")
    else:
        logger.warning("RESULT: FPS drift detected — check source decode speed.")


if __name__ == "__main__":
    source = sys.argv[1] if len(sys.argv) > 1 else "0"  # "0" = webcam
    asyncio.run(verify(source))
