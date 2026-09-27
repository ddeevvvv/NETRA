import pytest
import io
import base64
import zipfile
from datetime import datetime, timezone
from PIL import Image, ImageDraw

from app.models.event import Event
from app.models.camera import Camera
from app.models.zone import Zone
from app.models.watchlist import WatchlistEntry


def create_synthetic_image_b64():
    img = Image.new('RGB', (160, 120), color=(30, 41, 59))
    d = ImageDraw.Draw(img)
    d.rectangle([(10, 10), (150, 110)], outline=(220, 38, 38), width=2)
    d.text((20, 30), "TEST FRAME", fill=(255, 255, 255))
    bio = io.BytesIO()
    img.save(bio, format="JPEG")
    return "data:image/jpeg;base64," + base64.b64encode(bio.getvalue()).decode("utf-8")


def test_incident_evidence_package_pdf_with_real_image(client, db_session):
    cam = Camera(id="CAM-TEST-01", name="Perimeter North Gate", rtsp_url="rtsp://localhost:8554/cam1", status="ONLINE", location="Sector Alpha")
    zone = Zone(id="Z-01", camera_id="CAM-TEST-01", name="Restricted Alpha", zone_type="POLYGON", polygon_coords=[[0,0],[1,0],[1,1],[0,1]], restriction_level="RESTRICTED")
    db_session.add_all([cam, zone])
    db_session.commit()

    snap_b64 = create_synthetic_image_b64()
    ev = Event(
        id="EVT-EVD-01",
        camera_id="CAM-TEST-01",
        type="INTRUSION",
        severity="CRITICAL",
        timestamp=datetime.now(timezone.utc),
        object_type="person",
        track_id=42,
        confidence=0.96,
        zone_id="Z-01",
        acknowledged=False,
        requires_acknowledgment=True,
        evidence={"snapshot_uri": snap_b64},
        event_metadata={"rule_name": "Perimeter Virtual Fence Breach"}
    )
    db_session.add(ev)
    db_session.commit()

    resp = client.get("/api/v1/events/incident-evidence-package?camera_id=CAM-TEST-01&format=pdf")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert "attachment; filename=" in resp.headers["content-disposition"]
    assert resp.content.startswith(b"%PDF-")
    assert len(resp.content) > 3000


def test_incident_evidence_package_honest_degradation_no_image(client, db_session):
    cam = Camera(id="CAM-TEST-01", name="Perimeter North Gate", rtsp_url="rtsp://localhost:8554/cam1", status="ONLINE", location="Sector Alpha")
    zone = Zone(id="Z-01", camera_id="CAM-TEST-01", name="Restricted Alpha", zone_type="POLYGON", polygon_coords=[[0,0],[1,0],[1,1],[0,1]], restriction_level="RESTRICTED")
    db_session.add_all([cam, zone])
    db_session.commit()

    # Event with NO evidence snapshot
    ev = Event(
        id="EVT-EVD-NOIMG",
        camera_id="CAM-TEST-01",
        type="LOITERING",
        severity="HIGH",
        timestamp=datetime.now(timezone.utc),
        object_type="person",
        track_id=42,
        confidence=0.88,
        zone_id="Z-01",
        acknowledged=True,
        requires_acknowledgment=True,
        evidence={},
        event_metadata={"dwell_time_seconds": 22.0}
    )
    db_session.add(ev)
    db_session.commit()

    resp = client.get(f"/api/v1/events/{ev.id}/evidence-package?format=pdf")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content.startswith(b"%PDF-")
    assert len(resp.content) > 3000


def test_incident_evidence_package_zip_export(client, db_session):
    cam = Camera(id="CAM-TEST-01", name="Perimeter North Gate", rtsp_url="rtsp://localhost:8554/cam1", status="ONLINE", location="Sector Alpha")
    db_session.add(cam)
    ev = Event(
        id="EVT-EVD-ZIP",
        camera_id="CAM-TEST-01",
        type="INTRUSION",
        severity="CRITICAL",
        timestamp=datetime.now(timezone.utc),
        object_type="person",
        track_id=42,
        confidence=0.96,
        zone_id="Z-01",
        acknowledged=False,
        requires_acknowledgment=True,
        evidence={"snapshot_uri": create_synthetic_image_b64()},
        event_metadata={"rule_name": "Virtual Fence Breach"}
    )
    db_session.add(ev)
    db_session.commit()

    resp = client.get("/api/v1/events/incident-evidence-package?camera_id=CAM-TEST-01&format=zip")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"
    
    # Verify ZIP contents
    z_buf = io.BytesIO(resp.content)
    with zipfile.ZipFile(z_buf, 'r') as zf:
        namelist = zf.namelist()
        assert "metadata.json" in namelist
        assert "summary.txt" in namelist
        assert any(n.endswith(".pdf") for n in namelist)


def test_vehicle_evidence_package_pdf(client, db_session):
    cam = Camera(id="CAM-TEST-01", name="Perimeter North Gate", rtsp_url="rtsp://localhost:8554/cam1", status="ONLINE", location="Sector Alpha")
    db_session.add(cam)

    ev = Event(
        id="EVT-ANPR-01",
        camera_id="CAM-TEST-01",
        type="ANPR_MATCH",
        severity="HIGH",
        timestamp=datetime.now(timezone.utc),
        object_type="vehicle",
        track_id=12,
        confidence=0.95,
        zone_id="Z-01",
        acknowledged=True,
        requires_acknowledgment=True,
        evidence={"snapshot_uri": create_synthetic_image_b64()},
        event_metadata={
            "license_plate": "KA05NB4912",
            "list_type": "BLACKLIST",
            "notes": "Stolen White Scorpio",
            "raw_ocr": "KA05NB4912"
        }
    )
    db_session.add(ev)
    db_session.commit()

    resp = client.get("/api/v1/vehicles/KA05NB4912/evidence-package?format=pdf")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content.startswith(b"%PDF-")


def test_evidence_package_not_found(client, db_session):
    resp = client.get("/api/v1/events/incident-evidence-package?camera_id=NONEXISTENT_CAM")
    assert resp.status_code == 404
    assert "No events found" in resp.json()["detail"]
