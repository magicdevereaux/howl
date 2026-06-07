"""
Mobile-specific auth endpoints.

The web app uses httpOnly cookies for tokens — mobile clients can't do that.
These endpoints return access_token + refresh_token in the JSON response body
so the mobile app can store them in SecureStore.

All other API endpoints work for mobile automatically because get_current_user
now accepts Authorization: Bearer <token> as a fallback to the cookie.
"""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.auth import (
    ForgotPasswordIn,
    ResetPasswordIn,
    VerifyEmailIn,
    _TOKEN_EXPIRY_HOURS,
)
from app.db import get_db
from app.models.password_reset_token import PasswordResetToken
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.schemas.user import UserLogin, UserOut, UserRegister
from app.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    verify_password,
)
from app.services.email import send_verification_email

router = APIRouter(prefix="/api/mobile/auth", tags=["mobile-auth"])


class MobileAuthOut(BaseModel):
    user: UserOut
    access_token: str
    refresh_token: str
    token_type: str = "bearer"

    model_config = {"from_attributes": True}


class MobileRefreshIn(BaseModel):
    refresh_token: str


class MobileRefreshOut(BaseModel):
    user: UserOut
    access_token: str
    token_type: str = "bearer"

    model_config = {"from_attributes": True}


def _issue_tokens_body(user: User, db: Session) -> dict:
    """Create access + refresh token pair and return them in the response body."""
    access = create_access_token(user.id)
    raw_refresh = create_refresh_token()
    expires_at = datetime.now(timezone.utc) + timedelta(days=30)
    db.add(RefreshToken(user_id=user.id, token=raw_refresh, expires_at=expires_at))
    db.commit()
    return {
        "user": user,
        "access_token": access,
        "refresh_token": raw_refresh,
    }


@router.post("/register", response_model=MobileAuthOut, status_code=status.HTTP_201_CREATED)
def mobile_register(payload: UserRegister, db: Session = Depends(get_db)) -> dict:
    import secrets
    verification_token = secrets.token_urlsafe(32)
    user = User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        email_verification_token=verification_token,
        email_verification_token_expires_at=(
            datetime.now(timezone.utc) + timedelta(hours=_TOKEN_EXPIRY_HOURS)
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
    return _issue_tokens_body(user, db)


@router.post("/login", response_model=MobileAuthOut)
def mobile_login(payload: UserLogin, db: Session = Depends(get_db)) -> dict:
    user = db.query(User).filter(User.email == payload.email).first()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    return _issue_tokens_body(user, db)


@router.post("/refresh", response_model=MobileRefreshOut)
def mobile_refresh(payload: MobileRefreshIn, db: Session = Depends(get_db)) -> dict:
    _INVALID = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired refresh token.",
    )
    record = db.query(RefreshToken).filter(RefreshToken.token == payload.refresh_token).first()
    if record is None or record.revoked:
        raise _INVALID

    expires_at = record.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= datetime.now(timezone.utc):
        raise _INVALID

    new_access = create_access_token(record.user_id)
    user = db.get(User, record.user_id)
    return {"user": user, "access_token": new_access}


@router.post("/logout", status_code=204)
def mobile_logout(payload: MobileRefreshIn, db: Session = Depends(get_db)) -> None:
    record = db.query(RefreshToken).filter(RefreshToken.token == payload.refresh_token).first()
    if record and not record.revoked:
        record.revoked = True
        db.commit()
