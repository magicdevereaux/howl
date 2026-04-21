from datetime import datetime

from pydantic import BaseModel

from app.models.user import AvatarStatus


class AvatarStatusOut(BaseModel):
    model_config = {"from_attributes": True}

    avatar_status: AvatarStatus
    animal: str | None
    personality_traits: list[str] | None = None
    avatar_description: str | None = None
    avatar_status_updated_at: datetime | None = None
