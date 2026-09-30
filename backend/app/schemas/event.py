from datetime import datetime
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field, ConfigDict

class EvidenceSchema(BaseModel):
    snapshot_uri: Optional[str] = None
    clip_uri: Optional[str] = None

    model_config = ConfigDict(extra="allow")

class EventCreate(BaseModel):
    camera_id: str = Field(..., json_schema_extra={"example": "CAM-07"})
    type: str = Field(..., json_schema_extra={"example": "INTRUSION"})
    severity: str = Field(..., json_schema_extra={"example": "CRITICAL"})
    timestamp: datetime = Field(..., json_schema_extra={"example": "2026-09-11T12:52:03Z"})
    object_type: str = Field(..., json_schema_extra={"example": "person"})
    track_id: Optional[int] = Field(None, json_schema_extra={"example": 17})
    confidence: float = Field(..., ge=0.0, le=1.0, json_schema_extra={"example": 0.94})
    zone_id: Optional[str] = Field(None, json_schema_extra={"example": "Z-01"})
    evidence: Dict[str, Any] = Field(
        default_factory=dict,
        json_schema_extra={"example": {"snapshot_uri": "http://storage/snap.jpg", "clip_uri": "http://storage/clip.mp4"}}
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        json_schema_extra={"example": {"direction": "NORTHBOUND"}}
    )

    model_config = ConfigDict(extra="allow")

class EventResponse(BaseModel):
    id: str
    camera_id: Optional[str] = None
    type: str
    severity: str
    timestamp: datetime
    object_type: str
    track_id: Optional[int] = None
    confidence: float
    zone_id: Optional[str] = None
    evidence: Dict[str, Any]
    metadata: Dict[str, Any] = Field(default_factory=dict, validation_alias="event_metadata", serialization_alias="metadata")

    acknowledged: bool = False
    acknowledged_at: Optional[datetime] = None
    acknowledged_by: Optional[str] = None
    requires_acknowledgment: bool = True
    created_at: datetime

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

class EventAcknowledge(BaseModel):
    acknowledged_by: str = Field(..., json_schema_extra={"example": "Operator-01"})
