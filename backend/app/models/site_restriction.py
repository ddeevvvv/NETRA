import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Boolean, DateTime, JSON
from app.db.session import Base

def generate_uuid():
    return str(uuid.uuid4())

class SiteRestriction(Base):
    __tablename__ = "site_restrictions"

    id = Column(String, primary_key=True, default=generate_uuid, index=True)
    site_id = Column(String, nullable=False, index=True)  # e.g., "BOP-01"
    name = Column(String, nullable=True)  # e.g., "BOP-01 Perimeter Zone"
    restriction_level = Column(String, default="HIGH", nullable=False)  # "HIGH", "CRITICAL", "WARNING"
    polygon_geojson = Column(JSON, nullable=False)  # GeoJSON Geometry or coordinates array
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
