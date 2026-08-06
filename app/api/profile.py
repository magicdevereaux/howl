import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import get_current_user
from app.models.user import AvatarStatus, User
from app.schemas.user import ProfileUpdate, PublicProfileOut, UserOut
from app.services.image_generation import delete_avatar
from app.tasks.avatar import generate_avatar

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/profile", tags=["profile"])

# Single source of truth — these used to be duplicated here and drift was only
# prevented by a comment.
from app.api.avatar import (  # noqa: E402
    _MONTHLY_REGEN_LIMIT,
    _PREMIUM_REGEN_LIMIT,
    _REGEN_WINDOW_SECONDS,
)


def _try_consume_regen_slot(user: User, db: Session) -> bool:
    """Try to consume one monthly regeneration slot.

    Returns True if a slot was available (and the counter is incremented).
    Returns False if the limit is exhausted for the current window.

    Premium users share the same counter but against a far higher ceiling. They
    are "unlimited" as a product promise, but each regeneration is a paid
    DALL-E call, so the bio-edit path needs the same abuse ceiling as the
    explicit regenerate endpoint — otherwise it is a trivial way around it.
    """
    limit = _PREMIUM_REGEN_LIMIT if user.is_premium else _MONTHLY_REGEN_LIMIT

    now = datetime.now(UTC)
    reset_at = user.regenerations_reset_at
    if reset_at is not None and reset_at.tzinfo is None:
        reset_at = reset_at.replace(tzinfo=UTC)

    window_expired = reset_at is None or (now - reset_at).total_seconds() >= _REGEN_WINDOW_SECONDS
    if window_expired:
        user.avatar_regenerations_this_month = 0
        user.regenerations_reset_at = now
        db.flush()

    if user.avatar_regenerations_this_month >= limit:
        return False

    user.avatar_regenerations_this_month += 1
    return True


@router.get("/me", response_model=UserOut)
def get_my_profile(current_user: User = Depends(get_current_user)) -> User:
    return current_user


@router.patch("/me", response_model=UserOut)
def update_my_profile(
    payload: ProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    # These fields never trigger regeneration — apply unconditionally.
    if payload.name is not None:
        current_user.name = payload.name
    if payload.age is not None:
        current_user.age = payload.age
    if payload.location is not None:
        current_user.location = payload.location
    if payload.email_notifications is not None:
        current_user.email_notifications = payload.email_notifications
    if payload.gender is not None:
        current_user.gender = payload.gender
    if payload.sexuality is not None:
        current_user.sexuality = payload.sexuality
    if payload.looking_for is not None:
        current_user.looking_for = payload.looking_for
    if payload.age_preference_min is not None:
        current_user.age_preference_min = payload.age_preference_min
    if payload.age_preference_max is not None:
        current_user.age_preference_max = payload.age_preference_max

    if payload.bio is not None and payload.bio != current_user.bio:
        current_user.bio = payload.bio
        can_regen = _try_consume_regen_slot(current_user, db)
        if can_regen:
            # Slot available — reset the avatar and queue generation.
            # Delete the old image first so it doesn't orphan in R2.
            delete_avatar(current_user.avatar_url)
            current_user.animal = None
            current_user.personality_traits = None
            current_user.avatar_description = None
            current_user.avatar_url = None
            current_user.avatar_status = AvatarStatus.pending
            current_user.avatar_status_updated_at = datetime.now(UTC)
            current_user.profile_needs_regen = False
        else:
            # No slots left — flag that the avatar no longer matches the profile
            current_user.profile_needs_regen = True
        db.commit()
        db.refresh(current_user)
        if can_regen:
            generate_avatar.delay(current_user.id)
    elif payload.bio is not None:
        # Bio sent but unchanged — still save other fields
        db.commit()
        db.refresh(current_user)
    else:
        db.commit()
        db.refresh(current_user)
    return current_user


@router.delete("/me", status_code=204)
def delete_account(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """
    Permanently delete the authenticated user's account and all associated data.

    DB-level CASCADE handles: swipes (both directions), matches, and messages.
    Avatar image file is removed from disk before the DB row is deleted.
    """
    user_id = current_user.id
    avatar_url = current_user.avatar_url

    # Remove avatar image file before deleting the row (URL is lost after deletion)
    delete_avatar(avatar_url)

    db.delete(current_user)
    db.commit()
    logger.info("delete_account: user %d permanently deleted", user_id)


@router.get("/{user_id}", response_model=PublicProfileOut)
def get_profile(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> User:
    """Another user's public profile.

    Requires authentication and returns a narrow schema — this endpoint is
    enumerable by user id, so it must never expose email or account state.
    """
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user
