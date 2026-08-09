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
    # `task_ignore_result=True` above means nothing ever reads a result, so
    # this mostly documents intent rather than changing behaviour — but it's
    # cheap insurance against relying on Celery's one-day default if that ever
    # stops being true (GAPS #55).
    result_expires=3600,
    # ------------------------------------------------------------------
    # Queue routing (GAPS #55)
    #
    # Without this, all four task types share one FIFO queue, and
    # `worker_prefetch_multiplier=1` + `task_acks_late` means a worker holds
    # exactly one task at a time. `process_bot_responses` is the longest-
    # running task in the system by an order of magnitude (up to 20
    # sequential Claude calls, minutes of wall clock — see #51) and it runs
    # on Beat's 15-minute schedule below. `generate_avatar` is the product's
    # critical path (CLAUDE.md) and `notify_new_message`/`notify_new_match`
    # are user-facing pushes — none of them should be able to queue behind a
    # bot tick.
    #
    # This routes bot_response tasks to their own queue. It does nothing by
    # itself: a worker must actually be started consuming that queue, e.g. a
    # second Railway worker service running
    #   celery -A app.celery_app worker --loglevel=info --pool=solo -Q bot_response
    # alongside the existing worker, which should be narrowed to
    #   celery -A app.celery_app worker --loglevel=info --pool=solo -Q celery
    # See docs/RUNBOOK.md for the Railway service configuration.
    # ------------------------------------------------------------------
    task_routes={
        "app.tasks.bot_response.*": {"queue": "bot_response"},
    },
    # ------------------------------------------------------------------
    # Per-task time limits (GAPS #55)
    #
    # With no limit, a hung provider call parks a worker indefinitely: the
    # `anthropic` client's default timeout is ten minutes, and
    # `httpx.Client(timeout=30.0)` in image_generation.py only covers the
    # image download, not the DALL·E `images.generate` call itself. With
    # `--pool=solo` (Windows) that hung call is the entire worker.
    #
    # `soft_time_limit` raises `SoftTimeLimitExceeded` inside the task so it
    # can be caught if a task ever wants to clean up; `time_limit` is the
    # hard SIGKILL backstop a bit after it. Limits are generous for
    # `generate_avatar` (a Claude call plus a DALL·E render legitimately
    # takes a while) and for `process_bot_responses` (bounded to finish
    # before the *next* 15-minute Beat tick, not before some arbitrary
    # short deadline), and tight for the two notify tasks, which are just a
    # handful of DB writes and an HTTP push/APNs call.
    # ------------------------------------------------------------------
    task_annotations={
        "app.tasks.avatar.generate_avatar": {
            "soft_time_limit": 240,
            "time_limit": 300,
        },
        "app.tasks.bot_response.process_bot_responses": {
            "soft_time_limit": 780,
            "time_limit": 840,
        },
        "app.tasks.auto_match.auto_match_demo_user": {
            "soft_time_limit": 30,
            "time_limit": 45,
        },
        "app.tasks.notify.notify_new_message": {
            "soft_time_limit": 20,
            "time_limit": 30,
        },
        "app.tasks.notify.notify_new_match": {
            "soft_time_limit": 20,
            "time_limit": 30,
        },
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
