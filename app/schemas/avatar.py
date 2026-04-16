from pydantic import BaseModel

from app.models.user import AvatarStatus


class AvatarStatusOut(BaseModel):
    model_config = {"from_attributes": True}

    avatar_status: AvatarStatus
    animal: str | None
