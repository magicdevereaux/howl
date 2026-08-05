from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import get_current_user
from app.models.user import AvatarStatus, User
from app.schemas.avatar import AvatarStatusOut
from app.tasks.avatar import generate_avatar

router = APIRouter(prefix="/api/avatar", tags=["avatar"])

_MONTHLY_REGEN_LIMIT = 1
_REGEN_WINDOW_SECONDS = 30 * 24 * 3600  # 30-day rolling window


def _enforce_regen_limit(user: User, db: Session) -> None:
    """Reset the monthly counter if the window has expired, then enforce the limit.

    Only called for non-premium users.  Does not count stale-detection regenerations
    triggered by profile bio updates — those go through the Celery task directly.
    """
    now = datetime.now(UTC)

    reset_at = user.regenerations_reset_at
    if reset_at is not None and reset_at.tzinfo is None:
        reset_at = reset_at.replace(tzinfo=UTC)

    window_expired = reset_at is None or (now - reset_at).total_seconds() >= _REGEN_WINDOW_SECONDS
    if window_expired:
        user.avatar_regenerations_this_month = 0
        user.regenerations_reset_at = now
        db.flush()
        return  # counter just reset — this regeneration is allowed

    if user.avatar_regenerations_this_month >= _MONTHLY_REGEN_LIMIT:
        resets_at = reset_at + timedelta(seconds=_REGEN_WINDOW_SECONDS)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "regeneration_limit_reached",
                "message": (
                    f"You've used your {_MONTHLY_REGEN_LIMIT} free avatar regeneration "
                    "this month. Upgrade to premium for unlimited regenerations."
                ),
                "limit": _MONTHLY_REGEN_LIMIT,
                "resets_at": resets_at.isoformat(),
            },
        )


@router.get("/status", response_model=AvatarStatusOut)
def get_avatar_status(current_user: User = Depends(get_current_user)) -> User:
    return current_user


@router.post("/regenerate", response_model=AvatarStatusOut)
def regenerate_avatar(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    """
    Reset avatar state and re-queue generation from the existing bio.

    Safe to call when stuck in a stale pending state. Idempotent: calling
    it multiple times just re-queues generation each time.
    """
    if not current_user.bio:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot generate avatar without a bio. Update your profile first.",
        )

    if not current_user.is_premium:
        _enforce_regen_limit(current_user, db)

    # Clear stale avatar data, reset status, and record the manual regeneration
    current_user.animal = None
    current_user.personality_traits = None
    current_user.avatar_description = None
    current_user.avatar_url = None
    current_user.avatar_status = AvatarStatus.pending
    current_user.avatar_status_updated_at = datetime.now(UTC)
    current_user.profile_needs_regen = False  # avatar now reflects current profile

    if not current_user.is_premium:
        current_user.avatar_regenerations_this_month += 1

    db.commit()
    db.refresh(current_user)

    generate_avatar.delay(current_user.id)

    return current_user
