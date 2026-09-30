import logging
import uuid
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any, Union
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from app.db.session import get_db
from app.models.camera import Camera
from app.models.event import Event
from app.models.site_restriction import SiteRestriction
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

class SiteRestrictionCreate(BaseModel):
    site_id: str
    name: Optional[str] = None
    restriction_level: str = "HIGH"  # HIGH, CRITICAL, WARNING
    polygon_geojson: Any  # coordinates array or GeoJSON object
    is_active: bool = True

class SiteRestrictionResponse(BaseModel):
    id: str
    site_id: str
    name: Optional[str] = None
    restriction_level: str
    polygon_geojson: Any
    is_active: bool
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class SiteStatusResponse(BaseModel):
    id: str
    name: str
    location_label: str
    x: float  # Percentage offset (0-100) for schematic map placement
    y: float  # Percentage offset (0-100) for schematic map placement
    lat: Optional[float] = None  # Geographic latitude for GIS map placement
    lng: Optional[float] = None  # Geographic longitude for GIS map placement
    total_cameras: int
    online_count: int
    offline_count: int
    cameras: List[CameraSummary]
    highest_alert_severity: str  # CRITICAL, HIGH, WARNING, INFO, NONE
    unacked_alert_count: int
    status: str  # HEALTHY, DEGRADED, CRITICAL_ALERT, HIGH_ALERT, OFFLINE
    has_restriction: bool = False
    restriction_level: Optional[str] = None
    active_restrictions: List[SiteRestrictionResponse] = []

# Static site placement mapping for border outposts (BOPs) and check posts
SITE_CONFIGS = [
    {
        "id": "BOP-01",
        "name": "BOP 01 — North Sector",
        "location_label": "North Border Perimeter / Gate 1",
        "x": 28.0,
        "y": 32.0,
        "lat": 32.5850,
        "lng": 74.8320,
        "matching_keywords": ["TEST-01", "NORTH", "CAM1", "SECTOR ALPHA", "PERIMETER NORTH", "CAM-03", "CAM-04", "CAM-05", "CAM-06", "CAM-07"]
    },
    {
        "id": "BOP-02",
        "name": "BOP 02 — East Gate",
        "location_label": "East Gate & Checkpost Sector",
        "x": 72.0,
        "y": 45.0,
        "lat": 32.5310,
        "lng": 74.9650,
        "matching_keywords": ["TEST-02", "EAST", "CAM2", "GATE 2", "EAST PERIMETER"]
    },
    {
        "id": "CP-03",
        "name": "Check Post 03 — West Pass",
        "location_label": "West Transit Highway Checkpost",
        "x": 45.0,
        "y": 75.0,
        "lat": 32.4630,
        "lng": 74.8050,
        "matching_keywords": ["WEST", "CHECKPOST", "HIGHWAY", "PASS", "CAM-08"]
    }
]

SEVERITY_WEIGHTS = {
    "CRITICAL": 4,
    "HIGH": 3,
    "WARNING": 2,
    "INFO": 1,
    "NONE": 0
}

def get_site_for_camera_obj(cam: Camera) -> str:
    """Helper to map a camera to its configured site ID."""
    search_target = f"{cam.id} {cam.name} {cam.location or ''}".upper()
    for cfg in SITE_CONFIGS:
        if any(kw in search_target for kw in cfg["matching_keywords"]):
            return cfg["id"]
    return "BOP-01"

def get_site_for_camera_id_str(db: Session, camera_id: Optional[str]) -> str:
    """Helper to map a camera_id string to its configured site ID."""
    if not camera_id:
        return "BOP-01"
    cam = db.query(Camera).filter(Camera.id == camera_id).first()
    if cam:
        return get_site_for_camera_obj(cam)
    # Direct keyword fallback
    cid = camera_id.upper()
    for cfg in SITE_CONFIGS:
        if any(kw in cid for kw in cfg["matching_keywords"]):
            return cfg["id"]
    return "BOP-01"

@router.get("/status", response_model=List[SiteStatusResponse])
def get_sites_status(db: Session = Depends(get_db)):
    """
    Returns schematic site status overview across all border outposts.
    Aggregates camera connectivity, active unacknowledged alert severities,
    and active site restriction zones.
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

    # Fetch all active restriction zones
    all_restrictions = (
        db.query(SiteRestriction)
        .filter(SiteRestriction.is_active == True)
        .order_by(SiteRestriction.created_at.desc())
        .all()
    )
    site_restrictions_map: Dict[str, List[SiteRestriction]] = {cfg["id"]: [] for cfg in SITE_CONFIGS}
    for r in all_restrictions:
        if r.site_id in site_restrictions_map:
            site_restrictions_map[r.site_id].append(r)

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

        # Restrictions for this site
        site_r_list = site_restrictions_map.get(cfg["id"], [])
        has_restr = len(site_r_list) > 0
        restr_lvl = site_r_list[0].restriction_level if has_restr else None

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
            lat=cfg.get("lat"),
            lng=cfg.get("lng"),
            total_cameras=total_cams,
            online_count=online_cnt,
            offline_count=offline_cnt,
            cameras=cam_summaries,
            highest_alert_severity=highest_sev,
            unacked_alert_count=site_unacked_count,
            status=site_status,
            has_restriction=has_restr,
            restriction_level=restr_lvl,
            active_restrictions=[
                SiteRestrictionResponse.model_validate(r) for r in site_r_list
            ]
        ))

    return sites_response

# ── Site Restriction CRUD Endpoints ──

@router.get("/restrictions", response_model=List[SiteRestrictionResponse])
def list_site_restrictions(
    site_id: Optional[str] = Query(None, description="Filter by site_id"),
    active_only: bool = Query(True, description="Only return active restrictions"),
    db: Session = Depends(get_db)
):
    """List all site restriction zones."""
    query = db.query(SiteRestriction)
    if site_id:
        query = query.filter(SiteRestriction.site_id == site_id)
    if active_only:
        query = query.filter(SiteRestriction.is_active == True)
    
    return query.order_by(SiteRestriction.created_at.desc()).all()

@router.post("/restrictions", response_model=SiteRestrictionResponse, status_code=status.HTTP_201_CREATED)
def create_site_restriction(
    restr_in: SiteRestrictionCreate,
    db: Session = Depends(get_db)
):
    """Create a new site-level restriction zone polygon."""
    valid_site_ids = {cfg["id"] for cfg in SITE_CONFIGS}
    if restr_in.site_id not in valid_site_ids:
        # If unknown site ID, fallback or validate
        restr_in.site_id = "BOP-01"

    name_val = restr_in.name or f"{restr_in.site_id} Restricted Zone"

    db_restr = SiteRestriction(
        id=str(uuid.uuid4()),
        site_id=restr_in.site_id,
        name=name_val,
        restriction_level=restr_in.restriction_level.upper() if restr_in.restriction_level else "HIGH",
        polygon_geojson=restr_in.polygon_geojson,
        is_active=restr_in.is_active,
        created_at=datetime.now(timezone.utc)
    )
    db.add(db_restr)
    db.commit()
    db.refresh(db_restr)
    logger.info(f"Created site restriction zone {db_restr.id} for {db_restr.site_id} ({db_restr.restriction_level})")
    return db_restr

@router.delete("/restrictions/{restriction_id}")
def delete_site_restriction(
    restriction_id: str,
    db: Session = Depends(get_db)
):
    """Delete a site restriction zone."""
    db_restr = db.query(SiteRestriction).filter(SiteRestriction.id == restriction_id).first()
    if not db_restr:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Site restriction '{restriction_id}' not found"
        )
    db.delete(db_restr)
    db.commit()
    logger.info(f"Deleted site restriction {restriction_id}")
    return {"message": f"Site restriction '{restriction_id}' deleted successfully", "id": restriction_id}

@router.patch("/restrictions/{restriction_id}", response_model=SiteRestrictionResponse)
def update_site_restriction(
    restriction_id: str,
    is_active: Optional[bool] = None,
    restriction_level: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Update or toggle a site restriction zone."""
    db_restr = db.query(SiteRestriction).filter(SiteRestriction.id == restriction_id).first()
    if not db_restr:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Site restriction '{restriction_id}' not found"
        )
    if is_active is not None:
        db_restr.is_active = is_active
    if restriction_level is not None:
        db_restr.restriction_level = restriction_level.upper()
    
    db.commit()
    db.refresh(db_restr)
    return db_restr
