import pytest
from fastapi.testclient import TestClient
from app.main import app

def test_websocket_alerts_broadcast(client):
    with client.websocket_connect("/ws/alerts") as websocket:
        sample_payload = {
            "camera_id": "CAM-01",
            "type": "INTRUSION",
            "severity": "CRITICAL",
            "timestamp": "2026-09-12T14:00:00Z",
            "object_type": "person",
            "track_id": 42,
            "confidence": 0.96,
            "zone_id": "Z-01",
            "evidence": {
                "snapshot_uri": "http://storage/snapshots/test.jpg"
            },
            "metadata": {
                "direction": "SOUTHBOUND"
            }
        }

        # 1. Post event to API
        response = client.post("/api/v1/events", json=sample_payload)
        assert response.status_code == 201
        created_event = response.json()

        # 2. Receive message from WebSocket stream
        ws_msg = websocket.receive_json()
        assert ws_msg["id"] == created_event["id"]
        assert ws_msg["camera_id"] == "CAM-01"
        assert ws_msg["type"] == "INTRUSION"
        assert ws_msg["severity"] == "CRITICAL"
        assert ws_msg["metadata"]["direction"] == "SOUTHBOUND"
