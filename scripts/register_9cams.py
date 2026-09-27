"""
register_9cams.py — Register cameras 3-9 with the IBVAP backend.

CAM-TEST-01 and CAM-TEST-02 (cam1/cam2 via mediamtx) already exist.
This script registers CAM-03 through CAM-09 using direct file paths
mounted into the backend container at /feeds/camX.mp4.

Run from the project root:
    python scripts/register_9cams.py [--base-url http://localhost:8000]

Idempotent: cameras that already exist are skipped (not overwritten).
"""
import argparse
import json
import sys
import urllib.error
import urllib.request

# Camera metadata — location names chosen for border-surveillance context.
CAMERAS = [
    {
        "id": "CAM-03",
        "name": "North Perimeter Gate",
        "rtsp_url": "/feeds/cam3.mp4",
        "location": "North Perimeter",
        "status": "active",
    },
    {
        "id": "CAM-04",
        "name": "Vehicle Staging Area",
        "rtsp_url": "/feeds/cam4.mp4",
        "location": "Vehicle Staging",
        "status": "active",
    },
    {
        "id": "CAM-05",
        "name": "South Entry Checkpoint",
        "rtsp_url": "/feeds/cam5.mp4",
        "location": "South Entry",
        "status": "active",
    },
    {
        "id": "CAM-06",
        "name": "Command Post Exterior",
        "rtsp_url": "/feeds/cam6.mp4",
        "location": "Command Post",
        "status": "active",
    },
    {
        "id": "CAM-07",
        "name": "Main Road Overwatch",
        "rtsp_url": "/feeds/cam7.mp4",
        "location": "Main Road",
        "status": "active",
    },
    {
        "id": "CAM-08",
        "name": "Perimeter West Wide-Angle",
        "rtsp_url": "/feeds/cam8.mp4",
        "location": "West Perimeter",
        "status": "active",
    },
    {
        "id": "CAM-09",
        "name": "Aerial Observation (4K)",
        "rtsp_url": "/feeds/cam9.mp4",
        "location": "Aerial OP",
        "status": "active",
    },
]


def post_json(base_url: str, path: str, data: dict) -> tuple[int, str]:
    url = f"{base_url.rstrip('/')}{path}"
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8")
    except Exception as e:
        return 0, str(e)


def main():
    parser = argparse.ArgumentParser(description="Register cameras 3-9 with IBVAP backend.")
    parser.add_argument("--base-url", default="http://localhost:8000", help="Backend base URL")
    args = parser.parse_args()
    base_url = args.base_url

    print(f"Registering cameras at {base_url}")
    print("=" * 60)

    ok = 0
    skip = 0
    fail = 0
    for cam in CAMERAS:
        status_code, body = post_json(base_url, "/api/v1/cameras", cam)
        if status_code == 201:
            print(f"[REGISTERED] {cam['id']} — {cam['name']}")
            ok += 1
        elif status_code == 400 and "already exists" in body:
            print(f"[SKIP]       {cam['id']} — already registered")
            skip += 1
        else:
            print(f"[FAIL]       {cam['id']} — HTTP {status_code}: {body[:120]}")
            fail += 1

    print("=" * 60)
    print(f"Done: {ok} registered, {skip} skipped, {fail} failed")
    if fail:
        sys.exit(1)


if __name__ == "__main__":
    main()
