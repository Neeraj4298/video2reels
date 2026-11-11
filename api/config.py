"""
video2reels — API Layer Config
Reads settings from env vars (populated by docker-compose or .env).
"""
from __future__ import annotations
import os
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ── Database ──────────────────────────────────────────────────────────────
    database_url: str = "postgresql+asyncpg://video2reels:video2reels@localhost:5432/video2reels"

    # ── Redis / Celery ────────────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"

    # ── Object Storage (MinIO / S3) ───────────────────────────────────────────
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_secure: bool = False

    # Bucket names
    bucket_originals: str = "video2reels-originals"
    bucket_audio: str = "video2reels-audio"
    bucket_clips: str = "video2reels-clips"
    bucket_renders: str = "video2reels-renders"

    # ── LLM ───────────────────────────────────────────────────────────────────
    gemini_api_key: str = ""
    anthropic_api_key: str = ""
    llm_provider: str = "gemini"

    # ── Pipeline ──────────────────────────────────────────────────────────────
    clip_min_duration: int = 20
    clip_max_duration: int = 90
    top_n_clips: int = 10
    max_video_hours: float = 3.0

    # ── API ───────────────────────────────────────────────────────────────────
    api_title: str = "video2reels API"
    api_version: str = "2.1.0"
    debug: bool = False
    allow_local_storage_routes: bool = True

    # Signed URL expiry (seconds)
    presigned_url_ttl: int = 3600



@lru_cache
def get_settings() -> Settings:
    return Settings()
