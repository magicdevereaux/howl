"""
Redis-backed rate limiter for the auth surface.

Uses INCR + EXPIRE to track attempt counts per key within a fixed window.
Falls open (allows the request) if Redis is unavailable so a Redis outage
does not take down authentication. That tradeoff is deliberate — see
``check_rate_limit`` — and every caller inherits it.

Buckets are keyed per *action* so filling the login bucket does not lock a
user out of password reset, and vice versa. ``enforce_rate_limit`` is the
single entry point the routers/services use; it raises 429 with a
``Retry-After`` header.
"""

import logging

from fastapi import HTTPException, Request, status
from redis import Redis, RedisError

from app.config import settings

logger = logging.getLogger(__name__)

_client: Redis | None = None

_WINDOW_SECONDS = 15 * 60   # 15-minute window
_IP_LIMIT = 10               # login attempts per window per IP
_EMAIL_LIMIT = 5             # login attempts per window per email address

# Number of reverse proxies in front of the app whose X-Forwarded-For entries
# can be trusted. Railway/Vercel put exactly one in front, hence the default.
#
# Reads `settings.trusted_proxy_count` (GAPS #66) so the value can be tuned
# per deployment without a code change. This used to be a `getattr` fallback
# because `app/config.py` didn't declare the field — which meant setting
# TRUSTED_PROXY_COUNT in the environment silently did nothing. It's a real
# field now.
TRUSTED_PROXY_HOPS: int = settings.trusted_proxy_count


class _ActionLimit:
    """Per-action bucket sizes. ``None`` disables that bucket for the action."""

    __slots__ = ("label", "ip_limit", "email_limit")

    def __init__(self, label: str, ip_limit: int | None, email_limit: int | None) -> None:
        self.label = label
        self.ip_limit = ip_limit
        self.email_limit = email_limit


# All windows are _WINDOW_SECONDS (15 minutes).
_LIMITS: dict[str, _ActionLimit] = {
    # Brute-force protection. Unchanged from the original login-only limiter.
    "login": _ActionLimit("login", _IP_LIMIT, _EMAIL_LIMIT),
    # Stops one host mass-creating accounts (each of which costs a DALL·E call).
    "register": _ActionLimit("registration", 5, None),
    # Stops using a victim's address as a mail bomb, and stops enumeration
    # sweeps that probe many addresses from one host.
    "forgot_password": _ActionLimit("password reset", 5, 3),
    # Reset tokens are 32 random bytes, so this is belt-and-braces against
    # someone hammering the endpoint hoping for a collision.
    "reset_password": _ActionLimit("password reset", 10, None),
    "verify_email": _ActionLimit("verification", 20, None),
    "resend_verification": _ActionLimit("verification", 5, 3),
}


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


def client_ip(request: Request) -> str:
    """Best-effort real client IP, resistant to a spoofed ``X-Forwarded-For``.

    ``X-Forwarded-For`` is append-only: each proxy appends the address of the
    peer it received the request from. With ``TRUSTED_PROXY_HOPS`` proxies in
    front of us the *last* N entries were written by our own infrastructure and
    everything to the left of them is attacker-controlled. So we read the Nth
    entry from the right — never the first, which is exactly what a client
    trying to defeat the limiter gets to choose.

    Falls back to the socket peer when the header is absent or shorter than the
    trusted chain (i.e. it cannot have been written by our proxies), and when
    ``TRUSTED_PROXY_HOPS`` is 0 the header is ignored entirely.
    """
    direct = request.client.host if request.client else "unknown"

    hops = TRUSTED_PROXY_HOPS
    if hops <= 0:
        return direct

    forwarded = request.headers.get("X-Forwarded-For", "")
    parts = [p.strip() for p in forwarded.split(",") if p.strip()]
    if len(parts) < hops:
        return direct
    return parts[-hops]


def rate_limit_keys(action: str, ip: str, email: str | None = None) -> tuple[str, str | None]:
    """Return the Redis keys for the IP and (optionally) email counters."""
    return (
        f"rl:{action}:ip:{ip}",
        f"rl:{action}:email:{email.lower()}" if email else None,
    )


def _too_many(detail: str, retry_after: int) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=detail,
        headers={"Retry-After": str(retry_after)},
    )


def enforce_rate_limit(request: Request, action: str, email: str | None = None) -> None:
    """Apply the IP (and where configured, per-email) bucket for *action*.

    Raises 429 when either bucket is exhausted. The IP bucket is always checked
    first so a limited request cannot be used to probe whether an account
    exists. Shared by the web (``/api/auth/*``) and mobile
    (``/api/mobile/auth/*``) routers so the two cannot drift apart.

    Note this **fails open** if Redis is unreachable — see ``check_rate_limit``.
    """
    limits = _LIMITS[action]
    ip_key, email_key = rate_limit_keys(action, client_ip(request), email)

    if limits.ip_limit is not None:
        limited, retry_after = check_rate_limit(ip_key, limits.ip_limit, _WINDOW_SECONDS)
        if limited:
            raise _too_many(
                f"Too many {limits.label} attempts from this IP. "
                f"Try again in {retry_after} seconds.",
                retry_after,
            )

    if limits.email_limit is not None and email_key is not None:
        limited, retry_after = check_rate_limit(email_key, limits.email_limit, _WINDOW_SECONDS)
        if limited:
            raise _too_many(
                f"Too many {limits.label} attempts for this account. "
                f"Try again in {retry_after} seconds.",
                retry_after,
            )
