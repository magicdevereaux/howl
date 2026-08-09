"""
Web auth endpoints — tokens are delivered as httpOnly cookies.

This router is a thin shell: every rule (validation, hashing, token TTLs, rate
limiting, email side effects) lives in `app/services/auth_service.py`, shared
with `app/api/mobile_auth.py`. The only thing that belongs here is cookie
delivery. See docs/GAPS.md #18.
"""

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.schemas.user import AuthOut, UserLogin, UserOut, UserRegister
from app.services import auth_service
from app.services.auth_service import (
    ChangeEmailIn,
    ForgotPasswordIn,
    ResendVerificationIn,
    ResetPasswordIn,
    VerifyEmailIn,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Cookie settings: secure + samesite=none required for cross-origin (Vercel ↔ Railway).
# In debug mode, use lax + insecure so localhost HTTP works.
_COOKIE_SECURE   = not settings.debug
_COOKIE_SAMESITE: str = "none" if not settings.debug else "lax"


def _cookie_kwargs() -> dict:
    return dict(httponly=True, secure=_COOKIE_SECURE, samesite=_COOKIE_SAMESITE, path="/")


def _set_auth_cookies(response: Response, access_token: str, refresh_token: str) -> None:
    kw = _cookie_kwargs()
    response.set_cookie("access_token",  access_token,  max_age=settings.access_token_expire_minutes * 60,        **kw)
    response.set_cookie("refresh_token", refresh_token, max_age=settings.refresh_token_expire_days * 86400, **kw)


def _clear_auth_cookies(response: Response) -> None:
    kw = _cookie_kwargs()
    response.delete_cookie("access_token",  **kw)
    response.delete_cookie("refresh_token", **kw)


def _deliver(user: User, db: Session, response: Response) -> dict:
    """Issue a session and hand the tokens to the browser as httpOnly cookies."""
    access, raw_refresh = auth_service.issue_session(user, db)
    _set_auth_cookies(response, access, raw_refresh)
    return {"user": user}


@router.post("/register", response_model=AuthOut, status_code=status.HTTP_201_CREATED)
def register(
    payload: UserRegister,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> dict:
    user = auth_service.register_user(payload, request, db)
    return _deliver(user, db, response)


@router.post("/login", response_model=AuthOut)
def login(
    payload: UserLogin,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> dict:
    user = auth_service.authenticate_user(payload, request, db)
    return _deliver(user, db, response)


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)) -> User:
    return current_user


@router.post("/refresh", response_model=AuthOut)
def refresh(request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    """Exchange the refresh-token cookie for a new access-token cookie."""
    user, new_access = auth_service.rotate_access_token(request.cookies.get("refresh_token"), db)
    response.set_cookie(
        "access_token",
        new_access,
        max_age=settings.access_token_expire_minutes * 60,
        **_cookie_kwargs(),
    )
    return {"user": user}


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, db: Session = Depends(get_db)) -> None:
    """Revoke the refresh-token cookie and clear both auth cookies."""
    auth_service.revoke_refresh_token(request.cookies.get("refresh_token"), db)
    _clear_auth_cookies(response)


@router.post("/verify-email", status_code=200)
def verify_email(payload: VerifyEmailIn, request: Request, db: Session = Depends(get_db)) -> dict:
    return auth_service.verify_email(payload, request, db)


@router.post("/resend-verification", status_code=200)
def resend_verification(
    payload: ResendVerificationIn,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    return auth_service.resend_verification(payload, request, db)


@router.post("/change-email", status_code=200)
def change_email(
    payload: ChangeEmailIn,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Move the account to a new address.

    Only registered here, not in `mobile_auth.py`: `get_current_user` resolves a
    cookie *or* a bearer header from the one dependency, so the mobile client
    calls this same path. There is no cookie/bearer asymmetry to shell over —
    which is the only reason the two routers exist separately.
    """
    return auth_service.change_email(payload, request, current_user, db)


@router.post("/forgot-password", status_code=200)
def forgot_password(
    payload: ForgotPasswordIn,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    return auth_service.start_password_reset(payload, request, db)


@router.post("/reset-password", status_code=200)
def reset_password(
    payload: ResetPasswordIn,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    return auth_service.complete_password_reset(payload, request, db)
