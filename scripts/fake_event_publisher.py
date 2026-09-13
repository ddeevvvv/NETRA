import argparse
import random
import sys
import time
import requests
from datetime import datetime, timezone

SCENARIOS = [
    {
        "type": "INTRUSION",
        "severity": "CRITICAL",
        "object_type": "person",
        "camera_id": "CAM-01",
        "zone_id": "Z-01",
        "confidence_range": (0.88, 0.98),
        "evidence": {
            "snapshot_uri": "http://storage/snapshots/cam01_intrusion.jpg",
            "clip_uri": "http://storage/clips/cam01_intrusion.mp4"
        },
        "metadata": {
            "direction": "NORTHBOUND",
            "rule_name": "Virtual Fence Breach",
            "threshold": 0.85
        }
    },
    {
        "type": "ANPR_MATCH",
        "severity": "HIGH",
        "object_type": "vehicle",
        "camera_id": "CAM-02",
        "zone_id": "Z-02",
        "confidence_range": (0.91, 0.99),
        "evidence": {
            "snapshot_uri": "http://storage/snapshots/cam02_plate.jpg",
            "clip_uri": "http://storage/clips/cam02_plate.mp4"
        },
        "metadata": {
            "license_plate": "KA-05-NB-4912",
            "watchlist": "BOLO_VEHICLES",
            "speed_kmh": 64.5
        }
    },
    {
        "type": "LOITERING",
        "severity": "MEDIUM",
        "object_type": "person",
        "camera_id": "CAM-03",
        "zone_id": "Z-03",
        "confidence_range": (0.80, 0.92),
        "evidence": {
            "snapshot_uri": "http://storage/snapshots/cam03_loiter.jpg",
            "clip_uri": "http://storage/clips/cam03_loiter.mp4"
        },
        "metadata": {
            "dwell_time_seconds": 185,
            "threshold_seconds": 120
        }
    },
    {
        "type": "ROUTINE_CHECK",
        "severity": "INFO",
        "object_type": "person",
        "camera_id": "CAM-04",
        "zone_id": "Z-04",
        "confidence_range": (0.95, 0.99),
        "evidence": {
            "snapshot_uri": "http://storage/snapshots/cam04_patrol.jpg",
            "clip_uri": "http://storage/clips/cam04_patrol.mp4"
        },
        "metadata": {
            "status": "Patrol Officer Detected",
            "badge_id": "BORDER-GUARD-88"
        }
    }
]

def main():
    parser = argparse.ArgumentParser(description="IBVAP Fake Event Publisher")
    parser.add_argument("--url", default="http://localhost:8000", help="Base URL of IBVAP backend")
    parser.add_argument("--min-interval", type=float, default=3.0, help="Minimum interval in seconds")
    parser.add_argument("--max-interval", type=float, default=6.0, help="Maximum interval in seconds")
    parser.add_argument("--camera-id", help="Override camera_id")
    parser.add_argument("--zone-id", help="Override zone_id")
    args = parser.parse_args()

    endpoint = f"{args.url.rstrip('/')}/api/v1/events"
    print(f"[PUB] Starting IBVAP Fake Event Publisher posting to {endpoint}")
    print(f"[PUB] Event interval: {args.min_interval}s - {args.max_interval}s\n")
    sys.stdout.flush()

    track_id_counter = 10
    scenario_idx = 0

    try:
        while True:
            scenario = dict(SCENARIOS[scenario_idx % len(SCENARIOS)])
            scenario_idx += 1
            track_id_counter += 1

            cam_id = args.camera_id if args.camera_id else scenario["camera_id"]
            zone_id = args.zone_id if args.zone_id else scenario["zone_id"]
            conf_min, conf_max = scenario["confidence_range"]
            confidence = round(random.uniform(conf_min, conf_max), 2)

            payload = {
                "camera_id": cam_id,
                "type": scenario["type"],
                "severity": scenario["severity"],
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "object_type": scenario["object_type"],
                "track_id": track_id_counter,
                "confidence": confidence,
                "zone_id": zone_id,
                "evidence": scenario["evidence"],
                "metadata": scenario["metadata"]
            }

            try:
                res = requests.post(endpoint, json=payload, timeout=5)
                if res.status_code == 201:
                    created = res.json()
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] [PUB] POST 201 | Event ID: {created['id']} | Type: {created['type']} | Camera: {created['camera_id']} | Severity: {created['severity']}")
                else:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] [PUB] POST {res.status_code} | Response: {res.text}")
                sys.stdout.flush()
            except Exception as e:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] [PUB] Connection Error: {e}")
                sys.stdout.flush()

            delay = random.uniform(args.min_interval, args.max_interval)
            time.sleep(delay)
    except KeyboardInterrupt:
        print("\n[PUB] Publisher stopped by user.")
        sys.exit(0)

if __name__ == "__main__":
    main()
