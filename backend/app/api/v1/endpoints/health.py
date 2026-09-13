from datetime import datetime, timezone
from fastapi import APIRouter

router = APIRouter()

@router.get("/health")
def health_check():
    return {
        "status": "healthy",
        "service": "IBVAP Video Analytics Middleware",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
