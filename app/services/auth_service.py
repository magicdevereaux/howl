"""
Shared authentication logic for both auth routers.

`app/api/auth.py` (web — tokens delivered as httpOnly cookies) and
`app/api/mobile_auth.py` (mobile — tokens delivered in the JSON body) are the
only callers. **The one genuine difference between them is credential
delivery**; everything else — validation, hashing, token issuance, TTLs, rate
limiting, and the email side effects — lives here so the two cannot drift
apart again (see docs/GAPS.md #18).

Reading credentials back off a request is already unified in
`app/dependencies.py::get_current_user` (cookie first, then bearer), which is
deliberate. This module is the writing half of that story.

These functions raise `HTTPException` directly: they are the HTTP-facing
service layer, not a transport-agnostic domain layer, and having them own the
status codes is what stops the two routers reporting different errors for the
same condition.
"""

import logging
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.models.password_reset_token import PasswordResetToken
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.schemas.user import UserLogin, UserRegister
from app.security import create_access_token, create_refresh_token, hash_password, verify_password
from app.services.email import send_password_reset_email, send_verification_email
from app.services.rate_limit import enforce_rate_limit

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Token lifetimes — one definition each, used by both routers
# ---------------------------------------------------------------------------

VERIFICATION_TOKEN_EXPIRY_HOURS = 24
PASSWORD_RESET_TOKEN_EXPIRY_HOURS = 1

# A valid bcrypt hash of a throwaway string (not a secret). Verified against
# when the email is unknown so that "no such account" and "wrong password" take
# the same amount of time and cannot be told apart by a stopwatch.
_DUMMY_PASSWORD_HASH = "$2b$12$kyvU3Wy0bfD6RFM89.uhJuMYFz5er.dGpvb66CFDm16wCenEEQaoS"

# Deliberately identical whether or not the address is registered — see
# start_password_reset / resend_verification.
_GENERIC_RESET_MESSAGE = "If that email is registered, a reset link has been sent."
_GENERIC_VERIFICATION_MESSAGE = (
    "If that email is registered and not yet verified, a new verification link has been sent."
)


# ---------------------------------------------------------------------------
# Request bodies shared by both routers
#
# They live here rather than in either router so neither is the other's
# dependency. Response shapes stay in the routers: those differ by design
# (cookies vs. bearer tokens in the body).
# ---------------------------------------------------------------------------

class VerifyEmailIn(BaseModel):
    token: str


class ResendVerificationIn(BaseModel):
    email: EmailStr

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return v.strip().lower()


class ForgotPasswordIn(BaseModel):
    email: EmailStr

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return v.strip().lower()


class ResetPasswordIn(BaseModel):
    token: str
    new_password: str = Field(min_length=8)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _as_aware(dt: datetime) -> datetime:
    """Normalise naive datetimes (SQLite) against aware ones (PostgreSQL)."""
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt


def _new_verification_token(user: User) -> str:
    """Stamp a fresh email-verification token + expiry on *user* (no commit)."""
    token = secrets.token_urlsafe(32)
    user.email_verification_token = token
    user.email_verification_token_expires_at = datetime.now(UTC) + timedelta(
        hours=VERIFICATION_TOKEN_EXPIRY_HOURS
    )
    return token


# ---------------------------------------------------------------------------
# Session issuance
# ---------------------------------------------------------------------------

def issue_session(user: User, db: Session) -> tuple[str, str]:
    """Mint an access + refresh token pair and persist the refresh token.

    Returns ``(access_token, refresh_token)``. The caller decides how to
    deliver them: web sets cookies, mobile returns them in the body.
    """
    access = create_access_token(user.id)
    raw_refresh = create_refresh_token()
    expires_at = datetime.now(UTC) + timedelta(days=settings.refresh_token_expire_days)
    db.add(RefreshToken(user_id=user.id, token=raw_refresh, expires_at=expires_at))
    db.commit()
    return access, raw_refresh


def rotate_access_token(raw_refresh: str | None, db: Session) -> tuple[User, str]:
    """Exchange a refresh token for a fresh access token.

    Returns ``(user, access_token)``. Raises 401 if the token is missing,
    unknown, revoked, expired, or its user is gone.
    """
    invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired refresh token.",
    )
    if not raw_refresh:
        raise invalid

    record = db.query(RefreshToken).filter(RefreshToken.token == raw_refresh).first()
    if record is None or record.revoked:
        raise invalid
    if _as_aware(record.expires_at) <= datetime.now(UTC):
        raise invalid

    user = db.get(User, record.user_id)
    if user is None:
        raise invalid

    return user, create_access_token(record.user_id)


def revoke_refresh_token(raw_refresh: str | None, db: Session) -> None:
    """Revoke a refresh token if it exists. Silent when it doesn't — logout is
    idempotent and must not reveal whether a token was real."""
    if not raw_refresh:
        return
    record = db.query(RefreshToken).filter(RefreshToken.token == raw_refresh).first()
    if record and not record.revoked:
        record.revoked = True
        db.commit()


# ---------------------------------------------------------------------------
# Register / login
# ---------------------------------------------------------------------------

def register_user(payload: UserRegister, request: Request, db: Session) -> User:
    """Create an account, send the verification email, return the new user.

    Raises 409 on a duplicate address and 429 when the registration bucket for
    this IP is exhausted.
    """
    enforce_rate_limit(request, "register", payload.email)

    user = User(email=payload.email, password_hash=hash_password(payload.password))
    verification_token = _new_verification_token(user)
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )
    db.refresh(user)
    send_verification_email(user.email, verification_token)
    return user


def authenticate_user(payload: UserLogin, request: Request, db: Session) -> User:
    """Verify credentials and return the user, or raise 401 / 429."""
    enforce_rate_limit(request, "login", payload.email)

    user = db.query(User).filter(User.email == payload.email).first()
    # Always run one password verification so the unknown-email and
    # wrong-password paths cost the same wall-clock time.
    password_ok = verify_password(
        payload.password, user.password_hash if user else _DUMMY_PASSWORD_HASH
    )
    if user is None or not password_ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


# ---------------------------------------------------------------------------
# Email verification
# ---------------------------------------------------------------------------

def verify_email(payload: VerifyEmailIn, request: Request, db: Session) -> dict:
    """Consume an email-verification token and mark the account verified."""
    enforce_rate_limit(request, "verify_email")

    invalid = HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Invalid or expired verification token.",
    )
    user = db.query(User).filter(User.email_verification_token == payload.token).first()
    if not user:
        raise invalid

    expires_at = user.email_verification_token_expires_at
    if expires_at is None or _as_aware(expires_at) <= datetime.now(UTC):
        raise invalid

    user.is_email_verified = True
    user.email_verification_token = None
    user.email_verification_token_expires_at = None
    db.commit()
    return {"message": "Email verified successfully."}


def resend_verification(payload: ResendVerificationIn, request: Request, db: Session) -> dict:
    """Issue a fresh verification link.

    Returns the same response whether or not the address is registered (or is
    already verified) so this cannot be used to enumerate accounts. Rate limited
    per IP *and* per address so it cannot be used to mail-bomb someone either.
    """
    enforce_rate_limit(request, "resend_verification", payload.email)

    user = db.query(User).filter(User.email == payload.email).first()
    if user is None or user.is_email_verified:
        return {"message": _GENERIC_VERIFICATION_MESSAGE}

    token = _new_verification_token(user)
    db.commit()
    send_verification_email(user.email, token)
    logger.info("resend_verification: new token issued for user %d", user.id)
    return {"message": _GENERIC_VERIFICATION_MESSAGE}


# ---------------------------------------------------------------------------
# Password reset
# ---------------------------------------------------------------------------

def start_password_reset(payload: ForgotPasswordIn, request: Request, db: Session) -> dict:
    """Request a password-reset link.

    Always returns the same response regardless of whether the email is
    registered — this prevents leaking which addresses have accounts.
    """
    enforce_rate_limit(request, "forgot_password", payload.email)

    user = db.query(User).filter(User.email == payload.email).first()
    if not user:
        return {"message": _GENERIC_RESET_MESSAGE}

    # Invalidate any previous unused tokens for this user
    db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user.id,
        PasswordResetToken.used == False,  # noqa: E712
    ).update({"used": True}, synchronize_session=False)

    raw_token = secrets.token_urlsafe(32)
    expires_at = datetime.now(UTC) + timedelta(hours=PASSWORD_RESET_TOKEN_EXPIRY_HOURS)
    db.add(PasswordResetToken(user_id=user.id, token=raw_token, expires_at=expires_at))
    db.commit()

    send_password_reset_email(user.email, raw_token)
    return {"message": _GENERIC_RESET_MESSAGE}


def complete_password_reset(payload: ResetPasswordIn, request: Request, db: Session) -> dict:
    """Consume a reset token and update the user's password."""
    enforce_rate_limit(request, "reset_password")

    invalid = HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Invalid or expired reset token.",
    )

    record = (
        db.query(PasswordResetToken)
        .filter(PasswordResetToken.token == payload.token)
        .first()
    )
    if record is None or record.used:
        raise invalid
    if _as_aware(record.expires_at) <= datetime.now(UTC):
        raise invalid

    user = db.get(User, record.user_id)
    if user is None:
        raise invalid

    user.password_hash = hash_password(payload.new_password)
    record.used = True

    # Revoke every outstanding session. Someone resetting their password because
    # they were compromised must not leave the attacker holding a refresh token
    # that stays valid for another refresh_token_expire_days.
    revoked = (
        db.query(RefreshToken)
        .filter(RefreshToken.user_id == user.id, RefreshToken.revoked == False)  # noqa: E712
        .update({RefreshToken.revoked: True}, synchronize_session=False)
    )

    # Invalidate any other unused reset tokens issued for this account.
    db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user.id,
        PasswordResetToken.used == False,  # noqa: E712
    ).update({PasswordResetToken.used: True}, synchronize_session=False)

    db.commit()
    logger.info("reset_password: user %d reset password, revoked %d sessions", user.id, revoked)

    return {"message": "Password reset successful. You can now log in with your new password."}
