import sys
import json
import urllib.request
import urllib.error

def post_json(url, data):
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8")
    except Exception as e:
        return 0, str(e)

def seed_camera_and_zone(base_url="http://localhost:8000"):
    base = base_url.rstrip('/')
    
    # 1. Register CAM-02
    cam_url = f"{base}/api/v1/cameras"
    cam_payload = {
        "id": "CAM-02",
        "name": "Perimeter Gate East",
        "rtsp_url": "rtsp://mediamtx:8554/cam2",
        "location": "East Perimeter",
        "status": "active"
    }
    status, body = post_json(cam_url, cam_payload)
    if status == 201:
        print(f"[SUCCESS] Registered camera CAM-02: {body}")
    elif status == 400 and "already exists" in body:
        print(f"[INFO] Camera CAM-02 already registered.")
    else:
        print(f"[WARNING] Camera registration returned {status}: {body}")

    # 2. Register Zone for CAM-02
    zone_url = f"{base}/api/v1/zones"
    zone_payload = {
        "id": "Z-CAM2-01",
        "camera_id": "CAM-02",
        "name": "Gate 2 Restricted Zone",
        "zone_type": "POLYGON",
        "polygon_coords": [
            [0.10, 0.10],
            [0.90, 0.10],
            [0.90, 0.90],
            [0.10, 0.90]
        ],
        "restriction_level": "RESTRICTED",
        "dwell_threshold_seconds": 3.0,
        "rules": {
            "virtual_fence": True,
            "min_confidence": 0.4
        }
    }
    status, body = post_json(zone_url, zone_payload)
    if status == 201:
        print(f"[SUCCESS] Seeded zone Z-CAM2-01 for CAM-02: {body}")
    elif status == 400 and "already exists" in body:
        print(f"[INFO] Zone Z-CAM2-01 already exists.")
    else:
        print(f"[WARNING] Zone creation returned {status}: {body}")

if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
    seed_camera_and_zone(url)
