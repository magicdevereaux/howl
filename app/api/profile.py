import logging
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import get_current_user
from app.models.user import AvatarStatus, User
from app.schemas.user import ProfileUpdate, UserOut
from app.services.image_generation import AVATAR_DIR
from app.tasks.avatar import generate_avatar

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/profile", tags=["profile"])


@router.get("/me", response_model=UserOut)
def get_my_profile(current_user: User = Depends(get_current_user)) -> User:
    return current_user


@router.patch("/me", response_model=UserOut)
def update_my_profile(
    payload: ProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    # Name, age, and location never trigger regeneration — apply unconditionally.
    if payload.name is not None:
        current_user.name = payload.name
    if payload.age is not None:
        current_user.age = payload.age
    if payload.location is not None:
        current_user.location = payload.location

    if payload.bio is not None:
        current_user.bio = payload.bio
        # Reset avatar so it gets regenerated from the new bio
        current_user.animal = None
        current_user.personality_traits = None
        current_user.avatar_description = None
        current_user.avatar_url = None
        current_user.avatar_status = AvatarStatus.pending
        current_user.avatar_status_updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(current_user)
        generate_avatar.delay(current_user.id)
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

    # Remove avatar image file first (can't recover the path after the row is gone)
    if avatar_url:
        try:
            filename = Path(avatar_url).name
            (AVATAR_DIR / filename).unlink(missing_ok=True)
        except Exception as exc:
            # Never block deletion over a missing or unreadable file
            logger.warning("delete_account: could not remove avatar for user %d: %s", user_id, exc)

    db.delete(current_user)
    db.commit()
    logger.info("delete_account: user %d permanently deleted", user_id)


@router.get("/{user_id}", response_model=UserOut)
def get_profile(user_id: int, db: Session = Depends(get_db)) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user
