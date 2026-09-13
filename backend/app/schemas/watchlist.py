import re
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, field_validator


class WatchlistBase(BaseModel):
    type: str = "PLATE"  # "PLATE" or "FACE"
    reference_value: str  # e.g., "KA05NB4912"
    list_type: str = "BLACKLIST"  # "BLACKLIST" or "WHITELIST"
    added_by: Optional[str] = "System"
    notes: Optional[str] = None

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        v_upper = v.upper().strip()
        if v_upper not in ("PLATE", "FACE"):
            raise ValueError("type must be either 'PLATE' or 'FACE'")
        return v_upper

    @field_validator("list_type")
    @classmethod
    def validate_list_type(cls, v: str) -> str:
        v_upper = v.upper().strip()
        if v_upper not in ("BLACKLIST", "WHITELIST"):
            raise ValueError("list_type must be either 'BLACKLIST' or 'WHITELIST'")
        return v_upper

    @field_validator("reference_value")
    @classmethod
    def normalize_reference_value(cls, v: str) -> str:
        # Strip all whitespace, hyphens, and convert to uppercase
        clean = re.sub(r"[\s\-_]+", "", v).upper()
        if not clean:
            raise ValueError("reference_value cannot be empty")
        return clean


class WatchlistCreate(WatchlistBase):
    id: Optional[str] = None


class WatchlistResponse(WatchlistBase):
    id: str
    added_at: datetime

    model_config = ConfigDict(from_attributes=True)
