import asyncio
import logging
from typing import Dict, Optional, Any

from sqlalchemy.orm import Session
from app.db.session import SessionLocal
from app.models.camera import Camera
from app.ingestion.camera_worker import CameraWorker

logger = logging.getLogger("ibvap.ingestion.manager")


class IngestionManager:
    def __init__(self):
        self.workers: Dict[str, CameraWorker] = {}
        self.tasks: Dict[str, asyncio.Task] = {}
        self._detector = None  # shared singleton across all workers
        self._tracker_cls = None  # each camera gets its own Tracker instance

    def _init_inference(self):
        """Lazy-initialise Detector once (model load is slow — do it on first need)."""
        if self._detector is not None:
            return
        try:
            from app.inference.detector import Detector
            from app.inference.tracker import Tracker
            self._detector = Detector()
            self._tracker_cls = Tracker
            logger.info("[IngestionManager] Inference components ready.")
        except Exception as e:
            logger.warning(f"[IngestionManager] Inference unavailable (run without GPU?): {e}")
            self._detector = None
            self._tracker_cls = None

    def get_worker(self, camera_id: str) -> Optional[CameraWorker]:
        return self.workers.get(camera_id)

    async def start_camera(
        self,
        camera_id: str,
        rtsp_url: str,
        target_fps: float = 5.0,
        enable_inference: bool = True,
    ):
        if camera_id in self.workers and self.workers[camera_id].is_running:
            logger.info(f"CameraWorker '{camera_id}' is already running.")
            return self.workers[camera_id]

        return await self._create_and_start_worker(
            camera_id=camera_id, rtsp_url=rtsp_url,
            target_fps=target_fps, enable_inference=enable_inference,
        )

    async def restart_camera(
        self,
        camera_id: str,
        rtsp_url: str,
        target_fps: float = 5.0,
        enable_inference: bool = True,
    ):
        """Force-stop any existing worker (even if it reports is_running=True)
        and start a brand-new one. Use this when a worker has gone zombie
        (is_running=True but last_frame_at is stale)."""
        logger.info(f"[{camera_id}] restart_camera: tearing down existing worker (if any)")
        await self.stop_camera(camera_id)
        return await self._create_and_start_worker(
            camera_id=camera_id, rtsp_url=rtsp_url,
            target_fps=target_fps, enable_inference=enable_inference,
        )

    async def _create_and_start_worker(
        self,
        camera_id: str,
        rtsp_url: str,
        target_fps: float = 5.0,
        enable_inference: bool = True,
    ):
        """Internal: create a fresh CameraWorker, attach inference, and launch its task."""
        worker = CameraWorker(
            camera_id=camera_id,
            rtsp_url=rtsp_url,
            target_fps=target_fps,
            enable_inference=enable_inference,
        )

        # Attach inference if requested
        if enable_inference:
            self._init_inference()
            if self._detector and self._tracker_cls:
                tracker = self._tracker_cls(frame_rate=int(target_fps))
                worker.set_inference(self._detector, tracker)
            else:
                logger.warning(f"[{camera_id}] Inference requested but unavailable — running detection-free.")

        self.workers[camera_id] = worker
        task = asyncio.create_task(worker.start())
        self.tasks[camera_id] = task
        logger.info(f"Started ingestion worker for camera '{camera_id}' ({rtsp_url})")
        return worker

    async def stop_camera(self, camera_id: str):
        if camera_id in self.workers:
            # Signal the worker loop to exit cleanly (sets is_running=False).
            self.workers[camera_id].stop()
            if camera_id in self.tasks:
                task = self.tasks.pop(camera_id)
                task.cancel()
                # DO NOT await the cancelled task here — we are likely being called
                # from inside a FastAPI request handler (same event loop).  Awaiting
                # a cancelled task propagates CancelledError into the caller, which
                # drops the HTTP connection.  Schedule a fire-and-forget cleanup instead.
                async def _discard(t):
                    try:
                        await t
                    except (asyncio.CancelledError, Exception):
                        pass
                asyncio.ensure_future(_discard(task))
            del self.workers[camera_id]
            logger.info(f"Stopped ingestion worker for camera '{camera_id}'")

    async def sync_cameras_from_db(self):
        """Reads active cameras from PostgreSQL and starts workers for any unstarted ones."""
        db: Session = SessionLocal()
        try:
            cameras = db.query(Camera).filter(Camera.status.in_(["ONLINE", "active", "ACTIVE", "online"])).all()
            for cam in cameras:
                if cam.id not in self.workers or not self.workers[cam.id].is_running:
                    await self.start_camera(camera_id=cam.id, rtsp_url=cam.rtsp_url)
        except Exception as e:
            logger.error(f"Error syncing cameras from DB: {e}")
        finally:
            db.close()

    def get_all_health(self) -> Dict[str, Any]:
        return {cam_id: worker.get_health_status() for cam_id, worker in self.workers.items()}


ingestion_manager = IngestionManager()
