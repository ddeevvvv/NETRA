from datetime import datetime, timezone
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models.event import Event
from app.schemas.event import EventCreate, EventResponse, EventAcknowledge
from app.core.redis import publish_event

router = APIRouter()

@router.post("", response_model=EventResponse, status_code=status.HTTP_201_CREATED)
async def create_event(
    event_in: EventCreate,
    db: Session = Depends(get_db)
):
    event_dict = event_in.model_dump()
    metadata_val = event_dict.pop("metadata", {})
    
    db_event = Event(
        **event_dict,
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
        
    effective_start = start_time or from_time
    if effective_start:
        query = query.filter(Event.timestamp >= effective_start)
        
    effective_end = end_time or to_time
    if effective_end:
        query = query.filter(Event.timestamp <= effective_end)

    events = query.order_by(Event.timestamp.desc()).offset(offset).limit(limit).all()
    return events

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
