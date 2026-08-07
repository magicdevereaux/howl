from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        Index("ix_messages_created_at", "created_at"),
        # Chat pagination and the newest-message-per-match window function in
        # app/api/users.py both filter on match_id and order by created_at.
        # Its leading column also serves every plain match_id lookup, so the
        # old single-column ix_messages_match_id is redundant and was dropped.
        Index("ix_messages_match_id_created_at", "match_id", "created_at"),
        # FK with no index: the per-sender rate-limit count in app/api/chat.py
        # and the cascade check on user deletion both scan without it.
        Index("ix_messages_sender_id", "sender_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    match_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("matches.id", ondelete="CASCADE"), nullable=False
    )
    sender_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    content: Mapped[str] = mapped_column(String(2000), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<Message id={self.id} match={self.match_id} sender={self.sender_id}>"
