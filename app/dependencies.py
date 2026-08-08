from fastapi import Depends, HTTPException, Request, status
from jose import JWTError
from sqlalchemy.orm import Session

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


def require_verified_email(
    current_user: User = Depends(get_current_user),
) -> User:
    """Like `get_current_user`, but 403s when the account's email is unverified.

    Authentication succeeded — the caller is who they say they are — so this is
    403, not 401: re-authenticating will not help, only clicking the link will.
    Clients should treat it as "go to the verify-email screen" and can call
    `POST /api/auth/resend-verification` (or the `/api/mobile/auth/` twin) to get
    a fresh link.

    Deliberately **not** attached to any route yet: turning it on retroactively
    locks out every account created before verification was enforced, including
    the 1000 seeded bot users. See docs/GAPS.md #25 — the rollout is a product
    decision, not a code one.
    """
    if not current_user.is_email_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email verification required. Check your inbox for the verification link.",
        )
    return current_user
