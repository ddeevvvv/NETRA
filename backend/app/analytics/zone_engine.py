import logging
import time
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple

logger = logging.getLogger("ibvap.analytics.zone_engine")


def is_point_in_polygon(point: Tuple[float, float], polygon: List[List[float]]) -> bool:
    """
    Ray-casting algorithm for Point-in-Polygon testing with normalized coordinates (0.0 - 1.0).
    Returns True if point (x, y) is inside or on the boundary of the polygon.
    """
    x, y = point
    n = len(polygon)
    if n < 3:
        return False

    inside = False
    p1x, p1y = polygon[0][0], polygon[0][1]

    for i in range(n + 1):
        p2x, p2y = polygon[i % n][0], polygon[i % n][1]

        # Check if point is on horizontal segment
        if p1y == p2y and p1y == y and min(p1x, p2x) <= x <= max(p1x, p2x):
            return True

        # Check if ray crosses edge
        if min(p1y, p2y) < y <= max(p1y, p2y):
            if x <= max(p1x, p2x):
                if p1y != p2y:
                    x_intersect = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                    if p1x == p2x or x <= x_intersect:
                        inside = not inside
        p1x, p1y = p2x, p2y

    return inside


@dataclass
class TrackZoneState:
    consecutive_inside_frames: int = 0
    entry_time: Optional[float] = None
    confirmed_inside: bool = False
    loitering_emitted: bool = False
    last_seen_time: float = 0.0


class ZoneEngine:
    def __init__(
        self,
        temporal_confirmation_frames: int = 2,
        track_timeout_seconds: float = 3.0,
    ):
        """
        Args:
            temporal_confirmation_frames: Number of consecutive sampled frames a track
                must be inside a zone before ZONE_ENTRY/INTRUSION fires (suppresses 1-frame jitter).
            track_timeout_seconds: Inactive seconds before a lost track is considered exited and pruned.
        """
        self.temporal_confirmation_frames = temporal_confirmation_frames
        self.track_timeout_seconds = track_timeout_seconds

        # Map: (camera_id, track_id, zone_id) -> TrackZoneState
        self.states: Dict[Tuple[str, int, str], TrackZoneState] = {}
        # Map: (camera_id, track_id) -> last_seen_timestamp
        self.track_last_seen: Dict[Tuple[str, int], float] = {}

    def get_reference_point(self, bbox: List[float], frame_width: int, frame_height: int) -> Tuple[float, float]:
        """
        Calculates the bottom-center reference point of the bounding box
        and normalizes it to the [0.0, 1.0] range.
        """
        x1, y1, x2, y2 = bbox
        center_x = (x1 + x2) / 2.0
        bottom_y = float(y2)

        norm_x = max(0.0, min(1.0, center_x / max(frame_width, 1)))
        norm_y = max(0.0, min(1.0, bottom_y / max(frame_height, 1)))
        return (norm_x, norm_y)

    def process_frame(
        self,
        camera_id: str,
        tracks: List[Dict[str, Any]],
        frame_shape: Tuple[int, ...],
        zones: List[Dict[str, Any]],
        current_time: Optional[float] = None,
    ) -> Tuple[List[Dict[str, Any]], Dict[int, List[Dict[str, Any]]]]:
        """
        Processes tracked objects against camera zones.

        Args:
            camera_id: Camera identifier (e.g. 'CAM-TEST-01').
            tracks: List of track dicts with keys: 'track_id', 'object_class', 'bbox', 'confidence'.
            frame_shape: (height, width, channels) of the frame.
            zones: List of zone dicts or objects with 'id', 'name', 'polygon_coords',
                   'restriction_level', 'dwell_threshold_seconds', 'zone_type'.
            current_time: Optional wall-clock timestamp (seconds). Uses time.time() if None.

        Returns:
            Tuple of:
              - events: List of event dicts to be posted to /api/v1/events.
              - active_zone_tracks: Dict mapping track_id -> list of zones currently confirmed inside.
        """
        now = current_time if current_time is not None else time.time()
        frame_height, frame_width = frame_shape[0], frame_shape[1]

        events: List[Dict[str, Any]] = []
        active_zone_tracks: Dict[int, List[Dict[str, Any]]] = {}

        # Normalize zones into standard dict format
        parsed_zones = []
        for z in zones:
            if hasattr(z, "__dict__"):
                z_dict = {
                    "id": getattr(z, "id"),
                    "name": getattr(z, "name", getattr(z, "id")),
                    "zone_type": getattr(z, "zone_type", "POLYGON"),
                    "polygon_coords": getattr(z, "polygon_coords", []),
                    "restriction_level": getattr(z, "restriction_level", "RESTRICTED"),
                    "dwell_threshold_seconds": float(getattr(z, "dwell_threshold_seconds", 5.0) or 5.0),
                }
            elif isinstance(z, dict):
                z_dict = {
                    "id": z.get("id"),
                    "name": z.get("name", z.get("id")),
                    "zone_type": z.get("zone_type", "POLYGON"),
                    "polygon_coords": z.get("polygon_coords", []),
                    "restriction_level": z.get("restriction_level", "RESTRICTED"),
                    "dwell_threshold_seconds": float(z.get("dwell_threshold_seconds", 5.0) or 5.0),
                }
            else:
                continue

            if z_dict["polygon_coords"] and len(z_dict["polygon_coords"]) >= 3:
                parsed_zones.append(z_dict)

        seen_track_ids = set()

        for track in tracks:
            track_id = track.get("track_id", -1)
            if track_id < 0:
                continue

            seen_track_ids.add(track_id)
            self.track_last_seen[(camera_id, track_id)] = now

            bbox = track.get("bbox", [0, 0, 0, 0])
            ref_point = self.get_reference_point(bbox, frame_width, frame_height)
            obj_class = track.get("object_class", "person")
            confidence = float(track.get("confidence", 0.0))

            for zone in parsed_zones:
                zone_id = zone["id"]
                zone_name = zone["name"]
                restriction_level = zone["restriction_level"].upper()
                dwell_threshold = zone["dwell_threshold_seconds"]
                coords = zone["polygon_coords"]

                state_key = (camera_id, track_id, zone_id)
                if state_key not in self.states:
                    self.states[state_key] = TrackZoneState()

                state = self.states[state_key]
                state.last_seen_time = now

                inside = is_point_in_polygon(ref_point, coords)

                if inside:
                    state.consecutive_inside_frames += 1

                    # 1. Check for newly confirmed zone entry
                    if state.consecutive_inside_frames >= self.temporal_confirmation_frames and not state.confirmed_inside:
                        state.confirmed_inside = True
                        state.entry_time = now

                        is_restricted = (restriction_level == "RESTRICTED")
                        event_type = "INTRUSION" if is_restricted else "ZONE_ENTRY"
                        severity = "HIGH" if is_restricted else "INFO"
                        rule_name = "Virtual Fence Breach" if is_restricted else "Zone Entry"

                        event_payload = {
                            "camera_id": camera_id,
                            "type": event_type,
                            "severity": severity,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "object_type": obj_class,
                            "track_id": track_id,
                            "confidence": round(confidence, 2),
                            "zone_id": zone_id,
                            "evidence": {},
                            "metadata": {
                                "rule_name": rule_name,
                                "zone_name": zone_name,
                                "restriction_level": restriction_level,
                                "dwell_threshold_seconds": dwell_threshold,
                                "reference_point": [round(ref_point[0], 3), round(ref_point[1], 3)],
                            }
                        }
                        events.append(event_payload)
                        logger.info(
                            f"[{camera_id}] EMIT {event_type} ({severity}) - Track #{track_id} ({obj_class}) "
                            f"entered zone {zone_id} [{restriction_level}]"
                        )

                    # 2. Check for Loitering if confirmed inside
                    elif state.confirmed_inside and not state.loitering_emitted:
                        dwell_time = now - (state.entry_time or now)
                        if dwell_time >= dwell_threshold:
                            state.loitering_emitted = True
                            event_payload = {
                                "camera_id": camera_id,
                                "type": "LOITERING",
                                "severity": "WARNING",
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                                "object_type": obj_class,
                                "track_id": track_id,
                                "confidence": round(confidence, 2),
                                "zone_id": zone_id,
                                "evidence": {},
                                "metadata": {
                                    "rule_name": "Zone Loitering Alert",
                                    "zone_name": zone_name,
                                    "restriction_level": restriction_level,
                                    "dwell_time_seconds": round(dwell_time, 1),
                                    "threshold_seconds": dwell_threshold,
                                }
                            }
                            events.append(event_payload)
                            logger.info(
                                f"[{camera_id}] EMIT LOITERING (WARNING) - Track #{track_id} ({obj_class}) "
                                f"dwelling {dwell_time:.1f}s in zone {zone_id} (threshold {dwell_threshold}s)"
                            )

                    # If track is confirmed inside this zone, record in active map
                    if state.confirmed_inside:
                        active_zone_tracks.setdefault(track_id, []).append(zone)

                else:
                    # Point is outside the polygon
                    if state.confirmed_inside:
                        dwell_time = now - (state.entry_time or now)
                        event_payload = {
                            "camera_id": camera_id,
                            "type": "ZONE_EXIT",
                            "severity": "INFO",
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "object_type": obj_class,
                            "track_id": track_id,
                            "confidence": round(confidence, 2),
                            "zone_id": zone_id,
                            "evidence": {},
                            "metadata": {
                                "rule_name": "Zone Exit",
                                "zone_name": zone_name,
                                "restriction_level": restriction_level,
                                "dwell_time_seconds": round(dwell_time, 1),
                            }
                        }
                        events.append(event_payload)
                        logger.info(
                            f"[{camera_id}] EMIT ZONE_EXIT (INFO) - Track #{track_id} ({obj_class}) "
                            f"exited zone {zone_id} after {dwell_time:.1f}s"
                        )

                    # Reset state for this zone
                    state.confirmed_inside = False
                    state.consecutive_inside_frames = 0
                    state.loitering_emitted = False
                    state.entry_time = None

        # Clean up stale track states for tracks that have left the camera view
        stale_keys = []
        for state_key, state in list(self.states.items()):
            c_id, t_id, z_id = state_key
            if c_id != camera_id:
                continue

            last_seen = self.track_last_seen.get((c_id, t_id), state.last_seen_time)
            if (now - last_seen) > self.track_timeout_seconds:
                # If track was confirmed inside before disappearing, emit ZONE_EXIT
                if state.confirmed_inside:
                    dwell_time = now - (state.entry_time or now)
                    event_payload = {
                        "camera_id": c_id,
                        "type": "ZONE_EXIT",
                        "severity": "INFO",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "object_type": "person",
                        "track_id": t_id,
                        "confidence": 1.0,
                        "zone_id": z_id,
                        "evidence": {},
                        "metadata": {
                            "rule_name": "Zone Exit (Track Lost)",
                            "dwell_time_seconds": round(dwell_time, 1),
                        }
                    }
                    events.append(event_payload)
                    logger.info(
                        f"[{c_id}] EMIT ZONE_EXIT (INFO) - Track #{t_id} disappeared from view, "
                        f"exited zone {z_id}"
                    )
                stale_keys.append(state_key)

        for k in stale_keys:
            del self.states[k]
            cam_track_key = (k[0], k[1])
            if cam_track_key in self.track_last_seen:
                del self.track_last_seen[cam_track_key]

        return events, active_zone_tracks
