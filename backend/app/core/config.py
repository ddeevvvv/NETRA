import os
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    PROJECT_NAME: str = "IBVAP - Intelligent Border Video Analytics Platform"
    API_V1_STR: str = "/api/v1"
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "sqlite:///./ibvap.db"
    )
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    REDIS_ALERTS_CHANNEL: str = os.getenv("REDIS_ALERTS_CHANNEL", "ibvap:alerts")
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")


    model_config = SettingsConfigDict(case_sensitive=True)

settings = Settings()

