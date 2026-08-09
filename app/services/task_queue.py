"""Fail-open Celery enqueueing.

Every other Redis dependency in the request path fails **open** and says so:
the rate limiter (``app/services/rate_limit.py``), chat fan-out
(``app/services/pubsub.py``) and task locks (``app/services/task_lock.py``).
Enqueueing a task was the exception, and it failed *closed* in the worst
possible place — after the write had already been committed.

Measured with nothing listening on the Redis port, before this module existed:
``notify_new_message.delay(1, 2, 3)`` blocked for **108.8 seconds** and then
raised ``RuntimeError: Retry limit exceeded while trying to reconnect to the
Celery result store backend. The Celery application must be restarted.``  Three
things made that worse than a plain 500:

* **The write already happened.** ``POST /api/matches/{id}/messages`` commits the
  message and *then* enqueues, so the client saw a failure for a message that is
  in the database — and re-sent it.
* **Threadpool exhaustion.** These handlers are ``def``, not ``async def``, so
  Starlette runs them in a 40-worker threadpool. Forty concurrent sends parked
  for ~109 seconds each meant *no* sync route could be served, while ``/health``
  (``async def``) kept reporting ``ok``.
* **"The Celery application must be restarted."** The result backend's own
  words: once exhausted, the process does not self-heal when Redis returns.

So: enqueue through :func:`enqueue`, never through ``.delay()`` /
``.apply_async()`` directly. A broker outage then degrades to "no notification /
no avatar yet", which is recoverable, instead of losing the user's write.

The timeouts that turn ~109s into ~2s live in ``app/celery_app.py`` — both
halves are needed. This function stops the exception escaping; the transport
options stop the request hanging for two minutes first.
"""

import logging
from typing import Any

from celery import Task

logger = logging.getLogger(__name__)


def enqueue(task: Task, *args: Any, countdown: float | None = None) -> str | None:
    """Enqueue *task* with *args*, swallowing broker failures.

    Returns the task id, or ``None`` if the broker could not be reached — the
    caller's work is already committed and must not be rolled back because a
    notification could not be scheduled.

    Deliberately does **not** re-raise. If you need to know whether the task was
    accepted, check the return value; nothing in the request path does, because
    there is no useful recovery beyond logging.
    """
    try:
        # `.delay(*args)` is Celery's own sugar for `apply_async(args)` and routes
        # through it, so both branches hit the same machinery. Preferring it when
        # there is no countdown keeps the ordinary call shape — and keeps the
        # per-module `.delay` patches the test suite already relies on effective.
        if countdown is None:
            result = task.delay(*args)
        else:
            result = task.apply_async(args=list(args), countdown=countdown)
    except Exception:
        # Broad by intent: kombu raises OSError, ConnectionError, RuntimeError and
        # its own OperationalError depending on where in the connect/publish
        # sequence it fails. None of them are actionable here.
        logger.exception(
            "task_queue: could not enqueue %s%r — continuing without it",
            getattr(task, "name", task),
            args,
        )
        return None

    # `getattr` rather than `result.id` because the id is advisory — no caller in
    # the request path reads it, and the test suite's `.delay` stubs return None.
    # Failing an already-committed request over a missing task id would reintroduce
    # exactly the fail-closed behaviour this module exists to remove.
    task_id = getattr(result, "id", None)
    return str(task_id) if task_id is not None else None
