"""
SQLAlchemy async engine + session factory.
Import `AsyncSession` from here for DB access.
"""
from __future__ import annotations
from pathlib import Path
import socket
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from api.config import get_settings


class Base(DeclarativeBase):
    """Declarative base — all ORM models inherit from this."""
    pass


def _resolve_database_url(configured_url: str) -> str:
    """
    Use PostgreSQL primarily; if localhost:5432 is configured but not running on
    the development machine, fall back automatically to local SQLite.
    """
    if "localhost:5432" in configured_url or "127.0.0.1:5432" in configured_url:
        sock = socket.socket()
        sock.settimeout(0.3)
        is_open = sock.connect_ex(("127.0.0.1", 5432)) == 0
        sock.close()
        if not is_open:
            db_path = Path(__file__).resolve().parent.parent / "work" / "video2reels_local.db"
            db_path.parent.mkdir(parents=True, exist_ok=True)
            return f"sqlite+aiosqlite:///{db_path}"
    return configured_url


settings = get_settings()
_effective_db_url = _resolve_database_url(settings.database_url)

try:
    if _effective_db_url.startswith("sqlite"):
        engine = create_async_engine(
            _effective_db_url,
            echo=settings.debug,
            connect_args={"check_same_thread": False},
        )
    else:
        engine = create_async_engine(
            _effective_db_url,
            echo=settings.debug,
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True,
        )
    AsyncSessionLocal = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )
except ModuleNotFoundError:
    # Sync Celery workers without asyncpg only import `Base` from `api.db`
    engine = None  # type: ignore[assignment]
    AsyncSessionLocal = None  # type: ignore[assignment]


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: yields a DB session and handles cleanup."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
