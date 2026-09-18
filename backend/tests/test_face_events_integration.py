import pytest
from app.models.camera import Camera
from app.models.zone import Zone
from app.models.event import Event
from app.analytics.zone_engine import is_point_in_polygon


def test_face_detection_restricted_zone_event_integration(client, db_session):
    """
    Assert that FACE_DETECTED events are only emitted when a face is inside
    a RESTRICTED zone, and NOT when outside any zone or in a non-restricted zone.
    """
    # 1. Setup Camera and Zones (Z-01 Restricted, Z-02 Monitored)
    cam = Camera(id="CAM-TEST-01", name="Perimeter Cam", rtsp_url="rtsp://localhost:8554/cam1", status="ONLINE")
    restricted_zone = Zone(
        id="Z-01",
        camera_id="CAM-TEST-01",
        name="Restricted Zone East",
        zone_type="POLYGON",
        polygon_coords=[[0.5, 0.1], [0.95, 0.1], [0.95, 0.9], [0.5, 0.9]],
        restriction_level="RESTRICTED",
        dwell_threshold_seconds=5.0,
    )
    monitored_zone = Zone(
        id="Z-02",
        camera_id="CAM-TEST-01",
        name="Monitored Pathway",
        zone_type="POLYGON",
        polygon_coords=[[0.05, 0.1], [0.45, 0.1], [0.45, 0.9], [0.05, 0.9]],
        restriction_level="MONITORED",
        dwell_threshold_seconds=5.0,
    )
    db_session.add(cam)
    db_session.add(restricted_zone)
    db_session.add(monitored_zone)
    db_session.commit()

    frame_w, frame_h = 1280, 720

    # Helper function simulating CameraWorker's restricted-zone face event evaluation
    def evaluate_face_events(face_bbox, face_conf, tracks, zones):
        events = []
        fb = face_bbox
        fcx = (fb[0] + fb[2]) / 2.0
        fcy = (fb[1] + fb[3]) / 2.0
        face_ref = (fcx / max(frame_w, 1), fcy / max(frame_h, 1))

        for z in zones:
            restriction = getattr(z, "restriction_level", "RESTRICTED").upper()
            if restriction != "RESTRICTED":
                continue
            poly = getattr(z, "polygon_coords", [])
            if is_point_in_polygon(face_ref, poly):
                # Check track match
                matched_track = None
                for t in tracks:
                    if t.get("object_class") == "person":
                        tb = t.get("bbox", [0, 0, 0, 0])
                        if tb[0] <= fcx <= tb[2] and tb[1] <= fcy <= tb[3]:
                            matched_track = t.get("track_id")
                            break

                events.append({
                    "camera_id": getattr(z, "camera_id", "CAM-TEST-01"),
                    "type": "FACE_DETECTED",
                    "severity": "INFO",
                    "timestamp": "2026-09-14T02:00:00Z",
                    "object_type": "face",
                    "track_id": matched_track,
                    "confidence": face_conf,
                    "zone_id": getattr(z, "id", "Z-01"),
                    "evidence": {},
                    "metadata": {
                        "rule_name": "Face in Restricted Zone",
                        "zone_name": getattr(z, "name", "Z-01"),
                        "restriction_level": "RESTRICTED",
                        "face_bbox": fb,
                        "associated_track_id": matched_track,
                    }
                })
        return events

    # Case A: Face is OUTSIDE all zones (e.g. x=0.01, y=0.01)
    face_outside_bbox = [10, 10, 30, 30]
    tracks_outside = [{"track_id": 101, "object_class": "person", "bbox": [0, 0, 100, 200]}]
    evts_outside = evaluate_face_events(face_outside_bbox, 0.88, tracks_outside, [restricted_zone, monitored_zone])
    assert len(evts_outside) == 0, "No event should be emitted when face is outside restricted zones"

    # Case B: Face is inside MONITORED zone (non-restricted, x=0.25, y=0.5 -> norm ~ (0.25, 0.5))
    face_monitored_bbox = [310, 350, 330, 370]
    tracks_monitored = [{"track_id": 102, "object_class": "person", "bbox": [280, 300, 380, 600]}]
    evts_monitored = evaluate_face_events(face_monitored_bbox, 0.91, tracks_monitored, [restricted_zone, monitored_zone])
    assert len(evts_monitored) == 0, "No event should be emitted for face in a MONITORED (non-restricted) zone"

    # Case C: Face is inside RESTRICTED zone Z-01 (x=0.7, y=0.5 -> norm ~ (0.7, 0.5))
    # 0.7 * 1280 = 896, 0.5 * 720 = 360
    face_restricted_bbox = [880, 340, 912, 380]
    tracks_restricted = [{"track_id": 103, "object_class": "person", "bbox": [850, 300, 950, 600]}]
    evts_restricted = evaluate_face_events(face_restricted_bbox, 0.94, tracks_restricted, [restricted_zone, monitored_zone])
    assert len(evts_restricted) == 1, "Expected FACE_DETECTED event when face is inside RESTRICTED zone"

    face_event = evts_restricted[0]
    assert face_event["type"] == "FACE_DETECTED"
    assert face_event["severity"] == "INFO"
    assert face_event["zone_id"] == "Z-01"
    assert face_event["track_id"] == 103
    assert face_event["confidence"] == 0.94

    # Post to /api/v1/events and verify persistence
    resp = client.post("/api/v1/events", json=face_event)
    assert resp.status_code == 201
    created_id = resp.json()["id"]

    saved = db_session.query(Event).filter(Event.id == created_id).first()
    assert saved is not None
    assert saved.type == "FACE_DETECTED"
    assert saved.severity == "INFO"
    assert saved.zone_id == "Z-01"
    assert saved.track_id == 103
    assert saved.object_type == "face"
