from fastapi import APIRouter, Depends

from app.dependencies import get_current_user
from app.models.user import AvatarStatus, User
from app.schemas.avatar import AvatarStatusOut

router = APIRouter(prefix="/api/avatar", tags=["avatar"])


@router.get("/status", response_model=AvatarStatusOut)
def get_avatar_status(current_user: User = Depends(get_current_user)) -> User:
    return current_user
