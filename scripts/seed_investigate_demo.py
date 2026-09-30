#!/usr/bin/env python3
"""
Seed realistic demo data for NETRA:
- Zones for registered cameras
- Watchlist entries
- Vehicle sightings across multiple cameras for KA05NB4912, DL01AB1234, HR26DQ5551
- Face detection events with bounding boxes, confidence, and thumbnails
- Event log spread across cameras and severities for rich incident clusters
"""
import sys
import time
import requests
from datetime import datetime, timezone, timedelta

BASE_URL = "http://localhost:8000/api/v1"

ZONES = [
    {
        "id": "Z-03",
        "camera_id": "CAM-03",
        "name": "North Gate Perimeter Fence",
        "zone_type": "POLYGON",
        "polygon_coords": [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]],
        "restriction_level": "RESTRICTED",
        "dwell_threshold_seconds": 5.0,
    },
    {
        "id": "Z-04",
        "camera_id": "CAM-04",
        "name": "Vehicle Staging Area Zone",
        "zone_type": "POLYGON",
        "polygon_coords": [[0.15, 0.15], [0.85, 0.15], [0.85, 0.85], [0.15, 0.85]],
        "restriction_level": "MONITORED",
        "dwell_threshold_seconds": 10.0,
    },
    {
        "id": "Z-05",
        "camera_id": "CAM-05",
        "name": "South Entry Barrier Sector",
        "zone_type": "POLYGON",
        "polygon_coords": [[0.2, 0.2], [0.8, 0.2], [0.8, 0.8], [0.2, 0.8]],
        "restriction_level": "RESTRICTED",
        "dwell_threshold_seconds": 5.0,
    },
    {
        "id": "Z-06",
        "camera_id": "CAM-06",
        "name": "Command Post Outer Perimeter",
        "zone_type": "POLYGON",
        "polygon_coords": [[0.1, 0.2], [0.9, 0.2], [0.9, 0.8], [0.1, 0.8]],
        "restriction_level": "RESTRICTED",
        "dwell_threshold_seconds": 5.0,
    },
    {
        "id": "Z-07",
        "camera_id": "CAM-07",
        "name": "Main Road Overwatch Sector",
        "zone_type": "POLYGON",
        "polygon_coords": [[0.05, 0.1], [0.95, 0.1], [0.95, 0.9], [0.05, 0.9]],
        "restriction_level": "MONITORED",
        "dwell_threshold_seconds": 8.0,
    },
    {
        "id": "Z-08",
        "camera_id": "CAM-08",
        "name": "West Highway Checkpoint Sector",
        "zone_type": "POLYGON",
        "polygon_coords": [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]],
        "restriction_level": "MONITORED",
        "dwell_threshold_seconds": 8.0,
    },
]

WATCHLIST_ENTRIES = [
    {
        "type": "PLATE",
        "reference_value": "KA05NB4912",
        "list_type": "BLACKLIST",
        "added_by": "Officer-Singh",
        "notes": "Stolen White Scorpio — BOLO #1042"
    },
    {
        "type": "PLATE",
        "reference_value": "DL01AB1234",
        "list_type": "BLACKLIST",
        "added_by": "HQ-Intel",
        "notes": "Suspect Vehicle — Border Sector 3 Alert"
    },
    {
        "type": "PLATE",
        "reference_value": "MH12DE5678",
        "list_type": "BLACKLIST",
        "added_by": "Customs-Narcotics",
        "notes": "Narcotics Smuggling Watchlist — Pune Zone"
    },
    {
        "type": "PLATE",
        "reference_value": "HR26DQ5551",
        "list_type": "WHITELIST",
        "added_by": "Admin",
        "notes": "Authorized Border Patrol Escort Unit"
    }
]

def seed_zones():
    print("[1/5] Seeding Camera Zones...")
    for z in ZONES:
        try:
            r = requests.post(f"{BASE_URL}/zones", json=z, timeout=5)
            if r.status_code == 201:
                print(f"  + Added zone {z['id']} for {z['camera_id']}")
            elif r.status_code == 400 and "already exists" in r.text:
                print(f"  . Zone {z['id']} already exists")
            else:
                print(f"  ! Zone response {r.status_code}: {r.text}")
        except Exception as e:
            print(f"  ! Zone post error: {e}")

def seed_watchlist():
    print("\n[2/5] Seeding Watchlist...")
    for entry in WATCHLIST_ENTRIES:
        try:
            r = requests.post(f"{BASE_URL}/watchlist", json=entry, timeout=5)
            if r.status_code == 201:
                print(f"  + Added {entry['reference_value']} ({entry['list_type']})")
            elif r.status_code == 400 and "already exists" in r.text:
                print(f"  . {entry['reference_value']} already in watchlist")
            else:
                print(f"  ! Error adding {entry['reference_value']}: {r.status_code}")
        except Exception as e:
            print(f"  ! Failed to post watchlist: {e}")

def seed_vehicle_sightings():
    print("\n[3/5] Seeding Vehicle Sightings (KA05NB4912 multi-camera timeline)...")
    now = datetime.now(timezone.utc)
    
    sightings_data = [
        # KA05NB4912 - White Scorpio sighted moving through sector
        {
            "camera_id": "CAM-05",
            "type": "ANPR_MATCH",
            "severity": "CRITICAL",
            "timestamp": (now - timedelta(minutes=18)).isoformat(),
            "object_type": "vehicle",
            "track_id": 401,
            "confidence": 0.96,
            "zone_id": "Z-05",
            "evidence": {
                "snapshot_uri": "/api/v1/cameras/CAM-05/debug/anpr-crops",
                "clip_uri": ""
            },
            "metadata": {
                "license_plate": "KA05NB4912",
                "plate_text": "KA05NB4912",
                "raw_ocr": "KA 05 NB 4912",
                "speed_kmh": 54.2,
                "direction": "SOUTHBOUND",
                "watchlist_match": True,
                "list_type": "BLACKLIST",
                "notes": "Stolen White Scorpio — BOLO #1042",
                "rule_name": "Watchlist Plate Match",
            }
        },
        {
            "camera_id": "CAM-07",
            "type": "ANPR_MATCH",
            "severity": "CRITICAL",
            "timestamp": (now - timedelta(minutes=11)).isoformat(),
            "object_type": "vehicle",
            "track_id": 405,
            "confidence": 0.98,
            "zone_id": "Z-07",
            "evidence": {
                "snapshot_uri": "/api/v1/cameras/CAM-07/debug/anpr-crops",
                "clip_uri": ""
            },
            "metadata": {
                "license_plate": "KA05NB4912",
                "plate_text": "KA05NB4912",
                "raw_ocr": "KA-05-NB-4912",
                "speed_kmh": 48.0,
                "direction": "SOUTHBOUND",
                "watchlist_match": True,
                "list_type": "BLACKLIST",
                "notes": "Stolen White Scorpio — BOLO #1042",
                "rule_name": "Watchlist Plate Match",
            }
        },
        {
            "camera_id": "CAM-08",
            "type": "ANPR_MATCH",
            "severity": "CRITICAL",
            "timestamp": (now - timedelta(minutes=4)).isoformat(),
            "object_type": "vehicle",
            "track_id": 412,
            "confidence": 0.95,
            "zone_id": "Z-08",
            "evidence": {
                "snapshot_uri": "/api/v1/cameras/CAM-08/debug/anpr-crops",
                "clip_uri": ""
            },
            "metadata": {
                "license_plate": "KA05NB4912",
                "plate_text": "KA05NB4912",
                "raw_ocr": "KA05NB4912",
                "speed_kmh": 61.8,
                "direction": "EASTBOUND",
                "watchlist_match": True,
                "list_type": "BLACKLIST",
                "notes": "Stolen White Scorpio — BOLO #1042",
                "rule_name": "Watchlist Plate Match",
            }
        },
        # DL01AB1234 - Suspect vehicle on CAM-04
        {
            "camera_id": "CAM-04",
            "type": "ANPR_MATCH",
            "severity": "HIGH",
            "timestamp": (now - timedelta(minutes=25)).isoformat(),
            "object_type": "vehicle",
            "track_id": 388,
            "confidence": 0.93,
            "zone_id": "Z-04",
            "evidence": {},
            "metadata": {
                "license_plate": "DL01AB1234",
                "plate_text": "DL01AB1234",
                "raw_ocr": "DL 01 AB 1234",
                "speed_kmh": 42.5,
                "direction": "NORTHBOUND",
                "watchlist_match": True,
                "list_type": "BLACKLIST",
                "notes": "Suspect Vehicle — Border Sector 3 Alert",
                "rule_name": "Watchlist Plate Match",
            }
        },
        # HR26DQ5551 - Patrol vehicle on CAM-03
        {
            "camera_id": "CAM-03",
            "type": "ANPR_READ",
            "severity": "INFO",
            "timestamp": (now - timedelta(minutes=30)).isoformat(),
            "object_type": "vehicle",
            "track_id": 370,
            "confidence": 0.97,
            "zone_id": "Z-03",
            "evidence": {},
            "metadata": {
                "license_plate": "HR26DQ5551",
                "plate_text": "HR26DQ5551",
                "raw_ocr": "HR 26 DQ 5551",
                "speed_kmh": 35.0,
                "direction": "WESTBOUND",
                "watchlist_match": False,
                "list_type": "WHITELIST",
                "notes": "Authorized Border Patrol Escort Unit",
            }
        }
    ]

    for ev in sightings_data:
        try:
            r = requests.post(f"{BASE_URL}/events", json=ev, timeout=5)
            if r.status_code == 201:
                print(f"  + Added sighting {ev['metadata']['license_plate']} on {ev['camera_id']}")
            else:
                print(f"  ! Sighting post returned {r.status_code}: {r.text}")
        except Exception as e:
            print(f"  ! Sighting post error: {e}")

def seed_face_detections():
    print("\n[4/5] Seeding Face Detections...")
    now = datetime.now(timezone.utc)
    
    faces_data = [
        {
            "camera_id": "CAM-03",
            "type": "FACE_DETECTED",
            "severity": "CRITICAL",
            "timestamp": (now - timedelta(minutes=14)).isoformat(),
            "object_type": "person",
            "track_id": 101,
            "confidence": 0.94,
            "zone_id": "Z-03",
            "evidence": {
                "snapshot_uri": ""
            },
            "metadata": {
                "face_bbox": [124, 65, 238, 210],
                "restricted_zone_active": True,
                "restriction_level": "RESTRICTED",
                "zone_name": "North Gate Perimeter Fence",
                "detector": "RetinaFace-ResNet50",
            }
        },
        {
            "camera_id": "CAM-04",
            "type": "FACE_DETECTED",
            "severity": "HIGH",
            "timestamp": (now - timedelta(minutes=11)).isoformat(),
            "object_type": "person",
            "track_id": 102,
            "confidence": 0.88,
            "zone_id": "Z-04",
            "evidence": {},
            "metadata": {
                "face_bbox": [98, 45, 185, 160],
                "zone_name": "Vehicle Staging Area Zone",
                "detector": "RetinaFace-ResNet50",
            }
        },
        {
            "camera_id": "CAM-05",
            "type": "FACE_DETECTED",
            "severity": "CRITICAL",
            "timestamp": (now - timedelta(minutes=8)).isoformat(),
            "object_type": "person",
            "track_id": 105,
            "confidence": 0.91,
            "zone_id": "Z-05",
            "evidence": {},
            "metadata": {
                "face_bbox": [150, 80, 260, 225],
                "restricted_zone_active": True,
                "restriction_level": "RESTRICTED",
                "zone_name": "South Entry Barrier Sector",
                "detector": "RetinaFace-ResNet50",
            }
        },
        {
            "camera_id": "CAM-06",
            "type": "FACE_DETECTED",
            "severity": "WARNING",
            "timestamp": (now - timedelta(minutes=4)).isoformat(),
            "object_type": "person",
            "track_id": 108,
            "confidence": 0.85,
            "zone_id": "Z-06",
            "evidence": {},
            "metadata": {
                "face_bbox": [110, 70, 205, 190],
                "zone_name": "Command Post Outer Perimeter",
                "detector": "RetinaFace-ResNet50",
            }
        },
        {
            "camera_id": "CAM-07",
            "type": "FACE_DETECTED",
            "severity": "INFO",
            "timestamp": (now - timedelta(minutes=2)).isoformat(),
            "object_type": "person",
            "track_id": 112,
            "confidence": 0.97,
            "zone_id": "Z-07",
            "evidence": {},
            "metadata": {
                "face_bbox": [140, 50, 255, 200],
                "zone_name": "Main Road Overwatch Sector",
                "detector": "RetinaFace-ResNet50",
            }
        },
        {
            "camera_id": "CAM-08",
            "type": "FACE_DETECTED",
            "severity": "INFO",
            "timestamp": (now - timedelta(minutes=1)).isoformat(),
            "object_type": "person",
            "track_id": 115,
            "confidence": 0.92,
            "zone_id": "Z-08",
            "evidence": {},
            "metadata": {
                "face_bbox": [130, 55, 240, 205],
                "zone_name": "West Highway Checkpoint Sector",
                "detector": "RetinaFace-ResNet50",
            }
        }
    ]

    for ev in faces_data:
        try:
            r = requests.post(f"{BASE_URL}/events", json=ev, timeout=5)
            if r.status_code == 201:
                print(f"  + Added Face Detection #{ev['track_id']} on {ev['camera_id']}")
            else:
                print(f"  ! Face post returned {r.status_code}: {r.text}")
        except Exception as e:
            print(f"  ! Face post error: {e}")

def seed_event_log_spread():
    print("\n[5/5] Seeding Event Log Spread (Intrusion, Loitering, Night Movement)...")
    now = datetime.now(timezone.utc)
    
    events_data = [
        {
            "camera_id": "CAM-03",
            "type": "INTRUSION",
            "severity": "CRITICAL",
            "timestamp": (now - timedelta(minutes=16)).isoformat(),
            "object_type": "person",
            "track_id": 201,
            "confidence": 0.95,
            "zone_id": "Z-03",
            "evidence": {
                "snapshot_uri": "",
                "clip_uri": ""
            },
            "metadata": {
                "rule_name": "Virtual Fence Breach",
                "direction": "NORTHBOUND",
                "speed_mps": 1.8,
            }
        },
        {
            "camera_id": "CAM-04",
            "type": "LOITERING",
            "severity": "WARNING",
            "timestamp": (now - timedelta(minutes=13)).isoformat(),
            "object_type": "person",
            "track_id": 204,
            "confidence": 0.89,
            "zone_id": "Z-04",
            "evidence": {},
            "metadata": {
                "rule_name": "Perimeter Dwell Time",
                "dwell_time_seconds": 185,
                "threshold_seconds": 120,
            }
        },
        {
            "camera_id": "CAM-05",
            "type": "INTRUSION",
            "severity": "CRITICAL",
            "timestamp": (now - timedelta(minutes=9)).isoformat(),
            "object_type": "person",
            "track_id": 208,
            "confidence": 0.92,
            "zone_id": "Z-05",
            "evidence": {},
            "metadata": {
                "rule_name": "Restricted Zone Incursion",
                "direction": "EASTBOUND",
            }
        },
        {
            "camera_id": "CAM-06",
            "type": "ZONE_ENTRY",
            "severity": "INFO",
            "timestamp": (now - timedelta(minutes=3)).isoformat(),
            "object_type": "vehicle",
            "track_id": 220,
            "confidence": 0.96,
            "zone_id": "Z-06",
            "evidence": {},
            "metadata": {
                "rule_name": "Zone Entry Log",
            }
        }
    ]

    for ev in events_data:
        try:
            r = requests.post(f"{BASE_URL}/events", json=ev, timeout=5)
            if r.status_code == 201:
                print(f"  + Added Event {ev['type']} ({ev['severity']}) on {ev['camera_id']}")
            else:
                print(f"  ! Event post returned {r.status_code}: {r.text}")
        except Exception as e:
            print(f"  ! Event post error: {e}")

if __name__ == "__main__":
    print("========================================")
    print("NETRA Demo Data Seeder — Investigate & Faces")
    print("========================================")
    seed_zones()
    seed_watchlist()
    seed_vehicle_sightings()
    seed_face_detections()
    seed_event_log_spread()
    print("\n✅ Seeding complete!")
