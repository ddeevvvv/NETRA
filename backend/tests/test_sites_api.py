import pytest
from app.models.camera import Camera
from app.models.event import Event

def test_get_sites_status(client, db_session):
    cam1 = Camera(id="CAM-TEST-01", name="Test Cam", rtsp_url="rtsp://localhost:8554/cam1", location="Test", status="active")
    cam2 = Camera(id="CAM-TEST-02", name="Perimeter East Camera", rtsp_url="rtsp://localhost:8554/cam2", location="East Perimeter Gate", status="active")
    db_session.add_all([cam1, cam2])
    db_session.commit()

    resp = client.get("/api/v1/sites/status")
    assert resp.status_code == 200
    sites = resp.json()
    assert len(sites) >= 2

    site_map = {s["id"]: s for s in sites}
    assert "BOP-01" in site_map
    assert "BOP-02" in site_map

    bop1 = site_map["BOP-01"]
    assert bop1["total_cameras"] >= 1
    assert any(c["id"] == "CAM-TEST-01" for c in bop1["cameras"])

    bop2 = site_map["BOP-02"]
    assert bop2["total_cameras"] >= 1
    assert any(c["id"] == "CAM-TEST-02" for c in bop2["cameras"])
