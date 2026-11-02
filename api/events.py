"""
SSE (Server-Sent Events) progress broker.
Workers push progress to Redis pub/sub; API streams it to clients.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from typing import AsyncGenerator

import redis.asyncio as aioredis

from api.config import get_settings

_settings = get_settings()


def _channel(project_id: uuid.UUID) -> str:
    return f"v2r:progress:{project_id}"


async def publish_progress(
    project_id: uuid.UUID,
    stage: str,
    progress: int,
    message: str = "",
    **extra,
) -> None:
    """Push a progress event from a worker (sync-friendly wrapper also below)."""
    r = aioredis.from_url(_settings.redis_url)
    payload = json.dumps({"stage": stage, "progress": progress, "message": message, **extra})
    await r.publish(_channel(project_id), payload)
    await r.aclose()


def publish_progress_sync(
    project_id: str | uuid.UUID,
    stage: str,
    progress: int,
    message: str = "",
    **extra,
) -> None:
    """Sync version called from Celery workers (uses blocking redis)."""
    import redis as syncredis
    r = syncredis.from_url(_settings.redis_url)
    payload = json.dumps({"stage": stage, "progress": progress, "message": message, **extra})
    r.publish(_channel(uuid.UUID(str(project_id))), payload)
    r.close()


async def event_stream(project_id: uuid.UUID) -> AsyncGenerator[str, None]:
    """
    Async generator that subscribes to a project's Redis channel and
    yields SSE-formatted strings to the FastAPI endpoint.
    """
    r = aioredis.from_url(_settings.redis_url)
    pubsub = r.pubsub()
    await pubsub.subscribe(_channel(project_id))

    try:
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue
            data: str = message["data"]
            if isinstance(data, bytes):
                data = data.decode()
            yield f"data: {data}\n\n"
            # Stop streaming once pipeline is done or failed
            parsed = json.loads(data)
            if parsed.get("stage") in ("done", "failed"):
                break
    finally:
        await pubsub.unsubscribe(_channel(project_id))
        await r.aclose()
