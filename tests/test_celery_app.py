"""Tests for Celery queue routing and time-limit configuration (GAPS #55).

These are pure configuration tests against the real ``celery_app`` object —
no broker/backend connection is ever made, so they're hermetic regardless of
whether Redis is reachable from this environment.
"""

# Importing the task modules registers their tasks on celery_app.tasks; the
# app's own `include=[...]` normally does this at import time via the worker,
# but a bare `from app.celery_app import celery_app` in a test process does
# not trigger it.
import app.tasks.auto_match  # noqa: F401
import app.tasks.avatar  # noqa: F401
import app.tasks.bot_response  # noqa: F401
import app.tasks.notify  # noqa: F401
from app.celery_app import celery_app


def _route_queue(task_name: str) -> str:
    route = celery_app.amqp.router.route({}, task_name)
    return route["queue"].name


def test_bot_response_routed_to_its_own_queue():
    """The longest-running task (up to 20 sequential Claude calls) must not
    share a queue with generate_avatar or the notify tasks."""
    assert _route_queue("app.tasks.bot_response.process_bot_responses") == "bot_response"


def test_avatar_and_notify_tasks_stay_on_default_queue():
    """Only bot_response should move — everything else keeps today's
    behaviour so no second worker service is required just to keep working."""
    for name in [
        "app.tasks.avatar.generate_avatar",
        "app.tasks.auto_match.auto_match_demo_user",
        "app.tasks.notify.notify_new_message",
        "app.tasks.notify.notify_new_match",
    ]:
        assert _route_queue(name) == "celery"


def test_avatar_task_has_generous_time_limit():
    task = celery_app.tasks["app.tasks.avatar.generate_avatar"]
    assert task.soft_time_limit is not None
    assert task.time_limit is not None
    assert task.soft_time_limit < task.time_limit
    # Generous enough for a Claude call plus a DALL-E render, but bounded —
    # a hung provider call must not park a worker indefinitely.
    assert 60 <= task.soft_time_limit <= 600


def test_notify_tasks_have_tight_time_limits():
    for name in ["app.tasks.notify.notify_new_message", "app.tasks.notify.notify_new_match"]:
        task = celery_app.tasks[name]
        assert task.soft_time_limit is not None
        assert task.time_limit is not None
        assert task.time_limit <= 60


def test_bot_response_time_limit_fits_within_beat_interval():
    """The Beat schedule fires this task every 15 minutes; its hard time
    limit must leave room so a slow run doesn't still be executing when the
    next tick fires."""
    task = celery_app.tasks["app.tasks.bot_response.process_bot_responses"]
    beat_interval = celery_app.conf.beat_schedule["bot-response-every-15-min"]["schedule"]
    assert task.time_limit is not None
    assert task.time_limit < beat_interval


def test_all_task_types_have_explicit_time_limits():
    """Every task registered under app.tasks.* must have both a soft and a
    hard time limit — no task should be able to hang a worker forever."""
    for name, task in celery_app.tasks.items():
        if not name.startswith("app.tasks."):
            continue
        assert task.soft_time_limit is not None, f"{name} has no soft_time_limit"
        assert task.time_limit is not None, f"{name} has no time_limit"


def test_result_expires_set_explicitly():
    """Rather than relying on Celery's one-day default."""
    assert celery_app.conf.result_expires == 3600


def test_task_ignore_result_still_true():
    """Guard against regressing the #43 fix while touching this file for #55:
    a dead broker previously blocked `.delay()` for ~109s partly because
    enqueueing still reached the result backend."""
    assert celery_app.conf.task_ignore_result is True
