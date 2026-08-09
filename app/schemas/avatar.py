from datetime import datetime

from pydantic import BaseModel

from app.models.user import AvatarStatus
from app.schemas.ai_fields import DescriptionText, TraitList


class AvatarStatusOut(BaseModel):
    model_config = {"from_attributes": True}

    avatar_status: AvatarStatus
    animal: str | None
    personality_traits: TraitList = None
    avatar_description: DescriptionText = None
    avatar_url: str | None = None
    avatar_status_updated_at: datetime | None = None
