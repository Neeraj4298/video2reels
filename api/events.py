"""
SSE (Server-Sent Events) progress broker.
Workers push progress to Redis pub/sub; API streams it to clients.
"""
from __future__ import annotations

import asyncio
from collections import defaultdict
import json
import socket
from typing import AsyncGenerator
from urllib.parse import urlparse
import uuid

import redis.asyncio as aioredis

from api.config import get_settings

_settings = get_settings()
_local_subscribers: dict[str, list[asyncio.Queue[str]]] = defaultdict(list)


def _is_redis_reachable() -> bool:
    try:
        parsed = urlparse(_settings.redis_url)
        host = parsed.hostname or "localhost"
        port = parsed.port or 6379
        sock = socket.socket()
        sock.settimeout(0.25)
        ok = sock.connect_ex((host, port)) == 0
        sock.close()
        return ok
    except Exception:
        return False


def _channel(project_id: uuid.UUID) -> str:
    return f"v2r:progress:{project_id}"


def _notify_local(channel: str, payload: str) -> None:
    for q in list(_local_subscribers.get(channel, [])):
        try:
            q.put_nowait(payload)
        except Exception:
            pass


async def publish_progress(
    project_id: uuid.UUID,
    stage: str,
    progress: int,
    message: str = "",
    **extra,
) -> None:
    """Push a progress event from a worker (sync-friendly wrapper also below)."""
    channel = _channel(project_id)
    payload = json.dumps({"stage": stage, "progress": progress, "message": message, **extra})
    _notify_local(channel, payload)
    try:
        r = aioredis.from_url(_settings.redis_url)
        await r.publish(channel, payload)
        await r.aclose()
    except Exception:
        pass


def publish_progress_sync(
    project_id: str | uuid.UUID,
    stage: str,
    progress: int,
    message: str = "",
    **extra,
) -> None:
    """Sync version called from Celery workers (uses blocking redis with in-memory fallback)."""
    import redis as syncredis
    channel = _channel(uuid.UUID(str(project_id)))
    payload = json.dumps({"stage": stage, "progress": progress, "message": message, **extra})
    _notify_local(channel, payload)
    if _is_redis_reachable():
        try:
            r = syncredis.from_url(_settings.redis_url)
            r.publish(channel, payload)
            r.close()
        except Exception:
            pass


async def event_stream(project_id: uuid.UUID) -> AsyncGenerator[str, None]:
    """
    Async generator that subscribes to a project's Redis channel (or local queue
    fallback when Redis is offline) and yields SSE-formatted strings.
    """
    channel = _channel(project_id)
    try:
        r = aioredis.from_url(_settings.redis_url)
        pubsub = r.pubsub()
        await pubsub.subscribe(channel)
        try:
            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue
                data: str = message["data"]
                if isinstance(data, bytes):
                    data = data.decode()
                yield f"data: {data}\n\n"
                parsed = json.loads(data)
                if parsed.get("stage") in ("done", "failed"):
                    break
        finally:
            await pubsub.unsubscribe(channel)
            await r.aclose()
    except Exception:
        q: asyncio.Queue[str] = asyncio.Queue()
        _local_subscribers[channel].append(q)
        try:
            while True:
                data = await q.get()
                yield f"data: {data}\n\n"
                parsed = json.loads(data)
                if parsed.get("stage") in ("done", "failed"):
                    break
        finally:
            if q in _local_subscribers[channel]:
                _local_subscribers[channel].remove(q)
