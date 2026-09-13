from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, ConfigDict, field_validator

class ZoneBase(BaseModel):
    camera_id: Optional[str] = None
    name: str
    zone_type: str = "POLYGON"  # "POLYGON" or "LINE"
    polygon_coords: List[List[float]]  # list of [x, y] normalized coordinates (0.0 - 1.0)
    restriction_level: str = "RESTRICTED"  # "RESTRICTED" or "MONITORED"
    dwell_threshold_seconds: float = 5.0
    rules: Optional[Dict[str, Any]] = None

    @field_validator("polygon_coords")
    @classmethod
    def validate_coords(cls, v: List[List[float]], info) -> List[List[float]]:
        if not v or len(v) < 3:
            raise ValueError("polygon_coords must contain at least 3 points for a valid polygon")
        for pt in v:
            if len(pt) != 2:
                raise ValueError(f"Each coordinate point must have [x, y], got {pt}")
            x, y = pt[0], pt[1]
            if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
                raise ValueError(f"Coordinates must be normalized between 0.0 and 1.0, got ({x}, {y})")
        return v

    @field_validator("restriction_level")
    @classmethod
    def validate_restriction_level(cls, v: str) -> str:
        v_upper = v.upper()
        if v_upper not in ("RESTRICTED", "MONITORED"):
            raise ValueError("restriction_level must be either 'RESTRICTED' or 'MONITORED'")
        return v_upper

    @field_validator("zone_type")
    @classmethod
    def validate_zone_type(cls, v: str) -> str:
        v_upper = v.upper()
        if v_upper not in ("POLYGON", "LINE"):
            raise ValueError("zone_type must be either 'POLYGON' or 'LINE'")
        return v_upper

class ZoneCreate(ZoneBase):
    id: str

class ZoneUpdate(BaseModel):
    camera_id: Optional[str] = None
    name: Optional[str] = None
    zone_type: Optional[str] = None
    polygon_coords: Optional[List[List[float]]] = None
    restriction_level: Optional[str] = None
    dwell_threshold_seconds: Optional[float] = None
    rules: Optional[Dict[str, Any]] = None

class ZoneResponse(ZoneBase):
    id: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
