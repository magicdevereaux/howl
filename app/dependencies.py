from datetime import UTC, datetime, timedelta

from fastapi import Depends, HTTPException, Request, status
from jose import JWTError
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models.user import User
from app.security import decode_access_token


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    # Cookie-based auth (web) takes priority; Bearer token is the mobile fallback.
    token = request.cookies.get("access_token")
    if not token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    try:
        user_id = decode_access_token(token)
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )
    return user


# ---------------------------------------------------------------------------
# Email verification enforcement (GAPS #25)
#
# Graduated, not a hard gate. A new account is fully usable for
# `settings.email_verification_grace_period_hours` from `created_at`; after that
# window the *outbound* actions close (swipe, send message, generate avatar)
# while every read stays open, so the user can still see what they are about to
# lose and can still call resend-verification to rescue themselves.
#
# The grace window is derived from `created_at` rather than stored in a new
# column, so this needed no migration — and it means changing the window in
# config retroactively re-evaluates every account, which is what an operator
# would expect.
# ---------------------------------------------------------------------------

#: Machine-readable discriminator in the 403 body. Clients branch on
#: `status === 403 && body.detail?.code === EMAIL_VERIFICATION_REQUIRED`.
EMAIL_VERIFICATION_REQUIRED = "email_verification_required"

#: WebSocket close code for the same condition. Application close codes must be
#: in 4000-4999; this one deliberately reads as "403" so it is recognisable
#: alongside the existing 4001 (unauthenticated) and 4003 (not your match).
WS_EMAIL_VERIFICATION_REQUIRED = 4403

_VERIFICATION_MESSAGE = (
    "Please verify your email address to keep swiping, messaging and "
    "generating avatars. Check your inbox for the verification link, or "
    "request a new one."
)


def _as_utc(dt: datetime | None) -> datetime | None:
    """Attach UTC to a naive timestamp.

    `users.created_at` is ``DateTime(timezone=True)`` with a Python-side default,
    and SQLite (the entire test suite) hands it back **naive**. Comparing a naive
    value against an aware ``datetime.now(UTC)`` raises TypeError, so every read
    of `created_at` here has to go through this. Same idiom as
    `app/api/mobile_auth.py` and `_normalise` in `app/api/swipes.py`.
    """
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def email_verification_grace_expires_at(user: User) -> datetime:
    """When this account's unverified grace window closes (always tz-aware)."""
    # A missing created_at would mean a hand-built row; treat it as brand new
    # rather than instantly expired, so a data oddity cannot lock someone out.
    created_at = _as_utc(user.created_at) or datetime.now(UTC)
    return created_at + timedelta(hours=settings.email_verification_grace_period_hours)


def email_verification_error(user: User) -> dict[str, str] | None:
    """The 403 `detail` payload if `user` must verify before acting, else None.

    Split out from the dependency so the WebSocket handler — which cannot raise
    HTTPException — enforces the identical rule and reports the identical
    `code`, instead of drifting into a second implementation.
    """
    if user.is_email_verified:
        return None
    # Read through `settings` at call time, not import time, so flipping the
    # kill switch (or a test monkeypatching it) actually takes effect.
    if not settings.enforce_email_verification:
        return None

    expires_at = email_verification_grace_expires_at(user)
    if datetime.now(UTC) < expires_at:
        return None  # still inside the grace window

    return {
        "code": EMAIL_VERIFICATION_REQUIRED,
        "message": _VERIFICATION_MESSAGE,
        "grace_expired_at": expires_at.isoformat(),
    }


def require_verified_email(
    current_user: User = Depends(get_current_user),
) -> User:
    """Like `get_current_user`, but 403s once the grace window has expired.

    Authentication succeeded — the caller is who they say they are — so this is
    403, not 401: re-authenticating will not help, only clicking the link will.
    Clients should treat it as "go to the verify-email screen" and can call
    `POST /api/auth/resend-verification` (or the `/api/mobile/auth/` twin) to get
    a fresh link.

    Attached to outbound actions only. See `email_verification_error` for the
    rule and `docs/GAPS.md` #25 for the rollout decision.
    """
    error = email_verification_error(current_user)
    if error is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=error,
        )
    return current_user
