import asyncio
import os
import base64
import logging
import time
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Tuple
import cv2
import httpx
import numpy as np

from app.db.session import SessionLocal
from app.models.zone import Zone
from app.models.watchlist import WatchlistEntry
from app.analytics.zone_engine import ZoneEngine, is_point_in_polygon
from app.inference.anpr import ANPRProcessor
from app.inference.face_detector import FaceDetector

logger = logging.getLogger("ibvap.ingestion.worker")


def _draw_pill_badge(img, text: str, x: int, y: int, accent_color: tuple, font_scale: float = 0.40):
    """
    Renders a defense-grade floating pill badge:
    - Slate-900 semi-transparent backdrop: rgba(15, 23, 42, 0.82) -> BGR (42, 23, 15)
    - 1px subtle border: (59, 41, 30)
    - Colored accent indicator dot
    - Crisp white anti-aliased text
    - Clamped within image boundaries so it never clips
    """
    font = cv2.FONT_HERSHEY_SIMPLEX
    thickness = 1
    (tw, th), baseline = cv2.getTextSize(text, font, font_scale, thickness)
    pad_h = 5
    pad_v = 3
    dot_r = 3
    dot_gap = 5

    h, w = img.shape[:2]
    badge_w = pad_h + (dot_r * 2) + dot_gap + tw + pad_h
    badge_h = th + pad_v * 2 + 2

    bx1 = max(2, min(x, w - badge_w - 2))
    if y - badge_h - 2 >= 0:
        by1 = y - badge_h - 2
    else:
        by1 = min(y + 4, h - badge_h - 2)
    by2 = by1 + badge_h

    # Semi-transparent dark pill background (Slate-900 BGR)
    sub_img = img[by1:by2, bx1:bx1 + badge_w]
    if sub_img.shape[0] == badge_h and sub_img.shape[1] == badge_w:
        rect = np.full(sub_img.shape, (42, 23, 15), dtype=np.uint8)
        cv2.addWeighted(rect, 0.82, sub_img, 0.18, 0, sub_img)
        img[by1:by2, bx1:bx1 + badge_w] = sub_img

    # 1px subtle border
    cv2.rectangle(img, (bx1, by1), (bx1 + badge_w, by2), (59, 41, 30), 1)

    # Accent status dot
    dot_x = bx1 + pad_h + dot_r
    dot_y = by1 + badge_h // 2
    cv2.circle(img, (dot_x, dot_y), dot_r, accent_color, -1)

    # Sharp white text (LINE_AA for smooth edges)
    text_x = dot_x + dot_r + dot_gap
    text_y = by1 + pad_v + th
    cv2.putText(
        img,
        text,
        (text_x, text_y),
        font,
        font_scale,
        (255, 255, 255),
        1,
        cv2.LINE_AA,
    )


def _fetch_frame(cap: cv2.VideoCapture) -> Tuple[bool, Optional[np.ndarray]]:
    """Fetches the freshest frame from VideoCapture.
    Drains at most 1 stale frame if present without stalling the pipeline
    waiting for multiple future frame capture intervals.
    """
    try:
        # At most 1 discard grab to flush any single stale buffered frame
        cap.grab()
        ret, frame = cap.retrieve()
        if not ret or frame is None:
            ret, frame = cap.read()
        return ret, frame
    except Exception:
        return False, None


def _render_annotations(
    frame: np.ndarray,
    zones: List[Dict[str, Any]],
    detections: List[Dict[str, Any]],
    active_zone_map: Dict[int, List[Dict[str, Any]]],
    anpr_state: Dict[int, Dict[str, Any]],
    latest_face_detections: List[Dict[str, Any]],
) -> np.ndarray:
    """Renders zone polygons, bounding boxes, labels, ANPR badges, and face tags.
    Executed in a worker thread to keep the asyncio event loop unblocked.
    """
    annotated = frame.copy()
    h, w = frame.shape[:2]
    overlay = annotated.copy()
    has_zones = False

    for z in zones:
        coords = z.get("polygon_coords", [])
        if not coords or len(coords) < 3:
            continue

        has_zones = True
        pts = (np.array(coords, dtype=np.float32) * np.array([w, h])).astype(np.int32)
        pts = pts.reshape((-1, 1, 2))

        is_restricted = (z.get("restriction_level", "RESTRICTED").upper() == "RESTRICTED")
        poly_color = (0, 0, 220) if is_restricted else (220, 200, 0)

        cv2.fillPoly(overlay, [pts], poly_color)
        cv2.polylines(annotated, [pts], isClosed=True, color=poly_color, thickness=1)

        lbl_x = int(pts[0][0][0])
        lbl_y = int(pts[0][0][1])
        zone_label = f"[{z.get('restriction_level', 'RESTRICTED')}] {z.get('id', '')}: {z.get('name', '')}"
        _draw_pill_badge(annotated, zone_label, lbl_x, lbl_y, poly_color, font_scale=0.38)

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
        anpr_info = anpr_state.get(tid, {})
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
        label = f"#{tid} {obj_class} {int(conf * 100)}%{status_tag}{plate_tag}"

        # 1.5px / 1px crisp bounding box
        cv2.rectangle(annotated, (x1, y1), (x2, y2), box_color, 1)
        # Floating pill badge with Slate-900 backdrop and accent dot
        _draw_pill_badge(annotated, label, x1, y1, box_color, font_scale=0.38)

    # Draw face detection bounding boxes (1px stroke + non-overlapping pill badge below)
    for f in latest_face_detections:
        fx1, fy1, fx2, fy2 = int(f["bbox"][0]), int(f["bbox"][1]), int(f["bbox"][2]), int(f["bbox"][3])
        fconf = f["confidence"]
        face_color = (255, 180, 0)  # Defense cyan/blue in BGR
        cv2.rectangle(annotated, (fx1, fy1), (fx2, fy2), face_color, 1)
        _draw_pill_badge(
            annotated,
            f"FACE {int(fconf * 100)}%",
            fx1,
            fy2 + 16,
            face_color,
            font_scale=0.34,
        )

    return annotated


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
        # LOW_FPS hysteresis timers (seconds-based monotonic timestamps)
        self._low_fps_since: float = 0.0
        self._fps_recovered_since: float = 0.0

        self.connection_state: str = "OFFLINE"  # ONLINE, DEGRADED, RECONNECTING, OFFLINE
        self.reconnect_attempt_count: int = 0
        self.max_reconnect_retries: int = 10
        self.last_seen_at: Optional[datetime] = None
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
        self.latest_face_detections: List[Dict[str, Any]] = []
        self._last_face_event_time: Dict[str, float] = {}

        # Lazy-loaded inference components (set by manager after init)
        self._detector = None
        self._tracker = None
        self._anpr: Optional[ANPRProcessor] = None
        self._face_detector: Optional[FaceDetector] = None
        self._inference_lock: Optional[asyncio.Lock] = None

        # Zone Analytics Engine & Zones
        self._zone_engine = ZoneEngine(temporal_confirmation_frames=2, track_timeout_seconds=3.0)
        self._zones: List[Dict[str, Any]] = []
        self._last_zone_sync_time = 0.0

        # ANPR State & Watchlist Cache
        self._watchlist_plates: Dict[str, Dict[str, Any]] = {}
        self._anpr_state: Dict[int, Dict[str, Any]] = {}
        self.recent_anpr_crops: List[Dict[str, Any]] = []
        self._last_watchlist_sync_time = 0.0

        # VEHICLE_DETECTED debounce — track_ids that already fired this ingestion session
        self._vehicle_alerted_tracks: set = set()
        # Per-camera, per-object-class 30s cooldown for VEHICLE_DETECTED (dict of last-fired times)
        self._vehicle_event_cooldown: Dict[str, float] = {}

        # Night-mode / NIGHT_MOVEMENT detection state
        self._night_mode_active: bool = False
        self._night_event_cooldown: Dict[str, float] = {}
        self._night_event_debounce: float = float(os.environ.get("NIGHT_MOVEMENT_DEBOUNCE", 30.0))
        self._night_brightness_threshold: float = float(os.environ.get("NIGHT_BRIGHTNESS_THRESHOLD", 60.0))
        self._night_movement_enabled: bool = os.environ.get("NIGHT_MOVEMENT_ENABLED", "true").lower() == "true"
        self._night_motion_threshold: float = 3.0  # mean abs-diff to count as motion in dark scene

        # 4-K cap: downsample frames wider than this before YOLO inference
        self._inference_max_width: int = int(os.environ.get("INFERENCE_MAX_WIDTH", 960))

        # Persistent HTTP client for connection pooling
        self._http_client: Optional[httpx.AsyncClient] = None

    def set_inference(
        self,
        detector,
        tracker,
        anpr: Optional[ANPRProcessor] = None,
        face_detector: Optional[FaceDetector] = None,
        inference_lock: Optional[asyncio.Lock] = None,
    ):
        """Attach Detector + Tracker + ANPR + FaceDetector + Inference Lock after construction."""
        self._detector = detector
        self._tracker = tracker
        self._anpr = anpr if anpr is not None else ANPRProcessor()
        self._face_detector = face_detector
        self._inference_lock = inference_lock

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

    def _get_http_client(self) -> httpx.AsyncClient:
        """Returns or creates a shared httpx.AsyncClient for connection reuse."""
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(timeout=3.0)
        return self._http_client

    async def _post_event(self, payload: Dict[str, Any]):
        """POSTs an alert/event to /api/v1/events adhering strictly to the event schema."""
        endpoint = f"{self.api_base_url}/api/v1/events"
        try:
            client = self._get_http_client()
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
            "connection_state": self.connection_state,
            "reconnect_attempt_count": self.reconnect_attempt_count,
            "last_seen_at": self.last_seen_at.isoformat() if self.last_seen_at else None,
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
        if self.enable_inference and self._face_detector is None:
            self._face_detector = FaceDetector()

        cap = None
        last_sample_time = 0.0

        while self.is_running:
            # ── 1. Ensure VideoCapture is open ────────────────────────────────
            if cap is None or not cap.isOpened():
                self.reconnect_attempt_count += 1
                if self.reconnect_attempt_count < self.max_reconnect_retries:
                    self.connection_state = "RECONNECTING"
                else:
                    self.connection_state = "OFFLINE"

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
                    await asyncio.sleep(min(1.0, max(0.05, self.disconnect_timeout_seconds / 2.0)))
                    continue

            # ── 2. Frame acquisition (offloaded to thread, 1-frame drain) ─────
            ret, frame = await asyncio.to_thread(_fetch_frame, cap)

            now = time.time()

            if not ret or frame is None:
                if cap.get(cv2.CAP_PROP_FRAME_COUNT) > 0:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                if now - self._last_successful_frame_time > self.disconnect_timeout_seconds:
                    self.is_connected = False
                    self.reconnect_attempt_count += 1
                    if self.reconnect_attempt_count < self.max_reconnect_retries:
                        self.connection_state = "RECONNECTING"
                    else:
                        self.connection_state = "OFFLINE"
                    if cap is not None:
                        cap.release()
                        cap = None
                await asyncio.sleep(0.01)
                continue

            # ── 3. Mark connection alive ──────────────────────────────────────
            self.is_connected = True
            self.reconnect_attempt_count = 0
            self._last_successful_frame_time = now
            self.last_seen_at = datetime.now(timezone.utc)
            self.last_frame_at = self.last_seen_at
            if self.is_frozen or self.is_low_fps:
                self.connection_state = "DEGRADED"
            else:
                self.connection_state = "ONLINE"

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

                low_threshold = self.target_fps * 0.5
                recovery_threshold = self.target_fps * 0.8

                if self.measured_fps < low_threshold:
                    if self._low_fps_since == 0.0:
                        self._low_fps_since = now
                    if "LOW_FPS" not in self._active_failures:
                        if (now - self._low_fps_since) >= 10.0:
                            self.is_low_fps = True
                            self._active_failures.add("LOW_FPS")
                            await self._post_health_event(
                                severity="WARNING",
                                condition="LOW_FPS",
                                metadata_extra={
                                    "threshold": low_threshold,
                                    "measured_fps": round(self.measured_fps, 2),
                                    "duration_seconds": round(now - self._low_fps_since, 1),
                                }
                            )
                    self._fps_recovered_since = 0.0
                elif self.measured_fps >= recovery_threshold:
                    if "LOW_FPS" in self._active_failures:
                        if self._fps_recovered_since == 0.0:
                            self._fps_recovered_since = now
                        if (now - self._fps_recovered_since) >= 30.0:
                            self.is_low_fps = False
                            self._active_failures.remove("LOW_FPS")
                            await self._post_health_event(
                                severity="INFO",
                                condition="RECOVERED",
                                metadata_extra={
                                    "restored_issue": "LOW_FPS",
                                    "measured_fps": round(self.measured_fps, 2),
                                    "recovery_duration_seconds": round(now - self._fps_recovered_since, 1),
                                }
                            )
                    self._low_fps_since = 0.0
                else:
                    self._low_fps_since = 0.0
                    self._fps_recovered_since = 0.0

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
            prev_gray_snapshot = self._prev_frame_gray  # capture before overwrite
            self._prev_frame_gray = gray

            # ── 6b. Night Mode & NIGHT_MOVEMENT detection ─────────────────────
            mean_brightness = float(np.mean(gray))
            self._night_mode_active = mean_brightness < self._night_brightness_threshold

            if (
                self._night_movement_enabled
                and self._night_mode_active
                and prev_gray_snapshot is not None
            ):
                diff_nm = cv2.absdiff(gray, prev_gray_snapshot)
                motion_score = float(np.mean(diff_nm))
                if (
                    motion_score > self._night_motion_threshold
                    and (now - self._night_event_cooldown.get("motion", 0.0)) >= self._night_event_debounce
                ):
                    self._night_event_cooldown["motion"] = now
                    asyncio.create_task(self._post_event({
                        "camera_id": self.camera_id,
                        "type": "NIGHT_MOVEMENT",
                        "severity": "HIGH",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "object_type": "motion",
                        "track_id": None,
                        "confidence": round(min(1.0, motion_score / 20.0), 3),
                        "zone_id": None,
                        "evidence": {},
                        "metadata": {
                            "rule_name": "Night Movement Detected",
                            "mean_brightness": round(mean_brightness, 1),
                            "motion_score": round(motion_score, 3),
                            "brightness_threshold": self._night_brightness_threshold,
                        },
                    }))
                    logger.info(
                        f"[{self.camera_id}] EMIT NIGHT_MOVEMENT (HIGH) — "
                        f"brightness={mean_brightness:.1f} motion={motion_score:.3f}"
                    )

            # ── 7. AI Inference, Tracking, Zones & ANPR ──────────────────────
            # Downscale 4K+ frames before YOLO to avoid memory/perf issues.
            inf_frame = frame
            if frame.shape[1] > self._inference_max_width:
                scale = self._inference_max_width / frame.shape[1]
                inf_frame = cv2.resize(frame, (self._inference_max_width, int(frame.shape[0] * scale)), interpolation=cv2.INTER_AREA)

            annotated = frame.copy()
            detections = []
            active_zone_map: Dict[int, List[Dict[str, Any]]] = {}

            if self.enable_inference and self._detector is not None and self._tracker is not None:
                t0 = time.perf_counter()
                if self._inference_lock is not None:
                    async with self._inference_lock:
                        raw_detections = await asyncio.to_thread(self._detector.detect, inf_frame)
                else:
                    raw_detections = await asyncio.to_thread(self._detector.detect, inf_frame)
                tracks = await asyncio.to_thread(self._tracker.update, raw_detections, frame)
                latency_ms = (time.perf_counter() - t0) * 1000

                # 7a. Zone Analytics Engine (offloaded to thread)
                zone_events, active_zone_map = await asyncio.to_thread(
                    self._zone_engine.process_frame,
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
                                if self._inference_lock is not None:
                                    async with self._inference_lock:
                                        anpr_res = await asyncio.to_thread(self._anpr.process, crop)
                                else:
                                    anpr_res = await asyncio.to_thread(self._anpr.process, crop)

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
                                                "plate_text": plate,
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
                                                "plate_text": plate,
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

                # 7b-extra. VEHICLE_DETECTED — fire once per new vehicle track_id
                LARGE_VEHICLES = {"truck", "bus"}
                for t in tracks:
                    tid = t["track_id"]
                    obj_class = t["object_class"]
                    if obj_class in VEHICLE_CLASSES and tid not in self._vehicle_alerted_tracks:
                        if (now - self._vehicle_event_cooldown.get(obj_class, 0.0)) >= 30.0:
                            self._vehicle_event_cooldown[obj_class] = now
                            self._vehicle_alerted_tracks.add(tid)
                            severity = "HIGH" if obj_class in LARGE_VEHICLES else "WARNING"
                            asyncio.create_task(self._post_event({
                                "camera_id": self.camera_id,
                                "type": "VEHICLE_DETECTED",
                                "severity": severity,
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                                "object_type": obj_class,
                                "track_id": tid,
                                "confidence": round(t.get("confidence", 0.0), 3),
                                "zone_id": None,
                                "evidence": {},
                                "metadata": {
                                    "rule_name": "Vehicle Detected",
                                    "vehicle_class": obj_class,
                                    "bbox": [round(c, 1) for c in t.get("bbox", [])],
                                },
                            }))
                            logger.info(
                                f"[{self.camera_id}] EMIT VEHICLE_DETECTED ({severity}) — "
                                f"class={obj_class} track_id={tid} conf={t.get('confidence', 0):.2f}"
                        )
                    # Prune stale track IDs to avoid unbounded growth (keep last 500)
                    if len(self._vehicle_alerted_tracks) > 500:
                        self._vehicle_alerted_tracks = set(
                            list(self._vehicle_alerted_tracks)[-500:]
                        )

                # 7c. Face Detection & Restricted Zone Alerting
                if self._face_detector is not None:
                    try:
                        if self._inference_lock is not None:
                            async with self._inference_lock:
                                detected_faces = await asyncio.to_thread(self._face_detector.detect, frame)
                        else:
                            detected_faces = await asyncio.to_thread(self._face_detector.detect, frame)
                        self.latest_face_detections = detected_faces

                        for face in detected_faces:
                            fb = face["bbox"]
                            fcx = (fb[0] + fb[2]) / 2.0
                            fcy = (fb[1] + fb[3]) / 2.0
                            face_ref = (fcx / max(frame.shape[1], 1), fcy / max(frame.shape[0], 1))

                            for z in self._zones:
                                restriction = z.get("restriction_level", "RESTRICTED").upper()
                                if restriction != "RESTRICTED":
                                    continue
                                poly = z.get("polygon_coords", [])
                                if not poly or len(poly) < 3:
                                    continue

                                if is_point_in_polygon(face_ref, poly):
                                    # Match face to person track if face center is enclosed in track bbox
                                    matched_track_id = None
                                    for t in tracks:
                                        if t.get("object_class") == "person":
                                            tb = t.get("bbox", [0, 0, 0, 0])
                                            if tb[0] <= fcx <= tb[2] and tb[1] <= fcy <= tb[3]:
                                                matched_track_id = t.get("track_id")
                                                break

                                    debounce_key = f"{z.get('id')}:{matched_track_id}" if matched_track_id is not None else f"{z.get('id')}:face_{int(face_ref[0]*100)}_{int(face_ref[1]*100)}"
                                    if (now - self._last_face_event_time.get(debounce_key, 0.0)) >= 5.0:
                                        self._last_face_event_time[debounce_key] = now
                                        face_payload = {
                                            "camera_id": self.camera_id,
                                            "type": "FACE_DETECTED",
                                            "severity": "INFO",
                                            "timestamp": datetime.now(timezone.utc).isoformat(),
                                            "object_type": "face",
                                            "track_id": matched_track_id,
                                            "confidence": face["confidence"],
                                            "zone_id": z.get("id"),
                                            "evidence": {},
                                            "metadata": {
                                                "rule_name": "Face in Restricted Zone",
                                                "zone_name": z.get("name", z.get("id")),
                                                "restriction_level": "RESTRICTED",
                                                "face_bbox": [round(c, 1) for c in fb],
                                                "associated_track_id": matched_track_id,
                                            }
                                        }
                                        asyncio.create_task(self._post_event(face_payload))
                                        logger.info(
                                            f"[{self.camera_id}] EMIT FACE_DETECTED (INFO) - Face in restricted zone "
                                            f"{z.get('id')} (conf={face['confidence']}, track={matched_track_id})"
                                        )
                    except Exception as e:
                        logger.warning(f"[{self.camera_id}] Error in face detection loop: {e}")
            else:
                self.latest_face_detections = []

            # ── 8. Render Zone Polygons & Detections on Annotated Frame ───────
            annotated = await asyncio.to_thread(
                _render_annotations,
                frame,
                self._zones,
                detections,
                active_zone_map,
                self._anpr_state,
                self.latest_face_detections,
            )

            self.latest_detections = detections
            self.latest_frame_annotated = annotated

            await asyncio.sleep(0.002)

        if cap:
            cap.release()
        if self._http_client is not None and not self._http_client.is_closed:
            await self._http_client.aclose()
        logger.info(f"[{self.camera_id}] Stopped CameraWorker")

    def stop(self):
        self.is_running = False
        self.is_connected = False
        self.connection_state = "OFFLINE"
        if self._http_client is not None and not self._http_client.is_closed:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._http_client.aclose())
            except RuntimeError:
                pass
