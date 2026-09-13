from sqlalchemy.orm import Session
from app.db.session import engine, Base
from app.models import Camera, Zone, Event  # Ensure all models are registered

def init_db():
    Base.metadata.create_all(bind=engine)

if __name__ == "__main__":
    init_db()
    print("Database tables initialized successfully.")
