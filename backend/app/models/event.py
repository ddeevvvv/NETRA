import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Float, Integer, DateTime, Boolean, ForeignKey, JSON
from sqlalchemy.orm import relationship
from app.db.session import Base

def generate_uuid():
    return str(uuid.uuid4())

class Event(Base):
    __tablename__ = "events"

    id = Column(String, primary_key=True, default=generate_uuid, index=True)
    camera_id = Column(String, ForeignKey("cameras.id", ondelete="SET NULL"), nullable=True, index=True)
    type = Column(String, nullable=False, index=True)  # INTRUSION, ANPR, FACE, etc.
    severity = Column(String, nullable=False, index=True)  # LOW, MEDIUM, HIGH, CRITICAL
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    object_type = Column(String, nullable=False)  # person, vehicle, etc.
    track_id = Column(Integer, nullable=True)
    confidence = Column(Float, nullable=False)
    zone_id = Column(String, ForeignKey("zones.id", ondelete="SET NULL"), nullable=True, index=True)
    evidence = Column(JSON, nullable=False, default=dict)
    event_metadata = Column(JSON, nullable=False, default=dict)

    # Human-in-the-loop acknowledgment fields (Design principle)
    requires_acknowledgment = Column(Boolean, default=True, nullable=False, index=True)
    acknowledged = Column(Boolean, default=False, nullable=False)
    acknowledged_at = Column(DateTime(timezone=True), nullable=True)
    acknowledged_by = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    camera = relationship("Camera", back_populates="events")
    zone = relationship("Zone", back_populates="events")
