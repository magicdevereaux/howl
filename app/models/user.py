import enum
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AvatarStatus(str, enum.Enum):
    pending = "pending"
    ready = "ready"
    failed = "failed"


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        # The 18+ gate, enforced in the database rather than only in
        # ProfileUpdate.validate_age.  NULL is still permitted: registration
        # only takes an email and a password, so every account starts ageless
        # and onboarding fills this in later.  See GAPS #23 — making the column
        # NOT NULL is a separate, API-level change.
        CheckConstraint(
            "age IS NULL OR (age >= 18 AND age <= 120)",
            name="ck_users_age_range",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gender: Mapped[str | None] = mapped_column(String(50), nullable=True)
    sexuality: Mapped[str | None] = mapped_column(String(50), nullable=True)
    looking_for: Mapped[str | None] = mapped_column(String(50), nullable=True)
    age_preference_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    age_preference_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    location: Mapped[str | None] = mapped_column(String(100), nullable=True)
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)
    animal: Mapped[str | None] = mapped_column(String(50), nullable=True)
    personality_traits: Mapped[list | None] = mapped_column(JSON, nullable=True)
    avatar_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    avatar_status: Mapped[AvatarStatus] = mapped_column(
        Enum(AvatarStatus, name="avatar_status", native_enum=True),
        nullable=False,
        default=AvatarStatus.pending,
        server_default=AvatarStatus.pending.value,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        server_default=func.now(),
    )
    avatar_status_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    email_notifications: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )
    is_email_verified: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    email_verification_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    email_verification_token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_bot: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        index=True,
    )
    archetype: Mapped[str | None] = mapped_column(String(50), nullable=True)
    profile_needs_regen: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    is_premium: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    avatar_regenerations_this_month: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    regenerations_reset_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    daily_swipes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    swipes_reset_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email!r} animal={self.animal!r}>"
