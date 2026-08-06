"""
Redis-backed advisory locks for Celery tasks.

Celery is configured with ``task_acks_late = True`` (app/celery_app.py), so a
worker killed mid-task has its message redelivered and the task runs again from
the start. For tasks that call paid APIs that means paying twice for the same
work. These locks make a task single-flight for a given key.

Falls **open** if Redis is unavailable — the same tradeoff the rate limiter
makes. A Redis outage should degrade us to the current behaviour (possible
duplicate work), not stop avatars generating altogether.
"""

import logging

from redis import Redis, RedisError

from app.config import settings

logger = logging.getLogger(__name__)

_client: Redis | None = None

#: Long enough to outlive a slow Claude + DALL-E round trip, short enough that a
#: killed worker's lock clears without manual intervention.
DEFAULT_TTL_SECONDS = 600


def _get_client() -> Redis | None:
    global _client
    if _client is None:
        try:
            _client = Redis.from_url(settings.redis_url, decode_responses=True)
        except Exception as exc:
            logger.error("task_lock: could not create Redis client: %s", exc)
    return _client


def acquire(key: str, ttl: int = DEFAULT_TTL_SECONDS) -> bool:
    """Try to claim *key*.

    Returns True if the caller now holds the lock (or if Redis is unavailable
    and we are failing open). Returns False only when the lock is definitely
    held by someone else.
    """
    client = _get_client()
    if client is None:
        return True

    try:
        # SET NX EX is atomic — no check-then-set race.
        return bool(client.set(key, "1", nx=True, ex=ttl))
    except RedisError as exc:
        logger.warning("task_lock: Redis error acquiring %s, proceeding without lock: %s", key, exc)
        return True


def release(key: str) -> None:
    """Release *key*. Never raises."""
    client = _get_client()
    if client is None:
        return

    try:
        client.delete(key)
    except RedisError as exc:
        logger.warning("task_lock: Redis error releasing %s: %s", key, exc)
