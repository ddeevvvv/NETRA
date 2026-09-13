import pytest
from app.models.camera import Camera
from app.models.zone import Zone


def test_zone_crud_lifecycle(client, db_session):
    # 1. Create a parent camera first
    cam = Camera(id="CAM-01", name="Perimeter North", rtsp_url="rtsp://localhost:8554/cam1", status="ACTIVE")
    db_session.add(cam)
    db_session.commit()

    # 2. Create Zone via API
    zone_payload = {
        "id": "Z-01",
        "camera_id": "CAM-01",
        "name": "North Virtual Fence",
        "zone_type": "POLYGON",
        "polygon_coords": [
            [0.5, 0.2],
            [0.9, 0.2],
            [0.9, 0.8],
            [0.5, 0.8]
        ],
        "restriction_level": "RESTRICTED",
        "dwell_threshold_seconds": 6.0,
        "rules": {"min_confidence": 0.6}
    }
    resp = client.post("/api/v1/zones", json=zone_payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["id"] == "Z-01"
    assert data["camera_id"] == "CAM-01"
    assert data["restriction_level"] == "RESTRICTED"
    assert len(data["polygon_coords"]) == 4

    # 3. Duplicate ID rejection
    resp_dup = client.post("/api/v1/zones", json=zone_payload)
    assert resp_dup.status_code == 400

    # 4. List zones with filter
    resp_list = client.get("/api/v1/zones?camera_id=CAM-01")
    assert resp_list.status_code == 200
    assert len(resp_list.json()) == 1

    resp_empty = client.get("/api/v1/zones?camera_id=CAM-NONEXISTENT")
    assert resp_empty.status_code == 200
    assert len(resp_empty.json()) == 0

    # 5. Get Zone by ID
    resp_get = client.get("/api/v1/zones/Z-01")
    assert resp_get.status_code == 200
    assert resp_get.json()["name"] == "North Virtual Fence"

    # 6. Update Zone
    resp_update = client.put("/api/v1/zones/Z-01", json={"dwell_threshold_seconds": 12.0, "name": "Updated Fence"})
    assert resp_update.status_code == 200
    assert resp_update.json()["dwell_threshold_seconds"] == 12.0
    assert resp_update.json()["name"] == "Updated Fence"

    # 7. Delete Zone
    resp_del = client.delete("/api/v1/zones/Z-01")
    assert resp_del.status_code == 204

    resp_after = client.get("/api/v1/zones/Z-01")
    assert resp_after.status_code == 404


def test_zone_validation_failures(client):
    # Invalid coordinates (< 3 points)
    bad_poly = {
        "id": "Z-BAD-1",
        "name": "Bad Poly",
        "polygon_coords": [[0.1, 0.1], [0.2, 0.2]],
    }
    assert client.post("/api/v1/zones", json=bad_poly).status_code == 422

    # Invalid coordinates (out of 0.0 - 1.0 range)
    out_of_bounds = {
        "id": "Z-BAD-2",
        "name": "Out of bounds",
        "polygon_coords": [[0.1, 0.1], [1.5, 0.2], [0.5, 0.9]],
    }
    assert client.post("/api/v1/zones", json=out_of_bounds).status_code == 422

    # Invalid restriction level
    bad_level = {
        "id": "Z-BAD-3",
        "name": "Bad Level",
        "polygon_coords": [[0.1, 0.1], [0.5, 0.1], [0.5, 0.9]],
        "restriction_level": "INVALID_LEVEL"
    }
    assert client.post("/api/v1/zones", json=bad_level).status_code == 422
