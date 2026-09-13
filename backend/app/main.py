import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.db.session import engine, Base
from app.models import Camera, Zone, Event  # Ensure models loaded
from app.api.v1.router import api_router
from app.api.v1.endpoints import health, ws
from app.core.websocket_manager import redis_subscriber_loop
from app.ingestion.manager import ingestion_manager

from sqlalchemy import text
from app.db.session import SessionLocal

def ensure_schema_and_seeds():
    Base.metadata.create_all(bind=engine)
    # Check and add new columns to PostgreSQL if needed
    with engine.connect() as conn:
        try:
            conn.execute(text("ALTER TABLE zones ADD COLUMN IF NOT EXISTS zone_type VARCHAR DEFAULT 'POLYGON'"))
            conn.execute(text("ALTER TABLE zones ADD COLUMN IF NOT EXISTS restriction_level VARCHAR DEFAULT 'RESTRICTED'"))
            conn.execute(text("ALTER TABLE zones ADD COLUMN IF NOT EXISTS dwell_threshold_seconds FLOAT DEFAULT 5.0"))
            conn.commit()
        except Exception:
            pass

    # Auto-seed test zone Z-01 if CAM-TEST-01 exists and Z-01 does not exist
    db = SessionLocal()
    try:
        existing_zone = db.query(Zone).filter(Zone.id == "Z-01").first()
        if not existing_zone:
            z01 = Zone(
                id="Z-01",
                camera_id="CAM-TEST-01",
                name="Restricted Sector Alpha",
                zone_type="POLYGON",
                polygon_coords=[
                    [0.45, 0.10],
                    [0.95, 0.10],
                    [0.95, 0.90],
                    [0.45, 0.90]
                ],
                restriction_level="RESTRICTED",
                dwell_threshold_seconds=5.0,
                rules={"virtual_fence": True, "min_confidence": 0.5}
            )
            db.add(z01)
            db.commit()

        # Auto-seed sample watchlist entries
        from app.models.watchlist import WatchlistEntry
        if db.query(WatchlistEntry).count() == 0:
            samples = [
                WatchlistEntry(
                    id="WL-01",
                    type="PLATE",
                    reference_value="KA05NB4912",
                    list_type="BLACKLIST",
                    added_by="Officer-Singh",
                    notes="Stolen White Scorpio — BOLO #1042"
                ),
                WatchlistEntry(
                    id="WL-02",
                    type="PLATE",
                    reference_value="DL01AB1234",
                    list_type="BLACKLIST",
                    added_by="HQ-Intel",
                    notes="Suspect Vehicle — Border Sector 3 Alert"
                ),
                WatchlistEntry(
                    id="WL-03",
                    type="PLATE",
                    reference_value="HR26DQ5551",
                    list_type="WHITELIST",
                    added_by="Admin",
                    notes="Authorized Border Patrol Escort Unit"
                ),
            ]
            db.add_all(samples)
            db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Initialize database tables & schema
    ensure_schema_and_seeds()
    # 2. Start background Redis subscriber loop
    redis_task = asyncio.create_task(redis_subscriber_loop())
    # 3. Initial camera ingestion sync from DB
    asyncio.create_task(ingestion_manager.sync_cameras_from_db())
    yield
    # 4. Clean up on shutdown
    redis_task.cancel()
    try:
        await redis_task
    except asyncio.CancelledError:
        pass

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount health check & WebSocket endpoints at root level
app.include_router(health.router, tags=["health"])
app.include_router(ws.router, tags=["websocket"])

# Mount API v1 router
app.include_router(api_router, prefix=settings.API_V1_STR)

@app.get("/")
def root():
    return {
        "name": settings.PROJECT_NAME,
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health",
        "websocket": "/ws/alerts"
    }
