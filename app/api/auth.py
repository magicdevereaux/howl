import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.dependencies import get_current_user
from app.models.password_reset_token import PasswordResetToken
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.schemas.user import AuthOut, UserLogin, UserOut, UserRegister
from app.security import create_access_token, create_refresh_token, hash_password, verify_password
from app.services.email import send_password_reset_email, send_verification_email
from app.services.rate_limit import (
    _EMAIL_LIMIT,
    _IP_LIMIT,
    _WINDOW_SECONDS,
    check_rate_limit,
    login_rate_limit_keys,
)

_TOKEN_EXPIRY_HOURS = 1

# Cookie settings: secure + samesite=none required for cross-origin (Vercel ↔ Railway).
# In debug mode, use lax + insecure so localhost HTTP works.
_COOKIE_SECURE   = not settings.debug
_COOKIE_SAMESITE: str = "none" if not settings.debug else "lax"


def _set_auth_cookies(response: Response, access_token: str, refresh_token: str) -> None:
    kw = dict(httponly=True, secure=_COOKIE_SECURE, samesite=_COOKIE_SAMESITE, path="/")
    response.set_cookie("access_token",  access_token,  max_age=settings.access_token_expire_minutes * 60,        **kw)
    response.set_cookie("refresh_token", refresh_token, max_age=settings.refresh_token_expire_days * 86400, **kw)


def _clear_auth_cookies(response: Response) -> None:
    kw = dict(httponly=True, secure=_COOKIE_SECURE, samesite=_COOKIE_SAMESITE, path="/")
    response.delete_cookie("access_token",  **kw)
    response.delete_cookie("refresh_token", **kw)


def _issue_tokens(user: User, db: Session, response: Response) -> dict:
    """Create a new access + refresh token pair, persist the refresh token, set cookies."""
    access = create_access_token(user.id)
    raw_refresh = create_refresh_token()
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days)
    db.add(RefreshToken(user_id=user.id, token=raw_refresh, expires_at=expires_at))
    db.commit()
    _set_auth_cookies(response, access, raw_refresh)
    return {"user": user}


class VerifyEmailIn(BaseModel):
    token: str


class ForgotPasswordIn(BaseModel):
    email: EmailStr


class ResetPasswordIn(BaseModel):
    token: str
    new_password: str = Field(min_length=8)

router = APIRouter(prefix="/api/auth", tags=["auth"])


_VERIFICATION_TOKEN_EXPIRY_HOURS = 24


@router.post("/register", response_model=AuthOut, status_code=status.HTTP_201_CREATED)
def register(payload: UserRegister, response: Response, db: Session = Depends(get_db)) -> dict:
    verification_token = secrets.token_urlsafe(32)
    user = User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        email_verification_token=verification_token,
        email_verification_token_expires_at=(
            datetime.now(timezone.utc) + timedelta(hours=_VERIFICATION_TOKEN_EXPIRY_HOURS)
        ),
    )
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
    return _issue_tokens(user, db, response)


@router.post("/verify-email", status_code=200)
def verify_email(payload: VerifyEmailIn, db: Session = Depends(get_db)) -> dict:
    """Consume an email verification token and mark the account as verified."""
    _INVALID = HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Invalid or expired verification token.",
    )
    user = db.query(User).filter(
        User.email_verification_token == payload.token
    ).first()
    if not user:
        raise _INVALID

    expires_at = user.email_verification_token_expires_at
    if expires_at is None:
        raise _INVALID
    # Normalise naive datetime (SQLite) vs aware datetime (PostgreSQL)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= datetime.now(timezone.utc):
        raise _INVALID

    user.is_email_verified = True
    user.email_verification_token = None
    user.email_verification_token_expires_at = None
    db.commit()
    return {"message": "Email verified successfully."}


@router.post("/login", response_model=AuthOut)
def login(payload: UserLogin, request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    # Resolve the real client IP (respects X-Forwarded-For from Railway / reverse proxies)
    forwarded = request.headers.get("X-Forwarded-For")
    client_ip = forwarded.split(",")[0].strip() if forwarded else (
        request.client.host if request.client else "unknown"
    )

    ip_key, email_key = login_rate_limit_keys(client_ip, payload.email)

    limited, retry_after = check_rate_limit(ip_key, _IP_LIMIT, _WINDOW_SECONDS)
    if limited:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many login attempts from this IP. Try again in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
        )

    limited, retry_after = check_rate_limit(email_key, _EMAIL_LIMIT, _WINDOW_SECONDS)
    if limited:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many login attempts for this account. Try again in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
        )

    user = db.query(User).filter(User.email == payload.email).first()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return _issue_tokens(user, db, response)


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)) -> User:
    return current_user


@router.post("/refresh", response_model=AuthOut)
def refresh(request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    """Exchange the refresh-token cookie for a new access-token cookie."""
    _INVALID = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired refresh token.",
    )
    raw_refresh = request.cookies.get("refresh_token")
    if not raw_refresh:
        raise _INVALID

    record = db.query(RefreshToken).filter(RefreshToken.token == raw_refresh).first()
    if record is None or record.revoked:
        raise _INVALID

    expires_at = record.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= datetime.now(timezone.utc):
        raise _INVALID

    new_access = create_access_token(record.user_id)
    kw = dict(httponly=True, secure=_COOKIE_SECURE, samesite=_COOKIE_SAMESITE, path="/")
    response.set_cookie("access_token", new_access, max_age=settings.access_token_expire_minutes * 60, **kw)

    user = db.get(User, record.user_id)
    return {"user": user}


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, db: Session = Depends(get_db)) -> None:
    """Revoke the refresh-token cookie and clear both auth cookies."""
    raw_refresh = request.cookies.get("refresh_token")
    if raw_refresh:
        record = db.query(RefreshToken).filter(RefreshToken.token == raw_refresh).first()
        if record and not record.revoked:
            record.revoked = True
            db.commit()
    _clear_auth_cookies(response)


@router.post("/forgot-password", status_code=200)
def forgot_password(payload: ForgotPasswordIn, db: Session = Depends(get_db)) -> dict:
    """
    Request a password-reset link.

    Always returns the same response regardless of whether the email is
    registered — this prevents leaking which addresses have accounts.
    """
    _GENERIC = {"message": "If that email is registered, a reset link has been sent."}

    user = db.query(User).filter(User.email == payload.email).first()
    if not user:
        return _GENERIC

    # Invalidate any previous unused tokens for this user
    db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user.id,
        PasswordResetToken.used == False,  # noqa: E712
    ).update({"used": True}, synchronize_session=False)

    raw_token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=_TOKEN_EXPIRY_HOURS)
    db.add(PasswordResetToken(user_id=user.id, token=raw_token, expires_at=expires_at))
    db.commit()

    send_password_reset_email(user.email, raw_token)
    return _GENERIC


@router.post("/reset-password", status_code=200)
def reset_password(payload: ResetPasswordIn, db: Session = Depends(get_db)) -> dict:
    """Consume a reset token and update the user's password."""
    _INVALID = HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Invalid or expired reset token.",
    )

    record = (
        db.query(PasswordResetToken)
        .filter(PasswordResetToken.token == payload.token)
        .first()
    )
    if record is None or record.used:
        raise _INVALID

    # Normalize to aware datetime so the comparison works for both SQLite
    # (which returns naive datetimes) and PostgreSQL (which returns aware ones).
    expires_at = record.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= datetime.now(timezone.utc):
        raise _INVALID

    user = db.get(User, record.user_id)
    if user is None:
        raise _INVALID

    user.password_hash = hash_password(payload.new_password)
    record.used = True
    db.commit()

    return {"message": "Password reset successful. You can now log in with your new password."}
