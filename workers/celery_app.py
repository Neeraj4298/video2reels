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
import sys
from pathlib import Path
from celery import Celery
from celery.signals import worker_ready
from kombu import Exchange, Queue

# Ensure project root (/app) and local .venv site-packages are on sys.path in all worker processes
_ROOT_PATH = Path(__file__).resolve().parent.parent
_ROOT_DIR = str(_ROOT_PATH)
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)
for _sp in sorted((_ROOT_PATH / ".venv" / "lib").glob("python*/site-packages")):
    if _sp.is_dir() and str(_sp) not in sys.path:
        sys.path.insert(1, str(_sp))
for _b in (str(_ROOT_PATH / ".venv" / "bin"), str(_ROOT_PATH / "bin")):
    if Path(_b).is_dir() and _b not in os.environ.get("PATH", "").split(os.pathsep):
        os.environ["PATH"] = f"{_b}{os.pathsep}{os.environ.get('PATH', '')}"

# ── Build broker + backend URLs ───────────────────────────────────────────────
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
# Primary queue for heavy stages is 'gpu'; CPU worker acts as automatic fallback consumer
GPU_QUEUE = os.getenv("GPU_QUEUE", "gpu")

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

# Route GPU-heavy tasks explicitly (defaults to 'cpu' unless GPU_QUEUE=gpu is set)
celery_app.conf.task_routes = {
    "workers.tasks.stage_transcribe":     {"queue": GPU_QUEUE},
    "workers.tasks.stage_reframe":        {"queue": GPU_QUEUE},
    "workers.tasks.stage_render_all":     {"queue": GPU_QUEUE},
    "workers.tasks.stage_render_clip":    {"queue": GPU_QUEUE},
    "workers.tasks.render_clip":          {"queue": GPU_QUEUE},
}

# ── Reliability ───────────────────────────────────────────────────────────────
celery_app.conf.task_acks_late = True          # re-queue on worker crash
celery_app.conf.task_reject_on_worker_lost = True
celery_app.conf.worker_prefetch_multiplier = 1  # one task at a time per worker slot
celery_app.conf.broker_connection_timeout = 0.5
celery_app.conf.broker_transport_options = {
    "max_retries": 1,
    "interval_start": 0,
    "interval_step": 0.2,
    "interval_max": 0.2,
    "socket_connect_timeout": 0.5,
}

# ── Retries ───────────────────────────────────────────────────────────────────
celery_app.conf.task_max_retries = 3
# Individual tasks call self.retry(countdown=...) for exponential backoff.
# Backoff schedule: attempt 1 → 60s, attempt 2 → 300s, attempt 3 → 900s

# ── Result expiry ─────────────────────────────────────────────────────────────
celery_app.conf.result_expires = 86400  # 24 hours

# ── Worker settings ───────────────────────────────────────────────────────────
celery_app.conf.worker_max_tasks_per_child = 50  # recycle worker after 50 tasks (memory safety)


@worker_ready.connect
def _ensure_gpu_queue_fallback(sender=None, **kwargs):
    """
    GPU is the primary queue for transcription, reframing, and rendering.
    When running on a dev machine without a dedicated worker-gpu container,
    ensure the CPU worker also consumes the 'gpu' queue as fallback.
    """
    try:
        if sender and hasattr(sender, "app"):
            sender.app.control.add_consumer(
                "gpu",
                destination=[sender.hostname],
            )
    except Exception:
        pass

