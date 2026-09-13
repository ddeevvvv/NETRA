import pytest
from app.models.camera import Camera
from app.models.watchlist import WatchlistEntry
from app.models.event import Event


def test_anpr_watchlist_pipeline_integration(client, db_session):
    # 1. Setup Camera and Watchlist
    cam = Camera(id="CAM-TEST-01", name="Perimeter North", rtsp_url="rtsp://localhost:8554/cam1", status="ONLINE")
    wl_black = WatchlistEntry(
        id="WL-01",
        type="PLATE",
        reference_value="KA05NB4912",
        list_type="BLACKLIST",
        added_by="Officer-Singh",
        notes="Stolen White Scorpio"
    )
    wl_white = WatchlistEntry(
        id="WL-02",
        type="PLATE",
        reference_value="HR26DQ5551",
        list_type="WHITELIST",
        added_by="Admin",
        notes="Border Patrol Unit 7"
    )
    db_session.add_all([cam, wl_black, wl_white])
    db_session.commit()

    # 2. Simulate ANPR_MATCH on Blacklist plate
    black_match_payload = {
        "camera_id": "CAM-TEST-01",
        "type": "ANPR_MATCH",
        "severity": "HIGH",
        "timestamp": "2026-09-13T12:00:00Z",
        "object_type": "car",
        "track_id": 9,
        "confidence": 0.93,
        "zone_id": None,
        "evidence": {},
        "metadata": {
            "license_plate": "KA05NB4912",
            "list_type": "BLACKLIST",
            "notes": "Stolen White Scorpio",
            "ocr_confidence": 0.93,
            "rule_name": "Watchlist BLACKLIST Plate Detected"
        }
    }
    resp1 = client.post("/api/v1/events", json=black_match_payload)
    assert resp1.status_code == 201
    evt1_id = resp1.json()["id"]

    saved1 = db_session.query(Event).filter(Event.id == evt1_id).first()
    assert saved1 is not None
    assert saved1.type == "ANPR_MATCH"
    assert saved1.severity == "HIGH"
    assert saved1.event_metadata["license_plate"] == "KA05NB4912"
    assert saved1.event_metadata["list_type"] == "BLACKLIST"

    # 3. Simulate ANPR_MATCH on Whitelist plate
    white_match_payload = {
        "camera_id": "CAM-TEST-01",
        "type": "ANPR_MATCH",
        "severity": "INFO",
        "timestamp": "2026-09-13T12:01:00Z",
        "object_type": "car",
        "track_id": 10,
        "confidence": 0.95,
        "zone_id": None,
        "evidence": {},
        "metadata": {
            "license_plate": "HR26DQ5551",
            "list_type": "WHITELIST",
            "notes": "Border Patrol Unit 7",
            "ocr_confidence": 0.95,
            "rule_name": "Watchlist WHITELIST Plate Detected"
        }
    }
    resp2 = client.post("/api/v1/events", json=white_match_payload)
    assert resp2.status_code == 201
    evt2_id = resp2.json()["id"]

    saved2 = db_session.query(Event).filter(Event.id == evt2_id).first()
    assert saved2.type == "ANPR_MATCH"
    assert saved2.severity == "INFO"
    assert saved2.event_metadata["list_type"] == "WHITELIST"

    # 4. Simulate regular unlisted plate ANPR_READ
    read_payload = {
        "camera_id": "CAM-TEST-01",
        "type": "ANPR_READ",
        "severity": "INFO",
        "timestamp": "2026-09-13T12:02:00Z",
        "object_type": "truck",
        "track_id": 11,
        "confidence": 0.88,
        "zone_id": None,
        "evidence": {},
        "metadata": {
            "license_plate": "MH12DE9999",
            "ocr_confidence": 0.88,
            "rule_name": "Vehicle Plate Read"
        }
    }
    resp3 = client.post("/api/v1/events", json=read_payload)
    assert resp3.status_code == 201
    evt3_id = resp3.json()["id"]

    saved3 = db_session.query(Event).filter(Event.id == evt3_id).first()
    assert saved3.type == "ANPR_READ"
    assert saved3.severity == "INFO"
