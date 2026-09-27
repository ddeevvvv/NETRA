import re
from typing import List, Optional
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session
from sqlalchemy import func
from pydantic import BaseModel, Field

from app.db.session import get_db
from app.models.event import Event
from app.models.camera import Camera
from app.models.zone import Zone
from app.models.watchlist import WatchlistEntry
from app.analytics.evidence_exporter import generate_evidence_pdf, generate_evidence_zip

router = APIRouter()


class VehicleSighting(BaseModel):
    event_id: str
    camera_id: str
    camera_name: Optional[str] = None
    location: Optional[str] = None
    timestamp: str
    plate_text: str
    raw_ocr: Optional[str] = None
    confidence: float
    zone_id: Optional[str] = None
    zone_name: Optional[str] = None
    watchlist_match: bool = False
    list_type: Optional[str] = None
    notes: Optional[str] = None
    event_type: str
    severity: str
    evidence: dict = Field(default_factory=dict)
    metadata: dict = Field(default_factory=dict)

def normalize_plate(plate: str) -> str:
    """Strips all non-alphanumeric characters and converts to UPPERCASE."""
    if not plate:
        return ""
    return re.sub(r'[^A-Z0-9]', '', plate.upper())

@router.get("/{plate}/sightings", response_model=List[VehicleSighting])
@router.get("/{plate}/history", response_model=List[VehicleSighting])
def get_vehicle_sightings(
    plate: str,
    db: Session = Depends(get_db)
):
    norm_query_plate = normalize_plate(plate)
    if not norm_query_plate:
        return []

    # Fetch all ANPR-related events (ANPR_READ, ANPR_MATCH, ANPR_WATCHLIST, ANPR)
    anpr_types = ["ANPR_READ", "ANPR_MATCH", "ANPR_WATCHLIST", "ANPR"]
    events = (
        db.query(Event)
        .filter(Event.type.in_(anpr_types))
        .all()
    )

    # Load camera mapping and zone mapping
    cameras = {c.id: c for c in db.query(Camera).all()}
    zones = {z.id: z for z in db.query(Zone).all()}

    sightings = []
    for ev in events:
        meta = ev.event_metadata or {}
        raw_plate = (
            meta.get("license_plate") or 
            meta.get("plate_text") or 
            meta.get("plate") or 
            ""
        )
        norm_event_plate = normalize_plate(str(raw_plate))

        if norm_event_plate == norm_query_plate:
            cam = cameras.get(ev.camera_id)
            cam_name = cam.name if cam else ev.camera_id
            cam_location = cam.location if cam else "Unknown Location"

            zone_obj = zones.get(ev.zone_id) if ev.zone_id else None
            zone_name = zone_obj.name if zone_obj else None

            # Check if watchlist details are in metadata or query watchlist table
            list_type = meta.get("list_type")
            notes = meta.get("notes")
            is_watchlist = ev.type in ["ANPR_MATCH", "ANPR_WATCHLIST"] or bool(list_type)

            if not list_type and is_watchlist:
                # Fallback check against Watchlist table
                wl = db.query(WatchlistEntry).filter(
                    func.upper(WatchlistEntry.reference_value) == norm_query_plate
                ).first()
                if wl:
                    list_type = wl.list_type
                    notes = wl.notes

            sightings.append(VehicleSighting(
                event_id=ev.id,
                camera_id=ev.camera_id or "UNKNOWN",
                camera_name=cam_name,
                location=cam_location,
                timestamp=ev.timestamp.isoformat() if hasattr(ev.timestamp, 'isoformat') else str(ev.timestamp),
                plate_text=raw_plate or norm_query_plate,
                raw_ocr=meta.get("raw_ocr") or raw_plate,
                confidence=ev.confidence or 0.0,
                zone_id=ev.zone_id,
                zone_name=zone_name,
                watchlist_match=is_watchlist,
                list_type=list_type,
                notes=notes,
                event_type=ev.type,
                severity=ev.severity,
                evidence=ev.evidence or {},
                metadata=meta
            ))

    # Sort sightings chronologically (timestamp ASC)
    sightings.sort(key=lambda s: s.timestamp)
    return sightings


@router.get("/{plate}/evidence-package")
def export_vehicle_evidence_package(

    plate: str,
    export_format: str = Query("pdf", alias="format", description="Export format: 'pdf' or 'zip'"),
    db: Session = Depends(get_db)
):
    """
    Exports a self-contained Evidence Package for a vehicle plate tracking timeline.
    """
    sightings = get_vehicle_sightings(plate=plate, db=db)
    norm_plate = normalize_plate(plate)

    if not sightings:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No sightings found for license plate '{norm_plate or plate}'."
        )

    # Compile summary metrics
    unique_cams = list(set(s.camera_id for s in sightings))
    highest_conf = max(s.confidence for s in sightings)
    is_wl = any(s.watchlist_match for s in sightings)
    wl_type = next((s.list_type for s in sightings if s.list_type), None)
    wl_notes = next((s.notes for s in sightings if s.notes), None)

    sev = "CRITICAL" if wl_type == "BLACKLIST" else ("HIGH" if is_wl else "INFO")
    first_ts = sightings[0].timestamp
    last_ts = sightings[-1].timestamp

    desc = (
        f"Vehicle Tracking Dossier for plate {norm_plate}: {len(sightings)} sighting{'s' if len(sightings)!=1 else ''} "
        f"across {len(unique_cams)} camera{'s' if len(unique_cams)!=1 else ''}."
    )
    if is_wl:
        desc += f" [WATCHLIST {wl_type or 'ALERT'} MATCH]"
        if wl_notes:
            desc += f" — {wl_notes}"

    events_data = []
    for s in sightings:
        events_data.append({
            "id": s.event_id,
            "camera_id": s.camera_id,
            "type": s.event_type,
            "severity": s.severity,
            "timestamp": s.timestamp,
            "object_type": "vehicle",
            "track_id": None,
            "confidence": s.confidence,
            "zone_id": s.zone_id,
            "acknowledged": True,
            "evidence": s.evidence or {},
            "event_metadata": {
                "license_plate": s.plate_text,
                "raw_ocr": s.raw_ocr,
                "list_type": s.list_type,
                "notes": s.notes,
                "location": s.location,
            }
        })

    title = f"Vehicle Tracking Dossier: {norm_plate}"
    summary_meta = {
        "camera_id": ", ".join(unique_cams[:3]) + (f" (+{len(unique_cams)-3} more)" if len(unique_cams) > 3 else ""),
        "zone_id": sightings[0].zone_name or sightings[0].zone_id or "General",
        "severity": sev,
        "total_count": len(sightings),
        "unacked_count": 0,
        "first_event_at": first_ts,
        "last_event_at": last_ts,
        "description": desc,
        "plate_number": norm_plate,
        "watchlist_status": f"{wl_type} MATCH" if is_wl else "Standard Read",
    }

    clean_format = (export_format or "pdf").lower().strip()
    safe_plate = re.sub(r'[^A-Za-z0-9_-]', '_', norm_plate)
    ts_file = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    if clean_format == "zip":
        zip_bytes = generate_evidence_zip(
            title=title,
            package_type="VEHICLE_TRACKING",
            summary_meta=summary_meta,
            events=events_data,
            generated_by="IBVAP Operator",
        )
        return Response(
            content=zip_bytes,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="IBVAP_Vehicle_{safe_plate}_{ts_file}.zip"'},
        )
    else:
        pdf_bytes = generate_evidence_pdf(
            title=title,
            package_type="VEHICLE_TRACKING",
            summary_meta=summary_meta,
            events=events_data,
            generated_by="IBVAP Operator",
        )
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="IBVAP_Vehicle_{safe_plate}_{ts_file}.pdf"'},
        )

