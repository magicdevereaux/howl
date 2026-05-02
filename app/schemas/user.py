from datetime import datetime

from pydantic import BaseModel, EmailStr, field_validator

from app.models.user import AvatarStatus


class UserRegister(BaseModel):
    email: EmailStr
    password: str

    @field_validator("password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    email: str
    name: str | None = None
    age: int | None = None
    location: str | None = None
    bio: str | None
    animal: str | None
    avatar_url: str | None
    avatar_status: AvatarStatus
    created_at: datetime
    updated_at: datetime


class ProfileUpdate(BaseModel):
    name: str | None = None
    age: int | None = None
    location: str | None = None
    bio: str | None = None

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


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut
