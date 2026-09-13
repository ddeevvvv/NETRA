import asyncio
import os
import time
import pytest
import cv2
import numpy as np
from app.ingestion.camera_worker import CameraWorker

@pytest.fixture
def sample_video_file(tmp_path):
    """Creates a temporary 3-second video file with changing frames for testing."""
    video_path = str(tmp_path / "test_stream.mp4")
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(video_path, fourcc, 30.0, (320, 240))

    for i in range(90):
        # Create animated frame (changing color rectangle)
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        cv2.rectangle(frame, (i % 200, 50), (i % 200 + 50, 100), (0, 255, (i * 3) % 255), -1)
        out.write(frame)
    out.release()
    return video_path

@pytest.mark.asyncio
async def test_camera_worker_sampling_and_disconnect(sample_video_file, client):
    # 1. Create CameraWorker pointing to local test video file
    worker = CameraWorker(
        camera_id="CAM-TEST-01",
        rtsp_url=sample_video_file,
        target_fps=5.0,
        disconnect_timeout_seconds=1.0,
        frozen_frame_limit=100
    )

    task = asyncio.create_task(worker.start())

    # Allow worker to run for 2.5 seconds to sample frames
    await asyncio.sleep(2.5)

    health = worker.get_health_status()
    assert health["is_connected"] is True
    assert health["last_frame_at"] is not None
    assert health["measured_fps"] > 0.0

    # Stop worker and cancel task cleanly
    worker.stop()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

@pytest.mark.asyncio
async def test_camera_worker_disconnect_detection(client):
    # Create worker pointing to invalid/unreachable RTSP URL
    worker = CameraWorker(
        camera_id="CAM-UNREACHABLE",
        rtsp_url="rtsp://invalid_host:8554/dead_stream",
        target_fps=5.0,
        disconnect_timeout_seconds=0.5
    )

    task = asyncio.create_task(worker.start())

    # Wait for disconnect timeout
    await asyncio.sleep(1.2)

    health = worker.get_health_status()
    assert health["is_connected"] is False
    assert "DISCONNECTED" in health["active_failures"]

    worker.stop()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
