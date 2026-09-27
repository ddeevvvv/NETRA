import logging
from datetime import datetime
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from app.db.session import get_db
from app.models.camera import Camera
from app.models.event import Event
from app.ingestion.manager import ingestion_manager

router = APIRouter()
logger = logging.getLogger("ibvap.api.sites")

class CameraSummary(BaseModel):
    id: str
    name: str
    location: Optional[str] = None
    is_connected: bool
    status: str
    connection_state: str = "OFFLINE"
    last_seen_at: Optional[datetime] = None
    reconnect_attempt_count: int = 0
    fps: float = 0.0

class SiteStatusResponse(BaseModel):
    id: str
    name: str
    location_label: str
    x: float  # Percentage offset (0-100) for schematic map placement
    y: float  # Percentage offset (0-100) for schematic map placement
    total_cameras: int
    online_count: int
    offline_count: int
    cameras: List[CameraSummary]
    highest_alert_severity: str  # CRITICAL, HIGH, WARNING, INFO, NONE
    unacked_alert_count: int
    status: str  # HEALTHY, DEGRADED, CRITICAL_ALERT, HIGH_ALERT, OFFLINE

# Static site placement mapping for border outposts (BOPs) and check posts
SITE_CONFIGS = [
    {
        "id": "BOP-01",
        "name": "BOP 01 — North Sector",
        "location_label": "North Border Perimeter / Gate 1",
        "x": 28.0,
        "y": 32.0,
        "matching_keywords": ["TEST-01", "NORTH", "CAM1", "SECTOR ALPHA", "PERIMETER NORTH"]
    },
    {
        "id": "BOP-02",
        "name": "BOP 02 — East Gate",
        "location_label": "East Gate & Checkpost Sector",
        "x": 72.0,
        "y": 45.0,
        "matching_keywords": ["TEST-02", "EAST", "CAM2", "GATE 2", "EAST PERIMETER"]
    },
    {
        "id": "CP-03",
        "name": "Check Post 03 — West Pass",
        "location_label": "West Transit Highway Checkpost",
        "x": 45.0,
        "y": 75.0,
        "matching_keywords": ["WEST", "CHECKPOST", "HIGHWAY", "PASS"]
    }
]

SEVERITY_WEIGHTS = {
    "CRITICAL": 4,
    "HIGH": 3,
    "WARNING": 2,
    "INFO": 1,
    "NONE": 0
}

@router.get("/status", response_model=List[SiteStatusResponse])
def get_sites_status(db: Session = Depends(get_db)):
    """
    Returns schematic site status overview across all border outposts.
    Aggregates camera connectivity and active unacknowledged alert severities.
    """
    db_cameras = db.query(Camera).all()

    # Group cameras into sites based on camera ID/name/location matching
    site_cameras_map: Dict[str, List[Camera]] = {cfg["id"]: [] for cfg in SITE_CONFIGS}

    for cam in db_cameras:
        assigned = False
        search_target = f"{cam.id} {cam.name} {cam.location or ''}".upper()
        
        for cfg in SITE_CONFIGS:
            if any(kw in search_target for kw in cfg["matching_keywords"]):
                site_cameras_map[cfg["id"]].append(cam)
                assigned = True
                break
        
        if not assigned:
            # Fallback assignment to BOP-01 if unassigned
            site_cameras_map["BOP-01"].append(cam)

    # Fetch all actionable unacknowledged incident events for alert severity calculation
    unacked_events = (
        db.query(Event)
        .filter(
            Event.acknowledged == False,
            Event.requires_acknowledgment == True
        )
        .all()
    )

    # Map events by camera_id
    cam_events_map: Dict[str, List[Event]] = {}
    for ev in unacked_events:
        if ev.camera_id:
            cam_events_map.setdefault(ev.camera_id, []).append(ev)

    sites_response: List[SiteStatusResponse] = []

    for cfg in SITE_CONFIGS:
        site_cams = site_cameras_map[cfg["id"]]
        cam_summaries: List[CameraSummary] = []
        online_cnt = 0
        offline_cnt = 0
        highest_sev = "NONE"
        site_unacked_count = 0

        for cam in site_cams:
            worker = ingestion_manager.get_worker(cam.id)
            health = worker.get_health_status() if worker else {}
            is_conn = bool(worker and worker.is_running and worker.is_connected)
            fps_val = health.get("measured_fps", 0.0)
            conn_state = health.get("connection_state", "ONLINE" if is_conn else "OFFLINE")
            reconnect_cnt = health.get("reconnect_attempt_count", 0)
            last_seen = worker.last_seen_at if (worker and worker.last_seen_at) else cam.last_seen_at

            if conn_state in ("ONLINE", "DEGRADED"):
                online_cnt += 1
            else:
                offline_cnt += 1

            cam_summaries.append(CameraSummary(
                id=cam.id,
                name=cam.name,
                location=cam.location,
                is_connected=is_conn,
                status=conn_state,
                connection_state=conn_state,
                last_seen_at=last_seen,
                reconnect_attempt_count=reconnect_cnt,
                fps=fps_val
            ))

            # Check camera unacknowledged alerts
            events = cam_events_map.get(cam.id, [])
            site_unacked_count += len(events)
            for ev in events:
                sev = (ev.severity or "INFO").upper()
                if SEVERITY_WEIGHTS.get(sev, 0) > SEVERITY_WEIGHTS.get(highest_sev, 0):
                    highest_sev = sev

        # Derive overall site status
        total_cams = len(site_cams)
        has_degraded = any(c.connection_state in ("DEGRADED", "RECONNECTING") for c in cam_summaries)
        if highest_sev == "CRITICAL":
            site_status = "CRITICAL_ALERT"
        elif highest_sev == "HIGH":
            site_status = "HIGH_ALERT"
        elif total_cams > 0 and online_cnt == 0:
            site_status = "OFFLINE"
        elif offline_cnt > 0 or has_degraded:
            site_status = "DEGRADED"
        else:
            site_status = "HEALTHY"

        sites_response.append(SiteStatusResponse(
            id=cfg["id"],
            name=cfg["name"],
            location_label=cfg["location_label"],
            x=cfg["x"],
            y=cfg["y"],
            total_cameras=total_cams,
            online_count=online_cnt,
            offline_count=offline_cnt,
            cameras=cam_summaries,
            highest_alert_severity=highest_sev,
            unacked_alert_count=site_unacked_count,
            status=site_status
        ))

    return sites_response
