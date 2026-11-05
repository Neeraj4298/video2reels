"""
video2reels FastAPI application entry point.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.config import get_settings
from api.db import engine, Base
from api.routers import projects, clips, uploads, brand_kits
from api.schemas import HealthResponse

_settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialise resources on startup:
    1. Create DB tables (Alembic handles schema migrations in production).
    2. Ensure MinIO buckets exist so workers can upload/download immediately.
    """
    # ── Database ──────────────────────────────────────────────────────────────
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except Exception:
        # Silently ignore during unit tests or when DB isn't yet available
        pass

    # ── MinIO bucket bootstrap ────────────────────────────────────────────────
    try:
        from api.storage import _is_minio_reachable
        if _is_minio_reachable():
            import minio as _minio
            _s = get_settings()
            _client = _minio.Minio(
                _s.minio_endpoint,
                access_key=_s.minio_access_key,
                secret_key=_s.minio_secret_key,
                secure=False,
            )
            for _bucket in [
                _s.bucket_originals,
                _s.bucket_audio,
                _s.bucket_clips,
                _s.bucket_renders,
            ]:
                if not _client.bucket_exists(_bucket):
                    _client.make_bucket(_bucket)
    except Exception:
        # MinIO may not be running in test/dev environments — skip silently
        pass

    # Add already-rendered clips from output/yt_XUWQJ2Kj2k8 if local DB is empty so user can also inspect clips immediately
    yield

    # ── Cleanup ───────────────────────────────────────────────────────────────
    try:
        await engine.dispose()
    except Exception:
        pass


app = FastAPI(
    title=_settings.api_title,
    version=_settings.api_version,
    description=(
        "video2reels API — turn long-form videos into viral short-form clips. "
        "Upload a video or paste a URL; get scored, captioned, vertical MP4 clips back."
    ),
    lifespan=lifespan,
)

# ── CORS ──────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:3001",
        "http://localhost:80",
        "http://localhost",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(projects.router)
app.include_router(clips.router)
app.include_router(uploads.router)
app.include_router(brand_kits.router)


# ── Health check ──────────────────────────────────────────────────────────────
@app.get("/health", response_model=HealthResponse, tags=["meta"])
async def health():
    return HealthResponse(version=_settings.api_version)


# ── OpenAPI tag ordering ──────────────────────────────────────────────────────
app.openapi_tags = [
    {"name": "projects", "description": "Project lifecycle management"},
    {"name": "clips",    "description": "Clip review, trimming, re-render"},
    {"name": "uploads",  "description": "Direct upload presigned URLs"},
    {"name": "brand-kits", "description": "Brand kit management"},
    {"name": "meta",     "description": "Health check"},
]
