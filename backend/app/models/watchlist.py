import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime
from app.db.session import Base


class WatchlistEntry(Base):
    __tablename__ = "watchlist_entries"

    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    type = Column(String, nullable=False, default="PLATE", index=True)  # "PLATE" or "FACE"
    reference_value = Column(String, nullable=False, index=True)  # e.g., "KA05NB4912"
    list_type = Column(String, nullable=False, default="BLACKLIST", index=True)  # "BLACKLIST" or "WHITELIST"
    added_by = Column(String, nullable=True, default="System")
    added_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    notes = Column(String, nullable=True)
