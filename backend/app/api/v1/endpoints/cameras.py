import asyncio
import logging
from typing import List, Optional, Dict, Any

import cv2
import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.camera import Camera
from app.schemas.camera import CameraCreate, CameraResponse
from app.ingestion.manager import ingestion_manager

router = APIRouter()
logger = logging.getLogger("ibvap.api.cameras")


# ── CRUD ────────────────────────────────────────────────────────────────────

@router.post("", response_model=CameraResponse, status_code=status.HTTP_201_CREATED)
async def create_camera(camera_in: CameraCreate, db: Session = Depends(get_db)):
    existing = db.query(Camera).filter(Camera.id == camera_in.id).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Camera with ID '{camera_in.id}' already exists"
        )
    db_camera = Camera(**camera_in.model_dump())
    db.add(db_camera)
    db.commit()
    db.refresh(db_camera)

    # Automatically start ingestion worker + inference if ONLINE or ACTIVE
    if db_camera.status and db_camera.status.upper() in ("ONLINE", "ACTIVE"):
        await ingestion_manager.start_camera(
            camera_id=db_camera.id,
            rtsp_url=db_camera.rtsp_url,
            enable_inference=True,
        )

    return db_camera


@router.get("", response_model=List[CameraResponse])
def list_cameras(db: Session = Depends(get_db)):
    return db.query(Camera).all()


@router.get("/health-all", response_model=Dict[str, Dict[str, Any]])
async def get_all_camera_health(db: Session = Depends(get_db)):
    """Returns consolidated health metrics for all registered cameras in a single payload."""
    cameras = db.query(Camera).all()
    result = {}
    for cam in cameras:
        worker = ingestion_manager.get_worker(cam.id)
        if not worker or not worker.is_running:
            worker = await ingestion_manager.start_camera(
                camera_id=cam.id,
                rtsp_url=cam.rtsp_url,
                enable_inference=True,
            )
        health = worker.get_health_status()
        if worker.last_seen_at and cam.last_seen_at != worker.last_seen_at:
            cam.last_seen_at = worker.last_seen_at
        elif not health.get("last_seen_at") and cam.last_seen_at:
            health["last_seen_at"] = cam.last_seen_at.isoformat()
        result[cam.id] = health
    db.commit()
    return result


@router.get("/{camera_id}", response_model=CameraResponse)
def get_camera(camera_id: str, db: Session = Depends(get_db)):
    camera = db.query(Camera).filter(Camera.id == camera_id).first()
    if not camera:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Camera '{camera_id}' not found"
        )
    return camera


@router.post("/{camera_id}/start", response_model=CameraResponse)
async def start_camera_endpoint(
    camera_id: str,
    target_fps: float = 5.0,
    db: Session = Depends(get_db),
):
    camera = db.query(Camera).filter(Camera.id == camera_id).first()
    if not camera:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Camera '{camera_id}' not found"
        )
    await ingestion_manager.start_camera(
        camera_id=camera.id,
        rtsp_url=camera.rtsp_url,
        target_fps=target_fps,
        enable_inference=True
    )
    return camera


@router.post("/{camera_id}/restart", response_model=CameraResponse)
async def restart_camera_endpoint(
    camera_id: str,
    target_fps: float = 5.0,
    db: Session = Depends(get_db),
):
    """Force-recycle the ingestion worker even if it reports is_running=True.
    Use this when health shows is_connected=True but last_frame_at is stale (zombie worker)."""
    camera = db.query(Camera).filter(Camera.id == camera_id).first()
    if not camera:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Camera '{camera_id}' not found"
        )
    await ingestion_manager.restart_camera(
        camera_id=camera.id,
        rtsp_url=camera.rtsp_url,
        target_fps=target_fps,
        enable_inference=True
    )
    return camera


@router.post("/{camera_id}/stop", response_model=CameraResponse)
async def stop_camera_endpoint(camera_id: str, db: Session = Depends(get_db)):
    """Stop the ingestion worker for the camera."""
    camera = db.query(Camera).filter(Camera.id == camera_id).first()
    if not camera:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Camera '{camera_id}' not found"
        )
    await ingestion_manager.stop_camera(camera_id=camera.id)
    return camera


@router.get("/{camera_id}/health")
async def get_camera_health(camera_id: str, db: Session = Depends(get_db)):
    """Returns camera health status, last_frame_at, connection_state, and measured_fps."""
    worker = ingestion_manager.get_worker(camera_id)
    if not worker or not worker.is_running:
        camera = db.query(Camera).filter(Camera.id == camera_id).first()
        if not camera:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Camera '{camera_id}' not found"
            )
        worker = await ingestion_manager.start_camera(
            camera_id=camera.id,
            rtsp_url=camera.rtsp_url,
            enable_inference=True
        )
    health = worker.get_health_status()
    # Sync with DB if last_seen_at is known
    cam = db.query(Camera).filter(Camera.id == camera_id).first()
    if cam:
        if worker.last_seen_at and cam.last_seen_at != worker.last_seen_at:
            cam.last_seen_at = worker.last_seen_at
            db.commit()
        elif not health.get("last_seen_at") and cam.last_seen_at:
            health["last_seen_at"] = cam.last_seen_at.isoformat()
    return health


# ── Debug Endpoints ──────────────────────────────────────────────────────────

async def _get_worker_or_start(camera_id: str, db: Session):
    worker = ingestion_manager.get_worker(camera_id)
    if not worker or not worker.is_running:
        camera = db.query(Camera).filter(Camera.id == camera_id).first()
        if not camera:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No active worker for camera '{camera_id}'."
            )
        worker = await ingestion_manager.start_camera(
            camera_id=camera.id,
            rtsp_url=camera.rtsp_url,
            enable_inference=True
        )
    return worker


def _encode_frame_jpeg(frame: np.ndarray, quality: int = 85) -> bytes:
    """Encode a BGR frame to JPEG bytes."""
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise RuntimeError("JPEG encode failed")
    return buf.tobytes()


@router.get(
    "/{camera_id}/debug/snapshot",
    response_class=Response,
    summary="Single annotated JPEG snapshot from the camera",
    responses={200: {"content": {"image/jpeg": {}}}},
)
async def debug_snapshot(camera_id: str, db: Session = Depends(get_db)):
    """
    Returns the most-recent sampled frame as a JPEG with bounding boxes,
    track IDs, and class labels drawn on it. View directly in a browser.
    """
    worker = await _get_worker_or_start(camera_id, db)

    frame = worker.latest_frame_annotated if worker.latest_frame_annotated is not None else worker.latest_frame_raw
    if frame is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No frame available yet — worker may still be connecting."
        )

    jpeg_bytes = _encode_frame_jpeg(frame)
    return Response(
        content=jpeg_bytes,
        media_type="image/jpeg",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


async def _mjpeg_generator(worker, request: Request):
    """
    Async generator that yields MJPEG boundary frames indefinitely.
    Pulls latest_frame_annotated from the worker at ~10 fps for the browser.
    Terminates cleanly as soon as the client disconnects or closes the tab.
    """
    BOUNDARY = b"--ibvap_frame"

    try:
        while worker.is_running:
            if await request.is_disconnected():
                logger.info(f"Client disconnected from debug stream for camera {worker.camera_id}")
                break

            frame = worker.latest_frame_annotated if worker.latest_frame_annotated is not None else worker.latest_frame_raw
            if frame is not None:
                try:
                    jpeg = _encode_frame_jpeg(frame)
                except Exception:
                    await asyncio.sleep(0.1)
                    continue

                # Correct MJPEG multipart format:
                #   --boundary\r\n
                #   Content-Type: image/jpeg\r\n
                #   Content-Length: <n>\r\n
                #   \r\n
                #   <jpeg bytes>\r\n
                chunk = (
                    BOUNDARY + b"\r\n"
                    + b"Content-Type: image/jpeg\r\n"
                    + b"Content-Length: " + str(len(jpeg)).encode() + b"\r\n"
                    + b"\r\n"
                    + jpeg
                    + b"\r\n"
                )
                yield chunk
            else:
                # No frame yet — yield an empty keep-alive to prevent connection drop
                await asyncio.sleep(0.05)
                continue
            await asyncio.sleep(0.1)  # ~10 fps to browser
    except (asyncio.CancelledError, GeneratorExit):
        logger.info(f"Stream connection closed for camera {worker.camera_id}")
    except Exception as e:
        logger.warning(f"Error in MJPEG stream for {worker.camera_id}: {e}")


@router.get(
    "/{camera_id}/debug/stream",
    summary="Live MJPEG stream with bounding boxes and track IDs",
    responses={200: {"content": {"multipart/x-mixed-replace; boundary=ibvap_frame": {}}}},
)
async def debug_stream(camera_id: str, request: Request, db: Session = Depends(get_db)):
    """
    Live MJPEG stream of annotated frames. Open in a browser or VLC:
      http://localhost:8000/api/v1/cameras/{id}/debug/stream
    """
    worker = await _get_worker_or_start(camera_id, db)
    return StreamingResponse(
        _mjpeg_generator(worker, request),
        media_type="multipart/x-mixed-replace; boundary=ibvap_frame",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
            "Connection": "close",
            "X-Accel-Buffering": "no",
        },
    )


@router.get(
    "/{camera_id}/debug/anpr-crops",
    summary="Recent vehicle crops evaluated by ANPR",
    response_model=List[Dict[str, Any]]
)
async def debug_anpr_crops(camera_id: str, db: Session = Depends(get_db)):
    """
    Returns the most recent 5 vehicle crops evaluated by PaddleOCR,
    including plate read, OCR confidence, raw OCR text, match status, and base64 crop image.
    """
    worker = await _get_worker_or_start(camera_id, db)
    return list(reversed(worker.recent_anpr_crops))
