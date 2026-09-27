import re
from datetime import datetime, timezone
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models.event import Event
from app.schemas.event import EventCreate, EventResponse, EventAcknowledge
from app.core.redis import publish_event

router = APIRouter()
TELEMETRY_EVENT_TYPES = {"FACE_DETECTED", "CAMERA_HEALTH"}


class BulkAcknowledgeRequest(BaseModel):
    """Filters for bulk acknowledgment. All fields are optional.
    If none are provided, ALL unacknowledged incidents are cleared."""
    camera_id: Optional[str] = None
    site_id: Optional[str] = None
    event_ids: Optional[List[str]] = None
    acknowledged_by: str = "operator"

@router.post("", response_model=EventResponse, status_code=status.HTTP_201_CREATED)
async def create_event(
    event_in: EventCreate,
    db: Session = Depends(get_db)
):
    event_dict = event_in.model_dump()
    metadata_val = event_dict.pop("metadata", {})
    evt_type = (event_dict.get("type") or "").upper()
    req_ack = evt_type not in TELEMETRY_EVENT_TYPES
    
    db_event = Event(
        **event_dict,
        requires_acknowledgment=req_ack,
        event_metadata=metadata_val
    )
    db.add(db_event)
    db.commit()
    db.refresh(db_event)

    # Convert db_event to schema response dict matching exact event schema JSON
    response_obj = EventResponse.model_validate(db_event)
    event_payload = response_obj.model_dump(mode="json")

    # Publish to Redis channel 'ibvap:alerts' and WebSocket clients
    await publish_event(event_payload)

    return db_event

@router.get("", response_model=List[EventResponse])
def list_events(
    camera_id: Optional[str] = Query(None, description="Filter by camera_id"),
    type: Optional[str] = Query(None, description="Filter by event type"),
    severity: Optional[str] = Query(None, description="Filter by severity level"),
    acknowledged: Optional[bool] = Query(None, description="Filter by acknowledgment status"),
    requires_acknowledgment: Optional[bool] = Query(None, description="Filter by requires_acknowledgment"),
    start_time: Optional[datetime] = Query(None, description="Start timestamp (ISO format)"),
    end_time: Optional[datetime] = Query(None, description="End timestamp (ISO format)"),
    from_time: Optional[datetime] = Query(None, alias="from", description="Alias for start_time"),
    to_time: Optional[datetime] = Query(None, alias="to", description="Alias for end_time"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db)
):
    query = db.query(Event)

    if camera_id:
        query = query.filter(Event.camera_id == camera_id)
    if type:
        query = query.filter(Event.type == type)
    if severity:
        query = query.filter(Event.severity == severity)
    if acknowledged is not None:
        query = query.filter(Event.acknowledged == acknowledged)
    if requires_acknowledgment is not None:
        query = query.filter(Event.requires_acknowledgment == requires_acknowledgment)
        
    effective_start = start_time or from_time
    if effective_start:
        query = query.filter(Event.timestamp >= effective_start)
        
    effective_end = end_time or to_time
    if effective_end:
        query = query.filter(Event.timestamp <= effective_end)

    events = query.order_by(Event.timestamp.desc()).offset(offset).limit(limit).all()
    return events

@router.post("/acknowledge-bulk")
def acknowledge_bulk(
    req: BulkAcknowledgeRequest,
    db: Session = Depends(get_db)
):
    """Bulk-acknowledge unacknowledged incidents matching the given filters.
    Telemetry events (requires_acknowledgment=False) are never touched.
    """
    from app.models.camera import Camera  # local import to avoid circular deps

    query = db.query(Event).filter(
        Event.acknowledged == False,
        Event.requires_acknowledgment == True,
    )

    if req.event_ids:
        query = query.filter(Event.id.in_(req.event_ids))
    elif req.camera_id:
        query = query.filter(Event.camera_id == req.camera_id)
    elif req.site_id:
        # Filter by cameras belonging to the given site
        camera_ids = (
            db.query(Camera.id)
            .filter(Camera.site_id == req.site_id)
            .all()
        )
        cam_id_list = [c[0] for c in camera_ids]
        query = query.filter(Event.camera_id.in_(cam_id_list))

    events = query.all()
    now = datetime.now(timezone.utc)
    for ev in events:
        ev.acknowledged = True
        ev.acknowledged_at = now
        ev.acknowledged_by = req.acknowledged_by
    db.commit()

    return {
        "acknowledged_count": len(events),
        "message": f"{len(events)} incident(s) acknowledged by {req.acknowledged_by}.",
    }


@router.get("/summaries")
def get_incident_summaries(
    camera_id: Optional[str] = Query(None, description="Filter to a specific camera"),
    # The incident-clustering window is deliberately tightened to 5 minutes (2–5 min range)
    # This avoids merging unrelated activities on the same camera (e.g., morning loitering vs evening intrusion).
    window_minutes: int = Query(5, ge=1, le=1440, description="Cluster window in minutes (default tightened to 5)"),
    only_unacked: bool = Query(True, description="Only include unacknowledged incidents"),
    db: Session = Depends(get_db),
):
    """
    Returns plain-language incident summaries by clustering raw incident events
    (requires_acknowledgment=True) per camera within a rolling time window.

    Each summary entry represents one cluster:
    - camera_id, site_id (if known), zone_id (most common)
    - event_types: list of distinct event types in the cluster
    - total_count: number of events in the cluster
    - unacked_count: number still needing acknowledgment
    - severity: highest severity in the cluster
    - first_event_at / last_event_at: time range
    - description: human-readable one-liner
    - rule_name: from first event's metadata (if present)
    """
    from app.models.camera import Camera  # local import to avoid circular deps
    from collections import defaultdict

    # Base query — only incidents, not telemetry
    q = db.query(Event).filter(Event.requires_acknowledgment == True)
    if camera_id:
        q = q.filter(Event.camera_id == camera_id)
    if only_unacked:
        q = q.filter(Event.acknowledged == False)

    incidents = q.order_by(Event.camera_id, Event.timestamp.asc()).all()

    # Build camera→site map for label enrichment
    camera_site_map: dict[str, str | None] = {}
    if incidents:
        cam_ids = list({ev.camera_id for ev in incidents if ev.camera_id})
        cameras = db.query(Camera).filter(Camera.id.in_(cam_ids)).all()
        camera_site_map = {c.id: getattr(c, "site_id", None) for c in cameras}

    # ── Cluster events per (camera_id) within the rolling window ──────────
    window_seconds = window_minutes * 60

    # Group events by camera
    by_camera: dict[str, list] = defaultdict(list)
    for ev in incidents:
        by_camera[ev.camera_id or "UNKNOWN"].append(ev)

    summaries = []

    _sev_rank = {"CRITICAL": 4, "HIGH": 3, "WARNING": 2, "INFO": 1}

    for cam_id, evs in by_camera.items():
        # Cluster within the window: if gap between consecutive events > window, start new cluster
        clusters: list[list] = []
        current_cluster: list = []

        for ev in evs:  # already sorted by timestamp asc
            if not current_cluster:
                current_cluster.append(ev)
            else:
                prev_ts = current_cluster[-1].timestamp
                curr_ts = ev.timestamp
                # Normalise to offset-naive UTC for subtraction
                if prev_ts.tzinfo is not None:
                    prev_ts = prev_ts.replace(tzinfo=None)
                if curr_ts.tzinfo is not None:
                    curr_ts = curr_ts.replace(tzinfo=None)
                gap = (curr_ts - prev_ts).total_seconds()
                if gap <= window_seconds:
                    current_cluster.append(ev)
                else:
                    clusters.append(current_cluster)
                    current_cluster = [ev]

        if current_cluster:
            clusters.append(current_cluster)

        for cluster in clusters:
            types_in_cluster = list({e.type for e in cluster})
            zones_in_cluster = [e.zone_id for e in cluster if e.zone_id]
            primary_zone = max(set(zones_in_cluster), key=zones_in_cluster.count) if zones_in_cluster else None

            highest_sev = max(cluster, key=lambda e: _sev_rank.get(e.severity, 0)).severity
            first_ev = cluster[0]
            last_ev = cluster[-1]
            unacked = sum(1 for e in cluster if not e.acknowledged)

            # Plain-language description
            type_str = " + ".join(types_in_cluster)
            zone_str = f" in zone {primary_zone}" if primary_zone else ""
            desc = (
                f"{len(cluster)} {type_str} event{'s' if len(cluster) > 1 else ''}"
                f"{zone_str} on {cam_id}"
            )
            if unacked > 0:
                desc += f" — {unacked} pending acknowledgment"

            # Rule name from first event metadata if available
            first_meta = first_ev.event_metadata or {}
            rule_name = first_meta.get("rule_name") or None

            summaries.append({
                "camera_id": cam_id,
                "site_id": camera_site_map.get(cam_id),
                "zone_id": primary_zone,
                "event_types": types_in_cluster,
                "total_count": len(cluster),
                "unacked_count": unacked,
                "severity": highest_sev,
                "first_event_at": first_ev.timestamp.isoformat() if first_ev.timestamp else None,
                "last_event_at": last_ev.timestamp.isoformat() if last_ev.timestamp else None,
                "description": desc,
                "rule_name": rule_name,
            })

    # Sort: highest severity first, then most recent last_event_at
    summaries.sort(
        key=lambda s: (-_sev_rank.get(s["severity"], 0), s["last_event_at"] or ""),
        reverse=False,
    )

    return {"window_minutes": window_minutes, "total_clusters": len(summaries), "summaries": summaries}


@router.get("/incident-evidence-package")
@router.get("/evidence-package")
def export_incident_evidence_package(
    camera_id: Optional[str] = Query(None, description="Camera ID"),
    zone_id: Optional[str] = Query(None, description="Zone ID"),
    event_ids: Optional[str] = Query(None, description="Comma-separated event UUIDs"),
    start_time: Optional[datetime] = Query(None, description="Start timestamp of incident cluster"),
    end_time: Optional[datetime] = Query(None, description="End timestamp of incident cluster"),
    first_event_at: Optional[datetime] = Query(None, description="Alias for start_time"),
    last_event_at: Optional[datetime] = Query(None, description="Alias for end_time"),
    export_format: str = Query("pdf", alias="format", description="Export format: 'pdf' or 'zip'"),
    db: Session = Depends(get_db)
):
    """
    Exports a self-contained, certified Evidence Package (PDF report or ZIP bundle)
    for an incident cluster or set of events.
    """
    from fastapi.responses import Response
    from app.analytics.evidence_exporter import generate_evidence_pdf, generate_evidence_zip
    from app.models.camera import Camera

    query = db.query(Event)

    # If specific event IDs are requested
    if event_ids:
        id_list = [i.strip() for i in event_ids.split(",") if i.strip()]
        query = query.filter(Event.id.in_(id_list))
    else:
        if camera_id:
            query = query.filter(Event.camera_id == camera_id)
        if zone_id:
            query = query.filter(Event.zone_id == zone_id)

        eff_start = start_time or first_event_at
        eff_end = end_time or last_event_at

        if eff_start:
            query = query.filter(Event.timestamp >= eff_start)
        if eff_end:
            query = query.filter(Event.timestamp <= eff_end)

    events_db = query.order_by(Event.timestamp.asc()).all()

    if not events_db:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No events found matching the specified incident criteria."
        )

    # Convert events to dicts
    events_data = []
    types_set = set()
    zones_list = []
    unacked = 0
    _sev_rank = {"CRITICAL": 4, "HIGH": 3, "WARNING": 2, "INFO": 1}
    highest_sev = "INFO"

    for ev in events_db:
        if not ev.acknowledged:
            unacked += 1
        types_set.add(ev.type)
        if ev.zone_id:
            zones_list.append(ev.zone_id)
        if _sev_rank.get(ev.severity, 0) > _sev_rank.get(highest_sev, 0):
            highest_sev = ev.severity

        events_data.append({
            "id": ev.id,
            "camera_id": ev.camera_id,
            "type": ev.type,
            "severity": ev.severity,
            "timestamp": ev.timestamp.isoformat() if ev.timestamp else "",
            "object_type": ev.object_type,
            "track_id": ev.track_id,
            "confidence": ev.confidence,
            "zone_id": ev.zone_id,
            "acknowledged": ev.acknowledged,
            "acknowledged_by": ev.acknowledged_by,
            "evidence": ev.evidence or {},
            "event_metadata": ev.event_metadata or {},
        })

    primary_zone = max(set(zones_list), key=zones_list.count) if zones_list else zone_id
    primary_cam = camera_id or (events_db[0].camera_id if events_db else "ALL-CAMERAS")
    first_ts = events_db[0].timestamp.strftime("%Y-%m-%d %H:%M:%S UTC") if events_db[0].timestamp else ""
    last_ts = events_db[-1].timestamp.strftime("%Y-%m-%d %H:%M:%S UTC") if events_db[-1].timestamp else ""

    type_str = " + ".join(sorted(types_set))
    zone_str = f" in zone {primary_zone}" if primary_zone else ""
    description = (
        f"{len(events_db)} {type_str} event{'s' if len(events_db) > 1 else ''}"
        f"{zone_str} on {primary_cam}"
    )
    if unacked > 0:
        description += f" — {unacked} pending acknowledgment"

    title = f"Incident Cluster: {primary_cam}" + (f" ({primary_zone})" if primary_zone else "")
    summary_meta = {
        "camera_id": primary_cam,
        "zone_id": primary_zone,
        "severity": highest_sev,
        "total_count": len(events_db),
        "unacked_count": unacked,
        "first_event_at": first_ts,
        "last_event_at": last_ts,
        "description": description,
    }

    clean_format = (export_format or "pdf").lower().strip()
    safe_cam = re.sub(r'[^A-Za-z0-9_-]', '_', primary_cam)
    ts_file = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    if clean_format == "zip":
        zip_bytes = generate_evidence_zip(
            title=title,
            package_type="INCIDENT_CLUSTER",
            summary_meta=summary_meta,
            events=events_data,
            generated_by="IBVAP Operator",
        )
        return Response(
            content=zip_bytes,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="IBVAP_Evidence_{safe_cam}_{ts_file}.zip"'},
        )
    else:
        pdf_bytes = generate_evidence_pdf(
            title=title,
            package_type="INCIDENT_CLUSTER",
            summary_meta=summary_meta,
            events=events_data,
            generated_by="IBVAP Operator",
        )
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="IBVAP_Evidence_{safe_cam}_{ts_file}.pdf"'},
        )


@router.get("/{event_id}/evidence-package")
def export_single_event_evidence_package(
    event_id: str,
    export_format: str = Query("pdf", alias="format", description="Export format: 'pdf' or 'zip'"),
    db: Session = Depends(get_db)
):
    """
    Exports a self-contained Evidence Package for a single event.
    """
    from fastapi.responses import Response
    from app.analytics.evidence_exporter import generate_evidence_pdf, generate_evidence_zip

    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Event with ID '{event_id}' not found"
        )

    ts_str = event.timestamp.strftime("%Y-%m-%d %H:%M:%S UTC") if event.timestamp else ""
    event_dict = {
        "id": event.id,
        "camera_id": event.camera_id,
        "type": event.type,
        "severity": event.severity,
        "timestamp": event.timestamp.isoformat() if event.timestamp else "",
        "object_type": event.object_type,
        "track_id": event.track_id,
        "confidence": event.confidence,
        "zone_id": event.zone_id,
        "acknowledged": event.acknowledged,
        "acknowledged_by": event.acknowledged_by,
        "evidence": event.evidence or {},
        "event_metadata": event.event_metadata or {},
    }

    desc = f"Single {event.type} event on {event.camera_id}"
    if event.zone_id:
        desc += f" in zone {event.zone_id}"
    if not event.acknowledged:
        desc += " — Pending acknowledgment"

    title = f"Event Record: {event.type} on {event.camera_id}"
    summary_meta = {
        "camera_id": event.camera_id,
        "zone_id": event.zone_id,
        "severity": event.severity,
        "total_count": 1,
        "unacked_count": 0 if event.acknowledged else 1,
        "first_event_at": ts_str,
        "last_event_at": ts_str,
        "description": desc,
    }

    clean_format = (export_format or "pdf").lower().strip()
    safe_id = re.sub(r'[^A-Za-z0-9_-]', '_', event_id[:8])

    if clean_format == "zip":
        zip_bytes = generate_evidence_zip(
            title=title,
            package_type="SINGLE_EVENT",
            summary_meta=summary_meta,
            events=[event_dict],
            generated_by="IBVAP Operator",
        )
        return Response(
            content=zip_bytes,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="IBVAP_Event_{safe_id}.zip"'},
        )
    else:
        pdf_bytes = generate_evidence_pdf(
            title=title,
            package_type="SINGLE_EVENT",
            summary_meta=summary_meta,
            events=[event_dict],
            generated_by="IBVAP Operator",
        )
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="IBVAP_Event_{safe_id}.pdf"'},
        )


@router.get("/{event_id}", response_model=EventResponse)
def get_event(
    event_id: str,
    db: Session = Depends(get_db)
):
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Event with ID '{event_id}' not found"
        )
    return event

@router.post("/{event_id}/acknowledge", response_model=EventResponse)
def acknowledge_event(
    event_id: str,
    ack_in: EventAcknowledge,
    db: Session = Depends(get_db)
):
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Event with ID '{event_id}' not found"
        )
    
    event.acknowledged = True
    event.acknowledged_at = datetime.now(timezone.utc)
    event.acknowledged_by = ack_in.acknowledged_by
    db.commit()
    db.refresh(event)
    return event

