from celery import Celery

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
    # ------------------------------------------------------------------
    # Bounded failure when Redis is unreachable.
    #
    # Enqueueing happens inside request handlers, after the write has been
    # committed (see app/services/task_queue.py).  With the defaults, a dead
    # broker made `.delay()` block for a measured 108.8 seconds before raising
    # — long enough for forty concurrent sends to exhaust Starlette's sync
    # threadpool and take every other sync route down with them.  These options
    # turn that into ~2 seconds and one log line.
    #
    # `task_ignore_result` is where most of those 109 seconds actually went:
    # nothing in this codebase reads a task result, but the enqueue still had to
    # reach the result *backend*, and it is the backend that reports itself
    # unrecoverable ("The Celery application must be restarted") once its retry
    # budget is spent.  Not touching it at all is both faster and safer.
    task_ignore_result=True,
    broker_transport_options={
        "max_retries": 1,
        "socket_timeout": 2,
        "socket_connect_timeout": 2,
    },
    result_backend_transport_options={
        "max_retries": 1,
        "socket_timeout": 2,
        "socket_connect_timeout": 2,
    },
    task_publish_retry_policy={
        "max_retries": 1,
        "interval_start": 0,
        "interval_step": 0.2,
        "interval_max": 0.2,
    },
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
