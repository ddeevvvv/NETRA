import sys
import requests

def seed_zone(base_url="http://localhost:8000"):
    endpoint = f"{base_url.rstrip('/')}/api/v1/zones"
    payload = {
        "id": "Z-01",
        "camera_id": "CAM-TEST-01",
        "name": "Restricted Sector Alpha",
        "zone_type": "POLYGON",
        "polygon_coords": [
            [0.45, 0.10],
            [0.95, 0.10],
            [0.95, 0.90],
            [0.45, 0.90]
        ],
        "restriction_level": "RESTRICTED",
        "dwell_threshold_seconds": 5.0,
        "rules": {
            "virtual_fence": True,
            "min_confidence": 0.5
        }
    }

    try:
        resp = requests.post(endpoint, json=payload, timeout=5)
        if resp.status_code == 201:
            print(f"[SUCCESS] Seeded zone 'Z-01' for camera 'CAM-TEST-01': {resp.json()}")
        elif resp.status_code == 400 and "already exists" in resp.text:
            print(f"[INFO] Zone 'Z-01' already exists in DB.")
        else:
            print(f"[WARNING] Server responded with {resp.status_code}: {resp.text}")
    except Exception as e:
        print(f"[ERROR] Could not connect to backend at {endpoint}: {e}")

if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
    seed_zone(url)
