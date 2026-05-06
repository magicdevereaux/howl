from datetime import datetime

from pydantic import BaseModel


class BlockIn(BaseModel):
    blocked_id: int


class BlockedUserOut(BaseModel):
    id: int  # the blocked user's id
    name: str | None = None
    animal: str | None = None
    avatar_url: str | None = None
    blocked_at: datetime
