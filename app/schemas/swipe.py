from datetime import datetime

from pydantic import BaseModel

from app.models.swipe import SwipeDirection


class DiscoverUserOut(BaseModel):
    """Public profile shape for GET /api/users/discover — includes id for swipe submission."""
    model_config = {"from_attributes": True}

    id: int
    name: str | None = None
    location: str | None = None
    bio: str | None = None
    animal: str | None = None
    personality_traits: list[str] | None = None
    avatar_description: str | None = None
    avatar_url: str | None = None


class MatchedProfileOut(BaseModel):
    """Minimal public profile embedded in a match response."""
    model_config = {"from_attributes": True}

    id: int
    name: str | None = None
    animal: str | None = None
    avatar_url: str | None = None
    avatar_description: str | None = None


class LastMessageOut(BaseModel):
    sender_id: int
    content: str
    created_at: datetime


class MatchOut(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    matched_at: datetime
    other_user: MatchedProfileOut
    unread_count: int = 0
    last_message: LastMessageOut | None = None


class SwipeIn(BaseModel):
    target_user_id: int
    direction: SwipeDirection


class SwipeOut(BaseModel):
    matched: bool
    match: MatchOut | None = None


class UndoSwipeOut(BaseModel):
    target_user_id: int
    direction: SwipeDirection
    user: DiscoverUserOut
