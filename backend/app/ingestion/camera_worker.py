import asyncio
import os
import base64
import logging
import time
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
import cv2
import httpx
import numpy as np

from app.db.session import SessionLocal
from app.models.zone import Zone
from app.models.watchlist import WatchlistEntry
from app.analytics.zone_engine import ZoneEngine
from app.inference.anpr import ANPRProcessor

logger = logging.getLogger("ibvap.ingestion.worker")


class CameraWorker:
    def __init__(
        self,
        camera_id: str,
        rtsp_url: str,
        target_fps: float = 5.0,
        api_base_url: str = "http://localhost:8000",
        frozen_variance_threshold: float = 0.5,
        frozen_frame_limit: int = 15,
        disconnect_timeout_seconds: float = 5.0,
        enable_inference: bool = False,
    ):
        self.camera_id = camera_id
        self.rtsp_url = rtsp_url
        self.target_fps = target_fps
        self.sample_interval = 1.0 / target_fps
        self.api_base_url = api_base_url.rstrip("/")
        self.enable_inference = enable_inference

        self.frozen_variance_threshold = frozen_variance_threshold
        self.frozen_frame_limit = frozen_frame_limit
        self.disconnect_timeout_seconds = disconnect_timeout_seconds

        # Runtime metrics
        self.is_running = False
        self.is_connected = False
        self.is_frozen = False
        self.is_low_fps = False

        self.last_frame_at: Optional[datetime] = None
        self.measured_fps: float = 0.0

        # Internal state
        self._sampled_count = 0
        self._fps_window_start = time.time()
        self._consecutive_frozen = 0
        self._prev_frame_gray: Optional[np.ndarray] = None
        self._last_successful_frame_time = time.time()
        self._active_failures = set()
        self._frame_count = 0

        # Latest annotated frame (JPEG bytes) for debug endpoint
        self.latest_frame_raw: Optional[np.ndarray] = None
        self.latest_frame_annotated: Optional[np.ndarray] = None
        self.latest_detections: List[Dict[str, Any]] = []

        # Lazy-loaded inference components (set by manager after init)
        self._detector = None
        self._tracker = None
        self._anpr: Optional[ANPRProcessor] = None

        # Zone Analytics Engine & Zones
        self._zone_engine = ZoneEngine(temporal_confirmation_frames=2, track_timeout_seconds=3.0)
        self._zones: List[Dict[str, Any]] = []
        self._last_zone_sync_time = 0.0

        # ANPR State & Watchlist Cache
        self._watchlist_plates: Dict[str, Dict[str, Any]] = {}
        self._anpr_state: Dict[int, Dict[str, Any]] = {}
        self.recent_anpr_crops: List[Dict[str, Any]] = []
        self._last_watchlist_sync_time = 0.0

    def set_inference(self, detector, tracker, anpr: Optional[ANPRProcessor] = None):
        """Attach Detector + Tracker + ANPR after construction."""
        self._detector = detector
        self._tracker = tracker
        self._anpr = anpr if anpr is not None else ANPRProcessor()

    async def reload_zones(self):
        """Loads zones associated with this camera from database."""
        try:
            db = SessionLocal()
            try:
                db_zones = db.query(Zone).filter(Zone.camera_id == self.camera_id).all()
                self._zones = [
                    {
                        "id": z.id,
                        "name": z.name,
                        "zone_type": getattr(z, "zone_type", "POLYGON") or "POLYGON",
                        "polygon_coords": z.polygon_coords or [],
                        "restriction_level": getattr(z, "restriction_level", "RESTRICTED") or "RESTRICTED",
                        "dwell_threshold_seconds": float(getattr(z, "dwell_threshold_seconds", 5.0) or 5.0),
                    }
                    for z in db_zones
                ]
                self._last_zone_sync_time = time.time()
                logger.info(f"[{self.camera_id}] Loaded {len(self._zones)} zones into analytics engine.")
            finally:
                db.close()
        except Exception as e:
            logger.warning(f"[{self.camera_id}] Failed to reload zones: {e}")

    async def reload_watchlist(self):
        """Loads plate watchlist entries from database into memory cache."""
        try:
            db = SessionLocal()
            try:
                entries = db.query(WatchlistEntry).filter(WatchlistEntry.type == "PLATE").all()
                self._watchlist_plates = {
                    e.reference_value.upper(): {
                        "id": e.id,
                        "reference_value": e.reference_value.upper(),
                        "list_type": e.list_type.upper(),
                        "notes": e.notes,
                        "added_by": e.added_by
                    }
                    for e in entries
                }
                self._last_watchlist_sync_time = time.time()
                logger.info(f"[{self.camera_id}] Loaded {len(self._watchlist_plates)} plate watchlist entries.")
            finally:
                db.close()
        except Exception as e:
            logger.warning(f"[{self.camera_id}] Failed to reload watchlist: {e}")

    async def _post_event(self, payload: Dict[str, Any]):
        """POSTs an alert/event to /api/v1/events adhering strictly to the event schema."""
        endpoint = f"{self.api_base_url}/api/v1/events"
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.post(endpoint, json=payload)
                if resp.status_code == 201:
                    logger.info(
                        f"[{self.camera_id}] Posted {payload.get('type')} event: "
                        f"track={payload.get('track_id')} ({payload.get('severity')})"
                    )
                else:
                    logger.warning(f"[{self.camera_id}] Failed to post event: {resp.status_code} - {resp.text}")
        except Exception as e:
            logger.debug(f"[{self.camera_id}] Error posting event: {e}")

    async def _post_health_event(self, severity: str, condition: str, metadata_extra: Dict[str, Any]):
        """POSTs a CAMERA_HEALTH event adhering strictly to the event schema."""
        payload = {
            "camera_id": self.camera_id,
            "type": "CAMERA_HEALTH",
            "severity": severity,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "object_type": "system",
            "track_id": None,
            "confidence": 1.0,
            "zone_id": None,
            "evidence": {},
            "metadata": {
                "condition": condition,
                "measured_fps": round(self.measured_fps, 2),
                "target_fps": self.target_fps,
                **metadata_extra
            }
        }
        await self._post_event(payload)

    def get_health_status(self) -> Dict[str, Any]:
        """Returns camera health metrics for status indicators."""
        return {
            "camera_id": self.camera_id,
            "rtsp_url": self.rtsp_url,
            "is_running": self.is_running,
            "is_connected": self.is_connected,
            "is_frozen": self.is_frozen,
            "is_low_fps": self.is_low_fps,
            "measured_fps": round(self.measured_fps, 2),
            "target_fps": self.target_fps,
            "last_frame_at": self.last_frame_at.isoformat() if self.last_frame_at else None,
            "active_failures": list(self._active_failures),
            "latest_detection_count": len(self.latest_detections),
            "active_zones_count": len(self._zones),
            "watchlist_plates_count": len(self._watchlist_plates),
        }

    async def start(self):
        """Main camera ingestion, sampling, and inference loop."""
        self.is_running = True
        logger.info(
            f"[{self.camera_id}] Starting CameraWorker for {self.rtsp_url} "
            f"at target {self.target_fps} FPS | inference={'ON' if self.enable_inference else 'OFF'}"
        )

        # Initial zone & watchlist sync
        await self.reload_zones()
        await self.reload_watchlist()

        if self.enable_inference and self._anpr is None:
            self._anpr = ANPRProcessor()

        cap = None
        last_sample_time = 0.0

        while self.is_running:
            # ── 1. Ensure VideoCapture is open ────────────────────────────────
            if cap is None or not cap.isOpened():
                os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"
                source = int(self.rtsp_url) if self.rtsp_url.isdigit() else self.rtsp_url
                if isinstance(source, str) and ("localhost:8554" in source or "127.0.0.1:8554" in source):
                    alt_source = source.replace("localhost:8554", "mediamtx:8554").replace("127.0.0.1:8554", "mediamtx:8554")
                    cap = cv2.VideoCapture(alt_source, cv2.CAP_FFMPEG)
                    if not cap.isOpened():
                        cap = cv2.VideoCapture(source, cv2.CAP_FFMPEG)
                else:
                    cap = cv2.VideoCapture(source, cv2.CAP_FFMPEG)
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

                if not cap.isOpened():
                    now = time.time()
                    if self.is_connected or (now - self._last_successful_frame_time > self.disconnect_timeout_seconds):
                        if "DISCONNECTED" not in self._active_failures:
                            self.is_connected = False
                            self._active_failures.add("DISCONNECTED")
                            await self._post_health_event(
                                severity="HIGH",
                                condition="DISCONNECTED",
                                metadata_extra={"details": "RTSP stream connection failed"}
                            )
                    await asyncio.sleep(2.0)
                    continue

            # ── 2. Grab-and-discard buffer drain ──────────────────────────────
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

            now = time.time()

            if not ret or frame is None:
                if cap.get(cv2.CAP_PROP_FRAME_COUNT) > 0:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                await asyncio.sleep(0.01)
                continue

            # ── 3. Mark connection alive ──────────────────────────────────────
            self.is_connected = True
            self._last_successful_frame_time = now
            if "DISCONNECTED" in self._active_failures:
                self._active_failures.remove("DISCONNECTED")
                await self._post_health_event(
                    severity="INFO",
                    condition="RECOVERED",
                    metadata_extra={"restored_issue": "DISCONNECTED"}
                )

            # ── 4. Adaptive frame sampling ───────────────────────────────────
            if (now - last_sample_time) < self.sample_interval:
                await asyncio.sleep(0.002)
                continue

            last_sample_time = now
            self.last_frame_at = datetime.now(timezone.utc)
            self._sampled_count += 1
            self._frame_count += 1
            self.latest_frame_raw = frame.copy()

            # Periodic background sync (every 10s)
            if now - self._last_zone_sync_time > 10.0:
                await self.reload_zones()
            if now - self._last_watchlist_sync_time > 10.0:
                await self.reload_watchlist()

            # ── 5. Rolling FPS calculation ────────────────────────────────────
            elapsed = now - self._fps_window_start
            if elapsed >= 1.0:
                self.measured_fps = self._sampled_count / elapsed
                self._sampled_count = 0
                self._fps_window_start = now

                if self.measured_fps < (self.target_fps * 0.5):
                    if "LOW_FPS" not in self._active_failures:
                        self.is_low_fps = True
                        self._active_failures.add("LOW_FPS")
                        await self._post_health_event(
                            severity="WARNING",
                            condition="LOW_FPS",
                            metadata_extra={"threshold": self.target_fps * 0.5}
                        )
                else:
                    if "LOW_FPS" in self._active_failures:
                        self.is_low_fps = False
                        self._active_failures.remove("LOW_FPS")
                        await self._post_health_event(
                            severity="INFO",
                            condition="RECOVERED",
                            metadata_extra={"restored_issue": "LOW_FPS"}
                        )

            # ── 6. Frozen Frame Detection ─────────────────────────────────────
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            if self._prev_frame_gray is not None:
                diff = cv2.absdiff(gray, self._prev_frame_gray)
                variance = float(np.mean(diff))
                if variance < self.frozen_variance_threshold:
                    self._consecutive_frozen += 1
                    if self._consecutive_frozen >= self.frozen_frame_limit:
                        if "FROZEN" not in self._active_failures:
                            self.is_frozen = True
                            self._active_failures.add("FROZEN")
                            await self._post_health_event(
                                severity="HIGH",
                                condition="FROZEN",
                                metadata_extra={"variance": round(variance, 4), "consecutive_frames": self._consecutive_frozen}
                            )
                else:
                    self._consecutive_frozen = 0
                    if "FROZEN" in self._active_failures:
                        self.is_frozen = False
                        self._active_failures.remove("FROZEN")
                        await self._post_health_event(
                            severity="INFO",
                            condition="RECOVERED",
                            metadata_extra={"restored_issue": "FROZEN"}
                        )
            self._prev_frame_gray = gray

            # ── 7. AI Inference, Tracking, Zones & ANPR ──────────────────────
            annotated = frame.copy()
            detections = []
            active_zone_map: Dict[int, List[Dict[str, Any]]] = {}

            if self.enable_inference and self._detector is not None and self._tracker is not None:
                t0 = time.perf_counter()
                raw_detections = self._detector.detect(frame)
                tracks = self._tracker.update(raw_detections, frame)
                latency_ms = (time.perf_counter() - t0) * 1000

                # 7a. Zone Analytics Engine
                zone_events, active_zone_map = self._zone_engine.process_frame(
                    camera_id=self.camera_id,
                    tracks=tracks,
                    frame_shape=frame.shape,
                    zones=self._zones,
                    current_time=now,
                )
                for evt in zone_events:
                    asyncio.create_task(self._post_event(evt))

                # 7b. ANPR on Vehicle Tracks
                VEHICLE_CLASSES = {"car", "truck", "bus", "motorcycle"}
                for t in tracks:
                    tid = t["track_id"]
                    obj_class = t["object_class"]

                    if obj_class in VEHICLE_CLASSES and self._anpr is not None:
                        state = self._anpr_state.get(tid, {})
                        last_chk = state.get("last_checked_frame", 0)
                        has_confident_read = state.get("confidence", 0.0) >= 0.70

                        # Run ANPR every 10 frames per vehicle if not already confidently read
                        if not has_confident_read and (self._frame_count - last_chk >= 10):
                            x1, y1, x2, y2 = int(t["bbox"][0]), int(t["bbox"][1]), int(t["bbox"][2]), int(t["bbox"][3])
                            x1, y1 = max(0, x1), max(0, y1)
                            x2, y2 = min(frame.shape[1], x2), min(frame.shape[0], y2)

                            if (x2 - x1) >= 30 and (y2 - y1) >= 20:
                                crop = frame[y1:y2, x1:x2]
                                anpr_res = self._anpr.process(crop)

                                # Base64 encode crop for debug anpr-crops endpoint
                                ok, crop_buf = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 75])
                                crop_b64 = base64.b64encode(crop_buf.tobytes()).decode("utf-8") if ok else ""

                                crop_meta = {
                                    "timestamp": datetime.now(timezone.utc).isoformat(),
                                    "track_id": tid,
                                    "object_class": obj_class,
                                    "plate_read": anpr_res["plate_text"] if anpr_res else None,
                                    "raw_text": anpr_res["raw_text"] if anpr_res else None,
                                    "confidence": anpr_res["confidence"] if anpr_res else 0.0,
                                    "is_match": False,
                                    "list_type": None,
                                    "image_base64": crop_b64,
                                }

                                if anpr_res:
                                    plate = anpr_res["plate_text"]
                                    ocr_conf = anpr_res["confidence"]
                                    wl_entry = self._watchlist_plates.get(plate)

                                    if wl_entry:
                                        list_type = wl_entry["list_type"]
                                        is_blacklist = (list_type == "BLACKLIST")
                                        severity = "HIGH" if is_blacklist else "INFO"
                                        evt_type = "ANPR_MATCH"
                                        crop_meta["is_match"] = True
                                        crop_meta["list_type"] = list_type

                                        self._anpr_state[tid] = {
                                            "plate": plate,
                                            "confidence": ocr_conf,
                                            "is_match": True,
                                            "list_type": list_type,
                                            "notes": wl_entry.get("notes"),
                                            "last_checked_frame": self._frame_count,
                                        }

                                        event_payload = {
                                            "camera_id": self.camera_id,
                                            "type": evt_type,
                                            "severity": severity,
                                            "timestamp": datetime.now(timezone.utc).isoformat(),
                                            "object_type": obj_class,
                                            "track_id": tid,
                                            "confidence": ocr_conf,
                                            "zone_id": None,
                                            "evidence": {},
                                            "metadata": {
                                                "license_plate": plate,
                                                "list_type": list_type,
                                                "notes": wl_entry.get("notes"),
                                                "ocr_confidence": ocr_conf,
                                                "raw_ocr": anpr_res.get("raw_text"),
                                                "rule_name": f"Watchlist {list_type} Plate Detected",
                                            }
                                        }
                                        asyncio.create_task(self._post_event(event_payload))
                                    else:
                                        self._anpr_state[tid] = {
                                            "plate": plate,
                                            "confidence": ocr_conf,
                                            "is_match": False,
                                            "list_type": None,
                                            "last_checked_frame": self._frame_count,
                                        }
                                        event_payload = {
                                            "camera_id": self.camera_id,
                                            "type": "ANPR_READ",
                                            "severity": "INFO",
                                            "timestamp": datetime.now(timezone.utc).isoformat(),
                                            "object_type": obj_class,
                                            "track_id": tid,
                                            "confidence": ocr_conf,
                                            "zone_id": None,
                                            "evidence": {},
                                            "metadata": {
                                                "license_plate": plate,
                                                "ocr_confidence": ocr_conf,
                                                "raw_ocr": anpr_res.get("raw_text"),
                                                "rule_name": "Vehicle Plate Read",
                                            }
                                        }
                                        asyncio.create_task(self._post_event(event_payload))
                                else:
                                    self._anpr_state.setdefault(tid, {})["last_checked_frame"] = self._frame_count

                                self.recent_anpr_crops.append(crop_meta)
                                if len(self.recent_anpr_crops) > 5:
                                    self.recent_anpr_crops.pop(0)

                detections = tracks

            # ── 8. Render Zone Polygons & Detections on Annotated Frame ───────
            h, w = frame.shape[:2]
            overlay = annotated.copy()
            has_zones = False

            for z in self._zones:
                coords = z.get("polygon_coords", [])
                if not coords or len(coords) < 3:
                    continue

                has_zones = True
                pts = (np.array(coords, dtype=np.float32) * np.array([w, h])).astype(np.int32)
                pts = pts.reshape((-1, 1, 2))

                is_restricted = (z.get("restriction_level", "RESTRICTED").upper() == "RESTRICTED")
                poly_color = (0, 0, 220) if is_restricted else (220, 200, 0)

                cv2.fillPoly(overlay, [pts], poly_color)
                cv2.polylines(annotated, [pts], isClosed=True, color=poly_color, thickness=2)

                lbl_x = int(pts[0][0][0])
                lbl_y = max(int(pts[0][0][1]) - 8, 18)
                zone_label = f"[{z.get('restriction_level', 'RESTRICTED')}] {z.get('id', '')}: {z.get('name', '')}"
                cv2.putText(
                    annotated,
                    zone_label,
                    (lbl_x, lbl_y),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    poly_color,
                    2,
                )

            if has_zones:
                cv2.addWeighted(overlay, 0.25, annotated, 0.75, 0, annotated)

            # Draw bounding boxes, track labels, and ANPR plate overlays
            for t in detections:
                tid = t["track_id"]
                x1, y1, x2, y2 = int(t["bbox"][0]), int(t["bbox"][1]), int(t["bbox"][2]), int(t["bbox"][3])
                obj_class = t["object_class"]
                conf = t["confidence"]

                zones_inside = active_zone_map.get(tid, [])
                is_in_restricted = any(z.get("restriction_level", "RESTRICTED").upper() == "RESTRICTED" for z in zones_inside)
                is_in_monitored = any(z.get("restriction_level", "RESTRICTED").upper() == "MONITORED" for z in zones_inside)

                # ANPR read state
                anpr_info = self._anpr_state.get(tid, {})
                plate_text = anpr_info.get("plate")
                is_plate_match = anpr_info.get("is_match", False)
                plate_list_type = anpr_info.get("list_type")

                if is_in_restricted or (is_plate_match and plate_list_type == "BLACKLIST"):
                    box_color = (0, 0, 255)  # Bright RED for restricted intrusion or blacklist match
                    status_tag = " [INTRUSION]" if is_in_restricted else " [BLACKLIST]"
                elif is_in_monitored:
                    box_color = (0, 255, 255)  # Yellow for monitored zone
                    status_tag = " [MONITORED]"
                elif is_plate_match and plate_list_type == "WHITELIST":
                    box_color = (0, 200, 0)
                    status_tag = " [WHITELIST]"
                else:
                    box_color = (0, 255, 0) if obj_class == "person" else (255, 128, 0)
                    status_tag = ""

                plate_tag = f" · {plate_text}" if plate_text else ""
                label = f"#{tid} {obj_class} {conf:.2f}{status_tag}{plate_tag}"

                cv2.rectangle(annotated, (x1, y1), (x2, y2), box_color, 2)
                cv2.putText(
                    annotated,
                    label,
                    (x1, max(y1 - 8, 12)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.55,
                    box_color,
                    2,
                )

            self.latest_detections = detections
            self.latest_frame_annotated = annotated

            await asyncio.sleep(0.002)

        if cap:
            cap.release()
        logger.info(f"[{self.camera_id}] Stopped CameraWorker")

    def stop(self):
        self.is_running = False
