import pytest
from app.models.watchlist import WatchlistEntry


def test_watchlist_crud_lifecycle(client, db_session):
    # 1. Create a Blacklist Plate entry
    payload = {
        "id": "WL-TEST-01",
        "type": "PLATE",
        "reference_value": "KA05NB4912",
        "list_type": "BLACKLIST",
        "added_by": "Officer-Alpha",
        "notes": "Wanted in BOLO #1042"
    }
    resp = client.post("/api/v1/watchlist", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["id"] == "WL-TEST-01"
    assert data["reference_value"] == "KA05NB4912"
    assert data["list_type"] == "BLACKLIST"

    # 2. Duplicate rejection
    resp_dup = client.post("/api/v1/watchlist", json=payload)
    assert resp_dup.status_code == 400

    # 3. List with filters
    resp_list = client.get("/api/v1/watchlist?type=PLATE&list_type=BLACKLIST")
    assert resp_list.status_code == 200
    assert len(resp_list.json()) == 1

    resp_empty = client.get("/api/v1/watchlist?list_type=WHITELIST")
    assert resp_empty.status_code == 200
    assert len(resp_empty.json()) == 0

    # 4. Get by ID
    resp_get = client.get("/api/v1/watchlist/WL-TEST-01")
    assert resp_get.status_code == 200
    assert resp_get.json()["notes"] == "Wanted in BOLO #1042"

    # 5. Delete entry
    resp_del = client.delete("/api/v1/watchlist/WL-TEST-01")
    assert resp_del.status_code == 204

    resp_after = client.get("/api/v1/watchlist/WL-TEST-01")
    assert resp_after.status_code == 404


def test_watchlist_validation_errors(client):
    # Invalid type
    bad_type = {
        "type": "INVALID_TYPE",
        "reference_value": "KA05NB4912",
        "list_type": "BLACKLIST"
    }
    assert client.post("/api/v1/watchlist", json=bad_type).status_code == 422

    # Invalid list type
    bad_list = {
        "type": "PLATE",
        "reference_value": "KA05NB4912",
        "list_type": "REDLIST"
    }
    assert client.post("/api/v1/watchlist", json=bad_list).status_code == 422
