import pytest
from app.models.camera import Camera
from app.models.zone import Zone
from app.models.event import Event
from app.analytics.zone_engine import ZoneEngine


def test_zone_engine_to_events_pipeline_integration(client, db_session):
    # 1. Setup Camera and Zone
    cam = Camera(id="CAM-TEST-01", name="Perimeter 01", rtsp_url="rtsp://localhost:8554/cam1", status="ONLINE")
    zone = Zone(
        id="Z-01",
        camera_id="CAM-TEST-01",
        name="Restricted Zone East",
        zone_type="POLYGON",
        polygon_coords=[[0.5, 0.1], [0.95, 0.1], [0.95, 0.9], [0.5, 0.9]],
        restriction_level="RESTRICTED",
        dwell_threshold_seconds=5.0,
        rules={"virtual_fence": True}
    )
    db_session.add(cam)
    db_session.add(zone)
    db_session.commit()

    engine = ZoneEngine(temporal_confirmation_frames=2)
    frame_shape = (720, 1280, 3)  # 720p frame

    # 2. Simulate Track #42 (person) starting OUTSIDE zone (norm_x ~ 0.2)
    track_outside = [{"track_id": 42, "object_class": "person", "bbox": [200, 300, 300, 500], "confidence": 0.94}]
    evts_out, _ = engine.process_frame("CAM-TEST-01", track_outside, frame_shape, [zone], current_time=100.0)
    assert len(evts_out) == 0

    # 3. Simulate Track #42 stepping INSIDE zone Z-01 (norm_x = 0.7, norm_y = 0.7)
    # bottom_center = (900, 504) -> norm_x = 900/1280 = 0.703, norm_y = 504/720 = 0.7
    track_inside = [{"track_id": 42, "object_class": "person", "bbox": [850, 300, 950, 504], "confidence": 0.94}]

    # Frame 1 inside: temporal confirmation pending
    evts_in1, _ = engine.process_frame("CAM-TEST-01", track_inside, frame_shape, [zone], current_time=100.2)
    assert len(evts_in1) == 0

    # Frame 2 inside: confirmed! -> produces INTRUSION event
    evts_in2, active_map = engine.process_frame("CAM-TEST-01", track_inside, frame_shape, [zone], current_time=100.4)
    assert len(evts_in2) == 1
    intrusion_evt = evts_in2[0]

    # Post event to API
    resp = client.post("/api/v1/events", json=intrusion_evt)
    assert resp.status_code == 201
    db_evt_id = resp.json()["id"]

    # Verify event stored in DB
    saved_evt = db_session.query(Event).filter(Event.id == db_evt_id).first()
    assert saved_evt is not None
    assert saved_evt.type == "INTRUSION"
    assert saved_evt.severity == "HIGH"
    assert saved_evt.camera_id == "CAM-TEST-01"
    assert saved_evt.zone_id == "Z-01"
    assert saved_evt.track_id == 42
    assert saved_evt.object_type == "person"

    # 4. Simulate Track #42 dwelling for 6 seconds inside Z-01
    evts_dwell, _ = engine.process_frame("CAM-TEST-01", track_inside, frame_shape, [zone], current_time=106.5)
    assert len(evts_dwell) == 1
    loiter_evt = evts_dwell[0]
    assert loiter_evt["type"] == "LOITERING"
    assert loiter_evt["severity"] == "WARNING"

    resp_loiter = client.post("/api/v1/events", json=loiter_evt)
    assert resp_loiter.status_code == 201

    # 5. Simulate Track #42 exiting the zone
    evts_exit, active_map_exit = engine.process_frame("CAM-TEST-01", track_outside, frame_shape, [zone], current_time=108.0)
    assert len(evts_exit) == 1
    exit_evt = evts_exit[0]
    assert exit_evt["type"] == "ZONE_EXIT"
    assert exit_evt["severity"] == "INFO"

    resp_exit = client.post("/api/v1/events", json=exit_evt)
    assert resp_exit.status_code == 201

    # Query events list from API
    resp_list = client.get("/api/v1/events?camera_id=CAM-TEST-01")
    assert resp_list.status_code == 200
    events_list = resp_list.json()
    assert len(events_list) == 3
    event_types = [e["type"] for e in events_list]
    assert "INTRUSION" in event_types
    assert "LOITERING" in event_types
    assert "ZONE_EXIT" in event_types
