from fastapi import APIRouter
from app.api.v1.endpoints import events, cameras, zones, watchlist, vehicles, sites

api_router = APIRouter()
api_router.include_router(events.router, prefix="/events", tags=["events"])
api_router.include_router(cameras.router, prefix="/cameras", tags=["cameras"])
api_router.include_router(zones.router, prefix="/zones", tags=["zones"])
api_router.include_router(watchlist.router, prefix="/watchlist", tags=["watchlist"])
api_router.include_router(vehicles.router, prefix="/vehicles", tags=["vehicles"])
api_router.include_router(sites.router, prefix="/sites", tags=["sites"])

