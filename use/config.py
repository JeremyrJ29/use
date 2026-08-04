from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Postgres
    database_url: str = "postgresql+asyncpg://use:use_dev@localhost:5432/use"
    postgres_sync_url: str = "postgresql://use:use_dev@localhost:5432/use"

    # Neo4j
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "use_dev_neo4j"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # NATS
    nats_url: str = "nats://localhost:4222"

    # MinIO
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "use"
    minio_secret_key: str = "use_dev_minio"
    minio_secure: bool = False
    minio_raw_bucket: str = "use-raw"

    # Auth
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expiry_minutes: int = 30

    # App
    log_level: str = "INFO"
    environment: str = "development"


@lru_cache
def get_settings() -> Settings:
    return Settings()
