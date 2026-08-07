from datetime import datetime

from pydantic import BaseModel, EmailStr, field_validator, model_validator

from app.models.user import AvatarStatus


class UserRegister(BaseModel):
    email: EmailStr
    password: str

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return v.strip().lower()

    @field_validator("password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class UserLogin(BaseModel):
    email: EmailStr
    password: str

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return v.strip().lower()


class UserOut(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    email: str
    name: str | None = None
    age: int | None = None
    gender: str | None = None
    sexuality: str | None = None
    looking_for: str | None = None
    age_preference_min: int | None = None
    age_preference_max: int | None = None
    location: str | None = None
    bio: str | None
    animal: str | None
    personality_traits: list[str] | None = None
    avatar_description: str | None = None
    avatar_url: str | None
    avatar_status: AvatarStatus
    profile_needs_regen: bool = False
    is_email_verified: bool = False
    email_notifications: bool = True
    is_premium: bool = False
    daily_swipes: int = 0
    swipes_reset_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


_GENDERS = {'man', 'woman', 'non-binary', 'other'}
_SEXUALITIES = {'straight', 'gay', 'lesbian', 'bisexual', 'pansexual', 'other'}
_LOOKING_FOR = {'men', 'women', 'non-binary', 'everyone'}


class ProfileUpdate(BaseModel):
    name: str | None = None
    age: int | None = None
    gender: str | None = None
    sexuality: str | None = None
    looking_for: str | None = None
    age_preference_min: int | None = None
    age_preference_max: int | None = None
    location: str | None = None
    bio: str | None = None
    email_notifications: bool | None = None

    @field_validator("name")
    @classmethod
    def name_length(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if len(v) > 100:
            raise ValueError("Name must be at most 100 characters")
        return v or None  # treat blank string same as null

    @field_validator("age")
    @classmethod
    def validate_age(cls, v: int | None) -> int | None:
        if v is None:
            return v
        if v < 18:
            raise ValueError("Must be 18 or older")
        if v > 120:
            raise ValueError("Age must be 120 or less")
        return v

    @field_validator("gender")
    @classmethod
    def validate_gender(cls, v: str | None) -> str | None:
        if v is not None and v not in _GENDERS:
            raise ValueError(f"gender must be one of {sorted(_GENDERS)}")
        return v

    @field_validator("sexuality")
    @classmethod
    def validate_sexuality(cls, v: str | None) -> str | None:
        if v is not None and v not in _SEXUALITIES:
            raise ValueError(f"sexuality must be one of {sorted(_SEXUALITIES)}")
        return v

    @field_validator("looking_for")
    @classmethod
    def validate_looking_for(cls, v: str | None) -> str | None:
        if v is not None and v not in _LOOKING_FOR:
            raise ValueError(f"looking_for must be one of {sorted(_LOOKING_FOR)}")
        return v

    @field_validator("age_preference_min")
    @classmethod
    def validate_age_pref_min(cls, v: int | None) -> int | None:
        if v is not None and (v < 18 or v > 120):
            raise ValueError("age_preference_min must be between 18 and 120")
        return v

    @field_validator("age_preference_max")
    @classmethod
    def validate_age_pref_max(cls, v: int | None) -> int | None:
        if v is not None and (v < 18 or v > 120):
            raise ValueError("age_preference_max must be between 18 and 120")
        return v

    @model_validator(mode="after")
    def age_preference_range_ordered(self) -> "ProfileUpdate":
        """Reject an inverted age range.

        Per-field validation cannot catch this: 18 and 120 are both individually
        valid, but min=40 with max=25 matches nobody and silently empties the
        discover queue (``app/api/users.py`` ANDs the two bounds).

        Only checks the bounds present in *this* payload. A PATCH that sends one
        bound and leaves the other at its stored value can still land inverted;
        closing that needs the merge to happen against the persisted row, which
        is API-layer work.
        """
        low, high = self.age_preference_min, self.age_preference_max
        if low is not None and high is not None and low > high:
            raise ValueError(
                "age_preference_min must be less than or equal to age_preference_max"
            )
        return self

    @field_validator("location")
    @classmethod
    def location_length(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if len(v) > 100:
            raise ValueError("Location must be at most 100 characters")
        return v or None  # treat blank string same as null

    @field_validator("bio")
    @classmethod
    def bio_length(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if len(v) < 10:
            raise ValueError("Bio must be at least 10 characters")
        if len(v) > 500:
            raise ValueError("Bio must be at most 500 characters")
        return v


class PublicProfileOut(BaseModel):
    """Another user's profile, as shown in the chat profile modal.

    Deliberately narrow: never exposes email, account state (is_premium,
    is_email_verified, email_notifications), or swipe quota internals.
    """
    model_config = {"from_attributes": True}

    id: int
    name: str | None = None
    age: int | None = None
    location: str | None = None
    bio: str | None = None
    animal: str | None = None
    personality_traits: list[str] | None = None
    avatar_description: str | None = None
    avatar_url: str | None = None
    avatar_status: AvatarStatus


class AuthOut(BaseModel):
    """Response shape after login/register when tokens are delivered via httpOnly cookies."""
    user: UserOut
