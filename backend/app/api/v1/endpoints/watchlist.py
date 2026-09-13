import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models.watchlist import WatchlistEntry
from app.schemas.watchlist import WatchlistCreate, WatchlistResponse

router = APIRouter()


@router.post("", response_model=WatchlistResponse, status_code=status.HTTP_201_CREATED)
def create_watchlist_entry(entry_in: WatchlistCreate, db: Session = Depends(get_db)):
    # Check if duplicate entry with same type, reference_value and list_type exists
    existing = db.query(WatchlistEntry).filter(
        WatchlistEntry.type == entry_in.type,
        WatchlistEntry.reference_value == entry_in.reference_value,
        WatchlistEntry.list_type == entry_in.list_type
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Watchlist entry for {entry_in.type} '{entry_in.reference_value}' in {entry_in.list_type} already exists"
        )

    entry_data = entry_in.model_dump()
    if not entry_data.get("id"):
        entry_data["id"] = str(uuid.uuid4())

    db_entry = WatchlistEntry(**entry_data)
    db.add(db_entry)
    db.commit()
    db.refresh(db_entry)
    return db_entry


@router.get("", response_model=List[WatchlistResponse])
def list_watchlist_entries(
    type: Optional[str] = Query(None, description="Filter by entry type (PLATE, FACE)"),
    list_type: Optional[str] = Query(None, description="Filter by list type (BLACKLIST, WHITELIST)"),
    reference_value: Optional[str] = Query(None, description="Filter by reference value"),
    db: Session = Depends(get_db)
):
    query = db.query(WatchlistEntry)
    if type:
        query = query.filter(WatchlistEntry.type == type.upper())
    if list_type:
        query = query.filter(WatchlistEntry.list_type == list_type.upper())
    if reference_value:
        query = query.filter(WatchlistEntry.reference_value == reference_value.upper())
    return query.order_by(WatchlistEntry.added_at.desc()).all()


@router.get("/{entry_id}", response_model=WatchlistResponse)
def get_watchlist_entry(entry_id: str, db: Session = Depends(get_db)):
    entry = db.query(WatchlistEntry).filter(WatchlistEntry.id == entry_id).first()
    if not entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Watchlist entry '{entry_id}' not found"
        )
    return entry


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_watchlist_entry(entry_id: str, db: Session = Depends(get_db)):
    entry = db.query(WatchlistEntry).filter(WatchlistEntry.id == entry_id).first()
    if not entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Watchlist entry '{entry_id}' not found"
        )
    db.delete(entry)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
