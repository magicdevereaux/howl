from celery import Celery
from celery.schedules import crontab

from app.config import settings

celery_app = Celery(
    "howl",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "app.tasks.avatar",
        "app.tasks.auto_match",
        "app.tasks.notify",
        "app.tasks.bot_response",
    ],
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

# Celery Beat schedule — run the bot response task every 15 minutes.
# Start the scheduler alongside the worker:
#   celery -A app.celery_app beat --loglevel=info
celery_app.conf.beat_schedule = {
    "bot-response-every-15-min": {
        "task": "app.tasks.bot_response.process_bot_responses",
        "schedule": 900.0,  # seconds
    },
}
