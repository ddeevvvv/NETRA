import pytest

def test_health_check(client):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "service" in data

def test_post_and_get_event(client):
    # Sample payload matching exact event schema in AGENTS.md
    sample_payload = {
        "camera_id": "CAM-07",
        "type": "INTRUSION",
        "severity": "CRITICAL",
        "timestamp": "2026-09-11T12:52:03Z",
        "object_type": "person",
        "track_id": 17,
        "confidence": 0.94,
        "zone_id": "Z-01",
        "evidence": {
            "snapshot_uri": "http://storage/snapshots/snap_17.jpg",
            "clip_uri": "http://storage/clips/clip_17.mp4"
        },
        "metadata": {
            "direction": "NORTHBOUND"
        }
    }

    # 1. POST /api/v1/events
    post_resp = client.post("/api/v1/events", json=sample_payload)
    assert post_resp.status_code == 201, f"POST failed: {post_resp.text}"
    created_event = post_resp.json()

    assert "id" in created_event
    assert created_event["camera_id"] == "CAM-07"
    assert created_event["type"] == "INTRUSION"
    assert created_event["severity"] == "CRITICAL"
    assert created_event["object_type"] == "person"
    assert created_event["track_id"] == 17
    assert created_event["confidence"] == 0.94
    assert created_event["zone_id"] == "Z-01"
    assert created_event["evidence"]["snapshot_uri"] == "http://storage/snapshots/snap_17.jpg"
    assert created_event["metadata"]["direction"] == "NORTHBOUND"
    assert created_event["acknowledged"] is False

    event_id = created_event["id"]

    # 2. GET /api/v1/events/{id}
    get_single = client.get(f"/api/v1/events/{event_id}")
    assert get_single.status_code == 200
    assert get_single.json()["id"] == event_id

    # 3. GET /api/v1/events with filters
    list_resp = client.get("/api/v1/events?camera_id=CAM-07&type=INTRUSION&severity=CRITICAL")
    assert list_resp.status_code == 200
    events_list = list_resp.json()
    assert len(events_list) == 1
    assert events_list[0]["id"] == event_id

    # 4. POST /api/v1/events/{id}/acknowledge
    ack_resp = client.post(f"/api/v1/events/{event_id}/acknowledge", json={"acknowledged_by": "Operator-Alpha"})
    assert ack_resp.status_code == 200
    ack_data = ack_resp.json()
    assert ack_data["acknowledged"] is True
    assert ack_data["acknowledged_by"] == "Operator-Alpha"
    assert ack_data["acknowledged_at"] is not None
