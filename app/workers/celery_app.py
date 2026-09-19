"""Celery application instance configuration."""
from __future__ import annotations

from celery import Celery

from app.config import settings

celery_app = Celery(
    "question_extraction",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    # Serialization
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",

    # Timezone
    timezone="UTC",
    enable_utc=True,

    # Task behavior
    task_acks_late=True,           # Acknowledge after task completes (safer)
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,  # One task at a time per worker (memory-intensive)

    # Result TTL
    result_expires=86400,          # 24 hours

    # Routing
    task_routes={
        "app.workers.tasks.process_document_task": {"queue": "documents"},
    },
    task_default_queue="documents",
)
