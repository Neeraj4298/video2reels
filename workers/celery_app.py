"""
Celery application configuration.
Defines two queues:
  - cpu  : ingest, audio extraction, clip selection, caption generation
  - gpu  : transcription (Whisper), reframing, FFmpeg rendering

All tasks have:
  - max_retries = 3
  - exponential backoff: 60s → 300s → 900s
  - acks_late = True (task stays in queue if worker crashes mid-task)
"""
from __future__ import annotations

import os
from celery import Celery
from kombu import Exchange, Queue

# ── Build broker + backend URLs ───────────────────────────────────────────────
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "video2reels",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["workers.tasks"],
)

# ── Serialization ─────────────────────────────────────────────────────────────
celery_app.conf.task_serializer = "json"
celery_app.conf.result_serializer = "json"
celery_app.conf.accept_content = ["json"]
celery_app.conf.timezone = "UTC"
celery_app.conf.enable_utc = True

# ── Queues ────────────────────────────────────────────────────────────────────
default_exchange = Exchange("default", type="direct")
celery_app.conf.task_queues = (
    Queue("cpu", default_exchange, routing_key="cpu"),
    Queue("gpu", default_exchange, routing_key="gpu"),
)
celery_app.conf.task_default_queue = "cpu"
celery_app.conf.task_default_exchange = "default"
celery_app.conf.task_default_routing_key = "cpu"

# Route GPU-heavy tasks explicitly
celery_app.conf.task_routes = {
    "workers.tasks.stage_transcribe":     {"queue": "gpu"},
    "workers.tasks.stage_reframe":        {"queue": "gpu"},
    "workers.tasks.stage_render_clip":    {"queue": "gpu"},
    "workers.tasks.render_clip":          {"queue": "gpu"},
}

# ── Reliability ───────────────────────────────────────────────────────────────
celery_app.conf.task_acks_late = True          # re-queue on worker crash
celery_app.conf.task_reject_on_worker_lost = True
celery_app.conf.worker_prefetch_multiplier = 1  # one task at a time per worker slot

# ── Retries ───────────────────────────────────────────────────────────────────
celery_app.conf.task_max_retries = 3
# Individual tasks call self.retry(countdown=...) for exponential backoff.
# Backoff schedule: attempt 1 → 60s, attempt 2 → 300s, attempt 3 → 900s

# ── Result expiry ─────────────────────────────────────────────────────────────
celery_app.conf.result_expires = 86400  # 24 hours

# ── Worker settings ───────────────────────────────────────────────────────────
celery_app.conf.worker_max_tasks_per_child = 50  # recycle worker after 50 tasks (memory safety)
