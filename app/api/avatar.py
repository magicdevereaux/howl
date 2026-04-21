from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import get_current_user
from app.models.user import AvatarStatus, User
from app.schemas.avatar import AvatarStatusOut
from app.tasks.avatar import generate_avatar

router = APIRouter(prefix="/api/avatar", tags=["avatar"])


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

    # Clear stale avatar data and reset status
    current_user.animal = None
    current_user.personality_traits = None
    current_user.avatar_description = None
    current_user.avatar_url = None
    current_user.avatar_status = AvatarStatus.pending
    current_user.avatar_status_updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(current_user)

    generate_avatar.delay(current_user.id)

    return current_user
