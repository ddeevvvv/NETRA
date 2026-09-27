import pytest
from datetime import datetime, timedelta, timezone
from app.models.camera import Camera

def test_incident_summary_negative_case(client, db_session):
    # Insert two cameras into DB
    cam1 = Camera(
        id="CAM-TEST-01",
        name="Test Cam 1",
        rtsp_url="rtsp://localhost:8554/cam1",
        location="Test",
        status="active",
    )
    cam2 = Camera(
        id="CAM-TEST-02",
        name="Test Cam 2",
        rtsp_url="rtsp://localhost:8554/cam2",
        location="East",
        status="active",
    )
    db_session.add_all([cam1, cam2])
    db_session.commit()

    base_time = datetime.now(timezone.utc).replace(microsecond=0)

    # First event for CAM-TEST-01
    payload1 = {
        "camera_id": "CAM-TEST-01",
        "type": "INTRUSION",
        "severity": "INFO",
        "timestamp": base_time.isoformat(),
        "object_type": "person",
        "track_id": 1,
        "confidence": 0.9,
        "zone_id": "Z-01",
        "evidence": {},
        "metadata": {},
    }
    resp1 = client.post("/api/v1/events", json=payload1)
    assert resp1.status_code == 201

    # Event for CAM-TEST-02 at the same moment (different camera)
    payload2 = payload1.copy()
    payload2.update({"camera_id": "CAM-TEST-02", "track_id": 2})
    resp2 = client.post("/api/v1/events", json=payload2)
    assert resp2.status_code == 201

    # Second event for CAM-TEST-01 after 10 minutes (outside default 5‑min window)
    payload3 = payload1.copy()
    payload3.update({"timestamp": (base_time + timedelta(minutes=10)).isoformat(), "track_id": 3})
    resp3 = client.post("/api/v1/events", json=payload3)
    assert resp3.status_code == 201

    # Retrieve summaries with a 5‑minute clustering window
    resp = client.get("/api/v1/events/summaries?window_minutes=5")
    assert resp.status_code == 200
    data = resp.json()
    # Expect three distinct clusters: two for CAM-TEST-01 (separated by window) and one for CAM-TEST-02
    assert data["total_clusters"] == 3
    cam1_clusters = [s for s in data["summaries"] if s["camera_id"] == "CAM-TEST-01"]
    cam2_clusters = [s for s in data["summaries"] if s["camera_id"] == "CAM-TEST-02"]
    assert len(cam1_clusters) == 2
    assert len(cam2_clusters) == 1
