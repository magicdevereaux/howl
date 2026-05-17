"""
Redis-backed rate limiter for login brute-force protection.

Uses INCR + EXPIRE to track attempt counts per key within a sliding window.
Falls open (allows the request) if Redis is unavailable so a Redis outage
does not take down authentication.
"""

import logging

from redis import Redis, RedisError

from app.config import settings

logger = logging.getLogger(__name__)

_client: Redis | None = None

_WINDOW_SECONDS = 15 * 60   # 15-minute window
_IP_LIMIT = 10               # attempts per window per IP
_EMAIL_LIMIT = 5             # attempts per window per email address


def _get_client() -> Redis | None:
    global _client
    if _client is None:
        try:
            _client = Redis.from_url(settings.redis_url, decode_responses=True)
        except Exception as exc:
            logger.error("rate_limit: could not create Redis client: %s", exc)
    return _client


def check_rate_limit(key: str, limit: int, window: int = _WINDOW_SECONDS) -> tuple[bool, int]:
    """
    Increment the counter at *key* and check whether it exceeds *limit*.

    Returns (is_limited, retry_after_seconds).
    On any Redis error returns (False, 0) so auth is not blocked by infra issues.
    """
    client = _get_client()
    if client is None:
        return False, 0

    try:
        count = client.incr(key)
        if count == 1:
            # First attempt in this window — set the expiry
            client.expire(key, window)
        elif client.ttl(key) == -1:
            # Key has no TTL (edge case: previous expire call was lost)
            client.expire(key, window)

        if count > limit:
            ttl = client.ttl(key)
            return True, max(ttl, 1)

        return False, 0

    except RedisError as exc:
        logger.warning("rate_limit: Redis error, allowing request through: %s", exc)
        return False, 0


def login_rate_limit_keys(ip: str, email: str) -> tuple[str, str]:
    """Return the Redis keys for the IP and email rate limit counters."""
    return (
        f"rl:login:ip:{ip}",
        f"rl:login:email:{email.lower()}",
    )
