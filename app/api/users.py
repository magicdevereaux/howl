from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import get_current_user
from app.models.user import AvatarStatus, User
from app.schemas.browse import BrowseUserOut

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("/browse", response_model=list[BrowseUserOut])
def browse_users(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[User]:
    """Return all users with a ready avatar, excluding the current user."""
    users = (
        db.query(User)
        .filter(
            User.id != current_user.id,
            User.avatar_status == AvatarStatus.ready,
        )
        .order_by(User.created_at.desc())
        .all()
    )
    return users
