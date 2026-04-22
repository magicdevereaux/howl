from pydantic import BaseModel


class BrowseUserOut(BaseModel):
    """Public profile shape returned by GET /api/users/browse.

    Intentionally omits email, password_hash, id, and all auth fields.
    """
    model_config = {"from_attributes": True}

    name: str | None = None
    location: str | None = None
    bio: str | None = None
    animal: str | None = None
    personality_traits: list[str] | None = None
    avatar_description: str | None = None
    avatar_url: str | None = None
