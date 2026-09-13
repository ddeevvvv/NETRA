from datetime import datetime, timezone
from sqlalchemy import Column, String, Float, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
from app.db.session import Base

class Zone(Base):
    __tablename__ = "zones"

    id = Column(String, primary_key=True, index=True)  # e.g., "Z-01"
    camera_id = Column(String, ForeignKey("cameras.id", ondelete="CASCADE"), nullable=True)
    name = Column(String, nullable=False)
    zone_type = Column(String, default="POLYGON", nullable=True)  # "POLYGON" or "LINE"
    polygon_coords = Column(JSON, nullable=True)  # e.g., [[x1, y1], [x2, y2], ...] (normalized 0.0-1.0)
    restriction_level = Column(String, default="RESTRICTED", nullable=True)  # "RESTRICTED" or "MONITORED"
    dwell_threshold_seconds = Column(Float, default=5.0, nullable=True)
    rules = Column(JSON, nullable=True)  # extra metadata / overrides
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    camera = relationship("Camera", back_populates="zones")
    events = relationship("Event", back_populates="zone")
