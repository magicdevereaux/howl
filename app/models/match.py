from datetime import UTC, datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Match(Base):
    __tablename__ = "matches"
    __table_args__ = (
        UniqueConstraint("user1_id", "user2_id", name="uq_match_users"),
        # uq_match_users only prevents an exact duplicate pair; without this the
        # same two people could be matched twice as (a, b) and (b, a).  Every
        # writer already does min()/max(), so this makes the invariant the
        # database's job instead of a convention.
        CheckConstraint("user1_id < user2_id", name="ck_matches_user_order"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Canonical form: user1_id < user2_id always (enforced by ck_matches_user_order)
    user1_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user2_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    matched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )

    def __repr__(self) -> str:
        return f"<Match id={self.id} users=({self.user1_id},{self.user2_id})>"
