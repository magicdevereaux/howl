from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import get_current_user
from app.models.user import AvatarStatus, User
from app.schemas.user import ProfileUpdate, UserOut
from app.tasks.avatar import generate_avatar

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


@router.get("/{user_id}", response_model=UserOut)
def get_profile(user_id: int, db: Session = Depends(get_db)) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user
