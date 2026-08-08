from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import get_current_user, require_verified_email
from app.models.user import AvatarStatus, User
from app.schemas.avatar import AvatarStatusOut
from app.services.image_generation import delete_avatar
from app.tasks.avatar import generate_avatar

router = APIRouter(prefix="/api/avatar", tags=["avatar"])

_MONTHLY_REGEN_LIMIT = 1
_REGEN_WINDOW_SECONDS = 30 * 24 * 3600  # 30-day rolling window

#: Premium is "unlimited" as a product promise, but every regeneration is a paid
#: DALL-E call, so there is still an abuse ceiling. Set high enough that no
#: legitimate user reaches it.
_PREMIUM_REGEN_LIMIT = 100


def _regen_limit_for(user: User) -> int:
    return _PREMIUM_REGEN_LIMIT if user.is_premium else _MONTHLY_REGEN_LIMIT


def _enforce_regen_limit(user: User, db: Session) -> None:
    """Reset the monthly counter if the window has expired, then enforce the limit.

    Applies to everyone. Free users get _MONTHLY_REGEN_LIMIT; premium users get
    the much higher _PREMIUM_REGEN_LIMIT, which exists only to bound runaway
    spend on a paid image endpoint, not as a product-visible cap.

    Does not count stale-detection regenerations triggered by profile bio
    updates — those go through the Celery task directly.
    """
    now = datetime.now(UTC)
    limit = _regen_limit_for(user)

    reset_at = user.regenerations_reset_at
    if reset_at is not None and reset_at.tzinfo is None:
        reset_at = reset_at.replace(tzinfo=UTC)

    window_expired = reset_at is None or (now - reset_at).total_seconds() >= _REGEN_WINDOW_SECONDS
    if window_expired:
        user.avatar_regenerations_this_month = 0
        user.regenerations_reset_at = now
        db.flush()
        return  # counter just reset — this regeneration is allowed

    if user.avatar_regenerations_this_month >= limit:
        resets_at = reset_at + timedelta(seconds=_REGEN_WINDOW_SECONDS)
        message = (
            "You've reached the maximum number of avatar regenerations for this month."
            if user.is_premium
            else (
                f"You've used your {_MONTHLY_REGEN_LIMIT} free avatar regeneration "
                "this month. Upgrade to premium for unlimited regenerations."
            )
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "regeneration_limit_reached",
                "message": message,
                "limit": limit,
                "resets_at": resets_at.isoformat(),
            },
        )


@router.get("/status", response_model=AvatarStatusOut)
def get_avatar_status(current_user: User = Depends(get_current_user)) -> User:
    return current_user


@router.post("/regenerate", response_model=AvatarStatusOut)
def regenerate_avatar(
    current_user: User = Depends(require_verified_email),
    db: Session = Depends(get_db),
) -> User:
    """
    Reset avatar state and re-queue generation from the existing bio.

    Safe to call when stuck in a stale pending state. Idempotent: calling
    it multiple times just re-queues generation each time.

    Gated on email verification (GAPS #25): every regeneration is a paid DALL-E
    call, so an unverified throwaway address must not be able to burn spend past
    the grace window. Reading `GET /status` stays open.

    The other route to a paid call -- a bio edit on `PATCH /api/profile/me` --
    is gated too, but differently: that endpoint stays open (a user must be able
    to fix a typo'd email) and withholds only the generation, deferring it via
    `profile_needs_regen`. Keep the two in step.
    """
    if not current_user.bio:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot generate avatar without a bio. Update your profile first.",
        )

    _enforce_regen_limit(current_user, db)

    # Delete the previous image before dropping the reference to it. Without
    # this every regeneration leaks the old object into R2 permanently.
    # Best-effort: delete_avatar never raises and no-ops on None.
    delete_avatar(current_user.avatar_url)

    # Clear stale avatar data, reset status, and record the manual regeneration
    current_user.animal = None
    current_user.personality_traits = None
    current_user.avatar_description = None
    current_user.avatar_url = None
    current_user.avatar_status = AvatarStatus.pending
    current_user.avatar_status_updated_at = datetime.now(UTC)
    current_user.profile_needs_regen = False  # avatar now reflects current profile

    current_user.avatar_regenerations_this_month += 1

    db.commit()
    db.refresh(current_user)

    generate_avatar.delay(current_user.id)

    return current_user
