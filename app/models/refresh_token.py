from datetime import UTC, datetime

from sqlalchemy import Boolean, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.types import UtcDateTime


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    revoked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime,
        nullable=False,
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )

    def __repr__(self) -> str:
        return f"<RefreshToken user={self.user_id} revoked={self.revoked}>"
