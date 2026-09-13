from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict

class CameraCreate(BaseModel):
    id: str
    name: str
    rtsp_url: str
    location: Optional[str] = None
    status: Optional[str] = "ONLINE"

class CameraResponse(CameraCreate):
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
