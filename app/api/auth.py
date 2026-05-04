import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.dependencies import get_current_user
from app.models.password_reset_token import PasswordResetToken
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.schemas.user import TokenOut, UserLogin, UserOut, UserRegister
from app.security import create_access_token, create_refresh_token, hash_password, verify_password
from app.services.email import send_password_reset_email

_TOKEN_EXPIRY_HOURS = 1


class RefreshIn(BaseModel):
    refresh_token: str


def _issue_tokens(user: User, db: Session) -> dict:
    """Create a new access + refresh token pair, persist the refresh token."""
    access = create_access_token(user.id)
    raw_refresh = create_refresh_token()
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days)
    db.add(RefreshToken(user_id=user.id, token=raw_refresh, expires_at=expires_at))
    db.commit()
    return {"access_token": access, "refresh_token": raw_refresh, "user": user}


class ForgotPasswordIn(BaseModel):
    email: EmailStr


class ResetPasswordIn(BaseModel):
    token: str
    new_password: str = Field(min_length=8)

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
def register(payload: UserRegister, db: Session = Depends(get_db)) -> dict:
    user = User(
        email=payload.email,
        password_hash=hash_password(payload.password),
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
    return _issue_tokens(user, db)


@router.post("/login", response_model=TokenOut)
def login(payload: UserLogin, db: Session = Depends(get_db)) -> dict:
    user = db.query(User).filter(User.email == payload.email).first()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return _issue_tokens(user, db)


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)) -> User:
    return current_user


@router.post("/refresh")
def refresh(payload: RefreshIn, db: Session = Depends(get_db)) -> dict:
    """Exchange a valid refresh token for a new access token."""
    _INVALID = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired refresh token.",
    )
    record = (
        db.query(RefreshToken)
        .filter(RefreshToken.token == payload.refresh_token)
        .first()
    )
    if record is None or record.revoked:
        raise _INVALID

    expires_at = record.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= datetime.now(timezone.utc):
        raise _INVALID

    return {"access_token": create_access_token(record.user_id), "token_type": "bearer"}


@router.post("/logout", status_code=204)
def logout(payload: RefreshIn, db: Session = Depends(get_db)) -> None:
    """Revoke a refresh token. Idempotent — silently ignores unknown tokens."""
    record = (
        db.query(RefreshToken)
        .filter(RefreshToken.token == payload.refresh_token)
        .first()
    )
    if record and not record.revoked:
        record.revoked = True
        db.commit()


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
