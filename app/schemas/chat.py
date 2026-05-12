from datetime import datetime

from pydantic import BaseModel, Field


class MessageIn(BaseModel):
    content: str = Field(min_length=1, max_length=2000)


class MessageOut(BaseModel):
    id: int
    sender_id: int
    content: str
    created_at: datetime
    read_at: datetime | None = None
    is_mine: bool


class UnreadCountOut(BaseModel):
    count: int


class MessagePageOut(BaseModel):
    messages: list[MessageOut]
    has_more: bool
