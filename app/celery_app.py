from celery import Celery

from app.config import settings

celery_app = Celery(
    "howl",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.tasks.avatar"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    # Re-queue task if the worker dies mid-execution
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)
