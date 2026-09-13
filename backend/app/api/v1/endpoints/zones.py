from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models.zone import Zone
from app.schemas.zone import ZoneCreate, ZoneResponse, ZoneUpdate
from app.ingestion.manager import ingestion_manager

router = APIRouter()

@router.post("", response_model=ZoneResponse, status_code=status.HTTP_201_CREATED)
async def create_zone(zone_in: ZoneCreate, db: Session = Depends(get_db)):
    existing = db.query(Zone).filter(Zone.id == zone_in.id).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Zone with ID '{zone_in.id}' already exists"
        )
    db_zone = Zone(**zone_in.model_dump())
    db.add(db_zone)
    db.commit()
    db.refresh(db_zone)

    # If camera has an active worker, notify it to reload zones
    if db_zone.camera_id:
        worker = ingestion_manager.get_worker(db_zone.camera_id)
        if worker:
            await worker.reload_zones()

    return db_zone

@router.get("", response_model=List[ZoneResponse])
def list_zones(
    camera_id: Optional[str] = Query(None, description="Filter zones by camera_id"),
    db: Session = Depends(get_db)
):
    query = db.query(Zone)
    if camera_id:
        query = query.filter(Zone.camera_id == camera_id)
    return query.all()

@router.get("/{zone_id}", response_model=ZoneResponse)
def get_zone(zone_id: str, db: Session = Depends(get_db)):
    zone = db.query(Zone).filter(Zone.id == zone_id).first()
    if not zone:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Zone '{zone_id}' not found"
        )
    return zone

@router.put("/{zone_id}", response_model=ZoneResponse)
async def update_zone(zone_id: str, zone_update: ZoneUpdate, db: Session = Depends(get_db)):
    zone = db.query(Zone).filter(Zone.id == zone_id).first()
    if not zone:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Zone '{zone_id}' not found"
        )
    update_data = zone_update.model_dump(exclude_unset=True)
    for field, val in update_data.items():
        setattr(zone, field, val)
    db.commit()
    db.refresh(zone)

    if zone.camera_id:
        worker = ingestion_manager.get_worker(zone.camera_id)
        if worker:
            await worker.reload_zones()

    return zone

@router.delete("/{zone_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_zone(zone_id: str, db: Session = Depends(get_db)):
    zone = db.query(Zone).filter(Zone.id == zone_id).first()
    if not zone:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Zone '{zone_id}' not found"
        )
    camera_id = zone.camera_id
    db.delete(zone)
    db.commit()

    if camera_id:
        worker = ingestion_manager.get_worker(camera_id)
        if worker:
            await worker.reload_zones()

    return Response(status_code=status.HTTP_204_NO_CONTENT)
