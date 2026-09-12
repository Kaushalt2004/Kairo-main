import json
from typing import List, Union
from pydantic import AnyHttpUrl, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "Kairo Cloud"
    API_V1_STR: str = "/api/v1"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    LOG_LEVEL: str = "INFO"

    # Security
    SECRET_KEY: str = "kairo-insecure-dev-secret-key-change-in-production-987654321"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 hours
    ALGORITHM: str = "HS256"

    # PostgreSQL
    POSTGRES_SERVER: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "kairo"
    POSTGRES_PASSWORD: str = "kairo_password"
    POSTGRES_DB: str = "kairo_db"
    DATABASE_URL: str = "postgresql+asyncpg://kairo:kairo_password@localhost:5432/kairo_db"

    # Redis
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str = ""
    REDIS_URL: str = "redis://localhost:6379/0"

    # CORS
    CORS_ORIGINS: Union[List[str], str] = ["*"]

    # Ingestion & Heartbeat Settings
    TELEMETRY_SAMPLE_RATE_HZ: int = 10
    DB_PERSIST_INTERVAL_SECONDS: float = 1.0
    VEHICLE_OFFLINE_THRESHOLD_SECONDS: float = 10.0

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> List[str]:
        if isinstance(v, str):
            if v.startswith("[") and v.endswith("]"):
                try:
                    return json.loads(v)
                except Exception:
                    pass
            return [i.strip() for i in v.split(",") if i.strip()]
        elif isinstance(v, list):
            return v
        return ["*"]

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="allow"
    )


settings = Settings()
