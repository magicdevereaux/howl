"""
Mobile auth endpoints — tokens are delivered in the JSON response body.

The web app uses httpOnly cookies for tokens; mobile clients can't, so these
endpoints return access_token + refresh_token in the body for the app to put in
SecureStore.

Token *delivery* is the only difference from `app/api/auth.py`. Everything else
comes from `app/services/auth_service.py`, which both routers share so they
cannot drift apart again (docs/GAPS.md #18). Reading the credential back is
already unified in `get_current_user`, which accepts `Authorization: Bearer`
as a fallback to the cookie — so every other API endpoint works for mobile
automatically.
"""

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.user import User
from app.schemas.user import UserLogin, UserOut, UserRegister
from app.services import auth_service
from app.services.auth_service import ResendVerificationIn, VerifyEmailIn

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


def _deliver(user: User, db: Session) -> dict:
    """Issue a session and hand the tokens back in the response body."""
    access, raw_refresh = auth_service.issue_session(user, db)
    return {
        "user": user,
        "access_token": access,
        "refresh_token": raw_refresh,
    }


@router.post("/register", response_model=MobileAuthOut, status_code=status.HTTP_201_CREATED)
def mobile_register(
    payload: UserRegister,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    user = auth_service.register_user(payload, request, db)
    return _deliver(user, db)


@router.post("/login", response_model=MobileAuthOut)
def mobile_login(
    payload: UserLogin,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    user = auth_service.authenticate_user(payload, request, db)
    return _deliver(user, db)


@router.post("/refresh", response_model=MobileRefreshOut)
def mobile_refresh(payload: MobileRefreshIn, db: Session = Depends(get_db)) -> dict:
    user, new_access = auth_service.rotate_access_token(payload.refresh_token, db)
    return {"user": user, "access_token": new_access}


@router.post("/logout", status_code=204)
def mobile_logout(payload: MobileRefreshIn, db: Session = Depends(get_db)) -> None:
    auth_service.revoke_refresh_token(payload.refresh_token, db)


@router.post("/verify-email", status_code=200)
def mobile_verify_email(
    payload: VerifyEmailIn,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    return auth_service.verify_email(payload, request, db)


@router.post("/resend-verification", status_code=200)
def mobile_resend_verification(
    payload: ResendVerificationIn,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    return auth_service.resend_verification(payload, request, db)
